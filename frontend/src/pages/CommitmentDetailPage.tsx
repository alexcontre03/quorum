import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import type {
  Commitment,
  GitHubEvidence,
  GitHubPullRequest,
  PersistedAnalysisRun,
  SegmentContext,
} from "../types";
import {
  describeEvent,
  eventTone,
  hasActiveDuplicateFlag,
  meetingsCount,
  STAGE_LABEL,
  STAGE_ORDER,
  viewFromCommitment,
  type Tone,
} from "../commitment";
import { useToast } from "../components/Toast";
import { formatSprintId } from "../sprint";

const TONE_VAR: Record<Tone, string> = {
  neutral: "var(--text-tertiary)",
  info: "var(--accent)",
  attention: "var(--warning)",
  alert: "var(--danger)",
  success: "var(--success)",
};

const TONE_BG: Record<Tone, string> = {
  neutral: "var(--border-strong)",
  info: "var(--accent)",
  attention: "var(--warning)",
  alert: "var(--danger)",
  success: "var(--success)",
};

export function CommitmentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const toast = useToast();
  const navigate = useNavigate();
  const [commitment, setCommitment] = useState<Commitment | null>(null);
  const [sourceRun, setSourceRun] = useState<PersistedAnalysisRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const [context, setContext] = useState<SegmentContext | null>(null);
  const [loadingContext, setLoadingContext] = useState(false);

  useEffect(() => {
    if (!id) return;
    setLoading(true);
    api
      .getCommitment(id)
      .then(async (c) => {
        setCommitment(c);
        try {
          setSourceRun(await api.getRun(c.origin.source_run_id));
        } catch {
          setSourceRun(null);
        }
      })
      .catch((err) => toast.error((err as Error).message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const itemIndex = useMemo(() => {
    if (!commitment || !sourceRun) return -1;
    return sourceRun.analysis.items.findIndex(
      (it) => it.commitment_id === commitment.commitment_id
    );
  }, [commitment, sourceRun]);

  const sourceItem = itemIndex >= 0 && sourceRun ? sourceRun.analysis.items[itemIndex] : null;

  async function refresh() {
    if (!id) return;
    try {
      const c = await api.getCommitment(id);
      setCommitment(c);
      setSourceRun(await api.getRun(c.origin.source_run_id));
    } catch {
      /* swallow refresh errors */
    }
  }

  async function handleValidate(status: "approved" | "rejected") {
    if (!sourceRun || itemIndex < 0) return;
    setActing(true);
    try {
      await api.patchValidation(sourceRun.run_id, itemIndex, status);
      await refresh();
      toast.success(status === "approved" ? "Confirmado" : "Descartado");
    } catch (err) {
      toast.error(`No se pudo actualizar: ${(err as Error).message}`);
    } finally {
      setActing(false);
    }
  }

  async function toggleContext() {
    if (!commitment) return;
    if (contextOpen) {
      setContextOpen(false);
      return;
    }
    if (context) {
      setContextOpen(true);
      return;
    }
    if (commitment.origin.segment_index === null) return;
    setLoadingContext(true);
    try {
      const ctx = await api.getTranscriptContext(
        commitment.origin.transcript_id,
        commitment.origin.segment_index,
        2
      );
      setContext(ctx);
      setContextOpen(true);
    } catch (err) {
      toast.error(`No se pudo cargar el contexto: ${(err as Error).message}`);
    } finally {
      setLoadingContext(false);
    }
  }

  async function handleRefresh() {
    if (!id || acting) return;
    setActing(true);
    try {
      const result = await api.refreshCommitment(id);
      if (result.commitment) setCommitment(result.commitment);
      try {
        setSourceRun(await api.getRun(result.commitment?.origin.source_run_id || sourceRun?.run_id || ""));
      } catch {
        /* ignore */
      }
      const { refresh: refreshInfo } = result;
      if (!refreshInfo.changed) {
        if (!refreshInfo.jira_configured && !refreshInfo.git_configured) {
          toast.error("Ni Jira ni Git están configurados, no hay nada que refrescar.");
        } else {
          toast.success("Sin cambios desde la última consulta.");
        }
        return;
      }
      const summary = refreshInfo.changes
        .map((c) => (c.source === "jira" ? "Jira" : "Git"))
        .join(" + ");
      toast.success(`Actualizado desde ${summary}`);
    } catch (err) {
      toast.error(`No se pudo refrescar: ${(err as Error).message}`);
    } finally {
      setActing(false);
    }
  }

  async function handleDismissDuplicate() {
    if (!commitment || acting) return;
    setActing(true);
    try {
      const res = await api.dismissDuplicate(commitment.commitment_id);
      if (res.changed) {
        setCommitment(res.commitment);
        toast.success("Aviso de duplicado descartado");
      } else {
        toast.info("No había aviso activo");
      }
    } catch (err) {
      toast.error(`No se pudo descartar: ${(err as Error).message}`);
    } finally {
      setActing(false);
    }
  }

  async function handleCreateJira() {
    if (!sourceRun || itemIndex < 0) return;
    setActing(true);
    try {
      await api.createJiraIssue(sourceRun.run_id, itemIndex);
      await refresh();
      toast.success("Llevado al tablero");
    } catch (err) {
      toast.error(`No se pudo crear en Jira: ${(err as Error).message}`);
    } finally {
      setActing(false);
    }
  }

  if (loading) {
    return (
      <div className="cd">
        <p className="cb-muted">Cargando…</p>
      </div>
    );
  }

  if (!commitment) {
    return (
      <div className="cd">
        <Link to="/" className="cd-back">
          ← Compromisos
        </Link>
        <p className="cb-muted">No se ha encontrado el compromiso.</p>
        <button type="button" className="cd-action" onClick={() => navigate("/")}>
          Volver al tablero
        </button>
      </div>
    );
  }

  const view = viewFromCommitment(commitment);
  const n = meetingsCount(commitment);
  const speaker = commitment.origin.speaker || "Alguien";
  const detectedSince =
    n <= 1 ? "detectado en esta reunión" : `detectado hace ${n} reuniones`;

  const canValidate = sourceItem !== null && sourceItem.validation_status === "pending_review";
  const canCreateJira =
    sourceItem !== null &&
    sourceItem.validation_status === "approved" &&
    sourceItem.issue_draft !== null &&
    sourceItem.jira_created_issue === null;

  const reversedTimeline = [...commitment.timeline].reverse();

  const triggerQuote = commitment.origin.evidence || "";

  return (
    <div className="cd cd-doc">
      <div className="cd-doc-main">
        <div className="cd-topbar">
          <Link to="/" className="cd-back">
            ← Compromisos
          </Link>
        </div>

        <p className="cd-eyebrow">
          {commitment.origin.sprint_id
            ? `${formatSprintId(commitment.origin.sprint_id)} · `
            : ""}
          {commitment.origin.meeting_title} · {detectedSince}
        </p>
        <h1 className="cd-h1">{commitment.title}</h1>

        {triggerQuote && (
          <>
            <blockquote className="pullquote cd-pullquote">{triggerQuote}</blockquote>
            <p className="cd-pullquote-cite">
              — {speaker}
              {commitment.origin.timestamp ? ` · ${commitment.origin.timestamp}` : ""}
            </p>
          </>
        )}

        {hasActiveDuplicateFlag(commitment) && (
          <div className="cd-dup-banner" role="status">
            <p className="cd-dup-banner-text">
              El agente cree que esta tarea reaparece como duplicada en una reunión posterior.
              Revisa el aviso en la timeline y, si son tareas distintas, descártalo.
            </p>
            <button
              type="button"
              className="cd-dup-dismiss"
              onClick={handleDismissDuplicate}
              disabled={acting}
            >
              No es duplicado
            </button>
          </div>
        )}

        {(canValidate || canCreateJira) && (
          <div className="cd-actions">
            {canValidate && (
              <>
                <button
                  type="button"
                  className="cd-action is-primary"
                  disabled={acting}
                  onClick={() => handleValidate("approved")}
                >
                  Confirmar
                </button>
                <button
                  type="button"
                  className="cd-action is-danger"
                  disabled={acting}
                  onClick={() => handleValidate("rejected")}
                >
                  Descartar
                </button>
              </>
            )}
            {canCreateJira && (
              <button
                type="button"
                className="cd-action is-primary"
                disabled={acting}
                onClick={handleCreateJira}
              >
                {acting ? "Llevando…" : "Llevar al tablero"}
              </button>
            )}
          </div>
        )}

        <p className="cd-section-label">Cómo ha evolucionado</p>
        <div className="cd-evo">
        {reversedTimeline.map((ev, i) => {
          const isDetected = ev.event_type === "detected";
          const tone = eventTone(ev);
          const quote = ev.trigger_quote || (isDetected ? commitment.origin.evidence : "");
          // Show the agent explanation only when it adds something the quote
          // doesn't already say (avoid the redundant "Mikel dice X" alongside
          // the quote X). For the first detected event the quote IS the body.
          const explanation =
            !isDetected && ev.detail && ev.detail !== ev.trigger_quote
              ? ev.detail
              : "";
          const showRename =
            ev.event_type === "scope_changed" &&
            ev.previous_title &&
            ev.new_title &&
            ev.previous_title !== ev.new_title;
          return (
            <article
              key={i}
              className="cd-evo-card"
              data-tone={tone}
              data-detected={isDetected ? "true" : "false"}
            >
              <header className="cd-evo-head">
                <span
                  className="cd-evo-icon"
                  style={{ background: TONE_BG[tone] }}
                  aria-hidden="true"
                />
                <div className="cd-evo-head-text">
                  <h3 className="cd-evo-title">{describeEvent(ev)}</h3>
                  <p className="cd-evo-meta">
                    {formatDate(ev.meeting_date || ev.recorded_at)}
                    {ev.meeting_title ? ` · ${ev.meeting_title}` : ""}
                  </p>
                </div>
              </header>
              {isDetected && (
                <div className="cd-evo-speaker">
                  <div className="cd-avatar">{initials(speaker)}</div>
                  <p className="cd-evo-speaker-meta">
                    {speaker}
                    {commitment.origin.timestamp ? ` · ${commitment.origin.timestamp}` : ""}
                  </p>
                </div>
              )}
              {quote && <blockquote className="cd-evo-quote">“{quote}”</blockquote>}
              {showRename && (
                <p className="cd-evo-rename">
                  <span className="cd-evo-rename-old">{ev.previous_title}</span>
                  <span className="cd-evo-rename-arrow">→</span>
                  <span className="cd-evo-rename-new">{ev.new_title}</span>
                </p>
              )}
              {explanation && <p className="cd-evo-explanation">{explanation}</p>}
              {isDetected && commitment.origin.segment_index !== null && (
                <>
                  <button
                    type="button"
                    className="cd-evo-context-toggle"
                    onClick={toggleContext}
                    disabled={loadingContext}
                  >
                    {loadingContext
                      ? "Cargando contexto…"
                      : contextOpen
                      ? "Ocultar contexto"
                      : "Ver en contexto"}
                  </button>
                  {contextOpen && context && (
                    <div className="cd-context">
                      {context.segments.map((s) => (
                        <div
                          key={s.index}
                          className="cd-context-seg"
                          data-focus={s.is_focus ? "true" : "false"}
                        >
                          <p className="cd-context-meta">
                            {s.speaker}
                            {s.timestamp ? ` · ${s.timestamp}` : ""}
                          </p>
                          <p className="cd-context-text">{s.text}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )}
            </article>
          );
        })}
      </div>

      {(commitment.jira_created_issue ||
        (commitment.git_evidence && commitment.git_evidence.supporting_commits.length > 0)) && (
        <>
          <p className="cd-section-label">Trazas</p>
          <div className="cd-trace">
            {commitment.jira_created_issue && (
              <a
                className="cd-trace-row"
                href={commitment.jira_created_issue.url}
                target="_blank"
                rel="noreferrer"
              >
                <span style={{ color: "var(--accent)" }}>↗</span>
                <span>{commitment.jira_created_issue.issue_key}</span>
                <span className="cb-row-sub">en Jira</span>
              </a>
            )}
            {commitment.git_evidence?.supporting_commits.map((c) => (
              <div key={c.hash} className="cd-trace-row">
                <code>{c.hash}</code>
                <span>{c.message}</span>
              </div>
            ))}
          </div>
        </>
      )}

        {commitment.github_evidence && (
          <GitHubEvidenceSection evidence={commitment.github_evidence} />
        )}
      </div>

      <aside className="cd-doc-aside">
        <div className="cd-aside-block">
          <p className="eyebrow-small">Estado</p>
          <p className="cd-aside-value" style={{ color: TONE_VAR[view.statusTone] }}>
            ● {view.statusText}
          </p>
        </div>

        <div className="cd-aside-block">
          <p className="eyebrow-small">Ciclo de vida</p>
          <ol className="cd-aside-track">
            {STAGE_ORDER.map((stage, i) => {
              const done = i < view.stageIndex;
              const current = i === view.stageIndex;
              return (
                <li
                  key={stage}
                  className="cd-aside-step"
                  data-done={done ? "true" : "false"}
                  data-current={current ? "true" : "false"}
                >
                  <span className="cd-aside-step-mark" aria-hidden="true">
                    {done ? "✓" : current ? "●" : "·"}
                  </span>
                  <span className="cd-aside-step-label">{STAGE_LABEL[stage]}</span>
                </li>
              );
            })}
          </ol>
        </div>

        <div className="cd-aside-block">
          <p className="eyebrow-small">Asignado</p>
          <p className="cd-aside-value">{speaker}</p>
        </div>

        {commitment.origin.sprint_id && (
          <div className="cd-aside-block">
            <p className="eyebrow-small">Sprint</p>
            <p className="cd-aside-value cd-aside-num">
              {formatSprintId(commitment.origin.sprint_id)}
            </p>
          </div>
        )}

        <div className="cd-aside-block">
          <p className="eyebrow-small">Reunión origen</p>
          <p className="cd-aside-value">{commitment.origin.meeting_title}</p>
        </div>

        {commitment.jira_created_issue && (
          <div className="cd-aside-block">
            <p className="eyebrow-small">Jira</p>
            <a
              className="cd-aside-link"
              href={commitment.jira_created_issue.url}
              target="_blank"
              rel="noreferrer"
            >
              {commitment.jira_created_issue.issue_key} ↗
            </a>
          </div>
        )}

        {commitment.state !== "rejected" && (
          <div className="cd-aside-block">
            <button
              type="button"
              className="cd-refresh cd-aside-refresh"
              onClick={handleRefresh}
              disabled={acting}
              title="Consulta Jira y Git sin analizar reunión"
            >
              {acting ? "Refrescando…" : "↻ Refrescar estado"}
            </button>
          </div>
        )}
      </aside>
    </div>
  );
}

function initials(name: string): string {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  return parts
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}

function formatDate(iso?: string | null): string {
  if (!iso) return "";
  return iso.length === 10 ? iso : iso.slice(0, 10);
}

// ===== GitHub evidence (Decisión 023) =====

const GH_BADGE: Record<GitHubEvidence["evidence_level"], { label: string; tone: string }> = {
  merged: { label: "PR mergeado", tone: "success" },
  in_code_review: { label: "PR en revisión", tone: "info" },
  none: { label: "Sin actividad", tone: "neutral" },
};

function GitHubEvidenceSection({ evidence }: { evidence: GitHubEvidence }) {
  const badge = GH_BADGE[evidence.evidence_level];
  const totalActivity =
    evidence.pull_requests_merged.length +
    evidence.pull_requests_open.length +
    evidence.supporting_commits.length;
  if (totalActivity === 0 && evidence.evidence_level === "none") {
    return null;
  }
  return (
    <>
      <p className="cd-section-label">
        GitHub
        <span className={`cd-gh-badge cd-gh-badge-${badge.tone}`}>{badge.label}</span>
        {evidence.repo && <span className="cb-row-sub"> {evidence.repo}</span>}
      </p>
      <p className="cd-gh-explanation">{evidence.explanation}</p>

      {evidence.pull_requests_merged.length > 0 && (
        <PullRequestList
          title="Mergeados"
          prs={evidence.pull_requests_merged}
          tone="success"
        />
      )}
      {evidence.pull_requests_open.length > 0 && (
        <PullRequestList
          title="Abiertos"
          prs={evidence.pull_requests_open}
          tone="info"
        />
      )}
      {evidence.supporting_commits.length > 0 && (
        <div className="cd-gh-commits">
          <p className="cd-gh-sublabel">Commits relacionados</p>
          {evidence.supporting_commits.map((c) => (
            <div key={c.sha} className="cd-trace-row">
              {c.html_url ? (
                <a href={c.html_url} target="_blank" rel="noreferrer">
                  <code>{c.sha.slice(0, 7)}</code>
                </a>
              ) : (
                <code>{c.sha.slice(0, 7)}</code>
              )}
              <span>{c.message}</span>
              {c.author && <span className="cb-row-sub">{c.author}</span>}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function PullRequestList({
  title,
  prs,
  tone,
}: {
  title: string;
  prs: GitHubPullRequest[];
  tone: "success" | "info";
}) {
  return (
    <div className="cd-gh-prs">
      <p className="cd-gh-sublabel">{title}</p>
      {prs.map((pr) => (
        <a
          key={pr.number}
          className={`cd-gh-pr cd-gh-pr-${tone}`}
          href={pr.html_url}
          target="_blank"
          rel="noreferrer"
        >
          <span className="cd-gh-pr-num">#{pr.number}</span>
          <span className="cd-gh-pr-title">{pr.title}</span>
          {pr.head_ref && (
            <span className="cd-gh-pr-branch">
              {pr.head_ref} → {pr.base_ref || "main"}
            </span>
          )}
          {pr.merged_at && (
            <span className="cb-row-sub">mergeado {formatDate(pr.merged_at)}</span>
          )}
          {pr.author && <span className="cb-row-sub">@{pr.author}</span>}
        </a>
      ))}
    </div>
  );
}

