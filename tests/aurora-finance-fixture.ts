import type { LedgerSnapshot } from '../src/types';
// Independent synthetic ledger. Values are chosen to expose refunds and Beijing month boundaries.
export function financeFixture(state='normal'): LedgerSnapshot {
 const customer={id:'qa-customer',name:'合成验收客户',source:'xianyu',level:'C',followUpStatus:'contacted',channelIdentities:[]};
 const project={id:'qa-project',name:'合成历史项目',customerId:'qa-customer',category:'client',totalAmount:10000,startDate:'2025-12-01',dueDate:'2026-09-15',status:'in_progress',progress:0,accent:'blue',estimatedHours:10};
 const s={customers:[customer],projects:[project],payments:[
  {id:'old-year',amount:100,paidAt:'2025-12-15',status:'confirmed'},
  {id:'august',amount:200,paidAt:'2026-08-20',status:'confirmed'},
  {id:'boundary-before',amount:30,paidAt:'2026-08-31T15:59:59Z',status:'confirmed'},
  {id:'boundary-after',amount:40,paidAt:'2026-08-31T16:00:00Z',status:'confirmed'},
  {id:'september',amount:300,paidAt:'2026-09-09T10:30:00+08:00',status:'confirmed'},
  {id:'legacy-refund',amount:50,paidAt:'2026-08-25',status:'refunded'},
  {id:'pending',amount:9000,paidAt:'',dueAt:'2026-09-15',status:'pending'},
 ].map(p=>({dueAt:'',projectId:project.id,customerId:customer.id,type:'milestone',notes:'隔离验收',...p})),expenses:[
  {id:'expense-old',name:'合成往年费用',amount:10,paidAt:'2025-12-16'},
  {id:'expense-august',name:'合成八月费用',amount:20,paidAt:'2026-08-21'},
  {id:'expense-september',name:'合成九月费用',amount:30,paidAt:'2026-09-08'},
 ].map(e=>({...e,projectId:project.id,category:'software',notes:'仅用于隔离验收'})),
 settlementIssues:[{id:'issue-refund',projectId:project.id,type:'partial_refund',reason:'合成退款',refundAmount:25,receivableImpact:0,occurredAt:'2026-08-26'}],
 tasks:[],attachments:[],changeOrders:[],logs:[],completedOrderCount:0,settings:{xianyuStartedAt:'2025-12-01',monthlyIncomeGoal:1000,profileName:'合成验收账户',notificationsEnabled:false}} as unknown as LedgerSnapshot;
 if(state==='empty'){s.projects=[];s.payments=[];s.expenses=[];s.settlementIssues=[];}
 if(state==='long'){s.projects[0].name='合成长期交付与维护项目 · 多阶段支付和需求边界核对'.repeat(5);s.expenses[0].name='合成超长费用名称与说明'.repeat(12);}
 if(state==='undated'){s.payments[0].paidAt='';s.expenses[0].paidAt='';s.payments.find(p=>p.id==='pending')!.dueAt='';}
 if(state==='negative'){s.settlementIssues[0].refundAmount=750;}
 if(state==='aging'||state==='many'){
  s.projects=[];s.payments=[];s.expenses=[];s.settlementIssues=[];
  const rows=[['长账龄项目',-70,800],['阶段交付项目',-40,600],['近期回款项目',-7,400],['今日到期项目',0,500],['下月回款项目',20,900],['未约定收款项目',null,300],['计划冲突项目',-5,200],['终止待结算项目',-15,150]];
  rows.push(...Array.from({length:state==='many'?40:7},(_,i)=>['合成跟进项目 '+(i+1),-3,100]));
  const day=(n:number)=>new Date(Date.UTC(2026,8,17+n)).toISOString().slice(0,10);
  rows.forEach(([name,days,amount],i)=>{const id=i===0?'qa-project':'qa-aging-'+i;s.projects.push({...project,id,name:String(name),totalAmount:Number(amount)} as LedgerSnapshot['projects'][number]);if(days!==null)s.payments.push({id:'aging-payment-'+i,projectId:id,customerId:customer.id,amount:i===6?Number(amount)+50:i===0?500:Number(amount),status:'pending',type:'final',paidAt:'',dueAt:day(Number(days))} as LedgerSnapshot['payments'][number]);if(i===0)s.payments.push({id:'aging-second',projectId:id,customerId:customer.id,amount:300,status:'pending',type:'milestone',paidAt:'',dueAt:day(10)} as LedgerSnapshot['payments'][number]);if(i===7)s.settlementIssues.push({id:'qa-terminal',projectId:id,type:'project_cancelled',reason:'合成终止记录',occurredAt:day(-10),refundAmount:0,receivableImpact:0} as LedgerSnapshot['settlementIssues'][number]);});
 }
 return s;
}
