// Synthetic ledger only. No identifiers or amounts copied from the real account.
export const recordsHistorySnapshot = {
  customers: [{ id: 'qa-customer', name: '合成验收客户', source: 'xianyu', status: 'new', channelIdentities: [] }],
  projects: [{ id: 'qa-project', name: '合成历史项目', customerId: 'qa-customer', totalAmount: 10000, startDate: '2025-12-01', dueDate: '2026-09-15', status: 'in_progress', progress: 0, accent: 'blue', estimatedHours: 10 }],
  payments: [
    { id: 'old-year', amount: 100, paidAt: '2025-12-15', status: 'confirmed' },
    { id: 'august', amount: 200, paidAt: '2026-08-20', status: 'confirmed' },
    { id: 'boundary-before', amount: 30, paidAt: '2026-08-31T15:59:59Z', status: 'confirmed' },
    { id: 'boundary-after', amount: 40, paidAt: '2026-08-31T16:00:00Z', status: 'confirmed' },
    { id: 'september', amount: 300, paidAt: '2026-09-09T10:30:00+08:00', status: 'confirmed' },
    { id: 'legacy-refund', amount: 50, paidAt: '2026-08-25', status: 'refunded' },
    { id: 'pending', amount: 9000, paidAt: '', dueAt: '2026-09-15', status: 'pending' },
  ].map(payment => ({ ...payment, projectId: 'qa-project', customerId: 'qa-customer', type: 'milestone', notes: '隔离测试' })),
  expenses: [
    { id: 'expense-old', name: '合成往年费用', amount: 10, paidAt: '2025-12-16' },
    { id: 'expense-august', name: '合成八月费用', amount: 20, paidAt: '2026-08-21' },
    { id: 'expense-september', name: '合成九月费用', amount: 30, paidAt: '2026-09-08' },
  ].map(expense => ({ ...expense, projectId: 'qa-project', category: 'software', notes: '隔离测试' })),
  settlementIssues: [{ id: 'issue-refund', projectId: 'qa-project', type: 'partial_refund', title: '合成退款', refundAmount: 25, receivableImpact: 0, occurredAt: '2026-08-26' }],
  tasks: [], attachments: [], changeOrders: [], logs: [], completedOrderCount: 0,
  settings: { xianyuStartedAt: '2025-12-01', monthlyIncomeGoal: 1000, profileName: '合成验收账户', notificationsEnabled: false },
};

// Append after the existing safety prelude; the original prelude still blocks writes/network.
export const recordsHistoryPrelude = `(() => {
  if (!window.__qa) throw Error('History fixture requires the safety prelude');
  const mockFetch = window.fetch;
  const ledger = ${JSON.stringify(recordsHistorySnapshot)};
  window.fetch = async (url, opts) => {
    if (String(url) === '/api/ledger/snapshot' && (!opts?.method || opts.method === 'GET')) {
      window.__qa.calls.push({url: String(url), method: 'GET', fixture: 'records-history'});
      return new Response(JSON.stringify({revision: 1, snapshot: ledger}), {status: 200, headers: {'Content-Type': 'application/json'}});
    }
    return mockFetch(url, opts);
  };
})();`;
