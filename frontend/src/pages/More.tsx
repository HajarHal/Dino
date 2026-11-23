// « Plus » : assureur, contrats, voiture (modèle et photo), à propos.
import { useRef, useState } from "react";
import { api } from "../api";
import type { DocSummary, Dossier, Meta, Profile } from "../types";
import { Camera, Chevron, Close, Trash } from "../icons";
import { dateFr } from "../components/ui";

export function More({ meta, profile, docs, d, onChangeInsurer, onAddCp, refresh, email, onQuit }: {
  meta: Meta; profile: Profile; docs: DocSummary[]; d: Dossier | null;
  onChangeInsurer: () => void; onAddCp: () => void; refresh: () => void; email: string; onQuit: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const photo = useRef<HTMLInputElement>(null);
  const insurer = meta.insurers.find((i) => i.id === (profile.insurer_id ?? d?.insurer.id));
  const active = d?.policy.document_id;

  const run = (p: Promise<unknown>) => { setBusy(true); setErr(null); p.then(refresh).catch((e) => setErr(String(e.message))).finally(() => setBusy(false)); };

  return (
    <div className="page">
      <header className="hero"><h1>Plus</h1></header>
      {err && <p className="banner warn">{err}</p>}

      <h2 className="sec">Mon assureur</h2>
      <button className="card row-link" onClick={onChangeInsurer}>
        <span><b>{insurer?.label ?? "Non choisi"}</b>
          <span className="muted">{insurer?.cg_kind === "official" ? "Conditions Générales de l'assureur intégrées" : "Conditions Générales non intégrées"}</span></span>
        <Chevron size={20} />
      </button>

      <h2 className="sec">Mes contrats</h2>
      <section className="card flush">
        {docs.map((x) => (
          <div key={x.id} className={"doc-row" + (x.id === active ? " on" : "")}>
            <button className="doc-main" onClick={() => run(api.setProfile({ cp_id: x.id }))} disabled={!x.read}>
              <b>{x.vehicle ?? x.filename}</b>
              <span className="muted small">{[x.policy_number && `N° ${x.policy_number}`, x.period_end && `jusqu'au ${dateFr(x.period_end)}`,
                !x.read && "lecture échouée"].filter(Boolean).join(" · ") || x.filename}</span>
            </button>
            {x.id === active && <span className="tag">Affiché</span>}
            <button className="icon-btn" aria-label="Supprimer ce contrat" disabled={busy}
              onClick={() => confirm("Supprimer ce contrat et sa lecture ?") && run(api.deleteDocument(x.id))}><Trash size={18} /></button>
          </div>
        ))}
        <button className="link pad" onClick={onAddCp}>Ajouter des Conditions Particulières</button>
      </section>

      {d && (
        <>
          <h2 className="sec">Ma voiture</h2>
          <section className="card">
            <label className="field">
              <span>Modèle affiché</span>
              <select value={profile.car_key ?? ""} onChange={(e) => run(api.setProfile({ car_key: e.target.value || undefined }))} disabled={busy}>
                <option value="">Automatique (d'après la CP)</option>
                {meta.car_models.map((m) => <option key={m.key} value={m.key}>{m.make} {m.model}</option>)}
              </select>
            </label>
            <p className="muted small">Le modèle n'est pas toujours imprimé sur la CP. Choisissez le vôtre, ou ajoutez une photo de votre voiture (vue avant de trois quarts).</p>
            <input ref={photo} type="file" accept="image/*" hidden onChange={(e) => e.target.files?.[0] && run(api.uploadPhoto(d.policy.document_id, e.target.files[0]))} />
            <div className="row-btns">
              <button className="btn-soft" onClick={() => photo.current?.click()} disabled={busy}><Camera size={18} />{d.photo.source === "upload" ? "Changer ma photo" : "Ajouter ma photo"}</button>
              {d.photo.source === "upload" && <button className="link" onClick={() => run(api.deletePhoto(d.policy.document_id))}>Retirer ma photo</button>}
            </div>
            {busy && <p className="muted small">Enregistrement…</p>}
          </section>
        </>
      )}

      <h2 className="sec">À propos</h2>
      <section className="card small">
        <p>Les montants (plafonds, franchises) viennent de vos Conditions Particulières. Les explications sont des extraits
          mot pour mot des Conditions Générales de votre assureur, avec leur article. Rien n'est supposé : une valeur absente
          de la CP est signalée.</p>
        <p>Photos de véhicules : Wikimedia Commons, licences libres, auteur indiqué sous chaque photo.</p>
        <p className="muted">Les textes affichés sont des extraits de vos documents. Les documents originaux font foi.</p>
      </section>

      <button className="card row-link quit" onClick={onQuit}>
        <span className="rl-ico"><Close size={20} /></span>
        <span><b>Quitter</b><span className="muted">{email} · vos contrats restent enregistrés</span></span>
      </button>
    </div>
  );
}
