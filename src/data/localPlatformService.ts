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
  linked_customer_id: string | null;
  customer_name: string;
  item: { external_id: string; title: string; price?: string | null; description?: string | null } | null;
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

export interface RequirementAttachment {
  id: string;
  conversation_id: number;
  message_id: number | null;
  message_number: number | null;
  source: "manual" | "edge";
  attachment_type: "image";
  mime_type: string;
  original_name: string;
  sha256: string;
  file_size: number;
  width: number;
  height: number;
  sort_order: number;
  privacy_status: "pending" | "reviewed" | "excluded";
  reviewed_at: string | null;
  created_at: string;
  content_url: string;
  duplicate: boolean;
}

export interface RequirementImageCandidate {
  message_id: number;
  message_number: number;
  direction: string;
  time: string;
  label: string;
  captured: boolean;
  attachment_ids: string[];
}

export interface RequirementExportPreview {
  conversation_id: number;
  text_message_count: number;
  image_candidate_count: number;
  captured_image_count: number;
  missing_image_count: number;
  total_bytes: number;
  redaction_count: number;
  package_complete: boolean;
  attachments: RequirementAttachment[];
  image_candidates: RequirementImageCandidate[];
}

export interface RequirementExportPackage {
  export_id: string;
  conversation_id: number;
  package_root: string;
  readme_path: string;
  manifest_path: string;
  image_paths: string[];
  codex_prompt: string;
  selected_image_count: number;
  missing_image_count: number;
  package_complete: boolean;
  redaction_count: number;
}

export interface RequirementImportPreview {
  token: string;
  expires_at: string;
  customer_id: string;
  item_id: number | null;
  item_external_id: string | null;
  item_title: string | null;
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
  item_id: number | null;
  item_external_id: string | null;
  item_title: string | null;
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
  sources: Array<{ conversation_id: number; last_exported_message_id: number | null; channel: string; customer_name: string; item_external_id: string | null; item_title: string | null }>;
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
  raw_browse_count: number;
  collection_views_excluded: number;
  collect_count: number;
  want_count: number;
  sold_count: number;
  inquiry_count: number;
  converted_project_count: number;
  revenue_total: number;
  profit_total: number;
}

export interface ProductWindowMetricsView {
  days: number;
  observation_days: number;
  snapshot_count: number;
  browse_delta: number | null;
  inquiry_delta: number | null;
  want_delta: number | null;
  daily_browse: number | null;
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
  raw_browse_count: number;
  collection_views_excluded: number;
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
  snapshot_count: number;
  freshness_days: number | null;
  data_quality: "high" | "medium" | "low" | string;
  data_gaps: string[];
  traffic_cooldown_until: string | null;
  modification_observation_until: string | null;
  recent_windows: ProductWindowMetricsView[];
  history: ProductSnapshotView[];
  recommendation: ProductRecommendationView | null;
  actions: ProductActionView[];
}

export interface ProductPlanProductView {
  external_id: string;
  title: string;
  role: string;
  score: number;
  data_quality: string;
  reason: string;
}

export interface ProductOperatingPlanSlotView {
  id: string;
  date: string;
  weekday: string;
  scheduled_time: string;
  action_type: string;
  products: ProductPlanProductView[];
  planned_cost: number;
  reason: string;
  change_reason: string;
  evidence: string[];
  warnings: string[];
  confidence: string;
  locked: boolean;
  status: string;
  batch_id: string | null;
}

export interface ProductOperatingPlanView {
  id: string;
  version: number;
  start_date: string;
  end_date: string;
  generated_at: string;
  weekly_budget: number;
  spent_this_week: number;
  planned_this_week: number;
  remaining_this_week: number;
  cadence: string;
  change_summary: string;
  data_quality: string;
  rules_version: string;
  analysis_stage: string;
  effective_batch_count: number;
  slots: ProductOperatingPlanSlotView[];
}

export interface ProductTrafficBatchItemView {
  external_id: string;
  title: string;
  baseline_browse_count: number;
  baseline_collect_count: number;
  baseline_want_count: number;
  baseline_inquiry_count: number;
  baseline_captured_at: string | null;
  latest_checkpoint: string | null;
  latest_browse_count: number;
  latest_collect_count: number;
  latest_want_count: number;
  latest_inquiry_count: number;
  browse_delta: number;
  collect_delta: number;
  want_delta: number;
  inquiry_delta: number;
}

export interface ProductTrafficCheckpointMetricsView {
  checkpoint: "h1" | "h6" | "h24" | "h72" | string;
  hours: number;
  batch_count: number;
  browse_delta: number;
  collect_delta: number;
  want_delta: number;
  inquiry_delta: number;
  inquiry_conversion_rate: number | null;
  average_browse_delta: number;
  average_inquiry_delta: number;
}

