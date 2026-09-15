import { localApi } from "./localApi";
import type {
  ProductActionView,
  ProductCollectionRunView,
  ProductIntelligenceView,
  ProductLaunchPlanView,
  ProductMarketReferenceView,
  ProductModificationExperimentView,
  ProductMonitorBatchDisableResult,
  ProductOperatingPlanView,
  ProductRegistrationCommitResult,
  ProductRegistrationPreview,
  ProductTrafficBatchPageView,
  ProductTrafficBatchView,
  ProductTrafficMetricsInput,
  ProductTrafficReplanPreviewView,
  ProductTrafficStartPreviewView,
  ProductView,
  TrafficExperimentView,
  TrafficGrowthOverviewView,
} from "./localPlatformService";


const api = localApi;

export const productIntelligenceClient = {
  productIntelligence: () => api<ProductIntelligenceView>("/api/products/intelligence"),
  trafficGrowth: () => api<TrafficGrowthOverviewView>("/api/products/traffic-growth"),
  previewTrafficExperiment: (payload: { item_external_id: string; target_windows: string[]; baseline_weekly_budget: number; hard_weekly_cap: number }) => api("/api/products/traffic-experiments/preview", { method: "POST", body: JSON.stringify(payload) }),
  createTrafficExperiment: (payload: { request_id: string; item_external_id: string; target_windows: string[]; baseline_weekly_budget: number; hard_weekly_cap: number }) => api<TrafficExperimentView>("/api/products/traffic-experiments", { method: "POST", body: JSON.stringify(payload) }),
  advanceTrafficExperiment: (experimentId: string, payload: { request_id: string; expected_updated_at: string }) => api<TrafficExperimentView>(`/api/products/traffic-experiments/${encodeURIComponent(experimentId)}/advance`, { method: "POST", body: JSON.stringify(payload) }),
  createTrafficScaleCohort: (experimentId: string, payload: { request_id: string; stage: "S1" | "S2" | "S3"; no_other_promotion_confirmed: true; listing_unchanged_confirmed: true }) => api<TrafficExperimentView>(`/api/products/traffic-experiments/${encodeURIComponent(experimentId)}/cohorts`, { method: "POST", body: JSON.stringify(payload) }),
  refreshTrafficAttributions: (experimentId: string, requestId: string) => api<TrafficExperimentView>(`/api/products/traffic-experiments/${encodeURIComponent(experimentId)}/attributions/refresh`, { method: "POST", body: JSON.stringify({ request_id: requestId }) }),
  confirmTrafficAttribution: (attributionId: string, payload: { request_id: string; expected_updated_at: string; project_id: string; reason?: string }) => api<TrafficExperimentView>(`/api/products/traffic-attributions/${encodeURIComponent(attributionId)}/confirm`, { method: "POST", body: JSON.stringify(payload) }),
  rejectTrafficAttribution: (attributionId: string, payload: { request_id: string; expected_updated_at: string; project_id?: string | null; reason?: string }) => api<TrafficExperimentView>(`/api/products/traffic-attributions/${encodeURIComponent(attributionId)}/reject`, { method: "POST", body: JSON.stringify(payload) }),
  refreshTrafficBudgetDecision: (experimentId: string, requestId: string) => api<TrafficExperimentView>(`/api/products/traffic-experiments/${encodeURIComponent(experimentId)}/budget-decisions/refresh`, { method: "POST", body: JSON.stringify({ request_id: requestId }) }),
  applyTrafficBudgetDecision: (decisionId: string, payload: { request_id: string; expected_experiment_updated_at: string }) => api<TrafficExperimentView>(`/api/products/traffic-budget-decisions/${encodeURIComponent(decisionId)}/apply`, { method: "POST", body: JSON.stringify(payload) }),
  collectProducts: () => api<ProductCollectionRunView>("/api/products/collect", { method: "POST" }),
  collectProductsManual: (externalId?: string) => api<ProductCollectionRunView>("/api/products/collect/manual", { method: "POST", body: JSON.stringify({ external_id: externalId || null }) }),
  discoverOwnedListings: () => api<ProductRegistrationPreview>("/api/products/owned-listings/discover", { headers: { "X-Yuda-Desktop": "1" } }),
  resolveProductReference: (reference: string) => api<ProductRegistrationPreview>("/api/products/references/resolve", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify({ reference }) }),
  commitProductRegistration: (payload: { request_id: string; preview_token: string; external_ids: string[] }) => api<ProductRegistrationCommitResult>("/api/products/register/batch", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify(payload) }),
  updateProductMonitor: (externalId: string, enabled: boolean) => api<ProductView>(`/api/products/${encodeURIComponent(externalId)}/monitor`, { method: "PUT", body: JSON.stringify({ enabled }) }),
  disableProductMonitors: (externalIds: string[]) => api<ProductMonitorBatchDisableResult>("/api/products/monitors/disable-batch", { method: "POST", headers: { "X-Yuda-Desktop": "1" }, body: JSON.stringify({ external_ids: externalIds, confirmed: true }) }),
  recordProductAction: (externalId: string, payload: { action_type: string; status: "planned" | "completed" | "cancelled"; note: string; cost: number; recommendation_id?: string | null; observation_days: number }) => api<ProductActionView>(`/api/products/${encodeURIComponent(externalId)}/actions`, { method: "POST", body: JSON.stringify(payload) }),
  updateProductRecommendation: (recommendationId: string, status: "active" | "in_progress" | "completed" | "dismissed") => api<void>(`/api/products/recommendations/${encodeURIComponent(recommendationId)}`, { method: "PUT", body: JSON.stringify({ status }) }),
  recordTrafficBatch: (payload: { request_id: string; item_external_ids: string[]; actual_cost: number; plan_slot_id?: string | null; note?: string; checkpoint_collection_mode?: "auto" | "manual"; confirmed_already_purchased: true }) => api<ProductTrafficBatchView>("/api/products/traffic-batches/recorded", { method: "POST", body: JSON.stringify(payload) }),
  trafficBatches: (options: { cursor?: string | null; limit?: number; status?: string | null } = {}) => {
    const params = new URLSearchParams();
    if (options.cursor) params.set("cursor", options.cursor);
    if (options.limit) params.set("limit", String(options.limit));
    if (options.status) params.set("status", options.status);
    const suffix = params.size ? `?${params.toString()}` : "";
    return api<ProductTrafficBatchPageView>(`/api/products/traffic-batches${suffix}`);
  },
  trafficStartPreview: (batchId: string) => api<ProductTrafficStartPreviewView>(`/api/products/traffic-batches/${encodeURIComponent(batchId)}/start-preview`),
  prepareTrafficBaseline: (batchId: string, payload: { request_id: string; expected_updated_at: string; mode: "remote_refresh" | "manual"; items: ProductTrafficMetricsInput[] }) => api<ProductTrafficBatchView>(`/api/products/traffic-batches/${encodeURIComponent(batchId)}/baseline`, { method: "POST", body: JSON.stringify(payload) }),
  startTrafficBatch: (batchId: string, payload: { request_id: string; expected_updated_at: string; expected_baseline_captured_at: string }) => api<ProductTrafficBatchView>(`/api/products/traffic-batches/${encodeURIComponent(batchId)}/start`, { method: "POST", body: JSON.stringify(payload) }),
  recordActualTrafficStart: (batchId: string, payload: { request_id: string; expected_updated_at: string; confirmed_already_purchased: boolean; items: ProductTrafficMetricsInput[] }) => api<ProductTrafficBatchView>(`/api/products/traffic-batches/${encodeURIComponent(batchId)}/actual-start`, { method: "POST", body: JSON.stringify(payload) }),
  trafficReplanPreview: (batchId: string) => api<ProductTrafficReplanPreviewView>(`/api/products/traffic-batches/${encodeURIComponent(batchId)}/replan-preview`),
  replanTrafficBatch: (batchId: string, payload: { request_id: string; expected_updated_at: string; preview_hash: string }) => api<ProductTrafficBatchView>(`/api/products/traffic-batches/${encodeURIComponent(batchId)}/replan`, { method: "POST", body: JSON.stringify(payload) }),
  completeTrafficBatch: (batchId: string, payload: { completed_at?: string | null; actual_cost: number; total_exposure?: number | null; note?: string }) => api<ProductTrafficBatchView>(`/api/products/traffic-batches/${encodeURIComponent(batchId)}/complete`, { method: "POST", body: JSON.stringify(payload) }),
  recordTrafficCheckpoint: (batchId: string, payload: { checkpoint: "h1" | "h6" | "h24" | "h48" | "h72"; recorded_at?: string | null; items: ProductTrafficMetricsInput[]; note?: string }) => api<ProductTrafficBatchView>(`/api/products/traffic-batches/${encodeURIComponent(batchId)}/checkpoints`, { method: "POST", body: JSON.stringify(payload) }),
  updateTrafficCheckpointCollectionMode: (batchId: string, payload: { request_id: string; expected_updated_at: string; mode: "auto" | "manual" }) => api<ProductTrafficBatchView>(`/api/products/traffic-batches/${encodeURIComponent(batchId)}/checkpoint-collection-mode`, { method: "PUT", body: JSON.stringify(payload) }),
  retryTrafficCheckpointCollection: (batchId: string, checkpoint: "h1" | "h6" | "h24" | "h48" | "h72", payload: { request_id: string; expected_updated_at: string }) => api<ProductTrafficBatchView>(`/api/products/traffic-batches/${encodeURIComponent(batchId)}/checkpoints/${encodeURIComponent(checkpoint)}/retry`, { method: "POST", body: JSON.stringify(payload) }),
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
