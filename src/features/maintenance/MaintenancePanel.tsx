import { useEffect, useState } from 'react';
import { localApi } from '../../data/localApi';
interface Readiness { status:string; database:string; schema_revision?:string; }
interface Usage { date:string; attempts:number; daily_limit:number; admission_paused:boolean; completed_artifacts:number; artifacts_with_usage:number; reported_tokens:number|null; scope:string; }
export function MaintenancePanel({mode}:{mode:'readiness'|'analysis-usage'}) {
 const [data,setData]=useState<Readiness|Usage|null>(null);const [error,setError]=useState('');const [generation,setGeneration]=useState(0);
 useEffect(()=>{const abort=new AbortController();setData(null);setError('');localApi<Readiness|Usage>(`/api/maintenance/${mode}`,{signal:abort.signal,headers:{'X-Yuda-Desktop':'1'}}).then(value=>{if(!abort.signal.aborted)setData(value);}).catch(()=>{if(!abort.signal.aborted)setError('诊断读取失败，请检查本机服务版本与连接。');});return()=>abort.abort();},[mode,generation]);
 return <section className="acceptance-panel" aria-label={mode==='readiness'?'本机就绪检查':'持续分析用量'}><h3>{mode==='readiness'?'本机就绪检查':'持续分析用量'}</h3>
 {error?<p role="alert">{error}</p>:!data?<p role="status">正在读取本机状态…</p>:mode==='readiness'?<p>数据库：{(data as Readiness).database==='readable'?'可读取':'不可用'} · 迁移版本：{(data as Readiness).schema_revision||'未记录'}。此检查不代表外部渠道或模型已接通。</p>:<><p>{(data as Usage).date}（北京时间）· 已创建 {(data as Usage).attempts} / {(data as Usage).daily_limit} 次分析尝试。{(data as Usage).admission_paused?'已达到当日上限，新的自动分析等待下一日或人工调整配置。':''}</p><p>已保存产物 {(data as Usage).completed_artifacts} 份，其中 {(data as Usage).artifacts_with_usage} 份有用量记录；提供方报告 token：{(data as Usage).reported_tokens??'未知'}。</p><p>{(data as Usage).scope}。此处不是账单金额。</p></>}
 <button type="button" onClick={()=>setGeneration(v=>v+1)}>刷新本机状态</button>
 </section>;
}
