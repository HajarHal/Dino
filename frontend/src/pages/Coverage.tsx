// « Ma couverture » : le cas choisi (Ma police, Conducteur, Bris de glace, Vol…), la photo de la voiture avec,
// pour chaque partie, ce qui est couvert, puis le scénario fautif / non fautif et ce qu'il change.
import { useState } from "react";
import type { CaseId, Dossier, Fault, Row } from "../types";
import { CASE_ICON, Alert, Chevron, Doc, Shield } from "../icons";
import { CarCallouts } from "../components/CarCallouts";
import { AiBox, GuaranteeRow, Sheet, StatusPill, dateFr } from "../components/ui";
import { CheckList, ExactTextLink, FranchiseExample, HaveChip, MoneyPair, WhoPaysGrid, franchiseText, gIcon } from "../components/visual";
import { dh, t } from "../copy";

const CAR_CASES: CaseId[] = ["police", "glass", "theft", "fire", "nature"];
const PERSON_KEYS: [string, string][] = [["DRIVER_PROTECTION", "Conducteur"], ["PERSONAL_INJURY", "Conducteur et passagers"],
  ["DEATH_BENEFIT", "Capital décès"], ["DISABILITY_BENEFIT", "Capital invalidité"], ["MEDICAL_COSTS", "Frais médicaux"],
  ["PASSENGER_PROTECTION", "Par passager"], ["DEFENSE_RECOURS", "Plafond des frais"], ["RC", "Responsabilité civile"]];

export function Coverage({ d, openPolicy, onUseInsurer }: {
  d: Dossier; openPolicy: () => void; onUseInsurer: (id: string) => void;
}) {
  const q = new URLSearchParams(location.search);  // liens directs : ?case=theft&fault=not_at_fault
  const [caseId, setCase] = useState<CaseId>(() => (d.cases.some((c) => c.id === q.get("case")) ? q.get("case") as CaseId : "police"));
  const [fault, setFault] = useState<Fault>(() => (q.get("fault") === "not_at_fault" ? "not_at_fault" : "at_fault"));
  const [zone, setZone] = useState<string | null>(null);
  const [details, setDetails] = useState(false);
  const view = d.views[`${caseId}:${fault}`];
  const v = d.vehicle;
  const detected = d.detected_insurer;

  return (
    <div className="page">
      <header className="hero">
        <h1>Ma couverture auto</h1>
        <p>Découvrez ce qui est couvert sur votre véhicule et comprenez votre assurance simplement.</p>
      </header>

      {d.policy.status !== "active" && (
        <div className="banner warn"><Alert size={18} />
          {d.policy.status === "expired" ? `Contrat expiré : date de fin ${dateFr(d.policy.period_end)} sur votre CP.`
            : d.policy.status === "upcoming" ? `Contrat valable à partir du ${dateFr(d.policy.period_start)}.`
            : "Dates du contrat non lues : vérifiez la période sur votre CP."}
        </div>
      )}
      {d.insurer_mismatch && detected && (
        <div className="banner info"><Alert size={18} />
          <span>Votre CP semble émise par un autre assureur que {d.insurer.label}.</span>
          <button className="link" onClick={() => onUseInsurer(detected)}>Utiliser ses Conditions Générales</button>
        </div>
      )}

      <nav className="cases" aria-label="Situations">
        {d.cases.map((c) => {
          const Icon = CASE_ICON[c.id] ?? Doc;
          return (
            <button key={c.id} className={"case" + (caseId === c.id ? " on" : "")} onClick={() => { setCase(c.id); setZone(null); }}
              aria-pressed={caseId === c.id}>
              <span className="case-ico"><Icon size={26} /><i className={`case-dot st-${c.status}`} /></span>
              <span className="case-lb">{c.label}</span>
            </button>
          );
        })}
      </nav>

      <section className="card car-card">
        <div className="car-head">
          <div>
            <h2>{v.title}</h2>
            <p className="muted">{[v.registration, v.year, v.energy].filter(Boolean).join(" · ") || "Immatriculation non lue"}</p>
          </div>
          <button className="pill-btn" onClick={() => setDetails(true)}>Voir les détails <Chevron size={16} /></button>
        </div>
        {CAR_CASES.includes(caseId) ? (
          <>
            <CarCallouts photo={d.photo} view={view} onSelect={setZone} selected={zone} />
            <div className="parts" aria-label="Toutes les parties">
              {Object.values(view.parts).filter((p) => p.status !== "none").map((p) => (
                <button key={p.zone} className={`part-chip st-${p.status}` + (zone === p.zone ? " on" : "")} onClick={() => setZone(p.zone)}>
                  <i />{p.label}
                </button>
              ))}
            </div>
          </>
        ) : <PersonPanel items={view.items} caseId={caseId} />}
      </section>

      {!view.extra && (<div className="segmented" role="tablist" aria-label="Scénario">
        <button role="tab" aria-selected={fault === "at_fault"} className={fault === "at_fault" ? "on" : ""} onClick={() => setFault("at_fault")}>Scénario fautif</button>
        <button role="tab" aria-selected={fault === "not_at_fault"} className={fault === "not_at_fault" ? "on" : ""} onClick={() => setFault("not_at_fault")}>Scénario non fautif</button>
      </div>)}

      <HeadlineCard h={view.headline} />

      {view.items.filter((r) => r.ai?.status === "suggested").map((r) => (
        <section key={r.ai!.label} className="card">
          <h3>{r.ai!.label}{r.limit ? ` · ${r.limit}` : ""}</h3>
          <AiBox row={r} insurerId={d.insurer.id} />
        </section>
      ))}

      {!view.extra && view.who_pays && (view.who_pays.tiles.length > 0 || view.who_pays.needs.length > 0) && (
        <section className="card notes">
          <h3>{t(fault === "at_fault" ? "fault.at_fault.title" : "fault.not_at_fault.title")}</h3>
          <WhoPaysGrid tiles={view.who_pays.tiles} />
          <CheckList items={view.who_pays.needs} />
        </section>
      )}

      <button className="card row-link" onClick={openPolicy}>
        <span className="rl-ico"><Doc size={22} /></span>
        <span><b>Consulter ma police d'assurance</b>
          <span className="muted">{d.insurer.label}{d.policy.number ? ` · N° ${d.policy.number}` : ""}</span></span>
        <Chevron size={20} />
      </button>

      {zone && (zone === "car" ? view.car && (
        <Sheet title={view.car.label} onClose={() => setZone(null)}>
          <StatusPill status={view.car.status} />
          {view.items.filter((r) => r.code === "THEFT").map((r) => <GuaranteeRow key={r.code} row={r} open />)}
        </Sheet>
      ) : view.parts[zone] && (
        <PartSheet title={view.parts[zone].label} zone={zone} view={view} items={view.items} onClose={() => setZone(null)} />
      ))}
      {details && (
        <Sheet title={`${d.cases.find((c) => c.id === caseId)?.label} · garanties`} onClose={() => setDetails(false)}>
          {view.items.length ? view.items.map((r) => <GuaranteeRow key={r.code} row={r} />) : <p className="muted">Aucune garantie concernée.</p>}
        </Sheet>
      )}
    </div>
  );
}

