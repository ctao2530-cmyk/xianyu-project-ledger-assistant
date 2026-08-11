export type BusinessAnalysisDomain =
  | "portfolio"
  | "products"
  | "customers"
  | "projects"
  | "finance"
  | "data";

export type RecommendationStatus = "pending" | "accepted" | "ignored" | "completed";
export type BusinessAnalysisProvider = "codex_cli" | "deepseek";

export interface BusinessAnalysisModelOption {
  model: string;
  display_name: string;
  default_reasoning_effort: string | null;
  supported_reasoning_efforts: string[];
}

export interface BusinessAnalysisModelSettings {
  provider: "codex_cli";
  selected_model: string | null;
  selected_reasoning_effort: string | null;
  models: BusinessAnalysisModelOption[];
}

export interface BusinessAnalysisProviderStatus {
  provider: BusinessAnalysisProvider;
  label: string;
  configured: boolean;
  status: string;
  detail: string | null;
  model: string | null;
  lead_model: string | null;
}

export interface ProductSignalMetric {
  current: number;
  delta_7d: number | null;
  comparison_products: number;
  available: boolean;
  unit: string;
}

export interface BusinessAnalysisMetrics {
  products: {
    owned_products: number;
    monitored_products: number;
    active_products: number;
    status_counts: Record<string, number>;
    latest_published_at: string | null;
    snapshot_days: number;
    snapshot_coverage_percent: number;
    exposure: ProductSignalMetric;
    inquiries: ProductSignalMetric;
    converted_projects: ProductSignalMetric;
    platform_sold_count: number;
    inquiry_rate_percent: number | null;
  };
  customers: {
    total: number;
    follow_up_status_counts: Record<string, number>;
    won_customers: number;
    active_last_30d: number;
    stale_or_missing_contact_30d: number;
    latest_contact_at: string | null;
    conversation_customers: number;
    latest_message_at: string | null;
  };
  projects: {
    total: number;
    status_counts: Record<string, number>;
    active_projects: number;
    completed_projects: number;
    overdue_projects: number;
    contract_total: number;
    confirmed_income: number;
    outstanding_receivables: number;
  };
  finance: {
    income: BusinessAnalysisPeriodMetric;
    expenses: BusinessAnalysisPeriodMetric;
    profit: BusinessAnalysisPeriodMetric;
    all_time_income: number;
    all_time_expenses: number;
    all_time_profit: number;
    confirmed_payment_count: number;
    expense_count: number;
  };
}

export interface BusinessAnalysisPeriodMetric {
  current: number;
  previous: number;
  delta: number;
  change_percent: number | null;
  direction: "up" | "down" | "flat";
  unit: string;
}

export interface BusinessAnalysisInsight {
  id: string;
  domain: BusinessAnalysisDomain;
  severity: "info" | "positive" | "warning" | "critical";
  title: string;
  reason: string;
  evidence_refs: string[];
}

export interface BusinessAnalysisRecommendation {
  id: string;
  source_key: string | null;
  domain: BusinessAnalysisDomain;
  priority: "low" | "medium" | "high";
  title: string;
  problem: string;
  action: string;
  reason: string;
  data_source: string[];
  confidence: "low" | "medium" | "high";
  observe_period: string;
  status: RecommendationStatus;
  version: number;
  user_note: string;
  target_page: string;
  execution_mode: "manual";
  evidence_refs: string[];
}

export interface BusinessAnalysisDataSource {
  id: string;
  label: string;
  source_type: "sqlite" | "ledger";
  tables: string[];
  fields: string[];
  available: boolean;
  record_count: number;
  latest_at: string | null;
  note: string;
}

export interface BusinessAnalysisFutureField {
  domain: "products" | "customers" | "projects" | "finance" | "recommendations";
  field: string;
  label: "未来扩展字段";
  reason: string;
}

