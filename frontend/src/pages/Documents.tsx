// « Mes documents » : les Conditions Générales et les Conditions Particulières. Même structure qu'avant ; le contenu
// de chaque bloc est visuel (puces, chiffres, frise, étapes, tuiles), le texte exact reste à un tap.
import { useState } from "react";
import type { CGDoc, CPDoc, Dossier } from "../types";
import { api } from "../api";
import { Alert, Building, Phone } from "../icons";
import { GuaranteeRow, Sheet, StatusPill, dateFr } from "../components/ui";
import {
  ChipList, CheckList, ContractDurationBar, DelayTimeline, ExactTextLink, FranchiseExample, InfoTip, Steps, TerritoryChip,
  Unclassified, WhoPaysGrid, franchiseText, gIcon,
} from "../components/visual";
import { dh, t } from "../copy";

export type DocTab = "cg" | "cp";

export function Documents({ d, tab, setTab }: { d: Dossier; tab: DocTab; setTab: (t: DocTab) => void }) {
  return (
    <div className="page">
      <header className="hero">
        <h1>Mes documents</h1>
        <p>Ce que disent vos documents, sans reformulation. Les documents originaux font foi.</p>
      </header>
      <div className="segmented" role="tablist">
        <button role="tab" aria-selected={tab === "cg"} className={tab === "cg" ? "on" : ""} onClick={() => setTab("cg")}>Conditions Générales</button>
        <button role="tab" aria-selected={tab === "cp"} className={tab === "cp" ? "on" : ""} onClick={() => setTab("cp")}>Conditions Particulières</button>
      </div>
      {tab === "cg" ? <CG cg={d.documents.cg} /> : <CP cp={d.documents.cp} d={d} />}
    </div>
  );
}

// ------------------------------------------------------------------------------------------ Conditions Générales

function CG({ cg }: { cg: CGDoc }) {
  const [others, setOthers] = useState(false);
  const s = cg.source;
  const w = cg.who_pays;
  const exclCoded = cg.common_exclusions.filter((x) => x.codes?.length && x.src)
    .flatMap((x) => x.codes!.map((code) => ({ code, source: x.src! })));
  const exclOther = cg.common_exclusions.filter((x) => !x.codes?.length && x.src).map((x) => ({ text: x.text, source: x.src! }));
  const life = cg.contract_life.filter((x) => !(cg.territory && x.title === "Pays couverts"));
  return (
    <>
      <section className={"card source " + s.kind}>
        <Building size={22} />
        <div>
          {s.kind === "official" ? (
            <>
              <b>{s.document}</b>
              <span className="muted">{cg.insurer}{s.version ? ` · version ${s.version}` : ""} · textes cités mot pour mot, avec leur article</span>
              {s.pdf_url && <a className="link" href={s.pdf_url} target="_blank" rel="noreferrer">Ouvrir le document original (PDF)</a>}
            </>
          ) : (
            <>
              <b>Conditions Générales de {cg.insurer} non intégrées</b>
              <span className="muted">Seules les informations de votre CP sont affichées : garanties, plafonds, franchises.</span>
            </>
          )}
        </div>
      </section>

      <h2 className="sec">Vos garanties</h2>
      <div className="stack">{cg.mine.map((r) => <GuaranteeRow key={r.code + (r.cp_label ?? "")} row={r} />)}</div>

      {(cg.timeline.items.length > 0 || cg.timeline.other.length > 0) && (
        <>
          <h2 className="sec">Délais</h2>
          <section className="card">
            <DelayTimeline items={cg.timeline.items} />
            <Unclassified items={cg.timeline.other} />
          </section>
        </>
      )}

      {(cg.steps.items.length > 0 || cg.steps.other.length > 0 || cg.contacts.length > 0) && (
        <>
          <h2 className="sec">En cas de sinistre</h2>
          <section className="card">
            <Steps items={cg.steps.items} />
            <Unclassified items={cg.steps.other} />
            {cg.contacts.map((c) => (
              <a key={c.phone} className="phone" href={`tel:${c.phone.replace(/\s/g, "")}`}><Phone size={18} />{c.label} · {c.phone}</a>
            ))}
          </section>
        </>
      )}

      {w && (w.at_fault.length > 0 || w.not_at_fault.length > 0) && (
        <>
          <h2 className="sec">Responsable ou non</h2>
          <div className="two">
            {w.at_fault.length > 0 && <section className="card"><WhoPaysGrid tiles={w.at_fault} title={t("fault.at_fault.title")} /></section>}
            {(w.not_at_fault.length > 0 || w.needs.length > 0) && (
              <section className="card">
                <WhoPaysGrid tiles={w.not_at_fault} title={t("fault.not_at_fault.title")} />
                <CheckList items={w.needs} />
              </section>
            )}
          </div>
        </>
      )}

      {cg.compensation.length > 0 && (
        <>
          <h2 className="sec">Indemnisation</h2>
          <section className="card">
            <dl className="kv">{cg.compensation.map((x) => <div key={x.title}><dt>{x.title}</dt><dd><ExactTextLink source={x.src} /></dd></div>)}</dl>
          </section>
        </>
      )}

      {cg.common_exclusions.length > 0 && (
        <>
          <h2 className="sec">Exclusions communes</h2>
          <section className="card">
            <ChipList items={exclCoded} kind="exclusion" />
            <Unclassified items={exclOther} />
          </section>
        </>
      )}

      {(life.length > 0 || cg.territory) && (
        <>
          <h2 className="sec">La vie du contrat</h2>
          <section className="card">
            <TerritoryChip territory={cg.territory} />
            <dl className="kv">{life.map((x) => <div key={x.title}><dt>{x.title}</dt><dd><ExactTextLink source={x.src} /></dd></div>)}</dl>
          </section>
        </>
      )}

      {cg.others.length > 0 && (
        <>
          <h2 className="sec">{t("options.title")}</h2>
          <section className="card">
            <p className="muted small">{t("options.sub")}</p>
            <ul className="others">
              {(others ? cg.others : cg.others.slice(0, 6)).map((g) => (
                <li key={g.code}>
                  <b>{g.gcode ? t(`g.${g.gcode}.title`) : g.title}</b>
                  {g.gcode && <span className="muted">{t(`g.${g.gcode}.one`)}</span>}
                  <ExactTextLink source={g.source} />
                </li>
              ))}
            </ul>
            {cg.others.length > 6 && <button className="link" onClick={() => setOthers(!others)}>{others ? "Voir moins" : `Voir les ${cg.others.length}`}</button>}
          </section>
        </>
      )}
    </>
  );
}

