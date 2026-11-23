// Photo réelle du véhicule, avec une bulle par partie : nom, garantie, plafond, franchise.
// La photo est entourée d'une marge haute et basse où se placent les bulles (au-dessus des parties hautes,
// en dessous des parties basses), reliées par un trait au point posé sur la partie.
import { useMemo, useState } from "react";
import { t } from "../copy";
import { franchiseText } from "./visual";
import type { Part, Photo, View } from "../types";

const PRIORITY: Record<string, string[]> = {
  police: ["windshield", "mirrors", "headlights", "bodywork", "wheels", "front_bumper"],
  glass: ["windshield", "side_windows", "mirrors", "headlights"],
  theft: ["mirrors", "headlights", "wheels", "side_windows"],
  fire: ["windshield", "engine_mechanics", "bodywork", "wheels"],
  nature: ["windshield", "engine_mechanics", "bodywork", "wheels"],
};
const MAX = 5;
const PAD = 0.27;      // marge haute et basse, en fraction de la largeur
const CARD_W = 0.42;   // largeur d'une bulle, en fraction de la largeur
const CARD_H = 0.19;   // hauteur estimée d'une bulle (fraction de la largeur), pour éviter les chevauchements
const OFFSET = 0.07;   // distance entre le point et le bord de la bulle
const BADGE = 0.11;    // place réservée en haut au bandeau « Vol du véhicule »
const FOOT = 0.05;     // place réservée en bas à la légende de la photo

interface Placed { part: Part; x: number; y: number; side: "L" | "R"; above: boolean; edge: number }

/** Place les bulles colonne par colonne. Une bulle qui ne tient pas au-dessus passe en dessous, et inversement ;
 *  si elle ne tient nulle part, elle n'est pas affichée (la partie reste accessible par le détail). */
function place(parts: Part[], anchors: Photo["anchors"], ratio: number, badge: boolean): { list: Placed[]; H: number } {
  const H = ratio + 2 * PAD;
  const fy = (y: number) => (PAD + y * ratio) / H;  // ordonnée photo -> ordonnée cadre
  const ch = CARD_H / H, off = OFFSET / H, gap = 0.01;
  const top = (badge ? BADGE : 0.01) / H, bottom = 1 - FOOT / H;
  const imgTop = PAD / H, imgBottom = (PAD + ratio) / H, bite = 0.05 / H;  // les bulles mordent de 5 % sur la photo
  const out: Placed[] = [];
  for (const side of ["L", "R"] as const) {
    const col = parts.map((part) => ({ part, x: anchors[part.zone]![0], y: fy(anchors[part.zone]![1]) }))
      .filter((p) => (side === "L" ? p.x < 0.5 : p.x >= 0.5));
    let ceiling = 1;  // bord bas de la plus haute bulle « au-dessus » déjà placée
    let floor = 0;    // bord bas de la plus basse bulle « en dessous » déjà placée
    const mid = (PAD + ratio * 0.5) / H;
    const tryAbove = (p: (typeof col)[number]) => {
      const edge = Math.min(p.y - off, imgTop + bite, ceiling);  // bulle posée sur le bord haut de la photo
      if (edge - ch < top) return false;
      out.push({ ...p, side, above: true, edge }); ceiling = edge - ch - gap; return true;
    };
    const tryBelow = (p: (typeof col)[number]) => {
      const edge = Math.max(p.y + off, imgBottom - bite, floor);  // bulle posée sur le bord bas de la photo
      if (edge + ch > bottom) return false;
      out.push({ ...p, side, above: false, edge }); floor = edge + ch + gap; return true;
    };
    // La place au-dessus revient à la partie la plus haute, celle du dessous à la plus basse ;
    // une partie qui ne trouve pas de place de son côté passe de l'autre (traits sans croisement).
    const up = col.filter((p) => p.y < mid).sort((a, b) => a.y - b.y);
    const down = col.filter((p) => p.y >= mid).sort((a, b) => b.y - a.y);
    const leftovers: typeof col = [];
    for (const p of up) { if (!tryAbove(p)) leftovers.push(p); }
    for (const p of down) { if (!tryBelow(p)) leftovers.push(p); }
    for (const p of leftovers) { if (!tryBelow(p)) tryAbove(p); }
  }
  return { list: out, H };
}

