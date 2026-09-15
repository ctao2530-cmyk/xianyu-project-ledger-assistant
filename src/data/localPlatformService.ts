import type { LedgerSnapshot } from "../types";
import { localApi as api } from "./localApi";
import { productIntelligenceClient } from "./productIntelligenceClient";
import { customerImageClient } from "./customerImageClient";
import { customerConversationClient } from "./customerConversationClient";
import { customerAccessClient } from "./customerAccessClient";

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
  customer_reply_drafts_enabled?: boolean;
  customer_quote_conversion_enabled?: boolean;
}

export type CodexConnectionStatus = "not_connected" | "idle" | "running" | "blocked" | "failed" | "completed" | "disconnected";

export interface CodexTaskContext {
  task_key: string;
  title: string;
  stage_key: string | null;
  human_status: string;
  codex_execution_status: "todo" | "in_progress" | "blocked" | "implemented";
  estimated_hours: number;
  actual_hours: number;
  acceptance_points: unknown[];
  test_commands: string[];
}

export interface ProjectRequirementBlueprintView {
  case_id?: string | null;
  customer_id?: string | null;
  metrics?: Record<string, number>;
  diff?: Record<string, Record<string, {id: string; before: Record<string, unknown> | null; after: Record<string, unknown> | null}[]>>;
  id: number;
  project_id: string;
  version: number;
  schema_version: string;
  title: string;
  readiness: string;
  change_summary: string;
  source_type: string;
  source_label: string;
  source_filename: string;
  source_sha256: string;
  imported_at: string | null;
  created_at: string;
}

export interface RequirementProposalView {
  id: string; request_id: string; review_token: string; expected_version: number;
  document: RequirementBlueprint;
  diff: NonNullable<ProjectRequirementBlueprintView['diff']>;
}

export interface ProjectRequirementImportPreview {
  project_id: string;
  current_revision: number;
  next_version: number;
  preview_token: string;
  source_sha256: string;
  blueprint: Record<string, unknown>;
}

export type ProjectTaskDraftClassification = "new" | "unchanged" | "update_allowed" | "protected" | "conflict";

export interface ProjectTaskDraftItemView {
  id: string;
  task_key: string;
  workspace_key: string;
  stage_key: string;
  classification: ProjectTaskDraftClassification;
  current: Record<string, unknown>;
  proposed: Record<string, unknown>;
  protected_fields: string[];
  conflict_reason: string;
  selected: boolean;
  ordinal: number;
}

export interface ProjectTaskDraftPreviewView {
  id: string;
  project_id: string;
  requirement_version_id: number;
  requirement_version: number;
  source_label: string;
  project_revision: number;
  preview_token: string;
  status: string;
  summary: Record<ProjectTaskDraftClassification, number>;
  created_at: string;
  expires_at: string;
  items: ProjectTaskDraftItemView[];
}

export interface ProjectTaskDraftConfirmResult {
  project_id: string;
  preview_id: string;
  revision: number;
  created_task_ids: string[];
  updated_task_ids: string[];
  idempotent: boolean;
}

export interface CodexRunView {
  id: string;
  source: "mcp" | "hook" | "script" | "cli" | "ide" | string;
  external_session_id: string;
  external_turn_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  last_event_at: string;
}

export interface CodexSyncEventView {
  event_id: string;
  run_id: string;
  event_type: string;
  source: string;
  tool_name: string;
  task_key: string | null;
  task_mapped: boolean;
  summary: string;
  files: string[];
  remaining_work: string;
  blocker: string;
  command: string;
  exit_code: number | null;
  payload: Record<string, unknown>;
  occurred_at: string;
  received_at: string;
}

export interface CodexProjectSyncView {
  project_id: string;
  connection_status: CodexConnectionStatus;
  current_run: CodexRunView | null;
  current_task: CodexTaskContext | null;
  last_sync_at: string | null;
  runs: CodexRunView[];
  events: CodexSyncEventView[];
  counts: { files: number; commands: number; tests: number; blockers: number };
}

export interface CodexRuntimeCapabilities {
  runtime_type: string;
  available: boolean;
  version: string;
  supports_resume: boolean;
  supports_cancel: boolean;
  supports_approvals: boolean;
  supports_event_stream: boolean;
  detail: string;
}

export interface CodexManagedApproval {
  id: string;
  run_id: string;
  server_request_id: string;
  thread_id: string;
  turn_id: string;
  item_id: string;
  approval_kind: string;
  risk_level: "high" | "critical" | string;
  reason: string;
  command: string;
  cwd: string;
  status: string;
  created_at: string;
  decided_at: string | null;
}

export interface CodexManagedRun {
  id: string;
  project_id: string;
  binding_id: string | null;
  task_key: string | null;
  runtime_type: string;
  thread_id: string;
  turn_id: string;
  status: string;
  base_commit_sha: string;
  branch: string;
  worktree_path: string;
  model: string;
  reasoning_effort: string;
  sandbox_mode: string;
  approval_mode: string;
  started_at: string;
  paused_at: string | null;
  finished_at: string | null;
  last_event_at: string;
  approvals: CodexManagedApproval[];
}

export interface CodexManagedProjectView {
  project_id: string;
  runtime: CodexRuntimeCapabilities;
  tasks: CodexTaskContext[];
  binding: { id: string; repository_name: string; default_branch: string; current_head_sha: string; actual_head_sha?: string; repository_dirty?: boolean; head_matches?: boolean } | null;
  confirmed_plan_id: string | null;
  ready: boolean;
  readiness_reasons: string[];
  current_run: CodexManagedRun | null;
  runs: CodexManagedRun[];
  events: CodexSyncEventView[];
}

export interface CodexManagedDiff {
  run_id: string;
  base_commit_sha: string;
  branch: string;
  diff: string;
  truncated: boolean;
}

export type CodexAcceptanceStatus =
  | "pending"
  | "implemented"
  | "test_passed"
  | "verified"
  | "failed"
  | "waived";

export interface CodexProgressMetric {
  percent: number;
  completed_weight: number;
  total_weight: number;
}

export interface CodexProjectProgress {
  project_id: string;
  codex_execution: CodexProgressMetric;
  implemented: CodexProgressMetric;
  verified_delivery: CodexProgressMetric;
  weight_basis: string;
  warnings: string[];
  waived_count: number;
  waived_counted: number;
}

export interface CodexAcceptanceEvidence {
  id: string;
  point_id: string | null;
  point_key: string;
  run_id: string | null;
  evidence_type: string;
  file_paths: string[];
  test_command: string;
  exit_code: number | null;
  test_summary: string;
  commit_sha: string;
  manual_note: string;
  status: string;
  created_at: string;
  verified_at: string | null;
}

export interface CodexAcceptancePoint {
  id: string;
  task_id: string;
  task_key: string | null;
  task_title: string;
  point_key: string;
  title: string;
  verification_type: string;
  source: "codex_plan" | "manual_historical" | string;
  status: CodexAcceptanceStatus;
  point_weight: number | null;
  waived_counts: boolean;
  waiver_reason: string;
  active: boolean;
  verified_at: string | null;
  updated_at: string;
  evidence: CodexAcceptanceEvidence[];
}

export interface CodexTimeEntry {
  id: string;
  task_id: string | null;
  run_id: string | null;
  category: string;
  source: string;
  hours: number;
  note: string;
  adjustment_of_id: string | null;
  started_at: string | null;
  ended_at: string | null;
  occurred_at: string;
}

export interface CodexTimeSummary {
  total_hours: number;
  codex_hours: number;
  manual_hours: number;
  by_category: Record<string, number>;
  estimated_hours: number;
  variance_hours: number;
  variance_percent: number | null;
  entries: CodexTimeEntry[];
}

export interface CodexGitState {
  available: boolean;
  repository_name: string;
  branch: string;
  base_commit: string;
  current_commit: string;
  dirty: boolean;
  changed_files: string[];
  commits: Array<{ sha?: string; subject?: string; authored_at?: string; [key: string]: string | undefined }>;
  error: string;
}

export interface CodexGitLink {
  id: string;
  task_id: string;
  point_id: string | null;
  commit_sha: string;
  branch: string;
  status: string;
  note: string;
  created_at: string;
}

export interface CodexDeliveryTask {
  task_id: string;
  task_key: string | null;
  title: string;
  estimated_hours: number;
  actual_hours: number;
  acceptance_total: number;
  acceptance_verified: number;
  acceptance_waived: number;
  tests_passed: number;
  commits: string[];
  open_issues: string[];
}