// ------------------------------------------------------------------------------------------ Conditions Particulières

const STATUS_FR: Record<string, string> = { active: "En cours", expired: "Expiré", upcoming: "À venir", unknown: "Dates non lues" };
/** Aide (i) de chaque ligne « Véhicule » (clés veh.* de copy/fr.json). */
const VEH_HELP: Record<string, string> = {
  "Valeur à neuf": "veh.valeur_a_neuf.help", "Valeur vénale": "veh.valeur_venale.help",
  "Puissance fiscale": "veh.puissance_fiscale.help", "Mise en circulation": "veh.mise_en_circulation.help",
};

function CP({ cp, d }: { cp: CPDoc; d: Dossier }) {
  const [page, setPage] = useState<number | null>(null);
  const [broken, setBroken] = useState<Set<number>>(new Set());
  const [detail, setDetail] = useState<string | null>(null);
  const st = d.policy.status;
  const values = cp.vehicle.filter(([k]) => k === "Valeur à neuf" || k === "Valeur vénale");
  const rest = cp.vehicle.filter(([k]) => k !== "Valeur à neuf" && k !== "Valeur vénale");
  const detailRow = detail ? d.documents.cg.mine.find((r) => r.code === detail) : null;
  return (
    <>
      <section className={`card status-card st-${st === "active" ? "covered" : st === "expired" ? "not_covered" : "unknown"}`}>
        <div>
          <small>Contrat {STATUS_FR[st]}</small>
          <b>{d.policy.period_end ? (st === "expired" ? `Terminé le ${dateFr(d.policy.period_end)}` : `Jusqu'au ${dateFr(d.policy.period_end)}`) : "Période non lue"}</b>
        </div>
        <StatusPill status={st === "active" ? "covered" : st === "expired" ? "not_covered" : "unknown"} text={STATUS_FR[st]} />
        <ContractDurationBar start={cp.period.start} end={cp.period.end} />
      </section>

      {(cp.checks.length > 0 || cp.app_warnings.length > 0) && (
        <section className="card warn-card">
          <h3><Alert size={18} /> Points à vérifier</h3>
          <ul className="checks">
            {cp.checks.map((c) => <li key={c}><Alert size={14} />{t(`check.${c}`)}</li>)}
            {cp.app_warnings.map((w) => <li key={w}><Alert size={14} />{w}</li>)}
          </ul>
        </section>
      )}

      <h2 className="sec">Garanties souscrites</h2>
      <section className="card flush">
        <table className="lines">
          <thead><tr><th>Garantie</th><th>{t("ui.jusqua", { montant: "" })}</th><th>{t("ui.vous_payez")}</th></tr></thead>
          <tbody>{cp.lines.map((l, i) => {
            const G = gIcon(l.gcode);
            const canOpen = !!l.code && d.documents.cg.mine.some((r) => r.code === l.code);
            return (
              <tr key={i} className={(l.to_check ? "check " : "") + (canOpen ? "tappable" : "")} onClick={() => canOpen && setDetail(l.code!)}>
                <td><span className="line-title"><G size={18} /><b>{l.gcode ? t(`g.${l.gcode}.title`) : l.title ?? l.label}</b></span>
                  <small className="muted">{l.label}</small>
                  {l.to_check && <small className="warn">{t("ui.a_verifier")}</small>}</td>
                <td>{l.plafond_dh != null ? dh(l.plafond_dh) : null}</td>
                <td>{franchiseText(l.franchise)}</td>
              </tr>
            );
          })}</tbody>
        </table>
      </section>
      {detailRow && <Sheet title={detailRow.gcode ? t(`g.${detailRow.gcode}.title`) : detailRow.title} onClose={() => setDetail(null)}>
        <GuaranteeRow row={detailRow} open />
      </Sheet>}

      {cp.damage_example && cp.damage_example.franchise && cp.damage_example.franchise.base !== "UNKNOWN" && (
        <>
          <h2 className="sec">Votre franchise en exemple</h2>
          <section className="card">
            <p className="small"><b>{cp.damage_example.gcode ? t(`g.${cp.damage_example.gcode}.title`) : cp.damage_example.guarantee}</b> · {franchiseText(cp.damage_example.franchise)}</p>
            <FranchiseExample franchise={cp.damage_example.franchise} plafond={cp.damage_example.plafond_dh} />
          </section>
        </>
      )}

      <h2 className="sec">Contrat</h2>
      <section className="card">
        <dl className="kv">{cp.contract.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{["Début", "Fin"].includes(k) ? dateFr(v) : v}</dd></div>)}</dl>
      </section>

      <h2 className="sec">Véhicule</h2>
      <section className="card">
        <dl className="kv">{rest.map(([k, v]) => (
          <div key={k}>
            <dt>{k}{VEH_HELP[k] && <InfoTip helpKey={VEH_HELP[k]} />}</dt>
            <dd>{k === "Mise en circulation" ? dateFr(v) : k === "Usage" && cp.usage_code ? t(`veh.usage.${cp.usage_code}`) : v}</dd>
          </div>
        ))}</dl>
        {values.length > 0 && (
          <div className="money-pair">
            {values.map(([k, v]) => <span key={k}><small>{k}<InfoTip helpKey={VEH_HELP[k]} /></small><b>{v}</b></span>)}
          </div>
        )}
      </section>

      {d.policy.pages > broken.size && (
        <>
          <h2 className="sec">Document original</h2>
          <div className="pages">
            {Array.from({ length: d.policy.pages }, (_, i) => i + 1).filter((n) => !broken.has(n)).map((n) => (
              <button key={n} className="page-thumb" onClick={() => setPage(page === n ? null : n)}>
                {/* Image illisible : pas de miniature cassée, la page n'est pas affichée. */}
                <img src={api.pageUrl(d.policy.document_id, n)} alt={`Page ${n} de la CP`} loading="lazy"
                  onError={() => setBroken((b) => new Set(b).add(n))} />
              </button>
            ))}
          </div>
          {page && <img className="page-full" src={api.pageUrl(d.policy.document_id, page)} alt={`Page ${page}`} onClick={() => setPage(null)} />}
        </>
      )}
    </>
  );
}
