import { create } from "zustand";
import { persist } from "zustand/middleware";
import { fill, t } from "@/lib/i18n";
import { faNum, formatJalaliIso, isoDate, money, shiftDays } from "./format";

export type Role = "manager" | "customer" | "operator";
export type PublishMode = "bot" | "linkyar" | "manual";
export type ManagerStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "cart"
  | "edited"
  | "expired"
  | "customer_declined";
export type ExecStatus =
  | "none"
  | "paid"
  | "executed"
  | "failed_publish"
  | "cancelled"
  | "remind_sent"
  | "awaiting_manager_publish"
  | "awaiting_customer_confirm"
  | "awaiting_operator";
export type OrderStatus =
  | "waiting_managers"
  | "waiting_customer_confirm"
  | "waiting_payment"
  | "paid"
  | "completed"
  | "rejected"
  | "cancelled";

export type Screen =
  | { name: "home" }
  | { name: "channels" }
  | { name: "channel"; id: number }
  | { name: "tariffs" }
  | { name: "orders" }
  | { name: "calendar" }
  | { name: "days"; id: number }
  | { name: "finance" }
  | { name: "banners" }
  | { name: "bannerNew" }
  | { name: "bannerForward" }
  | { name: "banner"; id: number }
  | { name: "catalog" }
  | { name: "cart" }
  | { name: "wallet" }
  | { name: "opb" }
  | { name: "opp" }
  | { name: "mine" }
  | { name: "disputes" }
  | { name: "linkyar" };

export type LinkyarLink = {
  connected: boolean;
  checkedAt: number;
  error: string;
};

export type ChannelSnapshot = {
  at: number;
  members: number;
  views: number;
  dailyReach: number;
  posts: number;
  forwards: number;
};

export type Channel = {
  isListed?: boolean;
  id: number;
  name: string;
  link: string;
  publishMode: PublishMode;
  botIsAdmin: boolean;
  linkyarIsAdmin: boolean;
  botChecked?: boolean;
  linkyarChecked?: boolean;
  remindHours: number;
  members: number;
  avgViews: number;
  category: string;
  rating: number;
  ratingCount: number;
  language: string;
  about: string;
  statsAt: number;
  snapshots: ChannelSnapshot[];
};

export type Group = { id: number; name: string; channelIds: number[] };

export type Tariff = {
  id: number;
  channelId: number | null;
  groupId: number | null;
  name: string;
  startHour: number;
  durationHours: number;
  price: number;
  isActive: boolean;
};

export type Busy = { id: number; tariffId: number; date: string; manual: boolean };
export type CalDay = { date: string; status: string; why: string; free: boolean };

export const FEE_PERCENT = 14;
export const MIN_PAYOUT = 100_000;
export const MIN_TOPUP = 10_000;
export const BANNER_FEE = 140_000;

export type MediaKind = "photo" | "video";
export type BannerStage = "ready" | "pending" | "rejected";

export type Banner = {
  id: number;
  title: string;
  caption: string;
  fromLinkbank: boolean;
  mediaKind: MediaKind;
  mediaUrl: string;
  posterUrl: string;
  stage: BannerStage;
  rejectReason: string;
};

export function referencePosts(): Pick<Banner, "title" | "caption" | "mediaKind" | "mediaUrl" | "posterUrl">[] {
  return [
    {
      title: t().demo.coatTitle,
      caption: t().demo.coat,
      mediaKind: "photo",
      mediaUrl: "/banners/coat.jpg",
      posterUrl: "/banners/coat.jpg",
    },
  ];
}

export type CartItem = { id: number; tariffId: number; date: string };

export type Order = {
  canCancel?: boolean;
  canPay?: boolean;
  payHint?: string;
  paymentDeadline?: string;
  payParts?: number;
  payPartsPaid?: number;

  id: number;
  status: OrderStatus;
  created: string;
  bannerTitle: string;
  total: number;
};

export type OrderItem = {
  id: number;
  orderId: number;
  tariffId: number;
  date: string;
  price: number;
  managerStatus: ManagerStatus;
  execution: ExecStatus;
  publishedLink: string;
  proposedDate: string;
};

export type LedgerKind =
  | "earn"
  | "refund"
  | "penalty"
  | "payout_lock"
  | "spend"
  | "escrow"
  | "topup";

export type LedgerEntry = {
  id: number;
  owner: "manager" | "customer";
  amount: number;
  kind: LedgerKind;
  note: string;
  at: number;
};

export type Dispute = {
  id: number;
  itemId: number;
  note: string;
  status: "open" | "refunded" | "released";
};

export type Bank = { id: number; owner: "manager" | "customer"; holder: string; iban: string };

export type Payout = {
  id: number;
  owner: "manager" | "customer" | "queue";
  amount: number;
  status: "pending" | "paid";
  holder: string;
  iban: string;
  createdAt: number;
};

export type BannerReq = {
  id: number;
  customerLabel: string;
  title: string;
  caption: string;
  fee: number;
  status: "pending" | "approved" | "rejected";
  bannerId: number | null;
  mediaKind: MediaKind;
  mediaUrl: string;
  posterUrl: string;
  rejectReason: string;
};

export const PEOPLE: Record<Role, { handle: string; sub: string }> = new Proxy(
  {} as Record<Role, { handle: string; sub: string }>,
  {
    get(_target, role) {
      if (role !== "manager" && role !== "customer" && role !== "operator") return undefined;
      return { handle: t().people[role].handle, sub: t().people[role].sub };
    },
  },
);

type Data = {
  channels: Channel[];
  groups: Group[];
  tariffs: Tariff[];
  busy: Busy[];
  /** وضعیت روز از سرور برای هر تعرفه */
  calendarByTariff?: Record<number, CalDay[]>;
  onboarded?: Record<string, boolean>;
  banners: Banner[];
  selectedBannerId: number | null;
  cart: CartItem[];
  orders: Order[];
  items: OrderItem[];
  banks: Bank[];
  payouts: Payout[];
  ledger: LedgerEntry[];
  disputes: Dispute[];
  favorites: number[];
  bannerReqs: BannerReq[];
  linkyar: LinkyarLink;
  managerBalance: number;
  customerBalance: number;
  nextId: number;
};

