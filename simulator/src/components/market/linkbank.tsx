import { Component, useEffect, useState, type ReactNode } from "react";
import { fill, t as copy } from "@/lib/i18n";
import { Bar, BarChart, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Home,
  ImageIcon,
  LayoutList,
  Pencil,
  Radio,
  RotateCcw,
  ShoppingBag,
  Star,
  Trash2,
  Check,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import {
  BANNER_FEE,
  FEE_PERCENT,
  MIN_PAYOUT,
  PEOPLE,
  escrowTotal,
  screenTitle,
  useMarket,
  channelPulse,
  type Banner,
  type Channel,
  type MediaKind,
  type Role,
  type Screen,
} from "@/lib/market/store";
import {
  MODE_LABEL,
  ST_E,
  ST_M,
  ST_O,
  cpm,
  faNum,
  formatJalali,
  isoDate,
  jalaliParts,
  money,
  shiftDays,
} from "@/lib/market/format";

const ROLES: { id: Role; label: string }[] = [
  { id: "manager", label: copy().role.managerShort },
  { id: "customer", label: copy().role.customer },
  { id: "operator", label: copy().role.operator },
];

function horizon() {
  return Array.from({ length: 14 }, (_, i) => {
    const d = shiftDays(i);
    return { date: isoDate(d), jalali: formatJalali(d), when: d };
  });
}

function tail(iban: string) {
  return iban.slice(-4);
}

function adminPhrase(ch: Channel) {
  if (ch.publishMode === "manual") return "خودتان منتشر می‌کنید";
  const linkyar = ch.publishMode === "linkyar";
  const who = linkyar ? "لینک‌یار" : "لینک‌ساز";
  const checked = linkyar ? ch.linkyarChecked : ch.botChecked;
  if (checked === false) return `${who} هنوز بررسی نشده`;
  const isAdmin = linkyar ? ch.linkyarIsAdmin : ch.botIsAdmin;
  return isAdmin ? `${who} ادمین است` : `${who} ادمین نیست`;
}

export function LinkBank({ embedded = false }: { embedded?: boolean }) {
  useEffect(() => {
    const done = useMarket.persist.rehydrate();
    void Promise.resolve(done).then(() => {
      useMarket.getState().refreshChannelStats();
    });
  }, []);
  return <Shell embedded={embedded} />;
}

function Shell({ embedded = false }: { embedded?: boolean }) {
  const role = useMarket((s) => s.role);
  const stack = useMarket((s) => s.stack);
  const setRole = useMarket((s) => s.setRole);
  const go = useMarket((s) => s.go);
  const back = useMarket((s) => s.back);
  const reset = useMarket((s) => s.reset);
  const screen = stack[stack.length - 1] ?? { name: "home" as const };
  const [note, setNote] = useState<string | null>(null);

  function toast(message: string) {
    setNote(message);
    window.setTimeout(() => setNote((cur) => (cur === message ? null : cur)), 2400);
  }

  const tabs = tabsFor(role);
  const active = tabId(role, screen.name);

  return (
    <div className={embedded ? "flex h-full min-h-0 flex-col bg-bg text-fg" : "min-h-dvh bg-header text-fg md:py-6"}>
      <div
        className={
          embedded
            ? "relative flex h-full min-h-0 w-full flex-col overflow-hidden bg-bg"
            : "relative mx-auto flex min-h-dvh w-full max-w-md flex-col bg-bg md:overflow-hidden md:rounded-2xl md:border md:border-line"
        }
      >
        <header className="sticky top-0 z-10 shrink-0 border-b border-line bg-header">
          <div className="flex items-center gap-1 px-1">
            {stack.length > 1 ? (
              <button
                type="button"
                aria-label={copy().a11y.back}
                onClick={back}
                className="grid size-11 place-items-center rounded-xl text-fg"
              >
                <ChevronRight className="size-5" />
              </button>
            ) : (
              <span className="size-11" />
            )}
            <div className="flex-1 py-2 text-center">
              <h1 className="text-sm font-bold">{screenTitle(role, screen.name)}</h1>
              <p className="text-[11px] text-muted">{PEOPLE[role].sub}</p>
            </div>
            {embedded ? (
              <button
                type="button"
                aria-label={copy().a11y.reset}
                onClick={() => {
                  reset();
                  toast(copy().common.resetDone);
                }}
                className="grid size-11 place-items-center text-muted"
              >
                <RotateCcw className="size-4" />
              </button>
            ) : (
              <span className="size-11" />
            )}
          </div>
          {embedded ? null : (
          <div className="flex items-center gap-1 px-3 pb-2">
            {ROLES.map((r) => (
              <button
                key={r.id}
                type="button"
                onClick={() => setRole(r.id)}
                className={`min-h-11 rounded-full px-3 text-xs font-semibold ${
                  role === r.id ? "bg-link text-on" : "text-muted"
                }`}
              >
                {r.label}
              </button>
            ))}
            <button
              type="button"
              onClick={() => {
                reset();
                toast(copy().common.resetDone);
              }}
              className="ms-auto text-xs text-muted"
            >
              {copy().a11y.reset}
            </button>
          </div>
          )}
        </header>

        <main className={embedded ? "min-h-0 flex-1 overflow-y-auto px-3 pt-2 pb-3" : "flex-1 px-3 pt-2 pb-24"}>
          <ScreenGuard screen={screen} toast={toast} />
        </main>

        <nav
          className={
            embedded
              ? `grid shrink-0 border-t border-line bg-header ${tabs.length === 5 ? "grid-cols-5" : "grid-cols-4"}`
              : `fixed inset-x-0 bottom-0 z-10 mx-auto grid max-w-md border-t border-line bg-header md:absolute ${
                  tabs.length === 5 ? "grid-cols-5" : "grid-cols-4"
                }`
          }
        >
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const on = active === tab.id;
            const showBadge = role === "manager" && tab.id === "orders" && pendingOrders > 0;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => go(tab.screen)}
                className={`relative flex min-h-14 flex-col items-center justify-center gap-0.5 text-xs ${
                  on ? "font-bold text-link" : "text-muted"
                }`}
              >
                <span className="relative">
                  <Icon className="size-4" />
                  {showBadge ? (
                    <span className="absolute -end-2 -top-1 grid min-w-4 place-items-center rounded-full bg-danger px-1 text-[9px] font-bold text-white">
                      {faNum(pendingOrders > 9 ? 9 : pendingOrders)}
                      {pendingOrders > 9 ? "+" : ""}
                    </span>
                  ) : null}
                </span>
                {tab.label}
              </button>
            );
          })}
        </nav>

        {note ? (
          <div
            className={
              embedded
                ? "pointer-events-none absolute inset-x-3 bottom-20 z-20 rounded-2xl bg-fg px-3 py-3 text-center text-sm text-bg"
                : "fixed inset-x-4 bottom-20 z-20 mx-auto max-w-md rounded-2xl bg-fg px-3 py-3 text-center text-sm text-bg md:absolute"
            }
          >
            {note}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function tabsFor(role: Role): { id: string; label: string; screen: Screen; icon: LucideIcon }[] {
  if (role === "operator") {
    return [
      { id: "home", label: copy().screen.home, screen: { name: "home" }, icon: Home },
      { id: "opb", label: copy().screen.banners, screen: { name: "opb" }, icon: ImageIcon },
      { id: "opp", label: copy().screen.opp, screen: { name: "opp" }, icon: Wallet },
      { id: "orders", label: copy().screen.orders, screen: { name: "orders" }, icon: ClipboardList },
    ];
  }
  if (role === "customer") {
    return [
      { id: "home", label: copy().screen.home, screen: { name: "home" }, icon: Home },
      { id: "banners", label: copy().screen.banners, screen: { name: "banners" }, icon: ImageIcon },
      { id: "catalog", label: copy().tab.list, screen: { name: "catalog" }, icon: LayoutList },
      { id: "cart", label: copy().tab.cart, screen: { name: "cart" }, icon: ShoppingBag },
      { id: "finance", label: copy().screen.finance, screen: { name: "wallet" }, icon: Wallet },
    ];
  }
  return [
    { id: "home", label: copy().screen.home, screen: { name: "home" }, icon: Home },
    { id: "channels", label: copy().screen.channels, screen: { name: "channels" }, icon: Radio },
    { id: "orders", label: copy().screen.orders, screen: { name: "orders" }, icon: ClipboardList },
    { id: "calendar", label: copy().screen.calendar, screen: { name: "calendar" }, icon: CalendarDays },
    { id: "finance", label: copy().screen.finance, screen: { name: "finance" }, icon: Wallet },
  ];
}

function tabId(role: Role, name: Screen["name"]): string {
  if (name === "channel" || name === "tariffs") return "channels";
  if (name === "days") return role === "customer" ? "catalog" : "calendar";
  if (name === "wallet" || name === "finance") return "finance";
  if (name === "banner" || name === "bannerNew" || name === "bannerForward") return "banners";
  if (name === "mine" || name === "linkyar") return "home";
  return name;
}

class ScreenGuard extends Component<
  { screen: Screen; toast: (m: string) => void },
  { error: string | null }
> {
  state = { error: null as string | null };

  static getDerivedStateFromError(error: unknown) {
    return { error: error instanceof Error ? error.message : copy().common.unknownError };
  }

  componentDidUpdate(prev: { screen: Screen }) {
    if (prev.screen !== this.props.screen && this.state.error) this.setState({ error: null });
  }

  render() {
    if (this.state.error) {
      return (
        <div className="rounded-2xl border border-danger/40 bg-surface p-4 text-sm">
          <b>{copy().common.sectionFailed}</b>
          <p className="mt-1 text-xs text-muted">{this.state.error}</p>
          <button
            type="button"
            className="mt-3 min-h-11 w-full rounded-xl bg-link px-3 text-sm font-semibold text-on"
            onClick={() => {
              useMarket.getState().reset();
              this.setState({ error: null });
            }}
          >
            {copy().common.retry}
          </button>
        </div>
      );
    }
    return <ScreenBody screen={this.props.screen} toast={this.props.toast} />;
  }
}

function ScreenBody({ screen, toast }: { screen: Screen; toast: (m: string) => void }) {
  const role = useMarket((s) => s.role);
  if (role === "customer") return <Customer screen={screen} toast={toast} />;
  if (role === "operator") return <Operator screen={screen} toast={toast} />;
  return <Manager screen={screen} toast={toast} />;
}

function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`mb-2 overflow-hidden rounded-2xl bg-surface px-3.5 py-3 text-start ${className}`}>{children}</div>;
}

function Btn({
  children,
  onClick,
  tone = "solid",
  disabled,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  tone?: "solid" | "ghost" | "ok" | "danger";
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  const tones = {
    solid: "bg-link text-on",
    ghost: "border border-line bg-transparent text-fg",
    ok: "bg-ok/15 text-ok",
    danger: "bg-danger/15 text-danger",
  };
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className={`min-h-11 w-full rounded-xl px-3.5 text-sm font-semibold disabled:opacity-40 ${tones[tone]}`}
    >
      {children}
    </button>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="mb-2.5 grid gap-1.5 text-xs text-muted">
      {label}
      {children}
    </label>
  );
}

const control =
  "min-h-11 w-full rounded-xl border border-line bg-bg px-3 text-sm text-fg outline-none focus:border-link";

function Guide({
  title,
  steps,
  onDismiss,
}: {
  title: string;
  steps: string[];
  onDismiss?: () => void;
}) {
  return (
    <section className="mb-3">
      <h2 className="mb-1 px-1 text-[11px] text-muted">{title}</h2>
      <ol className="overflow-hidden rounded-2xl bg-surface">
        {steps.map((step, i) => (
          <li key={i} className="flex gap-2 border-b border-line px-3 py-2.5 last:border-b-0">
            <span className="grid size-5 shrink-0 place-items-center rounded-full bg-link/15 text-[11px] font-bold text-link">
              {faNum(i + 1)}
            </span>
            <span className="text-xs leading-relaxed">{step}</span>
          </li>
        ))}
      </ol>
      {onDismiss ? (
        <button type="button" onClick={onDismiss} className="mt-2 w-full min-h-9 rounded-full bg-surface text-xs font-semibold text-link">
          {copy().manager.gotIt}
        </button>
      ) : null}
    </section>
  );
}

