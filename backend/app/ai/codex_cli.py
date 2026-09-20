from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import logging
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from ..config import Settings
from .base import (
    AIInput,
    AIModelOption,
    AIModelSelection,
    AIProvider,
    AIProviderError,
    AIResult,
    ProviderHealth,
)


logger = logging.getLogger(__name__)


SYSTEM_TASK = """你是闲鱼卖家的中文客服草稿助手，只负责生成草稿，不能发送消息或执行任何操作。
请严格遵守：
1. 使用自然、简洁的中文，根据商品信息和完整聊天上下文回答，避免机械化客服语气。
2. 不虚构价格、能力、优惠和完成时间；信息不足时，引导客户发送具体需求、截止时间和参考资料。
3. 不主动承诺退款、售后或交付日期；不索要密码、验证码和敏感账号信息。
4. direct、friendly、conversion 三条建议必须明显不同，每条 20 至 100 个汉字。
5. 涉及报价或改价、退款或纠纷、交付时间承诺、账号密码或验证码、站外联系方式、支付方式、自动发送消息、删除或下架商品时，risk_level 必须是 high，并写明 risk_reasons。
6. needs_human_confirmation 必须为 true。只输出符合给定 JSON Schema 的 JSON，不要 Markdown，不要解释，不要调用工具。
7. 如果输入包含 seller_style，只模仿其中的语气、长度、称呼和表达习惯；示例中的价格、日期、联系方式、能力和承诺都不是当前事实，禁止照搬。"""


HEALTH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"ok": {"type": "boolean", "const": True}},
    "required": ["ok"],
    "additionalProperties": False,
}


