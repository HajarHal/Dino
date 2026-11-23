// Composants des explications visuelles. Aucun texte ici : tout vient de copy/fr.json (t) ou des valeurs de la CP.
// Chaque élément ouvre sa source : le texte exact des CG (verbatim), l'article, la page et le PDF.
import { useState, type ReactNode } from "react";
import type { ClauseSource, CodedClause, Franchise, Tile } from "../types";
import { Car, Check, Clock, Cross, Doc, Flame, Glass, Info, Key, MapPin, Scale, Shield, Storm, Tow, Trend, User, Users, Wallet, Wheel } from "../icons";
import { complete, dh, num, t } from "../copy";
import { Sheet } from "./ui";

type Icon = (p: { size?: number }) => JSX.Element;
const ICONS: Record<string, Icon> = { users: Users, car: Car, user: User, trend: Trend, scale: Scale, wallet: Wallet };
/** Icône d'une garantie (code d'affichage). */
export const G_ICON: Record<string, Icon> = {
  RC: Users, DEFENSE_RECOURS: Scale, BRIS_GLACE: Glass, VOL: Key, VOL_ROUES: Key, VOL_RETRO_OPTIQUES: Key,
  INCENDIE: Flame, DTA: Car, DOMMAGES_COLLISION: Car, INONDATION: Storm, CAT_NAT: Storm, PROTECTION_CONDUCTEUR: Wheel,
  PROTECTION_PASSAGERS: Users, ASSISTANCE: Tow, PERTE_FINANCIERE: Wallet,
};
export const gIcon = (gcode?: string | null): Icon => (gcode && G_ICON[gcode]) || Shield;

/** Libellé de la source : « CG · Art. 10 et 40 · page 11 ». */
export function sourceLabel(s: ClauseSource): string {
  if (s.article && s.page) return t("ui.source", { doc: s.doc, article: s.article, page: s.page });
  if (s.page) return t("ui.source.ref", { doc: s.doc, ref: s.ref ?? "", page: s.page });
  return t("ui.source.nopage", { doc: s.doc, ref: s.ref ?? "" });
}

/** Contenu de la feuille « texte exact ». */
function SourceView({ s }: { s: ClauseSource }) {
  return (
    <div className="src-view">
      <p className="muted small">{sourceLabel(s)}</p>
      <ul className="verbatim">{s.texts.map((x, i) => <li key={i}>{x}</li>)}</ul>
      {s.url && <a className="btn-soft" href={s.url} target="_blank" rel="noreferrer"><Doc size={18} />{t("ui.ouvrir_pdf")}</a>}
    </div>
  );
}

