import { localApi as api } from "./localApi";
import type { ConversationSummary, ConversationDetail, ConversationMessagePage, ConversationHistorySearchItem, ConversationHistoryPreview, ConversationHistoryCommitResult, ConversationMessage } from "./localPlatformService";

export interface ConversationGroup {
  id: string;
  title: string;
  revision: number;
  active: boolean;
  conversation_ids: number[];
  customer_id: string | null;
}
export interface ConversationGroupCandidate {
  id: number;
  channel: string;
  customer_name: string;
  item_id: string | number | null;
  item_external_id?: string | null;
  item_title: string | null;
  identity_basis: "platform_id" | "confirmed_identity";
  source_unknown: boolean;
}
export interface ConversationGroupChange {
  anchor_conversation_id: number;
  conversation_ids: number[];
  group_id?: string;
  expected_revision: number;
  title: string;
  reason: string;
  request_id: string;
}
export interface ConversationGroupPreview {
  preview_token: string;
  expires_at: string;
  group_id: string | null;
  expected_revision: number;
  conversation_ids: number[];
  added_ids: number[];
  removed_ids: number[];
  authorization_impact: unknown;
}
export interface ConversationGroupPage {
  group?: ConversationGroup;
  messages: Array<ConversationMessage & { source_conversation_id: number; source_item_external_id: string | null }>;
  total: number;
  has_more: boolean;
}
const desktop = { "X-Yuda-Desktop": "1" };
async function groupCustomerId(conversationId: number) {
  const conversation = await api<ConversationDetail>(`/api/conversations/${conversationId}`);
  if (!conversation.linked_customer_id) throw new Error("合并前请先在客户管理确认该渠道身份关联；图片归档和浏览不受影响");
  return conversation.linked_customer_id;
}
function groupPayload(payload: ConversationGroupChange, previewToken?: string) {
  return { group_id: payload.group_id, conversation_ids: payload.conversation_ids, expected_revision: payload.expected_revision, request_id: payload.request_id, reason: payload.reason, confirmed: Boolean(previewToken), ...(previewToken ? { preview_token: previewToken } : {}) };
}
export const customerConversationClient = {
  conversations: (channel = "all") => api<ConversationSummary[]>(`/api/conversations?channel=${encodeURIComponent(channel)}`),
  conversation: (id: number) => api<ConversationDetail>(`/api/conversations/${id}`),
  olderConversationMessages: (id: number, beforeMessageId: number, limit = 100) => api<ConversationMessagePage>(`/api/conversations/${id}/messages?before_message_id=${encodeURIComponent(String(beforeMessageId))}&limit=${encodeURIComponent(String(limit))}`),
  searchConversationHistory: (payload: { query: string; days: 7 | 30 | 90 | 365; limit?: number }) => api<ConversationHistorySearchItem[]>("/api/conversations/history-import/search", { method: "POST", headers: desktop, body: JSON.stringify({ ...payload, limit: payload.limit || 100 }) }),
  previewConversationHistory: (externalConversationId: string, historyScope: "recent" | "full" | "page" = "recent", messageLimit = 100, continuationToken?: string) => api<ConversationHistoryPreview>("/api/conversations/history-import/preview", { method: "POST", headers: desktop, body: JSON.stringify({ external_conversation_id: externalConversationId, message_limit: messageLimit, history_scope: historyScope, continuation_token: continuationToken }) }),
  commitConversationHistory: (payload: { request_id: string; preview_token: string; mark_latest_pending: boolean }) => api<ConversationHistoryCommitResult>("/api/conversations/history-import/commit", { method: "POST", headers: desktop, body: JSON.stringify(payload) }),
  conversationGroupCandidates: async (conversationId: number) => {
    const customerId = await groupCustomerId(conversationId);
    const result = await api<{ conversations: ConversationGroupCandidate[]; groups: ConversationGroup[] }>(`/api/customers/${encodeURIComponent(customerId)}/conversation-group-candidates`, { headers: desktop });
    return { customer_id: customerId, candidates: result.conversations.map((row) => ({ ...row, identity_basis: "confirmed_identity" as const, source_unknown: !row.item_id })), groups: result.groups };
  },
  previewConversationGroup: async (payload: ConversationGroupChange) => {
    const customerId = await groupCustomerId(payload.anchor_conversation_id);
    const result = await api<ConversationGroupPreview & { effects: { added: number[]; removed: number[] } }>(`/api/customers/${encodeURIComponent(customerId)}/conversation-groups/preview`, { method: "POST", headers: desktop, body: JSON.stringify(groupPayload(payload)) });
    return { ...result, added_ids: result.effects.added, removed_ids: result.effects.removed };
  },
  commitConversationGroup: async (payload: ConversationGroupChange & { preview_token: string; confirmed: true }) => {
    const customerId = await groupCustomerId(payload.anchor_conversation_id);
    return api<ConversationGroup>(`/api/customers/${encodeURIComponent(customerId)}/conversation-groups`, { method: "POST", headers: desktop, body: JSON.stringify(groupPayload(payload, payload.preview_token)) });
  },
  conversationGroupMessages: async (groupId: string, offset = 0, itemId = "", limit = 100) => {
    const result = await api<{ messages: Array<ConversationMessage & { conversation_id: number; source_item_external_id: string | null }>; total_count: number; has_more: boolean }>(`/api/conversation-groups/${encodeURIComponent(groupId)}/timeline?limit=${limit}&offset=${offset}${itemId ? `&item_id=${encodeURIComponent(itemId)}` : ""}`, { headers: desktop });
    return { messages: result.messages.map((message) => ({ ...message, source_conversation_id: message.conversation_id })), total: result.total_count, has_more: result.has_more } satisfies ConversationGroupPage;
  },
};
