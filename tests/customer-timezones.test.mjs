import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import test from 'node:test';

const page = readFileSync(new URL('../src/pages/CustomerMessagesPage.tsx', import.meta.url),'utf8');
const library = readFileSync(new URL('../src/components/CustomerImageLibrary.tsx', import.meta.url),'utf8');
// Execute the actual formatter declarations, without importing page side effects.
const expressions = [
  [page, 'dateTime'], [library, 'imageTime'], [library, 'fullTime'],
].map(([source,name]) => {
  const match = source.match(new RegExp(`const ${name} = (new Intl.DateTimeFormat\\([\\s\\S]*?\\n\\}\\));`));
  assert.ok(match, `Missing ${name}`);
  return [name,match[1]];
});
for (const zone of ['UTC','America/Los_Angeles','Asia/Shanghai']) {
  for (const [name,expression] of expressions) {
    test(`${name} remains Beijing time in ${zone}`, () => {
      const actual = JSON.parse(execFileSync(process.execPath,['-e', `const f=${expression}; console.log(JSON.stringify(['2026-09-08T10:53:00Z','2026-09-08T16:30:00Z','2026-09-08T18:53:00+08:00'].map(t=>Object.fromEntries(f.formatToParts(new Date(t)).map(p=>[p.type,p.value])))));`],{env:{...process.env,TZ:zone},encoding:'utf8'}));
      assert.equal(actual[0].hour,'18'); assert.equal(actual[0].minute,'53');
      assert.equal(Number(actual[1].day),9); assert.equal(actual[1].hour,'00'); assert.equal(actual[1].minute,'30');
      assert.deepEqual(actual[0],actual[2]);
    });
  }
}
