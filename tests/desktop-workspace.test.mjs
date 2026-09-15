import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
import test from 'node:test';
const read=p=>readFileSync(new URL('../'+p,import.meta.url),'utf8');
test('desktop shell uses independent navigation and explicit legacy-route inputs',()=>{
 const app=read('src/App.tsx'), sidebar=read('src/components/workspace/Sidebar.tsx');
 assert.match(app,/<AppShell>/);assert.match(app,/items=\{navItems\}/);
 assert.match(sidebar,/onSecondaryNavigate\(label, child.route\)/);
 assert.match(sidebar,/inert=\{mobile && !open/);
});
test('customer context follows explicit profile and avoids duplicate expanded domains',()=>{
 const page=read('src/pages/CustomerMessagesPage.tsx'),panel=read('src/components/workspace/CustomerContextPanel.tsx');
 assert.match(page,/customer=\{linkedCustomer\}/);assert.match(page,/pane=\{pane.view\}/);
 assert.match(panel,/pane!=='requirements'/);assert.match(panel,/pane!=='projects'/);
 assert.match(page,/className="conversation-history-trigger"/);
});
test('customer filters persist while identity is never inferred from display names',()=>{
 const master=read('src/components/workspace/MasterList.tsx');
 assert.match(master,/channelIdentities/);assert.match(master,/conversationId/);
 assert.match(master,/setItem\('xunying-master-scope'/);
 assert.doesNotMatch(master,/customer_name\s*===/);
});
test('finance detail and analysis cannot duplicate the same visible rows',()=>{
 const source=read('src/pages/OperatingRecordsPage.tsx');
 assert.match(source,/onToggle=\{e=>setAnalysisView\(e.currentTarget.open\)\}/);
 assert.match(source,/className="operating-record-list" hidden=\{analysisView\}/);
});
test('analysis keeps advanced capabilities after the main conclusion',()=>{
 const source=read('src/pages/BusinessAnalysisPage.tsx');
 assert.ok(source.indexOf('className="analysis-command-bar"')<source.indexOf('<PredictionForecastWorkbench'));
 assert.match(source,/<summary>预测与校准/);assert.match(source,/<summary>历史分析记录/);
});
test('scheme B defines explicit mobile and reduced motion fallbacks',()=>{
 const css=read('src/desktop-workspace.css');
 assert.match(css,/width:80px;background:#111827/);assert.match(css,/max-width:700px/);
 assert.match(css,/prefers-reduced-motion:reduce/);assert.match(css,/outline:2px solid/);
});
