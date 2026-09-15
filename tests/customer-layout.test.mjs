import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const { buildSync } = createRequire(require.resolve('vite/package.json'))('esbuild');
const built = buildSync({
  stdin: { contents: `export {CustomerContextPanel} from './src/components/workspace/CustomerContextPanel'; export {CustomerProfileWorkspace} from './src/components/workspace/CustomerProfileWorkspace';`, resolveDir: fileURLToPath(new URL('..', import.meta.url)) },
  bundle: true, write: false, platform: 'node', format: 'cjs', loader: { '.css': 'empty' },
  external: ['react', 'react-dom/server'], mainFields: ['module', 'main'], logLevel: 'silent',
});
const scope = vm.createContext({ module: { exports: {} }, require });
vm.runInContext(built.outputFiles[0].text, scope);
const { CustomerContextPanel, CustomerProfileWorkspace } = scope.module.exports;
const customer = { id: 'qa-customer', name: '合成客户', source: 'xianyu', level: 'B', tags: [] };
const props = { customer, projects: [], pane: 'conversation', onViewProjects() {}, onClose() {} };

test('context panel exposes one top-right close control, not another profile opener', () => {
  const html = renderToStaticMarkup(React.createElement(CustomerContextPanel, props));
  assert.match(html, /id="customer-context-panel"/);
  assert.match(html, /<header class="customer-context-heading">[\s\S]*aria-label="关闭客户资料"[\s\S]*<\/header>/);
  assert.doesNotMatch(html, /customer-context-toggle|返回会话/);
  assert.match(html, /合成客户/);
});
test('X and local Escape close; already-handled Escape is left to child dialogs', () => {
  let closed = 0, stopped = 0;
  const panel = CustomerContextPanel({ ...props, onClose: () => closed++ });
  panel.props.children[0].props.children[1].props.onClick();
  panel.props.onKeyDown({ key: 'Escape', defaultPrevented: false, stopPropagation: () => stopped++ });
  panel.props.onKeyDown({ key: 'Escape', defaultPrevented: true, stopPropagation: () => stopped++ });
  panel.props.onKeyDown({ key: 'Tab', defaultPrevented: false });
  assert.equal(closed, 2);
  assert.equal(stopped, 1);
});
test('profile-only customers keep the same header action slot without inventing a conversation', () => {
  const html = renderToStaticMarkup(React.createElement(CustomerProfileWorkspace, {
    customer, view: 'conversation', caseId: null, onView() {},
    headerActions: React.createElement('button', { className: 'customer-context-toggle' }, '客户资料'),
  }));
  assert.match(html, /<div class="thread-header-actions"><button class="customer-context-toggle">客户资料/);
  assert.match(html, /尚无可直接打开的已关联会话/);
  assert.doesNotMatch(html, /话术库|同步历史/);
});
test('no linked profile remains a safe empty state, never nickname inference', () => {
  const html = renderToStaticMarkup(React.createElement(CustomerContextPanel, { ...props, customer: undefined }));
  assert.match(html, /不会按昵称推断身份/);
  assert.match(html, /aria-label="关闭客户资料"/);
});
test('page mounts the opener only while closed and restores its focus', async () => {
  const page = await readFile(new URL('../src/pages/CustomerMessagesPage.tsx', import.meta.url), 'utf8');
  assert.match(page, /const contextAction = !contextVisible && <Button/);
  assert.match(page, /contextVisible&&\(profile\|\|\(!profileId&&detail\)\)&&<CustomerContextPanel/);
  assert.match(page, /\(contextVisible \? contextCloseRef : contextTriggerRef\)\.current\?\.focus\(\)/);
  assert.match(page, /<div className="thread-header-actions"[\s\S]*className="phrase-library-trigger customer-appica-button"/);
});
