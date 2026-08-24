export type PredictionTarget =
  | "workload_14d"
  | "project_delay_risk"
  | "cashflow_30d"
  | "customer_followup_priority";

export type PredictionDataSufficiency = "low" | "medium" | "high";
export type PredictionRiskLevel =
  | "low"
  | "normal"
  | "warning"
  | "high"
  | "urgent"
  | "overloaded";

export interface PredictionDriver {
  code: string;
  label: string;
  detail: string;
  impact: number | null;
  evidence_refs: string[];
}

export interface PredictionFact {
  key: string;
  label: string;
  value: number | string | boolean | null;
  unit: string | null;
  evidence_ref: string;
}

export interface PredictionResult {
  id: string;
  run_id: string | null;
  statement_type: "prediction";
  target: PredictionTarget;
  entity_type: "portfolio" | "project" | "customer";
  entity_id: string | null;
  entity_label: string | null;
  horizon: string;
  horizon_days: number;
  generated_at: string;
  horizon_start: string;
  horizon_end: string;
  prediction_value: number | null;
  lower_bound: number | null;
  upper_bound: number | null;
  score: number | null;
  risk_level: PredictionRiskLevel | null;
  data_sufficiency: PredictionDataSufficiency;
  method: string;
  model_version: string;
  summary: string;
  drivers: PredictionDriver[];
  facts: PredictionFact[];
  evidence_refs: string[];
  actual_value: number | string | boolean | null;
  evaluated_at: string | null;
  evaluation_method: string | null;
}

export interface PredictionRunView {
  id: string | null;
  request_id: string | null;
  record_status: "live" | "completed";
  generated_at: string;
  input_snapshot_hash: string;
  ledger_revision: number;
  feature_schema_version: string;
  engine_version: string;
  timezone: "Asia/Shanghai";
  results: PredictionResult[];
  is_stale: boolean;
}

export interface PredictionLatestView {
  run: PredictionRunView;
  workload: PredictionResult | null;
  cashflow: PredictionResult | null;
  high_risk_projects: PredictionResult[];
  priority_customers: PredictionResult[];
}

export type CalibrationSufficiency = "insufficient" | "exploratory" | "actionable";

export interface CalibrationMetrics {
  signed_bias_hours: number | null;
  mae_hours: number | null;
  overrun_rate: number | null;
  interval_coverage: number | null;
  multiplier_median: number | null;
  multiplier_lower: number | null;
  multiplier_upper: number | null;
}

export interface CalibrationCandidateView {
  project_id: string;
  project_name: string;
  project_status: string;
  estimated_hours: number;
  actual_hours: number;
  verified_progress: number;
  available_at: string;
  finalized_at: string | null;
  freeze_id: string | null;
  freeze_version: number | null;
  sample_readiness_status: string;
  freeze_stale: boolean;
  readiness_actions: string[];
  eligible: boolean;
  exclusion_code: string;
  exclusion_reason: string;
}

export interface CalibrationSummaryView {
  run_id: string | null;
  record_status: "live" | "completed";
  cutoff_at: string;
  input_snapshot_hash: string;
  sample_count: number;
  sufficiency: CalibrationSufficiency;
  thresholds: { exploratory_min: 3; actionable_min: 5 };
  algorithm_version: string;
  metrics: CalibrationMetrics;
  sample_start_at: string | null;
  sample_end_at: string | null;
  candidates: CalibrationCandidateView[];
  is_stale: boolean;
}

export interface CalibrationQuoteAssistView {
  project_id: string;
  project_name: string;
  original_estimated_hours: number;
  run_id: string | null;
  suggestion_id: string | null;
  suggestion_revision: number;
  sample_count: number;
  sufficiency: CalibrationSufficiency;
  suggested_hours: number | null;
  lower_hours: number | null;
  upper_hours: number | null;
  adopted_hours: number | null;
  status: "unavailable" | "preview" | "pending" | "adopted" | "rejected";
  sample_start_at: string | null;
  sample_end_at: string | null;
  basis: string[];
  invalidation_conditions: string[];
  formula: string;
}

export class PredictionApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "PredictionApiError";
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  const body = await response.json().catch(() => null) as T | { detail?: string | { message?: string } } | null;
  if (!response.ok) {
    const detail = (body as { detail?: string | { message?: string } } | null)?.detail;
    const message = typeof detail === "string" ? detail : detail?.message;
    throw new PredictionApiError(message || `预测服务请求失败（${response.status}）`, response.status);
  }
  return body as T;
}

export const predictionService = {
  latest: () => request<PredictionLatestView>("/api/predictions"),
  target: (target: PredictionTarget) => request<PredictionResult[]>(`/api/predictions/targets/${encodeURIComponent(target)}`),
  project: (projectId: string) => request<PredictionResult>(`/api/predictions/projects/${encodeURIComponent(projectId)}`),
  customer: (customerId: string) => request<PredictionResult>(`/api/predictions/customers/${encodeURIComponent(customerId)}`),
  calibration: () => request<CalibrationSummaryView>("/api/predictions/calibration"),
  runCalibration: (requestId: string) => request<CalibrationSummaryView>("/api/predictions/calibration/runs", {
    method: "POST",
    body: JSON.stringify({ request_id: requestId }),
  }),
  projectCalibration: (projectId: string) => request<CalibrationQuoteAssistView>(`/api/predictions/calibration/projects/${encodeURIComponent(projectId)}`),
  decideCalibration: (
    projectId: string,
    suggestionId: string,
    input: { request_id: string; expected_revision: number; action: "adopt" | "reject"; adopted_hours?: number; note?: string },
  ) => request<CalibrationQuoteAssistView>(
    `/api/predictions/calibration/projects/${encodeURIComponent(projectId)}/suggestions/${encodeURIComponent(suggestionId)}/decisions`,
    { method: "POST", body: JSON.stringify(input) },
  ),
};

export function predictionFact(result: PredictionResult | null | undefined, key: string) {
  return result?.facts.find((item) => item.key === key)?.value ?? null;
}

export function predictionSufficiencyLabel(value: PredictionDataSufficiency) {
  return value === "high" ? "高" : value === "medium" ? "中" : "低";
}

export function predictionRiskLabel(value: PredictionRiskLevel | null) {
  if (value === "overloaded") return "超载";
  if (value === "urgent") return "紧急";
  if (value === "high") return "高";
  if (value === "warning") return "偏高";
  if (value === "normal") return "正常";
  return "低";
}
