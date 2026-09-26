import { useEffect, useRef, useState } from "react";
import { LinkBank } from "./linkbank";
import { fill, t } from "@/lib/i18n";
import { faNum, money } from "@/lib/market/format";
import { BANNER_FEE, FEE_PERCENT, MIN_PAYOUT, useMarket } from "@/lib/market/store";

type Scheme = "dark" | "light";
type PayStatus = "paid" | "cancelled" | "failed" | "pending";
type Invoice = { title: string; amountToman: number; resolve: (status: PayStatus) => void };
type Bubble = { id: number; from: "bot" | "me"; text: string; pay?: number };

declare global {
  interface Window {
    __baleSim?: {
      openInvoice: (
        invoice: { title: string; amountToman: number },
        cb: (status: PayStatus) => void,
      ) => void;
    };
  }
}

const THEME: Record<Scheme, Record<string, string>> = {
  dark: {
    bg_color: "#121417",
    text_color: "#f2f4f5",
    hint_color: "#8b98a5",
    link_color: "#3dcec0",
    button_color: "#00a693",
    button_text_color: "#ffffff",
    secondary_bg_color: "#1c2128",
    header_bg_color: "#1a1f24",
    bottom_bar_bg_color: "#1a1f24",
    section_separator_color: "#2a3138",
    destructive_text_color: "#ff6b6b",
  },
  light: {
    bg_color: "#ffffff",
    text_color: "#1c1c1c",
    hint_color: "#8e8e93",
    link_color: "#008f7a",
    button_color: "#00a693",
    button_text_color: "#ffffff",
    secondary_bg_color: "#f4f4f5",
    header_bg_color: "#ffffff",
    bottom_bar_bg_color: "#ffffff",
    section_separator_color: "#e6e6e8",
    destructive_text_color: "#e53935",
  },
};

function numbered(title: string, steps: readonly string[]) {
  return [title, "", ...steps.map((step, i) => `${faNum(i + 1)}. ${step}`)].join("\n");
}

function customerGuide() {
  const bot = t().bot;
  const steps = bot.customer.map((step) => fill(step, { fee: money(BANNER_FEE), percent: faNum(FEE_PERCENT) }));
  return numbered(bot.customerTitle, steps);
}

function managerGuide() {
  const bot = t().bot;
  const steps = bot.manager.map((step) => fill(step, { fee: faNum(FEE_PERCENT), min: money(MIN_PAYOUT) }));
  return numbered(bot.managerTitle, steps);
}

function operatorGuide() {
  const bot = t().bot;
  return numbered(bot.operatorTitle, bot.operator);
}

const ROLE_GUIDE = {
  manager: managerGuide,
  customer: customerGuide,
  operator: operatorGuide,
} as const;