export interface CodexDeliveryChecklist {
  project_id: string;
  plan_id: string | null;
  deliverables: Array<{
    deliverable_key: string;
    title: string;
    description: string;
    task_ids: string[];
    acceptance_total: number;
    acceptance_verified: number;
  }>;
  tasks: CodexDeliveryTask[];
  delivery_files: string[];
  unresolved_issues: string[];
  generated_at: string;
}

export interface CodexProjectOutcome {
  project_id: string;
  requirement_complexity: number | null;
  estimated_hours: number;
  actual_hours: number;
  estimated_delivery_at: string;
  actual_completed_at: string | null;
  blocker_count: number;
  change_order_count: number;
  test_failure_count: number;
  rework_hours: number;
  verified_progress: number;
  revenue: number;
  profit: number;
  realized_hourly_rate: number;
  available_at: string;
  finalized_at: string | null;
}

export interface ProjectOutcomeFreezeView {
  id: string;
  project_id: string;
  version: number;
  supersedes_freeze_id: string | null;
  source_ledger_revision: number;
  input_hash: string;
  outcome: CodexProjectOutcome;
  evidence_summary: Record<string, number | string | boolean>;
  confirmed_scope_complete: boolean;
  confirmed_time_complete: boolean;
  confirmation_note: string;
  frozen_at: string;
  created_at: string;
  is_stale: boolean;
}

export interface ProjectSampleReadiness {
  project_id: string;
  status: "missing_scope" | "needs_verification" | "needs_time" | "terminal" | "ready_to_freeze" | "frozen" | "stale";
  can_freeze: boolean;
  calibration_eligible: boolean;
  active_task_count: number;
  active_point_count: number;
  verified_point_count: number;
  waived_point_count: number;
  estimated_hours: number;
  actual_hours: number;
  verified_progress: number;
  blockers: Array<{ code: string; message: string; action: string }>;
  latest_freeze: ProjectOutcomeFreezeView | null;
  freeze_history: ProjectOutcomeFreezeView[];
}

export interface CodexProjectVerificationView {
  revision: number;
  project_id: string;
  legacy_progress: number | null;
  progress_source: string;
  progress: CodexProjectProgress;
  points: CodexAcceptancePoint[];
  time: CodexTimeSummary;
  git: CodexGitState;
  git_links: CodexGitLink[];
  delivery: CodexDeliveryChecklist;
  outcome: CodexProjectOutcome;
  sample_readiness: ProjectSampleReadiness;
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
  images?: CustomerImageArchiveView[];
  customer_images?: CustomerImageArchiveView[];
  source_item_title?: string | null;
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
  has_older_messages: boolean;
  pending_message_id: number | null;
  drafts: ReplyDraft[];
  ai_task: { id: number; provider: string; model?: string | null; status: string; risk_level?: string | null; risk_reasons?: string[]; error_code?: string | null; error_message?: string | null; started_at?: string | null; finished_at?: string | null; duration_seconds?: number | null } | null;
}

