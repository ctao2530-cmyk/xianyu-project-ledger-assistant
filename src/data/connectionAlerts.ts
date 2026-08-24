import type { AIProviderStatus, PlatformStatus } from "./localPlatformService";

export type ConnectionAlertTarget = "xianyu" | "codex_cli" | "deepseek";
export type ConnectionAlertSettingsSection = "渠道连接" | "AI与回复";

export interface ConnectionAlert {
  id: string;
  target: ConnectionAlertTarget;
  title: string;
  description: string;
  actionLabel: string;
  settingsSection: ConnectionAlertSettingsSection;
}

const transientStates = new Set([
  "",
  "checking",
  "starting",
  "connecting",
  "reconnecting",
  "unknown",
]);

const providerUnverifiedStates = new Set([
  "",
  "checking",
  "starting",
  "unknown",
]);

const xianyuFailureStates = new Set([
  "config_required",
  "login_required",
  "verification_required",
  "disconnected",
  "paused",
  "error",
  "failed",
]);

function normalized(value: string | null | undefined) {
  return String(value || "").trim().toLowerCase();
}

function xianyuAlert(status: PlatformStatus | null): ConnectionAlert | null {
  if (!status) return null;
  const state = normalized(status.listener);
  const hasExplicitFailureDetail = Boolean(String(status.listener_detail || "").trim());
  const reconnectingWithFailure = state === "reconnecting" && hasExplicitFailureDetail;
  if (
    state === "connected"
    || (transientStates.has(state) && !reconnectingWithFailure)
    || (!xianyuFailureStates.has(state) && !reconnectingWithFailure)
  ) return null;

  if (state === "config_required") {
    return {
      id: "connection-xianyu-config",
      target: "xianyu",
      title: "闲鱼连接尚未配置",
      description: "需要在本机完成凭证配置并验证后，才能恢复客户消息监听。",
      actionLabel: "去配置",
      settingsSection: "渠道连接",
    };
  }
  if (state === "login_required") {
    return {
      id: "connection-xianyu-login",
      target: "xianyu",
      title: "闲鱼登录已失效",
      description: "请使用现有浏览器重新登录，并在渠道连接中按安全流程恢复监听。",
      actionLabel: "去恢复",
      settingsSection: "渠道连接",
    };
  }
  if (state === "verification_required") {
    return {
      id: "connection-xianyu-verification",
      target: "xianyu",
      title: "闲鱼需要人工访问验证",
      description: "自动重连已经暂停，请先在 Ego Lite 完成验证，再到渠道连接手动恢复。",
      actionLabel: "去验证",
      settingsSection: "渠道连接",
    };
  }
  if (state === "paused") {
    return {
      id: "connection-xianyu-paused",
      target: "xianyu",
      title: "闲鱼消息监听已暂停",
      description: "当前不会接收新的闲鱼客户消息，可在渠道连接中恢复。",
      actionLabel: "去恢复",
      settingsSection: "渠道连接",
    };
  }
  return {
    id: "connection-xianyu-error",
    target: "xianyu",
    title: "闲鱼连接异常",
    description: "本机监听返回明确异常，请到渠道连接查看安全诊断。",
    actionLabel: "看诊断",
    settingsSection: "渠道连接",
  };
}

function codexAlert(
  status: PlatformStatus | null,
  provider: AIProviderStatus | undefined,
): ConnectionAlert | null {
  const providerState = normalized(provider?.status);
  const modelState = normalized(status?.model);

  const hasPlatformEvidence = status !== null;
  const hasProviderEvidence = provider !== undefined && !providerUnverifiedStates.has(providerState);
  if (!hasPlatformEvidence && !hasProviderEvidence) return null;

  if (status?.codex_installed === false || providerState === "not_installed") {
    return {
      id: "connection-codex-install",
      target: "codex_cli",
      title: "Codex 尚未安装",
      description: "深度草稿与需求分析暂不可用，请在 AI 与回复中查看安装指引。",
      actionLabel: "看指引",
      settingsSection: "AI与回复",
    };
  }
  if (status?.codex_logged_in === false || providerState === "login_required") {
    return {
      id: "connection-codex-login",
      target: "codex_cli",
      title: "Codex 需要重新登录",
      description: "本机 Codex 会话未就绪，请完成登录后再检查连接。",
      actionLabel: "去恢复",
      settingsSection: "AI与回复",
    };
  }
  if (providerState === "error" || modelState === "error") {
    return {
      id: "connection-codex-error",
      target: "codex_cli",
      title: "Codex 连接异常",
      description: "本机 Codex 返回明确错误，请到 AI 与回复查看诊断；不会自动切换模型。",
      actionLabel: "看诊断",
      settingsSection: "AI与回复",
    };
  }
  return null;
}

function deepseekAlert(provider: AIProviderStatus | undefined): ConnectionAlert | null {
  if (!provider) return null;
  const state = normalized(provider.status);
  if (providerUnverifiedStates.has(state)) return null;
  if (!provider.configured || state === "not_configured") {
    return {
      id: "connection-deepseek-config",
      target: "deepseek",
      title: "DeepSeek 尚未配置",
      description: "快速草稿通道暂不可用，可在 AI 与回复中完成本机配置。",
      actionLabel: "去配置",
      settingsSection: "AI与回复",
    };
  }
  if (state === "auth_failed" || state === "authentication_failed") {
    return {
      id: "connection-deepseek-auth",
      target: "deepseek",
      title: "DeepSeek 鉴权失败",
      description: "当前 API 凭证未通过验证，请在 AI 与回复中安全更新。",
      actionLabel: "去恢复",
      settingsSection: "AI与回复",
    };
  }
  if (state === "error" || state === "failed" || state === "connection_error") {
    const authenticationFailure = /鉴权|认证|401|403/i.test(provider.detail || "");
    return {
      id: authenticationFailure ? "connection-deepseek-auth" : "connection-deepseek-error",
      target: "deepseek",
      title: authenticationFailure ? "DeepSeek 鉴权失败" : "DeepSeek 连接异常",
      description: authenticationFailure
        ? "当前 API 凭证未通过验证，请在 AI 与回复中安全更新。"
        : "快速草稿通道返回明确错误，请到 AI 与回复查看诊断；不会静默切换模型。",
      actionLabel: authenticationFailure ? "去恢复" : "看诊断",
      settingsSection: "AI与回复",
    };
  }
  return null;
}

export function buildConnectionAlerts(
  status: PlatformStatus | null,
  providers: AIProviderStatus[],
): ConnectionAlert[] {
  const result: ConnectionAlert[] = [];
  const xianyu = xianyuAlert(status);
  const codexProvider = providers.find((item) => item.provider === "codex_cli");
  const deepseekProvider = providers.find((item) => item.provider === "deepseek");
  const codex = codexAlert(status, codexProvider);
  const deepseek = deepseekAlert(deepseekProvider);
  if (xianyu) result.push(xianyu);
  if (codex) result.push(codex);
  if (deepseek) result.push(deepseek);
  return result;
}
