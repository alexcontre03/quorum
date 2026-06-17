import type {
  Commitment,
  CommitmentEvent,
  CommitmentState,
  FollowupType,
  ItemType,
  ValidationStatus,
} from "./types";

export function itemTypeLabel(type: ItemType): string {
  return { task: "task", ambiguous_task: "ambiguous", technical_decision: "decision" }[type] ?? type;
}

export function validationLabel(status: ValidationStatus): string {
  return { pending_review: "pending", approved: "approved", rejected: "rejected" }[status] ?? status;
}

export function followupLabel(type: FollowupType): string {
  return (
    {
      recurring_unresolved: "Recurrente sin resolver",
      scope_change: "Cambio de alcance",
      new_blocker: "Bloqueo nuevo",
      blocker_resolved: "Bloqueo resuelto",
      possible_duplicate: "Posible duplicado",
      contradicts_decision: "Contradice decision",
      verbal_close: "Cierre verbal",
    }[type] ?? type
  );
}

// ---------------- Compromiso: derivación de display ----------------

export function commitmentStateLabel(state: CommitmentState): string {
  return (
    {
      detected: "Detectado",
      validated: "Validado",
      registered: "En Jira",
      in_code_review: "En revision",
      evidenced: "Con evidencia",
      closed: "Cerrado",
      rejected: "Descartado",
    }[state] ?? state
  );
}

/** Paso del ciclo (1..5) al que ha llegado el compromiso. rejected → 0. */
export function lifecycleStep(state: CommitmentState): number {
  return (
    {
      detected: 1,
      validated: 2,
      registered: 3,
      in_code_review: 4,
      evidenced: 5,
      closed: 6,
      rejected: 0,
    }[state] ?? 0
  );
}

export const LIFECYCLE_STEPS: { state: CommitmentState; label: string }[] = [
  { state: "detected", label: "Detectado" },
  { state: "validated", label: "Validado" },
  { state: "registered", label: "En Jira" },
  { state: "in_code_review", label: "En revision" },
  { state: "evidenced", label: "Evidencia Git" },
  { state: "closed", label: "Cerrado" },
];

export type SignalRole = "neutral" | "info" | "attention" | "alert" | "success";

interface SignalInfo {
  label: string;
  role: SignalRole;
}

/** Etiqueta corta para badge (más concisa que `followupLabel`). */
export function followupSignal(type: FollowupType): SignalInfo {
  return (
    {
      recurring_unresolved: { label: "Recurrente", role: "attention" },
      new_blocker: { label: "Bloqueado", role: "alert" },
      contradicts_decision: { label: "Contradice decisión", role: "alert" },
      scope_change: { label: "Cambio de alcance", role: "attention" },
      possible_duplicate: { label: "Posible duplicado", role: "neutral" },
      blocker_resolved: { label: "Desbloqueado", role: "success" },
      verbal_close: { label: "Cierre verbal", role: "success" },
    } as const
  )[type];
}

/** Devuelve el último evento de tipo `followup` en el timeline, o null. */
export function latestFollowupEvent(commitment: Commitment): CommitmentEvent | null {
  for (let i = commitment.timeline.length - 1; i >= 0; i--) {
    const ev = commitment.timeline[i];
    if (ev.event_type === "followup" && ev.followup_type) return ev;
  }
  return null;
}

/** Señal (label + role) que se muestra en el tablero por compromiso. */
export function commitmentSignal(commitment: Commitment): SignalInfo {
  const latest = latestFollowupEvent(commitment);
  if (latest && latest.followup_type) return followupSignal(latest.followup_type);
  if (commitment.state === "evidenced") return { label: "Con evidencia", role: "success" };
  if (commitment.state === "closed") return { label: "Hecho", role: "success" };
  return { label: "Al día", role: "neutral" };
}

/** "Necesitan atención" si la señal es de rol attention o alert. */
export function needsAttention(commitment: Commitment): boolean {
  const sig = commitmentSignal(commitment);
  return sig.role === "attention" || sig.role === "alert";
}

/** Cuenta de reuniones distintas en las que aparece el compromiso (por run_id en timeline). */
export function meetingsCount(commitment: Commitment): number {
  const ids = new Set<string>();
  for (const ev of commitment.timeline) {
    if (ev.run_id) ids.add(ev.run_id);
  }
  return ids.size;
}
