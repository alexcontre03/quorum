// frontend/src/commitment.ts
//
// Capa de "vista" del compromiso para la UI: traducción única del lenguaje del pipeline
// al lenguaje del usuario.
//
// Trabaja sobre la entidad `Commitment` de tipos.ts (que ya tiene `state` y `timeline`).
// No deriva el estado desde DetectedItem.
//
// Si en algún componente escribes literales como "approved" o "pending_review", es bug.

import type { Commitment, CommitmentEvent, CommitmentState, FollowupType } from "./types";

export type LifeStage =
  | "said"
  | "confirmed"
  | "board"
  | "review"
  | "evidence"
  | "closed";

export const STAGE_ORDER: LifeStage[] = [
  "said",
  "confirmed",
  "board",
  "review",
  "evidence",
  "closed",
];

export const STAGE_LABEL: Record<LifeStage, string> = {
  said: "Se dijo",
  confirmed: "Confirmado",
  board: "En el tablero",
  review: "En revisión de código",
  evidence: "Código a medias",
  closed: "Cerrado",
};

export type Tone = "neutral" | "info" | "attention" | "alert" | "success";

export interface CommitmentView {
  stage: LifeStage;
  stageIndex: number;
  statusText: string;
  statusTone: Tone;
  needsAttention: boolean;
}

// CommitmentState (backend) -> LifeStage (UI) cuando no hay señal de seguimiento más fuerte.
function stateToStage(state: CommitmentState): LifeStage {
  switch (state) {
    case "closed":
      return "closed";
    case "evidenced":
      return "evidence";
    case "in_code_review":
      return "review";
    case "registered":
      return "board";
    case "validated":
      return "confirmed";
    case "rejected":
    case "detected":
    default:
      return "said";
  }
}

export function latestFollowup(commitment: Commitment): CommitmentEvent | null {
  // Si el usuario descartó el aviso de duplicado en algún momento, ese
  // `possible_duplicate` previo deja de contar. Cualquier follow-up posterior
  // sigue siendo válido. Iteramos en orden inverso: si vemos primero un
  // `duplicate_dismissed`, marcamos la bandera y saltamos los duplicados
  // anteriores.
  let duplicateDismissed = false;
  for (let i = commitment.timeline.length - 1; i >= 0; i--) {
    const ev = commitment.timeline[i];
    if (ev.event_type === "duplicate_dismissed") {
      duplicateDismissed = true;
      continue;
    }
    if (ev.event_type === "followup" && ev.followup_type) {
      if (ev.followup_type === "possible_duplicate" && duplicateDismissed) {
        continue;
      }
      return ev;
    }
  }
  return null;
}

/** ¿Hay un aviso de duplicado vivo que el usuario aún no descartó? */
export function hasActiveDuplicateFlag(commitment: Commitment): boolean {
  for (let i = commitment.timeline.length - 1; i >= 0; i--) {
    const ev = commitment.timeline[i];
    if (ev.event_type === "duplicate_dismissed") return false;
    if (ev.event_type === "followup" && ev.followup_type === "possible_duplicate") {
      return true;
    }
  }
  return false;
}

/** Cuenta de reuniones distintas en las que aparece el compromiso. */
export function meetingsCount(commitment: Commitment): number {
  const ids = new Set<string>();
  for (const ev of commitment.timeline) {
    if (ev.run_id) ids.add(ev.run_id);
  }
  return ids.size;
}

/** Vista lista para pintar: texto + tono + si necesita atención. */
export function viewFromCommitment(commitment: Commitment): CommitmentView {
  const stage = stateToStage(commitment.state);
  const stageIndex = STAGE_ORDER.indexOf(stage);
  const followup = latestFollowup(commitment);
  const followupType = (followup?.followup_type ?? null) as FollowupType | null;

  let statusText: string;
  let statusTone: Tone;
  let needsAttention = false;

  switch (followupType) {
    case "recurring_unresolved":
      statusText = "Sigue sin cerrarse";
      statusTone = "attention";
      needsAttention = true;
      break;
    case "new_blocker":
      statusText = "Bloqueado";
      statusTone = "alert";
      needsAttention = true;
      break;
    case "contradicts_decision":
      statusText = "Contradice una decisión";
      statusTone = "alert";
      needsAttention = true;
      break;
    case "scope_change":
      statusText = "Cambió el alcance";
      statusTone = "attention";
      needsAttention = true;
      break;
    case "possible_duplicate":
      statusText = "Posible duplicado";
      statusTone = "neutral";
      break;
    case "blocker_resolved":
      statusText = "Desbloqueado";
      statusTone = "success";
      break;
    case "verbal_close":
      statusText = "Cerrado de palabra";
      statusTone = "success";
      break;
    default:
      if (stage === "closed") {
        statusText = "Hecho";
        statusTone = "success";
      } else if (stage === "evidence") {
        statusText = "Hay código que lo prueba";
        statusTone = "success";
      } else if (stage === "board") {
        statusText = "En el tablero";
        statusTone = "info";
      } else if (stage === "confirmed") {
        statusText = "Confirmado";
        statusTone = "info";
      } else {
        statusText = commitment.state === "rejected" ? "Descartado" : "Por revisar";
        statusTone = "neutral";
      }
  }

  return { stage, stageIndex, statusText, statusTone, needsAttention };
}

