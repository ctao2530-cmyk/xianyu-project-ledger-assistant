import { localApi as api } from "./localApi";
import type { CustomerImageListView, CustomerImageArchiveStatus, CustomerImageFilters, CustomerImageHistoryPreview, CustomerImageAttentionItem, CustomerImageHistoryResult } from "./localPlatformService";

export interface CustomerImageQuery {
  channel?: string;
  conversationId?: number | null;
  conversationIds?: number[];
  itemId?: string;
  search?: string;
  dateFrom?: string;
  dateTo?: string;
  limit?: number;
  offset?: number;
}

export const customerImageClient = {
  customerImages: (filters: CustomerImageQuery = {}) => {
    const params = new URLSearchParams();
    if (filters.channel && filters.channel !== "all") params.set("channel", filters.channel);
    if (filters.conversationId) params.set("conversation_id", String(filters.conversationId));
    if (filters.conversationIds?.length) params.set("conversation_ids", filters.conversationIds.join(","));
    if (filters.itemId) params.set("item_id", filters.itemId);
    if (filters.search?.trim()) params.set("search", filters.search.trim());
    if (filters.dateFrom) params.set("date_from", filters.dateFrom);
    if (filters.dateTo) params.set("date_to", filters.dateTo);
    params.set("limit", String(filters.limit || 100));
    params.set("offset", String(filters.offset || 0));
    return api<CustomerImageListView>(`/api/customer-images?${params.toString()}`);
  },
  customerImageStatus: () => api<CustomerImageArchiveStatus>("/api/customer-images/status"),
  customerImageFilters: () => api<CustomerImageFilters>("/api/customer-images/filters"),
  previewCustomerImageHistory: () => api<CustomerImageHistoryPreview>("/api/customer-images/history-preview"),
  customerImageAttention: () => api<CustomerImageAttentionItem[]>("/api/customer-images/attention"),
  recoverCustomerImageHistory: (requestId: string) => api<CustomerImageHistoryResult>("/api/customer-images/history-recover", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify({ request_id: requestId, confirmed: true }) }),
  deleteCustomerImage: (archiveId: string) => api<void>(`/api/customer-images/${encodeURIComponent(archiveId)}/delete`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify({ confirmed: true }) }),
};
