import {
  ArrowClockwise,
  CheckCircle,
  Copy,
  Eye,
  EyeSlash,
  Key,
  LockKey,
  PlugsConnected,
  ShieldCheck,
  TerminalWindow,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  localPlatformService,
  type ConnectionRecoveryResult,
  type ConnectionRecoveryTarget,
} from "../data/localPlatformService";

interface CurrentConnectionState {
  status: string;
  detail: string;
  configured: boolean;
}

interface ConnectionRecoveryDrawerProps {
  target: ConnectionRecoveryTarget;
  current: CurrentConnectionState;
  onClose: () => void;
  onRecovered: (result: ConnectionRecoveryResult) => void;
  onToast: (message: string) => void;
}

const targetMeta = {
  xianyu: {
    eyebrow: "CHANNEL RECOVERY",
    title: "恢复闲鱼连接",
    description: "验证新 Cookie 后再写入本机配置，并重新建立消息监听。",
    fieldLabel: "完整 Cookie",
    placeholder: "粘贴 Ego Lite 请求头中的完整 Cookie",
    submitLabel: "验证并恢复闲鱼",
    Icon: PlugsConnected,
  },
  deepseek: {
    eyebrow: "MODEL RECOVERY",
    title: "更新 DeepSeek 连接",
    description: "先通过官方 /models 验证候选 Key，成功后才替换本机配置。",
    fieldLabel: "DeepSeek API Key",
    placeholder: "粘贴新的 API Key",
    submitLabel: "验证并更新 Key",
    Icon: Key,
  },
  codex_cli: {
    eyebrow: "CODEX RECOVERY",
    title: "检查 Codex 登录",
    description: "登录在本机终端完成，网页不会要求 ChatGPT 密码或 Token。",
    fieldLabel: "",
    placeholder: "",
    submitLabel: "重新检测 Codex",
    Icon: TerminalWindow,
  },
} as const;

