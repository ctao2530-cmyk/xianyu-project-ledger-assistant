import {
  ArrowClockwise,
  BookOpenText,
  Check,
  Cpu,
  FloppyDisk,
  PencilSimple,
  Plus,
  ShieldCheck,
  Star,
  X,
} from "@phosphor-icons/react";
import { type FormEvent, useEffect, useState } from "react";
import {
  localPlatformService,
  type GlobalAgentBootstrap,
  type GlobalAgentModelOption,
  type GlobalAgentProfile,
  type GlobalAgentProvider,
} from "../data/localPlatformService";
import "./global-agent.css";


const providerLabels: Record<GlobalAgentProvider, string> = {
  codex_cli: "Codex 本机 CLI",
  deepseek: "DeepSeek",
  openai_compatible: "OpenAI Compatible",
};

interface EditorState {
  id: string | null;
  revision: number;
  provider: GlobalAgentProvider;
  model: string;
  reasoning_effort: string;
  label: string;
  enabled: boolean;
  is_default: boolean;
}

function requestId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

function editorFromProfile(profile: GlobalAgentProfile): EditorState {
  return {
    id: profile.id,
    revision: profile.revision,
    provider: profile.provider,
    model: profile.model,
    reasoning_effort: profile.reasoning_effort,
    label: profile.label,
    enabled: profile.enabled,
    is_default: profile.is_default,
  };
}

const newEditor = (): EditorState => ({
  id: null,
  revision: 0,
  provider: "codex_cli",
  model: "",
  reasoning_effort: "medium",
  label: "",
  enabled: true,
  is_default: false,
});

