// Textes de l'application : copy/fr.json est la source unique. t("ui.jusqua", { montant: 20000 }) -> « Jusqu'à 20 000 DH ».
import fr from "../../copy/fr.json";

const TEXTS = fr as Record<string, string>;
/** Variables exprimées en dirhams. */
const MONEY = new Set(["montant", "fixed", "min", "amount", "you", "insurer"]);  // « max » : formaté par l'appelant (DH ou coefficient)

export type Var = string | number | null | undefined;

/** « 20 000 DH » : espace insécable entre les milliers, arrondi à l'unité. */
export const dh = (v: number) => `${String(Math.round(v)).replace(/\B(?=(\d{3})+(?!\d))/g, " ")} DH`;
/** « 5 » ou « 2,5 » (virgule décimale). */
export const num = (v: number) => String(Math.round(v * 100) / 100).replace(".", ",");

export const has = (key: string) => key in TEXTS;

export function t(key: string, vars: Record<string, Var> = {}): string {
  const raw = TEXTS[key] ?? key;
  return raw
    .replace(/\{(\w+)\}/g, (_, n: string) => {
      const v = vars[n];
      if (v === null || v === undefined) return "";
      if (typeof v === "number") return MONEY.has(n) ? dh(v) : num(v);
      return v;
    })
    .replace(/\s+([,.])/g, "$1")
    .replace(/\s{2,}/g, " ")
    .trim();
}

/** Toutes les variables d'un texte ont une valeur : sinon l'élément n'est pas affiché. */
export function complete(key: string, vars: Record<string, Var>): boolean {
  const names = [...(TEXTS[key] ?? "").matchAll(/\{(\w+)\}/g)].map((m) => m[1]);
  return names.every((n) => vars[n] !== null && vars[n] !== undefined);
}
