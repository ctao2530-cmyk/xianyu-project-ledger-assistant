export type ProjectStatus =
  | "pending"
  | "in_progress"
  | "delivered"
  | "completed"
  | "overdue";

export type PaymentType = "deposit" | "milestone" | "final" | "full";

export type PaymentStatus = "pending" | "confirmed" | "refunded";

export interface Project {
  id: string;
  name: string;
  customerId: string;
  totalAmount: number;
  startDate: string;
  dueDate: string;
  progress: number;
  status: ProjectStatus;
  notes?: string;
  accent: "blue" | "green" | "purple" | "orange";
}

export interface Payment {
  id: string;
  projectId: string;
  customerId: string;
  amount: number;
  type: PaymentType;
  status: PaymentStatus;
  paidAt: string;
  notes?: string;
}

export interface Customer {
  id: string;
  name: string;
  source: "xianyu" | "wechat" | "referral" | "other";
}

export interface OperationSettings {
  xianyuStartedAt: string;
  monthlyIncomeGoal: number;
}

export interface LedgerSnapshot {
  projects: Project[];
  payments: Payment[];
  customers: Customer[];
  settings: OperationSettings;
  completedOrderCount: number;
}

export interface QuickAccountingFormValue {
  projectName: string;
  customerName: string;
  amount: number;
  type: PaymentType;
  paidAt: string;
  durationDays: number;
  notes?: string;
}