function seed(): Data {
  const d = (n: number) => isoDate(shiftDays(n));
  return {
    channels: [
      {
        id: 1,
        name: t().demo.cook,
        link: "ble.ir/maman_cook",
        publishMode: "bot",
        botIsAdmin: true,
        linkyarIsAdmin: false,
        remindHours: 2,
        members: 186_000,
        avgViews: 42_000,
        category: t().demo.food,
        rating: 4.8,
        ratingCount: 36,
        language: "fa",
        about: t().demo.aboutCook,
        statsAt: Date.now() - 26 * 3600 * 1000,
        snapshots: buildSnapshots(186_000, 42_000, 1),
      },
      {
        id: 2,
        name: t().demo.fashion,
        link: "ble.ir/mod_zanan",
        publishMode: "linkyar",
        botIsAdmin: false,
        linkyarIsAdmin: true,
        remindHours: 2,
        members: 94_000,
        avgViews: 18_500,
        category: t().demo.style,
        rating: 4.5,
        ratingCount: 21,
        language: "fa",
        about: t().demo.aboutFashion,
        statsAt: Date.now() - 26 * 3600 * 1000,
        snapshots: buildSnapshots(94_000, 18_500, 2),
      },
      {
        id: 3,
        name: t().demo.tech,
        link: "ble.ir/tech_today",
        publishMode: "manual",
        botIsAdmin: false,
        linkyarIsAdmin: false,
        remindHours: 4,
        members: 41_000,
        avgViews: 9_200,
        category: t().demo.techCat,
        rating: 4.2,
        ratingCount: 11,
        language: "fa",
        about: t().demo.aboutTech,
        statsAt: Date.now() - 26 * 3600 * 1000,
        snapshots: buildSnapshots(41_000, 9_200, 3),
      },
    ],
    groups: [{ id: 1, name: t().demo.life, channelIds: [1, 2] }],
    tariffs: [
      { id: 1, channelId: 1, groupId: null, name: t().demo.lunch, startHour: 12, durationHours: 24, price: 850_000, isActive: true },
      { id: 2, channelId: 1, groupId: null, name: t().demo.night, startHour: 21, durationHours: 8, price: 1_450_000, isActive: true },
      { id: 3, channelId: 2, groupId: null, name: t().demo.pin, startHour: 10, durationHours: 24, price: 620_000, isActive: true },
      { id: 4, channelId: 3, groupId: null, name: t().demo.morning, startHour: 8, durationHours: 6, price: 390_000, isActive: true },
      { id: 5, channelId: null, groupId: 1, name: t().demo.bundle, startHour: 18, durationHours: 24, price: 2_200_000, isActive: true },
    ],
    busy: [
      { id: 101, tariffId: 1, date: d(2), manual: false },
      { id: 102, tariffId: 1, date: d(5), manual: true },
      { id: 103, tariffId: 2, date: d(1), manual: false },
      { id: 104, tariffId: 2, date: d(3), manual: true },
      { id: 105, tariffId: 3, date: d(4), manual: false },
      { id: 106, tariffId: 5, date: d(6), manual: true },
    ],
    banners: [
      {
        id: 1,
        title: t().demo.saffronTitle,
        caption:
          t().demo.saffron,
        fromLinkbank: true,
        mediaKind: "photo",
        mediaUrl: "/banners/saffron.jpg",
        posterUrl: "/banners/saffron.jpg",
        stage: "ready",
        rejectReason: "",
      },
      {
        id: 2,
        title: t().demo.creamTitle,
        caption:
          t().demo.cream,
        fromLinkbank: false,
        mediaKind: "video",
        mediaUrl: "/banners/cream.mp4",
        posterUrl: "/banners/cream.jpg",
        stage: "pending",
        rejectReason: "",
      },
      {
        id: 3,
        title: t().demo.creamOld,
        caption: t().demo.creamOldText,
        fromLinkbank: false,
        mediaKind: "photo",
        mediaUrl: "/banners/cream.jpg",
        posterUrl: "/banners/cream.jpg",
        stage: "rejected",
        rejectReason: t().demo.creamReject,
      },
    ],
    selectedBannerId: 1,
    cart: [{ id: 201, tariffId: 4, date: d(2) }],
    orders: [
      { id: 1042, status: "waiting_managers", created: d(0), bannerTitle: t().demo.saffronTitle, total: 850_000 },
      { id: 1038, status: "waiting_payment", created: d(-1), bannerTitle: t().demo.classTitle, total: 1_450_000 },
      { id: 1011, status: "completed", created: d(-6), bannerTitle: t().demo.boutiqueTitle, total: 620_000 },
    ],
    items: [
      {
        id: 501,
        orderId: 1042,
        tariffId: 1,
        date: d(2),
        price: 850_000,
        managerStatus: "pending",
        execution: "none",
        publishedLink: "",
        proposedDate: "",
      },
      {
        id: 502,
        orderId: 1038,
        tariffId: 2,
        date: d(1),
        price: 1_450_000,
        managerStatus: "approved",
        execution: "none",
        publishedLink: "",
        proposedDate: "",
      },
      {
        id: 503,
        orderId: 1011,
        tariffId: 3,
        date: d(-6),
        price: 620_000,
        managerStatus: "approved",
        execution: "executed",
        publishedLink: "https://ble.ir/mod_zanan/1842/1727000000000",
        proposedDate: "",
      },
    ],
    banks: [
      { id: 1, owner: "manager", holder: t().demo.hossein, iban: "IR820170000000123456789001" },
    ],
    payouts: [
      {
        id: 1,
        owner: "manager",
        amount: 2_000_000,
        status: "paid",
        holder: t().demo.hossein,
        iban: "IR820170000000123456789001",
        createdAt: Date.now() - 20 * 86400000,
      },
      {
        id: 2,
        owner: "queue",
        amount: 960_000,
        status: "pending",
        holder: t().demo.maryam,
        iban: "IR120540000000998877665544",
        createdAt: Date.now() - 3600000,
      },
    ],
    ledger: [
      {
        id: 1,
        owner: "manager",
        amount: 533_200,
        kind: "earn",
        note: t().demo.earnSeed,
        at: Date.now() - 6 * 86400000,
      },
      {
        id: 2,
        owner: "manager",
        amount: -2_000_000,
        kind: "payout_lock",
        note: t().demo.payoutSeed,
        at: Date.now() - 20 * 86400000,
      },
      {
        id: 3,
        owner: "customer",
        amount: 180_000,
        kind: "refund",
        note: t().demo.refundSeed,
        at: Date.now() - 2 * 86400000,
      },
    ],
    disputes: [],
    favorites: [1],
    bannerReqs: [
      {
        id: 17,
        customerLabel: "904412",
        title: t().demo.creamTitle,
        caption:
          t().demo.cream,
        fee: 140_000,
        status: "pending",
        bannerId: 2,
        mediaKind: "video",
        mediaUrl: "/banners/cream.mp4",
        posterUrl: "/banners/cream.jpg",
        rejectReason: "",
      },
      {
        id: 18,
        customerLabel: "221098",
        title: t().demo.coatTitle,
        caption:
          t().demo.coatShort,
        fee: 140_000,
        status: "pending",
        bannerId: null,
        mediaKind: "photo",
        mediaUrl: "/banners/coat.jpg",
        posterUrl: "/banners/coat.jpg",
        rejectReason: "",
      },
    ],
    managerBalance: 4_850_000,
    customerBalance: 2_000_000,
    nextId: 1000,
    linkyar: { connected: true, checkedAt: Date.now() - 26 * 3600 * 1000, error: "" },
  };
}

function ownerOf(data: Data, tariff: Tariff): string {
  if (tariff.groupId) return data.groups.find((g) => g.id === tariff.groupId)?.name ?? t().common.groupWord;
  return data.channels.find((c) => c.id === tariff.channelId)?.name ?? t().screen.channel;
}

function ibanOk(raw: string): boolean {
  const v = raw.replace(/\s/g, "").toUpperCase();
  return /^IR\d{24}$/.test(v);
}

function hasBanned(text: string): boolean {
  const flat = text.replace(/\s/g, "");
  return t().policy.banned.some((word) => text.includes(word) || flat.includes(word.replace(/\s/g, "")));
}

