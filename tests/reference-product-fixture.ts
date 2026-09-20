// Synthetic frontend fixture only. Never connected to a business database.
import type { ProductLaunchRecommendationView, ProductMarketBenchmarkView, ProductMarketReferenceView } from '../src/data/localPlatformService';

const emptyMarketBenchmark: ProductMarketBenchmarkView = {
  keyword: '', sample_days: 0, high_visibility_result_count: 0, priced_result_count: 0,
  repeated_result_count: 0, median_price: null, price_low: null, price_high: null,
  common_title_terms: [], common_tags: [], median_title_length: null, confidence: 'low', evidence: [],
};
// Every preview shares the same complete empty-state contract, including subpages.
const marketReference: ProductMarketReferenceView = {
  date: '2026-09-18', mode: 'recommended', selected_keyword: '', custom_keyword: '',
  common_keywords: [], recommendations: [], current_sample: null, recent_samples: [],
  stability: { keyword: '', sample_days: 0, visible_days: 0, average_best_position: null, status: 'insufficient', label: '样本不足' },
  benchmark: emptyMarketBenchmark,
  reminder: { date: '2026-09-18', status: 'pending', scheduled_for: '2026-09-18T12:00:00Z', due: false, snoozed_until: null },
  update_completed: false, last_updated_at: null, rules_version: 'synthetic', safety_note: '合成数据，禁止远程搜索',
};
const launchRecommendation: ProductLaunchRecommendationView = {
  keyword: '', theme: '待补充', title: '上新观察', recommended_window: '等待更多证据',
  demand_conversations: 0, matching_product_count: 0, capacity_available: 3, confidence: 'low',
  market_validation_required: true, ready: false, recommended_action: 'observe',
  suggested_product_type: '待市场参考验证', title_direction: '先明确交付范围',
  price_reference: '暂无有效价格样本', market_differentiation: '待积累市场证据',
  timing_basis: '样本不足，不推断发布时段', benchmark: emptyMarketBenchmark,
  rationale: ['尚无足够合成市场样本，继续积累证据。'], evidence: [],
};

export const referenceProductFixture = {
  collection:{configured:false,schedule:'隔离测试',timezone:'Asia/Shanghai',can_collect_today:false,next_collection_at:null,last_run:null,latest_attempt:null,attempts:[],safety_note:'合成数据，禁止远程采集'},
  summary:{monitored_products:1,active_products:2,pending_products:0,excluded_products:0,needs_attention:0,traffic_candidates:0,snapshot_days:0,active_projects:0,delivery_capacity:3},
  products:[1,2].map(id=>({external_id:`synthetic-product-${id}`,title:`合成商品 ${id} · 页面设计与开发`,price:100,status:'active',monitoring_enabled:id===1,monitor_source:'test',ownership_status:'owned',ownership_source:'test',last_attempt_at:null,last_collection_status:'waiting',last_error_code:null,last_error_detail:null,last_collected_at:null,browse_count:120,raw_browse_count:121,collection_views_excluded:1,collect_count:2,want_count:3,sold_count:0,browse_delta:null,inquiry_count:4,inbound_message_count:5,converted_project_count:0,revenue_total:0,profit_total:0,project_expense_total:0,project_refund_total:0,profit_is_realtime:true,linked_projects:[],inquiry_rate:3.3,deal_rate:0,snapshot_count:0,freshness_days:null,data_quality:'low',data_gaps:[],traffic_cooldown_until:null,modification_observation_until:null,recent_windows:[],history:[],recommendation:null,actions:[]})),
  candidates:[],recommendations:[],publish_timing:{sample_size:0,confidence:'low',summary:'尚无合成趋势样本',windows:[]},demand_opportunities:[],
  operating_plan:{slots:[],weekly_budget:0,data_quality:'low',change_summary:'无计划',rules_version:'test',version:1},
  traffic_batches:[],traffic_summary:{batch_count:0,effective_batch_count:0,active_batch_count:0,planned_batch_count:0,observation_batch_count:0,due_checkpoint_count:0,spent_this_week:0,analysis_stage:'learning',analysis_summary:'无投流数据'},
  exposure_analytics:{},market_reference:marketReference,launch_recommendation:launchRecommendation,launch_plans:[],modification_suggestions:[],modification_experiments:[],
};
referenceProductFixture.products[0].history = Array.from({length:7},(_,i)=>({date:`09-${String(i+1).padStart(2,'0')}`,browse_count:30+i*15})) as never[];
Object.assign(referenceProductFixture.products[0],{last_collection_status:'success',last_collected_at:'2026-09-07T00:00:00Z',snapshot_count:7,freshness_days:2,revenue_total:2100,profit_total:1650,project_expense_total:450,converted_project_count:1,linked_projects:[{project_id:'qa-project',project_name:'合成关联项目',relation_source:'project_binding',latest_confirmed_at:'2026-09-09T02:30:00Z',confirmed_total:2100,net_confirmed_total:2100,expense_total:450,refund_total:0,profit_total:1650}]});