export interface BusinessAnalysisOverview {
  summary: string;
  metrics: BusinessAnalysisMetrics;
  insights: BusinessAnalysisInsight[];
  recommendations: BusinessAnalysisRecommendation[];
  data_sources: BusinessAnalysisDataSource[];
  future_fields: BusinessAnalysisFutureField[];
  data_gaps: string[];
  analysis_method: "evidence_rules_v1" | "rules_plus_deepseek_v1" | "rules_plus_codex_v1";
  ledger_revision: number;
  period: {
    timezone: string;
    current_month_start: string;
    current_month_end: string;
    previous_month_start: string;
    previous_month_end: string;
    product_change_window_days: number;
  };
  generated_at: string;
  analysis_id: string | null;
  record_status: "live" | "completed";
  provider: string | null;
  model: string | null;
  ai_status: "not_requested" | "succeeded" | "failed";
  fallback_used: boolean;
  snapshot_time: string | null;
  is_stale: boolean;
  ai_error: { code: string; message: string; retryable: boolean } | null;
}

export interface BusinessAnalysisHistoryItem {
  id: string;
  snapshot_time: string;
  created_at: string;
  provider: string | null;
  model: string | null;
  ai_status: "not_requested" | "succeeded" | "failed";
  fallback_used: boolean;
  status: "completed";
  summary: string;
  insight_count: number;
  recommendation_count: number;
  pending_recommendation_count: number;
}

export interface BusinessAnalysisHistoryResponse {
  items: BusinessAnalysisHistoryItem[];
  total: number;
  limit: number;
  offset: number;
}

interface ErrorBody {
  detail?: string | {
    code?: string;
    message?: string;
    current_version?: number;
  };
}

export class BusinessAnalysisApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly currentVersion: number | null;

  constructor(message: string, status: number, code?: string, currentVersion?: number) {
    super(message);
    this.name = "BusinessAnalysisApiError";
    this.status = status;
    this.code = code || null;
    this.currentVersion = currentVersion ?? null;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  const body = await response.json().catch(() => null) as T | ErrorBody | null;
  if (!response.ok) {
    const detail = (body as ErrorBody | null)?.detail;
    const message = typeof detail === "string" ? detail : detail?.message;
    throw new BusinessAnalysisApiError(
      message || `经营分析服务请求失败（${response.status}）`,
      response.status,
      typeof detail === "object" ? detail?.code : undefined,
      typeof detail === "object" ? detail?.current_version : undefined,
    );
  }
  return body as T;
}

export function businessAnalysisRequestId(scope: "analysis-run" | "recommendation-update") {
  const unique = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${scope}:${unique}`;
}

export const businessAnalysisService = {
  latest: () => request<BusinessAnalysisOverview>("/api/business-analysis"),
  overview: () => request<BusinessAnalysisOverview>("/api/business-analysis/overview"),
  providers: () => request<BusinessAnalysisProviderStatus[]>("/api/ai/providers"),
  models: () => request<BusinessAnalysisModelSettings>("/api/ai/models"),
  run: (
    requestId: string,
    selection: {
      provider: BusinessAnalysisProvider;
      model: string;
      reasoningEffort?: string | null;
    },
  ) => request<BusinessAnalysisOverview>("/api/business-analysis/runs", {
    method: "POST",
    body: JSON.stringify({
      request_id: requestId,
      provider: selection.provider,
      model: selection.model,
      reasoning_effort: selection.provider === "codex_cli" ? selection.reasoningEffort || null : null,
    }),
  }),
  history: (limit = 20, offset = 0) => request<BusinessAnalysisHistoryResponse>(
    `/api/business-analysis/history?limit=${limit}&offset=${offset}`,
  ),
  historyDetail: (analysisId: string) => request<BusinessAnalysisOverview>(
    `/api/business-analysis/history/${encodeURIComponent(analysisId)}`,
  ),
  updateRecommendation: (
    recommendationId: string,
    payload: {
      status: RecommendationStatus;
      expected_version: number;
      request_id: string;
      note?: string;
    },
  ) => request<BusinessAnalysisRecommendation>(
    `/api/business-analysis/recommendations/${encodeURIComponent(recommendationId)}`,
    {
      method: "PATCH",
      body: JSON.stringify({ ...payload, note: payload.note || "" }),
    },
  ),
};
