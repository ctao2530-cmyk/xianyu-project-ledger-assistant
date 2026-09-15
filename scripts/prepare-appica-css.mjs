import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import postcss from 'postcss';

// Official utilities/tokens, scoped to customers; exclude the global HTML reset.
const require = createRequire(import.meta.url);
const root = postcss.parse(await readFile(require.resolve('@appica/ui-react/css'), 'utf8'));
root.walkAtRules('layer', rule => { if (rule.params === 'base') rule.remove(); });
root.walkRules(rule => {
  let parent = rule.parent;
  while (parent) { if (parent.type === 'atrule' && /keyframes$/.test(parent.name)) return; parent = parent.parent; }
  rule.selectors = rule.selectors.map(selector => selector.includes(':root') || selector === ':host'
    ? selector.replace(/:root|:host/g, '.customer-focus')
    : '.customer-focus ' + selector);
});
const directory = new URL('../src/vendor/', import.meta.url);
await mkdir(directory, { recursive: true });
const license = await readFile(new URL('../node_modules/@appica/ui-react/LICENSE', import.meta.url), 'utf8');
await writeFile(new URL('appica-scoped.css', directory), '/*! Generated from @appica/ui-react 1.1.0. Do not hand-edit.\n' + license + '\n*/\n' + root.toString());
