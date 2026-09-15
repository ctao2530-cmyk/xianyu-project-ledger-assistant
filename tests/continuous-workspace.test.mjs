import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
test('continuous shell removes outer isolation while preserving internal content spacing',async()=>{
 const css=await readFile(new URL('../src/components/workspace/retained-workspace-layout.css',import.meta.url),'utf8');
 assert.match(css,/\.dashboard-main \{padding:0;min-height:100dvh;background:#fff/);
 assert.match(css,/\.top-header \{margin:0;padding:8px 24px;box-shadow:none;border-bottom:0/);
 assert.match(css,/\.page-route-view \{padding:24px;/);
 assert.match(css,/\.page-route-view>\.action-workbench \{[^}]*border:0;border-radius:0/);
 assert.match(css,/@media\(max-width:700px\)/);
});