/** تاریخچهٔ ۱۴روزهٔ اعضا و بازدید. برداشت آخر همان عدد فعلی کانال است. */
export function buildSnapshots(members: number, views: number, salt: number): ChannelSnapshot[] {
  const points: ChannelSnapshot[] = [];
  for (let i = 13; i >= 0; i--) {
    const wobble = ((salt * 3 + i * 5) % 7) - 3;
    const factor = 1 - i * 0.006 + wobble * 0.001;
    const m = Math.max(1, Math.round(members * factor));
    const v = Math.max(1, Math.round(views * (factor + ((salt + i) % 3) * 0.008)));
    const posts = 1 + ((salt + i) % 4);
    const forwards = (salt + i) % 3;
    const reach = i === 0 ? views : v;
    const head = i === 0 ? members : m;
    points.push({
      at: shiftDays(-i).getTime(),
      members: head,
      views: reach,
      dailyReach: Math.round(reach * Math.min(posts, 3) * 0.62),
      posts,
      forwards,
    });
  }
  return points;
}

export type ChannelPulse = {
  members: number;
  views: number;
  err: number;
  growth: number;
  postsPerDay: number;
  citation: number;
  dailyReach: number;
  statsAt: number;
  language: string;
  about: string;
  series: { at: number; members: number; views: number }[];
};

export function channelPulse(channels: Channel[]): ChannelPulse {
  const buckets = new Map<string, { at: number; members: number; viewsWeight: number; weight: number; posts: number; forwards: number; daily: number }>();
  for (const ch of channels) {
    for (const p of ch.snapshots ?? []) {
      const key = isoDate(new Date(p.at));
      const row = buckets.get(key) ?? { at: p.at, members: 0, viewsWeight: 0, weight: 0, posts: 0, forwards: 0, daily: 0 };
      row.at = Math.max(row.at, p.at);
      row.members += p.members;
      row.viewsWeight += p.views * Math.max(p.members, 1);
      row.weight += Math.max(p.members, 1);
      row.posts += p.posts;
      row.forwards += p.forwards;
      row.daily += p.dailyReach;
      buckets.set(key, row);
    }
  }
  const series = [...buckets.values()]
    .sort((a, b) => a.at - b.at)
    .map((row) => ({
      at: row.at,
      members: row.members,
      views: row.weight ? Math.round(row.viewsWeight / row.weight) : 0,
      posts: channels.length ? row.posts / channels.length : 0,
      forwards: row.forwards,
      dailyReach: row.daily,
    }));
  const last = series[series.length - 1];
  const members = last?.members ?? channels.reduce((sum, c) => sum + (c.members || 0), 0);
  const views = last?.views ?? 0;
  const weekAgo = (last?.at ?? Date.now()) - 6 * 86400000;
  let prev = series[0];
  for (const point of series) {
    if (point.at <= weekAgo) prev = point;
  }
  const growth = prev && prev.members ? ((members - prev.members) / prev.members) * 100 : 0;
  const postsPerDay = series.length ? series.reduce((sum, p) => sum + p.posts, 0) / series.length : 0;
  const citation = series.length
    ? series.reduce((sum, p) => sum + (p.posts ? p.forwards / (p.posts * Math.max(channels.length, 1)) : 0), 0) / series.length
    : 0;
  const langs = [...new Set(channels.map((c) => c.language).filter(Boolean))];
  return {
    members,
    views,
    err: members ? (views / members) * 100 : 0,
    growth,
    postsPerDay,
    citation,
    dailyReach: last?.dailyReach ?? views,
    statsAt: channels.reduce((max, c) => Math.max(max, c.statsAt || 0), 0),
    language: langs.length === 1 ? langs[0] : "",
    about: channels.map((c) => c.about).find(Boolean) ?? "",
    series,
  };
}

export type MarketState = Data & {
  role: Role;
  stack: Screen[];
  setRole: (role: Role) => void;
  go: (screen: Screen) => void;
  push: (screen: Screen) => void;
  back: () => void;
  reset: () => void;
  ownerName: (tariffId: number) => string;
  tariffById: (id: number) => Tariff | undefined;
  isBusy: (tariffId: number, date: string) => boolean;
  payoutBlock: (owner: "manager" | "customer") => string | null;
  setPublishMode: (channelId: number, mode: PublishMode, remindHours?: number) => string | null;
  addTariff: (input: { channelId?: number | null; groupId?: number | null; name: string; startHour: number; durationHours: number; price: number }) => string | null;
  markOnboarded: (role: "customer" | "manager" | "operator") => void;
  onboarded: Record<string, boolean>;
  updateTariff: (input: { id: number; name: string; startHour: number; durationHours: number; price: number }) => string | null;
  removeTariff: (id: number) => string | null;
  updateChannel: (channelId: number, name: string) => string | null;
  removeChannel: (channelId: number) => string | null;
  archiveChannel: (channelId: number, listed?: boolean) => string | null;
  loadCalendar: (tariffId: number, asCustomer?: boolean) => Promise<string | null>;
  calendarDays: (tariffId: number) => CalDay[];
  searchCatalog: (q: string, readyOnly?: boolean) => Promise<string | null>;
  addGroup: (name: string, channelIds: number[]) => string | null;
  updateGroup: (groupId: number, name: string, channelIds: number[]) => string | null;
  removeGroup: (groupId: number) => string | null;

  toggleTariff: (id: number) => string | null;
  decideItem: (itemId: number, approve: boolean) => string | null;
  toggleBusy: (tariffId: number, date: string) => string | null;
  clearBusy: (slotId: number) => string | null;
  addToCart: (tariffId: number, date: string) => string | null;
  removeCart: (itemId: number) => string | null;
  useBanner: (bannerId: number) => string | null;
  renameBanner: (bannerId: number, title: string) => string | null;
  submitBanner: (input: {
    title: string;
    caption: string;
    mediaKind: MediaKind;
    mediaUrl: string;
    posterUrl: string;
  }) => string | null;
  claimReference: (index: number) => string | null;
  resubmitBanner: (bannerId: number, caption: string) => string | null;
  reviseBanner: (bannerId: number, title: string, caption: string) => string | null;
  removeBanner: (bannerId: number) => string | null;
  suggestTime: (itemId: number, date: string) => string | null;
  answerTime: (itemId: number, accept: boolean) => string | null;
  checkout: () => string | null;
  addBank: (owner: "manager" | "customer", iban: string, holder: string) => string | null;
  requestPayout: (owner: "manager" | "customer", bankId: number) => string | null;
  topUp: (owner: "manager" | "customer", amount: number, note?: string) => string | null;
  payOrder: (orderId: number, via?: "wallet" | "bale") => string | null;
  cancelOrder: (orderId: number) => string | null;
  publishItem: (itemId: number) => string | null;
  confirmPublish: (itemId: number) => string | null;
  openDispute: (itemId: number, note: string) => string | null;
  resolveDispute: (disputeId: number, refund: boolean) => string | null;
  rateChannel: (channelId: number, stars: number) => string | null;
  toggleFavorite: (tariffId: number) => string | null;
  /** لینک‌یار، اگر برداشت کهنه باشد، اعضا و بازدید را دوباره می‌خواند. force یعنی همین حالا، حتی اگر تازه باشد. */
  refreshChannelStats: (force?: boolean) => void;
  decideBanner: (requestId: number, approve: boolean, reason?: string) => string | null;
  markPayoutsPaid: () => string | null;
  payoutFile: () => string;
};