export interface ProductTrafficBatchView {
  id: string;
  plan_slot_id: string | null;
  status: "planned" | "running" | "observing" | "closed" | "cancelled" | string;
  planned_at: string;
  started_at: string | null;
  completed_at: string | null;
  actual_cost: number;
  total_exposure: number | null;
  note: string;
  products: ProductTrafficBatchItemView[];
  completed_checkpoints: string[];
  due_checkpoint: "h1" | "h6" | "h24" | "h72" | null;
  due_at: string | null;
  overlap_warning: string | null;
  browse_delta: number;
  collect_delta: number;
  want_delta: number;
  inquiry_delta: number;
  inquiry_conversion_rate: number | null;
  cost_per_browse: number | null;
  cost_per_inquiry: number | null;
  observation_checkpoint: "h1" | "h6" | "h24" | "h72" | null;
  observation_hours: number;
  time_bucket: string;
  data_quality: string;
  analysis_eligible: boolean;
  checkpoint_metrics: ProductTrafficCheckpointMetricsView[];
  created_at: string;
}

export interface ProductTrafficTimeBucketView {
  bucket: string;
  time_range: string;
  batch_count: number;
  total_cost: number;
  browse_delta: number;
  inquiry_delta: number;
  average_browse_delta: number;
  average_inquiry_delta: number;
  inquiry_conversion_rate: number | null;
  cost_per_browse: number | null;
  cost_per_inquiry: number | null;
  confidence: string;
  recommended: boolean;
}