def codex_output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Codex strict output requires every closed-object property in required.

    Pydantic marks defaulted fields optional in JSON Schema. Make those fields
    explicit on the wire, retaining nullable unions, defaults and validators.
    Leave open dictionary schemas intact instead of silently dropping keys.
    """
    result = deepcopy(schema)

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and node.get("additionalProperties") is False:
                node["required"] = list(node.get("properties", {}))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(result)
    return result


class CodexCliProvider(AIProvider):
    name = "codex_cli"

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._command_path: str | None = None
        self._supports_schema = False
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._process_lock = asyncio.Lock()
        self._process_slots = asyncio.Semaphore(settings.codex_max_concurrency)
        # Reply drafts use the shared pool directly. Long-form structured jobs
        # (currently requirement documents) are limited so that, with two or
        # more slots, at least one Codex process remains available to replies.
        self._structured_slots = asyncio.Semaphore(
            max(1, settings.codex_max_concurrency - 1)
        )
        self._catalog_lock = asyncio.Lock()
        self._model_catalog: list[AIModelOption] = []
        self._model_catalog_checked_at = 0.0
        self.configure_model(
            AIModelSelection(
                model=settings.codex_model.strip() or None,
                reasoning_effort=settings.codex_reasoning_effort.strip() or None,
            )
        )

    def _resolve_command(self) -> str | None:
        configured = self.settings.codex_command.strip()
        if not configured:
            return None
        path = shutil.which(configured)
        if path:
            return path
        candidate = Path(configured).expanduser()
        return str(candidate) if candidate.is_file() else None

    def _effective_timeout(self, timeout: float | None) -> float:
        """Keep deep Codex jobs independent from fast-provider deadlines."""
        if timeout is None:
            return self.settings.codex_timeout_seconds
        return max(timeout, self.settings.codex_timeout_seconds)

    async def _run_probe(
        self,
        *args: str,
        timeout: float = 15,
        max_output_chars: int = 20_000,
    ) -> tuple[int, str, str]:
        if not self._command_path:
            raise AIProviderError(
                "codex_not_installed",
                "未找到 Codex CLI",
                repair_command="npm install -g @openai/codex",
            )
        try:
            process = await asyncio.create_subprocess_exec(
                self._command_path,
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise AIProviderError("codex_probe_timeout", "Codex 环境检查超时") from exc
        except OSError as exc:
            raise AIProviderError(
                "codex_not_installed",
                "无法启动 Codex CLI",
                repair_command="npm install -g @openai/codex",
            ) from exc
        return (
            process.returncode or 0,
            stdout.decode("utf-8", errors="replace")[:max_output_chars],
            stderr.decode("utf-8", errors="replace")[:max_output_chars],
        )

    @staticmethod
    def _parse_model_catalog(content: str) -> list[AIModelOption]:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AIProviderError("codex_models_invalid", "Codex 模型目录格式无效") from exc
        rows = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise AIProviderError("codex_models_invalid", "Codex 模型目录缺少 models 字段")

        result: list[AIModelOption] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict) or row.get("visibility") != "list":
                continue
            model = str(row.get("slug") or "").strip()
            # The raw catalog may contain internal aliases such as
            # codex-auto-review. Only expose user-selectable GPT model slugs.
            if not model.startswith("gpt-") or model in seen:
                continue
            efforts = tuple(
                str(entry.get("effort"))
                for entry in row.get("supported_reasoning_levels", [])
                if isinstance(entry, dict) and entry.get("effort")
            )
            default_effort = str(row.get("default_reasoning_level") or "").strip() or None
            result.append(
                AIModelOption(
                    model=model,
                    display_name=str(row.get("display_name") or model),
                    default_reasoning_effort=default_effort,
                    supported_reasoning_efforts=efforts,
                )
            )
            seen.add(model)
        if not result:
            raise AIProviderError("codex_models_empty", "Codex 当前账号没有可选择的 GPT 模型")
        return result

    async def available_models(self, *, refresh: bool = False) -> list[AIModelOption]:
        async with self._catalog_lock:
            if (
                not refresh
                and self._model_catalog
                and time.monotonic() - self._model_catalog_checked_at < 600
            ):
                return list(self._model_catalog)
            if not self._command_path:
                self._command_path = self._resolve_command()
            code, output, _error = await self._run_probe(
                "debug",
                "models",
                timeout=20,
                max_output_chars=2_000_000,
            )
            if code != 0:
                raise AIProviderError("codex_models_failed", "无法读取 Codex 模型目录")
            models = self._parse_model_catalog(output)
            self._model_catalog = models
            self._model_catalog_checked_at = time.monotonic()
            return list(models)

    async def healthcheck(self, *, validate_execution: bool = True) -> ProviderHealth:
        self.health = ProviderHealth(status="checking", detail="正在检查 Codex CLI")
        self._command_path = self._resolve_command()
        if not self._command_path:
            self.health = ProviderHealth(
                status="not_installed",
                detail="未找到 Codex CLI，请安装后重启后端",
                installed=False,
                logged_in=False,
                repair_command="npm install -g @openai/codex",
                checked_at=datetime.now(timezone.utc),
            )
            return self.health

        try:
            help_code, help_output, help_error = await self._run_probe("exec", "--help")
            if help_code != 0:
                raise AIProviderError("codex_help_failed", "无法读取 codex exec 帮助")
            self._supports_schema = "--output-schema" in (help_output + help_error)

            login_code, login_output, login_error = await self._run_probe("login", "status")
            login_text = (login_output + login_error).lower()
            if login_code != 0 or "logged in" not in login_text:
                self.health = ProviderHealth(
                    status="login_required",
                    detail="Codex 尚未登录或登录已失效",
                    installed=True,
                    logged_in=False,
                    repair_command="codex login",
                    checked_at=datetime.now(timezone.utc),
                )
                return self.health

            if validate_execution:
                output = await self._invoke(
                    "只返回 {\"ok\": true}，不要解释，也不要调用工具。",
                    schema=HEALTH_SCHEMA,
                    task_key="healthcheck",
                    timeout=self.settings.codex_timeout_seconds,
                )
                parsed = self._extract_json(output)
                if parsed != {"ok": True}:
                    raise AIProviderError("codex_execution_invalid", "Codex 执行检查返回异常")

            self.health = ProviderHealth(
                status="connected",
                detail=(
                    "Codex CLI 已安装、已登录且可执行"
                    if validate_execution
                    else "Codex CLI 已安装并已登录"
                ),
                installed=True,
                logged_in=True,
                checked_at=datetime.now(timezone.utc),
            )
        except AIProviderError as exc:
            self.health = ProviderHealth(
                status="error",
                detail=exc.safe_message,
                installed=True,
                logged_in=True,
                repair_command=exc.repair_command,
                checked_at=datetime.now(timezone.utc),
            )
        return self.health

    def _command_args(
        self,
        workdir: Path,
        schema_file: Path,
        output_file: Path,
        model_selection: AIModelSelection | None = None,
        *,
        repository_scope: Path | None = None,
    ) -> list[str]:
        assert self._command_path
        args = [
            self._command_path,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--color",
            "never",
            "--cd",
            str(workdir),
        ]
        if repository_scope is None:
            args.extend(["--sandbox", "read-only"])
        if self.settings.codex_ignore_user_config or repository_scope is not None:
            args.append("--ignore-user-config")
        if self.settings.codex_ignore_rules or repository_scope is not None:
            args.append("--ignore-rules")
        if repository_scope is not None:
            # Permission profiles and the legacy --sandbox flag are mutually
            # exclusive. Deny the filesystem by default, reopen only Codex's
            # minimal runtime paths and the explicitly approved repository,
            # and keep command network access disabled.
            scope = json.dumps(str(repository_scope))
            args.extend(
                [
                    "--strict-config",
                    "--config",
                    'default_permissions="repository_planning"',
                    "--config",
                    (
                        'permissions.repository_planning.filesystem={'
                        '":root"="deny",'
                        '":minimal"="read",'
                        '":workspace_roots"={"."="read"}'
                        "}"
                    ),
                    "--config",
                    f"permissions.repository_planning.workspace_roots={{{scope}=true}}",
                    "--config",
                    "permissions.repository_planning.network={enabled=false}",
                ]
            )
        selection = model_selection or self.model_selection
        if selection.model:
            args.extend(["--model", selection.model])
        if selection.reasoning_effort:
            effort = json.dumps(selection.reasoning_effort)
            args.extend(["--config", f"model_reasoning_effort={effort}"])
        if self._supports_schema:
            args.extend(["--output-schema", str(schema_file)])
        args.extend(["--output-last-message", str(output_file), "-"])
        return args

    async def _invoke(
        self,
        prompt: str,
        *,
        schema: dict[str, Any],
        task_key: str,
        timeout: float | None = None,
        model_selection: AIModelSelection | None = None,
    ) -> str:
        async with self._process_slots:
            return await self._invoke_process(
                prompt,
                schema=schema,
                task_key=task_key,
                timeout=timeout,
                model_selection=model_selection,
            )

    async def _invoke_in_workspace(
        self,
        prompt: str,
        *,
        workspace: Path,
        schema: dict[str, Any],
        task_key: str,
        timeout: float | None = None,
        model_selection: AIModelSelection | None = None,
    ) -> str:
        async with self._process_slots:
            return await self._invoke_process(
                prompt,
                schema=schema,
                task_key=task_key,
                timeout=timeout,
                model_selection=model_selection,
                workspace=workspace,
            )

    async def _invoke_process(
        self,
        prompt: str,
        *,
        schema: dict[str, Any],
        task_key: str,
        timeout: float | None = None,
        model_selection: AIModelSelection | None = None,
        workspace: Path | None = None,
    ) -> str:
        if not self._command_path:
            raise AIProviderError(
                "codex_not_installed",
                "未找到 Codex CLI",
                repair_command="npm install -g @openai/codex",
            )
        started = time.monotonic()
        effective_timeout = self._effective_timeout(timeout)
        selection = model_selection or self.model_selection
        with tempfile.TemporaryDirectory(prefix="xianyu-codex-") as temp_dir:
            artifact_dir = Path(temp_dir)
            workdir = workspace or artifact_dir
            schema_file = artifact_dir / "reply-schema.json"
            output_file = artifact_dir / "reply.json"
            schema_file.write_text(json.dumps(codex_output_schema(schema), ensure_ascii=False), encoding="utf-8")
            args = self._command_args(
                workdir,
                schema_file,
                output_file,
                model_selection=model_selection,
                repository_scope=workspace,
            )
            try:
                process = await asyncio.create_subprocess_exec(
                    *args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except OSError as exc:
                raise AIProviderError(
                    "codex_not_installed",
                    "无法启动 Codex CLI",
                    repair_command="npm install -g @openai/codex",
                ) from exc
            async with self._process_lock:
                self._processes[task_key] = process
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(prompt.encode("utf-8")),
                    timeout=effective_timeout,
                )
            except asyncio.TimeoutError as exc:
                process.kill()
                await process.wait()
                logger.warning(
                    "Codex 进程超时 task=%s model=%s duration_ms=%s",
                    task_key,
                    selection.model or "default",
                    int((time.monotonic() - started) * 1000),
                )
                raise AIProviderError(
                    "codex_timeout",
                    f"Codex 生成超时（{int(effective_timeout)} 秒）",
                    retryable=True,
                ) from exc
            except asyncio.CancelledError:
                if process.returncode is None:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=3)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
                raise
            finally:
                async with self._process_lock:
                    self._processes.pop(task_key, None)

            stderr_text = stderr.decode("utf-8", errors="replace")
            if process.returncode != 0:
                logger.warning(
                    "Codex 进程失败 task=%s model=%s duration_ms=%s exit_code=%s",
                    task_key,
                    selection.model or "default",
                    int((time.monotonic() - started) * 1000),
                    process.returncode,
                )
                raise self._classify_failure(stderr_text)
            if output_file.exists():
                output = output_file.read_text(encoding="utf-8").strip()
            else:
                output = stdout.decode("utf-8", errors="replace").strip()
            if not output:
                raise AIProviderError("codex_empty_output", "Codex 未返回内容", retryable=True)
            logger.info(
                "Codex 进程完成 task=%s model=%s duration_ms=%s exit_code=0",
                task_key,
                selection.model or "default",
                int((time.monotonic() - started) * 1000),
            )
            return output

    def _classify_failure(self, stderr: str) -> AIProviderError:
        lowered = stderr.lower()
        if any(marker in lowered for marker in ("not logged in", "login required", "unauthorized")):
            return AIProviderError(
                "codex_login_required",
                "Codex 登录已失效",
                repair_command="codex login",
            )
        if any(marker in lowered for marker in ("usage limit", "rate limit", "quota", "credits")):
            return AIProviderError(
                "codex_quota_unavailable",
                "Codex 账号额度暂时不可用，请稍后手动重试",
                retryable=True,
            )
        if any(
            marker in lowered
            for marker in (
                "connection refused",
                "connection timed out",
                "failed to connect",
                "error sending request",
                "stream disconnected before completion",
                "network is unreachable",
            )
        ):
            return AIProviderError(
                "codex_network_unavailable",
                "Codex 已登录，但当前无法连接 ChatGPT；请检查网络或本机代理后重试",
                retryable=True,
            )
        return AIProviderError("codex_process_failed", "Codex 进程执行失败", retryable=True)

    @staticmethod
    def _extract_json(content: str) -> dict[str, Any]:
        stripped = content.strip()
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        start = stripped.find("{")
        while start >= 0:
            depth = 0
            in_string = False
            escaped = False
            for index in range(start, len(stripped)):
                char = stripped[index]
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue
                if char == '"':
                    in_string = True
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            parsed = json.loads(stripped[start : index + 1])
                        except json.JSONDecodeError:
                            break
                        if isinstance(parsed, dict):
                            return parsed
                        break
            start = stripped.find("{", start + 1)
        raise AIProviderError("codex_invalid_json", "Codex 返回内容不是有效 JSON", retryable=True)

    async def generate(
        self,
        payload: AIInput,
        *,
        task_key: str,
        model_selection: AIModelSelection | None = None,
    ) -> AIResult:
        schema = AIResult.model_json_schema()
        context_json = payload.model_dump_json()
        prompt = f"{SYSTEM_TASK}\n\n以下是本次输入 JSON：\n{context_json}"
        last_error: AIProviderError | None = None
        for attempt in range(2):
            attempt_prompt = prompt
            if attempt:
                attempt_prompt += "\n\n上次输出未通过 JSON 校验。请重新生成完整 JSON，不能省略字段。"
            try:
                output = await self._invoke(
                    attempt_prompt,
                    schema=schema,
                    task_key=task_key,
                    model_selection=model_selection,
                )
                parsed = self._extract_json(output)
                result = AIResult.model_validate(parsed).with_enforced_risks(payload)
                self.health = ProviderHealth(
                    status="connected",
                    detail="Codex CLI 调用正常",
                    installed=True,
                    logged_in=True,
                    checked_at=datetime.now(timezone.utc),
                )
                return result
            except ValidationError as exc:
                last_error = AIProviderError(
                    "codex_invalid_response",
                    "Codex 返回 JSON 字段或长度不符合要求",
                    retryable=True,
                )
                logger.warning("Codex 结构化结果校验失败（第 %d 次）", attempt + 1)
            except AIProviderError as exc:
                last_error = exc
                if exc.code not in {"codex_invalid_json", "codex_empty_output"}:
                    break
                logger.warning("Codex 返回格式无效（第 %d 次）", attempt + 1)
        assert last_error
        if last_error.code in {"codex_login_required", "codex_not_installed"}:
            self.health = ProviderHealth(
                status="login_required" if last_error.code == "codex_login_required" else "not_installed",
                detail=last_error.safe_message,
                installed=last_error.code != "codex_not_installed",
                logged_in=False,
                repair_command=last_error.repair_command,
                checked_at=datetime.now(timezone.utc),
            )
        raise last_error

    async def generate_structured(
        self,
        prompt: str,
        *,
        result_type: type[BaseModel],
        task_key: str,
        model_selection: AIModelSelection | None = None,
        timeout: float | None = None,
    ) -> BaseModel:
        """Run Codex with schema output and one bounded repair attempt."""
        async with self._structured_slots:
            return await self._generate_structured_inner(
                prompt,
                result_type=result_type,
                task_key=task_key,
                model_selection=model_selection,
                timeout=timeout,
            )

    async def generate_structured_in_workspace(
        self,
        prompt: str,
        *,
        workspace: Path,
        result_type: type[BaseModel],
        task_key: str,
        model_selection: AIModelSelection | None = None,
        timeout: float | None = None,
    ) -> BaseModel:
        """Run one schema-constrained planning job in an approved read-only repo."""
        resolved = workspace.expanduser().resolve(strict=True)
        if not resolved.is_dir():
            raise AIProviderError("codex_workspace_invalid", "绑定的代码仓库目录不存在")
        async with self._structured_slots:
            last_error: AIProviderError | None = None
            for attempt in range(2):
                attempt_prompt = prompt
                if attempt:
                    attempt_prompt += (
                        "\n\n上次输出未通过 JSON Schema 校验。"
                        "请重新输出完整 JSON，不得省略任何必填字段。"
                    )
                try:
                    output = await self._invoke_in_workspace(
                        attempt_prompt,
                        workspace=resolved,
                        schema=result_type.model_json_schema(),
                        task_key=task_key,
                        timeout=timeout,
                        model_selection=model_selection,
                    )
                    return result_type.model_validate(self._extract_json(output))
                except ValidationError:
                    last_error = AIProviderError(
                        "codex_invalid_response",
                        "Codex 返回 JSON 字段不符合开发计划结构",
                        retryable=True,
                    )
                except AIProviderError as exc:
                    last_error = exc
                    if exc.code not in {
                        "codex_invalid_json",
                        "codex_empty_output",
                        "codex_invalid_response",
                    }:
                        break
            assert last_error
            raise last_error

    async def _generate_structured_inner(
        self,
        prompt: str,
        *,
        result_type: type[BaseModel],
        task_key: str,
        model_selection: AIModelSelection | None = None,
        timeout: float | None = None,
    ) -> BaseModel:
        last_error: AIProviderError | None = None
        for attempt in range(2):
            attempt_prompt = prompt
            if attempt:
                attempt_prompt += (
                    "\n\n上次输出未通过 JSON Schema 校验。"
                    "请重新输出完整 JSON，不得省略任何必填字段。"
                )
            try:
                output = await self._invoke(
                    attempt_prompt,
                    schema=result_type.model_json_schema(),
                    task_key=task_key,
                    timeout=timeout,
                    model_selection=model_selection,
                )
                parsed = self._extract_json(output)
                result = result_type.model_validate(parsed)
                self.health = ProviderHealth(
                    status="connected",
                    detail="Codex CLI 调用正常",
                    installed=True,
                    logged_in=True,
                    checked_at=datetime.now(timezone.utc),
                )
                return result
            except ValidationError:
                last_error = AIProviderError(
                    "codex_invalid_response",
                    "Codex 返回 JSON 字段不符合需求文档结构",
                    retryable=True,
                )
                logger.warning("Codex 通用结构化结果校验失败（第 %d 次）", attempt + 1)
            except AIProviderError as exc:
                last_error = exc
                if exc.code not in {
                    "codex_invalid_json",
                    "codex_empty_output",
                    "codex_invalid_response",
                }:
                    break
                logger.warning("Codex 通用结构化输出无效（第 %d 次）", attempt + 1)
        assert last_error
        raise last_error

    async def cancel(self, task_key: str) -> None:
        async with self._process_lock:
            process = self._processes.get(task_key)
            if process and process.returncode is None:
                process.terminate()

    async def close(self) -> None:
        async with self._process_lock:
            processes = list(self._processes.values())
        for process in processes:
            if process.returncode is None:
                process.terminate()
