import {useEffect,useRef,type ReactNode} from 'react';
import {DotsThree} from '@phosphor-icons/react';
export function ActionMenu({children,label='更多',iconOnly=false}:{children:ReactNode;label?:string;iconOnly?:boolean}) {
  const root=useRef<HTMLDetailsElement>(null);
  useEffect(()=>{const outside=(e:PointerEvent)=>{if(root.current&&!root.current.contains(e.target as Node))root.current.open=false};document.addEventListener('pointerdown',outside);return()=>document.removeEventListener('pointerdown',outside)},[]);
  return <details ref={root} className={`customer-hub-more workspace-action-menu${iconOnly?' is-icon-only':''}`} onKeyDown={e=>{if(e.key==='Escape'&&root.current){root.current.open=false;root.current.querySelector('summary')?.focus()}}}><summary aria-label={label} title={iconOnly?label:undefined}>{iconOnly?<DotsThree size={24} weight="bold" aria-hidden="true"/>:label}</summary><div onClick={e=>{if((e.target as HTMLElement).closest('button,a')&&root.current)root.current.open=false}}>{children}</div></details>;
}
