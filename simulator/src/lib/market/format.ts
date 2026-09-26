import { t } from "@/lib/i18n";

export function faNum(value: string | number): string {
  const digits = t().meta.digits;
  return String(value ?? "").replace(/[0-9]/g, (d) => digits[Number(d)] ?? d);
}

export function cpm(price: number, views: number): number {
  if (!views) return 0;
  return Math.round(price / (views / 1000));
}

export function money(n: number): string {
  const s = Math.round(n || 0)
    .toLocaleString("en-US")
    .replace(/,/g, t().meta.groupSep);
  return `${faNum(s)} ${t().unit.toman}`;
}

export function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function parseIso(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1, 12, 0, 0, 0);
}

export function shiftDays(n: number, from = new Date()): Date {
  const d = new Date(from);
  d.setHours(12, 0, 0, 0);
  d.setDate(d.getDate() + n);
  return d;
}

/** Gregorian → Jalali, same algorithm as bot_flow/jalali.py */
export function gregorianToJalali(gy: number, gm: number, gd: number): [number, number, number] {
  const gDm = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
  let jy: number;
  if (gy > 1600) {
    jy = 979;
    gy -= 1600;
  } else {
    jy = 0;
    gy -= 621;
  }
  const gy2 = gm > 2 ? gy + 1 : gy;
  let days =
    365 * gy +
    Math.floor((gy2 + 3) / 4) -
    Math.floor((gy2 + 99) / 100) +
    Math.floor((gy2 + 399) / 400) -
    80 +
    gd +
    (gDm[gm - 1] ?? 0);
  jy += 33 * Math.floor(days / 12053);
  days %= 12053;
  jy += 4 * Math.floor(days / 1461);
  days %= 1461;
  if (days > 365) {
    jy += Math.floor((days - 1) / 365);
    days = (days - 1) % 365;
  }
  let jm: number;
  let jd: number;
  if (days < 186) {
    jm = 1 + Math.floor(days / 31);
    jd = 1 + (days % 31);
  } else {
    jm = 7 + Math.floor((days - 186) / 30);
    jd = 1 + ((days - 186) % 30);
  }
  return [jy, jm, jd];
}

export function formatJalali(d: Date): string {
  const [jy, jm, jd] = gregorianToJalali(d.getFullYear(), d.getMonth() + 1, d.getDate());
  const weekday = t().calendar.weekdays[(d.getDay() + 6) % 7] ?? "";
  return faNum(`${weekday} ${jy}/${String(jm).padStart(2, "0")}/${String(jd).padStart(2, "0")}`);
}

export function jalaliParts(d: Date) {
  const [, m, day] = gregorianToJalali(d.getFullYear(), d.getMonth() + 1, d.getDate());
  const months = t().calendar.months;
  return {
    month: months[(m || 1) - 1] ?? "",
    day: faNum(day),
    col: (d.getDay() + 1) % 7,
  };
}

export function formatJalaliIso(iso: string): string {
  return formatJalali(parseIso(iso));
}

function liveTable(section: "mode" | "stM" | "stE" | "stO"): Record<string, string> {
  return new Proxy({} as Record<string, string>, {
    get(_target, key) {
      if (typeof key !== "string") return "";
      const table = t()[section] as Record<string, string>;
      return table[key] ?? "";
    },
  });
}

export const MODE_LABEL = liveTable("mode");
export const ST_M = liveTable("stM");
export const ST_E = liveTable("stE");
export const ST_O = liveTable("stO");