const ESCROW: ExecStatus[] = [
  "paid",
  "remind_sent",
  "awaiting_manager_publish",
  "awaiting_customer_confirm",
  "awaiting_operator",
];

export function escrowTotal(items: OrderItem[]): number {
  return (items ?? [])
    .filter((i) => i && ESCROW.includes(i.execution))
    .reduce((sum, i) => sum + (Number(i.price) || 0), 0);
}

function finishOrder(orders: Order[], items: OrderItem[], orderId: number): Order[] {
  return orders.map((o) => {
    if (o.id !== orderId) return o;
    const lines = items.filter((i) => i.orderId === orderId);
    if (lines.some((i) => i.managerStatus === "pending")) return { ...o, status: "waiting_managers" as const };
    if (lines.some((i) => i.managerStatus === "edited")) return { ...o, status: "waiting_customer_confirm" as const };
    const approved = lines.filter((i) => i.managerStatus === "approved");
    if (!approved.length) return { ...o, status: "rejected" as const, total: 0 };
    const total = approved.reduce((sum, i) => sum + i.price, 0);
    const done = approved.every(
      (i) => i.execution === "executed" || i.execution === "cancelled" || i.execution === "failed_publish",
    );
    if (done) return { ...o, status: "completed" as const, total };
    if (approved.every((i) => i.execution === "none")) return { ...o, status: "waiting_payment" as const, total };
    return { ...o, status: "paid" as const, total };
  });
}

function releaseItem(
  get: () => MarketState,
  set: (partial: Partial<MarketState>) => void,
  itemId: number,
  fromDispute: boolean,
): string | null {
  const s = get();
  const item = s.items.find((i) => i.id === itemId);
  const ready = fromDispute ? item?.execution === "awaiting_operator" : item?.execution === "awaiting_customer_confirm";
  if (!item || !ready) return t().error.notReadyRelease;
  const fee = Math.round((item.price * FEE_PERCENT) / 100);
  const net = item.price - fee;
  const id = s.nextId;
  const items = s.items.map((i) => (i.id === itemId ? { ...i, execution: "executed" as const } : i));
  set({
    nextId: id + 1,
    managerBalance: s.managerBalance + net,
    items,
    orders: finishOrder(s.orders, items, item.orderId),
    ledger: [
      {
        id,
        owner: "manager",
        amount: net,
        kind: "earn",
        note: fill(t().note.earnItem, { id: faNum(itemId), fee: faNum(FEE_PERCENT) }),
        at: Date.now(),
      },
      ...(s.ledger ?? []),
    ],
  });
  return null;
}

function mergeMarket(persisted: unknown, current: MarketState): MarketState {
  const base = seed();
  const p = (persisted && typeof persisted === "object" ? persisted : {}) as Partial<Data> & {
    role?: Role;
    stack?: Screen[];
  };
  const list = <T>(value: unknown, fallback: T[]): T[] => (Array.isArray(value) ? (value as T[]) : fallback);
  const channels = list(p.channels, base.channels).map((raw) => {
    const c = raw as Channel;
    return {
      ...c,
      members: c.members ?? 0,
      avgViews: c.avgViews ?? 0,
      category: c.category || t().common.general,
      rating: c.rating ?? 0,
      ratingCount: c.ratingCount ?? 0,
      language: c.language || "fa",
      about: c.about || base.channels.find((x) => x.id === c.id)?.about || "",
      statsAt: typeof c.statsAt === "number" ? c.statsAt : 0,
      snapshots:
        Array.isArray(c.snapshots) && c.snapshots.length
          ? c.snapshots
          : (base.channels.find((x) => x.id === c.id)?.snapshots ?? buildSnapshots(c.members ?? 0, c.avgViews ?? 0, c.id || 1)),
    };
  });
  const data: Data = {
    ...base,
    ...p,
    channels,
    groups: list(p.groups, base.groups),
    tariffs: list(p.tariffs, base.tariffs),
    busy: list(p.busy, base.busy),
    banners: list(p.banners, base.banners).map((raw) => {
      const b = raw as Banner;
      const stage: BannerStage =
        b.stage === "pending" || b.stage === "rejected" || b.stage === "ready"
          ? b.stage
          : b.fromLinkbank
            ? "ready"
            : "pending";
      return {
        id: b.id,
        title: b.title || t().common.bannerWord,
        caption: b.caption || "",
        fromLinkbank: Boolean(b.fromLinkbank),
        mediaKind: b.mediaKind === "video" ? "video" : "photo",
        mediaUrl: b.mediaUrl || "/banners/saffron.jpg",
        posterUrl: b.posterUrl || b.mediaUrl || "/banners/saffron.jpg",
        stage,
        rejectReason: b.rejectReason || "",
      };
    }),
    cart: list(p.cart, base.cart),
    orders: list(p.orders, base.orders),
    items: list(p.items, base.items).map((raw) => {
      const i = raw as OrderItem;
      return { ...i, proposedDate: i.proposedDate || "", publishedLink: i.publishedLink || "" };
    }),
    banks: list(p.banks, base.banks).filter((b) => b && typeof b.iban === "string" && typeof b.holder === "string"),
    payouts: list(p.payouts, base.payouts).filter((x) => x && typeof x.amount === "number" && typeof x.iban === "string"),
    ledger: list(p.ledger, base.ledger),
    disputes: list(p.disputes, base.disputes),
    favorites: list(p.favorites, base.favorites),
    bannerReqs: list(p.bannerReqs, base.bannerReqs).map((raw) => {
      const r = raw as BannerReq;
      return {
        ...r,
        title: r.title || (r.caption || "").split("\n")[0]?.slice(0, 40) || t().common.bannerWord,
        mediaKind: r.mediaKind === "video" ? "video" : "photo",
        mediaUrl: r.mediaUrl || "/banners/saffron.jpg",
        posterUrl: r.posterUrl || r.mediaUrl || "/banners/saffron.jpg",
        rejectReason: r.rejectReason || "",
      };
    }),
    managerBalance: typeof p.managerBalance === "number" ? p.managerBalance : base.managerBalance,
    customerBalance: typeof p.customerBalance === "number" ? p.customerBalance : base.customerBalance,
    nextId: typeof p.nextId === "number" ? p.nextId : base.nextId,
    linkyar: {
      connected: p.linkyar?.connected !== false,
      checkedAt: typeof p.linkyar?.checkedAt === "number" ? p.linkyar.checkedAt : base.linkyar.checkedAt,
      error: typeof p.linkyar?.error === "string" ? p.linkyar.error : "",
    },
  };
  const role = p.role === "customer" || p.role === "operator" || p.role === "manager" ? p.role : current.role;
  const stack = Array.isArray(p.stack) && p.stack[0]?.name ? p.stack : [{ name: "home" as const }];
  return { ...current, ...data, role, stack };
}

