import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import type { Excerpt, Row, Status } from "../types";
import { Check, Close, Cross, Info } from "../icons";
import { t } from "../copy";
import { ChipList, CheckList, ExactTextLink, HaveChip, MoneyPair, NoteList, Unclassified, gIcon } from "./visual";

/** Un seul vocabulaire de statut pour toute l'application. */
export const STATUS: Record<Status, { word: string; short: string }> = {
  covered: { word: "Couvert", short: "Couvert" },
  partial: { word: "Couvert sous condition", short: "Sous condition" },
  not_covered: { word: "Non couvert", short: "Non couvert" },
  unknown: { word: "À vérifier", short: "À vérifier" },
  none: { word: "Non concerné", short: "—" },
};

export function StatusPill({ status, text }: { status: Status; text?: string }) {
  return (
    <span className={`pill st-${status}`}>
      {status === "covered" ? <Check size={13} /> : status === "not_covered" ? <Cross size={13} /> : <Info size={13} />}
      {text ?? STATUS[status].short}
    </span>
  );
}

export function Spinner({ label }: { label?: string }) {
  return <div className="spinner" role="status"><span className="spin" aria-hidden />{label}</div>;
}

/** Panneau qui monte du bas de l'écran (mobile) ; fenêtre centrée sur grand écran. */
export function Sheet({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", k);
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", k); document.body.style.overflow = ""; };
  }, [onClose]);
  return (
    <div className="sheet-back" onClick={onClose}>
      <div className="sheet" role="dialog" aria-modal aria-label={title} onClick={(e) => e.stopPropagation()}>
        <div className="sheet-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Fermer"><Close size={20} /></button>
        </div>
        <div className="sheet-body">{children}</div>
      </div>
    </div>
  );
}

export function KV({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="kv">
      {rows.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
    </dl>
  );
}

/** Référence d'un extrait des Conditions Générales (article ou page). */
export function Ref({ r }: { r?: string | null }) {
  return r ? <small className="ref-tag">CG · {r}</small> : null;
}

/** Liste d'extraits des CG (texte tel qu'imprimé) ; chaque élément peut porter son article. */
export function Bullets({ items, tone }: { items: (string | Excerpt)[]; tone?: "yes" | "no" | "cond" }) {
  if (!items.length) return null;
  return (
    <ul className={`bullets excerpt ${tone ?? ""}`}>
      {items.map((x) => {
        const e = typeof x === "string" ? { text: x } : x;
        return <li key={e.text}>{e.text}{e.ref && <> <Ref r={e.ref} /></>}</li>;
      })}
    </ul>
  );
}

/** Message quand les CG de l'assureur ne sont pas dans l'application : on n'affiche rien d'autre que la CP. */
export function NoCG({ what = "ces informations" }: { what?: string }) {
  return <p className="muted small">Conditions Générales de votre assureur non intégrées : {what} ne peuvent pas être affichées.</p>;
}

/** Fiche d'une garantie : puces « ce qui est payé » / « ce qui n'est pas payé », conditions, « bon à savoir »,
 *  clauses non classées (verbatim) et texte exact. Aucune phrase des CG visible par défaut. */
export function GuaranteeDetail({ row }: { row: Row }) {
  const empty = !row.cover_codes?.length && !row.exclusion_codes?.length && !row.condition_codes?.length
    && !row.note_codes?.length && !row.unclassified?.length && !row.source;
  return (
    <div className="gdetail">
      <ChipList items={row.cover_codes} kind="cover" title={t("ui.couvert")} />
      <ChipList items={row.exclusion_codes} kind="exclusion" title={t("ui.pas_couvert")} />
      <CheckList items={row.condition_codes} />
      <NoteList items={row.note_codes} />
      <Unclassified items={row.unclassified} />
      <ExactTextLink source={row.source} />
      {empty && !row.plain && <NoCG what="les détails de cette garantie" />}
    </div>
  );
}

/** Recharge le dossier (écouté par App). */
export const reloadDossier = () => window.dispatchEvent(new Event("dossier:reload"));

/** Classement proposé par l'IA : la citation des CG qui le justifie, puis « Correct ? ». */
export function AiBox({ row, insurerId }: { row: Row; insurerId?: string }) {
  const [busy, setBusy] = useState(false);
  if (!row.ai) return null;
  const decide = (d: "confirm" | "reject") => {
    setBusy(true);
    api.decideClassification(row.ai!.label, d, insurerId).then(reloadDossier).finally(() => setBusy(false));
  };
  return (
    <div className="ai-box">
      <p className="small"><b>Classé automatiquement</b> sous « {row.ai.guarantee} », d'après vos CG.</p>
      {row.plain && <ExactTextLink source={{ doc: "CG", ref: row.ref || null, texts: [row.plain] }} />}
      {row.ai.status === "suggested" ? (
        <div className="ai-actions">
          <span className="small">Correct ?</span>
          <button className="pill-btn" disabled={busy} onClick={() => decide("confirm")}>Oui</button>
          <button className="pill-btn no" disabled={busy} onClick={() => decide("reject")}>Non</button>
        </div>
      ) : <p className="muted small">Classement confirmé.</p>}
    </div>
  );
}

/** Ligne de garantie dépliable : nom simple, ce qu'elle couvre en une ligne, « Vous l'avez », chiffres, puis le détail. */
export function GuaranteeRow({ row, open: initial = false }: { row: Row; open?: boolean }) {
  const [open, setOpen] = useState(initial);
  const G = gIcon(row.gcode);
  const named = !!row.gcode && !row.ai;
  return (
    <div className={"grow" + (open ? " open" : "")}>
      <button className="grow-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="g-ico"><G size={20} /></span>
        <span className="grow-title">
          <b>{named ? t(`g.${row.gcode}.title`) : row.title}</b>
          {named && <span className="muted">{t(`g.${row.gcode}.one`)}</span>}
          {named && row.cp_label && <small className="muted">{row.cp_label}</small>}
        </span>
        {row.subscribed || row.status !== "unknown" ? <HaveChip subscribed={row.subscribed} /> : <StatusPill status="unknown" text={t("ui.a_verifier")} />}
      </button>
      {row.subscribed && <MoneyPair plafond={row.plafond_dh} franchise={row.franchise} />}
      {row.also?.map((a) => <p key={a.label} className="muted small">Autre ligne de la CP : {a.label}{a.limit ? ` · ${a.limit}` : ""}</p>)}
      {row.to_check && <p className="warn small">Montant lu de deux façons différentes : vérifiez-le sur votre CP.</p>}
      {row.ai ? <AiBox row={row} /> : open && <GuaranteeDetail row={row} />}
    </div>
  );
}

export const dateFr = (iso?: string | null) => {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
};