/** Texto humano breve para un evento del timeline (detalle). */
export function describeEvent(ev: CommitmentEvent): string {
  switch (ev.event_type) {
    case "detected":
      return "Se dijo por primera vez";
    case "validated":
      return "Confirmado en triaje";
    case "rejected":
      return "Descartado";
    case "jira_created":
      return "Llevado al tablero";
    case "jira_status_refreshed":
      return "Estado refrescado desde Jira";
    case "jira_sync_failed":
      return "Jira no se pudo sincronizar";
    case "jira_scope_synced":
      return "Tablero actualizado con el nuevo alcance";
    case "jira_blocker_labeled":
      return "Issue etiquetado como bloqueado";
    case "jira_blocker_cleared":
      return "Etiqueta de bloqueo retirada del issue";
    case "git_evidence_updated":
      return "Aparece código que lo respalda";
    case "github_evidence_updated":
      return "Actividad detectada en GitHub";
    case "duplicate_dismissed":
      return "Descartas que sea duplicado";
    case "scope_changed":
      return "Cambió el alcance";
    case "closed":
      return "Cerrado";
    case "followup": {
      const t = ev.followup_type as FollowupType | null;
      switch (t) {
        case "recurring_unresolved":
          return "Vuelve a salir y sigue sin cerrarse";
        case "new_blocker":
          return "Aparece un bloqueo";
        case "contradicts_decision":
          return "Contradice una decisión anterior";
        case "scope_change":
          return "Le cambia el alcance";
        case "possible_duplicate":
          return "Podría ser duplicado";
        case "blocker_resolved":
          return "Se desbloquea";
        case "verbal_close":
          return "Se da por cerrado de palabra";
        default:
          return "Vuelve a salir";
      }
    }
    default:
      return ev.event_type;
  }
}

/** Tono para el punto del timeline. */
export function eventTone(ev: CommitmentEvent): Tone {
  if (ev.event_type === "followup" && ev.followup_type) {
    const t = ev.followup_type as FollowupType;
    if (t === "new_blocker" || t === "contradicts_decision") return "alert";
    if (t === "recurring_unresolved" || t === "scope_change") return "attention";
    if (t === "blocker_resolved" || t === "verbal_close") return "success";
    return "neutral";
  }
  if (ev.event_type === "rejected") return "alert";
  if (
    ev.event_type === "closed" ||
    ev.event_type === "git_evidence_updated" ||
    ev.event_type === "jira_blocker_cleared"
  )
    return "success";
  if (
    ev.event_type === "jira_created" ||
    ev.event_type === "validated" ||
    ev.event_type === "jira_scope_synced" ||
    ev.event_type === "jira_status_refreshed" ||
    ev.event_type === "github_evidence_updated"
  )
    return "info";
  if (ev.event_type === "scope_changed" || ev.event_type === "jira_blocker_labeled")
    return "attention";
  if (ev.event_type === "jira_sync_failed") return "alert";
  return "neutral";
}

/** Nombre corto de reunión a partir del título completo, para el tablero
 *  ("Ciclo 1 de observabilidad..." → "observabilidad"). Heurística: última palabra
 *  significativa o "reunión" como fallback. */
export function shortMeetingName(meetingTitle: string): string {
  if (!meetingTitle) return "una reunión";
  const lower = meetingTitle.toLowerCase();
  const hints = [
    "observabilidad",
    "login",
    "billing",
    "facturación",
    "mobile",
    "release",
    "soporte",
    "autenticación",
  ];
  for (const h of hints) {
    if (lower.includes(h)) return h;
  }
  return meetingTitle.split(/\s+/).slice(-1)[0]?.toLowerCase() ?? "reunión";
}

/** "hace N reuniones" / "esta reunión" */
export function meetingsAgoLabel(n: number): string {
  if (n <= 1) return "esta reunión";
  return `hace ${n} reuniones`;
}
