import {
  ArrowClockwise,
  ChatCircleDots,
  Copy,
  LinkSimple,
  ShieldCheck,
  WarningCircle,
  X,
  XCircle,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ConversationGroup } from "../data/customerConversationClient";
import {
  localPlatformService,
  type CustomerConversationAccessState,
  type CustomerContextThreadBinding,
  type CustomerContextThreadBindingList,
  type GlobalAgentCustomerContextOption,
} from "../data/localPlatformService";

const requestId = (prefix: string) => `${prefix}:${Date.now()}:${crypto.randomUUID()}`;

const formatExpiry = (value: string) => new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
}).format(new Date(value));

interface OneTimeThreadKey {
  bindingId: string;
  instruction: string;
}

export function ChatGPTConversationAccessCard({ onToast, initialConversationId, selectedGroup }: { onToast: (message: string) => void; initialConversationId?: number; selectedGroup?: ConversationGroup | null }) {
  const [conversations, setConversations] = useState<GlobalAgentCustomerContextOption[]>([]);
  const [conversationId, setConversationId] = useState(0);
  const [access, setAccess] = useState<CustomerConversationAccessState | null>(null);
  const [threadBindings, setThreadBindings] = useState<CustomerContextThreadBindingList | null>(null);
  const [oneTimeKey, setOneTimeKey] = useState<OneTimeThreadKey | null>(null);
  const [allowText, setAllowText] = useState(true);
  const [allowImages, setAllowImages] = useState(false);
  const [allowArtifacts, setAllowArtifacts] = useState(false);
  const [expiresInSeconds, setExpiresInSeconds] = useState(3600);
  const [authorizationNote, setAuthorizationNote] = useState("用于一个独立 ChatGPT 对话按需读取该客户会话，不自动分析或执行业务动作");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const accessVersion = useRef(0);
  const [confirmedScope, setConfirmedScope] = useState(false);

  const selected = useMemo(
    () => conversations.find((item) => item.conversation_id === conversationId) || null,
    [conversationId, conversations],
  );
  const activeBindings = useMemo(
    () => (threadBindings?.bindings || []).filter((item) => item.active),
    [threadBindings],
  );
  const selectedBinding = useMemo(
    () => activeBindings.find((item) => item.grant?.conversation_id === conversationId) || null,
    [activeBindings, conversationId],
  );

  const loadAccess = async (targetId: number) => {
    const version = ++accessVersion.current;
    const value = await localPlatformService.customerConversationAccess(targetId);
    if (version !== accessVersion.current) return;
    setAccess(value);
    if (value.latest_grant) {
      setAllowText(value.latest_grant.allow_text);
      setAllowImages(value.latest_grant.allow_images);
      setAllowArtifacts(value.latest_grant.allow_artifacts);
      setAuthorizationNote(value.latest_grant.authorization_note);
    }
  };

  const refreshBindings = async () => {
    const value = await localPlatformService.customerContextThreadBindings();
    setThreadBindings(value);
    return value;
  };

  useEffect(() => {
    let current = true;
    setBusy(true);
    void Promise.all([
      localPlatformService.globalAgentCustomerContextOptions(),
      localPlatformService.customerContextThreadBindings(),
    ])
      .then(async ([items, bindings]) => {
        if (!current) return;
        setConversations(items);
        setThreadBindings(bindings);
        const firstActiveConversation = bindings.bindings.find((item) => item.active)?.grant?.conversation_id;
        const firstId = initialConversationId
          ? (items.some((item) => item.conversation_id === initialConversationId) ? initialConversationId : 0)
          : firstActiveConversation || bindings.legacy_grant?.conversation_id || items[0]?.conversation_id || 0;
        if (initialConversationId && !firstId) setError("当前指定会话不在授权候选中，请核对本地会话与身份；不会替换为其他客户");
        setConversationId(firstId);
        if (firstId) await loadAccess(firstId);
      })
      .catch((reason) => current && setError(reason instanceof Error ? reason.message : "客户会话读取失败"))
      .finally(() => current && setBusy(false));
    return () => { current = false; accessVersion.current += 1; };
  }, [initialConversationId]);

  const chooseConversation = async (nextId: number) => {
    setConversationId(nextId);
    setOneTimeKey(null);
    setConfirmedScope(false);
    setAccess(null);
    setAllowText(true); setAllowImages(false); setAllowArtifacts(false);
    setBusy(true);
    setError("");
    try {
      await loadAccess(nextId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "授权状态读取失败");
    } finally {
      setBusy(false);
    }
  };

  const createBinding = async () => {
    if (!selected || !access || !confirmedScope) return;
    if (!allowText && !allowImages && !allowArtifacts) {
      setError("至少选择原始文字、归档原图或版本化成果中的一项");
      return;
    }
    if (authorizationNote.trim().length < 2) {
      setError("请填写本次授权用途");
      return;
    }
    setBusy(true);
    setError("");
    setOneTimeKey(null);
    try {
      const created = await localPlatformService.createCustomerContextThreadBinding({
        request_id: requestId("customer-thread-binding"),
        conversation_id: selected.conversation_id,
        expected_conversation_revision: access.revision,
        allow_text: allowText,
        allow_images: allowImages,
        allow_artifacts: allowArtifacts,
        allow_new_messages: true,
        expires_in_seconds: expiresInSeconds,
        authorization_note: authorizationNote.trim(),
        confirmed: true,
        ...(selectedGroup ? { group_id: selectedGroup.id, expected_group_revision: selectedGroup.revision, selected_conversation_ids: [...selectedGroup.conversation_ids] } : {}),
      });
      if (!created.context_key) throw new Error("线程上下文密钥未返回，请重新创建授权");
      const instruction = [
        "同一客户授权续期时，请继续在原 ChatGPT 对话中使用本说明，以本次 context_key 替换旧密钥；无需新建对话，也不要重置摘要或增量进度。首次绑定可使用新对话；不同客户请使用不同对话。",
        `此 ChatGPT 对话只绑定循营客户“${selected.customer_name}”。`,
        `调用循营客户上下文工具时，每次都传入 context_key：${created.context_key}`,
        "不得省略、替换或猜测 context_key，不得读取其他客户。",
      ].join("\n");
      setOneTimeKey({ bindingId: created.id, instruction });
      await Promise.all([refreshBindings(), loadAccess(selected.conversation_id)]);
      onToast("已创建独立 ChatGPT 线程授权；未调用小策或任何模型");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "线程授权创建失败");
    } finally {
      setBusy(false);
    }
  };

  const revokeBinding = async (binding: CustomerContextThreadBinding) => {
    setBusy(true);
    setError("");
    try {
      await localPlatformService.revokeCustomerContextThreadBinding(binding.id, {
        request_id: requestId("customer-thread-revoke"),
        expected_revision: binding.revision,
        reason: "用户在独立 ChatGPT 会话授权入口手动撤销",
        confirmed: true,
      });
      if (oneTimeKey?.bindingId === binding.id) setOneTimeKey(null);
      await refreshBindings();
      if (binding.grant?.conversation_id === conversationId) await loadAccess(conversationId);
      onToast("该 ChatGPT 线程读取授权已撤销");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "线程授权撤销失败");
    } finally {
      setBusy(false);
    }
  };

  const copyInstruction = async () => {
    if (!oneTimeKey) return;
    try {
      await navigator.clipboard.writeText(oneTimeKey.instruction);
      onToast("线程绑定说明已复制，请粘贴到对应的 ChatGPT 对话");
    } catch {
      setError("浏览器未允许复制，请手动选择下方说明");
    }
  };

  const conversationFor = (binding: CustomerContextThreadBinding) => conversations.find(
    (item) => item.conversation_id === binding.grant?.conversation_id,
  );

  return <section className="chatgpt-conversation-access" aria-label="ChatGPT 客户会话读取">
    <header>
      <span className="chatgpt-access-icon"><LinkSimple size={21} weight="duotone" /></span>
      <div><strong>ChatGPT 多客户线程读取</strong><small>一个客户会话对应一个 ChatGPT 对话 · 多个对话可同时有效 · 独立路径 · 不创建小策对话 · 不调用模型</small></div>
      <em className={activeBindings.length || threadBindings?.legacy_binding_active ? "is-active" : ""}>{activeBindings.length ? `${activeBindings.length} 个线程有效` : threadBindings?.legacy_binding_active ? "旧单槽有效" : "未授权"}</em>
    </header>

    <div className="chatgpt-access-flow" aria-label="独立读取流程">
      <span><i>1</i><b>选择一个客户</b><small>循营只为这个客户生成不透明密钥</small></span>
      <span><i>2</i><b>复制到一个 GPT 对话</b><small>该对话每次工具调用都携带同一密钥</small></span>
      <span><i>3</i><b>并行处理其他客户</b><small>为其他客户重复创建，不替换现有线程</small></span>
    </div>

    <div className="chatgpt-access-fields">
      <label><span>客户会话</span><select aria-label="选择 ChatGPT 读取的客户会话" value={conversationId} disabled={busy || !conversations.length || Boolean(initialConversationId)} onChange={(event) => void chooseConversation(Number(event.target.value))}>{conversations.map((item) => <option key={item.conversation_id} value={item.conversation_id}>{item.customer_name} · {item.item_title || "商品来源未知"} · {item.text_message_count} 条文字 · {item.image_message_count || 0} 条图片</option>)}</select></label>
      <label><span>有效期</span><select aria-label="ChatGPT 读取授权有效期" value={expiresInSeconds} disabled={busy} onChange={(event) => setExpiresInSeconds(Number(event.target.value))}><option value={900}>15 分钟</option><option value={3600}>1 小时</option><option value={14400}>4 小时</option><option value={86400}>24 小时</option><option value={259200}>3 天</option><option value={432000}>5 天</option><option value={604800}>7 天</option></select></label>
    </div>

    {selected ? <div className="chatgpt-access-target"><span><small>当前目标</small><b>{selected.customer_name}</b></span><span><small>关联商品</small><b>{selected.item_title || "未关联商品"}</b></span><span><small>线程状态</small><b>{selectedBinding ? `已绑定 ${selectedBinding.context_key_hint}` : "可创建新线程"}</b></span></div> : <p className="chatgpt-access-empty">当前没有可授权的客户会话（包括纯图片会话）。</p>}
    {selectedGroup && <p className="chatgpt-access-target">授权会话组「{selectedGroup.title}」版本 {selectedGroup.revision}，仅包含当前选择的 {selectedGroup.conversation_ids.length} 条会话。后续新增成员不会自动扩权。</p>}

    <fieldset disabled={busy || !selected}>
      <legend>允许此 ChatGPT 对话按需读取</legend>
      <label><input type="checkbox" checked={allowText} onChange={(event) => setAllowText(event.target.checked)} /><span><b>原始文字</b><small>默认开启；不会先调用小策总结</small></span></label>
      <label><input type="checkbox" checked={allowImages} onChange={(event) => { setAllowImages(event.target.checked); setConfirmedScope(false); }} /><span><b>图片（原图与兼容副本）</b><small>完整性核验通过后按需提供，派生预览会明确标记</small></span></label>
      <label><input type="checkbox" checked={allowArtifacts} onChange={(event) => setAllowArtifacts(event.target.checked)} /><span><b>版本化成果</b><small>只读取已经存在的需求文档与计划</small></span></label>
    </fieldset>
    <label className="customer-workflow-note"><input type="checkbox" checked={confirmedScope} disabled={busy || !selected} onChange={(event) => setConfirmedScope(event.target.checked)} />我确认允许 OpenAI 按所选范围读取{allowText && allowImages ? "文字＋图片" : allowImages ? "图片" : "文字或成果"}；这不会开启持续分析。</label>

    <label className="chatgpt-access-note"><span>本次授权用途</span><textarea rows={2} maxLength={2000} value={authorizationNote} disabled={busy || !selected} onChange={(event) => setAuthorizationNote(event.target.value)} /></label>

    {oneTimeKey && <div className="chatgpt-thread-key" role="status" aria-live="polite">
      <div><ChatCircleDots size={18} weight="duotone" /><span><b>线程绑定说明仅显示一次</b><small>复制后粘贴到为该客户新建的 ChatGPT 对话。</small></span><button type="button" aria-label="关闭一次性线程绑定说明" onClick={() => setOneTimeKey(null)}><X size={15} /></button></div>
      <pre>{oneTimeKey.instruction}</pre>
      <button type="button" onClick={() => void copyInstruction()}><Copy size={15} />复制线程绑定说明</button>
    </div>}

    <section className="chatgpt-thread-list" aria-label="有效 ChatGPT 客户线程">
      <div><strong>当前有效线程</strong><small>不同客户可同时读取；同一客户重新创建会撤销旧密钥。</small></div>
      {threadBindings?.legacy_binding_active && !activeBindings.length && <p className="is-legacy"><WarningCircle size={14} />旧单槽授权仍有效。创建首个独立客户线程后，旧单槽将停用，避免未携带密钥时读错客户。</p>}
      {activeBindings.length ? <ul>{activeBindings.map((binding) => {
        const conversation = conversationFor(binding);
        return <li key={binding.id}><span><b>{conversation?.customer_name || "客户会话"}</b><small>{binding.context_key_hint} · 有效至 {formatExpiry(binding.expires_at)}{binding.last_used_at ? " · 已读取" : " · 未读取"}</small></span><button type="button" className="outline-action" disabled={busy} onClick={() => void revokeBinding(binding)}><XCircle size={15} />撤销</button></li>;
      })}</ul> : <p>暂无有效线程授权。</p>}
    </section>

    <aside><ShieldCheck size={16} weight="fill" /><span>密钥只映射到一个已明确选择的客户会话，数据库仅保存哈希。创建授权不会向 OpenAI 发送客户内容；只有对应 ChatGPT 对话实际调用 MCP 时才读取。Tunnel 模式以密钥隔离线程，OAuth 模式还会校验用户身份。</span></aside>
    {error && <p className="chatgpt-access-error" role="alert"><WarningCircle size={15} />{error}</p>}

    <footer>
      <span><ShieldCheck size={15} />DeepSeek 不可获得此授权</span>
      <div><button type="button" className="business-primary" disabled={busy || !selected || !access || !confirmedScope || !threadBindings?.configured} onClick={() => void createBinding()}>{busy ? <><ArrowClockwise size={15} className="spin" />正在核对</> : selectedBinding ? "重新生成此客户线程" : "创建独立客户线程"}</button></div>
    </footer>
  </section>;
}