export function CarCallouts({ photo, view, onSelect, selected }: {
  photo: Photo; view: View; onSelect: (zone: string) => void; selected?: string | null;
}) {
  const [ratio, setRatio] = useState(0.56);
  const parts = useMemo(() => {
    const order = PRIORITY[view.case] ?? [];
    return order.map((z) => view.parts[z]).filter((p): p is Part => !!p && p.status !== "none" && !!photo.anchors[p.zone]).slice(0, MAX);
  }, [view, photo]);
  const { list, H } = useMemo(() => place(parts, photo.anchors, ratio, !!view.car), [parts, photo.anchors, ratio, view.car]);
  const pct = (v: number) => `${v * 100}%`;

  return (
    <div className="car-frame" style={{ aspectRatio: `1 / ${H}` }}>
      <img src={photo.url} alt={photo.label} draggable={false} style={{ top: pct(PAD / H), height: pct(ratio / H) }}
        onLoad={(e) => { const i = e.currentTarget; if (i.naturalWidth) setRatio(i.naturalHeight / i.naturalWidth); }} />
      {view.car && (
        <button className={`car-badge st-${view.car.status}`} onClick={() => onSelect("car")}>
          <b>{view.car.label}</b>
          <span>{view.car.status === "covered" ? [view.car.amount, view.car.deductible && `franchise ${view.car.deductible}`].filter(Boolean).join(" · ") : view.car.status === "unknown" ? "À vérifier" : "Non couvert"}</span>
        </button>
      )}
      <svg className="lines" viewBox={`0 0 100 ${H * 100}`} preserveAspectRatio="none" aria-hidden>
        {list.map((c) => {
          const left = c.side === "L" ? 0.02 : 1 - 0.02 - CARD_W;
          const lx = Math.min(Math.max(c.x, left + 0.05), left + CARD_W - 0.05);
          return <line key={c.part.zone} x1={c.x * 100} y1={c.y * H * 100} x2={lx * 100} y2={c.edge * H * 100}
            className={`ln st-${c.part.status}`} vectorEffect="non-scaling-stroke" />;
        })}
      </svg>
      {list.map((c) => (
        <button key={`d-${c.part.zone}`} className={`dot st-${c.part.status}` + (selected === c.part.zone ? " on" : "")}
          style={{ left: pct(c.x), top: pct(c.y) }} onClick={() => onSelect(c.part.zone)} aria-label={c.part.label} />
      ))}
      {list.map((c) => {
        const p = c.part;
        const style = { [c.side === "L" ? "left" : "right"]: "2%", width: pct(CARD_W),
          ...(c.above ? { bottom: pct(1 - c.edge) } : { top: pct(c.edge) }) };
        return (
          <button key={`c-${p.zone}`} className={`callout st-${p.status}` + (selected === p.zone ? " on" : "")} style={style}
            onClick={() => onSelect(p.zone)}>
            {/* Nom de la pièce, « Jusqu'à … », puis ce qui reste à payer (f.*). Une valeur absente n'est pas affichée. */}
            <span className="co-title">{p.label}</span>
            {p.status === "not_covered" || p.status === "unknown" ? (
              <span className="co-amount">{p.status === "not_covered" ? "Non couvert" : "À vérifier"}</span>
            ) : (
              <>
                {p.plafond_dh != null && <span className="co-amount">{t("ui.jusqua", { montant: p.plafond_dh })}</span>}
                {franchiseText(p.franchise)
                  ? <span className="co-sub">{franchiseText(p.franchise)}</span>
                  : p.note && <span className="co-sub">{t("ui.bon_a_savoir")}</span>}
              </>
            )}
          </button>
        );
      })}
      <div className="photo-tag">
        <span>{photo.exact ? photo.label : "Photo d'illustration"}</span>
        {photo.source === "catalog" && (photo.credit_url
          ? <a href={photo.credit_url} target="_blank" rel="noreferrer">{photo.credit}</a> : <span>{photo.credit}</span>)}
      </div>
    </div>
  );
}
