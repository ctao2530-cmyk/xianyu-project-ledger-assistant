import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const require = createRequire(import.meta.url);
const { buildSync } = createRequire(require.resolve('vite/package.json'))('esbuild');
const { createElement } = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const built = buildSync({
  stdin: {
    contents: `export { referenceProductFixture } from './tests/reference-product-fixture';
      export { ProductLaunchWorkbench } from './src/pages/ProductLaunchWorkbench';
      export { MarketReferenceWorkbench } from './src/pages/ProductMarketWorkbench';`,
    resolveDir: fileURLToPath(new URL('../', import.meta.url)),
    loader: 'tsx',
  },
  bundle: true, write: false, format: 'cjs', platform: 'node', jsx: 'automatic',
  external: ['react', 'react/jsx-runtime'], mainFields: ['module', 'main'],
  loader: { '.css': 'empty' }, logLevel: 'silent',
});
const context = vm.createContext({ module: { exports: {} }, require });
vm.runInContext(built.outputFiles[0].text, context);
const { referenceProductFixture: data, ProductLaunchWorkbench, MarketReferenceWorkbench } = context.module.exports;
const unexpectedAction = () => { throw new Error('Rendering must not perform business actions'); };

test('shared preview data renders the real launch workbench without triggering actions', () => {
  const html = renderToStaticMarkup(createElement(ProductLaunchWorkbench, {
    data, busy: false, onCreateLaunchPlan: unexpectedAction,
    onCompleteLaunchPlan: unexpectedAction, onShowModification: unexpectedAction,
  }));
  assert.ok(html.includes('上新雷达'));
  assert.ok(html.includes('继续积累证据'));
  assert.ok(!html.includes('NaN'));
});

test('shared preview data renders recommended and custom market views with no imported samples', () => {
  for (const keywordMode of ['recommended', 'custom']) {
    const html = renderToStaticMarkup(createElement(MarketReferenceWorkbench, {
      data, expanded: true, busy: false, keywordMode, customKeyword: '', saveCommonKeyword: false,
      setKeywordMode: unexpectedAction, setCustomKeyword: unexpectedAction,
      setSaveCommonKeyword: unexpectedAction, setMarketImportOpen: unexpectedAction,
      chooseRecommendedKeyword: unexpectedAction, useCustomMarketKeyword: unexpectedAction,
      returnToRecommendedKeyword: unexpectedAction, snoozeMarketReminder: unexpectedAction,
      skipMarketReminder: unexpectedAction,
    }));
    assert.ok(html.includes('高可见市场基准'));
    assert.ok(html.includes('还没有今天的真实搜索参考'));
    assert.ok(!html.includes('NaN'));
  }
});