/** Élément tappable qui ouvre son texte exact. Sans source : affiché, non tappable. */
export function Tap({ source, className, children }: { source?: ClauseSource | null; className?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  if (!source) return <span className={className}>{children}</span>;
  return (
    <>
      <button type="button" className={"tap " + (className ?? "")} onClick={() => setOpen(true)}>{children}</button>
      {open && <Sheet title={t("ui.texte_exact")} onClose={() => setOpen(false)}><SourceView s={source} /></Sheet>}
    </>
  );
}

/** 1. Lien « Lire le texte exact » + source. */
export function ExactTextLink({ source, label }: { source?: ClauseSource | null; label?: string }) {
  if (!source || !source.texts.length) return null;
  return (
    <p className="exact-link">
      <Tap source={source} className="link">{label ?? t("ui.texte_exact")}</Tap>
      <small className="muted"> · {sourceLabel(source)}</small>
    </p>
  );
}

/** 2. Puces vertes ✓ (cov.*) ou rouges × (ex.*). */
export function ChipList({ items, kind, title }: { items?: CodedClause[]; kind: "cover" | "exclusion"; title?: string }) {
  if (!items?.length) return null;
  const prefix = kind === "cover" ? "cov" : "ex";
  return (
    <div className="chip-block">
      {title && <h4 className={kind === "cover" ? "h-yes" : "h-no"}>{title}</h4>}
      <div className="chips">
        {items.map((c) => (
          <Tap key={c.code} source={c.source} className={`vchip ${kind}`}>
            {kind === "cover" ? <Check size={14} /> : <Cross size={14} />}{t(`${prefix}.${c.code}`)}
          </Tap>
        ))}
      </div>
    </div>
  );
}

/** « Bon à savoir » : une icône et une phrase par code (note.*). */
export function NoteList({ items }: { items?: CodedClause[] }) {
  if (!items?.length) return null;
  return (
    <div className="chip-block">
      <h4 className="h-cond">{t("ui.bon_a_savoir")}</h4>
      <ul className="notes-list">
        {items.map((n) => <li key={n.code}><Tap source={n.source}><Info size={16} /><span>{t(`note.${n.code}`)}</span></Tap></li>)}
      </ul>
    </div>
  );
}

/** Clauses qu'aucun code ne couvre : verbatim, dans un accordéon fermé. */
export function Unclassified({ items }: { items?: { text: string; source: ClauseSource }[] }) {
  if (!items?.length) return null;
  return (
    <details className="unclassified">
      <summary>{t("ui.autres_conditions")}</summary>
      <ul>{items.map((u, i) => <li key={i}><span className="excerpt">{u.text}</span><small>{sourceLabel(u.source)}</small></li>)}</ul>
    </details>
  );
}

/** Texte de franchise (f.*), ou null si la franchise n'est pas indiquée. */
export function franchiseText(f?: Franchise | null): string | null {
  if (!f) return null;
  const vars = {
    percent: f.percent, base: t(`f.base.${f.base}`), fixed: f.fixed, min: f.min, max: f.max != null ? dh(f.max) : null,
  };
  return complete(`f.${f.kind}`, vars) ? t(`f.${f.kind}`, vars) : null;
}

/** 3. Deux chiffres côte à côte : « Jusqu'à » et « Vous payez ». Une valeur absente n'est pas affichée. */
export function MoneyPair({ plafond, franchise }: { plafond?: number | null; franchise?: Franchise | null }) {
  const f = franchiseText(franchise);
  if (plafond == null && !f) return null;
  return (
    <div className="money-pair">
      {plafond != null && <span><small>{t("ui.jusqua", { montant: "" })}</small><b>{dh(plafond)}</b></span>}
      {f && <span><small>{t("ui.vous_payez")}</small><b className="f-text">{f.replace(/^Vous payez\s*/, "") || f}</b></span>}
    </div>
  );
}

/** Logique pure (même calcul que ica/explain.py franchise_split). */
export function franchiseSplit(amount: number, f: Franchise, plafond?: number | null): [number, number] {
  let you: number;
  if (f.kind === "NONE") you = 0;
  else if (f.kind === "FIXED") you = f.fixed ?? 0;
  else {
    you = (amount * (f.percent ?? 0)) / 100;
    if ((f.kind === "PERCENT_MIN" || f.kind === "PERCENT_MIN_MAX") && f.min != null) you = Math.max(you, f.min);
    if (f.kind === "PERCENT_MIN_MAX" && f.max != null) you = Math.min(you, f.max);
  }
  you = Math.min(you, amount);
  const insurer = plafond ? Math.min(amount - you, plafond) : amount - you;
  return [Math.round(you), Math.round(insurer)];
}

/** 4. « Pour 10 000 DH de dégâts : vous payez…, l'assureur… » + curseur. Rien si la base est inconnue. */
export function FranchiseExample({ franchise, plafond }: { franchise?: Franchise | null; plafond?: number | null }) {
  const start = Math.min(10000, plafond ?? 10000);
  const [a, setA] = useState(start);
  if (!franchise || franchise.kind === "NONE" || franchise.base === "UNKNOWN" || !plafond) return null;
  const amount = franchise.base === "VEHICLE_VALUE" ? plafond : a;
  const [you, insurer] = franchiseSplit(amount, franchise, plafond);
  return (
    <div className="calc">
      <p className="calc-line">{t("f.example", { amount, you, insurer })}</p>
      {franchise.base !== "VEHICLE_VALUE" && plafond > 1000 && (
        <input type="range" min={1000} max={plafond} step={500} value={a} onChange={(e) => setA(Number(e.target.value))}
          aria-label={t("f.example", { amount: a, you, insurer })} />
      )}
      <div className="calc-split">
        <span><small>{t("ui.vous_payez")}</small><b>{dh(you)}</b></span>
        <span className="ins"><small>{t("ui.assureur_paie")}</small><b>{dh(insurer)}</b></span>
      </div>
    </div>
  );
}

/** 5. Grille « qui paie quoi » : 2 à 4 tuiles. */
export function WhoPaysGrid({ tiles, title }: { tiles?: Tile[]; title?: string }) {
  if (!tiles?.length) return null;
  return (
    <div className="who">
      {title && <h4>{title}</h4>}
      <div className="who-grid">
        {tiles.map((x) => {
          const I = ICONS[x.icon] ?? Info;
          const vars = { ...x.vars, max: typeof x.vars.max === "number" ? num(x.vars.max) : x.vars.max };
          return (
            <Tap key={x.code + x.value_key} source={x.source} className="who-tile">
              <span className="wt-ico"><I size={20} /></span>
              <small>{t(x.label_key)}</small>
              <b>{t(x.value_key, vars)}</b>
              {x.sub_key && complete(x.sub_key, vars) && <small className="muted">{t(x.sub_key, vars)}</small>}
              {x.review && <i className="review">{t("ui.a_verifier")}</i>}
            </Tap>
          );
        })}
      </div>
    </div>
  );
}

/** 6. Coches « pour être payé, il faut » (cond.*). */
export function CheckList({ items }: { items?: CodedClause[] }) {
  if (!items?.length) return null;
  return (
    <div className="chip-block">
      <h4>{t("ui.il_faut")}</h4>
      <ul className="checklist">{items.map((c) => <li key={c.code}><Tap source={c.source}><Check size={16} /><span>{t(`cond.${c.code}`)}</span></Tap></li>)}</ul>
    </div>
  );
}

const unitText = (n: number, unit: string) => t(`unit.${unit}`, { n });

/** 7. Frise des délais, du plus court au plus long. */
export function DelayTimeline({ items }: { items: { code: string; n: number; unit: string; source: ClauseSource }[] }) {
  if (!items.length) return null;
  return (
    <div className="timeline">
      {items.map((d) => (
        <Tap key={d.code} source={d.source} className="milestone">
          <span className="dot" /><b>{unitText(d.n, d.unit)}</b><small>{t(`delay.${d.code}`)}</small>
        </Tap>
      ))}
    </div>
  );
}

/** 8. Étapes numérotées, avec le délai correspondant à droite. */
export function Steps({ items }: { items: { code: string; delay: { n: number; unit: string } | null; source: ClauseSource }[] }) {
  if (!items.length) return null;
  return (
    <ol className="vsteps">
      {items.map((s, i) => (
        <li key={s.code}>
          <Tap source={s.source} className="vstep">
            <span className="num">{i + 1}</span>
            <span className="vs-text"><b>{t(`step.${s.code}`)}</b><small>{t(`step.${s.code}.sub`)}</small></span>
            {s.delay && <span className="delay-chip"><Clock size={14} />{unitText(s.delay.n, s.delay.unit)}</span>}
          </Tap>
        </li>
      ))}
    </ol>
  );
}

/** 9. Durée du contrat : début -> aujourd'hui -> fin. */
export function ContractDurationBar({ start, end, today = new Date() }: { start?: string | null; end?: string | null; today?: Date }) {
  if (!start || !end) return null;
  const s = new Date(start).getTime(), e = new Date(end).getTime(), now = today.getTime();
  if (!(e > s)) return null;
  const pct = Math.max(0, Math.min(100, ((now - s) / (e - s)) * 100));
  const left = Math.ceil((e - now) / 86400000);
  const state = left < 0 ? "expired" : left < 30 ? "soon" : "ok";
  return (
    <div className={`duration ${state}`}>
      <div className="bar"><i style={{ width: `${pct}%` }} /></div>
      <p className="small">
        {state === "expired" ? <><Cross size={14} />{t("contract.expired")}</>
          : <>{state === "soon" ? <Info size={14} /> : <Check size={14} />}{t("contract.days_left", { n: left })}
            {state === "soon" && <b> · {t("contract.renew_soon")}</b>}</>}
      </p>
    </div>
  );
}

/** 10. Icône (i) qui affiche une aide (veh.*). */
export function InfoTip({ helpKey }: { helpKey: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="infotip">
      <button type="button" className="icon-btn small" aria-label={t(helpKey)} aria-expanded={open} onClick={() => setOpen(!open)}><Info size={16} /></button>
      {open && <small className="tip">{t(helpKey)}</small>}
    </span>
  );
}

/** Puce « pays couverts ». */
export function TerritoryChip({ territory }: { territory?: { code: string; source: ClauseSource } | null }) {
  if (!territory) return null;
  return <Tap source={territory.source} className="vchip terr"><MapPin size={14} />{t(`terr.${territory.code}`)}</Tap>;
}

/** Puce « Vous l'avez » / « Vous ne l'avez pas ». */
export function HaveChip({ subscribed }: { subscribed: boolean }) {
  return (
    <span className={`pill ${subscribed ? "st-covered" : "st-not_covered"}`}>
      {subscribed ? <Check size={13} /> : <Cross size={13} />}{t(subscribed ? "ui.vous_avez" : "ui.vous_avez_pas")}
    </span>
  );
}
