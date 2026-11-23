// Démarrage : 1. choisir son assureur (ses Conditions Générales sont déjà intégrées) ; 2. ajouter sa CP.
import { useRef, useState } from "react";
import { api, waitJob } from "../api";
import type { Insurer, Job, Meta } from "../types";
import { Back, Camera, Check, Upload } from "../icons";
import { Spinner } from "../components/ui";

/** Monogramme neutre (aucun logo de marque) : sigle s'il existe (AXA, RMA), sinon majuscules du nom (AtlantaSanad → AS). */
function initials(s: string): string {
  const w = s.replace(/Assurances?|Maroc/gi, "").trim().split(/\s+/)[0] ?? s;
  if (w.length <= 4 && w === w.toUpperCase()) return w;
  const caps = w.match(/[A-Z]/g) ?? [];
  return caps.length > 1 ? caps.join("").slice(0, 3) : w.slice(0, 2).toUpperCase();
}

export function InsurerPicker({ insurers, selected, onPick, onBack }: {
  insurers: Insurer[]; selected?: string; onPick: (id: string) => void; onBack?: () => void;
}) {
  return (
    <div className="page onboarding">
      {onBack && <button className="back" onClick={onBack}><Back size={20} />Retour</button>}
      <p className="step">Étape 1 sur 2</p>
      <h1>Quel est votre assureur ?</h1>
      <p className="lead">Ses Conditions Générales sont déjà dans l'application : vous n'avez pas à les ajouter.</p>
      <div className="insurers">
        {insurers.map((i) => (
          <button key={i.id} className={"insurer" + (selected === i.id ? " on" : "")} onClick={() => onPick(i.id)}>
            <span className="ins-logo">{i.id === "other" ? "?" : initials(i.label)}</span>
            <span className="ins-name"><b>{i.label}</b>{i.full_name && <small>{i.full_name}</small>}</span>
            <span className={"ins-tag " + i.cg_kind}>{i.cg_kind === "official" ? "CG intégrées" : "CG non intégrées"}</span>
            {selected === i.id && <Check size={18} />}
          </button>
        ))}
      </div>
    </div>
  );
}

export function CpUpload({ meta, insurer, onDone, onBack }: {
  meta: Meta; insurer?: Insurer; onDone: () => void; onBack: () => void;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const camera = useRef<HTMLInputElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const add = (list: FileList | null) => list && setFiles((f) => [...f, ...Array.from(list)]);

  const read = async () => {
    setBusy(true); setErr(null);
    try {
      const { job_id } = await api.uploadCP(files);
      const j = await waitJob(job_id, setJob);
      if (j.status === "FAILED") throw new Error(j.error ?? "Lecture impossible");
      onDone();
    } catch (e) {
      setErr(String((e as Error).message)); setJob(null);
    } finally { setBusy(false); }
  };
  const sample = async () => {
    setBusy(true);
    try { await api.loadSample(); onDone(); } catch (e) { setErr(String((e as Error).message)); setBusy(false); }
  };

  if (busy && job) {
    return (
      <div className="page onboarding reading">
        <Spinner />
        <h1>Lecture de votre contrat</h1>
        <p className="lead">Votre CP est lue deux fois et les deux lectures sont comparées. Cela prend en général une à deux minutes.</p>
        <p className="muted small">{job.activity ?? job.message} · {job.elapsed_s} s</p>
      </div>
    );
  }
  return (
    <div className="page onboarding">
      <button className="back" onClick={onBack}><Back size={20} />{insurer?.label ?? "Assureur"}</button>
      <p className="step">Étape 2 sur 2</p>
      <h1>Ajoutez vos Conditions Particulières</h1>
      <p className="lead">Le document qui indique votre véhicule, vos garanties, vos plafonds et vos franchises. Une photo nette suffit.</p>

      <input ref={camera} type="file" accept="image/*" capture="environment" hidden onChange={(e) => add(e.target.files)} />
      <input ref={picker} type="file" accept="image/*,application/pdf" multiple hidden onChange={(e) => add(e.target.files)} />
      <div className="drop" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); add(e.dataTransfer.files); }}>
        <div className="drop-actions">
          <button className="btn-soft" onClick={() => camera.current?.click()} disabled={!meta.llm_available}><Camera size={20} />Prendre une photo</button>
          <button className="btn-soft" onClick={() => picker.current?.click()} disabled={!meta.llm_available}><Upload size={20} />Choisir un fichier</button>
        </div>
        <p className="muted small">Photo, scan ou PDF. Plusieurs pages possibles. Votre nom, CIN et adresse ne sont pas lus.</p>
        {files.length > 0 && (
          <ul className="files">{files.map((f, i) => (
            <li key={i}><span>{f.name}</span><button className="link" onClick={() => setFiles(files.filter((_, k) => k !== i))}>Retirer</button></li>
          ))}</ul>
        )}
      </div>
      {!meta.llm_available && <p className="banner warn">La lecture automatique n'est pas configurée sur ce serveur (clé API absente). Vous pouvez essayer l'exemple.</p>}
      {err && <p className="banner warn">{err}</p>}
      <button className="btn" disabled={!files.length || busy} onClick={read}>{busy ? "Envoi…" : "Lire mon contrat"}</button>
      <button className="link center" onClick={sample} disabled={busy}>Essayer avec un exemple de contrat</button>
    </div>
  );
}
