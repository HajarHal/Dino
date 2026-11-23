// Écran de connexion : se connecter, ou créer un compte (e-mail + mot de passe).
import { useState } from "react";
import { api } from "../api";
import dino from "../assets/dino.png";

export function Login({ onDone }: { onDone: (email: string) => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const signup = mode === "signup";

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    (signup ? api.signup : api.login)(email, password)
      .then((r) => onDone(r.email))
      .catch((x) => setErr(String((x as Error).message)))
      .finally(() => setBusy(false));
  };

  return (
    <div className="page onboarding">
      <img className="login-mascot" src={dino} alt="Dino" />
      <h1>{signup ? "Créer un compte" : "Se connecter"}</h1>
      <p className="lead">Découvrez ce qui est couvert sur votre véhicule et comprenez votre assurance simplement.</p>
      <form className="card login" onSubmit={submit}>
        <label className="field">
          <span>Adresse e-mail</span>
          <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="field">
          <span>Mot de passe</span>
          <input type="password" autoComplete={signup ? "new-password" : "current-password"} required minLength={signup ? 8 : undefined}
            value={password} onChange={(e) => setPassword(e.target.value)} />
          {signup && <small className="muted">8 caractères minimum.</small>}
        </label>
        {err && <p className="banner warn">{err}</p>}
        <button className="btn" type="submit" disabled={busy}>{busy ? "Patientez…" : signup ? "Créer mon compte" : "Se connecter"}</button>
      </form>
      <button className="link center-link" onClick={() => { setMode(signup ? "login" : "signup"); setErr(null); }}>
        {signup ? "J'ai déjà un compte : me connecter" : "Pas encore de compte ? En créer un"}
      </button>
    </div>
  );
}
