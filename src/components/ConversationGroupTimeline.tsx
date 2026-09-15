import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { localPlatformService, type CustomerImageArchiveView } from "../data/localPlatformService";
import type { ConversationGroup, ConversationGroupPage } from "../data/customerConversationClient";
import { subscribeCustomerEvents } from "../data/customerEvents";
import { ImageLightbox, OriginalPreview } from "./CustomerImageLibrary";
import { MessageTimelineEntry } from './workspace/MessageTimelineEntry';
import { useLatestMessageScroll } from './workspace/useLatestMessageScroll';
import "../pages/customer-messages.css";

export function ConversationGroupTimeline({ group, latestMessageRequest = 0 }: { group: ConversationGroup; latestMessageRequest?: number }) {
  const [page, setPage] = useState<ConversationGroupPage | null>(null);
  const [itemId, setItemId] = useState("");
  const [items, setItems] = useState<Array<{ id: string; externalId: string | null; title: string }>>([]);
  const [image, setImage] = useState<CustomerImageArchiveView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const version = useRef(0);
  const oldestOffset = useRef(0);
  const messagesRef = useRef<HTMLElement>(null);
  const historyScroll = useRef<{ height: number; top: number } | null>(null);
  useLayoutEffect(() => {
    const saved = historyScroll.current;
    historyScroll.current = null;
    if (saved && messagesRef.current) messagesRef.current.scrollTop = saved.top + messagesRef.current.scrollHeight - saved.height;
  }, [page]);
  useLatestMessageScroll(messagesRef, `${group.id}:${itemId}`, latestMessageRequest, page !== null);
  const load = useCallback(async (append = false) => {
    const seq = ++version.current;
    setBusy(true);
    try {
      const previousHeight = messagesRef.current?.scrollHeight || 0;
      const previousTop = messagesRef.current?.scrollTop || 0;
      let offset = append ? Math.max(0, oldestOffset.current - 100) : 0;
      let result = await localPlatformService.conversationGroupMessages(group.id, offset, itemId, append ? oldestOffset.current - offset : 100);
      if (seq !== version.current) return;
      // The existing API is oldest-first. Seek the tail instead of presenting its first page as latest.
      if (!append && result.total > result.messages.length) {
        offset = Math.max(0, result.total - 100);
        result = await localPlatformService.conversationGroupMessages(group.id, offset, itemId);
      }
      if (seq !== version.current) return;
      if (append) historyScroll.current = { height: previousHeight, top: previousTop };
      setPage((previous) => append && previous ? { ...result, messages: [...result.messages, ...previous.messages] } : result);
      oldestOffset.current = offset;
      setError("");
    } catch (e) { if (seq === version.current) { setError(e instanceof Error ? e.message : "合并会话读取失败"); setPage(null); oldestOffset.current = 0; } }
    finally { if (seq === version.current) setBusy(false); }
  }, [group.id, group.revision, itemId]);
  useEffect(() => { setPage(null); void load(); return () => { version.current += 1; }; }, [load, latestMessageRequest]);
  useEffect(() => subscribeCustomerEvents(() => void load()), [load]);
  useEffect(() => {
    let live = true;
    const anchor = group.conversation_ids[0];
    if (anchor) void localPlatformService.conversationGroupCandidates(anchor).then((value) => { if (live) setItems(value.candidates.filter((row) => group.conversation_ids.includes(row.id) && row.item_id).map((row) => ({ id: String(row.item_id), externalId: row.item_external_id || null, title: row.item_title || "商品来源未知" })).filter((row, index, all) => all.findIndex((candidate) => candidate.id === row.id) === index)); }).catch(() => {});
    return () => { live = false; };
  }, [group.id, group.revision]);
  return <section className="conversation-group-timeline" ref={messagesRef}>
    <label>商品筛选<select aria-label="合并会话商品筛选" value={itemId} onChange={(event) => setItemId(event.target.value)}><option value="">全部商品</option>{items.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
    {error && <p role="alert">{error}</p>}
    <div className="thread-messages">{!busy && oldestOffset.current > 0 && <div className="thread-history-control"><button type="button" onClick={() => void load(true)}>加载更早消息</button></div>}{page?.messages.map((message,index) => <MessageTimelineEntry receivedAt={message.received_at} previousAt={page.messages[index-1]?.received_at} direction={message.direction} key={`${message.source_conversation_id}:${message.id}`} provenance={<small className="message-provenance">原会话 #{message.source_conversation_id} · {message.source_item_external_id ? message.source_item_title || items.find((item) => item.externalId === message.source_item_external_id)?.title || "原商品记录不可用" : "历史商品来源未知"}</small>} media={(message.images||message.customer_images||[]).length>0?<div className="message-image-grid">{(message.images || message.customer_images || []).map((entry) => <button key={entry.id} type="button" aria-label="查看合并会话图片" onClick={() => setImage(entry)}><OriginalPreview image={entry} compact /></button>)}</div>:null}>{message.content && message.content !== "[图片]" ? <p>{message.content}</p>:null}</MessageTimelineEntry>)}</div>
    {!busy && page && !page.messages.length && <p>当前范围暂无消息</p>}
    {busy && <p role="status">正在读取合并会话…</p>}
    <ImageLightbox image={image} onClose={() => setImage(null)} onOpenConversation={(id) => { window.location.hash = encodeURIComponent(`客户消息/conversation/${id}`); setImage(null); }} onDeleted={() => { setImage(null); void load(); }} />
  </section>;
}
