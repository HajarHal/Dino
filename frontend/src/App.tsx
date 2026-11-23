import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { DocSummary, Dossier, Meta, Profile } from "./types";
import { Dots, Doc, Shield } from "./icons";
import { Spinner } from "./components/ui";
import { Coverage } from "./pages/Coverage";
import { Documents, type DocTab } from "./pages/Documents";
import { CpUpload, InsurerPicker } from "./pages/Onboarding";
import { More } from "./pages/More";
import { Login } from "./pages/Login";
import dino from "./assets/dino.png";

type Tab = "coverage" | "documents" | "more";
type Flow = null | "insurer" | "upload";

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [docs, setDocs] = useState<DocSummary[] | null>(null);
  const [dossier, setDossier] = useState<Dossier | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const q = new URLSearchParams(location.search);  // liens directs : ?tab=documents&doc=cp
  const [tab, setTab] = useState<Tab>(() => (["documents", "more"].includes(q.get("tab") ?? "") ? q.get("tab") as Tab : "coverage"));
  const [docTab, setDocTab] = useState<DocTab>(() => (q.get("doc") === "cp" ? "cp" : "cg"));
  const [flow, setFlow] = useState<Flow>(null);
  const [me, setMe] = useState<string | null | undefined>(undefined);  // undefined : vérification en cours

  const refresh = useCallback(async () => {
    try {
      const [p, ds] = await Promise.all([api.profile(), api.documents()]);
      setProfile(p); setDocs(ds);
      if (ds.some((x) => x.read)) setDossier(await api.dossier());
      else setDossier(null);
      setErr(null);
    } catch (e) { setErr(String((e as Error).message)); }
  }, []);
  useEffect(() => {
    api.meta().then(setMeta).catch((e) => setErr(String(e.message)));
    api.me().then((m) => setMe(m.email)).catch(() => setMe(null));
  }, []);
  useEffect(() => { if (me) refresh(); }, [me, refresh]);
  useEffect(() => {  // session expirée ou fermée ailleurs : retour à l'écran de connexion
    const lost = () => setMe(null);
    window.addEventListener("auth:lost", lost);
    return () => window.removeEventListener("auth:lost", lost);
  }, []);
  const quit = async () => {
    await api.logout().catch(() => undefined);
    setMe(null); setProfile(null); setDocs(null); setDossier(null); setFlow(null); setTab("coverage");
  };
  useEffect(() => { window.scrollTo(0, 0); }, [tab, flow]);
  useEffect(() => {  // « Correct ? » de l'IA, et classement en cours : recharger le dossier
    const r = () => { refresh(); };
    window.addEventListener("dossier:reload", r);
    return () => window.removeEventListener("dossier:reload", r);
  }, [refresh]);
  useEffect(() => {
    if (!dossier?.ai_pending?.length) return;
    const t = setTimeout(refresh, 4000);
    return () => clearTimeout(t);
  }, [dossier, refresh]);

  if (err && !meta) {
    return <div className="page"><p className="banner warn">Serveur injoignable ({err}). Lancez « uvicorn ica.api:app --port 8000 » puis rechargez la page.</p></div>;
  }
  if (me === null && meta) return <Shell><Login onDone={(email) => setMe(email)} /></Shell>;
  if (!meta || !me || !profile || !docs) return <div className="page"><Spinner label="Chargement" /></div>;

  const hasCp = docs.some((x) => x.read);
  const step: Flow = flow ?? (!profile.insurer_id ? "insurer" : !hasCp ? "upload" : null);
  const insurer = meta.insurers.find((i) => i.id === profile.insurer_id);
  const pickInsurer = (id: string) => api.setProfile({ insurer_id: id }).then(async (p) => {
    setProfile(p);
    if (flow === "insurer" && hasCp) { setFlow(null); await refresh(); } else setFlow("upload");
  });

  if (step === "insurer") {
    return <Shell><InsurerPicker insurers={meta.insurers} selected={profile.insurer_id} onPick={pickInsurer}
      onBack={hasCp ? () => setFlow(null) : undefined} /></Shell>;
  }
  if (step === "upload") {
    return <Shell><CpUpload meta={meta} insurer={insurer} onBack={() => setFlow(hasCp ? null : "insurer")}
      onDone={async () => { setFlow(null); setTab("coverage"); await refresh(); }} /></Shell>;
  }

  return (
    <Shell avatar={() => setTab("more")}>
      {err && <p className="banner warn">{err}</p>}
      {!dossier ? <Spinner label="Lecture de votre contrat" /> : (
        <>
          {tab === "coverage" && <Coverage d={dossier} openPolicy={() => { setDocTab("cp"); setTab("documents"); }}
            onUseInsurer={(id) => api.setProfile({ insurer_id: id }).then(refresh)} />}
          {tab === "documents" && <Documents d={dossier} tab={docTab} setTab={setDocTab} />}
        </>
      )}
      {tab === "more" && <More meta={meta} profile={profile} docs={docs} d={dossier} refresh={refresh}
        onChangeInsurer={() => setFlow("insurer")} onAddCp={() => setFlow("upload")}
        email={me} onQuit={quit} />}
      <nav className="tabbar" aria-label="Navigation">
        {([["coverage", "Ma couverture", Shield], ["documents", "Mes documents", Doc], ["more", "Plus", Dots]] as const).map(([id, label, Icon]) => (
          <button key={id} className={tab === id ? "on" : ""} aria-current={tab === id ? "page" : undefined} onClick={() => setTab(id)}>
            <Icon size={24} /><span>{label}</span>
          </button>
        ))}
      </nav>
    </Shell>
  );
}

function Shell({ children, avatar }: { children: React.ReactNode; avatar?: () => void }) {
  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">D<span className="brand-i">i</span>no</span>
        {avatar
          ? <button className="avatar" onClick={avatar} aria-label="Mon compte"><img src={dino} alt="" /></button>
          : <span className="avatar"><img src={dino} alt="" /></span>}
      </header>
      <main>{children}</main>
    </div>
  );
}