const focusableSelector = [
  "button:not([disabled])",
  "input:not([disabled])",
  "[href]",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

export function ConnectionRecoveryDrawer({
  target,
  current,
  onClose,
  onRecovered,
  onToast,
}: ConnectionRecoveryDrawerProps) {
  const meta = targetMeta[target];
  const drawerRef = useRef<HTMLElement>(null);
  const credentialRef = useRef<HTMLInputElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const busyRef = useRef(false);
  const onCloseRef = useRef(onClose);
  const [credential, setCredential] = useState("");
  const [revealed, setRevealed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ConnectionRecoveryResult | null>(null);

  useEffect(() => {
    busyRef.current = busy;
    onCloseRef.current = onClose;
  }, [busy, onClose]);

  useEffect(() => {
    setCredential("");
    setRevealed(false);
    setError("");
    setResult(null);
  }, [target]);

  const displayed = result || current;
  const statusReady = displayed.status === "connected";
  const verificationRequired = displayed.status === "verification_required";
  const statusLabel = statusReady
    ? "连接正常"
    : verificationRequired
      ? "等待人工验证"
    : displayed.status === "checking" || displayed.status === "connecting" || displayed.status === "reconnecting"
      ? "正在检查"
      : "需要处理";

  const instructions = useMemo(() => {
    if (target === "xianyu") {
      return [
        "在现有 Ego Lite 闲鱼页面完成访问验证，并确认商品页可以正常打开。",
        "从开发者工具 Network 的闲鱼请求头复制完整 Cookie，不需要打开第二个网站。",
        "粘贴后只执行一次只读验证；失败会保持暂停且不会覆盖原配置。",
      ];
    }
    if (target === "deepseek") {
      return [
        "粘贴 DeepSeek 控制台生成的 API Key。",
        "本机服务使用候选 Key 访问官方 /models，不发送客户对话。",
        "验证成功后原子更新 .env，新的草稿任务立即使用该连接。",
      ];
    }
    return [
      "复制下方命令并在本机终端执行。",
      "按 Codex 提示完成 ChatGPT 登录，凭证由 Codex 自己管理。",
      "返回这里点击“重新检测 Codex”，不会自动切换到其他模型。",
    ];
  }, [target]);

  useEffect(() => {
    returnFocusRef.current = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const frame = window.requestAnimationFrame(() => {
      if (target !== "codex_cli") credentialRef.current?.focus();
      else drawerRef.current?.focus();
    });
    const onKeyDown = (event: KeyboardEvent) => {
      const drawer = drawerRef.current;
      if (event.key === "Escape" && !busyRef.current) {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !drawer) return;
      const focusable = Array.from(drawer.querySelectorAll<HTMLElement>(focusableSelector));
      if (!focusable.length) {
        event.preventDefault();
        drawer.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === drawer)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", onKeyDown);
      returnFocusRef.current?.focus();
    };
  }, [target]);

  const complete = (next: ConnectionRecoveryResult) => {
    setCredential("");
    setRevealed(false);
    setResult(next);
    setError("");
    onRecovered(next);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (target !== "codex_cli" && !credential.trim()) {
      setError(target === "xianyu" ? "请先粘贴完整 Cookie" : "请先粘贴 API Key");
      return;
    }
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const next = target === "xianyu"
        ? await localPlatformService.recoverXianyu(credential)
        : target === "deepseek"
          ? await localPlatformService.recoverDeepSeek(credential)
          : await localPlatformService.checkCodexConnection();
      complete(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "连接恢复失败，请重试");
    } finally {
      setBusy(false);
    }
  };

  const reloadLocalConfig = async () => {
    if (target === "codex_cli") return;
    setBusy(true);
    setError("");
    setResult(null);
    try {
      complete(await localPlatformService.reloadConnection(target));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "本机配置重新读取失败");
    } finally {
      setBusy(false);
    }
  };

  const copyCodexLogin = async () => {
    try {
      await navigator.clipboard.writeText("codex login");
      onToast("Codex 登录命令已复制");
    } catch {
      onToast("复制失败，请手动输入 codex login");
    }
  };

  const Icon = meta.Icon;
  return <div className="connection-recovery-layer">
    <button className="connection-recovery-scrim" type="button" aria-label="关闭连接恢复" disabled={busy} onClick={onClose} />
    <aside ref={drawerRef} className="connection-recovery-drawer" role="dialog" aria-modal="true" aria-labelledby="connection-recovery-title" tabIndex={-1}>
      <form onSubmit={submit}>
        <header>
          <span className="connection-recovery-icon"><Icon size={22} weight="duotone" /></span>
          <div><small>{meta.eyebrow}</small><h2 id="connection-recovery-title">{meta.title}</h2><p>{meta.description}</p></div>
          <button type="button" aria-label="关闭" disabled={busy} onClick={onClose}><X size={19} /></button>
        </header>

        <div className="connection-recovery-body">
          <section className={`connection-current-state ${statusReady ? "is-ready" : "is-warning"}`}>
            <i>{statusReady ? <CheckCircle size={19} weight="fill" /> : <WarningCircle size={19} weight="fill" />}</i>
            <span><small>当前状态</small><b>{statusLabel}</b><p>{displayed.detail}</p></span>
            <em>{displayed.configured ? "已配置" : "未配置"}</em>
          </section>

          <section className="connection-recovery-steps">
            <h3>恢复步骤</h3>
            <ol>{instructions.map((instruction, index) => <li key={instruction}><i>{index + 1}</i><span>{instruction}</span></li>)}</ol>
          </section>

          {target === "codex_cli" ? <section className="codex-login-command">
            <span><TerminalWindow size={18} weight="duotone" /><code>codex login</code></span>
            <button type="button" onClick={() => void copyCodexLogin()}><Copy size={16} />复制命令</button>
          </section> : <label className="connection-secret-field">
            <span>{meta.fieldLabel}<small>不会保存到浏览器、SQLite 或业务日志</small></span>
            <div>
              <LockKey size={18} weight="duotone" />
              <input
                ref={credentialRef}
                type={revealed ? "text" : "password"}
                autoComplete="off"
                spellCheck={false}
                value={credential}
                onChange={(event) => setCredential(event.target.value)}
                placeholder={meta.placeholder}
                aria-label={meta.fieldLabel}
              />
              <button type="button" aria-label={revealed ? "隐藏凭证" : "显示凭证"} onClick={() => setRevealed((value) => !value)}>{revealed ? <EyeSlash size={17} /> : <Eye size={17} />}</button>
            </div>
          </label>}

          <p className="connection-security-note"><ShieldCheck size={17} weight="fill" />候选凭证先由本机后端验证。验证失败不会写入 `.env`，网页也不会读取 Ego Lite 密码、ChatGPT 密码或系统钥匙串。</p>

          {error && <p className="connection-recovery-feedback is-error" role="alert"><WarningCircle size={17} weight="fill" />{error}</p>}
          {result && <p className={`connection-recovery-feedback ${result.status === "connected" ? "is-success" : "is-warning"}`} role="status">{result.status === "connected" ? <CheckCircle size={17} weight="fill" /> : <ArrowClockwise size={17} />}{result.detail}</p>}
        </div>

        <footer>
          {target === "codex_cli" ? <button type="button" className="connection-secondary-action" onClick={() => void copyCodexLogin()}><Copy size={16} />复制登录命令</button> : <button type="button" className="connection-secondary-action" disabled={busy} onClick={() => void reloadLocalConfig()}><ArrowClockwise size={16} />重新读取本机配置</button>}
          <button type="submit" className="connection-primary-action" disabled={busy}>{busy ? <><ArrowClockwise className="spin" size={17} />正在安全验证…</> : <><PlugsConnected size={17} weight="fill" />{meta.submitLabel}</>}</button>
        </footer>
      </form>
    </aside>
  </div>;
}