export interface ProductExposureAnalyticsView {
  window_days: number;
  total_spent: number;
  observed_cost: number;
  eligible_batch_count: number;
  excluded_batch_count: number;
  browse_delta: number;
  collect_delta: number;
  want_delta: number;
  inquiry_delta: number;
  average_browse_delta: number;
  average_inquiry_delta: number;
  inquiry_conversion_rate: number | null;
  cost_per_browse: number | null;
  cost_per_inquiry: number | null;
  confidence: string;
  best_time_bucket: string | null;
  summary: string;
  checkpoints: ProductTrafficCheckpointMetricsView[];
  time_buckets: ProductTrafficTimeBucketView[];
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

export interface ProductCollectionAttemptItemView {
  external_id: string;
  title: string;
  status: "pending" | "success" | "failed" | "skipped" | string;
  error_code: string | null;
  detail: string;
  finished_at: string | null;
}

export interface ProductCollectionAttemptView {
  id: string;
  run_date: string;
  daily_run_id: string | null;
  trigger: "scheduled" | "manual" | "manual_all" | "manual_single" | string;
  requested_external_id: string | null;
  requested_title: string | null;
  status: string;
  monitored_count: number;
  collected_count: number;
  failed_count: number;
  skipped_count: number;
  detail: string;
  started_at: string;
  finished_at: string | null;
  items: ProductCollectionAttemptItemView[];
}

export interface ProductMarketKeywordCandidateView {
  keyword: string;
  theme: string;
  score: number;
  reason: string;
  evidence: string[];
  confidence: string;
}

export interface ProductMarketSampleResultView {
  position: number;
  title: string;
  price: number | null;
  tags: string[];
}

export interface ProductMarketSampleView {
  id: string;
  keyword: string;
  sample_date: string;
  source: "edge_codex" | string;
  captured_at: string;
  result_count: number;
  note: string;
  results: ProductMarketSampleResultView[];
}

export interface ProductMarketBenchmarkView {
  keyword: string;
  sample_days: number;
  high_visibility_result_count: number;
  priced_result_count: number;
  repeated_result_count: number;
  median_price: number | null;
  price_low: number | null;
  price_high: number | null;
  common_title_terms: string[];
  common_tags: string[];
  median_title_length: number | null;
  confidence: string;
  evidence: string[];
}

export interface ProductMarketReferenceView {
  date: string;
  mode: "recommended" | "custom";
  selected_keyword: string;
  custom_keyword: string;
  recommendations: ProductMarketKeywordCandidateView[];
  common_keywords: string[];
  current_sample: ProductMarketSampleView | null;
  recent_samples: ProductMarketSampleView[];
  stability: {
    keyword: string;
    sample_days: number;
    visible_days: number;
    average_best_position: number | null;
    status: "insufficient" | "emerging" | "stable" | string;
    label: string;
  };
  benchmark: ProductMarketBenchmarkView;
  reminder: {
    date: string;
    status: "pending" | "sent" | "snoozed" | "skipped" | "completed" | string;
    scheduled_for: string;
    due: boolean;
    snoozed_until: string | null;
  };
  update_completed: boolean;
  last_updated_at: string | null;
  rules_version: string;
  safety_note: string;
}

export interface ProductLaunchRecommendationView {
  keyword: string;
  theme: string;
  title: string;
  recommended_window: string;
  demand_conversations: number;
  matching_product_count: number;
  capacity_available: number;
  confidence: string;
  market_validation_required: boolean;
  ready: boolean;
  recommended_action: "launch" | "modify_existing" | "observe" | string;
  suggested_product_type: string;
  title_direction: string;
  price_reference: string;
  market_differentiation: string;
  timing_basis: string;
  benchmark: ProductMarketBenchmarkView;
  rationale: string[];
  evidence: string[];
}

export interface ProductLaunchPlanView {
  id: string;
  keyword: string;
  theme: string;
  title: string;
  recommended_window: string;
  rationale: string[];
  evidence: string[];
  confidence: string;
  status: "proposed" | "planned" | "completed" | "cancelled" | string;
  created_at: string;
  updated_at: string;
}

export interface ProductModificationSuggestionView {
  external_id: string;
  title: string;
  variable: "title" | "cover" | "description" | "price" | null;
  reason: string;
  suggested_change: string;
  confidence: string;
  blocked_reason: string | null;
  benchmark_keyword: string | null;
  market_evidence: string[];
  market_gap: string | null;
  reference_price_range: string | null;
  confidence_basis: string[];
  evidence_sources: string[];
}

export interface ProductModificationExperimentView {
  id: string;
  item_external_id: string;
  item_title: string;
  variable: "title" | "cover" | "description" | "price";
  before_value: string;
  after_value: string;
  baseline: Record<string, number | string | null>;
  started_at: string;
  observation_until: string;
  status: "observing" | "completed" | "cancelled" | string;
  result: Record<string, number | string | null>;
  decision: "pending" | "keep" | "rollback" | "continue" | string;
  evidence: string[];
  can_evaluate: boolean;
}

export interface ProductIntelligenceView {
  collection: {
    configured: boolean;
    schedule: string;
    timezone: string;
    can_collect_today: boolean;
    next_collection_at: string | null;
    last_run: ProductCollectionRunView | null;
    latest_attempt: ProductCollectionAttemptView | null;
    attempts: ProductCollectionAttemptView[];
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
  operating_plan: ProductOperatingPlanView;
  traffic_batches: ProductTrafficBatchView[];
  traffic_summary: {
    batch_count: number;
    effective_batch_count: number;
    active_batch_count: number;
    due_checkpoint_count: number;
    spent_this_week: number;
    analysis_stage: string;
    analysis_summary: string;
  };
  exposure_analytics: ProductExposureAnalyticsView;
  market_reference: ProductMarketReferenceView;
  launch_recommendation: ProductLaunchRecommendationView;
  launch_plans: ProductLaunchPlanView[];
  modification_suggestions: ProductModificationSuggestionView[];
  modification_experiments: ProductModificationExperimentView[];
}

export interface OperationsSummary {
  unread: number;
  pending_replies: number;
  first_pending_conversation_id: number | null;
  open_leads: number;
  quoted_leads: number;
  converted_leads: number;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {
    ...init,
    headers,
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
  requirementExportPreview: (conversationId: number) => api<RequirementExportPreview>(`/api/conversations/${conversationId}/requirement-export-preview`),
  uploadRequirementAttachment: (conversationId: number, file: File, messageId?: number | null) => {
    const body = new FormData();
    body.append("file", file);
    body.append("source", "manual");
    if (messageId) body.append("message_id", String(messageId));
    return api<RequirementAttachment>(`/api/conversations/${conversationId}/requirement-attachments`, { method: "POST", body });
  },
  updateRequirementAttachmentPrivacy: (conversationId: number, attachmentId: string, privacyStatus: "pending" | "reviewed" | "excluded") => api<RequirementAttachment>(`/api/conversations/${conversationId}/requirement-attachments/${encodeURIComponent(attachmentId)}`, { method: "PATCH", body: JSON.stringify({ privacy_status: privacyStatus }) }),
  deleteRequirementAttachment: (conversationId: number, attachmentId: string) => api<void>(`/api/conversations/${conversationId}/requirement-attachments/${encodeURIComponent(attachmentId)}`, { method: "DELETE" }),
  createRequirementExportPackage: (conversationId: number, attachmentIds: string[], allowIncomplete: boolean) => api<RequirementExportPackage>(`/api/conversations/${conversationId}/requirement-export-package`, { method: "POST", body: JSON.stringify({ confirmed: true, attachment_ids: attachmentIds, allow_incomplete: allowIncomplete }) }),
  previewRequirementImport: (payload: { conversation_id: number; customer_id: string; case_id?: string | null; case_title?: string | null; source_label?: string; document: string | Record<string, unknown> }) => api<RequirementImportPreview>("/api/requirements/import/preview", { method: "POST", body: JSON.stringify(payload) }),
  commitRequirementImport: (token: string, expectedVersion: number) => api<{ case: RequirementCaseDetail; version_id: number; version: number; idempotent: boolean }>("/api/requirements/import/commit", { method: "POST", body: JSON.stringify({ token, expected_version: expectedVersion }) }),
  customerRequirements: (customerId: string) => api<RequirementCaseSummary[]>(`/api/customers/${encodeURIComponent(customerId)}/requirements`),
  requirementCase: (caseId: string, version?: number) => api<RequirementCaseDetail>(`/api/requirement-cases/${encodeURIComponent(caseId)}${version ? `?version=${version}` : ""}`),
  editRequirementCase: (caseId: string, payload: { expected_version: number; change_summary: string; document: RequirementBlueprint }) => api<{ case: RequirementCaseDetail; version_id: number; version: number; idempotent: boolean }>(`/api/requirement-cases/${encodeURIComponent(caseId)}/edit`, { method: "POST", body: JSON.stringify(payload) }),
  transferRequirementCase: (caseId: string, payload: { request_id: string; expected_customer_id: string; expected_version: number; expected_revision: number; target_customer_id?: string | null; new_customer_name?: string | null }) => api<{ revision: number; snapshot: LedgerSnapshot; target_customer_id: string; case: RequirementCaseDetail; idempotent: boolean }>(`/api/requirement-cases/${encodeURIComponent(caseId)}/transfer`, { method: "POST", body: JSON.stringify(payload) }),
  quotes: (leadId: string) => api<QuoteView[]>(`/api/leads/${leadId}/quotes`),
  generateQuote: (leadId: string, hourlyRate?: number) => api<QuoteView>(`/api/leads/${leadId}/quote/generate`, { method: "POST", body: JSON.stringify({ hourly_rate: hourlyRate || null, risk_buffer: 0.15 }) }),
  convertLead: (leadId: string, quoteId: string, projectName?: string) => api<{ project_id: string; revision: number }>(`/api/leads/${leadId}/convert`, { method: "POST", body: JSON.stringify({ quote_id: quoteId, confirmed: true, project_name: projectName || null }) }),
  migrationPreview: (snapshot: LedgerSnapshot) => api<MigrationPreview>("/api/ledger/migrations/preview", { method: "POST", body: JSON.stringify({ snapshot }) }),
  migrationCommit: (snapshot: LedgerSnapshot, token: string, resolutions: Record<string, "sqlite" | "browser">) => api<{ revision: number; snapshot: LedgerSnapshot; backup_name: string; attachments_written: number }>("/api/ledger/migrations/commit", { method: "POST", body: JSON.stringify({ snapshot, token, resolutions }) }),
  operationsSummary: () => api<OperationsSummary>("/api/operations/summary"),
  analyzeBusinessRequirement: (content: string) => api<BusinessRequirementAnalysis>("/api/ai/business/analyze", { method: "POST", body: JSON.stringify({ content }) }),
  createBusinessQuote: (analysis: BusinessRequirementAnalysis, complexity: "standard" | "advanced" | "complex", riskBuffer = 0.15) => api<BusinessQuote>("/api/ai/business/quote", { method: "POST", body: JSON.stringify({ analysis, complexity, risk_buffer: riskBuffer }) }),
  reviewBusinessProject: (payload: Record<string, unknown>) => api<BusinessReview>("/api/ai/business/review", { method: "POST", body: JSON.stringify(payload) }),
  productIntelligence: () => api<ProductIntelligenceView>("/api/products/intelligence"),
  collectProducts: () => api<ProductCollectionRunView>("/api/products/collect", { method: "POST" }),
  collectProductsManual: (externalId?: string) => api<ProductCollectionRunView>("/api/products/collect/manual", { method: "POST", body: JSON.stringify({ external_id: externalId || null }) }),
  registerProduct: (itemReference: string) => api<ProductView>("/api/products/register", { method: "POST", body: JSON.stringify({ item_reference: itemReference }) }),
  updateProductMonitor: (externalId: string, enabled: boolean) => api<ProductView>(`/api/products/${encodeURIComponent(externalId)}/monitor`, { method: "PUT", body: JSON.stringify({ enabled }) }),
  recordProductAction: (externalId: string, payload: { action_type: string; status: "planned" | "completed" | "cancelled"; note: string; cost: number; recommendation_id?: string | null; observation_days: number }) => api<ProductActionView>(`/api/products/${encodeURIComponent(externalId)}/actions`, { method: "POST", body: JSON.stringify(payload) }),
  updateProductRecommendation: (recommendationId: string, status: "active" | "in_progress" | "completed" | "dismissed") => api<void>(`/api/products/recommendations/${encodeURIComponent(recommendationId)}`, { method: "PUT", body: JSON.stringify({ status }) }),
  createTrafficBatch: (payload: { request_id: string; item_external_ids: string[]; planned_at: string; actual_cost: number; plan_slot_id?: string | null; note?: string }) => api<ProductTrafficBatchView>("/api/products/traffic-batches", { method: "POST", body: JSON.stringify(payload) }),
  startTrafficBatch: (batchId: string) => api<ProductTrafficBatchView>(`/api/products/traffic-batches/${encodeURIComponent(batchId)}/start`, { method: "POST" }),
  completeTrafficBatch: (batchId: string, payload: { completed_at: string; actual_cost: number; total_exposure?: number | null; note?: string }) => api<ProductTrafficBatchView>(`/api/products/traffic-batches/${encodeURIComponent(batchId)}/complete`, { method: "POST", body: JSON.stringify(payload) }),
  recordTrafficCheckpoint: (batchId: string, payload: { checkpoint: "h1" | "h6" | "h24" | "h72"; recorded_at: string; items: Array<{ external_id: string; browse_count: number; collect_count: number; want_count: number; inquiry_count: number }>; note?: string }) => api<ProductTrafficBatchView>(`/api/products/traffic-batches/${encodeURIComponent(batchId)}/checkpoints`, { method: "POST", body: JSON.stringify(payload) }),
  cancelTrafficBatch: (batchId: string) => api<ProductTrafficBatchView>(`/api/products/traffic-batches/${encodeURIComponent(batchId)}/cancel`, { method: "POST" }),
  refreshOperatingPlan: () => api<ProductOperatingPlanView>("/api/products/operating-plan/refresh", { method: "POST" }),
  updateOperatingPlanSlot: (slotId: string, locked: boolean) => api<ProductOperatingPlanView>(`/api/products/operating-plan/slots/${encodeURIComponent(slotId)}`, { method: "PUT", body: JSON.stringify({ locked }) }),
  marketReference: () => api<ProductMarketReferenceView>("/api/products/market-reference"),
  updateMarketKeyword: (payload: { mode: "recommended" | "custom"; keyword: string; save_as_common?: boolean }) => api<ProductMarketReferenceView>("/api/products/market-reference/keyword", { method: "PUT", body: JSON.stringify(payload) }),
  importMarketReference: (payload: { keyword: string; captured_at: string; results: Array<{ position: number; title: string; price: number | null; tags: string[] }>; note?: string }) => api<ProductMarketReferenceView>("/api/products/market-reference/import", { method: "POST", body: JSON.stringify(payload) }),
  snoozeMarketReminder: (hours = 2) => api<ProductMarketReferenceView>("/api/products/market-reference/reminder/snooze", { method: "POST", body: JSON.stringify({ hours }) }),
  skipMarketReminder: () => api<ProductMarketReferenceView>("/api/products/market-reference/reminder/skip", { method: "POST" }),
  createLaunchPlan: (payload: { keyword: string; title?: string | null }) => api<ProductLaunchPlanView>("/api/products/launch-plans", { method: "POST", body: JSON.stringify(payload) }),
  updateLaunchPlan: (planId: string, status: "proposed" | "planned" | "completed" | "cancelled") => api<ProductLaunchPlanView>(`/api/products/launch-plans/${encodeURIComponent(planId)}`, { method: "PUT", body: JSON.stringify({ status }) }),
  createModificationExperiment: (externalId: string, payload: { variable: "title" | "cover" | "description" | "price"; before_value: string; after_value: string; observation_days?: number }) => api<ProductModificationExperimentView>(`/api/products/${encodeURIComponent(externalId)}/modification-experiments`, { method: "POST", body: JSON.stringify(payload) }),
  updateModificationExperiment: (experimentId: string, payload: { decision: "keep" | "rollback" | "continue"; note?: string }) => api<ProductModificationExperimentView>(`/api/products/modification-experiments/${encodeURIComponent(experimentId)}`, { method: "PUT", body: JSON.stringify(payload) }),
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
