import type { ReactNode } from 'react';
export function Tabs<T extends string>({label,items,value,onChange,vertical=false}:{label:string;items:Array<{key:T;label:string;icon?:ReactNode}>;value:T;onChange:(key:T)=>void;vertical?:boolean}) {
  return <nav className={`workspace-tabs ${vertical?'is-vertical':''}`} aria-label={label}>{items.map(item=><button type="button" key={item.key} aria-current={item.key===value?'page':undefined} onClick={()=>onChange(item.key)}>{item.icon}{item.label}</button>)}</nav>;
}
