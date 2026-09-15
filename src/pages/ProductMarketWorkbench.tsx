import {
  BellRinging,
  CheckCircle,
  FolderOpen,
  Info,
  MagnifyingGlass,
  PencilSimple,
  TrendUp,
  UploadSimple,
} from "@phosphor-icons/react";
import type { ProductIntelligenceView } from "../data/localPlatformService";
import "./product-planning-workbenches.css";


const moneyExact = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  minimumFractionDigits: 0,
  maximumFractionDigits: 2,
});
const dateTime = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "Asia/Shanghai",
});
const confidenceLabels: Record<string, string> = {
  high: "高置信",
  medium: "中等置信",
  low: "低置信",
};

function formatDate(value: string | null | undefined) {
  if (!value) return "尚未采集";
  const hasTimezone = /(?:z|[+-]\d{2}:\d{2})$/i.test(value);
  const isDateTime = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value);
  const parsed = new Date(isDateTime && !hasTimezone ? `${value}Z` : value);
  return Number.isNaN(parsed.getTime()) ? value : dateTime.format(parsed);
}

type KeywordMode = "recommended" | "custom";

interface MarketReferenceWorkbenchProps {
  data: ProductIntelligenceView;
  expanded?: boolean;
  busy: boolean;
  keywordMode: KeywordMode;
  customKeyword: string;
  saveCommonKeyword: boolean;
  setKeywordMode: (value: KeywordMode) => void;
  setCustomKeyword: (value: string) => void;
  setSaveCommonKeyword: (value: boolean) => void;
  setMarketImportOpen: (value: boolean) => void;
  chooseRecommendedKeyword: (keyword: string) => Promise<void>;
  useCustomMarketKeyword: () => Promise<void>;
  returnToRecommendedKeyword: () => Promise<void>;
  snoozeMarketReminder: () => Promise<void>;
  skipMarketReminder: () => Promise<void>;
}

