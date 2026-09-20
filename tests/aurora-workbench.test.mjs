import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const { buildSync } = createRequire(require.resolve('vite/package.json'))('esbuild');
const built = buildSync({
  stdin: { contents: "export {AuroraWorkbench} from './src/components/workbench/AuroraWorkbench';", resolveDir: fileURLToPath(new URL('..', import.meta.url)) },
  bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic',
  external: ['react', 'react/jsx-runtime', 'react-dom', 'recharts'], mainFields: ['module', 'main'], logLevel: 'silent',
});
const events = [];
const context = vm.createContext({ module: { exports: {} }, require, Intl, Date, Event,
  window: { dispatchEvent: event => events.push(event.type) },
  document: { querySelector: () => ({ scrollIntoView() {} }) },
});
vm.runInContext(built.outputFiles[0].text, context);
const { AuroraWorkbench } = context.module.exports;
const Icon = () => null;
const metrics = ['待处理消息', '客户总数', '进行中项目', '本月收入'].map((label, i) => ({ label, value: [2, 4, 3, '¥1,750.00'][i], icon: Icon, note: '已有统计', href: '#existing-' + i }));
function props(overrides = {}) {
  return { snapshot: { settings: { profileName: '合成配置名称' } }, content: {
    outstanding: 3900, outstandingCount: 1, onProjects() {}, onQuickAccounting() {}, onAnalysis() {},
    reminders: React.createElement('span', null, '提醒插槽'), projects: React.createElement('span', null, '项目插槽'), recent: React.createElement('span', null, '收款插槽'),
  }, taskList: React.createElement('span', null, '原待办控制器插槽'), cashflow: { income: 1750, expenses: 450 }, points: [], metrics, actions: [], state: '', hasMore: false,
  dueToday: [], category: '全部', onCategoryChange() {}, hour: 9, ...overrides };
}
const render = value => renderToStaticMarkup(React.createElement(AuroraWorkbench, value));
function elements(node) {
  if (!React.isValidElement(node)) return [];
  return [node, ...React.Children.toArray(node.props.children).flatMap(elements)];
}
const label = element => React.Children.toArray(element.props.children).filter(value => typeof value === 'string').join('');

test('home presents supplied cash totals and every promoted slot without side effects', () => {
  events.length = 0;
  const html = render(props());
  for (const text of ['¥1,750.00', '¥3,900.00', '¥450.00', '提醒插槽', '项目插槽', '收款插槽', '原待办控制器插槽']) assert.ok(html.includes(text), text);
  assert.deepEqual(events, []);
  assert.doesNotMatch(html, /12,460|8,200|林墨|较上周|会议|发票|换一换/);
});

test('empty and zero statistics remain zero rather than sample values', () => {
  const value = props({ snapshot: { settings: { profileName: '' } }, cashflow: { income: 0, expenses: 0 }, metrics: metrics.map(item => ({ ...item, value: 0 })) });
  value.content.outstanding = 0; value.content.outstandingCount = 0;
  const html = render(value);
  assert.match(html, /¥0.00/); assert.match(html, /本月暂无已记录收支/);
});

test('shortcuts invoke existing callbacks only after explicit clicks', () => {
  const calls = [];
  const value = props();
  value.content = { ...value.content, onProjects: () => calls.push('projects'), onQuickAccounting: () => calls.push('accounting'), onAnalysis: () => calls.push('analysis') };
  const nodes = elements(AuroraWorkbench(value));
  for (const text of ['项目管理 / 新建', '记录一笔收款', '查看经营分析']) nodes.find(node => node.type === 'button' && label(node) === text).props.onClick();
  assert.deepEqual(calls, ['projects', 'accounting', 'analysis']);
  nodes.find(node => node.type === 'button' && label(node) === '打开小策对话').props.onClick();
  assert.equal(events.at(-1), 'xunying:global-agent-open');
});

test('today delivery keeps the exact project id and existing requirement section', () => {
  const id = 'project / 中文';
  const html = render(props({ dueToday: [{ id, name: '独立交付项目' }] }));
  assert.ok(html.includes('#' + encodeURIComponent(`项目管理/${id}/overview?section=requirements`)));
  assert.match(html, /独立交付项目/);
});

test('partial results are labelled, and task shortcuts preserve selected category', () => {
  let selected;
  const value = props({ hasMore: true, actions: [{ category: '待确认需求' }], category: '待确认需求', onCategoryChange: next => { selected = next; } });
  const nodes = elements(AuroraWorkbench(value));
  const filter = nodes.find(node => node.type === 'button' && node.props['aria-pressed'] === true);
  filter.props.onClick();
  assert.equal(selected, '待确认需求');
  assert.match(render(value), /已加载/);
});

test('closing 小策 after navigation returns focus to a currently visible control', async () => {
  const { readFile } = await import('node:fs/promises');
  const source = await readFile(new URL('../src/components/GlobalAgentLauncher.tsx', import.meta.url), 'utf8');
  const closeSource = source.slice(source.indexOf('  const close = () =>'), source.indexOf('  const panelGeometry'));
  const ts = await import('typescript');
  const code = ts.default.transpileModule(closeSource, { compilerOptions: { target: ts.default.ScriptTarget.ES2022 } }).outputText;
  for (const fromHome of [true, false]) {
    const focused = []; let frame;
    const control = (name, visible) => ({ isConnected: true, getClientRects: () => visible ? [{}] : [], focus: () => focused.push(name) });
    const opener = control('opener', true), launcher = control('launcher', true), nav = control('nav', true);
    const scope = vm.createContext({ homeEntry: fromHome, homeOpenerRef: { current: fromHome ? opener : null }, buttonRef: { current: launcher }, setOpen() {},
      window: { requestAnimationFrame: callback => { frame = callback; } },
      document: { querySelector: selector => selector.includes('aria-current') ? nav : control('mobile-menu', false) },
    });
    vm.runInContext(code + '\nclose();', scope);
    // The route changed between close() and its animation frame.
    if (fromHome) opener.isConnected = false;
    else launcher.getClientRects = () => [];
    frame();
    assert.deepEqual(focused, [fromHome ? 'launcher' : 'nav']);
  }
});
