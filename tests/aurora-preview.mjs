// S01 isolated fixture adapter. Reuses the existing complete mock/403 boundary.
// Run only in the source-checkpoint copy, never beside local credentials/data.
import { readFileSync, writeFileSync, existsSync, realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
const cwd = realpathSync(process.cwd());
if (!cwd.startsWith(realpathSync(tmpdir()) + "/") || existsSync('.env') || existsSync('data')) throw Error('S01 requires an isolated temporary source copy');
const original = readFileSync('tests/information-architecture-preview.mjs', 'utf8');
const target = "createRoot(document.getElementById('root')).render(location.search.includes('shell=1')?<FullApp/>:<App/>);";
if (!original.includes(target)) throw Error('Baseline fixture changed; review adapter');
const imports = `
import {AppShell, VisualPreferences} from './src/components/workspace/AppShell';
import {TopBar} from './src/components/workspace/TopBar';
import {AuroraTopNav} from './src/components/workspace/AuroraTopNav';
import {AuroraSample} from './src/components/workspace/AuroraSample';
import {House} from '@phosphor-icons/react';
`;
const sample = `
window.__auroraTest={time:new URLSearchParams(location.search).has('time')?Number(new URLSearchParams(location.search).get('time')):undefined,failure:new URLSearchParams(location.search).get('failure'),lowPower:location.search.includes('lowPower=1')};
function SampleShell(){
  const [active,setActive]=React.useState('首页概览');
  const [mounted,setMounted]=React.useState(true);
  React.useEffect(()=>{window.__toggleSample=()=>setMounted(v=>!v);return()=>delete window.__toggleSample},[]);
  const items=['首页概览','客户消息','项目管理','商品经营','经营记录','经营分析中心'].map((label,i)=>({label,displayLabel:['工作台','客户','项目','服务商品','收支经营','经营分析'][i],icon:House}));
  const secondary={商品经营:['经营总览','曝光分析','上新与修改','市场参考'].map((label,i)=>({label,key:['overview','exposure','launch','market'][i],route:'商品经营/'+['overview','exposure','launch','market'][i]}))};
  const navigate=(value)=>{setActive(value);location.hash=encodeURIComponent(value)};
  return mounted?<AppShell backgroundTest={window.__auroraTest}><main className="dashboard-main"><TopBar navigation={<AuroraTopNav active={active} items={items} secondary={secondary} selectedChild={()=>decodeURIComponent(location.hash).split('/')[1]||'overview'} onActiveChange={navigate} onSecondaryNavigate={(parent,route)=>{setActive(parent);location.hash=encodeURIComponent(route)}}/>} snapshot={snapshot} meta={{title:'S01 组件样板',subtitle:'合成验收',placeholder:''}} search="" onSearch={()=>{}} onMenu={()=>{}} activePage={active} reminders={[]} onReminderAction={()=>{}} onViewAllReminders={()=>{}} onRefreshReminders={()=>{}} onOpenSettings={()=>{}} profileName="合成账户" profilePlan="隔离样板"/><AuroraSample/></main></AppShell>:<p id="unmounted">Sample unmounted</p>;
}
createRoot(document.getElementById('root')).render(<React.StrictMode>{location.search.includes('sample=1')?<SampleShell/>:<FullApp/>}</React.StrictMode>);
`;
const fixture = original.replace("import React from 'react';", "import React from 'react';" + imports).replace(target, sample).replace("const qaPrelude=", "const qaPrelude=");
const output = resolve('tests/.aurora-preview-generated.mjs');
writeFileSync(output, fixture);
await import(output);