export interface PhraseSnippetView {
  id: string;
  category_id: string;
  content: string;
  position: number;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface PhraseCategoryView {
  id: string;
  category_key: string;
  name: string;
  source: "default" | "custom" | string;
  position: number;
  active: boolean;
  phrases: PhraseSnippetView[];
  created_at: string;
  updated_at: string;
}

export interface PhraseLibraryView {
  revision: number;
  categories: PhraseCategoryView[];
  idempotent: boolean;
}

export interface CustomerImageArchiveView {
  id: string;
  conversation_id: number;
  message_id: number;
  channel: "xianyu" | "wechat" | string;
  customer_name: string;
  received_at: string;
  captured_at: string | null;
  mime_type: string;
  original_name: string;
  file_size: number;
  width: number;
  height: number;
  integrity_verified: boolean;
  content_url: string;
  download_url: string;
  archive_id?: string;
  capture_status?: string;
  status?: string;
  media_index?: number;
  error_code?: string | null;
  error_message?: string | null;
  preview_url?: string | null;
  source_item_id?: string | null;
  source_item_title?: string | null;
}

export interface CustomerImageListView {
  items: CustomerImageArchiveView[];
  total: number;
  has_more: boolean;
}

export interface CustomerImageArchiveStatus {
  state: "healthy" | "needs_attention";
  stored_count: number;
  attention_count: number;
  failed_count: number;
  pending_count: number;
  missing_count: number;
  candidate_count: number;
  channel_counts: Record<string, number>;
  last_captured_at: string | null;
  message: string;
}

export interface CustomerImageFilters {
  channels: string[];
  conversations: Array<{ id: number; customer_name: string; channel: string; image_count: number }>;
  items?: Array<{ id: string; title: string }>;
}

export interface CustomerImageHistoryPreview {
  candidate_count: number;
  channel_counts: Record<string, number>;
  related_conversation_count: number;
  automatic: true;
  connection_status: string;
  can_recover: boolean;
  notice: string;
}

export interface CustomerImageHistoryResult {
  conversation_count: number;
  checked_conversation_count: number;
  stored_count: number;
  unmatched_count: number;
  failed_count: number;
  failed_conversations: Array<{ conversation_id: number; customer_name: string; error_code: string }>;
  stopped_early: boolean;
  action_hint: string;
  idempotent: boolean;
  status: CustomerImageArchiveStatus;
}

export interface CustomerImageAttentionItem {
  message_id: number;
  conversation_id: number;
  channel: "xianyu" | "wechat" | string;
  customer_name: string;
  received_at: string;
  status: "failed" | "pending" | "missing";
  error_code: string;
}

export interface ConversationHistorySearchItem {
  external_conversation_id: string;
  customer_name: string;
  item_title: string | null;
  last_message: string;
  last_message_at: string;
  direction: "inbound" | "outbound";
  existing_conversation_id: number | null;
  known_message_count: number;
}

export interface ConversationHistoryPreviewMessage {
  platform_message_id: string;
  sender_name: string;
  direction: "inbound" | "outbound";
  message_type: string;
  content: string;
  received_at: string;
  import_status: "new" | "existing" | "unsupported";
}

export interface ConversationHistoryPreview {
  token: string;
  expires_at: string;
  external_conversation_id: string;
  customer_name: string;
  item: { external_id: string; title: string; price?: string | null } | null;
  item_warning: string | null;
  messages: ConversationHistoryPreviewMessage[];
  platform_message_count: number;
  existing_count: number;
  new_count: number;
  image_candidate_count?: number;
  unsupported_count: number;
  history_scope: "recent" | "full" | "page";
  has_more?: boolean;
  next_continuation_token?: string | null;
  history_complete?: boolean;
}

export interface ConversationMessagePage {
  messages: ConversationMessage[];
  has_more: boolean;
}

export interface ConversationHistoryCommitResult {
  conversation_id: number;
  created_conversation: boolean;
  platform_message_count: number;
  imported_count: number;
  existing_count: number;
  pending_message_id: number | null;
  draft_task_queued: boolean;
  draft_task_id: number | null;
  image_candidate_count: number;
  image_stored_count: number;
  image_failed_count: number;
  idempotent: boolean;
  has_more?: boolean;
  next_continuation_token?: string | null;
  history_complete?: boolean;
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

export type ConnectionRecoveryTarget = "xianyu" | "deepseek" | "codex_cli";

export interface ConnectionRecoveryResult {
  provider: ConnectionRecoveryTarget;
  status: string;
  detail: string;
  configured: boolean;
  persisted: boolean;
  repair_command: string | null;
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
  evidence_refs: Array<{ id: string; message_number?: number | null; message_id?:number | null; archive_id?:string | null; conversation_id?:number | null; quote: string }>;
}

export interface ProductRegistrationCandidate {
  external_id: string;
  title: string;
  price: number | null;
  status: string;
  ownership_status: "owned" | "pending" | "excluded" | string;
  already_registered: boolean;
  monitoring_enabled: boolean;
  can_register: boolean;
  blocked_reason: string | null;
}

export interface ProductRegistrationPreview {
  token: string;
  expires_at: string;
  source: "account_listing" | "shared_reference" | string;
  items: ProductRegistrationCandidate[];
  warnings: string[];
}

export interface ProductRegistrationCommitResult {
  products: ProductView[];
  registered_count: number;
  already_registered_count: number;
  idempotent: boolean;
}

export interface ProductMonitorBatchDisableResult {
  disabled_external_ids: string[];
  disabled_count: number;
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

export interface CodexRepositoryBinding {
  id: string;
  requirement_case_id: string | null;
  project_id: string | null;
  repository_name: string;
  default_branch: string;
  current_head_sha: string;
  enabled: boolean;
  updated_at: string;
  idempotent: boolean;
}

export interface CodexPlanDocument {
  schema_version: "1.0";
  title: string;
  summary: string;
  repository_snapshot: { mode: "requirement_only" | "repository"; head_sha: string; branch: string; dirty: boolean };
  estimate: { low_hours: number; expected_hours: number; high_hours: number; confidence: "low" | "medium" | "high" };
  assumptions: string[];
  risks: string[];
  deliverables: Array<{ deliverable_key: string; title: string; description: string; acceptance_criteria: string[] }>;
  stages: Array<{ stage_key: string; title: string; estimated_hours: number; depends_on: string[]; deliverable_keys: string[] }>;
  tasks: Array<{
    task_key: string; stage_key: string; title: string; description: string; estimated_hours: number;
    depends_on: string[]; expected_paths: string[];
    acceptance_points: Array<{ point_key: string; title: string; verification_type: "automated_test" | "manual_test" | "visual_review" | "document_review" }>;
    test_commands: string[]; risks: string[]; included: boolean; note: string;
  }>;
}

export interface CodexDevelopmentPlan {
  id: string;
  requirement_case_id: string;
  requirement_version_id: number;
  requirement_version: number;
  project_id: string | null;
  binding_id: string | null;
  version: number;
  status: "draft" | "confirmed" | "superseded" | "cancelled";
  source: string;
  repository_name: string | null;
  repository_mode: "requirement_only" | "repository";
  repository_head_sha: string;
  repository_branch: string;
  repository_dirty: boolean;
  raw_document: CodexPlanDocument;
  document: CodexPlanDocument;
  model: string;
  reasoning_effort: string | null;
  created_at: string;
  updated_at: string;
  confirmed_at: string | null;
  idempotent: boolean;
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
  project_expense_total: number;
  project_refund_total: number;
  profit_is_realtime: boolean;
  linked_projects: Array<{
    project_id: string;
    project_name: string;
    relation_source: "project_binding" | "conversation_compatibility" | string;
    latest_confirmed_at: string | null;
    confirmed_total: number;
    net_confirmed_total: number;
    expense_total: number;
    refund_total: number;
    profit_total: number;
  }>;
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
  change_factors: string[];
  evidence: string[];
  warnings: string[];
  confidence: string;
  locked: boolean;
  lock_mode: "none" | "stability" | "manual" | string;
  lock_label: string | null;
  cooldown_conflict_count: number;
  cooldown_until: string | null;
  status: string;
  batch_id: string | null;
  source_batch_id: string | null;
  availability_at: string | null;
  is_new_spend: boolean;
  rotation_summary: Record<string, unknown>;
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
  change_factors: string[];
  data_quality: string;
  rules_version: string;
  analysis_stage: string;
  effective_batch_count: number;
  slots: ProductOperatingPlanSlotView[];
}

export interface ProductTrafficItemCheckpointView {
  checkpoint: "h1" | "h6" | "h24" | "h48" | "h72" | string;
  hours: number;
  recorded_at: string;
  browse_count: number;
  collect_count: number;
  want_count: number;
  inquiry_count: number;
  browse_delta: number;
  collect_delta: number;
  want_delta: number;
  inquiry_delta: number;
}

export interface ProductTrafficExploratoryPointView {
  key: string;
  label: string;
  source: "checkpoint" | "daily_snapshot" | string;
  recorded_at: string;
  browse_count: number;
  collect_count: number;
  want_count: number;
  inquiry_count: number;
  browse_change: number;
  collect_change: number;
  want_change: number;
  inquiry_change: number;
}

export interface ProductTrafficBatchItemView {
  external_id: string;
  title: string;
  baseline_browse_count: number;
  baseline_collect_count: number;
  baseline_want_count: number;
  baseline_inquiry_count: number;
  baseline_captured_at: string | null;
  baseline_source: "pending" | "remote_refresh" | "manual" | "legacy_snapshot" | "missing" | string;
  latest_checkpoint: string | null;
  latest_browse_count: number;
  latest_collect_count: number;
  latest_want_count: number;
  latest_inquiry_count: number;
  browse_delta: number;
  collect_delta: number;
  want_delta: number;
  inquiry_delta: number;
  checkpoints: ProductTrafficItemCheckpointView[];
  exploratory_points: ProductTrafficExploratoryPointView[];
}

export interface ProductTrafficCheckpointMetricsView {
  checkpoint: "h1" | "h6" | "h24" | "h48" | "h72" | string;
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

export interface ProductTrafficCheckpointJobItemView {
  external_id: string;
  title: string;
  status: "pending" | "completed" | "failed" | "protection_skipped" | string;
  captured_at: string | null;
  error_code: string | null;
  error_detail: string;
}

export interface ProductTrafficCheckpointJobView {
  checkpoint: "h1" | "h6" | "h24" | "h48" | "h72" | string;
  hours: number;
  scheduled_for: string;
  status: "scheduled" | "waiting_connection" | "collecting" | "partial" | "waiting_manual" | "completed" | "missed" | "circuit_open" | string;
  mode: "auto" | "manual" | string;
  attempt_count: number;
  collected_count: number;
  total_count: number;
  captured_at: string | null;
  completed_at: string | null;
  capture_delay_minutes: number | null;
  last_error_code: string | null;
  last_error_detail: string;
  can_retry_auto: boolean;
  can_complete_manually: boolean;
  items: ProductTrafficCheckpointJobItemView[];
}

export interface ProductTrafficBatchView {
  id: string;
  plan_slot_id: string | null;
  status: "planned" | "running" | "observing" | "closed" | "invalidated" | "cancelled" | string;
  planned_at: string;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
  baseline_prepared_at: string | null;
  recording_mode: "standard" | "actual_overlap" | "scale_cohort" | string;
  attribution_status: "clean" | "overlap" | "cohort_overlap" | string;
  invalidated_at: string | null;
  invalidation_reason: "missing_baseline" | "legacy_baseline" | "stale_baseline" | "invalid_baseline_time" | string | null;
  invalidation_label: string | null;
  checkpoint_collection_mode: "auto" | "manual" | string;
  observation_window_hours: 48 | 72 | number;
  terminal_checkpoint: "h48" | "h72" | string;
  checkpoint_sequence: Array<"h1" | "h6" | "h24" | "h48" | "h72" | string>;
  is_legacy_protocol: boolean;
  observation_title: string;
  checkpoint_jobs: ProductTrafficCheckpointJobView[];
  has_reliable_baseline: boolean;
  baseline_expires_at: string | null;
  baseline_status: "pending" | "ready" | "expired" | "used" | "legacy" | string;
  baseline_status_label: string;
  can_prepare_baseline: boolean;
  can_start: boolean;
  planned_actual_delta_minutes: number | null;
  planned_actual_delta_label: string | null;
  needs_replan: boolean;
  replan_reason: string | null;
  actual_cost: number;
  total_exposure: number | null;
  note: string;
  products: ProductTrafficBatchItemView[];
  completed_checkpoints: string[];
  due_checkpoint: "h1" | "h6" | "h24" | "h48" | "h72" | null;
  due_at: string | null;
  due_ready: boolean;
  checkpoint_progress: number;
  baseline_age_minutes: number | null;
  baseline_quality: "fresh" | "weak" | "missing" | "planned" | string;
  baseline_quality_label: string;
  baseline_quality_detail: string;
  overlap_warning: string | null;
  start_blocked: boolean;
  start_blocked_reason: string | null;
  start_blocked_until: string | null;
  browse_delta: number;
  collect_delta: number;
  want_delta: number;
  inquiry_delta: number;
  inquiry_conversion_rate: number | null;
  cost_per_browse: number | null;
  cost_per_inquiry: number | null;
  observation_checkpoint: "h1" | "h6" | "h24" | "h48" | "h72" | null;
  observation_hours: number;
  time_bucket: string;
  data_quality: string;
  analysis_eligible: boolean;
  analysis_tier: "fact_only" | "exploratory" | "decision_grade" | string;
  analysis_tier_label: string;
  analysis_confidence: "low" | "medium" | "high" | string;
  exploratory_available: boolean;
  exploratory_reference_source: "checkpoint" | "daily_snapshot" | string | null;
  exploratory_reference_label: string | null;
  exploratory_reference_at: string | null;
  exploratory_through_label: string | null;
  exploratory_through_at: string | null;
  observed_browse_change: number;
  observed_collect_change: number;
  observed_want_change: number;
  observed_inquiry_change: number;
  natural_browse_low: number | null;
  natural_browse_high: number | null;
  natural_sample_size: number;
  natural_item_count: number;
  control_browse_expected: number | null;
  control_item_count: number;
  control_adjusted_browse_change: number | null;
  directional_browse_low: number | null;
  directional_browse_high: number | null;
  exploratory_summary: string | null;
  analysis_limitations: string[];
  exploratory_points: ProductTrafficExploratoryPointView[];
  checkpoint_metrics: ProductTrafficCheckpointMetricsView[];
  created_at: string;
}

export interface ProductTrafficStartPreviewView {
  batch: ProductTrafficBatchView;
  can_start: boolean;
  can_start_clean: boolean;
  can_start_cohort: boolean;
  can_record_actual: boolean;
  blocked_reasons: string[];
  ownership_ready: boolean;
  baseline_status: string;
  baseline_expires_at: string | null;
  earliest_start_at: string | null;
  cooldown_until: string | null;
  overlap_items: Array<{
    external_id: string;
    title: string;
    source_batch_id: string;
    source_started_at: string;
    cooldown_until: string;
  }>;
  conflicting_batches: Array<{
    batch_id: string;
    started_at: string;
    cooldown_until: string;
    item_count: number;
    item_external_ids: string[];
  }>;
  analysis_impact: string;
  safety_notice: string;
  actions: Array<"start" | "remote_refresh" | "manual" | "remove_overlap" | "replan" | "wait" | "actual_start" | string>;
}

export interface ProductTrafficReplanPreviewView {
  batch_id: string;
  updated_at: string;
  preview_hash: string;
  can_replan: boolean;
  proposed_planned_at: string;
  current_products: ProductPlanProductView[];
  proposed_products: ProductPlanProductView[];
  retained_products: ProductPlanProductView[];
  removed_products: ProductPlanProductView[];
  added_products: ProductPlanProductView[];
  source_batch_id: string | null;
  availability_at: string | null;
  is_new_spend: boolean;
  fee_impact: number;
  reasons: string[];
  warnings: string[];
}

export interface ProductTrafficBatchPageView {
  items: ProductTrafficBatchView[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface ProductTrafficMetricsInput {
  external_id: string;
  browse_count: number;
  collect_count: number;
  want_count: number;
  inquiry_count: number;
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

export interface TrafficGrowthProductView {
  external_id: string;
  title: string;
  historical_project_count: number;
  historical_realized_profit: number;
  historical_profit_is_attributed: boolean;
}

export interface TrafficExperimentCellView {
  id: string;
  phase: "exploration" | "confirmation" | "off_matrix" | string;
  window_bucket: string;
  time_range: string;
  repeat_index: number;
  status: string;
  scheduled_for: string | null;
  batch_id: string | null;
  actual_bucket: string | null;
  exclusion_reason: string | null;
  browse_delta: number | null;
  inquiry_delta: number | null;
  analysis_eligible: boolean;
}

export interface TrafficTimeWindowResultView {
  window_bucket: string;
  time_range: string;
  valid_batch_count: number;
  browse_delta: number;
  inquiry_delta: number;
  average_browse_delta: number;
  average_inquiry_delta: number;
  rank: number | null;
  provisional_winner: boolean;
  confirmed_winner: boolean;
}

export interface TrafficScaleCohortView {
  id: string;
  stage: "S1" | "S2" | "S3" | string;
  status: string;
  target_batches_per_week: number;
  weekly_budget: number;
  no_other_promotion_confirmed: boolean;
  listing_unchanged_confirmed: boolean;
  started_at: string | null;
  ended_at: string | null;
  tail_ends_at: string | null;
  commercial_followup_ends_at: string | null;
  batch_ids: string[];
  batch_count: number;
  actual_cost: number;
}

export interface TrafficCommercialAttributionView {
  id: string;
  scope: "batch" | "cohort" | string;
  cohort_id: string | null;
  batch_id: string | null;
  conversation_id: number;
  project_id: string | null;
  project_name: string | null;
  status: "candidate" | "confirmed" | "rejected" | string;
  source: string;
  first_inbound_at: string;
  window_start: string;
  window_end: string;
  confirmed_by_user_at: string | null;
  realized_profit: number;
  updated_at: string;
}

export interface TrafficGrowthMetricsView {
  actual_cost: number;
  attributed_inquiry_count: number;
  paid_project_count: number;
  realized_contribution_profit: number;
  profit_to_cost_ratio: number | null;
  net_after_traffic: number;
  active_projects: number;
  delivery_capacity: number;
  observation_complete: boolean;
  limitations: string[];
}

export interface TrafficBudgetDecisionView {
  id: string | null;
  recommendation: "scale" | "hold" | "reduce" | "pause";
  status: string;
  from_stage: "T0" | "S1" | "S2" | "S3" | string;
  to_stage: "T0" | "S1" | "S2" | "S3" | string;
  current_weekly_budget: number;
  recommended_weekly_budget: number;
  metrics: TrafficGrowthMetricsView;
  evidence: string[];
  rules_version: string;
  decided_at: string;
  applied_at: string | null;
  can_apply: boolean;
}

export interface TrafficExperimentView {
  id: string;
  mode: "time_test" | "scale_cohort" | string;
  status: "active" | "paused" | "completed" | string;
  phase: string;
  product: TrafficGrowthProductView;
  target_windows: string[];
  baseline_weekly_budget: number;
  current_weekly_budget: number;
  hard_weekly_cap: number;
  base_batch_cost: number;
  started_at: string;
  completed_at: string | null;
  valid_exploration_batches: number;
  required_exploration_batches: number;
  valid_confirmation_batches: number;
  required_confirmation_batches: number;
  provisional_winner: string | null;
  confirmed_winner: string | null;
  cells: TrafficExperimentCellView[];
  time_windows: TrafficTimeWindowResultView[];
  cohorts: TrafficScaleCohortView[];
  attributions: TrafficCommercialAttributionView[];
  metrics: TrafficGrowthMetricsView;
  budget_decision: TrafficBudgetDecisionView;
  next_cell: TrafficExperimentCellView | null;
  warnings: string[];
  updated_at: string;
}

export interface TrafficGrowthOverviewView {
  active_experiment: TrafficExperimentView | null;
  historical_experiments: TrafficExperimentView[];
  recommended_candidate: TrafficGrowthProductView | null;
  safety_notice: string;
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
    planned_batch_count: number;
    observation_batch_count: number;
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

export interface CustomerIntakeCandidate {
  conversation_id: number;
  channel: string;
  customer_name: string;
  customer_source: "xianyu" | "wechat" | "referral" | "other";
  last_message_at: string | null;
  last_text_preview: string;
  same_name_exists: boolean;
}

export interface CustomerIntakeCandidatesView {
  revision: number;
  candidates: CustomerIntakeCandidate[];
}

export interface CustomerCreatePayload {
  request_id: string;
  expected_revision: number;
  confirmed: true;
  conversation_id: number | null;
  name: string;
  source: "xianyu" | "wechat" | "referral" | "other";
  phone: string;
  level: "A" | "B" | "C";
  current_need: string;
  price_type: "" | "customer_budget" | "operator_quote" | "agreed_price";
  price_amount: number | null;
  next_action: string;
  notes: string;
}

export interface CustomerCreateResult {
  revision: number;
  snapshot: LedgerSnapshot;
  customer_id: string;
  conversation_id: number | null;
  created: boolean;
  idempotent: boolean;
}

export type GlobalAgentProvider = "codex_cli" | "deepseek" | "openai_compatible";
export type GlobalAgentTargetPage = "" | "home" | "products" | "customers" | "projects" | "finance" | "business-analysis" | "settings";

export interface GlobalAgentProfile {
  id: string;
  provider: GlobalAgentProvider;
  model: string;
  reasoning_effort: string;
  label: string;
  enabled: boolean;
  is_default: boolean;
  configured: boolean;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface GlobalAgentModelOption {
  model: string;
  display_name: string;
  default_reasoning_effort: string | null;
  supported_reasoning_efforts: string[];
}

export interface GlobalAgentKnowledgeCitation {
  id: string;
  relative_path: string;
  absolute_path: string;
  title: string;
  heading: string;
  snippet: string;
  maturity: string;
  content_hash: string;
}

export interface GlobalAgentToolReference {
  id: string;
  name: string;
  label: string;
  status: string;
  duration_ms: number;
  source: string;
  observed_at: string | null;
  revision: number | null;
  read_only: boolean;
  sensitivity: string;
}

export interface GlobalAgentFact {
  text: string;
  evidence_refs: string[];
}

export interface GlobalAgentRequirementAnalysisItem {
  text: string;
  evidence_refs: string[];
}

export interface GlobalAgentRequirementRisk {
  id: string;
  title: string;
  description: string;
  severity: "low" | "medium" | "high";
  mitigation: string;
  evidence_refs: string[];
}

export interface GlobalAgentRequirementAnalysis {
  maturity: "discovery" | "clarifying" | "ready";
  summary: string;
  customer_confirmed: GlobalAgentRequirementAnalysisItem[];
  operator_decisions: GlobalAgentRequirementAnalysisItem[];
  unconfirmed: GlobalAgentRequirementAnalysisItem[];
  constraints: GlobalAgentRequirementAnalysisItem[];
  open_questions: string[];
  assumptions: string[];
  risks: GlobalAgentRequirementRisk[];
}

export interface GlobalAgentRequirementBlueprint {
  title: string;
  maturity: "discovery" | "clarifying" | "ready";
  objectives: Array<{ id: string; title: string; description: string; evidence_refs: string[] }>;
  capabilities: Array<{ id: string; title: string; description: string; objective_ids: string[]; priority: "must" | "should" | "could"; evidence_refs: string[] }>;
  stages: Array<{ id: string; title: string; objective: string; capability_ids: string[]; dependency_ids: string[]; work_items: string[]; deliverables: string[]; estimated_hours: number | null; evidence_refs: string[] }>;
  acceptance_gates: Array<{ id: string; title: string; description: string; stage_ids: string[]; criteria: string[]; evidence_refs: string[] }>;
  out_of_scope: string[];
  assumptions: string[];
  open_questions: string[];
  risks: GlobalAgentRequirementRisk[];
}

export interface GlobalAgentExecutionPlanStage {
  id: string;
  task_key: string;
  workspace_key: string;
  title: string;
  objective: string;
  dependency_task_keys: string[];
  allowed_changes: string[];
  deliverables: string[];
  process_tests: string[];
  acceptance_criteria: string[];
  stop_conditions: string[];
  evidence_refs: string[];
}

export interface GlobalAgentExecutionPlan {
  title: string;
  objective: string;
  readiness: "discovery" | "clarifying" | "ready";
  change_summary: string;
  allowed_changes: string[];
  must_not_change: string[];
  out_of_scope: string[];
  stages: GlobalAgentExecutionPlanStage[];
  assumptions: string[];
  open_questions: string[];
  risks: GlobalAgentRequirementRisk[];
}

export interface GlobalAgentCustomerProposalText {
  value: string;
  evidence_refs: string[];
}

export interface GlobalAgentCustomerCreateProposal {
  conversation_id: number;
  customer_name: GlobalAgentCustomerProposalText;
  phone: GlobalAgentCustomerProposalText;
  source: "xianyu" | "wechat" | "other";
  level: "A" | "B" | "C";
  current_need: GlobalAgentCustomerProposalText;
  price: {
    price_type: "" | "customer_budget" | "operator_quote" | "agreed_price";
    amount: number | null;
    evidence_refs: string[];
  };
  next_action: GlobalAgentCustomerProposalText;
  notes: GlobalAgentCustomerProposalText;
}

export interface GlobalAgentAnswer {
  conclusion: string;
  facts: GlobalAgentFact[];
  causes: string[];
  knowledge_citation_ids: string[];
  limitations: string[];
  confidence: "low" | "medium" | "high";
  observation_period: string;
  next_step: string;
  target_page: GlobalAgentTargetPage;
  updated_customer_context?: GlobalAgentCustomerSummary | null;
  requirement_analysis?: GlobalAgentRequirementAnalysis | null;
  requirement_blueprint?: GlobalAgentRequirementBlueprint | null;
  execution_plan?: GlobalAgentExecutionPlan | null;
  customer_create_proposal?: GlobalAgentCustomerCreateProposal | null;
}

export type CustomerContextAudience = "openai_chatgpt" | "openai_api" | "codex_cli";

export interface CustomerContextGrant {
  id: string;
  thread_id: string;
  conversation_id: number;
  provider_scope: "openai";
  audience: CustomerContextAudience;
  allow_text: boolean;
  allow_images: boolean;
  allow_artifacts: boolean;
  allow_new_messages: boolean;
  consent_policy_version: string;
  consent_text_hash: string;
  status: "active" | "expired" | "revoked";
  revision: number;
  thread_revision: number;
  authorization_note: string;
  confirmed_at: string;
  expires_at: string;
  revoked_at: string | null;
  created_at: string;
  updated_at: string;
  capability_token?: string | null;
  idempotent?: boolean;
}

export interface CustomerConversationAccessState {
  conversation_id: number;
  revision: number;
  latest_grant: CustomerContextGrant | null;
}

export interface CustomerContextTunnelBindingState {
  auth_mode: "oauth" | "tunnel_binding";
  configured: boolean;
  header_name: string;
  slot: "openai_chatgpt";
  revision: number;
  active: boolean;
  grant: CustomerContextGrant | null;
  idempotent?: boolean;
}

export interface CustomerContextThreadBinding {
  id: string;
  auth_mode: "oauth" | "tunnel_binding";
  context_key_hint: string;
  status: "active" | "expired" | "revoked";
  revision: number;
  active: boolean;
  identity_claimed: boolean;
  expires_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
  grant: CustomerContextGrant | null;
  context_key?: string | null;
  idempotent?: boolean;
}

export interface CustomerContextThreadBindingList {
  auth_mode: "oauth" | "tunnel_binding";
  configured: boolean;
  legacy_binding_active: boolean;
  legacy_grant: CustomerContextGrant | null;
  bindings: CustomerContextThreadBinding[];
}

export interface CustomerAnalysisSubscription {
  id: string;
  thread_id: string;
  conversation_id: number;
  provider_scope: "openai";
  model: string;
  configured: boolean;
  external_conversation_ready: boolean;
  status: "active" | "paused";
  analysis_state: "waiting" | "pending" | "analyzing" | "completed" | "failed" | "configuration_required";
  include_images: boolean;
  debounce_seconds: number;
  max_wait_seconds: number;
  last_enqueued_message_id: number | null;
  last_analyzed_message_id: number | null;
  latest_message_id: number | null;
  pending_message_count: number;
  latest_artifact_version: number;
  next_run_at: string | null;
  last_started_at: string | null;
  last_completed_at: string | null;
  last_error_code: string;
  last_error_message: string;
  consent_policy_version: string;
  consent_text_hash: string;
  authorization_note: string;
  confirmed_at: string;
  revision: number;
  paused_at: string | null;
  created_at: string;
  updated_at: string;
  idempotent?: boolean;
}

export interface GlobalAgentCustomerSummaryItem {
  text: string;
  evidence_message_ids: number[];
}

export interface GlobalAgentCustomerSummary {
  goals: GlobalAgentCustomerSummaryItem[];
  confirmed_requirements: GlobalAgentCustomerSummaryItem[];
  unconfirmed_requirements: GlobalAgentCustomerSummaryItem[];
  constraints: GlobalAgentCustomerSummaryItem[];
  decisions: GlobalAgentCustomerSummaryItem[];
  recent_changes: GlobalAgentCustomerSummaryItem[];
  pending_questions: GlobalAgentCustomerSummaryItem[];
  risks: GlobalAgentCustomerSummaryItem[];
}

export interface GlobalAgentCustomerContextOption {
  conversation_id: number;
  customer_id: string | null;
  channel: string;
  customer_name: string;
  item_title: string | null;
  text_message_count: number;
  image_message_count?: number;
  latest_text_message_id: number | null;
  latest_message_at: string | null;
  summary_version: number | null;
  summarized_through_message_id: number | null;
  new_message_count: number;
  context_updated: boolean;
}

export type GlobalAgentCustomerContextState = GlobalAgentCustomerContextOption;

export interface GlobalAgentMessage {
  id: string;
  thread_id: string;
  role: "user" | "assistant";
  content: string;
  status: string;
  run_id: string | null;
  run_elapsed_ms: number | null;
  answer: GlobalAgentAnswer | null;
  citations: GlobalAgentKnowledgeCitation[];
  tool_references: GlobalAgentToolReference[];
  created_at: string;
}

export interface GlobalAgentRun {
  id: string;
  request_id: string;
  thread_id: string;
  user_message_id: string;
  assistant_message_id: string | null;
  provider: GlobalAgentProvider;
  model: string;
  reasoning_effort: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled" | "interrupted";
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export type GlobalAgentRunStepStatus = "pending" | "running" | "completed" | "failed" | "cancelled" | "interrupted" | "skipped";
export type GlobalAgentRunTracePhase = "context" | "evidence" | "tools" | "generate" | "validate" | "persist";

export interface GlobalAgentRunStep {
  id: string;
  position: number;
  node_name: string;
  label: string;
  phase: GlobalAgentRunTracePhase;
  status: GlobalAgentRunStepStatus;
  summary: string;
  duration_ms: number;
  started_at: string | null;
  completed_at: string | null;
}

export interface GlobalAgentRunTool {
  id: string;
  position: number;
  name: string;
  label: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled" | "interrupted";
  summary: string;
  duration_ms: number;
  source: string;
  observed_at: string | null;
  revision: number | null;
  read_only: boolean;
  sensitivity: string;
  created_at: string;
}

export interface GlobalAgentRunTrace {
  run_id: string;
  thread_id: string;
  provider: GlobalAgentProvider;
  model: string;
  status: GlobalAgentRun["status"];
  completed_steps: number;
  total_steps: number;
  tool_count: number;
  elapsed_ms: number;
  decision_summary: string;
  legacy: boolean;
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  steps: GlobalAgentRunStep[];
  tools: GlobalAgentRunTool[];
}

export interface GlobalAgentThread {
  id: string;
  title: string;
  profile_id: string | null;
  provider: GlobalAgentProvider;
  model: string;
  reasoning_effort: string;
  context_scope: "general_business" | "customer_conversation";
  customer_context: GlobalAgentCustomerContextState | null;
  status: string;
  revision: number;
  created_at: string;
  updated_at: string;
  messages: GlobalAgentMessage[];
  active_run: GlobalAgentRun | null;
  latest_run: GlobalAgentRun | null;
}

export interface GlobalAgentKnowledgeStatus {
  root: string;
  approved_directories: string[];
  active_documents: number;
  inactive_documents: number;
  chunks: number;
  last_indexed_at: string | null;
}

export interface GlobalAgentKnowledgeReindexResult extends GlobalAgentKnowledgeStatus {
  indexed_documents: number;
  excluded_documents: number;
  deactivated_documents: number;
  idempotent: boolean;
}

export interface GlobalAgentBootstrap {
  profiles: GlobalAgentProfile[];
  threads: GlobalAgentThread[];
  knowledge: GlobalAgentKnowledgeStatus;
}

export const localPlatformService = {
  status: () => api<PlatformStatus>("/api/status"),
  customerIntakeCandidates: () => api<CustomerIntakeCandidatesView>("/api/customers/intake-candidates", { headers: { "X-Yuda-Desktop": "1" } }),
  createCustomer: (payload: CustomerCreatePayload) => api<CustomerCreateResult>("/api/customers", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  globalAgentBootstrap: () => api<GlobalAgentBootstrap>("/api/global-agent/bootstrap", { headers: { "X-Yuda-Desktop": "1" } }),
  globalAgentCustomerContextOptions: () => api<GlobalAgentCustomerContextOption[]>("/api/global-agent/customer-context-options", { headers: { "X-Yuda-Desktop": "1" } }),
  globalAgentThread: (threadId: string) => api<GlobalAgentThread>(`/api/global-agent/threads/${encodeURIComponent(threadId)}`, { headers: { "X-Yuda-Desktop": "1" } }),
  createGlobalAgentThread: (payload: { request_id: string; profile_id: string; title: string }) => api<GlobalAgentThread>("/api/global-agent/threads", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  updateGlobalAgentThreadProfile: (threadId: string, payload: { request_id: string; expected_revision: number; profile_id: string }) => api<GlobalAgentThread>(`/api/global-agent/threads/${encodeURIComponent(threadId)}/profile`, { method: "PATCH", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  updateGlobalAgentThreadContext: (threadId: string, payload: { request_id: string; expected_revision: number; context_scope: "general_business" | "customer_conversation"; conversation_id: number | null }) => api<GlobalAgentThread>(`/api/global-agent/threads/${encodeURIComponent(threadId)}/context`, { method: "PATCH", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  customerContextGrant: (threadId: string) => api<CustomerContextGrant | null>(`/api/customer-context/threads/${encodeURIComponent(threadId)}/grant`, { headers: { "X-Yuda-Desktop": "1" } }),
  customerAnalysisSubscription: (threadId: string) => api<CustomerAnalysisSubscription | null>(`/api/customer-context/threads/${encodeURIComponent(threadId)}/analysis`, { headers: { "X-Yuda-Desktop": "1" } }),
  upsertCustomerAnalysisSubscription: (payload: { request_id: string; thread_id: string; expected_thread_revision: number; expected_subscription_revision: number; provider_scope: "openai"; model: string; include_images: boolean; debounce_seconds: number; max_wait_seconds: number; authorization_note: string; confirmed_automatic_analysis: true }) => api<CustomerAnalysisSubscription>("/api/customer-context/analysis-subscriptions", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  pauseCustomerAnalysisSubscription: (subscriptionId: string, payload: { request_id: string; expected_revision: number; reason: string; confirmed: true }) => api<CustomerAnalysisSubscription>(`/api/customer-context/analysis-subscriptions/${encodeURIComponent(subscriptionId)}/pause`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  retryCustomerAnalysisSubscription: (subscriptionId: string, payload: { request_id: string; expected_revision: number; confirmed: true }) => api<CustomerAnalysisSubscription>(`/api/customer-context/analysis-subscriptions/${encodeURIComponent(subscriptionId)}/retry`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  createCustomerContextGrant: (payload: { request_id: string; thread_id: string; expected_revision: number; provider_scope: "openai"; audience: CustomerContextAudience; allow_text: boolean; allow_images: boolean; allow_artifacts: boolean; allow_new_messages: boolean; expires_in_seconds: number; authorization_note: string; confirmed: true }) => api<CustomerContextGrant>("/api/customer-context/grants", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  customerContextTunnelBinding: () => api<CustomerContextTunnelBindingState>("/api/customer-context/tunnel-binding", { headers: { "X-Yuda-Desktop": "1" } }),
  replaceCustomerContextTunnelBinding: (payload: { request_id: string; conversation_id: number; expected_binding_revision: number; expected_conversation_revision: number; allow_text: boolean; allow_images: boolean; allow_artifacts: boolean; allow_new_messages: boolean; expires_in_seconds: number; authorization_note: string; confirmed: true }) => api<CustomerContextTunnelBindingState>("/api/customer-context/tunnel-binding", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  revokeCustomerContextTunnelBinding: (payload: { request_id: string; expected_binding_revision: number; reason: string; confirmed: true }) => api<CustomerContextTunnelBindingState>("/api/customer-context/tunnel-binding/revoke", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  ...customerAccessClient,
  createCustomerConversationGrant: (payload: { request_id: string; conversation_id: number; expected_revision: number; provider_scope: "openai"; audience: CustomerContextAudience; allow_text: boolean; allow_images: boolean; allow_artifacts: boolean; allow_new_messages: boolean; expires_in_seconds: number; authorization_note: string; confirmed: true }) => api<CustomerContextGrant>("/api/customer-context/conversation-grants", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  revokeCustomerContextGrant: (grantId: string, payload: { request_id: string; expected_revision: number; reason: string; confirmed: true }) => api<CustomerContextGrant>(`/api/customer-context/grants/${encodeURIComponent(grantId)}/revoke`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  deleteGlobalAgentThread: (threadId: string, payload: { request_id: string; expected_revision: number }) => api<void>(`/api/global-agent/threads/${encodeURIComponent(threadId)}`, { method: "DELETE", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  sendGlobalAgentMessage: (threadId: string, payload: { request_id: string; expected_revision: number; content: string; recheck_full_context?: boolean }) => api<GlobalAgentRun>(`/api/global-agent/threads/${encodeURIComponent(threadId)}/messages`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  confirmGlobalAgentCustomerCreate: (threadId: string, payload: { assistant_message_id: string; request_id: string; expected_revision: number; confirmed: true }) => api<CustomerCreateResult>(`/api/global-agent/threads/${encodeURIComponent(threadId)}/customer-create/confirm`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  globalAgentRun: (runId: string) => api<GlobalAgentRun>(`/api/global-agent/runs/${encodeURIComponent(runId)}`, { headers: { "X-Yuda-Desktop": "1" } }),
  globalAgentRunTrace: (runId: string) => api<GlobalAgentRunTrace>(`/api/global-agent/runs/${encodeURIComponent(runId)}/trace`, { headers: { "X-Yuda-Desktop": "1" } }),
  cancelGlobalAgentRun: (runId: string, requestId: string) => api<GlobalAgentRun>(`/api/global-agent/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify({ request_id: requestId }) }),
  createGlobalAgentProfile: (payload: { request_id: string; expected_revision: 0; provider: GlobalAgentProvider; model: string; reasoning_effort: string; label: string; enabled: boolean; is_default: boolean }) => api<GlobalAgentProfile>("/api/global-agent/profiles", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  updateGlobalAgentProfile: (profileId: string, payload: { request_id: string; expected_revision: number; model: string; reasoning_effort: string; label: string; enabled: boolean; is_default: boolean }) => api<GlobalAgentProfile>(`/api/global-agent/profiles/${encodeURIComponent(profileId)}`, { method: "PATCH", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  globalAgentProviderModels: (provider: GlobalAgentProvider) => api<GlobalAgentModelOption[]>(`/api/global-agent/providers/${encodeURIComponent(provider)}/models`, { headers: { "X-Yuda-Desktop": "1" } }),
  reindexGlobalAgentKnowledge: (requestId: string) => api<GlobalAgentKnowledgeReindexResult>("/api/global-agent/knowledge/reindex", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify({ request_id: requestId, confirmed: true }) }),
  codexProjectSync: (projectId: string) => api<CodexProjectSyncView>(`/api/projects/${encodeURIComponent(projectId)}/codex-sync`),
  projectRequirementBlueprints: (projectId: string) => api<ProjectRequirementBlueprintView[]>(`/api/projects/${encodeURIComponent(projectId)}/requirement-blueprints`),
  requirementProposals: (customerId:string) => api<RequirementProposalView[]>(`/api/customers/${encodeURIComponent(customerId)}/requirement-proposals`, {headers:{'X-Yuda-Desktop':'1'}}),
  confirmRequirementProposal: (payload:{request_id:string; review_token:string; expected_version:number; confirmed:true}) => api<{case_id:string;version:number}>('/api/requirement-proposals/confirm',{method:'POST',headers:{'X-Yuda-Desktop':'1'},body:JSON.stringify(payload)}),
  linkProjectRequirement: (projectId:string,payload:{case_id:string; expected_revision:number;request_id:string;confirmed:true}) => api<{revision:number}>(`/api/projects/${encodeURIComponent(projectId)}/requirement-case`,{method:'POST',headers:{'X-Yuda-Desktop':'1'},body:JSON.stringify(payload)}),
  previewProjectRequirementImport: (projectId: string, payload: { expected_revision: number; source_filename: string; blueprint: Record<string, unknown> }) => api<ProjectRequirementImportPreview>(`/api/projects/${encodeURIComponent(projectId)}/requirement-blueprints/preview`, { method: "POST", body: JSON.stringify(payload) }),
  commitProjectRequirementImport: (projectId: string, payload: { request_id: string; expected_revision: number; source_filename: string; blueprint: Record<string, unknown>; preview_token: string; confirmed: true }) => api<{ project_id: string; requirement_version_id: number; version: number; revision: number; idempotent: boolean }>(`/api/projects/${encodeURIComponent(projectId)}/requirement-blueprints/commit`, { method: "POST", body: JSON.stringify(payload) }),
  createProjectTaskDraftPreview: (projectId: string, payload: { expected_revision: number; requirement_version_id?: number | null }) => api<ProjectTaskDraftPreviewView>(`/api/projects/${encodeURIComponent(projectId)}/task-draft-previews`, { method: "POST", body: JSON.stringify(payload) }),
  latestProjectTaskDraft: (projectId: string) => api<ProjectTaskDraftPreviewView | null>(`/api/projects/${encodeURIComponent(projectId)}/task-drafts`),
  confirmProjectTaskDraft: (projectId: string, payload: { request_id: string; expected_revision: number; preview_id: string; preview_token: string; selected_task_keys: string[]; apply_allowed_updates_only: true; note: string; confirmed: true }) => api<ProjectTaskDraftConfirmResult>(`/api/projects/${encodeURIComponent(projectId)}/task-drafts/confirm`, { method: "POST", body: JSON.stringify(payload) }),
  codexManagedProject: (projectId: string) => api<CodexManagedProjectView>(`/api/projects/${encodeURIComponent(projectId)}/codex-runtime`, { headers: { "X-Yuda-Desktop": "1" } }),
  startCodexManagedRun: (payload: { request_id: string; project_id: string; task_key: string; binding_id: string; model: string; reasoning_effort: string; sandbox_mode: "workspace-write"; approval_mode: "untrusted"; acknowledge_dirty_repository: boolean }) => api<CodexManagedRun>("/api/codex/runs", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  pauseCodexManagedRun: (runId: string, requestId: string) => api<CodexManagedRun>(`/api/codex/runs/${encodeURIComponent(runId)}/pause`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify({ request_id: requestId }) }),
  resumeCodexManagedRun: (runId: string, requestId: string) => api<CodexManagedRun>(`/api/codex/runs/${encodeURIComponent(runId)}/resume`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify({ request_id: requestId }) }),
  cancelCodexManagedRun: (runId: string, requestId: string) => api<CodexManagedRun>(`/api/codex/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify({ request_id: requestId }) }),
  codexManagedDiff: (runId: string) => api<CodexManagedDiff>(`/api/codex/runs/${encodeURIComponent(runId)}/diff`, { headers: { "X-Yuda-Desktop": "1" } }),
  openCodexWorktree: (runId: string) => api<void>(`/api/codex/runs/${encodeURIComponent(runId)}/open`, { method: "POST", headers: { "X-Yuda-Desktop": "1" } }),
  decideCodexApproval: (approvalId: string, requestId: string, decision: "approve_once" | "reject" | "cancel") => api<CodexManagedApproval>(`/api/codex/approvals/${encodeURIComponent(approvalId)}/decision`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify({ request_id: requestId, decision }) }),
  projectVerification: (projectId: string) => api<CodexProjectVerificationView>(`/api/projects/${encodeURIComponent(projectId)}/verification`, { headers: { "X-Yuda-Desktop": "1" } }),
  createManualAcceptancePoints: (projectId: string, payload: { request_id: string; expected_revision: number; reason: string; points: Array<{ task_id: string; point_key: string; title: string; verification_type: "automated_test" | "manual_test" | "visual_review" | "document_review"; point_weight?: number | null }> }) => api<CodexProjectVerificationView>(`/api/projects/${encodeURIComponent(projectId)}/manual-acceptance-points`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  retireManualAcceptancePoint: (pointId: string, payload: { request_id: string; expected_revision: number; reason: string }) => api<CodexProjectVerificationView>(`/api/acceptance-points/${encodeURIComponent(pointId)}/retire`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  freezeProjectOutcome: (projectId: string, payload: { request_id: string; expected_revision: number; confirmed_scope_complete: true; confirmed_time_complete: true; confirmation_note: string }) => api<ProjectOutcomeFreezeView>(`/api/projects/${encodeURIComponent(projectId)}/outcome-freezes`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  projectOutcomeFreezes: (projectId: string) => api<ProjectOutcomeFreezeView[]>(`/api/projects/${encodeURIComponent(projectId)}/outcome-freezes`, { headers: { "X-Yuda-Desktop": "1" } }),
  decideAcceptancePoint: (pointId: string, payload: { request_id: string; expected_revision: number; status: "pending" | "verified" | "failed" | "waived"; reason: string; waived_counts: boolean }) => api<CodexProjectVerificationView>(`/api/acceptance-points/${encodeURIComponent(pointId)}/decision`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  runProjectVerificationTest: (projectId: string, payload: { request_id: string; expected_revision: number; point_id: string; command: string; timeout_seconds: number; confirmed: true }) => api<CodexProjectVerificationView>(`/api/projects/${encodeURIComponent(projectId)}/tests/run`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  addProjectTimeEntry: (projectId: string, payload: { request_id: string; expected_revision: number; task_id: string; category: "development" | "testing" | "fixing" | "communication"; hours: number; note: string }) => api<CodexProjectVerificationView>(`/api/projects/${encodeURIComponent(projectId)}/time-entries`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  linkProjectGitCommit: (projectId: string, payload: { request_id: string; expected_revision: number; task_id: string; point_id?: string | null; commit_sha: string; note: string }) => api<CodexProjectVerificationView>(`/api/projects/${encodeURIComponent(projectId)}/git-links`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  recoverXianyu: (cookie: string) => api<ConnectionRecoveryResult>("/api/connections/xianyu/recover", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify({ cookie }) }),
  recoverDeepSeek: (apiKey: string) => api<ConnectionRecoveryResult>("/api/connections/deepseek/recover", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify({ api_key: apiKey }) }),
  reloadConnection: (provider: "xianyu" | "deepseek") => api<ConnectionRecoveryResult>("/api/connections/reload", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify({ provider }) }),
  checkCodexConnection: () => api<ConnectionRecoveryResult>("/api/connections/codex/check", { method: "POST", headers: { "X-Yuda-Desktop": "1" } }),
  phraseLibrary: () => api<PhraseLibraryView>("/api/phrase-library", { headers: { "X-Yuda-Desktop": "1" } }),
  createPhraseCategory: (payload: { request_id: string; expected_revision: number; name: string }) => api<PhraseLibraryView>("/api/phrase-library/categories", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  createPhrase: (payload: { request_id: string; expected_revision: number; category_id: string; content: string }) => api<PhraseLibraryView>("/api/phrase-library/phrases", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  updatePhrase: (phraseId: string, payload: { request_id: string; expected_revision: number; category_id: string; content: string }) => api<PhraseLibraryView>(`/api/phrase-library/phrases/${encodeURIComponent(phraseId)}`, { method: "PATCH", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  reorderPhrases: (payload: { request_id: string; expected_revision: number; category_id: string; phrase_ids: string[] }) => api<PhraseLibraryView>("/api/phrase-library/phrases/reorder", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  setPhraseActivation: (phraseId: string, payload: { request_id: string; expected_revision: number; active: boolean }) => api<PhraseLibraryView>(`/api/phrase-library/phrases/${encodeURIComponent(phraseId)}/activation`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  ...customerImageClient,
  ...customerConversationClient,
  providers: (refresh = false) => api<AIProviderStatus[]>(`/api/ai/providers${refresh ? "?refresh=true" : ""}`),
  customerRequirements: (customerId: string) => api<RequirementCaseSummary[]>(`/api/customers/${encodeURIComponent(customerId)}/requirements`),
  requirementCase: (caseId: string, version?: number) => api<RequirementCaseDetail>(`/api/requirement-cases/${encodeURIComponent(caseId)}${version ? `?version=${version}` : ""}`),
  editRequirementCase: (caseId: string, payload: { expected_version: number; change_summary: string; document: RequirementBlueprint }) => api<{ case: RequirementCaseDetail; version_id: number; version: number; idempotent: boolean }>(`/api/requirement-cases/${encodeURIComponent(caseId)}/edit`, { method: "POST", body: JSON.stringify(payload) }),
  transferRequirementCase: (caseId: string, payload: { request_id: string; expected_customer_id: string; expected_version: number; expected_revision: number; target_customer_id?: string | null; new_customer_name?: string | null }) => api<{ revision: number; snapshot: LedgerSnapshot; target_customer_id: string; case: RequirementCaseDetail; idempotent: boolean }>(`/api/requirement-cases/${encodeURIComponent(caseId)}/transfer`, { method: "POST", body: JSON.stringify(payload) }),
  codexBindings: (caseId: string) => api<CodexRepositoryBinding[]>(`/api/requirement-cases/${encodeURIComponent(caseId)}/codex-bindings`, { headers: { "X-Yuda-Desktop": "1" } }),
  bindCodexRepository: (payload: { request_id: string; requirement_case_id: string; project_id?: string | null; repository_path: string }) => api<CodexRepositoryBinding>("/api/codex/repository-bindings", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  latestCodexPlanForCase: (caseId: string) => api<CodexDevelopmentPlan | null>(`/api/requirement-cases/${encodeURIComponent(caseId)}/codex-plan`, { headers: { "X-Yuda-Desktop": "1" } }),
  generateCodexPlan: (payload: { request_id: string; requirement_case_id: string; expected_requirement_version: number; binding_id?: string | null }) => api<CodexDevelopmentPlan>("/api/codex/plans/generate", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  updateCodexPlan: (planId: string, payload: { request_id: string; expected_updated_at: string; document: CodexPlanDocument }) => api<CodexDevelopmentPlan>(`/api/codex/plans/${encodeURIComponent(planId)}/draft`, { method: "PUT", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  confirmCodexPlan: (planId: string, payload: { request_id: string; expected_updated_at: string; expected_requirement_version: number; expected_revision: number; confirmed: true }) => api<{ plan: CodexDevelopmentPlan; project_id: string; task_ids: string[]; revision: number; idempotent: boolean }>(`/api/codex/plans/${encodeURIComponent(planId)}/confirm`, { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  migrationPreview: (snapshot: LedgerSnapshot) => api<MigrationPreview>("/api/ledger/migrations/preview", { method: "POST", body: JSON.stringify({ snapshot }) }),
  migrationCommit: (snapshot: LedgerSnapshot, token: string, resolutions: Record<string, "sqlite" | "browser">) => api<{ revision: number; snapshot: LedgerSnapshot; backup_name: string; attachments_written: number }>("/api/ledger/migrations/commit", { method: "POST", body: JSON.stringify({ snapshot, token, resolutions }) }),
  operationsSummary: () => api<OperationsSummary>("/api/operations/summary"),
  analyzeBusinessRequirement: (content: string) => api<BusinessRequirementAnalysis>("/api/ai/business/analyze", { method: "POST", body: JSON.stringify({ content }) }),
  createBusinessQuote: (analysis: BusinessRequirementAnalysis, complexity: "standard" | "advanced" | "complex", riskBuffer = 0.15) => api<BusinessQuote>("/api/ai/business/quote", { method: "POST", body: JSON.stringify({ analysis, complexity, risk_buffer: riskBuffer }) }),
  reviewBusinessProject: (payload: Record<string, unknown>) => api<BusinessReview>("/api/ai/business/review", { method: "POST", body: JSON.stringify(payload) }),
  ...productIntelligenceClient,
};

export function connectPlatformEvents(
  onEvent: (event: Record<string, unknown>) => void,
  onState?: (state: "connecting" | "connected" | "disconnected") => void,
) {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  let socket: WebSocket | null = null;
  let stopped = false;
  let retryTimer: number | null = null;
  let attempt = 0;
  const connect = () => {
    if (stopped) return;
    onState?.("connecting");
    socket = new WebSocket(`${scheme}://${window.location.host}/events`);
    socket.addEventListener("open", () => {
      attempt = 0;
      onState?.("connected");
    });
    socket.addEventListener("message", (event) => {
      try {
        onEvent(JSON.parse(event.data) as Record<string, unknown>);
      } catch {
        // Ignore malformed local events; normal API refresh remains available.
      }
    });
    socket.addEventListener("close", () => {
      if (stopped) return;
      onState?.("disconnected");
      const delay = Math.min(15_000, 1_000 * 2 ** Math.min(attempt++, 4));
      retryTimer = window.setTimeout(connect, delay);
    });
  };
  const reconnectOnline = () => {
    if (!stopped && socket?.readyState !== WebSocket.OPEN) {
      if (retryTimer !== null) window.clearTimeout(retryTimer);
      connect();
    }
  };
  window.addEventListener("online", reconnectOnline);
  connect();
  return () => {
    stopped = true;
    if (retryTimer !== null) window.clearTimeout(retryTimer);
    window.removeEventListener("online", reconnectOnline);
    socket?.close();
  };
}
