import type { LedgerSnapshot } from "../types";

export interface PlatformStatus {
  listener: string;
  listener_detail?: string | null;
  model: string;
  model_detail?: string | null;
  codex_installed?: boolean | null;
  codex_logged_in?: boolean | null;
  wechat_provider?: string;
  wechat_status?: string;
  automatic_sending?: boolean;
}

export interface ConversationSummary {
  id: number;
  channel: "xianyu" | "wechat" | string;
  customer_name: string;
  item_title: string | null;
  unread_count: number;
  last_message: string | null;
  last_message_at: string;
}

export interface ConversationMessage {
  id: number;
  sender_name: string;
  direction: "inbound" | "outbound";
  content: string;
  status: string;
  risk_flags: string[];
  received_at: string;
}

export interface ReplyDraft {
  id: number;
  style: string;
  content: string;
  risk_flags: string[];
}

export interface ConversationDetail {
  id: number;
  channel: string;
  external_id: string;
  customer_id: string;
  customer_name: string;
  item: { title: string; price?: string | null; description?: string | null } | null;
  messages: ConversationMessage[];
  pending_message_id: number | null;
  drafts: ReplyDraft[];
  ai_task: { id: number; provider: string; model?: string | null; status: string; risk_level?: string | null; risk_reasons?: string[]; error_code?: string | null; error_message?: string | null; started_at?: string | null; finished_at?: string | null; duration_seconds?: number | null } | null;
}

export type DraftProvider = "deepseek" | "codex_cli";

export interface AIProviderStatus {
  provider: DraftProvider;
  label: string;
  configured: boolean;
  status: string;
  detail: string | null;
  model: string | null;
  last_latency_seconds: number | null;
  supports_replies: boolean;
  supports_lead_analysis: boolean;
  manual_requirement_import: boolean;
  base_url: string | null;
  chat_endpoint: string | null;
  models_endpoint: string | null;
  config_file: string | null;
  lead_model: string | null;
}

export interface RequirementWorkspace {
  latest: null | {
    id: number;
    version: number;
    title: string;
    readiness: string;
    content_markdown: string;
    document: Record<string, unknown>;
  };
  versions: Array<{ id: number; version: number; title: string; readiness: string }>;
  task: null | { id: number; status: string; error_message?: string | null };
  model_label: string;
}

export interface LeadView {
  id: string;
  conversation_id: number;
  customer_id: string | null;
  status: string;
  requirement_version_id: number | null;
  latest_quote_id: string | null;
  converted_project_id: string | null;
}

export interface LeadAnalysis {
  id: string;
  conversation_id: number;
  provider: string;
  model: string;
  confirmed_at: string | null;
  created_at: string;
  result: {
    has_project_need: boolean;
    confidence: number;
    project_type: string;
    suggested_title: string;
    confirmed_signals: string[];
    open_questions: string[];
    budget_signals: string[];
    timeline_signals: string[];
    intent_signals: string[];
    risks: string[];
    message_refs: number[];
    conversion_advice: string;
  };
}

export interface SalesAnalysisResult {
  customer_type: "新访客" | "潜在客户" | "意向客户" | "已有客户" | "低匹配客户";
  need_type: string;
  purchase_probability: number;
  stage: "初次咨询" | "需求沟通" | "方案评估" | "报价决策" | "待跟进" | "已成交" | "暂不匹配";
  customer_profile: string;
  need_signals: string[];
  sales_strategy: string;
  next_action: string;
  recommended_reply: string;
  evidence_refs: number[];
  risk_flags: string[];
  tools_used: Array<"customer_history" | "similar_projects" | "pricing_history">;
  needs_human_confirmation: true;
}

