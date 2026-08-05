export type ProjectStatus =
  | "pending"
  | "in_progress"
  | "delivered"
  | "completed"
  | "overdue";

export type PaymentType = "deposit" | "milestone" | "final" | "full";

export type PaymentStatus = "pending" | "confirmed" | "refunded";

export type TaskStatus = "todo" | "in_progress" | "done";

export type CustomerFollowUpStatus =
  | "new"
  | "contacted"
  | "proposal"
  | "won"
  | "inactive";

export type CustomerLevel = "A" | "B" | "C";

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
  type?: string;
  estimatedHours?: number;
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
  dueAt: string;
  notes?: string;
}

export interface Customer {
  id: string;
  name: string;
  source: "xianyu" | "wechat" | "referral" | "other";
  phone: string;
  followUpStatus: CustomerFollowUpStatus;
  lastContactAt: string;
  level: CustomerLevel;
  tags?: string[];
}

export interface ProjectTask {
  id: string;
  projectId: string;
  title: string;
  status: TaskStatus;
  startDate: string;
  dueDate: string;
  estimatedHours: number;
  actualHours: number;
}

export interface ProjectLog {
  id: string;
  projectId: string;
  createdAt: string;
  content: string;
  hours: number;
  category: "development" | "communication" | "delivery";
}

export interface ProjectAttachment {
  id: string;
  projectId: string;
  name: string;
  size: string;
  type: "document" | "design" | "archive";
  uploadedAt: string;
  dataUrl?: string;
}

export interface Expense {
  id: string;
  projectId?: string;
  name: string;
  category: "software" | "outsourcing" | "server" | "office" | "refund" | "other";
  amount: number;
  paidAt: string;
  notes?: string;
}

export interface OperationSettings {
  xianyuStartedAt: string;
  monthlyIncomeGoal: number;
  defaultDurationDays?: number;
  defaultPaymentType?: PaymentType;
  reminderDays?: number;
  decimalPlaces?: number;
  notificationsEnabled?: boolean;
  paymentRemindersEnabled?: boolean;
  goalRemindersEnabled?: boolean;
  autoBackupEnabled?: boolean;
  backupTime?: string;
  themeColor?: string;
  colorMode?: "light" | "dark";
}

export interface LedgerSnapshot {
  projects: Project[];
  payments: Payment[];
  expenses: Expense[];
  customers: Customer[];
  tasks: ProjectTask[];
  logs: ProjectLog[];
  attachments: ProjectAttachment[];
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
  contractTotal?: number;
  status?: "pending" | "confirmed";
  dueAt?: string;
  notes?: string;
}
