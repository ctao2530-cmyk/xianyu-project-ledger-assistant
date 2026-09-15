import type { ProductView } from '../../data/localPlatformService';

/** Existing product facts only; exposure and conversion revenue are not interchangeable. */
export function ProductMetricSummary({product}: {product: ProductView}) {
  const count = new Intl.NumberFormat('zh-CN');
  const metrics = [
    ['经营浏览', product.browse_count],
    ['想要', product.want_count],
    ['咨询', product.inquiry_count],
    ['关联项目', product.converted_project_count],
  ] as const;
  return <section className="reference-product-metrics" aria-label="当前商品数据概览">
    <h4>数据概览</h4>
    <dl>{metrics.map(([label,value])=><div key={label}><dt>{label}</dt><dd>{count.format(value)}</dd></div>)}</dl>
    <details className="product-browse-accounting" aria-label="浏览量口径说明"><summary>浏览量统计口径</summary><p>平台原始 {count.format(product.raw_browse_count)}，已排除 {product.collection_views_excluded} 次成功采集自访问；经营策略只使用排除后的数据。</p></details>
  </section>;
}
