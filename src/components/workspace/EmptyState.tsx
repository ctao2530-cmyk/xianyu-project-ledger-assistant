import type {ReactNode} from 'react';
export function EmptyState({children}:{children:ReactNode}) {return <div className="workspace-empty" role="status">{children}</div>}
