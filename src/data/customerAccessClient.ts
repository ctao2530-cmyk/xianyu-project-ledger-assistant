import { localApi as api } from "./localApi";
import type { CustomerConversationAccessState, CustomerContextThreadBinding, CustomerContextThreadBindingList } from "./localPlatformService";

export interface CustomerThreadAccessRequest {
  request_id: string;
  conversation_id: number;
  expected_conversation_revision: number;
  allow_text: boolean;
  allow_images: boolean;
  allow_artifacts: boolean;
  allow_new_messages: boolean;
  expires_in_seconds: number;
  authorization_note: string;
  confirmed: true;
  group_id?: string;
  expected_group_revision?: number;
  selected_conversation_ids?: number[];
}
const desktop = { "X-Yuda-Desktop": "1" };
export const customerAccessClient = {
  customerConversationAccess: (conversationId: number) => api<CustomerConversationAccessState>(`/api/customer-context/conversations/${conversationId}/access`, { headers: desktop }),
  customerContextThreadBindings: () => api<CustomerContextThreadBindingList>("/api/customer-context/thread-bindings", { headers: desktop }),
  createCustomerContextThreadBinding: (payload: CustomerThreadAccessRequest) => api<CustomerContextThreadBinding>("/api/customer-context/thread-bindings", { method: "POST", headers: desktop, body: JSON.stringify(payload) }),
  revokeCustomerContextThreadBinding: (bindingId: string, payload: { request_id: string; expected_revision: number; reason: string; confirmed: true }) => api<CustomerContextThreadBinding>(`/api/customer-context/thread-bindings/${encodeURIComponent(bindingId)}/revoke`, { method: "POST", headers: desktop, body: JSON.stringify(payload) }),
};
