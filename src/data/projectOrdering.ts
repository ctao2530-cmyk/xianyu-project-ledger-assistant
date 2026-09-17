import type { Project } from '../types';

function timestamp(value: string | null | undefined): number {
  const parsed = value ? Date.parse(value) : NaN;
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
}

/** Unknown update times sort last; IDs only resolve equal timestamps. */
export function compareProjectUpdates(left: Project, right: Project): number {
  const a = timestamp(left.updatedAt), b = timestamp(right.updatedAt);
  return a === b ? left.id.localeCompare(right.id) : a > b ? -1 : 1;
}
