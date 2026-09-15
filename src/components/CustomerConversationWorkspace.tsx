import { useEffect, useState } from "react";
import { localPlatformService, type GlobalAgentCustomerContextOption } from "../data/localPlatformService";
import { ConversationGroupDialog } from "./ConversationGroupDialog";
import { ConversationGroupTimeline } from "./ConversationGroupTimeline";
import { CustomerWorkflowDialog } from "./CustomerWorkflowDialog";
import { ChatGPTConversationAccessCard } from "./ChatGPTConversationAccessCard";
import type { ConversationGroup } from "../data/customerConversationClient";

export function CustomerConversationWorkspace({ customerId }: { customerId: string }) {
  const [options, setOptions] = useState<GlobalAgentCustomerContextOption[]>([]);
  const [conversationId, setConversationId] = useState(0);
  const [group, setGroup] = useState<ConversationGroup | null>(null);
  const [mode, setMode] = useState<"group" | "access" | "timeline" | null>(null);
  const [notice, setNotice] = useState("");
  useEffect(() => {
    let live = true; setOptions([]); setConversationId(0); setGroup(null); setMode(null); setNotice("");
    void localPlatformService.globalAgentCustomerContextOptions().then((rows) => {
      if (!live) return;
      const matches = rows.filter((item) => item.customer_id === customerId);
      setOptions(matches); setConversationId(matches[0]?.conversation_id || 0);
    }).catch((e) => { if (live) setNotice(e instanceof Error ? e.message : "客户会话读取失败"); });
    return () => { live = false; };
  }, [customerId]);
  useEffect(() => {
    let live = true;
    if (conversationId) void localPlatformService.conversationGroupCandidates(conversationId).then((result) => { if (live) setGroup(result.groups.find((item) => item.active) || null); }).catch(() => {});
    return () => { live = false; };
  }, [conversationId]);
  return <section className="customer-conversation-actions" aria-label="客户会话操作">
    {options.length > 1 && <select aria-label="选择客户商品会话" value={conversationId} onChange={(event) => { setConversationId(Number(event.target.value)); setGroup(null); }} >{options.map((item) => <option key={item.conversation_id} value={item.conversation_id}>{item.item_title || "商品来源未知"} · {item.channel}</option>)}</select>}
    <button type="button" disabled={!conversationId} onClick={() => { window.location.hash = encodeURIComponent(`客户消息/conversation/${conversationId}`); }}>查看会话</button>
    <button type="button" disabled={!conversationId} onClick={() => { window.location.hash = encodeURIComponent(`客户消息/conversation/${conversationId}?view=materials`); }}>客户图片</button>
    <button type="button" disabled={!conversationId} onClick={() => setMode("group")}>合并会话</button>
    <button type="button" disabled={!conversationId} onClick={() => setMode("access")}>GPT 授权</button>
    {group && <button type="button" onClick={() => setMode("timeline")}>查看合并时间线</button>}
    {!options.length && <small>该客户尚无已确认关联的渠道会话。</small>}
    {notice && <small role="status">{notice}</small>}
    {mode === "group" && <ConversationGroupDialog conversationId={conversationId} onClose={() => setMode(null)} onChanged={(next) => { setGroup(next.active ? next : null); setNotice("会话范围已更新，原始记录保持不变"); }} />}
    {mode === "access" && <CustomerWorkflowDialog title="GPT 会话读取授权" onClose={() => setMode(null)}><ChatGPTConversationAccessCard onToast={setNotice} initialConversationId={group?.conversation_ids[0] || conversationId} selectedGroup={group} /></CustomerWorkflowDialog>}
    {mode === "timeline" && group && <CustomerWorkflowDialog title={group.title} onClose={() => setMode(null)}><ConversationGroupTimeline group={group} /></CustomerWorkflowDialog>}
  </section>;
}
