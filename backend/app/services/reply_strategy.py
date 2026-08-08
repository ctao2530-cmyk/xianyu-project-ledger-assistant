from __future__ import annotations

from dataclasses import dataclass

from ..ai import AIModelSelection
from ..config import Settings
from ..database import Database
from ..models import OperationLog, ReplyStrategyPreference


VALID_MODES = {"fast", "balanced", "quality", "custom"}


class ReplyStrategyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReplyProfile:
    mode: str
    label: str
    description: str
    model: str | None
    reasoning_effort: str | None
    context_messages: int
    context_chars: int

    @property
    def selection(self) -> AIModelSelection:
        return AIModelSelection(
            model=self.model,
            reasoning_effort=self.reasoning_effort,
        )


@dataclass(frozen=True, slots=True)
class ResolvedReplyStrategy:
    mode: str
    model_selection: AIModelSelection
    context_messages: int
    context_chars: int
    escalated_for_risk: bool = False


class ReplyStrategyService:
    """Select latency/quality profiles without changing safety decisions."""

    def __init__(self, database: Database, settings: Settings, provider_name: str) -> None:
        self.database = database
        self.settings = settings
        self.provider_name = provider_name
        configured = settings.reply_speed_mode.strip().lower()
        default_mode = configured if configured in VALID_MODES else "balanced"
        if provider_name != "codex_cli":
            default_mode = "custom"
        with self.database.session() as session:
            row = session.get(ReplyStrategyPreference, 1)
            if row is None:
                row = ReplyStrategyPreference(id=1, mode=default_mode)
                session.add(row)
                session.commit()
            self._mode = row.mode if row.mode in VALID_MODES else default_mode

    def profiles(self) -> tuple[ReplyProfile, ...]:
        return (
            ReplyProfile(
                mode="fast",
                label="极速",
                description="适合在吗、价格和能否制作等日常咨询",
                model=self.settings.reply_fast_model.strip() or None,
                reasoning_effort=self.settings.reply_fast_reasoning_effort.strip() or None,
                context_messages=self.settings.reply_fast_context_messages,
                context_chars=self.settings.reply_fast_context_chars,
            ),
            ReplyProfile(
                mode="balanced",
                label="平衡",
                description="速度与上下文完整性兼顾",
                model=self.settings.reply_balanced_model.strip() or None,
                reasoning_effort=(
                    self.settings.reply_balanced_reasoning_effort.strip() or None
                ),
                context_messages=self.settings.reply_balanced_context_messages,
                context_chars=self.settings.reply_balanced_context_chars,
            ),
            ReplyProfile(
                mode="quality",
                label="高质量",
                description="适合复杂需求、报价、交付和风险内容",
                model=self.settings.reply_quality_model.strip() or None,
                reasoning_effort=(
                    self.settings.reply_quality_reasoning_effort.strip() or None
                ),
                context_messages=self.settings.codex_max_context_messages,
                context_chars=self.settings.codex_max_context_chars,
            ),
        )

    @property
    def mode(self) -> str:
        return self._mode

    def profile(self, mode: str) -> ReplyProfile | None:
        return next((profile for profile in self.profiles() if profile.mode == mode), None)

    def set_mode(self, mode: str) -> None:
        normalized = mode.strip().lower()
        if normalized not in VALID_MODES:
            raise ReplyStrategyError("不支持的回复速度模式")
        if self.provider_name != "codex_cli" and normalized != "custom":
            raise ReplyStrategyError("当前 AI Provider 仅支持自定义模式")
        with self.database.session() as session:
            row = session.get(ReplyStrategyPreference, 1)
            if row is None:
                row = ReplyStrategyPreference(id=1)
                session.add(row)
            row.mode = normalized
            session.add(
                OperationLog(
                    action="reply_strategy_changed",
                    detail=f"回复速度模式切换为 {normalized}",
                )
            )
            session.commit()
        self._mode = normalized

    def resolve(
        self,
        *,
        base_selection: AIModelSelection,
        has_local_risk: bool,
    ) -> ResolvedReplyStrategy:
        if has_local_risk and self.settings.reply_high_risk_routing_enabled:
            profile = self.profile("quality")
            assert profile
            return ResolvedReplyStrategy(
                mode="quality",
                model_selection=profile.selection,
                context_messages=profile.context_messages,
                context_chars=profile.context_chars,
                escalated_for_risk=True,
            )
        profile = self.profile(self._mode)
        if profile:
            return ResolvedReplyStrategy(
                mode=profile.mode,
                model_selection=profile.selection,
                context_messages=profile.context_messages,
                context_chars=profile.context_chars,
            )
        return ResolvedReplyStrategy(
            mode="custom",
            model_selection=base_selection,
            context_messages=self.settings.codex_max_context_messages,
            context_chars=self.settings.codex_max_context_chars,
        )


__all__ = [
    "ReplyProfile",
    "ReplyStrategyError",
    "ReplyStrategyService",
    "ResolvedReplyStrategy",
]