export function MarketReferenceWorkbench({
  data,
  expanded = false,
  busy,
  keywordMode,
  customKeyword,
  saveCommonKeyword,
  setKeywordMode,
  setCustomKeyword,
  setSaveCommonKeyword,
  setMarketImportOpen,
  chooseRecommendedKeyword,
  useCustomMarketKeyword,
  returnToRecommendedKeyword,
  snoozeMarketReminder,
  skipMarketReminder,
}: MarketReferenceWorkbenchProps) {
  return <section id={expanded ? "product-market-reference" : undefined} className={`product-market-reference-card ${expanded ? "is-expanded" : ""}`}>
    <header>
      <span><small>MARKET REFERENCE</small><h3>市场参考</h3></span>
      <em className={`market-stability status-${data.market_reference.stability.status}`}>{data.market_reference.stability.label}</em>
    </header>
    {!data.market_reference.update_completed && data.market_reference.reminder.status !== "skipped" && <div className="market-reminder-banner">
      <BellRinging size={23} weight="duotone" />
      <span><b>{data.market_reference.reminder.status === "snoozed" ? "提醒已延后" : "今日市场参考未更新"}</b><small>{data.market_reference.reminder.status === "snoozed" && data.market_reference.reminder.snoozed_until ? `将在 ${formatDate(data.market_reference.reminder.snoozed_until)} 再提醒` : "北京时间 20:00 检查；更新任一关键词后自动清除"}</small><em>只提醒，不会自动搜索或打开新网站</em></span>
      <div><button type="button" onClick={() => setMarketImportOpen(true)}>现在更新</button><button type="button" onClick={() => void snoozeMarketReminder()}>今晚稍后</button><button type="button" onClick={() => void skipMarketReminder()}>今日不再提醒</button></div>
    </div>}
    {data.market_reference.update_completed && <div className="market-reminder-banner is-complete"><CheckCircle size={23} weight="fill" /><span><b>今日市场参考已更新</b><small>{data.market_reference.current_sample?.result_count || 0} 条公开结果 · {formatDate(data.market_reference.last_updated_at)}</small><em>同一关键词同一天只保留一个样本</em></span></div>}

    <div className="market-keyword-tabs" role="tablist" aria-label="关键词来源">
      <button type="button" role="tab" aria-selected={keywordMode === "recommended"} className={keywordMode === "recommended" ? "active" : ""} onClick={() => setKeywordMode("recommended")}>系统推荐</button>
      <button type="button" role="tab" aria-selected={keywordMode === "custom"} className={keywordMode === "custom" ? "active" : ""} onClick={() => setKeywordMode("custom")}>我的关键词</button>
    </div>

    {keywordMode === "recommended" ? <div className="market-keyword-editor">
      <div className="market-editor-title"><span><b>今日推荐搜索词</b><small>根据咨询需求、商品缺口、历史参考和交付容量生成</small></span><Info size={17} /></div>
      <div className="market-keyword-options">
        {data.market_reference.recommendations.map((candidate) => {
          const selectedKeyword = data.market_reference.mode === "recommended" && data.market_reference.selected_keyword === candidate.keyword;
          return <button type="button" className={selectedKeyword ? "selected" : ""} aria-pressed={selectedKeyword} disabled={busy} onClick={() => void chooseRecommendedKeyword(candidate.keyword)} key={candidate.keyword}>
            <i>{selectedKeyword ? <CheckCircle size={18} weight="fill" /> : <span />}</i><span><b>{candidate.keyword}</b><small>{candidate.reason}</small></span><em>{confidenceLabels[candidate.confidence] || candidate.confidence}</em>
          </button>;
        })}
      </div>
      <div className="market-editor-actions"><button type="button" className="product-primary-button" disabled={busy || data.market_reference.mode !== "recommended"} onClick={() => setMarketImportOpen(true)}><MagnifyingGlass size={16} />使用选中关键词更新</button><button type="button" className="product-outline-button" onClick={() => setKeywordMode("custom")}>我有自己的关键词</button></div>
    </div> : <div className="market-keyword-editor custom-mode">
      <div className="market-editor-title"><span><b>今天用我的关键词</b><small>有明确方向时，可临时替代系统推荐</small></span><PencilSimple size={17} /></div>
      <input value={customKeyword} onChange={(event) => setCustomKeyword(event.target.value)} placeholder="例如：uni-app 页面修改" maxLength={80} />
      <label className="market-common-toggle"><input type="checkbox" checked={saveCommonKeyword} onChange={(event) => setSaveCommonKeyword(event.target.checked)} /><span>加入常用关键词</span><small>不勾选时仅本次验证</small></label>
      {data.market_reference.common_keywords.length > 0 && <div className="market-common-keywords">{data.market_reference.common_keywords.map((keyword) => <button type="button" onClick={() => setCustomKeyword(keyword)} key={keyword}>{keyword}</button>)}</div>}
      <div className="market-editor-actions"><button type="button" className="product-primary-button" disabled={busy || !customKeyword.trim()} onClick={() => void useCustomMarketKeyword()}>使用我的关键词更新</button><button type="button" className="product-outline-button" onClick={() => { setKeywordMode("recommended"); void returnToRecommendedKeyword(); }}>返回系统推荐</button></div>
    </div>}

    <div className="market-import-row">
      <FolderOpen size={24} weight="duotone" />
      <span><b>{data.market_reference.current_sample ? "已导入今天的市场参考" : "尚未导入市场参考"}</b><small>使用现有 Ego Lite 搜索，由 Codex 整理公开字段后粘贴导入；不会打开第二个网站</small></span>
      <button type="button" onClick={() => setMarketImportOpen(true)}><UploadSimple size={16} />{data.market_reference.current_sample ? "修正导入" : "导入参考"}</button>
    </div>

    {expanded && <div className="market-sample-detail">
      <div className="market-sample-summary">
        <span><small>当前关键词</small><b>{data.market_reference.selected_keyword || "尚未选择"}</b></span>
        <span><small>近 30 天样本</small><b>{data.market_reference.benchmark.sample_days} 天</b></span>
        <span><small>前 10 位公开结果</small><b>{data.market_reference.benchmark.high_visibility_result_count} 条</b></span>
        <span><small>多日重复结构</small><b>{data.market_reference.benchmark.repeated_result_count} 个</b></span>
      </div>
      <div className="market-benchmark-panel">
        <header><span><TrendUp size={18} weight="duotone" /><b>高可见市场基准</b></span><em className={`confidence-${data.market_reference.benchmark.confidence}`}>{confidenceLabels[data.market_reference.benchmark.confidence] || data.market_reference.benchmark.confidence}</em></header>
        <div className="market-benchmark-grid">
          <span><small>公开标价中位数</small><b>{data.market_reference.benchmark.median_price === null ? "—" : moneyExact.format(data.market_reference.benchmark.median_price)}</b><em>{data.market_reference.benchmark.price_low === null || data.market_reference.benchmark.price_high === null ? "等待更多标价" : `${moneyExact.format(data.market_reference.benchmark.price_low)}–${moneyExact.format(data.market_reference.benchmark.price_high)}`}</em></span>
          <span><small>标题长度中位数</small><b>{data.market_reference.benchmark.median_title_length === null ? "—" : `${data.market_reference.benchmark.median_title_length} 字`}</b><em>只用于结构参考</em></span>
          <span><small>常见能力词</small><b>{data.market_reference.benchmark.common_title_terms.slice(0, 4).join(" · ") || "等待多日样本"}</b><em>不会复制完整标题</em></span>
          <span><small>常见公开标签</small><b>{data.market_reference.benchmark.common_tags.slice(0, 4).join(" · ") || "暂无稳定标签"}</b><em>仅来自人工导入字段</em></span>
        </div>
        <ul>{data.market_reference.benchmark.evidence.map((line) => <li key={line}>{line}</li>)}</ul>
      </div>
      {data.market_reference.current_sample ? <div className="market-result-table" role="table" aria-label="今天导入的公开搜索结果">
        <div role="row"><span>位置</span><span>标题</span><span>价格</span><span>公开标签</span></div>
        {data.market_reference.current_sample.results.map((result) => <div role="row" key={`${result.position}-${result.title}`}><span>#{result.position}</span><span>{result.title}</span><span>{result.price === null ? "—" : moneyExact.format(result.price)}</span><span>{result.tags.join("、") || "—"}</span></div>)}
      </div> : <div className="product-empty-state compact-market-empty"><MagnifyingGlass size={34} weight="duotone" /><h4>还没有今天的真实搜索参考</h4><p>先在已登录的 Ego Lite 中搜索当前关键词，再把 Codex 整理出的 JSON 导入。</p></div>}
    </div>}
    <footer><Info size={14} />推荐词只用于搜索验证；连续多日稳定后才判断高可见，不会称为“闲鱼官方热门”。</footer>
  </section>;
}
