import {useEffect,useRef,useState} from 'react';
import {HandWaving,ArrowRight,Bell,List,UserCircle,CaretDown,GearSix,X,CheckCircle,ChatCircleDots,ShoppingBag,MagnifyingGlass,RocketLaunch,TrendUp,ChartBar,ClipboardText,Lightbulb,WifiSlash,type Icon as PhosphorIcon} from '@phosphor-icons/react';
import type {LedgerSnapshot} from '../../types';
import type {SettingsSectionName} from '../../pages/OtherPages';
import {GlobalSearch} from './GlobalSearch';
type HeaderReminderKind = "customer" | "collection" | "market" | "launch" | "traffic" | "experiment" | "strategy" | "connection";

export interface HeaderReminder {
  id: string;
  kind: HeaderReminderKind;
  label: string;
  title: string;
  description: string;
  meta: string;
  actionLabel: string;
  targetPage: "客户消息" | "商品经营" | "设置中心";
  targetHash: string;
  settingsSection?: SettingsSectionName;
}

const headerReminderIcons: Record<HeaderReminderKind, PhosphorIcon> = {
  customer: ChatCircleDots,
  collection: ShoppingBag,
  market: MagnifyingGlass,
  launch: RocketLaunch,
  traffic: TrendUp,
  experiment: ClipboardText,
  strategy: Lightbulb,
  connection: WifiSlash,
};

