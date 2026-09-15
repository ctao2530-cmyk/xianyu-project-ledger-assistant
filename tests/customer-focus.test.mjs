import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = path => readFile(new URL('../' + path, import.meta.url), 'utf8');
test('channel toolbar is composed into the customer master without losing refresh', async () => {
  const page = await source('src/pages/CustomerMessagesPage.tsx');
  const master = await source('src/components/workspace/MasterList.tsx');
  assert.match(page, /<MasterList toolbar=\{<MessagesToolbar/);
  assert.match(master, /\{toolbar\}/);
  assert.match(page, /onRefresh=\{\(\) => void refreshCurrent\(\)\}/);
});
test('mobile detail selection and return preserve route-driven navigation', async () => {
  const page = await source('src/pages/CustomerMessagesPage.tsx');
  assert.match(page, /setMobileList\(!readConversationRouteId\(\) && !readProfile\(\)\)/);
  assert.match(page, /setMobileList\(false\);setProfileId\(null\);setSelectedId\(id\)/);
  assert.match(page, /customer-list-back/);
  assert.match(page, /window.addEventListener\("popstate", syncRoute\)/);
});
test('scoped visual roles replace nested bubble gradients and stacked phone panes', async () => {
  const css = await source('src/components/workspace/customer-focus.css');
  assert.match(css, /show-customer-list .messages-workbench>:not\(.workspace-master\)/);
  assert.match(css, /show-customer-detail .workspace-master \{display:none/);
  assert.match(css, /thread-messages p \{[^}]*font-size:14px[^}]*background:transparent/);
  assert.match(css, /:focus-visible/);
});
