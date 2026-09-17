/** Display-only ledger ranges. Never rewrite stored dates or accounting records. */
export type RecordsPeriod = 'all' | 'month' | 'history';

export { businessDate as ledgerDateKey } from '../shared/time/businessDate';
import { businessDate as ledgerDateKey } from '../shared/time/businessDate';

export function validLedgerMonth(value: string): boolean {
  return /^\d{4}-(0[1-9]|1[0-2])$/.test(value) && !value.startsWith('0000');
}

export function restoreRecordsPeriod(value: string): RecordsPeriod {
  return value === 'month' || value === 'history' ? value : 'all';
}

export function inLedgerPeriod(value: string, month: string | null): boolean {
  return month === null || ledgerDateKey(value).slice(0, 7) === month;
}

export function ledgerMonthLabel(month: string): string {
  return `${month.slice(0, 4)}年${Number(month.slice(5))}月`;
}

export function summarizeCashflow(records: ReadonlyArray<{ type: string; amount: number }>) {
  return records.reduce((total, record) => {
    // Keep the existing net-income definition: receipts minus both refund paths.
    if (record.type === 'income' || record.type === 'refund') total.income += record.amount;
    if (record.type === 'expense') total.expenses -= record.amount;
    return total;
  }, { income: 0, expenses: 0 });
}
