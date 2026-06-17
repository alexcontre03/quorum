import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { Commitment, SprintSummary } from "../types";
import {
  meetingsAgoLabel,
  meetingsCount,
  shortMeetingName,
  viewFromCommitment,
  type CommitmentView,
  type Tone,
} from "../commitment";
import { useToast } from "../components/Toast";
import { formatSprintId } from "../sprint";

interface BoardRow extends CommitmentView {
  id: string;
  title: string;
  meetingName: string;
  meetingsAgoText: string;
  sprintId: string | null;
}

const TONE_VAR: Record<Tone, string> = {
  neutral: "var(--text-tertiary)",
  info: "var(--accent)",
  attention: "var(--warning)",
  alert: "var(--danger)",
  success: "var(--success)",
};

export function CommitmentsBoardPage() {
  const toast = useToast();
  const [commitments, setCommitments] = useState<Commitment[]>([]);
  const [sprints, setSprints] = useState<SprintSummary[]>([]);
  const [selectedSprintId, setSelectedSprintId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    // Commitments are required; sprints are optional decoration.
    // If the backend is older and /api/sprints is not yet available, the board still loads.
    api
      .listCommitments(100)
      .then((all) => {
        const userFacing = all.filter(
          (c) => c.item_type !== "technical_decision" && c.state !== "rejected"
        );
        setCommitments(userFacing);
      })
      .catch((err) => toast.error((err as Error).message))
      .finally(() => setLoading(false));

    api
      .listSprints()
      .then(setSprints)
      .catch(() => setSprints([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleRefreshAll() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      const result = await api.refreshAllCommitments();
      const reloaded = await api.listCommitments(100);
      setCommitments(
        reloaded.filter(
          (c) => c.item_type !== "technical_decision" && c.state !== "rejected"
        )
      );
      if (result.changed === 0) {
        toast.success(`Sin cambios en ${result.refreshed} compromisos consultados.`);
      } else {
        toast.success(
          `${result.changed} actualizado${result.changed === 1 ? "" : "s"} de ${result.refreshed}.`
        );
      }
    } catch (err) {
      toast.error(`No se pudo refrescar: ${(err as Error).message}`);
    } finally {
      setRefreshing(false);
    }
  }

  const filteredCommitments = useMemo(() => {
    if (selectedSprintId === null) return commitments;
    return commitments.filter((c) => c.origin.sprint_id === selectedSprintId);
  }, [commitments, selectedSprintId]);

  const rows: BoardRow[] = useMemo(
    () =>
      filteredCommitments.map((c) => {
        const view = viewFromCommitment(c);
        const n = meetingsCount(c);
        return {
          ...view,
          id: c.commitment_id,
          title: c.title,
          meetingName: shortMeetingName(c.origin.meeting_title),
          meetingsAgoText: meetingsAgoLabel(n),
          sprintId: c.origin.sprint_id,
        };
      }),
    [filteredCommitments]
  );

  const { attention, rest, counts } = useMemo(() => {
    const attention = rows.filter((r) => r.needsAttention);
    const rest = rows.filter((r) => !r.needsAttention);
    const done = rows.filter((r) => r.stage === "closed").length;
    return {
      attention,
      rest,
      counts: { active: rows.length - done, attention: attention.length, done },
    };
  }, [rows]);

  const showSprintChips =
    sprints.filter((s) => s.sprint_id !== null).length > 0;

  return (
    <div className="cb">
      <p className="cb-eyebrow">Trazabilidad</p>
      <h1 className="cb-h1">Compromisos</h1>
      <p className="cb-lede">Todo lo que el equipo se comprometió a hacer, y en qué punto está.</p>

      {showSprintChips && (
        <div className="cb-chips" role="tablist" aria-label="Filtrar por sprint">
          <button
            type="button"
            role="tab"
            aria-selected={selectedSprintId === null}
            className="cb-chip"
            data-on={selectedSprintId === null ? "true" : "false"}
            onClick={() => setSelectedSprintId(null)}
          >
            Todos los sprints
          </button>
          {sprints
            .filter((s) => s.sprint_id !== null)
            .map((s) => (
              <button
                key={s.sprint_id as string}
                type="button"
                role="tab"
                aria-selected={selectedSprintId === s.sprint_id}
                className="cb-chip"
                data-on={selectedSprintId === s.sprint_id ? "true" : "false"}
                onClick={() => setSelectedSprintId(s.sprint_id)}
              >
                {formatSprintId(s.sprint_id as string)}
              </button>
            ))}
        </div>
      )}

      <div className="cb-kpis">
        <div className="cb-kpi">
          <span className="cb-kpi-n">{counts.active}</span>
          <span className="cb-kpi-l">activos</span>
        </div>
        <div className="cb-kpi">
          <span className="cb-kpi-n" style={{ color: "var(--warning)" }}>
            {counts.attention}
          </span>
          <span className="cb-kpi-l">necesitan atención</span>
        </div>
        <div className="cb-kpi">
          <span className="cb-kpi-n" style={{ color: "var(--success)" }}>
            {counts.done}
          </span>
          <span className="cb-kpi-l">ya hechos</span>
        </div>
        <button
          type="button"
          className="cb-cta cb-cta-secondary"
          onClick={handleRefreshAll}
          disabled={refreshing}
          title="Consulta Jira y Git para todos los activos"
        >
          {refreshing ? "Refrescando…" : "↻ Refrescar todos"}
        </button>
        <Link to="/analizar" className="cb-cta">
          + Analizar reunión
        </Link>
      </div>

      {loading && <p className="cb-muted">Cargando compromisos…</p>}

      {!loading && rows.length === 0 && (
        <div className="cb-empty">
          {selectedSprintId === null ? (
            <>
              <p>Todavía no hay compromisos.</p>
              <Link to="/analizar" className="cb-cta">
                Analizar una reunión
              </Link>
            </>
          ) : (
            <p>No hay compromisos en este sprint.</p>
          )}
        </div>
      )}

      {attention.length > 0 && (
        <section className="cb-section">
          <p className="cb-section-label">Necesitan atención</p>
          {attention.map((r) => (
            <Row key={r.id} r={r} />
          ))}
        </section>
      )}

      {rest.length > 0 && (
        <section className="cb-section">
          <p className="cb-section-label">Al día</p>
          {rest.map((r) => (
            <Row key={r.id} r={r} />
          ))}
        </section>
      )}

      <p className="cb-research">
        <Link to="/evaluacion">Evaluación del modelo →</Link>
        <br />
        <span>medición de la IA (CDIA), no parte del producto del Scrum Master</span>
      </p>
    </div>
  );
}

function Row({ r }: { r: BoardRow }) {
  return (
    <Link to={`/compromisos/${r.id}`} className="cb-row">
      <div className="cb-row-main">
        <p className="cb-row-title">{r.title}</p>
        <p className="cb-row-sub">
          se dijo en la reunión de {r.meetingName} · {r.meetingsAgoText}
        </p>
      </div>
      <LifeDots index={r.stageIndex} />
      <span className="cb-row-tag" style={{ color: TONE_VAR[r.statusTone] }}>
        {r.statusText}
      </span>
    </Link>
  );
}

function LifeDots({ index }: { index: number }) {
  return (
    <div className="cb-dots" aria-hidden>
      {[0, 1, 2, 3, 4].map((i) => (
        <span key={i} className="cb-dot" data-on={i <= index ? "true" : "false"} />
      ))}
    </div>
  );
}

