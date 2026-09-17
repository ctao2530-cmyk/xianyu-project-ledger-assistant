import { localApi } from '../../data/localApi';
import type { WorkbenchPage } from './domain';
export async function readWorkbench(offset: number, signal: AbortSignal): Promise<WorkbenchPage> {
  const result = await localApi<WorkbenchPage>(`/api/workbench/actions?offset=${offset}&limit=100`, { signal, headers: { 'X-Yuda-Desktop': '1' } });
  if (!Array.isArray(result.items) || !Number.isInteger(result.total) || typeof result.hasMore !== 'boolean') throw new Error('工作台接口版本不兼容，请更新本机服务');
  return result;
}
