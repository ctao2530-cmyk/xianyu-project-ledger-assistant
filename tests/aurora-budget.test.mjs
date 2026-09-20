import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';
import { readFileSync } from 'node:fs';
const source = readFileSync(new URL('../src/components/aurora/auroraParameters.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { auroraBufferSize, auroraDefaults } = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'));
test('backing buffers remain inside the GPU budget across mobile, retina and ultrawide displays', () => {
  for (const [w,h] of [[390,844],[1280,800],[1440,900],[1586,992],[3840,2160],[7680,4320]]) {
    for (const dpr of [1,1.25,2,3,4]) {
      const size = auroraBufferSize(w,h,dpr);
      assert.ok(size.width > 0 && size.height > 0);
      assert.ok(size.width * size.height <= 1_200_000);
      assert.ok(size.width <= w*.65*1.25 && size.height <= h*.65*1.25);
      assert.ok(Math.abs(size.width / size.height - w / h) < .015);
    }
  }
  assert.deepEqual(auroraBufferSize(1586,992,2),auroraBufferSize(1586,992,4));
});
test('motion contract is bounded and reduced-motion can use a reproducible still frame', () => {
  assert.equal(auroraDefaults.seed,17);
  assert.equal(auroraDefaults.testTimeSeconds,8);
  assert.equal(auroraDefaults.pointerParallax,false);
  assert.ok(auroraDefaults.fps <= 30 && auroraDefaults.lowPowerFps <= 20);
});
