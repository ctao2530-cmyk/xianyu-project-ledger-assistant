import { useEffect, useState } from 'react';
import type { LedgerSnapshot } from '../../types';
import { subscribeCustomerEvents } from '../../data/customerEvents';
import { readWorkbench } from '../../features/workbench/client';
import type { WorkbenchPage } from '../../features/workbench/domain';
export type { WorkbenchAction } from '../../features/workbench/domain';

/** Each page is a bounded SQLite projection. Refresh always restarts pagination. */
export function useWorkbenchActions(snapshot: LedgerSnapshot) {
  const [page, setPage] = useState<WorkbenchPage | null>(null);
  const [state, setState] = useState('正在核对客户与需求待办…');
  const [generation, setGeneration] = useState(0);
  const [offset, setOffset] = useState(0);
  const customerIds = snapshot.customers.map(c => c.id).join('|');
  const refresh = () => { setOffset(0); setGeneration(value => value + 1); };
  useEffect(() => subscribeCustomerEvents(refresh), []);
  useEffect(() => { setOffset(0); setPage(null); }, [customerIds]);
  useEffect(() => {
    const controller = new AbortController();
    if (offset === 0) setPage(null);
    setState('正在核对客户与需求待办…');
    readWorkbench(offset, controller.signal).then(next => {
      if (controller.signal.aborted) return;
      setPage(previous => offset === 0 ? next : { ...next, items: [...new Map([...(previous?.items || []), ...next.items].map(item => [item.id, item])).values()] });
      setState('');
    }).catch(() => { if (!controller.signal.aborted) setState('客户与需求待办读取失败，当前列表不完整。请刷新重试。'); });
    return () => controller.abort();
  }, [generation, offset, customerIds]);
  return { remote: page?.items || [], state, refresh, hasMore: page?.hasMore || false,
    asOf: page?.asOf, total: page?.total, loadMore: () => { if (!state && page?.hasMore) setOffset(page.offset + 100); } };
}