function MenuList({ children }: { children: ReactNode }) {
  return <ul className="overflow-hidden rounded-2xl bg-surface">{children}</ul>;
}

function MenuRow({
  title,
  hint,
  onClick,
}: {
  title: string;
  hint: string;
  onClick: () => void;
}) {
  return (
    <li className="border-b border-line last:border-b-0">
      <button type="button" onClick={onClick} className="flex w-full items-center gap-2 px-3 py-3 text-start">
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold">{title}</span>
          <span className="block text-[11px] leading-relaxed text-muted">{hint}</span>
        </span>
        <ChevronLeft className="size-4 shrink-0 text-muted" />
      </button>
    </li>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="px-3 py-8 text-center text-sm leading-relaxed text-muted">{children}</div>;
}

function Badge({
  children,
  tone = "muted",
}: {
  children: ReactNode;
  tone?: "muted" | "ok" | "warn" | "danger";
}) {
  const tones = {
    muted: "bg-line/70 text-muted",
    ok: "bg-ok/15 text-ok",
    warn: "bg-link/15 text-link",
    danger: "bg-danger/15 text-danger",
  };
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs ${tones[tone]}`}>{children}</span>
  );
}

function run(toast: (m: string) => void, ok: string, err: string | null) {
  toast(err ?? ok);
}

function Manager({ screen, toast }: { screen: Screen; toast: (m: string) => void }) {
  const s = useMarket();
  const [openItem, setOpenItem] = useState<number | null>(null);
  const pending = s.items.filter((i) => i.managerStatus === "pending").length;

  if (screen.name === "home") {
    return (
      <>
        <button
          type="button"
          onClick={() => s.go({ name: "finance" })}
          className="mb-3 flex w-full items-center gap-2 rounded-2xl bg-surface px-3 py-3 text-start"
        >
          <span className="min-w-0 flex-1">
            <span className="block text-[11px] text-muted">{copy().manager.balanceLabel}</span>
            <b className="text-base">{money(s.managerBalance)}</b>
          </span>
          <span className="text-end text-[11px] text-muted">
            {pending ? fill(copy().tpl.pendingShort, { n: faNum(pending) }) : copy().tpl.noPending}
          </span>
          <ChevronLeft className="size-4 shrink-0 text-muted" />
        </button>
        {!(s.onboarded || {}).manager ? (
          <Guide
            title={copy().manager.guideTitle}
            steps={[
              copy().manager.guide[0],
              copy().manager.guide[1],
              copy().manager.guide[2],
              copy().manager.guide[3],
              copy().manager.guide[4],
              fill(copy().tpl.managerHomeFee, { fee: faNum(FEE_PERCENT), min: money(MIN_PAYOUT) }),
            ]}
            onDismiss={() => s.markOnboarded("manager")}
          />
        ) : null}
        {pending > 0 ? (
          <div className="mb-3">
            <Btn onClick={() => s.go({ name: "orders" })}>{fill(copy().tpl.pendingCta, { n: faNum(pending) })}</Btn>
          </div>
        ) : null}
        <h2 className="mb-1 px-1 text-[11px] text-muted">{copy().manager.nextTitle}</h2>
        <MenuList>
          <MenuRow
            title={copy().screen.orders}
            hint={copy().manager.ordersHint}
            onClick={() => s.go({ name: "orders" })}
          />
          <MenuRow
            title={copy().screen.channels}
            hint={copy().manager.channelsHint}
            onClick={() => s.go({ name: "channels" })}
          />
          <MenuRow
            title={copy().screen.tariffs}
            hint={copy().manager.tariffsHint}
            onClick={() => s.go({ name: "tariffs" })}
          />
          <MenuRow
            title={copy().manager.calendarTitle}
            hint={copy().manager.calendarHint}
            onClick={() => s.go({ name: "calendar" })}
          />
          <MenuRow
            title={copy().manager.financeTitle}
            hint={fill(copy().tpl.financeHint, { fee: faNum(FEE_PERCENT) })}
            onClick={() => s.go({ name: "finance" })}
          />
        </MenuList>
      </>
    );
  }

  if (screen.name === "channels") {
    if (!s.channels.length && !s.groups.length) {
      return (
        <>
          <Guide
            title={copy().manager.emptyChannelGuide}
            steps={[
              copy().manager.emptyChannelSteps[0],
              copy().manager.emptyChannelSteps[1],
              copy().manager.emptyChannelSteps[2],
              copy().manager.emptyChannelSteps[3],
            ]}
          />
          <Empty>{copy().manager.noChannel}</Empty>
        </>
      );
    }
    return (
      <>
        <p className="mb-2 px-1 text-xs leading-relaxed text-muted">
          {copy().manager.channelLead}
        </p>
        <GroupDesk toast={toast} />
        <h2 className="mb-1 px-1 text-[11px] text-muted">{copy().manager.yourChannels}</h2>
        <ul className="overflow-hidden rounded-2xl bg-surface">
          {s.channels.map((ch) => (
            <li key={ch.id} className="border-b border-line last:border-b-0">
              <button
                type="button"
                onClick={() => s.push({ name: "channel", id: ch.id })}
                className="flex w-full items-center gap-2 px-3 py-3 text-start"
              >
                <span className="grid size-10 shrink-0 place-items-center rounded-full bg-header text-sm font-bold text-link">
                  {ch.name.slice(0, 1)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">{ch.name}</span>
                  <span className="block truncate text-[11px] text-muted">
                    {fill(copy().common.channelMeta, {
                      mode: MODE_LABEL[ch.publishMode],
                      admin: adminPhrase(ch),
                    })}
                  </span>
                  <span className="block truncate text-[11px] text-muted">
                    {fill(copy().stats.membersViews, { members: faNum(ch.members), views: faNum(ch.avgViews) })}
                  </span>
                </span>
                <ChevronLeft className="size-4 shrink-0 text-muted" />
              </button>
            </li>
          ))}
        </ul>
      </>
    );
  }

  if (screen.name === "channel") {
    const ch = s.channels.find((c) => c.id === screen.id);
    if (!ch) return <Empty>{copy().error.channelMissing}</Empty>;
    return <ChannelEditor key={screen.id} channelId={screen.id} toast={toast} />;
  }

  if (screen.name === "tariffs") return <TariffDesk toast={toast} />;

  if (screen.name === "orders") {
    if (!s.items.length) return <Empty>{copy().manager.ordersEmpty}</Empty>;
    return (
      <>
        <p className="mb-2 px-1 text-xs leading-relaxed text-muted">
          {copy().manager.ordersLead}
        </p>
        <ul className="overflow-hidden rounded-2xl bg-surface">
          {s.items.map((o) => {
            const t = s.tariffById(o.tariffId);
            const open = openItem === o.id;
            const tone =
              o.managerStatus === "approved" ? "text-ok" : o.managerStatus === "rejected" || o.managerStatus === "customer_declined" ? "text-danger" : "text-link";
            return (
              <li key={o.id} className="border-b border-line last:border-b-0">
                <button
                  type="button"
                  className="flex w-full items-center gap-2 px-3 py-3 text-start"
                  onClick={() => setOpenItem(open ? null : o.id)}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{s.ownerName(o.tariffId)}</span>
                    <span className="block truncate text-[11px] text-muted">
                      {t?.name} · {formatJalali(shiftFromIso(o.date))}
                    </span>
                  </span>
                  <span className="shrink-0 text-end">
                    <span className="block text-xs font-semibold">{money(o.price)}</span>
                    <span className={`block text-[11px] ${tone}`}>{ST_M[o.managerStatus]}</span>
                  </span>
                </button>
                {open ? (
                  <div className="px-3 pb-3">
                    <p className="text-[11px] text-muted">{fill(copy().common.execLine, { status: ST_E[o.execution] })}</p>
                    {o.publishedLink ? (
                      <a className="mt-1 block text-xs text-link" href={o.publishedLink} target="_blank" rel="noreferrer">
                        {copy().common.link}
                      </a>
                    ) : null}
                    {o.managerStatus === "pending" || o.managerStatus === "edited" ? (
                      <div className="mt-2">
                        <p className="mb-1 text-[11px] text-muted">{copy().manager.otherDay}</p>
                        <div className="flex gap-1 overflow-x-auto pb-1">
                          {horizon()
                            .filter((d) => d.date !== o.date && !s.isBusy(o.tariffId, d.date))
                            .slice(0, 6)
                            .map((d) => (
                              <button
                                key={d.date}
                                type="button"
                                className="min-h-11 shrink-0 rounded-xl border border-line px-3 text-xs"
                                onClick={() => run(toast, copy().toast.timeSent, s.suggestTime(o.id, d.date))}
                              >
                                {jalaliParts(d.when).day}
                              </button>
                            ))}
                        </div>
                      </div>
                    ) : null}
                    {o.managerStatus === "pending" ? (
                      <div className="mt-2 grid grid-cols-2 gap-2">
                        <Btn tone="ok" onClick={() => run(toast, copy().toast.channelAccepted, s.decideItem(o.id, true))}>
                          {copy().common.accept}
                        </Btn>
                        <Btn tone="danger" onClick={() => run(toast, copy().toast.channelLeft, s.decideItem(o.id, false))}>
                          {copy().common.reject}
                        </Btn>
                      </div>
                    ) : null}
                    {o.execution === "paid" ? (
                      <div className="mt-2">
                        <Btn onClick={() => run(toast, copy().toast.publishedHold, s.publishItem(o.id))}>
                          {t?.channelId && s.channels.find((c) => c.id === t.channelId)?.publishMode === "manual"
                            ? copy().manager.selfPublished
                            : copy().manager.published}
                        </Btn>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      </>
    );
  }

  if (screen.name === "calendar") {
    if (!s.tariffs.length) {
      return (
        <>
          <Guide
            title={copy().manager.calendarTitle}
            steps={[copy().manager.calendarSteps[0], copy().manager.calendarSteps[1]]}
          />
          <Empty>{copy().manager.noTariff}</Empty>
        </>
      );
    }
    return (
      <>
        <p className="mb-2 px-1 text-xs leading-relaxed text-muted">
          {copy().manager.calendarLead}
        </p>
        <ul className="overflow-hidden rounded-2xl bg-surface">
          {s.tariffs.map((t) => (
            <li key={t.id} className="border-b border-line last:border-b-0">
              <button
                type="button"
                onClick={() => s.push({ name: "days", id: t.id })}
                className="flex w-full items-center gap-2 px-3 py-3 text-start"
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold">{t.name}</span>
                  <span className="block text-[11px] text-muted">{s.ownerName(t.id)} · {money(t.price)}</span>
                </span>
                <ChevronLeft className="size-4 shrink-0 text-muted" />
              </button>
            </li>
          ))}
        </ul>
      </>
    );
  }

  if (screen.name === "days") return <ManagerDays tariffId={screen.id} toast={toast} />;

  if (screen.name === "finance") return <WalletPanel owner="manager" toast={toast} />;

  return null;
}

function shiftFromIso(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1, 12);
}

function faPercent(n: number) {
  const body = (Math.round(Math.abs(n) * 10) / 10).toFixed(1);
  const [whole, frac] = body.split(".");
  return `${faNum(whole)}٫${faNum(frac)}٪`;
}

function faSignedPercent(n: number) {
  if (Math.abs(n) < 0.05) return faPercent(0);
  return `${n < 0 ? "−" : "+"}${faPercent(n)}`;
}

function faDec(n: number) {
  const body = (Math.round(n * 10) / 10).toFixed(1);
  const [whole, frac] = body.split(".");
  return `${faNum(whole)}٫${faNum(frac)}`;
}

function tariffChannels(
  s: {
    channels: Channel[];
    groups: { id: number; channelIds: number[] }[];
    tariffById: (id: number) => { channelId: number | null; groupId: number | null } | undefined;
  },
  tariffId: number,
): Channel[] {
  const tariff = s.tariffById(tariffId);
  if (!tariff) return [];
  if (tariff.channelId) return s.channels.filter((c) => c.id === tariff.channelId);
  const ids = s.groups.find((g) => g.id === tariff.groupId)?.channelIds ?? [];
  return s.channels.filter((c) => ids.includes(c.id));
}

function ChannelPulse({ channels }: { channels: Channel[] }) {
  const pulse = channelPulse(channels);
  const [mode, setMode] = useState<"members" | "views">("members");
  if (!channels.length || !pulse.series.length) return null;
  const data = pulse.series.map((point) => ({
    label: jalaliParts(new Date(point.at)).day,
    value: mode === "members" ? point.members : point.views,
  }));
  const cells: [string, string][] = [
    [copy().stats.members, faNum(pulse.members)],
    [copy().stats.reach, faNum(pulse.views)],
    [copy().stats.err, faPercent(pulse.err)],
    [copy().stats.daily, faNum(pulse.dailyReach)],
    [copy().stats.posts, faDec(pulse.postsPerDay)],
    [copy().stats.citation, faDec(pulse.citation)],
  ];
  return (
    <section className="mb-3 rounded-2xl bg-surface px-3 py-3">
      <p className="mb-2 text-[11px] leading-relaxed text-muted">{copy().stats.auto}</p>
      <div className="mb-2 grid grid-cols-3 gap-x-2 gap-y-2">
        {cells.map(([label, value]) => (
          <div key={label}>
            <span className="block text-[10px] text-muted">{label}</span>
            <b className="block text-xs">{value}</b>
          </div>
        ))}
      </div>
      {pulse.about ? <p className="mb-2 text-[11px] leading-relaxed text-muted">{pulse.about}</p> : null}
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-[11px] text-muted">{mode === "members" ? copy().stats.chartMembers : copy().stats.chartViews}</span>
        <b className={`text-[11px] ${pulse.growth < 0 ? "text-danger" : "text-ok"}`}>
          {copy().stats.growth} {faSignedPercent(pulse.growth)}
        </b>
      </div>
      <div className="mb-2 flex gap-1">
        {(
          [
            ["members", copy().stats.chartMembers],
            ["views", copy().stats.chartViews],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setMode(id)}
            className={`min-h-8 rounded-full px-3 text-[11px] ${mode === id ? "bg-link text-on" : "text-muted"}`}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="h-28 w-full min-w-0">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
            <XAxis dataKey="label" tick={{ fill: "var(--color-muted)", fontSize: 10 }} axisLine={false} tickLine={false} />
            <YAxis hide domain={["dataMin", "dataMax"]} />
            <Tooltip
              cursor={{ stroke: "var(--color-line)" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const value = Number(payload[0].value) || 0;
                return <div className="rounded-xl bg-header px-2 py-1 text-[11px] text-fg">{faNum(value)}</div>;
              }}
            />
            <Line type="monotone" dataKey="value" stroke="var(--color-link)" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2 text-[11px] text-muted">
        {copy().stats.lang}: {pulse.language === "fa" ? copy().stats.langFa : pulse.language || copy().stats.empty}
        {" · "}
        {copy().stats.updated}: {pulse.statsAt ? formatJalali(new Date(pulse.statsAt)) : copy().stats.empty}
      </p>
    </section>
  );
}


function GroupDesk({ toast }: { toast: (m: string) => void }) {
  const groups = useMarket((s) => s.groups);
  const channels = useMarket((s) => s.channels);
  const addGroup = useMarket((s) => s.addGroup);
  const updateGroup = useMarket((s) => s.updateGroup);
  const removeGroup = useMarket((s) => s.removeGroup);
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<number[]>([]);
  const [editingId, setEditingId] = useState<number | null>(null);

  const toggle = (id: number) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const reset = () => {
    setEditingId(null);
    setName("");
    setSelected([]);
  };

  return (
    <>
      <h2 className="mb-1 px-1 text-[11px] text-muted">{copy().manager.groups}</h2>
      <Card>
        <Field label={copy().manager.groupName}>
          <input className={control} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <p className="mb-1 text-[11px] text-muted">{copy().manager.groupChannels}</p>
        <div className="mb-2 flex flex-wrap gap-1">
          {channels.map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => toggle(c.id)}
              className={`min-h-9 rounded-full px-3 text-xs ${selected.includes(c.id) ? "bg-link text-on" : "bg-header text-muted"}`}
            >
              {c.name}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          <Btn
            onClick={() => {
              const err = editingId
                ? updateGroup(editingId, name, selected)
                : addGroup(name, selected);
              if (!err) reset();
              run(toast, copy().toast.groupSaved, err);
            }}
          >
            {editingId ? copy().manager.saveTariffEdit : copy().manager.addGroup}
          </Btn>
          {editingId ? <Btn onClick={reset}>{copy().manager.cancelTariffEdit}</Btn> : null}
        </div>
      </Card>
      {groups.length ? (
        <ul className="mb-3 overflow-hidden rounded-2xl bg-surface">
          {groups.map((g) => (
            <li key={g.id} className="flex items-center gap-2 border-b border-line px-3 py-3 last:border-b-0">
              <button
                type="button"
                className="min-w-0 flex-1 text-start"
                onClick={() => {
                  setEditingId(g.id);
                  setName(g.name);
                  setSelected([...g.channelIds]);
                }}
              >
                <span className="block text-sm font-semibold">{fill(copy().common.groupTitle, { name: g.name })}</span>
                <span className="block text-[11px] text-muted">{fill(copy().common.groupCount, { n: faNum(g.channelIds.length) })}</span>
              </button>
              <button
                type="button"
                className="min-h-9 shrink-0 rounded-full px-3 text-xs text-danger"
                onClick={() => run(toast, copy().toast.groupDeleted, removeGroup(g.id))}
              >
                {copy().manager.deleteGroup}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </>
  );
}

function ChannelEditor({ channelId, toast }: { channelId: number; toast: (m: string) => void }) {
  const channel = useMarket((s) => s.channels.find((c) => c.id === channelId));
  const setPublishMode = useMarket((s) => s.setPublishMode);
  const updateChannel = useMarket((s) => s.updateChannel);
  const removeChannel = useMarket((s) => s.removeChannel);
  const archiveChannel = useMarket((s) => s.archiveChannel);
  const back = useMarket((s) => s.back);
  const [remind, setRemind] = useState(channel?.remindHours ?? 2);
  const [editName, setEditName] = useState(channel?.name ?? "");
  if (!channel) return <Empty>{copy().error.channelMissing}</Empty>;
  const hints: Record<string, string> = {
    bot: copy().manager.modeBot,
    linkyar: copy().manager.modeLinkyar,
    manual: copy().manager.modeManual,
  };
  return (
    <>
      <div className="mb-3 rounded-2xl bg-surface px-3 py-3">
        <b className="text-sm">{channel.name}</b>
        <div className="text-xs text-muted" dir="ltr">
          {channel.link}
        </div>
      </div>
      <Card>
        <Field label={copy().manager.channelNameEdit}>
          <input className={control} value={editName} onChange={(e) => setEditName(e.target.value)} />
        </Field>
        <div className="flex flex-wrap gap-2">
          <Btn
            onClick={() => {
              const err = updateChannel(channel.id, editName);
              run(toast, copy().toast.channelRenamed, err);
            }}
          >
            {copy().manager.saveChannelName}
          </Btn>
          <Btn
            onClick={() => {
              const listed = (channel as { isListed?: boolean }).isListed !== false;
              const err = archiveChannel(channel.id, !listed ? true : false);
              run(
                toast,
                listed ? copy().toast.channelArchived : copy().toast.channelUnarchived,
                err,
              );
            }}
          >
            {(channel as { isListed?: boolean }).isListed === false
              ? copy().manager.unarchiveChannel
              : copy().manager.archiveChannel}
          </Btn>
          <Btn
            onClick={() => {
              const err = removeChannel(channel.id);
              if (!err) back();
              run(toast, copy().toast.channelDeleted, err);
            }}
          >
            {copy().manager.deleteChannel}
          </Btn>
        </div>
      </Card>
      <ChannelPulse channels={[channel]} />
      <h2 className="mb-1 px-1 text-[11px] text-muted">{copy().manager.modeTitle}</h2>
      <ul className="mb-3 overflow-hidden rounded-2xl bg-surface">
        {(["bot", "linkyar", "manual"] as const).map((mode) => {
          const on = channel.publishMode === mode;
          return (
            <li key={mode} className="border-b border-line last:border-b-0">
              <button
                type="button"
                onClick={() => {
                  run(toast, copy().toast.modeSaved, setPublishMode(channel.id, mode, mode === "manual" ? remind : undefined));
                }}
                className="flex w-full items-start gap-2 px-3 py-3 text-start"
              >
                <span
                  className={`mt-0.5 grid size-5 shrink-0 place-items-center rounded-full border ${on ? "border-link bg-link text-on" : "border-muted"}`}
                >
                  {on ? <Check className="size-3" /> : null}
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-semibold">{MODE_LABEL[mode]}</span>
                  <span className="block text-[11px] leading-relaxed text-muted">{hints[mode]}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      {channel.publishMode === "manual" ? (
        <Card>
          <Field label={copy().manager.remindLabel}>
            <select className={control} value={remind} onChange={(e) => setRemind(Number(e.target.value))}>
              {[1, 2, 4, 6, 12, 24].map((h) => (
                <option key={h} value={h}>
                  {fill(copy().common.hoursBefore, { n: faNum(h) })}
                </option>
              ))}
            </select>
          </Field>
          <Btn
            onClick={() =>
              run(toast, copy().toast.remindSaved, setPublishMode(channel.id, "manual", remind))
            }
          >
            {copy().manager.saveRemind}
          </Btn>
        </Card>
      ) : null}
    </>
  );
}

function TariffDesk({ toast }: { toast: (m: string) => void }) {
  const channels = useMarket((s) => s.channels);
  const groups = useMarket((s) => s.groups);
  const tariffs = useMarket((s) => s.tariffs);
  const ownerName = useMarket((s) => s.ownerName);
  const addTariff = useMarket((s) => s.addTariff);
  const updateTariff = useMarket((s) => s.updateTariff);
  const removeTariff = useMarket((s) => s.removeTariff);
  const toggleTariff = useMarket((s) => s.toggleTariff);
  const [ownerKind, setOwnerKind] = useState<"channel" | "group">("channel");
  const [channelId, setChannelId] = useState(channels[0]?.id ?? 0);
  const [groupId, setGroupId] = useState(groups[0]?.id ?? 0);
  const [name, setName] = useState("");
  const [hour, setHour] = useState(12);
  const [duration, setDuration] = useState("24");
  const [price, setPrice] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);

  const resetForm = () => {
    setEditingId(null);
    setName("");
    setHour(12);
    setDuration("24");
    setPrice("");
    setOwnerKind("channel");
    setChannelId(channels[0]?.id ?? 0);
    setGroupId(groups[0]?.id ?? 0);
  };

  const loadForEdit = (row: (typeof tariffs)[number]) => {
    setEditingId(row.id);
    setName(row.name);
    setHour(row.startHour ?? 12);
    setDuration(String(row.durationHours ?? 24));
    setPrice(String(row.price ?? ""));
    if (row.groupId) {
      setOwnerKind("group");
      setGroupId(row.groupId);
    } else {
      setOwnerKind("channel");
      if (row.channelId) setChannelId(row.channelId);
    }
  };

  return (
    <>
      <p className="mb-2 px-1 text-xs leading-relaxed text-muted">
        {editingId ? copy().manager.editTariff : copy().manager.priceLead}
      </p>
      <Card>
        {editingId == null ? (
          <Field label={copy().manager.ownerType}>
            <select className={control} value={ownerKind} onChange={(e) => setOwnerKind(e.target.value as "channel" | "group")}>
              <option value="channel">{copy().manager.ownerChannel}</option>
              <option value="group" disabled={!groups.length}>{copy().manager.ownerGroup}</option>
            </select>
          </Field>
        ) : null}
        {ownerKind === "channel" || editingId != null ? (
          <Field label={copy().screen.channel}>
            <select
              className={control}
              value={channelId}
              disabled={editingId != null}
              onChange={(e) => setChannelId(Number(e.target.value))}
            >
              {channels.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
        ) : (
          <Field label={copy().manager.ownerGroup}>
            <select className={control} value={groupId} onChange={(e) => setGroupId(Number(e.target.value))}>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field label={copy().manager.fieldPlan}>
          <input className={control} value={name} placeholder={copy().manager.planPh} onChange={(e) => setName(e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label={copy().manager.fieldHour}>
            <select className={control} value={hour} onChange={(e) => setHour(Number(e.target.value))}>
              {Array.from({ length: 24 }, (_, i) => (
                <option key={i} value={i}>
                  {faNum(i)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={copy().manager.fieldDuration}>
            <input className={control} inputMode="numeric" value={duration} onChange={(e) => setDuration(e.target.value)} />
          </Field>
        </div>
        <Field label={copy().manager.fieldPrice}>
          <input className={control} inputMode="numeric" value={price} onChange={(e) => setPrice(e.target.value)} />
        </Field>
        <div className="flex gap-2">
          <Btn
            onClick={() => {
              const payload = {
                name,
                startHour: hour,
                durationHours: Number(duration),
                price: Number(price.replace(/[^\d]/g, "")),
              };
              const err = editingId
                ? updateTariff({ id: editingId, ...payload })
                : addTariff(
                    ownerKind === "group"
                      ? { groupId, channelId: null, ...payload }
                      : { channelId, groupId: null, ...payload },
                  );
              if (!err) resetForm();
              run(toast, editingId ? copy().toast.tariffUpdated : copy().toast.tariffSaved, err);
            }}
          >
            {editingId ? copy().manager.saveTariffEdit : copy().manager.saveTariff}
          </Btn>
          {editingId ? (
            <Btn onClick={resetForm}>{copy().manager.cancelTariffEdit}</Btn>
          ) : null}
          {editingId ? (
            <Btn
              onClick={() => {
                const err = removeTariff(editingId);
                if (!err) resetForm();
                run(toast, copy().toast.tariffDeleted, err);
              }}
            >
              {copy().manager.deleteTariff}
            </Btn>
          ) : null}
        </div>
      </Card>
      <h2 className="mb-1 mt-1 px-1 text-[11px] text-muted">{copy().manager.tariffList}</h2>
      <p className="mb-2 px-1 text-[11px] text-muted">{copy().manager.pickToEdit}</p>
      {!tariffs.length ? <Empty>{copy().manager.noTariffs}</Empty> : null}
      {tariffs.length ? (
        <ul className="overflow-hidden rounded-2xl bg-surface">
          {tariffs.map((t) => (
            <li key={t.id} className="flex items-center gap-2 border-b border-line px-3 py-3 last:border-b-0">
              <button
                type="button"
                className={`min-w-0 flex-1 text-start ${editingId === t.id ? "opacity-100" : ""}`}
                onClick={() => loadForEdit(t)}
              >
                <span className="block truncate text-sm font-semibold">{t.name}</span>
                <span className="block truncate text-[11px] text-muted">
                  {fill(copy().common.tariffMeta, {
                    owner: ownerName(t.id),
                    hour: faNum(t.startHour),
                    hours: faNum(t.durationHours),
                    price: money(t.price),
                  })}
                </span>
              </button>
              <button
                type="button"
                className={`min-h-9 shrink-0 rounded-full px-3 text-xs font-semibold ${t.isActive ? "bg-ok/15 text-ok" : "bg-line text-muted"}`}
                onClick={() => run(toast, copy().toast.tariffToggled, toggleTariff(t.id))}
              >
                {t.isActive ? copy().common.active : copy().common.off}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </>
  );
}

type DayState = "free" | "busy" | "locked" | "cart" | "past" | "hold";

function DayGrid({
  days,
  model,
}: {
  days: { date: string; when: Date }[];
  model: (date: string) => { state: DayState; onClick?: () => void };
}) {
  const first = days[0] ? jalaliParts(days[0].when) : null;
  const last = days.length ? jalaliParts(days[days.length - 1].when) : null;
  const title =
    first && last ? (first.month === last.month ? first.month : fill(copy().calendar.span, { from: first.month, to: last.month })) : "";
  const lead = first?.col ?? 0;
  const heads = [copy().calendar.heads[0], copy().calendar.heads[1], copy().calendar.heads[2], copy().calendar.heads[3], copy().calendar.heads[4], copy().calendar.heads[5], copy().calendar.heads[6]];
  const tone: Record<DayState, string> = {
    free: "border-ok/40 bg-surface",
    busy: "border-danger/40 bg-danger/15",
    cart: "border-link bg-link/15",
    locked: "border-line bg-header",
    past: "border-line bg-header opacity-60",
    hold: "border-amber-500/40 bg-amber-500/10",
  };
  const tag: Record<DayState, string> = {
    free: "text-ok",
    busy: "text-danger",
    cart: "text-link",
    locked: "text-muted",
    past: "text-muted",
    hold: "text-amber-700",
  };
  const label: Record<DayState, string> = {
    free: copy().day.free,
    busy: copy().day.busy,
    cart: copy().day.cart,
    locked: copy().day.order,
    past: copy().day.past,
    hold: copy().day.hold,
  };
  return (
    <div className="mb-3">
      <p className="mb-2 text-center text-xs font-semibold">{title}</p>
      <div className="mb-1 grid grid-cols-7 text-center text-[11px] text-muted">
        {heads.map((h) => (
          <span key={h}>{h}</span>
        ))}
      </div>
      <div className="grid grid-cols-7 gap-1">
        {Array.from({ length: lead }, (_, i) => (
          <span key={`gap-${i}`} />
        ))}
        {days.map((d) => {
          const parts = jalaliParts(d.when);
          const cell = model(d.date);
          const body = (
            <>
              <span className="block text-sm font-bold leading-none">{parts.day}</span>
              <span className={`mt-1 block text-[10px] leading-none ${tag[cell.state]}`}>{label[cell.state]}</span>
            </>
          );
          if (!cell.onClick) {
            return (
              <div key={d.date} className={`grid min-h-14 place-items-center rounded-xl border px-0.5 py-1.5 text-center ${tone[cell.state]}`}>
                {body}
              </div>
            );
          }
          return (
            <button
              key={d.date}
              type="button"
              onClick={cell.onClick}
              className={`grid min-h-14 place-items-center rounded-xl border px-0.5 py-1.5 text-center ${tone[cell.state]}`}
            >
              {body}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function DayLegend() {
  const bits = [
    ["bg-ok", copy().day.free],
    ["bg-danger", copy().day.manual],
    ["bg-muted", copy().day.locked],
  ];
  return (
    <div className="mb-2 flex flex-wrap gap-1.5">
      {bits.map(([dot, name]) => (
        <span key={name} className="inline-flex items-center gap-1.5 rounded-full bg-surface px-2 py-1 text-[11px] text-muted">
          <span className={`size-1.5 rounded-full ${dot}`} />
          {name}
        </span>
      ))}
    </div>
  );
}

function CustomerDays({ tariffId, toast }: { tariffId: number; toast: (m: string) => void }) {
  const s = useMarket();
  const t = s.tariffById(tariffId);
  const loadCalendar = useMarket((st) => st.loadCalendar);
  const calDays = useMarket((st) => st.calendarDays(tariffId));
  useEffect(() => {
    void loadCalendar(tariffId, true);
  }, [tariffId, loadCalendar]);
  if (!t) return <Empty>{copy().catalog.missing}</Empty>;
  const byDate = new Map(calDays.map((d) => [d.date, d]));
  return (
    <DayGrid
      days={horizon()}
      model={(date) => {
        const inCart = s.cart.some((c) => c.tariffId === t.id && c.date === date);
        if (inCart) return { state: "cart" as DayState };
        const cal = byDate.get(date);
        const busy = s.isBusy(t.id, date);
        const status = cal?.status || (busy ? "full" : "free");
        const state = statusToDayState(status, false);
        return {
          state,
          onClick:
            state === "free"
              ? () => run(toast, copy().toast.addedCart, s.addToCart(t.id, date))
              : undefined,
        };
      }}
    />
  );
}

function statusToDayState(status: string, manual?: boolean): DayState {
  if (status === "free") return "free";
  if (status === "past") return "past";
  if (status === "banner-hold") return "hold";
  if (status === "full") return manual ? "busy" : "locked";
  return "locked";
}

function ManagerDays({ tariffId, toast }: { tariffId: number; toast: (m: string) => void }) {
  const tariff = useMarket((s) => s.tariffs.find((t) => t.id === tariffId));
  const ownerName = useMarket((s) => s.ownerName);
  const busyAll = useMarket((s) => s.busy);
  const toggleBusy = useMarket((s) => s.toggleBusy);
  const loadCalendar = useMarket((s) => s.loadCalendar);
  const calDays = useMarket((s) => s.calendarDays(tariffId));
  const busy = (Array.isArray(busyAll) ? busyAll : []).filter((b) => b.tariffId === tariffId);
  useEffect(() => {
    void loadCalendar(tariffId, false);
  }, [tariffId, loadCalendar]);
  if (!tariff) return <Empty>{copy().catalog.missing}</Empty>;
  const days = horizon();
  const manual = busy.filter((b) => b.manual);
  const byDate = new Map(calDays.map((d) => [d.date, d]));
  return (
    <>
      <div className="mb-3 flex items-center justify-between gap-2 rounded-2xl bg-surface px-3 py-3">
        <span className="min-w-0">
          <b className="block truncate text-sm">{tariff.name}</b>
          <span className="block truncate text-[11px] text-muted">
            {ownerName(tariffId)} · {copy().unit.hour} {faNum(tariff.startHour)} · {money(tariff.price)}
          </span>
        </span>
        <span className="shrink-0 text-xs text-link">{fill(copy().common.dayCount, { n: faNum(manual.length) })}</span>
      </div>
      <p className="mb-2 px-1 text-xs leading-relaxed text-muted">{copy().manager.dayLead}</p>
      {tariff.groupId ? (
        <p className="mb-2 px-1 text-xs leading-relaxed text-link">{copy().manager.packageCalendar}</p>
      ) : null}
      <DayLegend />
      <DayGrid
        days={days}
        model={(date) => {
          const slot = busy.find((b) => b.date === date);
          const cal = byDate.get(date);
          const status = cal?.status || (slot ? "full" : "free");
          const state = statusToDayState(status, slot?.manual);
          const canToggle = state === "free" || (state === "busy" && !!slot?.manual);
          return {
            state,
            onClick: canToggle
              ? () => {
                  const err = toggleBusy(tariffId, date);
                  void loadCalendar(tariffId, false);
                  run(toast, state === "free" ? copy().toast.dayMarked : copy().toast.dayCleared, err);
                }
              : undefined,
          };
        }}
      />
    </>
  );
}


function ledgerLabel(kind: string) {
  const map = copy().ledger as Record<string, string>;
  return map[kind] ?? kind;
}

function weekFlow(entries: { amount: number; at: number }[]) {
  return Array.from({ length: 7 }, (_, i) => {
    const when = shiftDays(i - 6);
    const key = isoDate(when);
    const net = entries
      .filter((e) => isoDate(new Date(e.at)) === key)
      .reduce((sum, e) => sum + (Number(e.amount) || 0), 0);
    return {
      day: jalaliParts(when).day,
      net,
      fill: net < 0 ? "var(--color-danger)" : net > 0 ? "var(--color-ok)" : "var(--color-line)",
    };
  });
}

function WeekChart({
  entries,
  title = copy().wallet.chart,
}: {
  entries: { amount: number; at: number }[];
  title?: string;
}) {
  const data = weekFlow(entries);
  const net = data.reduce((sum, row) => sum + row.net, 0);
  return (
    <section className="mb-3 rounded-2xl bg-surface px-3 py-3">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-[11px] text-muted">{title}</span>
        <b className={`text-xs ${net < 0 ? "text-danger" : "text-ok"}`}>
          {net > 0 ? "+" : ""}
          {money(net)}
        </b>
      </div>
      <div className="h-28 w-full min-w-0">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 0, left: 0, bottom: 0 }}>
            <XAxis dataKey="day" tick={{ fill: "var(--color-muted)", fontSize: 10 }} axisLine={false} tickLine={false} />
            <YAxis hide />
            <Tooltip
              cursor={{ fill: "var(--color-header)" }}
              content={({ active, payload }) => {
                if (!active || !payload?.length) return null;
                const value = Number(payload[0].value) || 0;
                return (
                  <div className="rounded-xl bg-header px-2 py-1 text-[11px] text-fg">
                    {value > 0 ? "+" : ""}
                    {money(value)}
                  </div>
                );
              }}
            />
            <Bar dataKey="net" radius={[6, 6, 2, 2]} maxBarSize={16} minPointSize={3}>
              {data.map((row, i) => (
                <Cell key={`${row.day}-${i}`} fill={row.fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function WalletPanel({ owner, toast }: { owner: "manager" | "customer"; toast: (m: string) => void }) {
  const balance = useMarket((s) => Number(owner === "manager" ? s.managerBalance : s.customerBalance) || 0);
  const banksAll = useMarket((s) => s.banks);
  const payoutsAll = useMarket((s) => s.payouts);
  const ledgerAll = useMarket((s) => s.ledger);
  const items = useMarket((s) => s.items);
  const banks = (Array.isArray(banksAll) ? banksAll : []).filter((b) => b?.owner === owner && b.iban);
  const payouts = (Array.isArray(payoutsAll) ? payoutsAll : []).filter((p) => p?.owner === owner && p.iban);
  const ledgerFull = (Array.isArray(ledgerAll) ? ledgerAll : []).filter((l) => l?.owner === owner);
  const ledger = ledgerFull.slice(0, 8);
  const escrow = escrowTotal(items ?? []);
  const block = useMarket((s) => s.payoutBlock(owner));
  const addBank = useMarket((s) => s.addBank);
  const requestPayout = useMarket((s) => s.requestPayout);
  const [iban, setIban] = useState("");
  const [holder, setHolder] = useState("");
  const [charge, setCharge] = useState(500_000);

  return (
    <>
      <div className="mb-3 rounded-2xl bg-link p-4 text-on">
        <span className="text-xs text-on/80">{owner === "manager" ? copy().wallet.available : copy().wallet.balance}</span>
        <b className="mt-1 block text-2xl">{money(balance)}</b>
        <span className="mt-1 block text-xs text-on/80">
          {owner === "manager" ? copy().wallet.escrow : copy().wallet.locked} {money(escrow)}
        </span>
      </div>
      <WeekChart entries={ledgerFull} />
      {owner === "manager" ? (
        <p className="mb-3 px-1 text-xs leading-relaxed text-muted">
          {fill(copy().tpl.walletFee, { fee: faNum(FEE_PERCENT), min: money(MIN_PAYOUT) })}
        </p>
      ) : (
        <p className="mb-3 px-1 text-xs leading-relaxed text-muted">
          {copy().wallet.chargeLead}
        </p>
      )}
      {block ? <p className="mb-2 px-1 text-xs text-muted">{block}</p> : null}

      <h2 className="mb-1 px-1 text-[11px] text-muted">{owner === "manager" ? copy().wallet.bank : copy().wallet.refundIban}</h2>
      <div className="mb-3 overflow-hidden rounded-2xl bg-surface">
        <div className="px-3 py-3">
          <Field label={copy().wallet.iban}>
            <input className={control} dir="ltr" placeholder={copy().wallet.ibanPh} value={iban} onChange={(e) => setIban(e.target.value)} />
          </Field>
          <Field label={copy().wallet.holder}>
            <input className={control} value={holder} onChange={(e) => setHolder(e.target.value)} />
          </Field>
          <Btn
            tone="ghost"
            onClick={() => {
              const err = addBank(owner, iban, holder);
              if (!err) {
                setIban("");
                setHolder("");
              }
              run(toast, copy().toast.ibanSaved, err);
            }}
          >
            {copy().wallet.addIban}
          </Btn>
        </div>
        {banks.map((b) => (
          <div key={b.id} className="flex items-center justify-between gap-2 border-t border-line px-3 py-3">
            <span className="min-w-0">
              <b className="block truncate text-sm">{b.holder}</b>
              <span className="block text-[11px] text-muted" dir="ltr">
                IR ··· {tail(b.iban)}
              </span>
            </span>
            <button
              type="button"
              disabled={Boolean(block)}
              onClick={() => run(toast, copy().toast.payoutAsked, requestPayout(owner, b.id))}
              className="min-h-9 shrink-0 rounded-full px-3 text-xs font-semibold text-link"
            >
              {copy().screen.opp}
            </button>
          </div>
        ))}
      </div>

      {owner === "customer" ? (
        <>
          <h2 className="mb-1 px-1 text-[11px] text-muted">{copy().wallet.chargeTitle}</h2>
          <div className="mb-2 grid grid-cols-2 gap-2">
            {[200_000, 500_000].map((amount) => (
              <button
                key={amount}
                type="button"
                onClick={() => setCharge(amount)}
                className={`min-h-11 rounded-xl border text-sm font-semibold ${
                  charge === amount ? "border-link text-link" : "border-line bg-surface text-fg"
                }`}
              >
                {money(amount)}
              </button>
            ))}
          </div>
          <div className="mb-3">
            <Btn onClick={() => chargeViaBale(charge, toast)}>{fill(copy().common.chargeAmount, { amount: money(charge) })}</Btn>
          </div>
        </>
      ) : null}

      {payouts.length ? (
        <>
          <h2 className="mb-1 px-1 text-[11px] text-muted">{copy().wallet.payouts}</h2>
          <ul className="mb-3 overflow-hidden rounded-2xl bg-surface">
            {payouts.map((p) => (
              <li key={p.id} className="flex items-center justify-between gap-2 border-b border-line px-3 py-3 last:border-b-0">
                <span className="text-sm font-semibold">{money(p.amount)}</span>
                <span className={`text-[11px] ${p.status === "pending" ? "text-link" : "text-ok"}`}>
                  {p.status === "pending" ? copy().wallet.payoutPending : copy().wallet.payoutPaid}
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <h2 className="mb-1 px-1 text-[11px] text-muted">{copy().wallet.ledger}</h2>
      {ledger.length === 0 ? (
        <Empty>{copy().wallet.ledgerEmpty}</Empty>
      ) : (
        <ul className="overflow-hidden rounded-2xl bg-surface">
          {ledger.map((l) => (
            <li key={l.id} className="flex items-center justify-between gap-3 border-b border-line px-3 py-3 last:border-b-0">
              <span className="min-w-0">
                <span className="block text-sm font-semibold">{ledgerLabel(l.kind)}</span>
                <span className="block truncate text-[11px] text-muted">{l.note}</span>
              </span>
              <b className={`shrink-0 text-sm ${l.amount < 0 ? "text-danger" : "text-ok"}`}>{money(l.amount)}</b>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function CatalogBoard() {
  const s = useMarket();
  const searchCatalog = useMarket((st) => st.searchCatalog);
  const [q, setQ] = useState("");
  const [category, setCategory] = useState(copy().common.all);
  const [sort, setSort] = useState<"price" | "cpm" | "views" | "err" | "growth">("views");
  useEffect(() => {
    const h = window.setTimeout(() => {
      void searchCatalog(q.trim());
    }, 320);
    return () => window.clearTimeout(h);
  }, [q, searchCatalog]);
  const cats = [copy().common.all, ...new Set(s.channels.map((c) => c.category || copy().common.general))];
  const list = s.tariffs
    .filter((t) => t.isActive)
    .map((t) => {
      const related = tariffChannels(s, t.id);
      const pulse = channelPulse(related);
      const ch = related.length === 1 ? related[0] : undefined;
      return { t, ch, pulse, views: pulse.views, priceCpm: cpm(t.price, pulse.views || 1) };
    })
    .filter((row) => {
      const name = `${s.ownerName(row.t.id)} ${row.t.name}`.toLowerCase();
      if (q && !name.includes(q.trim().toLowerCase())) return false;
      if (category !== copy().common.all && (row.ch?.category ?? copy().common.general) !== category) return false;
      return true;
    })
    .sort((a, b) => {
      if (sort === "price") return a.t.price - b.t.price;
      if (sort === "cpm") return a.priceCpm - b.priceCpm;
      if (sort === "err") return b.pulse.err - a.pulse.err;
      if (sort === "growth") return b.pulse.growth - a.pulse.growth;
      return b.views - a.views;
    });
  const ready = s.banners.find((b) => b.id === s.selectedBannerId && b.fromLinkbank && b.stage === "ready");

  return (
    <>
      {!ready ? (
        <button
          type="button"
          onClick={() => s.go({ name: "banners" })}
          className="mb-2 w-full rounded-2xl bg-surface px-3 py-3 text-start"
        >
          <span className="block text-sm font-semibold">{copy().catalog.needBannerTitle}</span>
          <span className="mt-0.5 block text-[11px] leading-relaxed text-muted">
            {copy().catalog.needBanner}
          </span>
        </button>
      ) : (
        <p className="mb-2 px-1 text-xs text-muted">{fill(copy().tpl.bannerOrder, { title: ready.title })}</p>
      )}
      <input
        className={control}
        placeholder={copy().catalog.search}
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />
      <div className="my-2 flex gap-1 overflow-x-auto">
        {cats.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setCategory(c)}
            className={`min-h-9 shrink-0 rounded-full px-3 text-xs ${category === c ? "bg-link text-on" : "bg-surface text-muted"}`}
          >
            {c}
          </button>
        ))}
      </div>
      <div className="mb-2 flex gap-1 overflow-x-auto">
        {(
          [
            ["views", copy().catalog.sortViews],
            ["cpm", copy().catalog.sortCpm],
            ["price", copy().catalog.sortPrice],
            ["err", copy().catalog.sortErr],
            ["growth", copy().catalog.sortGrowth],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setSort(id)}
            className={`min-h-9 rounded-full px-3 text-xs ${sort === id ? "bg-link text-on" : "text-muted"}`}
          >
            {label}
          </button>
        ))}
      </div>
      {!list.length ? <Empty>{copy().catalog.empty}</Empty> : null}
      <div className="overflow-hidden rounded-2xl bg-surface">
        {list.map(({ t, pulse, views, priceCpm }) => {
          const fav = (s.favorites ?? []).includes(t.id);
          return (
            <div key={t.id} className="flex items-center gap-1 border-b border-line px-2 last:border-b-0">
              <button
                type="button"
                onClick={() => s.push({ name: "days", id: t.id })}
                className="flex min-w-0 flex-1 items-center gap-2 py-2.5 text-start"
              >
                <span className="grid size-10 shrink-0 place-items-center rounded-full bg-header text-xs font-bold">
                  {s.ownerName(t.id).slice(0, 1)}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-1.5">
                    <span className="block truncate text-sm font-semibold">{s.ownerName(t.id)}</span>
                    {t.groupId ? (
                      <span className="shrink-0 rounded-full bg-link/15 px-2 py-0.5 text-[10px] font-semibold text-link">
                        {copy().catalog.packageBadge}
                      </span>
                    ) : null}
                  </span>
                  <span className="block truncate text-[11px] text-muted">
                    {t.groupId
                      ? fill(copy().catalog.packageChannels, {
                          n: faNum((s.groups.find((g) => g.id === t.groupId)?.channelIds || []).length || 0),
                        })
                      : null}
                    {t.groupId ? " · " : ""}
                    {fill(copy().common.membersLine, {
                      members: faNum(pulse.members),
                      views: faNum(views),
                      cpm: money(priceCpm),
                    })}
                  </span>
                  <span className="block truncate text-[11px] text-muted">
                    {fill(copy().catalog.metricLine, {
                      err: faPercent(pulse.err),
                      growth: faSignedPercent(pulse.growth),
                    })}
                  </span>
                </span>
                <span className="shrink-0 text-end">
                  <span className="block text-sm font-bold">{money(t.price)}</span>
                  <span className="block text-[11px] text-muted">{fill(copy().common.hoursShort, { n: faNum(t.durationHours) })}</span>
                </span>
              </button>
              <button
                type="button"
                aria-label={fav ? copy().a11y.unsave : copy().a11y.save}
                className={`grid size-11 shrink-0 place-items-center ${fav ? "text-link" : "text-muted"}`}
                onClick={() => s.toggleFavorite(t.id)}
              >
                <Star className={`size-4 ${fav ? "fill-current" : ""}`} />
              </button>
            </div>
          );
        })}
      </div>
    </>
  );
}

function chargeViaBale(amount: number, toast: (m: string) => void) {
  const apply = () =>
    run(toast, copy().toast.charged, useMarket.getState().topUp("customer", amount, copy().toast.topupNote));
  const sim = window.__baleSim;
  if (!sim) {
    apply();
    return;
  }
  sim.openInvoice({ title: copy().toast.chargeTitle, amountToman: amount }, (status) => {
    if (status === "paid") apply();
    else if (status === "cancelled") toast(copy().toast.chargeCancel);
    else if (status === "failed") toast(copy().toast.chargeFail);
    else toast(copy().toast.chargePending);
  });
}

function payOrderViaBale(orderId: number, amount: number, toast: (m: string) => void) {
  const apply = () =>
    run(
      toast,
      copy().toast.paidHold,
      useMarket.getState().payOrder(orderId, "bale"),
    );
  const sim = window.__baleSim;
  if (!sim) {
    apply();
    return;
  }
  sim.openInvoice({ title: fill(copy().common.orderNo, { n: faNum(orderId) }), amountToman: amount }, (status) => {
    if (status === "paid") apply();
    else if (status === "cancelled") toast(copy().toast.payCancel);
    else if (status === "failed") toast(copy().toast.payFail);
    else toast(copy().toast.payPending);
  });
}

function orderTone(status: string) {
  if (status === "rejected" || status === "cancelled" || status === "failed_publish") return "text-danger";
  if (status === "paid" || status === "completed" || status === "executed" || status === "approved") return "text-ok";
  return "text-link";
}

function MyOrders({ toast }: { toast: (m: string) => void }) {
  const s = useMarket();
  const [note, setNote] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  if (!s.orders.length) return <Empty>{copy().orders.empty}</Empty>;
  return (
    <ul className="overflow-hidden rounded-2xl bg-surface">
      {s.orders.map((o) => {
        const lines = s.items.filter((i) => i.orderId === o.id);
        const shown = open === o.id;
        return (
          <li key={o.id} className="border-b border-line last:border-b-0">
            <button
              type="button"
              className="flex w-full items-center gap-2 px-3 py-3 text-start"
              onClick={() => setOpen(shown ? null : o.id)}
            >
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-semibold">{fill(copy().common.orderNo, { n: faNum(o.id) })}</span>
                <span className="block truncate text-[11px] text-muted">{o.bannerTitle}</span>
              </span>
              <span className="shrink-0 text-end">
                <span className="block text-xs font-semibold">{money(o.total)}</span>
                <span className={`block text-[11px] ${orderTone(o.status)}`}>{ST_O[o.status]}</span>
              </span>
            </button>
            {shown ? (
              <div className="px-3 pb-3">
            <p className="text-xs text-muted">{formatJalali(shiftFromIso(o.created))}</p>
            {o.status === "waiting_payment" ? (
              <div className="mt-2">
                <Btn onClick={() => payOrderViaBale(o.id, o.total, toast)}>{copy().orders.pay}</Btn>
              </div>
            ) : null}
            {lines.map((line) => {
              const t = s.tariffById(line.tariffId);
              const chId = t?.channelId ?? s.channels[0]?.id;
              return (
                <div key={line.id} className="mt-2 border-t border-line pt-2">
                  <p className="text-xs text-muted">
                    {s.ownerName(line.tariffId)} · {ST_E[line.execution]}
                  </p>
                  {line.publishedLink ? (
                    <a className="text-xs text-link" href={line.publishedLink} target="_blank" rel="noreferrer">
                      {copy().common.link}
                    </a>
                  ) : null}
                  {line.managerStatus === "edited" && line.proposedDate ? (
                    <div className="mt-2">
                      <p className="text-xs leading-relaxed text-muted">
                        {fill(copy().tpl.proposal, {
                          from: formatJalali(shiftFromIso(line.date)),
                          to: formatJalali(shiftFromIso(line.proposedDate)),
                        })}
                      </p>
                      <div className="mt-2 grid grid-cols-2 gap-2">
                        <Btn tone="ok" onClick={() => run(toast, copy().toast.timeAccepted, s.answerTime(line.id, true))}>
                          {copy().orders.acceptTime}
                        </Btn>
                        <Btn tone="danger" onClick={() => run(toast, copy().toast.channelLeft, s.answerTime(line.id, false))}>
                          {copy().orders.rejectChannel}
                        </Btn>
                      </div>
                    </div>
                  ) : null}
                  {line.managerStatus === "rejected" || line.managerStatus === "customer_declined" ? (
                    <p className="mt-1 text-xs text-muted">{copy().orders.othersContinue}</p>
                  ) : null}
                  {line.execution === "failed_publish" ? (
                    <p className="mt-1 text-xs text-muted">{copy().orders.publishFailed}</p>
                  ) : null}
                  <p className="text-xs text-muted">{ST_M[line.managerStatus]}</p>
                  {line.execution === "awaiting_customer_confirm" ? (
                    <div className="mt-2 grid grid-cols-2 gap-2">
                      <Btn tone="ok" onClick={() => run(toast, fill(copy().toast.confirmed, { fee: faNum(FEE_PERCENT) }), s.confirmPublish(line.id))}>
                        {copy().orders.confirm}
                      </Btn>
                      <Btn
                        tone="danger"
                        onClick={() => run(toast, copy().toast.disputed, s.openDispute(line.id, note || copy().toast.disputeDefault))}
                      >
                        {copy().orders.dispute}
                      </Btn>
                    </div>
                  ) : null}
                  {line.execution === "executed" && chId ? (
                    <div className="mt-2 flex gap-1">
                      {[5, 4, 3].map((star) => (
                        <button
                          key={star}
                          type="button"
                          className="min-h-9 rounded-lg bg-surface px-2 text-xs"
                          onClick={() => run(toast, copy().toast.rated, s.rateChannel(chId, star))}
                        >
                          {fill(copy().common.starN, { n: faNum(star) })}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              );
            })}
            {lines.some((l) => l.execution === "awaiting_customer_confirm") ? (
              <input
                className={`${control} mt-2`}
                placeholder={copy().orders.disputePh}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            ) : null}
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function Disputes({ toast }: { toast: (m: string) => void }) {
  const disputesAll = useMarket((s) => s.disputes);
  const items = useMarket((s) => s.items);
  const ownerName = useMarket((s) => s.ownerName);
  const resolveDispute = useMarket((s) => s.resolveDispute);
  const [openId, setOpenId] = useState<number | null>(null);
  const disputes = Array.isArray(disputesAll) ? disputesAll : [];
  const open = disputes.filter((d) => d.status === "open");
  if (!open.length) return <Empty>{copy().operator.disputeEmpty}</Empty>;
  return (
    <>
      <p className="mb-2 px-1 text-xs leading-relaxed text-muted">
        {copy().operator.disputeLead}
      </p>
      <ul className="overflow-hidden rounded-2xl bg-surface">
        {open.map((d) => {
          const item = items.find((i) => i.id === d.itemId);
          const shown = openId === d.id;
          return (
            <li key={d.id} className="border-b border-line last:border-b-0">
              <button
                type="button"
                className="flex w-full items-center gap-2 px-3 py-3 text-start"
                onClick={() => setOpenId(shown ? null : d.id)}
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">
                    {item ? ownerName(item.tariffId) : fill(copy().tpl.disputeTitle, { n: faNum(d.id) })}
                  </span>
                  <span className="block truncate text-[11px] text-muted">{d.note}</span>
                </span>
                <span className="shrink-0 text-end">
                  <span className="block text-xs font-semibold">{item ? money(item.price) : ""}</span>
                  <span className="block text-[11px] text-link">{copy().common.open}</span>
                </span>
              </button>
              {shown ? (
                <div className="grid grid-cols-2 gap-2 px-3 pb-3">
                  <Btn tone="ok" onClick={() => run(toast, copy().toast.released, resolveDispute(d.id, false))}>
                    {copy().operator.release}
                  </Btn>
                  <Btn tone="danger" onClick={() => run(toast, copy().toast.refunded, resolveDispute(d.id, true))}>
                    {copy().operator.refund}
                  </Btn>
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </>
  );
}

function Customer({ screen, toast }: { screen: Screen; toast: (m: string) => void }) {
  const s = useMarket();
  const banner = s.banners.find((b) => b.id === s.selectedBannerId && b.fromLinkbank);

  if (screen.name === "home") {
    const ready = Boolean(banner);
    return (
      <>
        <button
          type="button"
          onClick={() => s.go({ name: "wallet" })}
          className="mb-3 flex w-full items-center gap-2 rounded-2xl bg-surface px-3 py-3 text-start"
        >
          <span className="min-w-0 flex-1">
            <span className="block text-[11px] text-muted">{copy().wallet.balanceLabel}</span>
            <b className="text-base">{money(s.customerBalance)}</b>
          </span>
          <span className="text-end">
            <span className="block text-[11px] text-muted">{copy().wallet.cartLabel}</span>
            <b className="text-sm">{faNum(s.cart.length)}</b>
          </span>
          <ChevronLeft className="size-4 shrink-0 text-muted" />
        </button>
        {!(s.onboarded || {}).customer ? (
          <Guide
            title={copy().customer.guideTitle}
            steps={[
              copy().customer.guide[0],
              fill(copy().tpl.customerBannerFee, { fee: money(BANNER_FEE) }),
              copy().customer.guide[1],
              copy().customer.guide[2],
              copy().customer.guide[3],
              copy().tpl.customerPay,
            ]}
            onDismiss={() => s.markOnboarded("customer")}
          />
        ) : null}
        <h2 className="mb-1 px-1 text-[11px] text-muted">{copy().customer.next}</h2>
        <MenuList>
          <MenuRow
            title={copy().screen.banners}
            hint={
              ready
                ? fill(copy().tpl.bannerPicked, { title: banner?.title ?? "" })
                : copy().customer.needPick
            }
            onClick={() => s.go({ name: "banners" })}
          />
          <MenuRow
            title={copy().customer.catalog}
            hint={copy().customer.catalogHint}
            onClick={() => s.go({ name: "catalog" })}
          />
          <MenuRow
            title={copy().screen.cart}
            hint={copy().customer.cartHint}
            onClick={() => s.go({ name: "cart" })}
          />
          <MenuRow
            title={copy().screen.mine}
            hint={copy().customer.mineHint}
            onClick={() => s.go({ name: "mine" })}
          />
        </MenuList>
      </>
    );
  }

  if (screen.name === "catalog") return <CatalogBoard />;

  if (screen.name === "days") {
    const t = s.tariffById(screen.id);
    if (!t) return <Empty>{copy().catalog.missing}</Empty>;
    return (
      <>
        <div className="mb-3 rounded-2xl bg-surface px-3 py-3">
          <b className="block text-sm">{t.name}</b>
          <span className="block text-[11px] text-muted">
            {s.ownerName(t.id)} · {money(t.price)} · {copy().catalog.dayHint}
          </span>
        </div>
        <p className="mb-2 px-1 text-xs leading-relaxed text-muted">
          {copy().catalog.dayLead}
        </p>
        <ChannelPulse channels={tariffChannels(s, t.id)} />
        <CustomerDays tariffId={t.id} toast={toast} />
      </>
    );
  }

  if (screen.name === "banners") return <BannerHub toast={toast} />;
  if (screen.name === "banner" && "id" in screen) return <BannerDetail id={screen.id} toast={toast} />;
  if (screen.name === "bannerNew") return <BannerComposer toast={toast} />;
  if (screen.name === "bannerForward") return <BannerForward />;

  if (screen.name === "cart") {
    if (!s.cart.length) return <Empty>{copy().orders.cartEmpty}</Empty>;
    const total = s.cart.reduce((sum, line) => sum + (s.tariffById(line.tariffId)?.price ?? 0), 0);
    return (
      <>
        <p className="mb-2 px-1 text-xs leading-relaxed text-muted">{copy().orders.cartLead}</p>
        <ul className="mb-3 overflow-hidden rounded-2xl bg-surface">
          {s.cart.map((it) => {
            const t = s.tariffById(it.tariffId);
            return (
              <li key={it.id} className="flex items-center gap-1 border-b border-line pe-1 last:border-b-0">
                <span className="min-w-0 flex-1 px-3 py-3">
                  <span className="block truncate text-sm font-semibold">{s.ownerName(it.tariffId)}</span>
                  <span className="block truncate text-[11px] text-muted">
                    {t?.name} · {formatJalali(shiftFromIso(it.date))}
                  </span>
                </span>
                <b className="shrink-0 text-xs">{money(t?.price ?? 0)}</b>
                <button
                  type="button"
                  aria-label={copy().a11y.removeCart}
                  className="grid size-11 shrink-0 place-items-center text-danger"
                  onClick={() => run(toast, copy().toast.removedCart, s.removeCart(it.id))}
                >
                  <Trash2 className="size-4" />
                </button>
              </li>
            );
          })}
        </ul>
        <div className="rounded-2xl bg-surface px-3 py-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm">{copy().orders.total}</span>
            <b className="text-sm">{money(total)}</b>
          </div>
          <p className="mt-1 text-xs text-muted">
            {banner ? fill(copy().tpl.bannerOrder, { title: banner.title }) : copy().tpl.noBannerYet}
          </p>
          <div className="mt-2">
            <Btn
              disabled={!banner}
              onClick={() => {
                const err = s.checkout();
                if (!err) s.go({ name: "mine" });
                run(toast, copy().toast.checkedOut, err);
              }}
            >
              {copy().orders.checkout}
            </Btn>
          </div>
        </div>
      </>
    );
  }

  if (screen.name === "mine") return <MyOrders toast={toast} />;

  if (screen.name === "wallet") return <WalletPanel owner="customer" toast={toast} />;

  return <Empty>{copy().orders.elsewhere}</Empty>;
}

function stageLabel(banner: Banner): { text: string; tone: "ok" | "warn" | "danger" } {
  if (banner.stage === "rejected") return { text: copy().banner.rejected, tone: "danger" };
  if (banner.stage === "pending" || !banner.fromLinkbank) return { text: copy().banner.pending, tone: "warn" };
  return { text: copy().banner.ready, tone: "ok" };
}

function BannerMedia({
  banner,
  compact = false,
}: {
  banner: Pick<Banner, "mediaKind" | "mediaUrl" | "posterUrl" | "title">;
  compact?: boolean;
}) {
  const frame = compact
    ? "aspect-video max-h-36 w-full rounded-xl bg-bg object-cover"
    : "aspect-square w-full rounded-xl bg-bg object-cover";
  if (banner.mediaKind === "video") {
    return <video className={frame} controls playsInline poster={banner.posterUrl} src={banner.mediaUrl} />;
  }
  return <img className={frame} src={banner.mediaUrl} alt={banner.title} />;
}

function CaptionBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 110 || text.split("\n").length > 3;
  return (
    <div className="mt-2">
      <p className={`whitespace-pre-wrap text-sm leading-relaxed ${open ? "" : "line-clamp-3"}`}>{text}</p>
      {long ? (
        <button type="button" className="mt-1 text-xs text-link" onClick={() => setOpen((v) => !v)}>
          {open ? copy().banner.closeText : copy().banner.moreText}
        </button>
      ) : null}
    </div>
  );
}

function IconBtn({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className="grid size-11 shrink-0 place-items-center rounded-xl text-muted"
    >
      {children}
    </button>
  );
}

function BannerHub({ toast }: { toast: (m: string) => void }) {
  const banners = useMarket((s) => s.banners);
  const selected = useMarket((s) => s.selectedBannerId);
  const push = useMarket((s) => s.push);
  const removeBanner = useMarket((s) => s.removeBanner);
  const useBanner = useMarket((s) => s.useBanner);
  const go = useMarket((s) => s.go);
  return (
    <>
      <h2 className="mb-1 px-1 text-[11px] text-muted">{copy().banner.register}</h2>
      <p className="mb-2 px-1 text-xs leading-relaxed text-muted">
        {copy().banner.registerLead}
      </p>
      <div className="mb-3">
        <MenuList>
          <MenuRow
            title={copy().banner.haveTitle}
            hint={copy().banner.haveHint}
            onClick={() => push({ name: "bannerForward" })}
          />
          <MenuRow
            title={copy().banner.needTitle}
            hint={fill(copy().tpl.newBannerHint, { fee: money(BANNER_FEE) })}
            onClick={() => push({ name: "bannerNew" })}
          />
        </MenuList>
      </div>
      <h2 className="mb-1 px-1 text-[11px] text-muted">{copy().banner.yours}</h2>
      <p className="mb-2 px-1 text-[11px] leading-relaxed text-muted">
        {copy().banner.listLead}
      </p>
      {!banners.length ? <Empty>{copy().banner.empty}</Empty> : null}
      <ul className="overflow-hidden rounded-2xl bg-surface">
        {banners.map((b) => {
          const stage = stageLabel(b);
          const thumb = b.mediaKind === "video" ? b.posterUrl : b.mediaUrl;
          return (
            <li key={b.id} className="flex items-center border-b border-line pe-1 last:border-b-0">
              <button
                type="button"
                className="flex min-w-0 flex-1 items-center gap-2 px-2 py-2 text-start"
                onClick={() => push({ name: "banner", id: b.id })}
              >
                <img src={thumb} alt="" className="size-11 shrink-0 rounded-lg object-cover" />
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold">
                    {b.title}
                    {selected === b.id ? copy().common.selectedMark : ""}
                  </span>
                  <span className={`block truncate text-[11px] ${stage.tone === "danger" ? "text-danger" : "text-muted"}`}>
                    {stage.text} · {b.mediaKind === "video" ? copy().common.video : copy().common.photo}
                  </span>
                </span>
              </button>
              <IconBtn label={copy().a11y.edit} onClick={() => push({ name: "banner", id: b.id })}>
                <Pencil className="size-4" />
              </IconBtn>
              {b.fromLinkbank && b.stage === "ready" ? (
                <IconBtn
                  label={copy().banner.pick}
                  onClick={() => {
                    const err = useBanner(b.id);
                    if (!err) go({ name: "catalog" });
                    run(toast, copy().toast.picked, err);
                  }}
                >
                  <Check className="size-4 text-ok" />
                </IconBtn>
              ) : null}
              <IconBtn
                label={copy().a11y.remove}
                onClick={() => run(toast, copy().toast.bannerRemoved, removeBanner(b.id))}
              >
                <Trash2 className="size-4" />
              </IconBtn>
            </li>
          );
        })}
      </ul>
    </>
  );
}

function BannerDetail({ id, toast }: { id: number; toast: (m: string) => void }) {
  const banner = useMarket((s) => s.banners.find((b) => b.id === id));
  const reviseBanner = useMarket((s) => s.reviseBanner);
  const removeBanner = useMarket((s) => s.removeBanner);
  const useBanner = useMarket((s) => s.useBanner);
  const back = useMarket((s) => s.back);
  const go = useMarket((s) => s.go);
  const [title, setTitle] = useState(banner?.title ?? "");
  const [caption, setCaption] = useState(banner?.caption ?? "");
  if (!banner) return <Empty>{copy().error.bannerMissing}</Empty>;
  const stage = stageLabel(banner);
  return (
    <>
      <BannerMedia banner={banner} />
      <div className="mt-2 flex items-center justify-between gap-2">
        <Badge tone={stage.tone}>{stage.text}</Badge>
        <span className="text-xs text-muted">{banner.mediaKind === "video" ? copy().common.video : copy().common.photo}</span>
      </div>
      {banner.rejectReason ? <p className="mt-2 text-xs leading-relaxed text-danger">{banner.rejectReason}</p> : null}
      <CaptionBlock text={banner.caption} />
      <div className="mt-3">
        <Field label={copy().banner.fieldTitle}>
          <input className={control} value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label={copy().banner.fieldText}>
          <textarea className={control} rows={4} value={caption} onChange={(e) => setCaption(e.target.value)} />
        </Field>
        <Btn
          tone="ghost"
          onClick={() =>
            run(
              toast,
              banner.stage === "ready" ? copy().toast.revisedPending : copy().toast.saved,
              reviseBanner(banner.id, title, caption),
            )
          }
        >
          {copy().banner.saveEdit}
        </Btn>
      </div>
      {banner.fromLinkbank && banner.stage === "ready" ? (
        <div className="mt-2">
          <Btn
            onClick={() => {
              const err = useBanner(banner.id);
              if (!err) go({ name: "catalog" });
              run(toast, copy().toast.picked, err);
            }}
          >
            {copy().banner.pick}
          </Btn>
        </div>
      ) : null}
      <div className="mt-2">
        <Btn
          tone="danger"
          onClick={() => {
            const err = removeBanner(banner.id);
            if (!err) back();
            run(toast, copy().toast.bannerRemoved, err);
          }}
        >
          {copy().banner.remove}
        </Btn>
      </div>
    </>
  );
}

const SAMPLES: { label: string; mediaKind: MediaKind; mediaUrl: string; posterUrl: string }[] = [
  { label: copy().banner.samplePhoto, mediaKind: "photo", mediaUrl: "/banners/saffron.jpg", posterUrl: "/banners/saffron.jpg" },
  { label: copy().banner.sampleVideo, mediaKind: "video", mediaUrl: "/banners/cream.mp4", posterUrl: "/banners/cream.jpg" },
];

function BannerComposer({ toast }: { toast: (m: string) => void }) {
  const banners = useMarket((s) => s.banners);
  const submitBanner = useMarket((s) => s.submitBanner);
  const back = useMarket((s) => s.back);
  const fee = banners.some((b) => b.fromLinkbank) ? BANNER_FEE : 0;
  const [title, setTitle] = useState("");
  const [caption, setCaption] = useState("");
  const [mediaKind, setMediaKind] = useState<MediaKind>("photo");
  const [mediaUrl, setMediaUrl] = useState("");
  const [posterUrl, setPosterUrl] = useState("");

  function onFile(file: File | undefined) {
    if (!file) return;
    const url = URL.createObjectURL(file);
    if (file.type.startsWith("video")) {
      setMediaKind("video");
      setMediaUrl(url);
      setPosterUrl("");
      return;
    }
    if (file.type.startsWith("image")) {
      setMediaKind("photo");
      setMediaUrl(url);
      setPosterUrl(url);
      return;
    }
    toast(copy().toast.onlyMedia);
  }

  return (
    <>
      <p className="mb-3 px-1 text-xs leading-relaxed text-muted">
        {copy().banner.composerLead}
        {fee ? fill(copy().tpl.feeCost, { fee: money(fee) }) : copy().tpl.firstFree}{" "}
        {copy().banner.composerBack}
      </p>
      <div className="mb-2 grid grid-cols-2 gap-2">
        {SAMPLES.map((sample) => (
          <button
            key={sample.label}
            type="button"
            className={`min-h-11 rounded-xl border px-3 text-xs ${mediaUrl === sample.mediaUrl ? "border-link text-link" : "border-line text-muted"}`}
            onClick={() => {
              setMediaKind(sample.mediaKind);
              setMediaUrl(sample.mediaUrl);
              setPosterUrl(sample.posterUrl);
            }}
          >
            {sample.label}
          </button>
        ))}
      </div>
      <Field label={copy().banner.ownFile}>
        <input
          className={control}
          type="file"
          accept="image/*,video/*"
          onChange={(e) => onFile(e.target.files?.[0])}
        />
      </Field>
      {mediaUrl ? (
        <div className="mb-2">
          <BannerMedia banner={{ mediaKind, mediaUrl, posterUrl, title: title || copy().banner.preview }} />
        </div>
      ) : (
        <Empty>{copy().banner.noMedia}</Empty>
      )}
      <Field label={copy().banner.titlePh}>
        <input className={control} value={title} onChange={(e) => setTitle(e.target.value)} placeholder={copy().banner.titleEx} />
      </Field>
      <Field label={copy().banner.textLabel}>
        <textarea
          className={control}
          rows={5}
          value={caption}
          onChange={(e) => setCaption(e.target.value)}
          placeholder={copy().banner.textPh}
        />
      </Field>
      <Btn
        onClick={() => {
          const err = submitBanner({ title, caption, mediaKind, mediaUrl, posterUrl });
          if (!err) back();
          run(toast, fee ? copy().toast.sentPaid : copy().toast.sentFree, err);
        }}
      >
        {fee ? fill(copy().tpl.sendPaid, { fee: money(fee) }) : copy().tpl.sendFree}
      </Btn>
    </>
  );
}

function BannerForward() {
  return (
    <>
      <Guide
        title={copy().banner.forwardTitle}
        steps={[
          copy().banner.forwardSteps[0],
          copy().banner.forwardSteps[1],
          copy().banner.forwardSteps[2],
          copy().banner.forwardSteps[3],
        ]}
      />
      <p className="px-1 text-xs leading-relaxed text-muted">
        {copy().banner.forwardNote}
      </p>
    </>
  );
}

function OperatorBanner({ id, toast }: { id: number; toast: (m: string) => void }) {
  const req = useMarket((s) => s.bannerReqs.find((r) => r.id === id));
  const decideBanner = useMarket((s) => s.decideBanner);
  const [why, setWhy] = useState("");
  if (!req) return null;
  return (
    <div>
      <BannerMedia
        compact
        banner={{ mediaKind: req.mediaKind, mediaUrl: req.mediaUrl, posterUrl: req.posterUrl, title: req.title }}
      />
      <div className="mt-2 flex items-start justify-between gap-2">
        <b className="text-sm">{req.title}</b>
        <Badge tone={req.fee ? "warn" : "ok"}>{req.fee ? money(req.fee) : copy().banner.firstFreeBadge}</Badge>
      </div>
      <p className="mt-1 text-xs text-muted">{fill(copy().common.customerNo, { n: faNum(req.customerLabel) })}</p>
      <CaptionBlock text={req.caption} />
      <Field label={copy().banner.rejectLabel}>
        <input className={control} value={why} onChange={(e) => setWhy(e.target.value)} placeholder={copy().banner.rejectPh} />
      </Field>
      <div className="grid grid-cols-2 gap-2">
        <Btn tone="ok" onClick={() => run(toast, copy().toast.publishedReady, decideBanner(req.id, true))}>
          {copy().banner.approve}
        </Btn>
        <Btn tone="danger" onClick={() => run(toast, copy().toast.rejectedSeen, decideBanner(req.id, false, why))}>
          {copy().common.reject}
        </Btn>
      </div>
    </div>
  );
}

function Operator({ screen, toast }: { screen: Screen; toast: (m: string) => void }) {
  const s = useMarket();
  const [openReq, setOpenReq] = useState<number | null>(null);
  const pending = s.items.filter((i) => i.managerStatus === "pending").length;

  if (screen.name === "disputes") return <Disputes toast={toast} />;

  if (screen.name === "linkyar") {
    const now = Date.now();
    const freshCount = s.channels.filter((ch) => ch.statsAt && now - ch.statsAt < 6 * 3600 * 1000).length;
    const on = s.linkyar.connected && !s.linkyar.error;
    return (
      <>
        <div className={`mb-3 rounded-2xl px-3 py-3 ${on ? "bg-link text-on" : "bg-danger/15 text-danger"}`}>
          <span className={`text-xs ${on ? "text-on/80" : ""}`}>{copy().operator.linkyarAccount}</span>
          <b className="mt-1 block">{on ? copy().operator.linkyarOn : copy().operator.linkyarOff}</b>
          <span className={`mt-1 block text-xs ${on ? "text-on/80" : ""}`} dir="ltr">
            {copy().operator.linkyarHandle}
          </span>
        </div>
        <p className="mb-2 px-1 text-xs leading-relaxed text-muted">{copy().operator.linkyarLead}</p>
        <p className="mb-2 px-1 text-[11px] text-muted">
          {copy().stats.updated}: {s.linkyar.checkedAt ? formatJalali(new Date(s.linkyar.checkedAt)) : copy().stats.empty}
          {" · "}
          {fill(copy().operator.linkyarFresh, { n: faNum(freshCount), all: faNum(s.channels.length) })}
        </p>
        {s.linkyar.error ? <p className="mb-2 px-1 text-xs text-danger">{s.linkyar.error}</p> : null}
        <div className="mb-3">
          <Btn
            onClick={() => {
              s.refreshChannelStats(true);
              toast(copy().toast.statsRead);
            }}
          >
            {copy().operator.reread}
          </Btn>
        </div>
        <ul className="overflow-hidden rounded-2xl bg-surface">
          {s.channels.map((ch) => {
            const stale = !ch.statsAt || now - ch.statsAt >= 6 * 3600 * 1000;
            return (
              <li key={ch.id} className="border-b border-line px-3 py-3 last:border-b-0">
                <div className="flex items-start justify-between gap-2">
                  <span className="min-w-0">
                    <b className="block truncate text-sm">{ch.name}</b>
                    <span className="block truncate text-[11px] text-muted" dir="ltr">
                      {ch.link}
                    </span>
                  </span>
                  <span className={`shrink-0 text-[11px] font-semibold ${stale ? "text-danger" : "text-ok"}`}>
                    {stale ? copy().operator.stale : copy().operator.fresh}
                  </span>
                </div>
                <p className="mt-1 text-[11px] text-muted">
                  {fill(copy().stats.membersViews, { members: faNum(ch.members), views: faNum(ch.avgViews) })}
                </p>
                <p className="mt-0.5 text-[11px] text-muted">
                  {ch.linkyarChecked === false
                    ? "لینک‌یار هنوز بررسی نشده"
                    : ch.linkyarIsAdmin
                      ? copy().operator.adminYes
                      : copy().operator.adminNo}
                  {" · "}
                  {ch.statsAt ? formatJalali(new Date(ch.statsAt)) : copy().stats.empty}
                </p>
              </li>
            );
          })}
        </ul>
      </>
    );
  }

  if (screen.name === "home") {
    const reqs = s.bannerReqs.filter((r) => r.status === "pending").length;
    const pays = s.payouts.filter((p) => p.status === "pending");
    const due = pays.reduce((sum, p) => sum + (Number(p.amount) || 0), 0);
    return (
      <>
        <button
          type="button"
          onClick={() => s.push({ name: "linkyar" })}
          className="mb-3 flex w-full items-center gap-2 rounded-2xl bg-link px-3 py-3 text-start text-on"
        >
          <span className="min-w-0 flex-1">
            <span className="block text-[11px] text-on/80">{copy().operator.linkyarAccount}</span>
            <b className="text-base">{s.linkyar.connected ? copy().operator.linkyarOn : copy().operator.linkyarOff}</b>
          </span>
          <ChevronLeft className="size-4 shrink-0" />
        </button>
        <button
          type="button"
          onClick={() => s.go({ name: "opp" })}
          className="mb-3 flex w-full items-center gap-2 rounded-2xl bg-surface px-3 py-3 text-start"
        >
          <span className="min-w-0 flex-1">
            <span className="block text-[11px] text-muted">{copy().operator.waitingPayout}</span>
            <b className="text-base">{money(due)}</b>
          </span>
          <span className="text-end text-[11px] text-muted">
            {pays.length ? fill(copy().tpl.payoutCount, { n: faNum(pays.length) }) : copy().tpl.noPayoutReq}
          </span>
          <ChevronLeft className="size-4 shrink-0 text-muted" />
        </button>
        {!(s.onboarded || {}).operator ? (
          <Guide
            title={copy().operator.guideTitle}
            steps={[
              copy().operator.guide[0],
              copy().operator.guide[1],
              copy().operator.guide[2],
              copy().operator.guide[3],
            ]}
            onDismiss={() => s.markOnboarded("operator")}
          />
        ) : null}
        <h2 className="mb-1 px-1 text-[11px] text-muted">{copy().operator.queues}</h2>
        <MenuList>
          <MenuRow
            title={copy().operator.review}
            hint={reqs ? fill(copy().tpl.reqWaiting, { n: faNum(reqs) }) : copy().tpl.noReq}
            onClick={() => s.go({ name: "opb" })}
          />
          <MenuRow
            title={copy().screen.disputes}
            hint={copy().operator.disputesHint}
            onClick={() => s.go({ name: "disputes" })}
          />
          <MenuRow
            title={copy().operator.payouts}
            hint={pays.length ? fill(copy().tpl.payoutWaiting, { n: faNum(pays.length) }) : copy().tpl.noPayoutOpen}
            onClick={() => s.go({ name: "opp" })}
          />
          <MenuRow
            title={copy().screen.orders}
            hint={pending ? fill(copy().tpl.itemsWaiting, { n: faNum(pending) }) : copy().tpl.ordersOverview}
            onClick={() => s.go({ name: "orders" })}
          />
        </MenuList>
      </>
    );
  }

  if (screen.name === "opb") {
    const reqs = s.bannerReqs.filter((r) => r.status === "pending");
    if (!reqs.length) return <Empty>{copy().operator.emptyBanners}</Empty>;
    return (
      <>
        <p className="mb-2 px-1 text-xs leading-relaxed text-muted">
          {copy().operator.bannerLead}
        </p>
        <ul className="overflow-hidden rounded-2xl bg-surface">
          {reqs.map((r) => {
            const shown = openReq === r.id;
            const thumb = r.mediaKind === "video" ? r.posterUrl : r.mediaUrl;
            return (
              <li key={r.id} className="border-b border-line last:border-b-0">
                <button
                  type="button"
                  className="flex w-full items-center gap-2 px-3 py-2.5 text-start"
                  onClick={() => setOpenReq(shown ? null : r.id)}
                >
                  <img src={thumb} alt="" className="size-11 shrink-0 rounded-lg object-cover" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{r.title}</span>
                    <span className="block truncate text-[11px] text-muted">
                      {fill(copy().common.customerNo, { n: faNum(r.customerLabel) })} · {r.mediaKind === "video" ? copy().common.video : copy().common.photo}
                    </span>
                  </span>
                  <span className="shrink-0 text-end">
                    <span className="block text-[11px] font-semibold text-link">{r.fee ? money(r.fee) : copy().common.free}</span>
                    <span className="block text-[11px] text-muted">{copy().operator.waiting}</span>
                  </span>
                </button>
                {shown ? (
                  <div className="px-3 pb-3">
                    <OperatorBanner id={r.id} toast={toast} />
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      </>
    );
  }

  if (screen.name === "opp") {
    const rows = s.payouts.filter((p) => p.status === "pending");
    const due = rows.reduce((sum, p) => sum + (Number(p.amount) || 0), 0);
    return (
      <>
        <WeekChart
          title={copy().wallet.payoutChart}
          entries={s.payouts.map((p) => ({ amount: -Math.abs(Number(p.amount) || 0), at: p.createdAt }))}
        />
        <p className="mb-2 px-1 text-xs leading-relaxed text-muted">
          {fill(copy().tpl.dueLine, { amount: money(due) })}
        </p>
        {!rows.length ? <Empty>{copy().error.noPayouts}</Empty> : null}
        {rows.length ? (
          <ul className="mb-3 overflow-hidden rounded-2xl bg-surface">
            {rows.map((p) => (
              <li key={p.id} className="flex items-center justify-between gap-2 border-b border-line px-3 py-3 last:border-b-0">
                <span className="min-w-0">
                  <b className="block truncate text-sm">{p.holder}</b>
                  <span className="block text-[11px] text-muted" dir="ltr">
                    IR ··· {tail(p.iban)}
                  </span>
                </span>
                <b className="shrink-0 text-sm text-danger">{money(p.amount)}</b>
              </li>
            ))}
          </ul>
        ) : null}
        <div className="mb-2">
          <Btn
            tone="ghost"
            disabled={!rows.length}
            onClick={() => {
              const text = s.payoutFile();
              void navigator.clipboard.writeText(text).then(
                () => toast(copy().toast.fileCopied),
                () => toast(text),
              );
            }}
          >
            {copy().operator.copyFile}
          </Btn>
        </div>
        <Btn
          disabled={!rows.length}
          onClick={() => run(toast, copy().toast.payoutsPaid, s.markPayoutsPaid())}
        >
          {copy().operator.markPaid}
        </Btn>
      </>
    );
  }

  if (screen.name === "orders") {
    if (!s.items.length) return <Empty>{copy().operator.ordersEmpty}</Empty>;
    return (
      <>
        <p className="mb-2 px-1 text-xs leading-relaxed text-muted">{copy().operator.ordersLead}</p>
        <ul className="overflow-hidden rounded-2xl bg-surface">
          {s.items.map((o) => (
            <li key={o.id} className="flex items-center gap-2 border-b border-line px-3 py-3 last:border-b-0">
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold">
                  {s.ownerName(o.tariffId)} · {fill(copy().common.orderNo, { n: faNum(o.orderId) })}
                </span>
                <span className="block truncate text-[11px] text-muted">
                  {formatJalali(shiftFromIso(o.date))} · {ST_M[o.managerStatus]}
                </span>
              </span>
              <span className="shrink-0 text-end">
                <span className="block text-xs font-semibold">{money(o.price)}</span>
                <span className={`block text-[11px] ${orderTone(o.execution)}`}>{ST_E[o.execution]}</span>
              </span>
            </li>
          ))}
        </ul>
      </>
    );
  }

  return <Empty>{copy().operator.none}</Empty>;
}
