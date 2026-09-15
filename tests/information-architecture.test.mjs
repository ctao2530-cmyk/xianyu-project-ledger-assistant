import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const read=path=>readFileSync(new URL('../'+path,import.meta.url),'utf8');
test('six primary entries retain legacy route recognition',()=>{
  const app=read('src/App.tsx');
  const nav=app.slice(app.indexOf('const navItems:'),app.indexOf('const secondaryNavItems:'));
  const visible=nav.split('\n').filter(line=>line.trim().startsWith('{ label:')&&!line.includes('hidden: true'));
  assert.equal(visible.length,7); // Six business entries plus auxiliary settings.
  for(const label of ['工作台','客户','项目','商品','收支','经营分析'])assert.ok(visible.some(line=>line.includes(`displayLabel: "${label}"`)));
  assert.match(app,/navItems.some/);
  assert.match(app,/projectSectionHash\(route.projectRoute\)/);
});
test('customer panes retain a stable binding and archive scope',()=>{
  const page=read('src/pages/CustomerMessagesPage.tsx');
  const library=read('src/components/CustomerImageLibrary.tsx');
  assert.match(page,/c.id === detail\?\.linked_customer_id/);
  assert.match(page,/CustomerRequirementBlueprintPage embedded/);
  assert.match(page,/scoped initialConversationId=\{detail.id\}/);
  assert.match(library,/conversationId: scoped \? initialConversationId/);
  assert.match(page,/xunying:customer-created/);
});
test('formal delivery uses explicit node relationships, not task completion',()=>{
  const source=read('src/components/ProjectDeliverySummary.tsx');
  assert.match(source,/requirementCase\(caseId, version\)/);
  assert.match(source,/stage.capability_ids.includes\(capability.id\)/);
  assert.match(source,/gate.stage_ids.some/);
  assert.match(source,/未记录客户验收结果/);
  assert.doesNotMatch(source,/snapshot.tasks|status === ['"]done['"]/);
});
test('workbench is read-only and payment confirmation carries exact project',()=>{
  const source=read('src/components/ActionWorkbench.tsx');
  assert.match(source,/getProjectFinancials\(snapshot\)/);
  assert.match(source,/onConfirmPayment\(action.projectId!/);
  assert.doesNotMatch(source,/runAgent|sendMessage|createCustomer|createProject|confirmRequirementProposal/);
});
test('cashflow track is optional and filters survive navigation',()=>{
  const source=read('src/pages/OperatingRecordsPage.tsx');
  assert.match(source,/<details className="operating-track-optional"[^>]*>/);
  assert.match(source,/onNavigateProject\(record.projectId!/);
  assert.match(source,/writeUiSession\('records-type',type\)/);
});