export const useMarket = create<MarketState>()(
  persist(
    (set, get) => ({
      ...seed(),
      role: "manager",
      stack: [{ name: "home" }],
      setRole: (role) => set({ role, stack: [{ name: "home" }] }),
      go: (screen) => set({ stack: [screen] }),
      push: (screen) => set({ stack: [...get().stack, screen] }),
      back: () => {
        const stack = get().stack;
        if (stack.length > 1) set({ stack: stack.slice(0, -1) });
      },
      reset: () => set({ ...seed(), role: get().role, stack: [{ name: "home" }] }),
      ownerName: (tariffId) => {
        const t = get().tariffs.find((x) => x.id === tariffId);
        return t ? ownerOf(get(), t) : "—";
      },
      tariffById: (id) => get().tariffs.find((t) => t.id === id),
      isBusy: (tariffId, date) => get().busy.some((b) => b.tariffId === tariffId && b.date === date),
      payoutBlock: (owner) => {
        const s = get();
        const banks = Array.isArray(s.banks) ? s.banks : [];
        const payouts = Array.isArray(s.payouts) ? s.payouts : [];
        const available = Number(owner === "manager" ? s.managerBalance : s.customerBalance) || 0;
        if (!banks.some((b) => b && b.owner === owner && b.iban)) return t().error.needIban;
        if (payouts.some((p) => p && p.owner === owner && p.status === "pending")) return t().error.payoutOpen;
        const weekAgo = Date.now() - 7 * 86400000;
        if (payouts.some((p) => p && p.owner === owner && p.status === "paid" && (p.createdAt ?? 0) > weekAgo)) {
          return t().error.payoutWeekly;
        }
        if (available < MIN_PAYOUT) return fill(t().error.minPayout, { min: money(MIN_PAYOUT) });
        return null;
      },
      setPublishMode: (channelId, mode, remindHours) => {
        set({
          channels: get().channels.map((c) =>
            c.id === channelId
              ? { ...c, publishMode: mode, remindHours: remindHours ?? c.remindHours }
              : c,
          ),
        });
        return null;
      },
      addTariff: (input) => {
        const name = input.name.trim();
        const channelId = input.channelId || null;
        const groupId = input.groupId || null;
        if (!name || input.durationHours <= 0 || input.price < 0) return t().error.tariffFields;
        if (!!channelId === !!groupId) return t().error.tariffOwner ?? "کانال یا مجموعه را انتخاب کنید";
        const s = get();
        if (channelId && !s.channels.some((c) => c.id === channelId)) return t().error.channelMissing;
        if (groupId && !s.groups.some((g) => g.id === groupId)) return t().error.groupMissing;
        const id = s.nextId;
        set({
          nextId: id + 1,
          tariffs: [
            {
              id,
              channelId,
              groupId,
              name: name.slice(0, 100),
              startHour: input.startHour,
              durationHours: input.durationHours,
              price: input.price,
              isActive: true,
            },
            ...s.tariffs,
          ],
        });
        return null;
      },
      markOnboarded: (role) => {
        set({ onboarded: { ...(get().onboarded || {}), [role]: true } });
      },
      updateTariff: (input) => {
        const name = input.name.trim();
        if (!name || input.durationHours <= 0 || input.price < 0) return t().error.tariffFields;
        const row = get().tariffs.find((x) => x.id === input.id);
        if (!row) return t().error.tariffMissing;
        set({
          tariffs: get().tariffs.map((x) =>
            x.id === input.id
              ? {
                  ...x,
                  name: name.slice(0, 100),
                  startHour: input.startHour,
                  durationHours: input.durationHours,
                  price: input.price,
                }
              : x,
          ),
        });
        return null;
      },
      removeTariff: (id) => {
        const row = get().tariffs.find((x) => x.id === id);
        if (!row) return t().error.tariffMissing;
        set({
          tariffs: get().tariffs.filter((x) => x.id !== id),
          busy: get().busy.filter((b) => b.tariffId !== id),
        });
        return null;
      },
      updateChannel: (channelId, name) => {
        const n = name.trim();
        if (!n) return t().error.needChannelName;
        if (!get().channels.some((c) => c.id === channelId)) return t().error.channelMissing;
        set({
          channels: get().channels.map((c) => (c.id === channelId ? { ...c, name: n.slice(0, 200) } : c)),
        });
        return null;
      },
      removeChannel: (channelId) => {
        if (!get().channels.some((c) => c.id === channelId)) return t().error.channelMissing;
        const drop = new Set(get().tariffs.filter((x) => x.channelId === channelId).map((x) => x.id));
        set({
          channels: get().channels.filter((c) => c.id !== channelId),
          tariffs: get().tariffs.filter((x) => x.channelId !== channelId),
          busy: get().busy.filter((b) => !drop.has(b.tariffId)),
          calendarByTariff: Object.fromEntries(
            Object.entries(get().calendarByTariff).filter(([id]) => !drop.has(Number(id))),
          ),
        });
        return null;
      },
      loadCalendar: async (tariffId, asCustomer) => {
        // demo: derive from busy
        const busy = get().busy.filter((b) => b.tariffId === tariffId);
        const days: CalDay[] = [];
        const today = new Date();
        for (let i = 0; i < 14; i++) {
          const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() + i, 12);
          const iso = d.toISOString().slice(0, 10);
          const slot = busy.find((b) => b.date === iso);
          const status = slot ? (slot.manual ? "full" : "full") : "free";
          days.push({ date: iso, status, why: slot ? "پر است" : "", free: !slot });
        }
        set({
          calendarByTariff: { ...(get().calendarByTariff || {}), [tariffId]: days },
        });
        return null;
      },
      calendarDays: (tariffId) => (get().calendarByTariff || {})[tariffId] ?? [],
      searchCatalog: async (_q, _readyOnly) => null,
      addGroup: (name, channelIds) => {
        const n = name.trim();
        if (!n || !channelIds.length) return t().error.groupFields ?? "نام و کانال‌ها لازم است";
        const id = get().nextId;
        set({
          nextId: id + 1,
          groups: [{ id, name: n.slice(0, 200), channelIds: [...channelIds] }, ...get().groups],
        });
        return null;
      },
      updateGroup: (groupId, name, channelIds) => {
        const n = name.trim();
        if (!get().groups.some((g) => g.id === groupId)) return t().error.groupMissing;
        if (!n || !channelIds.length) return t().error.groupFields ?? "نام و کانال‌ها لازم است";
        set({
          groups: get().groups.map((g) =>
            g.id === groupId ? { ...g, name: n.slice(0, 200), channelIds: [...channelIds] } : g,
          ),
        });
        return null;
      },
      removeGroup: (groupId) => {
        if (!get().groups.some((g) => g.id === groupId)) return t().error.groupMissing;
        set({
          groups: get().groups.filter((g) => g.id !== groupId),
          tariffs: get().tariffs.filter((x) => x.groupId !== groupId),
        });
        return null;
      },

      toggleTariff: (id) => {
        set({
          tariffs: get().tariffs.map((t) => (t.id === id ? { ...t, isActive: !t.isActive } : t)),
        });
        return null;
      },
      decideItem: (itemId, approve) => {
        const s = get();
        const item = s.items.find((i) => i.id === itemId);
        if (!item || item.managerStatus !== "pending") return t().error.notPending;
        const items = s.items.map((i) =>
          i.id === itemId ? { ...i, managerStatus: approve ? ("approved" as const) : ("rejected" as const) } : i,
        );
        const orders = finishOrder(s.orders, items, item.orderId);
        set({ items, orders });
        return null;
      },
      toggleBusy: (tariffId, date) => {
        const s = get();
        const slot = s.busy.find((b) => b.tariffId === tariffId && b.date === date);
        if (!slot) {
          const id = s.nextId;
          set({ nextId: id + 1, busy: [...s.busy, { id, tariffId, date, manual: true }] });
          return null;
        }
        if (!slot.manual) return t().error.busyLocked;
        set({ busy: s.busy.filter((b) => b.id !== slot.id) });
        return null;
      },
      clearBusy: (slotId) => {
        const slot = get().busy.find((b) => b.id === slotId);
        if (!slot?.manual) return t().error.notManual;
        set({ busy: get().busy.filter((b) => b.id !== slotId) });
        return null;
      },
      addToCart: (tariffId, date) => {
        const s = get();
        const tariff = s.tariffs.find((x) => x.id === tariffId);
        if (!tariff || !tariff.isActive) return t().error.tariffOff;
        if (s.busy.some((b) => b.tariffId === tariffId && b.date === date)) return t().error.slotFull;
        if (s.cart.some((c) => c.tariffId === tariffId && c.date === date)) return t().error.alreadyInCart;
        const id = s.nextId;
        set({ nextId: id + 1, cart: [...s.cart, { id, tariffId, date }] });
        return null;
      },
      removeCart: (itemId) => {
        set({ cart: get().cart.filter((c) => c.id !== itemId) });
        return null;
      },
      useBanner: (bannerId) => {
        const b = get().banners.find((x) => x.id === bannerId);
        if (!b?.fromLinkbank || b.stage !== "ready") return t().error.bannerNotReady;
        set({ selectedBannerId: bannerId });
        return null;
      },
      renameBanner: (bannerId, title) => {
        const name = title.trim();
        if (!name) return t().error.bannerName;
        set({
          banners: get().banners.map((b) => (b.id === bannerId ? { ...b, title: name.slice(0, 80) } : b)),
        });
        return null;
      },
      submitBanner: (input) => {
        const caption = input.caption.trim();
        const title = (input.title.trim() || caption.split("\n")[0] || "").slice(0, 80);
        if (caption.length < 12) return t().error.captionShort;
        if (!input.mediaUrl) return t().error.needMedia;
        if (hasBanned(caption) || hasBanned(title)) return t().error.banned;
        const s = get();
        const fee = s.banners.some((b) => b.fromLinkbank) ? BANNER_FEE : 0;
        if (fee > 0 && s.customerBalance < fee) return t().error.bannerFeeBalance;
        const id = s.nextId;
        const banner: Banner = {
          id,
          title: title || t().common.untitledBanner,
          caption: caption.slice(0, 800),
          fromLinkbank: false,
          mediaKind: input.mediaKind,
          mediaUrl: input.mediaUrl,
          posterUrl: input.posterUrl || input.mediaUrl,
          stage: "pending",
          rejectReason: "",
        };
        const req: BannerReq = {
          id: id + 1,
          customerLabel: "904412",
          title: banner.title,
          caption: banner.caption,
          fee,
          status: "pending",
          bannerId: banner.id,
          mediaKind: banner.mediaKind,
          mediaUrl: banner.mediaUrl,
          posterUrl: banner.posterUrl,
          rejectReason: "",
        };
        set({
          nextId: id + (fee ? 3 : 2),
          customerBalance: s.customerBalance - fee,
          banners: [banner, ...s.banners],
          bannerReqs: [req, ...s.bannerReqs],
          ledger:
            fee > 0
              ? [
                  {
                    id: id + 2,
                    owner: "customer",
                    amount: -fee,
                    kind: "spend",
                    note: t().note.bannerFee,
                    at: Date.now(),
                  },
                  ...(s.ledger ?? []),
                ]
              : s.ledger,
        });
        return null;
      },
      claimReference: (index) => {
        const post = referencePosts()[index];
        if (!post) return t().error.postMissing;
        const s = get();
        if (s.banners.some((b) => b.fromLinkbank && b.title === post.title)) return t().error.alreadyClaimed;
        const id = s.nextId;
        set({
          nextId: id + 1,
          selectedBannerId: id,
          banners: [
            {
              id,
              title: post.title,
              caption: post.caption,
              fromLinkbank: true,
              mediaKind: post.mediaKind,
              mediaUrl: post.mediaUrl,
              posterUrl: post.posterUrl,
              stage: "ready",
              rejectReason: "",
            },
            ...s.banners,
          ],
        });
        return null;
      },
      resubmitBanner: (bannerId, caption) => {
        const text = caption.trim();
        if (text.length < 12) return t().error.captionLonger;
        if (hasBanned(text)) return t().error.banned;
        const s = get();
        const banner = s.banners.find((b) => b.id === bannerId);
        if (!banner || banner.stage !== "rejected") return t().error.onlyRejected;
        const id = s.nextId;
        set({
          nextId: id + 1,
          banners: s.banners.map((b) =>
            b.id === bannerId
              ? { ...b, caption: text.slice(0, 800), stage: "pending" as const, rejectReason: "", fromLinkbank: false }
              : b,
          ),
          bannerReqs: [
            {
              id,
              customerLabel: "904412",
              title: banner.title,
              caption: text.slice(0, 800),
              fee: 0,
              status: "pending" as const,
              bannerId,
              mediaKind: banner.mediaKind,
              mediaUrl: banner.mediaUrl,
              posterUrl: banner.posterUrl,
              rejectReason: "",
            },
            ...s.bannerReqs,
          ],
        });
        return null;
      },
      reviseBanner: (bannerId, title, caption) => {
        const text = caption.trim();
        const name = title.trim();
        if (name.length < 2) return t().error.needTitle;
        if (text.length < 12) return t().error.captionLonger;
        if (hasBanned(text) || hasBanned(name)) return t().error.banned;
        const s = get();
        const banner = s.banners.find((b) => b.id === bannerId);
        if (!banner) return t().error.bannerMissing;
        const next = { ...banner, title: name.slice(0, 80), caption: text.slice(0, 800) };
        if (banner.stage === "pending") {
          set({
            banners: s.banners.map((b) => (b.id === bannerId ? next : b)),
            bannerReqs: s.bannerReqs.map((r) =>
              r.bannerId === bannerId && r.status === "pending" ? { ...r, title: next.title, caption: next.caption } : r,
            ),
          });
          return null;
        }
        const id = s.nextId;
        set({
          nextId: id + 1,
          selectedBannerId: s.selectedBannerId === bannerId ? null : s.selectedBannerId,
          banners: s.banners.map((b) =>
            b.id === bannerId ? { ...next, stage: "pending" as const, fromLinkbank: false, rejectReason: "" } : b,
          ),
          bannerReqs: [
            {
              id,
              customerLabel: "904412",
              title: next.title,
              caption: next.caption,
              fee: 0,
              status: "pending" as const,
              bannerId,
              mediaKind: banner.mediaKind,
              mediaUrl: banner.mediaUrl,
              posterUrl: banner.posterUrl,
              rejectReason: "",
            },
            ...s.bannerReqs,
          ],
        });
        return null;
      },
      removeBanner: (bannerId) => {
        const s = get();
        if (!s.banners.some((b) => b.id === bannerId)) return t().error.bannerMissing;
        set({
          banners: s.banners.filter((b) => b.id !== bannerId),
          bannerReqs: s.bannerReqs.filter((r) => !(r.bannerId === bannerId && r.status === "pending")),
          selectedBannerId: s.selectedBannerId === bannerId ? null : s.selectedBannerId,
        });
        return null;
      },
      suggestTime: (itemId, date) => {
        const s = get();
        const item = s.items.find((i) => i.id === itemId);
        if (!item || (item.managerStatus !== "pending" && item.managerStatus !== "edited")) {
          return t().error.timeLocked;
        }
        if (date === item.date) return t().error.sameDay;
        if (s.busy.some((b) => b.tariffId === item.tariffId && b.date === date)) return t().error.dayFull;
        const items = s.items.map((i) =>
          i.id === itemId ? { ...i, managerStatus: "edited" as const, proposedDate: date } : i,
        );
        set({ items, orders: finishOrder(s.orders, items, item.orderId) });
        return null;
      },
      answerTime: (itemId, accept) => {
        const s = get();
        const item = s.items.find((i) => i.id === itemId);
        if (!item || item.managerStatus !== "edited" || !item.proposedDate) return t().error.noProposal;
        const released = s.busy.filter((b) => !(b.tariffId === item.tariffId && b.date === item.date && !b.manual));
        if (accept) {
          const id = s.nextId;
          const items = s.items.map((i) =>
            i.id === itemId
              ? { ...i, date: item.proposedDate, managerStatus: "approved" as const, proposedDate: "" }
              : i,
          );
          set({
            nextId: id + 1,
            busy: [...released, { id, tariffId: item.tariffId, date: item.proposedDate, manual: false }],
            items,
            orders: finishOrder(s.orders, items, item.orderId),
          });
          return null;
        }
        const items = s.items.map((i) =>
          i.id === itemId ? { ...i, managerStatus: "customer_declined" as const, proposedDate: "" } : i,
        );
        set({ busy: released, items, orders: finishOrder(s.orders, items, item.orderId) });
        return null;
      },
      checkout: () => {
        const s = get();
        if (!s.cart.length) return t().error.cartEmpty;
        const banner = s.banners.find((b) => b.id === s.selectedBannerId);
        if (!banner?.fromLinkbank) return t().error.needReference;
        for (const line of s.cart) {
          if (s.busy.some((b) => b.tariffId === line.tariffId && b.date === line.date)) return t().error.slotFull;
        }
        let next = s.nextId;
        const orderId = next++;
        const newItems: OrderItem[] = s.cart.map((line) => {
          const t = s.tariffs.find((x) => x.id === line.tariffId);
          return {
            id: next++,
            orderId,
            tariffId: line.tariffId,
            date: line.date,
            price: t?.price ?? 0,
            managerStatus: "pending",
            execution: "none",
            publishedLink: "",
            proposedDate: "",
          };
        });
        const total = newItems.reduce((a, i) => a + i.price, 0);
        const newBusy: Busy[] = newItems.map((i) => ({ id: next++, tariffId: i.tariffId, date: i.date, manual: false }));
        const order: Order = {
          id: orderId,
          status: "waiting_managers",
          created: isoDate(new Date()),
          bannerTitle: banner.title,
          total,
        };
        set({
          nextId: next,
          orders: [order, ...s.orders],
          items: [...newItems, ...s.items],
          busy: [...s.busy, ...newBusy],
          cart: [],
        });
        return null;
      },
      addBank: (owner, iban, holder) => {
        const name = holder.trim();
        const clean = iban.replace(/\s/g, "").toUpperCase();
        if (!name) return t().error.needHolder;
        if (!ibanOk(clean)) return t().error.badIban;
        const id = get().nextId;
        set({
          nextId: id + 1,
          banks: [...get().banks, { id, owner, holder: name, iban: clean }],
        });
        return null;
      },
      cancelOrder: (orderId) => {
        const order = get().orders.find((o) => o.id === orderId);
        if (!order) return "سفارش پیدا نشد";
        if (order.status === "cancelled") return null;
        const cancellable = ["waiting_banner", "waiting_managers", "waiting_customer_confirm", "waiting_payment"].includes(
          order.status,
        );
        if (!cancellable) return "این سفارش قابل لغو نیست";
        set({
          orders: get().orders.map((o) => (o.id === orderId ? { ...o, status: "cancelled" as const } : o)),
          items: get().items.map((i) =>
            i.orderId === orderId
              ? { ...i, managerStatus: "customer_declined" as const, execution: "cancelled" as const }
              : i,
          ),
        });
        return null;
      },
      requestPayout: (owner, bankId) => {
        const block = get().payoutBlock(owner);
        if (block) return block;
        const bank = get().banks.find((b) => b.id === bankId && b.owner === owner);
        if (!bank) return t().error.ibanMissing;
        const amount = owner === "manager" ? get().managerBalance : get().customerBalance;
        const id = get().nextId;
        const entry: LedgerEntry = {
          id: id + 1,
          owner,
          amount: -amount,
          kind: "payout_lock",
          note: fill(t().note.payoutTo, { holder: bank.holder }),
          at: Date.now(),
        };
        set({
          nextId: id + 2,
          managerBalance: owner === "manager" ? 0 : get().managerBalance,
          customerBalance: owner === "customer" ? 0 : get().customerBalance,
          ledger: [entry, ...(get().ledger ?? [])],
          payouts: [
            {
              id,
              owner,
              amount,
              status: "pending",
              holder: bank.holder,
              iban: bank.iban,
              createdAt: Date.now(),
            },
            ...get().payouts,
          ],
        });
        return null;
      },
      topUp: (owner, amount, note) => {
        const value = Math.round(amount);
        if (value < MIN_TOPUP) return fill(t().error.minTopup, { min: money(MIN_TOPUP) });
        const id = get().nextId;
        set({
          nextId: id + 1,
          managerBalance: owner === "manager" ? get().managerBalance + value : get().managerBalance,
          customerBalance: owner === "customer" ? get().customerBalance + value : get().customerBalance,
          ledger: [
            { id, owner, amount: value, kind: "topup", note: note || t().note.topup, at: Date.now() },
            ...(get().ledger ?? []),
          ],
        });
        return null;
      },
      payOrder: (orderId, via = "wallet") => {
        const s = get();
        const order = s.orders.find((o) => o.id === orderId);
        if (!order || order.status !== "waiting_payment") return t().error.notPayable;
        const lines = s.items.filter((i) => i.orderId === orderId && i.managerStatus === "approved");
        const total = lines.reduce((a, i) => a + i.price, 0);
        if (total <= 0) return t().error.badTotal;
        if (via !== "bale" && s.customerBalance < total) return t().error.lowBalance;
        const id = s.nextId;
        const items = s.items.map((i) =>
          lines.some((l) => l.id === i.id) ? { ...i, execution: "paid" as const } : i,
        );
        set({
          nextId: id + 1,
          customerBalance: via === "bale" ? s.customerBalance : s.customerBalance - total,
          items,
          orders: finishOrder(s.orders, items, orderId),
          ledger: [
            {
              id,
              owner: "customer",
              amount: -total,
              kind: "escrow",
              note: via === "bale" ? fill(t().note.payBale, { id: faNum(orderId) }) : fill(t().note.escrow, { id: faNum(orderId) }),
              at: Date.now(),
            },
            ...(s.ledger ?? []),
          ],
        });
        return null;
      },
      publishItem: (itemId) => {
        const s = get();
        const item = s.items.find((i) => i.id === itemId);
        if (!item || item.execution !== "paid") return t().error.notPublishable;
        const tariff = s.tariffs.find((x) => x.id === item.tariffId);
        const ch = tariff?.channelId ? s.channels.find((c) => c.id === tariff.channelId) : s.channels[0];
        const link = `https://ble.ir/${(ch?.link ?? "channel").replace(/^.*\//, "")}/${item.id}`;
        set({
          items: s.items.map((i) =>
            i.id === itemId ? { ...i, execution: "awaiting_customer_confirm" as const, publishedLink: link } : i,
          ),
        });
        return null;
      },
      confirmPublish: (itemId) => releaseItem(get, set, itemId, false),
      openDispute: (itemId, note) => {
        const text = note.trim();
        if (text.length < 4) return t().error.disputeNote;
        const s = get();
        const item = s.items.find((i) => i.id === itemId);
        if (!item || (item.execution !== "paid" && item.execution !== "awaiting_customer_confirm")) {
          return t().error.disputeClosed;
        }
        if ((s.disputes ?? []).some((d) => d.itemId === itemId && d.status === "open")) return t().error.disputeOpen;
        const id = s.nextId;
        set({
          nextId: id + 1,
          items: s.items.map((i) => (i.id === itemId ? { ...i, execution: "awaiting_operator" as const } : i)),
          disputes: [{ id, itemId, note: text.slice(0, 240), status: "open" }, ...(s.disputes ?? [])],
        });
        return null;
      },
      resolveDispute: (disputeId, refund) => {
        const s = get();
        const d = (s.disputes ?? []).find((x) => x.id === disputeId && x.status === "open");
        if (!d) return t().error.disputeMissing;
        if (refund) {
          const item = s.items.find((i) => i.id === d.itemId);
          if (!item) return t().error.itemMissing;
          const id = s.nextId;
          const items = s.items.map((i) =>
            i.id === item.id ? { ...i, execution: "cancelled" as const } : i,
          );
          set({
            nextId: id + 1,
            customerBalance: s.customerBalance + item.price,
            items,
            orders: finishOrder(s.orders, items, item.orderId),
            disputes: s.disputes.map((x) => (x.id === disputeId ? { ...x, status: "refunded" as const } : x)),
            ledger: [
              { id, owner: "customer", amount: item.price, kind: "refund", note: fill(t().note.disputeRefund, { id: faNum(disputeId) }), at: Date.now() },
              ...(s.ledger ?? []),
            ],
          });
          return null;
        }
        const err = releaseItem(get, set, d.itemId, true);
        if (err) return err;
        set({
          disputes: get().disputes.map((x) => (x.id === disputeId ? { ...x, status: "released" as const } : x)),
        });
        return null;
      },
      rateChannel: (channelId, stars) => {
        const score = Math.round(stars);
        if (score < 1 || score > 5) return t().error.badScore;
        const ch = get().channels.find((c) => c.id === channelId);
        if (!ch) return t().error.channelMissing;
        const count = (ch.ratingCount ?? 0) + 1;
        const rating = Math.round((((ch.rating ?? 0) * (ch.ratingCount ?? 0) + score) / count) * 10) / 10;
        set({
          channels: get().channels.map((c) => (c.id === channelId ? { ...c, rating, ratingCount: count } : c)),
        });
        return null;
      },
      toggleFavorite: (tariffId) => {
        const cur = get().favorites ?? [];
        set({
          favorites: cur.includes(tariffId) ? cur.filter((id) => id !== tariffId) : [...cur, tariffId],
        });
        return null;
      },
      refreshChannelStats: (force) => {
        const now = Date.now();
        const today = isoDate(new Date());
        let changed = false;
        const channels = get().channels.map((ch) => {
          const snaps = ch.snapshots?.length ? ch.snapshots : buildSnapshots(ch.members || 0, ch.avgViews || 0, ch.id);
          const last = snaps[snaps.length - 1];
          if (!last) return ch;
          const fresh = !force && today === isoDate(new Date(last.at)) && now - (ch.statsAt || 0) < 6 * 3600 * 1000;
          if (fresh) return snaps === ch.snapshots ? ch : { ...ch, snapshots: snaps };
          const bump = 1 + (0.003 + (ch.id % 5) * 0.001);
          const members = Math.max(1, Math.round(last.members * bump));
          const views = Math.max(1, Math.round(last.views * (bump + 0.004)));
          const posts = 1 + ((ch.id + new Date().getDate()) % 4);
          const forwards = (ch.id + posts) % 4;
          const point: ChannelSnapshot = {
            at: now,
            members,
            views,
            dailyReach: Math.round(views * Math.min(posts, 3) * 0.62),
            posts,
            forwards,
          };
          const sameDay = isoDate(new Date(last.at)) === today;
          const snapshots = (sameDay ? [...snaps.slice(0, -1), point] : [...snaps, point]).slice(-30);
          changed = true;
          return { ...ch, members, avgViews: views, snapshots, statsAt: now, language: ch.language || "fa" };
        });
        if (changed || force) {
          set({
            channels,
            linkyar: { connected: true, checkedAt: now, error: "" },
          });
        }
      },
      decideBanner: (requestId, approve, reason = "") => {
        const req = get().bannerReqs.find((r) => r.id === requestId);
        if (!req || req.status !== "pending") return t().error.notPending;
        const why = reason.trim();
        if (!approve && why.length < 4) return t().error.rejectReason;
        const s = get();
        let banners = s.banners;
        let nextId = s.nextId;
        let bannerId = req.bannerId;
        if (approve && !bannerId) {
          bannerId = nextId++;
          banners = [
            {
              id: bannerId,
              title: req.title,
              caption: req.caption,
              fromLinkbank: true,
              mediaKind: req.mediaKind,
              mediaUrl: req.mediaUrl,
              posterUrl: req.posterUrl,
              stage: "ready",
              rejectReason: "",
            },
            ...banners,
          ];
        }
        set({
          nextId,
          bannerReqs: s.bannerReqs.map((r) =>
            r.id === requestId
              ? { ...r, status: approve ? "approved" : "rejected", rejectReason: approve ? "" : why, bannerId }
              : r,
          ),
          banners: banners.map((b) => {
            if (b.id !== bannerId) return b;
            if (approve) return { ...b, fromLinkbank: true, stage: "ready" as const, rejectReason: "" };
            return { ...b, fromLinkbank: false, stage: "rejected" as const, rejectReason: why };
          }),
        });
        return null;
      },
      markPayoutsPaid: () => {
        const pending = get().payouts.some((p) => p.status === "pending");
        if (!pending) return t().error.noPayouts;
        set({
          payouts: get().payouts.map((p) => (p.status === "pending" ? { ...p, status: "paid" } : p)),
        });
        return null;
      },
      payoutFile: () =>
        get()
          .payouts.filter((p) => p.status === "pending")
          .map((p) => `${p.amount * 10},${p.iban},,${p.holder}`)
          .join("\n"),
    }),
    { name: "linkbank-demo-v3", skipHydration: true, version: 3, merge: mergeMarket },
  ),
);

export function dayLabel(iso: string): string {
  return formatJalaliIso(iso);
}

export function screenTitle(_role: Role, name: Screen["name"]): string {
  const map = t().screen as Record<string, string>;
  return map[name] ?? map.fallback;
}
