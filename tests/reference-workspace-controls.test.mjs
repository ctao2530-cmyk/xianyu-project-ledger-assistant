import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

test('project customer filter uses stable identity and participates in paging and session restore', async()=>{
  const source=await readFile(new URL('../src/pages/ProjectWorkspacePage.tsx',import.meta.url),'utf8');
  assert.match(source,/readUiSession\('projects-customer'\)/);
  assert.match(source,/item.project.customerId !== customerFilter/);
  assert.match(source,/pageSize,customerFilter/);
  assert.match(source,/aria-label="按客户筛选项目"/);
  assert.ok(source.includes('setSearch("");setCustomerFilter("");setStatus("all")'));
});

test('analysis compact queue preserves lifecycle filters and explicit actions behind disclosure', async()=>{
  const source=await readFile(new URL('../src/pages/BusinessAnalysisPage.tsx',import.meta.url),'utf8');
  assert.match(source,/active: "未完成"/);
  assert.match(source,/select className="reference-queue-filter" aria-label="建议生命周期筛选"/);
  assert.match(source,/details className=\{`analysis-queue-card reference-queue-row/);
  assert.match(source,/onUpdate=\{\(status\) => requestRecommendationUpdate\(recommendation, status\)\}/);
  assert.match(source,/onStart=\{\(\) => openStartConfirmation\(recommendation\)\}/);
});

test('product overview uses supported metrics and keeps the immutable accounting explanation', async()=>{
  const metrics=await readFile(new URL('../src/components/workspace/ProductMetricSummary.tsx',import.meta.url),'utf8');
  const page=await readFile(new URL('../src/pages/ProductIntelligencePage.tsx',import.meta.url),'utf8');
  for(const field of ['browse_count','want_count','inquiry_count','converted_project_count','raw_browse_count','collection_views_excluded'])assert.ok(metrics.includes('product.'+field));
  assert.match(page,/<details className="product-profit-formula">/);
  const linked=await readFile(new URL('../src/components/workspace/ProductLinkedProjects.tsx',import.meta.url),'utf8');
  assert.match(page,/<ProductLinkedProjects projects=\{selected.linked_projects\}/);
  assert.match(linked,/项目管理\/\$\{project.project_id\}\/overview/);
  for (const field of ['net_confirmed_total','profit_total','expense_total','refund_total','relation_source','latest_confirmed_at']) assert.ok(linked.includes('project.'+field));
  assert.match(linked,/aria-expanded=\{open\}/);
  assert.match(linked,/<table aria-label="当前商品关联项目与实际利润">/);
});

test('customer menus retain accessible names and scoped archives reuse parent history entry', async()=>{
  const menu=await readFile(new URL('../src/components/workspace/ActionMenu.tsx',import.meta.url),'utf8');
  const page=await readFile(new URL('../src/pages/CustomerMessagesPage.tsx',import.meta.url),'utf8');
  const library=await readFile(new URL('../src/components/CustomerImageLibrary.tsx',import.meta.url),'utf8');
  assert.match(menu,/summary aria-label=\{label\}/);
  assert.match(menu,/e.key==='Escape'/);
  assert.match(page,/<ActionMenu iconOnly label="更多会话操作">/);
  assert.match(library,/!scoped && <button type="button" className="customer-image-history-button"/);
  assert.match(library,/!scoped && <button type="button" className="customer-image-history-button-mobile"/);
});

test('project filters share the row predicate and mobile rows have bounded columns', async()=>{
  const source=await readFile(new URL('../src/pages/ProjectWorkspacePage.tsx',import.meta.url),'utf8');
  const css=await readFile(new URL('../src/components/workspace/reference-workspace.css',import.meta.url),'utf8');
  assert.match(source,/searched.filter\(item => matchesStatus\(item, status\)\)/);
  assert.match(source,/searched.filter\(item => matchesStatus\(item, value\)\).length/);
  assert.doesNotMatch(source,/定制开发"\)\} · \{project.id\}/);
  assert.match(css,/project-hub-shell \{[^}]*grid-template-columns:minmax\(0,1fr\)/);
  assert.match(css,/project-hub-list>article \{display:grid;grid-template-columns:minmax\(0,1fr\) minmax\(0,1fr\)/);
  assert.match(css,/status-completed\) \{background:#e5f7ed;color:#16834b/);
});

test('workbench separates actionable reason from the actual object and preserves payment confirmation', async()=>{
  const source=await readFile(new URL('../src/components/ActionWorkbench.tsx',import.meta.url),'utf8');
  assert.match(source,/<h2>\{action.detail\}<\/h2>/);
  assert.match(source,/className="workbench-action-object" title=\{action.title\}>\{action.title\}/);
  assert.match(source,/onConfirmPayment\(action.projectId!\)/);
});

test('analysis metrics display their primary label once without decorative repeated facts', async()=>{
  const source=await readFile(new URL('../src/pages/BusinessAnalysisPage.tsx',import.meta.url),'utf8');
  const card=source.slice(source.indexOf('function MetricCard('),source.indexOf('function AnalysisStateBadge('));
  assert.equal((card.match(/\{label\}/g)||[]).length,1);
  assert.doesNotMatch(card,/当前经营事实/);
  assert.match(card,/\{secondaryValue\}/);
  assert.match(card,/\{footer\}/);
});

test('product controls occupy their object workspace without duplicate creation entry', async()=>{
  const page=await readFile(new URL('../src/pages/ProductIntelligencePage.tsx',import.meta.url),'utf8');
  const workspace=await readFile(new URL('../src/components/workspace/ProductOverviewWorkspace.tsx',import.meta.url),'utf8');
  assert.match(page,/management=\{overviewControls\} overview=\{overviewFacts\} onAdd=\{openRegistration\}/);
  assert.match(page,/!selected && <>\{overviewFacts\}\{overviewControls\}<\/>/);
  assert.match(page,/!selected && <button[^\n]+onClick=\{openRegistration\}/);
  assert.match(workspace,/\{overview\}\s*<\/aside>/);
  assert.match(workspace,/\{context\}\{management\}<\/ContextPanel>/);
});

test('product split and primary-action ordering have responsive scoped styles', async()=>{
  const css=await readFile(new URL('../src/components/workspace/reference-workspace.css',import.meta.url),'utf8');
  assert.match(css,/\.product-object-detail \.product-detail-grid \{grid-template-columns:minmax\(0,1\.4fr\) minmax\(210px,1fr\)/);
  assert.match(css,/\.product-object-workspace \.product-master-heading \.product-primary-button \{order:0;/);
  assert.match(css,/@media\(max-width:1450px\)/);
  assert.match(css,/\.project-list-pagination :is\(button,select\) \{min-height:44px/);
});