export interface SalesAnalysis {
  id: string;
  conversation_id: number;
  message_id: number;
  provider: string;
  model: string;
  status: "running" | "completed" | "failed" | string;
  result: SalesAnalysisResult | null;
  tools_used: string[];
  context_summary: {
    message_count: number;
    project_count: number;
    quote_count: number;
    confirmed_revenue: number;
    memory_version: number;
  };
  error_code: string | null;
  error_message: string | null;
  confirmed_at: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface SalesMemoryItem {
  id: string;
  customer_id: string | null;
  conversation_id: number;
  source_analysis_id: string | null;
  customer_background: string;
  requirements: string[];
  communication_summary: string;
  latest_analysis: Record<string, unknown>;
  follow_up_status: string;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface SalesMemory {
  customer_id: string | null;
  memories: SalesMemoryItem[];
  memory_count: number;
  latest_version: number;
}

export interface SalesConfirmation {
  analysis: SalesAnalysis;
  lead: LeadView;
  memory: SalesMemoryItem;
  revision: number;
  idempotent: boolean;
}

export interface RequirementBlueprint {
  schema_version: "2.0";
  title: string;
  project_type: string;
  readiness: "discovery" | "clarifying" | "ready" | "approved";
  change_summary: string;
  objectives: Array<{ id: string; title: string; description: string; evidence_refs: string[] }>;
  capabilities: Array<{ id: string; title: string; description: string; objective_ids: string[]; priority: "must" | "should" | "could"; evidence_refs: string[] }>;
  stages: Array<{ id: string; title: string; objective: string; implementation: string; estimated_hours: number; capability_ids: string[]; dependency_ids: string[]; work_items: string[]; deliverables: string[]; evidence_refs: string[] }>;
  acceptance_gates: Array<{ id: string; title: string; description: string; stage_ids: string[]; criteria: string[]; evidence_refs: string[] }>;
  out_of_scope: string[];
  assumptions: string[];
  open_questions: string[];
  risks: Array<{ id: string; title: string; description: string; severity: "low" | "medium" | "high"; mitigation: string; evidence_refs: string[] }>;
  evidence_refs: Array<{ id: string; message_number: number; quote: string }>;
}

export interface RequirementExport {
  conversation_id: number;
  filename: string;
  prompt: string;
  analysis_document: string;
  schema: Record<string, unknown>;
  conversation_package: Record<string, unknown>;
  redaction_count: number;
  private_content_included: boolean;
}

export interface RequirementImportPreview {
  token: string;
  expires_at: string;
  customer_id: string;
  case_id: string | null;
  case_title: string;
  target_version: number;
  expected_version: number;
  document: RequirementBlueprint;
  estimated_hours: number;
  warnings: string[];
  changes: string[];
}

export interface RequirementVersionCaseSummary {
  id: number;
  version: number;
  schema_version: string;
  source_type: string;
  source_label: string;
  title: string;
  readiness: string;
  change_summary: string;
  imported_at: string | null;
  created_at: string;
}

export interface RequirementCaseSummary {
  id: string;
  customer_id: string;
  title: string;
  status: string;
  current_version: number;
  source_count: number;
  estimated_hours: number;
  open_question_count: number;
  updated_at: string;
}

export interface RequirementCaseDetail extends RequirementCaseSummary {
  lead_id: string | null;
  project_id: string | null;
  versions: RequirementVersionCaseSummary[];
  selected_version: RequirementVersionCaseSummary | null;
  document: RequirementBlueprint | Record<string, unknown> | null;
  sources: Array<{ conversation_id: number; last_exported_message_id: number | null; channel: string; customer_name: string }>;
}

export interface QuoteView {
  id: string;
  lead_id: string;
  version: number;
  status: string;
  hourly_rate: number;
  risk_buffer: number;
  estimated_hours: number;
  total_amount: number;
  stages: Array<Record<string, unknown>>;
  payment_plan: Array<Record<string, unknown>>;
  risks: string[];
}

export interface MigrationConflict {
  key: string;
  collection: string;
  incoming_id: string;
  existing_id: string;
  reason: string;
  incoming: Record<string, unknown>;
  existing: Record<string, unknown>;
}

export interface MigrationPreview {
  token: string;
  current_revision: number;
  incoming_counts: Record<string, number>;
  additions: Record<string, number>;
  identical: Record<string, number>;
  conflicts: MigrationConflict[];
  can_import_without_review: boolean;
}

export interface BusinessRequirementAnalysis {
  project_type: string;
  features: string[];
  estimated_days_min: number;
  estimated_days_max: number;
  estimated_hours: number;
  risks: string[];
  scope_notes: string[];
  quote_min: number | null;
  quote_max: number | null;
  hourly_rate: number | null;
  pricing_blocked: boolean;
}

export interface BusinessQuote {
  total_amount: number;
  hourly_rate: number;
  risk_buffer: number;
  estimated_hours: number;
  items: Array<{ name: string; amount: number }>;
  payment_plan: Array<{ type: string; label: string; ratio: number; amount: number }>;
  delivery_note: string;
}

export interface BusinessReview {
  summary: string;
  pricing_advice: string;
  recommended_increase_percent: number;
  improvements: string[];
  risks: string[];
}

export interface ProductSnapshotView {
  date: string;
  source: string;
  browse_count: number;
  collect_count: number;
  want_count: number;
  sold_count: number;
  inquiry_count: number;
  converted_project_count: number;
  revenue_total: number;
  profit_total: number;
}

export interface ProductRecommendationView {
  id: string;
  item_external_id: string;
  item_title: string;
  recommendation_date: string;
  strategy_code: string;
  priority_score: number;
  attention: "high" | "medium" | "low" | string;
  posture: string;
  title: string;
  summary: string;
  evidence: string[];
  actions: string[];
  confidence: "high" | "medium" | "low" | string;
  status: string;
}

export interface ProductActionView {
  id: string;
  action_type: string;
  status: string;
  note: string;
  cost: number;
  happened_at: string;
  observation_until: string | null;
}

export interface ProductView {
  external_id: string;
  title: string;
  price: number | null;
  status: string;
  monitoring_enabled: boolean;
  monitor_source: string;
  ownership_status: "owned" | "pending" | "excluded" | string;
  ownership_source: string;
  last_attempt_at: string | null;
  last_collection_status: "waiting" | "success" | "failed" | "excluded" | "pending" | "skipped" | string;
  last_error_code: string | null;
  last_error_detail: string | null;
  last_collected_at: string | null;
  browse_count: number;
  collect_count: number;
  want_count: number;
  sold_count: number;
  browse_delta: number | null;
  inquiry_count: number;
  inbound_message_count: number;
  converted_project_count: number;
  revenue_total: number;
  profit_total: number;
  inquiry_rate: number | null;
  deal_rate: number | null;
  history: ProductSnapshotView[];
  recommendation: ProductRecommendationView | null;
  actions: ProductActionView[];
}

export interface ProductCollectionRunView {
  id: string;
  run_date: string;
  trigger: string;
  status: string;
  monitored_count: number;
  collected_count: number;
  failed_count: number;
  detail: string;
  started_at: string;
  finished_at: string | null;
}

export interface ProductIntelligenceView {
  collection: {
    configured: boolean;
    schedule: string;
    timezone: string;
    can_collect_today: boolean;
    next_collection_at: string | null;
    last_run: ProductCollectionRunView | null;
    safety_note: string;
  };
  summary: {
    monitored_products: number;
    active_products: number;
    pending_products: number;
    excluded_products: number;
    needs_attention: number;
    traffic_candidates: number;
    snapshot_days: number;
    active_projects: number;
    delivery_capacity: number;
  };
  products: ProductView[];
  candidates: ProductView[];
  recommendations: ProductRecommendationView[];
  publish_timing: {
    sample_size: number;
    confidence: string;
    summary: string;
    windows: Array<{ weekday: string; time_range: string; inquiry_count: number; share: number }>;
  };
  demand_opportunities: Array<{
    theme: string;
    message_count: number;
    conversation_count: number;
    converted_project_count: number;
    posture: string;
    suggestion: string;
  }>;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  const body = await response.json().catch(() => null) as { detail?: string | { message?: string } } | null;
  if (!response.ok) {
    const detail = body?.detail;
    const message = typeof detail === "string" ? detail : detail?.message;
    throw new Error(message || `本机服务请求失败（${response.status}）`);
  }
  return body as T;
}

export const localPlatformService = {
  status: () => api<PlatformStatus>("/api/status"),
  conversations: (channel = "all") => api<ConversationSummary[]>(`/api/conversations?channel=${encodeURIComponent(channel)}`),
  conversation: (id: number) => api<ConversationDetail>(`/api/conversations/${id}`),
  requirements: (id: number) => api<RequirementWorkspace>(`/api/conversations/${id}/requirements`),
  generateRequirements: (id: number) => api(`/api/conversations/${id}/requirements/generate`, { method: "POST" }),
  providers: (refresh = false) => api<AIProviderStatus[]>(`/api/ai/providers${refresh ? "?refresh=true" : ""}`),
  regenerateDrafts: (messageId: number, provider: DraftProvider = "codex_cli") => api(`/api/messages/${messageId}/drafts/generate`, { method: "POST", body: JSON.stringify({ provider }) }),
  send: (messageId: number, content: string) => api(`/api/messages/${messageId}/send`, { method: "POST", body: JSON.stringify({ content }) }),
  ignore: (messageId: number) => api(`/api/messages/${messageId}/ignore`, { method: "POST" }),
  getLead: (conversationId: number) => api<LeadView | null>(`/api/conversations/${conversationId}/lead`),
  analyzeLead: (conversationId: number, refresh = false) => api<LeadAnalysis>(`/api/conversations/${conversationId}/lead/analyze?refresh=${refresh ? "true" : "false"}`, { method: "POST" }),
  confirmLead: (conversationId: number, analysisRunId?: string) => api<LeadView>(`/api/conversations/${conversationId}/lead`, { method: "POST", body: JSON.stringify({ confirmed: true, analysis_run_id: analysisRunId || null }) }),
  salesAnalysis: (conversationId: number) => api<SalesAnalysis | null>(`/api/conversations/${conversationId}/sales/analysis`),
  salesHistory: (conversationId: number, limit = 10) => api<SalesAnalysis[]>(`/api/conversations/${conversationId}/sales/history?limit=${limit}`),
  salesMemory: (conversationId: number) => api<SalesMemory>(`/api/conversations/${conversationId}/sales/memory`),
  analyzeSales: (conversationId: number, refresh = false, provider?: DraftProvider) => api<SalesAnalysis>(`/api/conversations/${conversationId}/sales/analyze?refresh=${refresh ? "true" : "false"}${provider ? `&provider=${encodeURIComponent(provider)}` : ""}`, { method: "POST" }),
  confirmSales: (conversationId: number, analysisRunId: string) => api<SalesConfirmation>(`/api/conversations/${conversationId}/sales/confirm`, { method: "POST", body: JSON.stringify({ confirmed: true, analysis_run_id: analysisRunId }) }),
  requirementExport: (conversationId: number) => api<RequirementExport>(`/api/conversations/${conversationId}/requirement-export`),
  previewRequirementImport: (payload: { conversation_id: number; customer_id: string; case_id?: string | null; case_title?: string | null; source_label?: string; document: string | Record<string, unknown> }) => api<RequirementImportPreview>("/api/requirements/import/preview", { method: "POST", body: JSON.stringify(payload) }),
  commitRequirementImport: (token: string, expectedVersion: number) => api<{ case: RequirementCaseDetail; version_id: number; version: number; idempotent: boolean }>("/api/requirements/import/commit", { method: "POST", body: JSON.stringify({ token, expected_version: expectedVersion }) }),
  customerRequirements: (customerId: string) => api<RequirementCaseSummary[]>(`/api/customers/${encodeURIComponent(customerId)}/requirements`),
  requirementCase: (caseId: string, version?: number) => api<RequirementCaseDetail>(`/api/requirement-cases/${encodeURIComponent(caseId)}${version ? `?version=${version}` : ""}`),
  quotes: (leadId: string) => api<QuoteView[]>(`/api/leads/${leadId}/quotes`),
  generateQuote: (leadId: string, hourlyRate?: number) => api<QuoteView>(`/api/leads/${leadId}/quote/generate`, { method: "POST", body: JSON.stringify({ hourly_rate: hourlyRate || null, risk_buffer: 0.15 }) }),
  convertLead: (leadId: string, quoteId: string, projectName?: string) => api<{ project_id: string; revision: number }>(`/api/leads/${leadId}/convert`, { method: "POST", body: JSON.stringify({ quote_id: quoteId, confirmed: true, project_name: projectName || null }) }),
  migrationPreview: (snapshot: LedgerSnapshot) => api<MigrationPreview>("/api/ledger/migrations/preview", { method: "POST", body: JSON.stringify({ snapshot }) }),
  migrationCommit: (snapshot: LedgerSnapshot, token: string, resolutions: Record<string, "sqlite" | "browser">) => api<{ revision: number; snapshot: LedgerSnapshot; backup_name: string; attachments_written: number }>("/api/ledger/migrations/commit", { method: "POST", body: JSON.stringify({ snapshot, token, resolutions }) }),
  operationsSummary: () => api<{ unread: number; pending_replies: number; open_leads: number; quoted_leads: number; converted_leads: number }>("/api/operations/summary"),
  analyzeBusinessRequirement: (content: string) => api<BusinessRequirementAnalysis>("/api/ai/business/analyze", { method: "POST", body: JSON.stringify({ content }) }),
  createBusinessQuote: (analysis: BusinessRequirementAnalysis, complexity: "standard" | "advanced" | "complex", riskBuffer = 0.15) => api<BusinessQuote>("/api/ai/business/quote", { method: "POST", body: JSON.stringify({ analysis, complexity, risk_buffer: riskBuffer }) }),
  reviewBusinessProject: (payload: Record<string, unknown>) => api<BusinessReview>("/api/ai/business/review", { method: "POST", body: JSON.stringify(payload) }),
  productIntelligence: () => api<ProductIntelligenceView>("/api/products/intelligence"),
  collectProducts: () => api<ProductCollectionRunView>("/api/products/collect", { method: "POST" }),
  registerProduct: (itemReference: string) => api<ProductView>("/api/products/register", { method: "POST", body: JSON.stringify({ item_reference: itemReference }) }),
  updateProductMonitor: (externalId: string, enabled: boolean) => api<ProductView>(`/api/products/${encodeURIComponent(externalId)}/monitor`, { method: "PUT", body: JSON.stringify({ enabled }) }),
  recordProductAction: (externalId: string, payload: { action_type: string; status: "planned" | "completed" | "cancelled"; note: string; cost: number; recommendation_id?: string | null; observation_days: number }) => api<ProductActionView>(`/api/products/${encodeURIComponent(externalId)}/actions`, { method: "POST", body: JSON.stringify(payload) }),
  updateProductRecommendation: (recommendationId: string, status: "active" | "in_progress" | "completed" | "dismissed") => api<void>(`/api/products/recommendations/${encodeURIComponent(recommendationId)}`, { method: "PUT", body: JSON.stringify({ status }) }),
};

export function connectPlatformEvents(onEvent: (event: Record<string, unknown>) => void) {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${scheme}://${window.location.host}/events`);
  socket.addEventListener("message", (event) => {
    try {
      onEvent(JSON.parse(event.data) as Record<string, unknown>);
    } catch {
      // Ignore malformed local events; normal API refresh remains available.
    }
  });
  return () => socket.close();
}
