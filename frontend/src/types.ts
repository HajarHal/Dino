// Miroir de la réponse de GET /api/dossier (ica/coverage_view.py) et des autres routes de ica/api.py.

export type Status = "covered" | "partial" | "not_covered" | "unknown" | "none";
export type Fault = "at_fault" | "not_at_fault";
/** Situations habituelles, plus « cp1 », « cp2 »… : une par garantie de la CP qu'aucune situation n'affiche. */
export type CaseId = string;

export interface Insurer { id: string; label: string; full_name?: string | null; cg_kind: "official" | "missing"; product?: string | null }
export interface Meta { llm_available: boolean; llm_error?: string | null; insurers: Insurer[]; car_models: { key: string; make: string; model: string }[] }
export interface Profile { insurer_id?: string; cp_id?: string; car_key?: string }
export interface DocSummary {
  id: string; filename: string; created_at?: string; pages: number; read: boolean; insurer_id?: string | null;
  policy_number?: string | null; period_end?: string | null; vehicle?: string | null; lines: number;
}
export interface Job { id: string; status: "RUNNING" | "DONE" | "FAILED"; message: string; activity?: string | null; error?: string | null; elapsed_s: number;
  result?: { document_id: string; lines: number; detected_insurer?: string | null } }

/** Extrait des Conditions Générales, avec son article. */
export interface Excerpt { text: string; ref?: string | null; codes?: string[]; src?: ClauseSource }

// ---- Explications visuelles (ica/explain.py) : des codes (clés de copy/fr.json) et des valeurs.
/** Source d'un élément : le verbatim et où le lire. */
export interface ClauseSource { doc: "CG" | "CP"; ref?: string | null; article?: string | null; page?: number | null; url?: string | null; texts: string[] }
export interface Franchise {
  kind: "NONE" | "FIXED" | "PERCENT" | "PERCENT_MIN" | "PERCENT_MIN_MAX"; percent: number | null; min: number | null;
  max: number | null; fixed: number | null; base: "DAMAGE" | "VEHICLE_VALUE" | "INDEMNITY" | "UNKNOWN";
}
export interface CodedClause { code: string; source: ClauseSource }
export interface Tile {
  code: string; icon: string; label_key: string; value_key: string; sub_key: string | null;
  vars: Record<string, number | string | null>; review: boolean; source: ClauseSource | null;
}
export interface Visual {
  gcode?: string | null; plafond_dh?: number | null; franchise?: Franchise | null;
  cover_codes?: CodedClause[]; exclusion_codes?: CodedClause[]; condition_codes?: CodedClause[]; note_codes?: CodedClause[];
  unclassified?: { text: string; source: ClauseSource }[]; source?: ClauseSource | null;
}
export interface Entry { code: string; short: string; title: string; note?: string | null; ref?: string | null; conditional: boolean; limit?: string | null; deductible?: string | null; amount?: number | null; franchise?: Franchise | null }
export interface Part {
  zone: string; label: string; status: Status; subtitle?: string | null; amount?: string | null;
  deductible?: string | null; note?: string | null; note_ref?: string | null; entries: Entry[];
  plafond_dh?: number | null; franchise?: Franchise | null;
}
export interface Row extends Visual {
  code: string; title: string; plain: string; covers: string[]; not_covered: string[]; conditions: string[]; ref: string;
  subscribed: boolean; status: Status; limit?: string | null; deductible?: string | null; cp_label?: string | null; to_check: boolean;
  also?: { label: string; limit?: string | null }[];
  /** Ligne classée par l'IA (garantie inconnue des règles) : citation des CG vérifiée dans le PDF. */
  ai?: { status: "suggested" | "confirmed"; label: string; guarantee: string };
}
export interface View {
  case: CaseId; fault: Fault; fault_relevant: boolean;
  headline: { status: Status; title: string; sub?: string | null; text?: string | null; ref?: string | null;
              gcode?: string | null; subscribed?: boolean; plafond_dh?: number | null; franchise?: Franchise | null; source?: ClauseSource | null };
  who_pays?: { tiles: Tile[]; needs: CodedClause[] } | null;
  notes: Excerpt[]; needs: Excerpt[]; parts: Record<string, Part>;
  car: { status: Status; label: string; amount?: string | null; deductible?: string | null } | null;
  items: Row[];
  extra?: boolean;
}
export interface Photo {
  source: "catalog" | "upload"; url: string; anchors: Record<string, [number, number] | null>;
  credit: string; credit_url?: string; exact: boolean; label: string; key?: string; detected_by?: string;
}
export interface Source { kind: "official" | "missing"; document?: string | null; version?: string | null; product?: string | null; pdf_url?: string | null }
export interface CGDoc {
  source: Source; insurer: string; mine: Row[];
  others: { code: string; title: string; plain: string; ref: string; gcode?: string | null; source?: ClauseSource | null }[];
  deadlines: { title: string; value: string; text: string; ref: string }[];
  claim_steps: Excerpt[]; documents_needed: Excerpt[];
  fault: { at_fault: Excerpt[]; not_at_fault: Excerpt[]; needs: Excerpt[] };
  compensation: { title: string; text: string; ref: string; src: ClauseSource }[];
  contract_life: { title: string; text: string; ref: string; src: ClauseSource }[];
  common_exclusions: Excerpt[]; contacts: { label: string; phone: string }[];
  timeline: { items: { code: string; n: number; unit: string; source: ClauseSource }[]; other: { text: string; source: ClauseSource }[] };
  steps: { items: { code: string; delay: { n: number; unit: string } | null; source: ClauseSource }[]; other: { text: string; source: ClauseSource }[] };
  who_pays: { at_fault: Tile[]; not_at_fault: Tile[]; needs: CodedClause[] } | null;
  territory: { code: string; source: ClauseSource } | null;
}
export interface CPDoc {
  contract: [string, string][]; status: string; vehicle: [string, string][];
  lines: { label: string; code?: string | null; title?: string | null; plain?: string | null; ref?: string | null; section: string; limit?: string | null;
           deductible?: string | null; premium?: string | null; to_check: boolean;
           gcode?: string | null; plafond_dh?: number | null; franchise?: Franchise | null }[];
  damage_example: { guarantee: string; deductible: string; rows: { cost: string; you: string; insurer: string }[];
                    gcode?: string | null; franchise?: Franchise | null; plafond_dh?: number | null } | null;
  warnings: string[];
  checks: string[]; app_warnings: string[]; period: { start: string | null; end: string | null }; usage_code: string | null;
}
/** Ligne de la CP qu'aucune situation n'affiche (libellé non reconnu ou garantie sans cas). */
export interface OtherLine {
  label: string; code?: string | null; recognized: boolean; title?: string | null; plain?: string | null; ref?: string | null;
  status: Status; limit?: string | null; deductible?: string | null; to_check: boolean;
}
export interface Dossier {
  insurer: { id: string; label: string; source: Source };
  insurer_mismatch: boolean; detected_insurer?: string | null;
  policy: { document_id: string; number?: string | null; status: "active" | "expired" | "upcoming" | "unknown";
            period_start?: string | null; period_end?: string | null; complete: boolean; rc_limit?: string | null; pages: number };
  vehicle: { title: string; registration?: string | null; year?: number | null; energy?: string | null; model_known: boolean };
  cases: { id: CaseId; label: string; status: Status; extra?: boolean }[];
  views: Record<string, View>;
  other_lines: OtherLine[];
  ai_pending: string[];
  documents: { cg: CGDoc; cp: CPDoc };
  photo: Photo;
}