export function BaleSim() {
  const [scheme, setScheme] = useState<Scheme>("dark");
  const [mini, setMini] = useState(false);
  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [log, setLog] = useState<Bubble[]>([
    {
      id: 1,
      from: "bot",
      text: t().bot.welcome,
    },
  ]);
  const setRole = useMarket((s) => s.setRole);
  const endRef = useRef<HTMLDivElement>(null);

  function push(from: Bubble["from"], text: string, pay?: number) {
    setLog((rows) => [...rows, { id: Date.now() + rows.length, from, text, pay }]);
  }

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [log]);

  useEffect(() => {
    window.__baleSim = {
      openInvoice(req, cb) {
        setInvoice({
          title: req.title,
          amountToman: req.amountToman,
          resolve: (status) => {
            cb(status);
            setInvoice(null);
            push(
              "bot",
              status === "paid"
                ? t().toast.payOk
                : status === "cancelled"
                  ? t().toast.payCancelDot
                  : status === "failed"
                    ? t().toast.payFailDot
                    : t().toast.payPendingDot,
            );
          },
        });
      },
    };
    return () => {
      delete window.__baleSim;
    };
  }, []);

  const colors = THEME[scheme];

  return (
    <div className="flex h-dvh flex-col bg-[#0b0e11] px-3 py-3 text-white" data-bale={scheme}>
      <div className="mx-auto flex h-full min-h-0 w-full max-w-md flex-col">
        <div className="mb-2 flex shrink-0 items-center justify-between gap-2 text-xs text-[#8b98a5]">
          <span>{t().brand.sim}</span>
          <button
            type="button"
            className="min-h-9 rounded-full bg-[#1c2128] px-3"
            onClick={() => setScheme((s) => (s === "dark" ? "light" : "dark"))}
          >
            {scheme === "dark" ? t().brand.lightMode : t().brand.darkMode}
          </button>
        </div>
        <div
          className="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-[28px] border border-[#2a3138] shadow-2xl"
          style={{ background: colors.bg_color, color: colors.text_color }}
        >
          <header
            className="flex items-center gap-2 px-3 py-3"
            style={{ background: colors.header_bg_color, borderBottom: `1px solid ${colors.section_separator_color}` }}
          >
            <div className="grid size-10 place-items-center rounded-full text-sm font-bold text-white" style={{ background: colors.button_color }}>
              {t().brand.mark}
            </div>
            <div className="flex-1">
              <b className="block text-sm">{t().brand.bot}</b>
              <span className="text-[11px]" style={{ color: colors.hint_color }}>
                {t().brand.online}
              </span>
            </div>
          </header>
          <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto px-3 py-3">
            {log.map((m) => (
              <div key={m.id} className={m.from === "bot" ? "flex justify-start" : "flex justify-end"}>
                <div
                  className={`inline-block max-w-[85%] whitespace-pre-wrap px-3 py-2 text-sm leading-relaxed ${
                    m.from === "bot" ? "rounded-2xl rounded-tr-md" : "rounded-2xl rounded-tl-md"
                  }`}
                  style={{
                    background: m.from === "me" ? colors.button_color : colors.secondary_bg_color,
                    color: m.from === "me" ? colors.button_text_color : colors.text_color,
                  }}
                >
                  {m.text}
                  {m.pay ? (
                    <button
                      type="button"
                      className="mt-2 block min-h-9 w-full rounded-xl text-xs font-semibold"
                      style={{ background: colors.button_color, color: colors.button_text_color }}
                      onClick={() =>
                        window.__baleSim?.openInvoice(
                          { title: t().bot.sampleInvoice, amountToman: m.pay || 0 },
                          () => undefined,
                        )
                      }
                    >
                      {fill(t().common.payAmount, { amount: money(m.pay) })}
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
            <div ref={endRef} />
          </div>
          <div className="grid grid-cols-2 gap-2 px-3 pt-2" style={{ background: colors.bottom_bar_bg_color }}>
            <SimBtn colors={colors} onClick={() => { push("me", t().bot.mini); setMini(true); }}>
              {t().bot.openMini}
            </SimBtn>
            <SimBtn
              colors={colors}
              onClick={() => {
                push("me", t().bot.forwardMe);
                const err = useMarket.getState().claimReference(0);
                useMarket.getState().setRole("customer");
                useMarket.getState().push({ name: "banners" });
                push("bot", err ? err : t().toast.claimed);
                setMini(true);
              }}
            >
              {t().bot.forward}
            </SimBtn>
          </div>
          <div
            className="grid grid-cols-3 gap-2 px-3 pt-2 pb-3"
            style={{ background: colors.bottom_bar_bg_color }}
          >
            {(
              [
                ["manager", t().role.manager],
                ["customer", t().role.customer],
                ["operator", t().role.operator],
              ] as const
            ).map(([id, label]) => (
              <SimBtn
                key={id}
                colors={colors}
                onClick={() => {
                  setRole(id);
                  push("me", label);
                  push("bot", ROLE_GUIDE[id]());
                  setMini(true);
                }}
              >
                {label}
              </SimBtn>
            ))}
          </div>

          {mini ? (
            <div className="absolute inset-0 flex flex-col" style={{ background: colors.bg_color }}>
              <header
                className="flex items-center gap-1 px-1"
                style={{ background: colors.header_bg_color, borderBottom: `1px solid ${colors.section_separator_color}` }}
              >
                <button type="button" className="grid size-11 place-items-center" onClick={() => setMini(false)} aria-label={t().a11y.closeMini}>
                  ×
                </button>
                <div className="flex-1 py-2 text-center text-sm font-bold">{t().brand.bot}</div>
                <button
                  type="button"
                  className="px-2 text-[11px]"
                  style={{ color: colors.link_color }}
                  onClick={() => setScheme((s) => (s === "dark" ? "light" : "dark"))}
                >
                  {scheme === "dark" ? t().brand.light : t().brand.dark}
                </button>
              </header>
              <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                <LinkBank embedded />
              </div>
            </div>
          ) : null}

          {invoice ? (
            <div className="absolute inset-0 z-20 flex items-end bg-black/50 p-3">
              <div className="w-full rounded-3xl p-4" style={{ background: colors.secondary_bg_color }}>
                <p className="text-xs" style={{ color: colors.hint_color }}>
                  {t().bot.gateway}
                </p>
                <b className="mt-1 block">{invoice.title}</b>
                <p className="mt-2 text-sm">{money(invoice.amountToman)}</p>
                <p className="text-xs" style={{ color: colors.hint_color }}>
                  {fill(t().common.rialLine, { n: faNum(invoice.amountToman * 10) })}
                </p>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <SimBtn colors={colors} tone="fill" onClick={() => invoice.resolve("paid")}>
                    {t().bot.pay}
                  </SimBtn>
                  <SimBtn colors={colors} onClick={() => invoice.resolve("cancelled")}>
                    {t().bot.cancel}
                  </SimBtn>
                  <SimBtn colors={colors} onClick={() => invoice.resolve("failed")}>
                    {t().bot.failed}
                  </SimBtn>
                  <SimBtn colors={colors} onClick={() => invoice.resolve("pending")}>
                    {t().bot.processing}
                  </SimBtn>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function SimBtn({
  children,
  onClick,
  colors,
  tone = "key",
}: {
  children: string;
  onClick: () => void;
  colors: Record<string, string>;
  tone?: "key" | "fill";
}) {
  const fill = tone === "fill";
  return (
    <button
      type="button"
      onClick={onClick}
      className="min-h-11 rounded-xl px-2 text-xs font-semibold"
      style={{
        background: fill ? colors.button_color : colors.secondary_bg_color,
        color: fill ? colors.button_text_color : colors.text_color,
        border: fill ? "none" : `1px solid ${colors.section_separator_color}`,
      }}
    >
      {children}
    </button>
  );
}