function PartSheet({ title, zone, view, items, onClose }: {
  title: string; zone: string; view: Dossier["views"][string]; items: Row[]; onClose: () => void;
}) {
  const p = view.parts[zone];
  const rows = items.filter((r) => p.entries.some((e) => e.code === r.code));
  return (
    <Sheet title={title} onClose={onClose}>
      <div className="part-sum">
        <StatusPill status={p.status} text={undefined} />
        {p.subtitle && <span className="muted">{p.subtitle}</span>}
      </div>
      {p.note && <ExactTextLink label={t("ui.bon_a_savoir")} source={{ doc: "CG", ref: p.note_ref ?? null, texts: [p.note] }} />}
      {p.entries.length > 0 && (
        <table className="mini">
          <thead><tr><th>Garantie</th><th>{t("ui.jusqua", { montant: "" })}</th><th>{t("ui.vous_payez")}</th></tr></thead>
          <tbody>{p.entries.map((e) => (
            <tr key={e.code}><td>{e.title}</td>
              <td>{e.amount != null ? dh(e.amount) : null}</td><td>{franchiseText(e.franchise)}</td></tr>
          ))}</tbody>
        </table>
      )}
      {p.status === "not_covered" && <p>Aucune garantie de votre CP ne concerne cette partie.</p>}
      {p.status === "unknown" && <p>Aucune garantie trouvée sur votre CP pour cette partie. La CP n'a pas été lue en entier : vérifiez-la.</p>}
      {rows.map((r) => <GuaranteeRow key={r.code} row={r} />)}
    </Sheet>
  );
}

/** Conducteur, passagers, assistance, défense : pas de pièce du véhicule, les montants qui comptent. */
function PersonPanel({ items, caseId }: { items: Row[]; caseId: CaseId }) {
  const Icon = CASE_ICON[caseId] ?? Doc;
  const subscribed = items.filter((r) => r.subscribed && r.limit);
  // Conducteur / Passagers : le libellé imprimé sur la CP (« IPT à 100% ») ; autres cas : intitulé court.
  const person = caseId === "driver" || caseId === "passengers";
  const tiles = subscribed.map((r) => ({ r, label: person ? r.title : PERSON_KEYS.find(([c]) => c === r.code)?.[1] ?? r.title }));
  return (
    <div className="person">
      <span className="person-ico"><Icon size={40} /></span>
      {tiles.length ? (
        <div className="tiles">
          {tiles.map(({ r, label }) => (
            <div key={r.code} className="tile">
              <small>{label}</small>
              <b>{r.limit}</b>
              {r.deductible && r.deductible !== "Aucune" && <small className="muted">Franchise {r.deductible}</small>}
            </div>
          ))}
        </div>
      ) : (
        <p className="muted center">Aucune garantie de ce type sur votre CP.</p>
      )}
    </div>
  );
}

/** Carte garantie : nom simple (g.X.title), ce qu'elle couvre en une ligne, « Jusqu'à » et « Vous payez »,
 *  « Vous l'avez », l'exemple chiffré de franchise, puis le texte exact (le paragraphe des CG n'est plus affiché). */
function HeadlineCard({ h }: { h: Dossier["views"][string]["headline"] }) {
  const G = gIcon(h.gcode);
  const subscribed = h.subscribed ?? h.status !== "not_covered";
  return (
    <section className={`card headline st-${h.status}`}>
      <span className="hl-ico">{h.gcode ? <G size={22} /> : <Shield size={22} />}</span>
      <div className="hl-body">
        <h3>{h.gcode ? t(`g.${h.gcode}.title`) : h.title}</h3>
        {h.gcode && <p className="muted">{t(`g.${h.gcode}.one`)}</p>}
        {subscribed && <MoneyPair plafond={h.plafond_dh} franchise={h.franchise} />}
        {!subscribed && h.status === "unknown" ? <StatusPill status="unknown" text={t("ui.a_verifier")} /> : <HaveChip subscribed={subscribed} />}
        {subscribed && <FranchiseExample franchise={h.franchise} plafond={h.plafond_dh} />}
        <ExactTextLink source={h.source} />
      </div>
    </section>
  );
}
