import type { DocSummary, Dossier, Job, Meta, Profile } from "./types";

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const b = await r.json(); msg = typeof b.detail === "string" ? b.detail : msg; } catch { /* corps non JSON */ }
    const e = new Error(msg) as Error & { status?: number };
    e.status = r.status;
    if (r.status === 401 && !url.startsWith("/api/auth/")) window.dispatchEvent(new Event("auth:lost"));
    throw e;
  }
  return r.json() as Promise<T>;
}
const json = (method: string, body: unknown): RequestInit => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});
const form = (field: string, files: File[]): RequestInit => {
  const fd = new FormData();
  files.forEach((f) => fd.append(field, f));
  return { method: "POST", body: fd };
};

export const api = {
  meta: () => req<Meta>("/api/meta"),
  profile: () => req<Profile>("/api/profile"),
  setProfile: (p: Partial<Profile>) => req<Profile>("/api/profile", json("PUT", p)),
  documents: () => req<DocSummary[]>("/api/documents"),
  uploadCP: (files: File[]) => req<{ job_id: string }>("/api/documents/cp", form("files", files)),
  loadSample: () => req<{ document_id: string }>("/api/documents/cp/sample", { method: "POST" }),
  me: () => req<{ email: string }>("/api/auth/me"),
  login: (email: string, password: string) => req<{ email: string }>("/api/auth/login", json("POST", { email, password })),
  signup: (email: string, password: string) => req<{ email: string }>("/api/auth/signup", json("POST", { email, password })),
  /** « Quitter » : ferme la session ; les contrats restent dans le compte. */
  logout: () => req<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  deleteDocument: (id: string) => req<{ ok: boolean }>(`/api/documents/${id}`, { method: "DELETE" }),
  job: (id: string) => req<Job>(`/api/jobs/${id}`),
  dossier: (cp?: string) => req<Dossier>("/api/dossier" + (cp ? `?cp=${cp}` : "")),
  uploadPhoto: (cp: string, file: File) => req<unknown>(`/api/documents/${cp}/vehicle-photo`, form("file", [file])),
  deletePhoto: (cp: string) => req<unknown>(`/api/documents/${cp}/vehicle-photo`, { method: "DELETE" }),
  /** Confirme ou refuse le classement proposé par l'IA ; l'application recharge ensuite le dossier. */
  decideClassification: (label: string, decision: "confirm" | "reject", insurer_id?: string) =>
    req<{ ok: boolean; status: string }>("/api/classifications", json("PUT", { label, decision, insurer_id })),
  pageUrl: (cp: string, page: number) => `/api/documents/${cp}/pages/${page}`,
};

export async function waitJob(id: string, onTick: (j: Job) => void): Promise<Job> {
  for (;;) {
    const j = await api.job(id);
    onTick(j);
    if (j.status !== "RUNNING") return j;
    await new Promise((r) => setTimeout(r, 1200));
  }
}
