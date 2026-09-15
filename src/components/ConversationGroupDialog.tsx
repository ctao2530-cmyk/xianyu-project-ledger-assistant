import { useEffect, useRef, useState } from "react";
import { localPlatformService } from "../data/localPlatformService";
import type { ConversationGroup, ConversationGroupCandidate, ConversationGroupPreview, ConversationGroupChange } from "../data/customerConversationClient";
import { CustomerWorkflowDialog } from "./CustomerWorkflowDialog";

export function ConversationGroupDialog({ conversationId, onClose, onChanged }: { conversationId: number; onClose: () => void; onChanged: (group: ConversationGroup) => void }) {
  const [candidates, setCandidates] = useState<ConversationGroupCandidate[]>([]);
  const [groups, setGroups] = useState<ConversationGroup[]>([]);
  const [groupId, setGroupId] = useState("");
  const [selected, setSelected] = useState<number[]>([conversationId]);
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<ConversationGroupPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const request = useRef("");
  const group = groups.find((item) => item.id === groupId);
  useEffect(() => {
    let live = true;
    setBusy(true);
    void localPlatformService.conversationGroupCandidates(conversationId).then((result) => {
      if (!live) return;
      setCandidates(result.candidates); setGroups(result.groups);
      const existing = result.groups.find((item) => item.active && item.conversation_ids.includes(conversationId));
      if (existing) { setGroupId(existing.id); setSelected(existing.conversation_ids); }
    }).catch((e) => { if (live) setError(e instanceof Error ? e.message : "会话范围读取失败"); }).finally(() => { if (live) setBusy(false); });
    return () => { live = false; };
  }, [conversationId]);
  const invalidate = () => { setPreview(null); request.current = ""; };
  const payload = (): ConversationGroupChange => ({ anchor_conversation_id: conversationId, conversation_ids: selected, group_id: groupId || undefined, expected_revision: group?.revision || 0, title: "合并会话", reason: reason.trim(), request_id: request.current });
  const act = async () => {
    setBusy(true); setError("");
    try {
      if (!preview) { request.current ||= crypto.randomUUID(); setPreview(await localPlatformService.previewConversationGroup(payload())); }
      else { const saved = await localPlatformService.commitConversationGroup({ ...payload(), preview_token: preview.preview_token, request_id: request.current, confirmed: true }); onChanged(saved); onClose(); }
    } catch (e) { setError(e instanceof Error ? e.message : "会话合并失败"); setPreview(null); }
    finally { setBusy(false); }
  };
  return <CustomerWorkflowDialog title="合并会话" onClose={onClose}>
    <p className="customer-workflow-note">仅显示稳定平台身份或已确认客户关联一致的会话。原消息、图片和商品归属均保留。</p>
    <label className="customer-workflow-field">会话组<select value={groupId} disabled={busy} onChange={(event) => { const next = groups.find((item) => item.id === event.target.value); setGroupId(next?.id || ""); setSelected(next?.conversation_ids || [conversationId]); invalidate(); }}><option value="">创建新组</option>{groups.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
    <fieldset className="conversation-group-choices" disabled={busy}><legend>选择商品会话</legend>{candidates.map((item) => <label key={item.id}><input type="checkbox" checked={selected.includes(item.id)} onChange={(event) => { setSelected((ids) => event.target.checked ? [...ids, item.id] : ids.filter((id) => id !== item.id)); invalidate(); }} /><span><b>{item.item_title || "商品来源未知"}</b><small>{item.customer_name} · {item.channel} · {item.identity_basis === "platform_id" ? "平台身份一致" : "人工确认关联"}</small></span></label>)}</fieldset>
    <label className="customer-workflow-field">修改原因<input value={reason} maxLength={500} placeholder="例如：统一查看同一客户的商品需求" disabled={busy} onChange={(event) => { setReason(event.target.value); invalidate(); }} /></label>
    {group && <button type="button" className="customer-workflow-secondary" disabled={busy} onClick={() => { setSelected([]); invalidate(); }}>取消合并，保留所有原会话</button>}
    {preview && <section className="conversation-group-preview" aria-label="合并范围预览"><b>{preview.conversation_ids.length ? `确认合并查看 ${preview.conversation_ids.length} 条会话` : "确认取消此合并"}</b><p>新增 {preview.added_ids.length} 条，移除 {preview.removed_ids.length} 条。</p><p>新增成员不会自动获得 GPT 授权；移除成员将阻止后续读取。已发送给 GPT 的内容无法撤回。</p></section>}
    {error && <p role="alert" className="customer-workflow-error">{error}</p>}
    <footer><button type="button" disabled={busy} onClick={onClose}>关闭</button><button type="button" className="primary" disabled={busy || reason.trim().length < 2 || (!group && selected.length < 2)} onClick={() => void act()}>{busy ? "正在核对…" : preview ? "确认此范围" : "预览范围"}</button></footer>
  </CustomerWorkflowDialog>;
}
