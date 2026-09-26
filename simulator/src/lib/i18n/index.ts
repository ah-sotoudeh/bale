import { fa } from "./fa";

type Widen<T> = T extends string
  ? string
  : T extends readonly (infer U)[]
    ? readonly Widen<U>[]
    : T extends object
      ? { readonly [K in keyof T]: Widen<T[K]> }
      : T;

/** شکل پروندهٔ ترجمه. زبان تازه باید همین کلیدها را داشته باشد. */
export type Copy = Widen<typeof fa>;

const bundles: Record<string, Copy> = { fa };
let active = "fa";

/** زبان تازه را بعد از ترجمهٔ یک کپی از fa.ts این‌جا ثبت کنید. */
export function registerLocale(code: string, messages: Copy) {
  bundles[code] = messages;
}

export function setLocale(code: string) {
  if (!bundles[code]) return false;
  active = code;
  return true;
}

export function getLocale() {
  return active;
}

export function t(): Copy {
  return bundles[active] ?? fa;
}

/** جاهای خالی {name} را پر می‌کند. کلید ناشناس را دست‌نخورده می‌گذارد. */
export function fill(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (all, key) => (Object.prototype.hasOwnProperty.call(vars, key) ? String(vars[key]) : all));
}