export function TopBar({
  snapshot,
  meta,
  search,
  onSearch,
  onMenu,
  activePage,
  reminders,
  onReminderAction,
  onViewAllReminders,
  onRefreshReminders,
  onOpenSettings,
  profileName,
  profilePlan,
}: {
  snapshot: LedgerSnapshot;
  meta: {title:string;subtitle:string;placeholder:string};
  search: string;
  onSearch: (value: string) => void;
  onMenu: () => void;
  activePage: string;
  reminders: HeaderReminder[];
  onReminderAction: (reminder: HeaderReminder) => void;
  onViewAllReminders: () => void;
  onRefreshReminders: () => void;
  onOpenSettings: (section: SettingsSectionName) => void;
  profileName: string;
  profilePlan: string;
}) {
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const notificationAnchorRef = useRef<HTMLDivElement>(null);
  const notificationButtonRef = useRef<HTMLButtonElement>(null);
  const notificationPanelRef = useRef<HTMLElement>(null);
  const profileAnchorRef = useRef<HTMLDivElement>(null);
  const profileButtonRef = useRef<HTMLButtonElement>(null);
  const visibleReminders = reminders.slice(0, 4);

  useEffect(() => {
    if (!notificationsOpen && !profileOpen) return;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (notificationsOpen && !notificationAnchorRef.current?.contains(target)) setNotificationsOpen(false);
      if (profileOpen && !profileAnchorRef.current?.contains(target)) setProfileOpen(false);
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [notificationsOpen, profileOpen]);

  useEffect(() => {
    if (!notificationsOpen) return;
    const panel = notificationPanelRef.current;
    const frame = window.requestAnimationFrame(() => panel?.focus());
    const mobile = window.matchMedia("(max-width: 560px)").matches;
    const previousOverflow = document.body.style.overflow;
    if (mobile) document.body.style.overflow = "hidden";

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setNotificationsOpen(false);
        window.requestAnimationFrame(() => notificationButtonRef.current?.focus());
        return;
      }
      if (event.key !== "Tab" || !panel) return;
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(
        "button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
      )).filter((element) => element.getClientRects().length > 0);
      if (!focusable.length) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (document.activeElement === panel) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (!panel.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [notificationsOpen]);

  useEffect(() => {
    if (!profileOpen) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setProfileOpen(false);
      window.requestAnimationFrame(() => profileButtonRef.current?.focus());
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [profileOpen]);

  const closeNotifications = () => setNotificationsOpen(false);

  return (
    <><header className={`top-header compact-topbar ${activePage === "AI经营助手" ? "top-header-partner" : ""}`}>
      <button className={`menu-button ${activePage === "AI经营助手" ? "partner-brand-menu" : ""}`} aria-label="打开导航" onClick={onMenu}>
        {activePage === "AI经营助手" ? <><img src="/assets/xunying/orbit-mark.png" alt="" aria-hidden="true" /><span>循营</span></> : <List size={24} />}
      </button>
      <div className="greeting">
        <h1>{activePage === "首页概览" ? <>你好，{profileName}！<span aria-hidden="true"><HandWaving size={25} weight="duotone"/></span></> : meta.title}{activePage === "数据统计" && <em className="page-context-tag">商品增长复盘</em>}{activePage === "经营分析中心" && <em className="page-context-tag">证据链优先</em>}</h1>
        <p>{meta.subtitle}</p>
      </div>
      <img className="header-planet" src={activePage === "AI经营助手" ? "/assets/xunying/xiaoce-avatar.png" : "/assets/chrome-v2/header-planet.png"} alt="" aria-hidden="true" draggable={false}/>
      <GlobalSearch snapshot={snapshot}/>
      <div className="header-actions">
        <div className="popover-anchor" ref={notificationAnchorRef}>
          <button
            ref={notificationButtonRef}
            className="round-button"
            aria-label={`查看智能提醒，${reminders.length} 项待处理`}
            aria-expanded={notificationsOpen}
            aria-controls="smart-reminder-panel"
            aria-haspopup="dialog"
            onClick={() => {
              setProfileOpen(false);
              if (!notificationsOpen) onRefreshReminders();
              setNotificationsOpen((value) => !value);
            }}
          >
            <Bell size={23} />
            {reminders.length > 0 && <b>{reminders.length}</b>}
          </button>
          {notificationsOpen && (
            <>
              <button className="notification-backdrop" aria-label="关闭智能提醒" onClick={closeNotifications} tabIndex={-1} />
              <section
                ref={notificationPanelRef}
                id="smart-reminder-panel"
                className="header-popover notification-popover"
                role="dialog"
                aria-modal="true"
                aria-labelledby="smart-reminder-title"
                tabIndex={-1}
              >
                <span className="notification-drawer-handle" aria-hidden="true" />
                <header className="notification-heading">
                  <span className="notification-heading-icon"><Bell size={21} weight="duotone" /></span>
                  <span className="notification-heading-copy">
                    <strong id="smart-reminder-title">智能提醒</strong>
                    <small>客户消息、商品经营与连接异常</small>
                  </span>
                  <span className="notification-status">{reminders.length > 0 ? `${reminders.length} 项待处理` : "当前已清空"}</span>
                  <button className="notification-close" aria-label="关闭智能提醒" onClick={closeNotifications}><X size={19} /></button>
                </header>

                {visibleReminders.length > 0 ? (
                  <ul className="notification-list" aria-label="待处理客户、商品经营与连接异常事项">
                    {visibleReminders.map((reminder) => {
                      const ReminderIcon = headerReminderIcons[reminder.kind];
                      return (
                        <li key={reminder.id}>
                          <button
                            className={`notification-item is-${reminder.kind}`}
                            onClick={() => {
                              closeNotifications();
                              onReminderAction(reminder);
                            }}
                          >
                            <span className="notification-item-icon"><ReminderIcon size={21} weight="duotone" /></span>
                            <span className="notification-item-copy">
                              <small>{reminder.label}</small>
                              <strong>{reminder.title}</strong>
                              <span>{reminder.description}</span>
                            </span>
                            <span className="notification-item-side">
                              <time>{reminder.meta}</time>
                              <span>{reminder.actionLabel}<ArrowRight size={14} /></span>
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <div className="notification-empty">
                    <span><CheckCircle size={25} weight="duotone" /></span>
                    <strong>当前事项已处理完成</strong>
                    <p>新的客户消息、商品经营事项或明确连接异常会显示在这里。</p>
                  </div>
                )}

                <footer className="notification-footer">
                  <button onClick={() => { closeNotifications(); onViewAllReminders(); }}>
                    查看全部提醒 <ArrowRight size={15} />
                  </button>
                  <button onClick={() => { closeNotifications(); onOpenSettings("提醒通知"); }}>
                    <GearSix size={16} />提醒设置
                  </button>
                </footer>
              </section>
            </>
          )}
        </div>
        <div className="popover-anchor" ref={profileAnchorRef}>
          <button
            ref={profileButtonRef}
            className="profile-button"
            aria-label="打开个人与账户设置"
            aria-expanded={profileOpen}
            onClick={() => {
              setNotificationsOpen(false);
              setProfileOpen((value) => !value);
            }}
          >
            <span className="avatar"><UserCircle size={33} weight="duotone" /></span>
            <span><strong>{profileName}</strong><small>{profilePlan}</small></span>
            <CaretDown size={16} />
          </button>
          {profileOpen && (
            <div className="header-popover profile-popover">
              <button onClick={() => { onOpenSettings("个人资料"); setProfileOpen(false); }}>个人资料</button>
              <button onClick={() => { onOpenSettings("账号设置"); setProfileOpen(false); }}>账号设置</button>
            </div>
          )}
        </div>
      </div>
    </header>

    </>
  );
}