export function GlobalAgentSettingsCard({ onToast }: { onToast: (message: string) => void }) {
  const [bootstrap, setBootstrap] = useState<GlobalAgentBootstrap | null>(null);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [models, setModels] = useState<GlobalAgentModelOption[]>([]);
  const [busy, setBusy] = useState(false);
  const [catalogBusy, setCatalogBusy] = useState(false);
  const [error, setError] = useState("");

  const load = async () => {
    setError("");
    try {
      setBootstrap(await localPlatformService.globalAgentBootstrap());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法读取小策配置");
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const fetchModels = async () => {
    if (!editor) return;
    setCatalogBusy(true);
    setError("");
    try {
      const rows = await localPlatformService.globalAgentProviderModels(editor.provider);
      setModels(rows);
      if (!editor.model && rows[0]) {
        setEditor((current) => current ? {
          ...current,
          model: rows[0].model,
          reasoning_effort: rows[0].default_reasoning_effort || current.reasoning_effort,
        } : current);
      }
      onToast(rows.length ? `已读取 ${rows.length} 个可用模型` : "Provider 没有返回可用模型");
    } catch (reason) {
      setModels([]);
      setError(reason instanceof Error ? reason.message : "模型目录读取失败");
    } finally {
      setCatalogBusy(false);
    }
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!editor) return;
    const label = editor.label.trim();
    const model = editor.model.trim();
    if (!label || !model) {
      setError("请填写配置名称和模型标识");
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (editor.id) {
        await localPlatformService.updateGlobalAgentProfile(editor.id, {
          request_id: requestId("agent-profile-update"),
          expected_revision: editor.revision,
          model,
          reasoning_effort: editor.provider === "codex_cli" ? editor.reasoning_effort : "",
          label,
          enabled: editor.enabled,
          is_default: editor.is_default,
        });
      } else {
        await localPlatformService.createGlobalAgentProfile({
          request_id: requestId("agent-profile-create"),
          expected_revision: 0,
          provider: editor.provider,
          model,
          reasoning_effort: editor.provider === "codex_cli" ? editor.reasoning_effort : "",
          label,
          enabled: editor.enabled,
          is_default: editor.is_default,
        });
      }
      setEditor(null);
      setModels([]);
      await load();
      onToast(editor.id ? "模型配置已更新" : "模型配置已新增");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "模型配置保存失败");
    } finally {
      setBusy(false);
    }
  };

  const updateProfile = async (profile: GlobalAgentProfile, changes: Partial<Pick<GlobalAgentProfile, "enabled" | "is_default">>) => {
    setBusy(true);
    setError("");
    try {
      await localPlatformService.updateGlobalAgentProfile(profile.id, {
        request_id: requestId("agent-profile-action"),
        expected_revision: profile.revision,
        model: profile.model,
        reasoning_effort: profile.reasoning_effort,
        label: profile.label,
        enabled: changes.enabled ?? profile.enabled,
        is_default: changes.is_default ?? profile.is_default,
      });
      await load();
      onToast(changes.is_default ? "已设为小策默认模型" : changes.enabled ? "模型配置已启用" : "模型配置已停用");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "模型配置更新失败");
    } finally {
      setBusy(false);
    }
  };

  const reindex = async () => {
    setBusy(true);
    setError("");
    try {
      const knowledge = await localPlatformService.reindexGlobalAgentKnowledge(requestId("agent-knowledge-reindex"));
      setBootstrap((current) => current ? { ...current, knowledge } : current);
      onToast(`知识索引已更新：${knowledge.indexed_documents} 篇已处理`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "知识索引更新失败");
    } finally {
      setBusy(false);
    }
  };

  const profiles = bootstrap?.profiles || [];
  const knowledge = bootstrap?.knowledge;
  return <section className="global-agent-settings" aria-label="小策全局 Agent 设置">
    <header>
      <span><h3>小策 · 全局 Agent</h3><p>配置可选模型与只读知识索引。密钥继续只从本机环境读取，不在网页保存。</p></span>
      <button type="button" disabled={busy} onClick={() => { setEditor(newEditor()); setModels([]); }}><Plus size={15} />新增模型</button>
    </header>

    <div className="global-agent-settings-summary">
      <span><b>{profiles.filter((item) => item.enabled).length}</b><small>已启用模型配置</small></span>
      <span><b>{knowledge?.active_documents ?? "—"}</b><small>已批准知识笔记</small></span>
      <span><b>{knowledge?.chunks ?? "—"}</b><small>可检索知识分块</small></span>
    </div>

    <div className="global-agent-profile-list">
      {profiles.map((profile) => <article className="global-agent-profile-row" key={profile.id}>
        <span><strong>{profile.label}{profile.is_default ? " · 默认" : ""}</strong><small>{providerLabels[profile.provider]} · {profile.model}{profile.reasoning_effort ? ` · ${profile.reasoning_effort}` : ""}</small></span>
        <em className={profile.configured && profile.enabled ? "" : "is-muted"}>{!profile.enabled ? "已停用" : profile.configured ? "已配置" : "待配置"}</em>
        <div>
          {!profile.is_default && profile.enabled && <button type="button" title="设为默认" aria-label={`将 ${profile.label} 设为默认`} disabled={busy} onClick={() => void updateProfile(profile, { is_default: true })}><Star size={15} /></button>}
          <button type="button" title="编辑" aria-label={`编辑 ${profile.label}`} disabled={busy} onClick={() => { setEditor(editorFromProfile(profile)); setModels([]); }}><PencilSimple size={15} /></button>
          <button type="button" title={profile.enabled ? "停用" : "启用"} aria-label={`${profile.enabled ? "停用" : "启用"} ${profile.label}`} disabled={busy || (profile.is_default && profile.enabled)} onClick={() => void updateProfile(profile, { enabled: !profile.enabled })}>{profile.enabled ? <X size={15} /> : <Check size={15} />}</button>
        </div>
      </article>)}
    </div>

    {editor && <form className="global-agent-profile-editor" onSubmit={save}>
      <label>配置名称<input value={editor.label} onChange={(event) => setEditor({ ...editor, label: event.target.value })} placeholder="例如：Codex 深度经营分析" /></label>
      <label>Provider<select value={editor.provider} disabled={Boolean(editor.id)} onChange={(event) => { const provider = event.target.value as GlobalAgentProvider; setEditor({ ...editor, provider, reasoning_effort: provider === "codex_cli" ? "medium" : "" }); setModels([]); }}><option value="codex_cli">Codex 本机 CLI</option><option value="deepseek">DeepSeek</option><option value="openai_compatible">OpenAI Compatible</option></select></label>
      <label className="is-wide">模型标识<input list="global-agent-model-options" value={editor.model} onChange={(event) => setEditor({ ...editor, model: event.target.value })} placeholder="输入模型 ID，或读取 Provider 模型目录" /></label>
      <datalist id="global-agent-model-options">{models.map((item) => <option value={item.model} key={item.model}>{item.display_name}</option>)}</datalist>
      {editor.provider === "codex_cli" && <label>推理强度<select value={editor.reasoning_effort} onChange={(event) => setEditor({ ...editor, reasoning_effort: event.target.value })}><option value="low">low</option><option value="medium">medium</option><option value="high">high</option><option value="xhigh">xhigh</option><option value="max">max</option><option value="ultra">ultra</option></select></label>}
      <label>状态<select value={editor.enabled ? "enabled" : "disabled"} onChange={(event) => setEditor({ ...editor, enabled: event.target.value === "enabled" })}><option value="enabled">启用</option><option value="disabled">停用</option></select></label>
      <label>默认模型<select value={editor.is_default ? "default" : "optional"} onChange={(event) => setEditor({ ...editor, is_default: event.target.value === "default" })}><option value="optional">可选模型</option><option value="default">设为默认</option></select></label>
      <footer><button type="button" disabled={catalogBusy} onClick={() => void fetchModels()}><Cpu size={15} />{catalogBusy ? "读取中…" : "读取可用模型"}</button><button type="button" onClick={() => { setEditor(null); setModels([]); }}>取消</button><button type="submit" disabled={busy}><FloppyDisk size={15} />{busy ? "保存中…" : "保存配置"}</button></footer>
    </form>}

    <p className="global-agent-settings-note"><ShieldCheck size={16} weight="fill" />知识只扫描 10-Projects、20-Decisions、30-Patterns、40-Cross-Domain 和 60-Playbooks；不会读取 00-Inbox、客户图片或密钥内容。</p>
    <button type="button" disabled={busy} onClick={() => void reindex()}><BookOpenText size={16} />{busy ? "处理中…" : "人工更新已批准知识索引"}<ArrowClockwise size={14} /></button>
    {knowledge?.last_indexed_at && <small>最近索引：{new Date(knowledge.last_indexed_at).toLocaleString("zh-CN", { hour12: false })}</small>}
    {error && <p className="global-agent-settings-error" role="alert">{error}</p>}
  </section>;
}
