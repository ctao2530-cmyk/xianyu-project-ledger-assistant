import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
test('control refinement is scoped and preserves responsive access',async()=>{
 const css=await readFile(new URL('../src/components/workspace/page-controls.css',import.meta.url),'utf8');
 assert.match(css,/min-height:44px/);
 assert.match(css,/:focus-visible/);
 assert.match(css,/\.product-command-card \{display:flex;flex-direction:column-reverse/);
 assert.match(css,/\.operating-track-card:has\(.operating-track-optional:not\(\[open\]\)\)/);
 assert.match(css,/@media\(max-width:600px\)/);
 assert.doesNotMatch(css,/display:none|pointer-events:none|!important/);
});
