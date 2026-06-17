import { useState } from "react";
import { Link } from "react-router-dom";
import type { DetectedItem } from "../types";
import { itemTypeLabel, validationLabel } from "../labels";
import { Pill } from "./Pill";

interface ItemCardProps {
  item: DetectedItem;
  index: number;
  runId: string | null;
  onValidate?: (index: number, status: "approved" | "rejected") => Promise<void>;
  onCreateJira?: (index: number) => Promise<void>;
  defaultExpanded?: boolean;
  /** Modo compacto: sin detalle expandible; muestra cita inline y enlace al detalle del compromiso. */
  compact?: boolean;
}

export function ItemCard({
  item,
  index,
  runId,
  onValidate,
  onCreateJira,
  defaultExpanded,
  compact,
}: ItemCardProps) {
  const [expanded, setExpanded] = useState(!!defaultExpanded);
  const [busy, setBusy] = useState(false);

  const status = item.validation_status ?? "pending_review";
  const canValidate = item.item_type !== "technical_decision" && !!runId;
  const hasDetail =
    !compact &&
    (!!item.summary ||
      !!item.evidence ||
      !!item.issue_draft ||
      item.jira_matches.length > 0 ||
      !!item.git_evidence);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className={`item${expanded ? " expanded" : ""}${compact ? " compact" : ""}`}>
      <div className="item-head">
        {!compact && (
          <button
            type="button"
            className="item-toggle"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            disabled={!hasDetail}
          >
            <span className={`chevron${expanded ? " open" : ""}`} aria-hidden>
              ›
            </span>
          </button>
        )}

        <div className="item-main">
          <div className="item-title-row">
            <span className="item-title">{item.title}</span>
            <div className="item-tags">
              <Pill text={itemTypeLabel(item.item_type)} variant={item.item_type} />
              <Pill text={item.confidence} />
              {canValidate && <Pill text={validationLabel(status)} variant={`validation-${status}`} />}
              {item.git_evidence && (
                <Pill text={`git: ${item.git_evidence.evidence_level}`} variant={`evidence-${item.git_evidence.evidence_level}`} />
              )}
              {item.jira_created_issue && <Pill text={item.jira_created_issue.issue_key} variant="task" />}
            </div>
          </div>
          <div className="item-sub">
            {item.speaker}
            {item.timestamp ? ` · ${item.timestamp}` : ""}
          </div>
          {compact && item.evidence && (
            <div className="item-evidence-compact">“{item.evidence}”</div>
          )}
        </div>

        <div className="item-actions">
          {canValidate && status === "pending_review" && onValidate && (
            <>
              <button type="button" className="btn-approve" disabled={busy} onClick={() => run(() => onValidate(index, "approved"))}>
                Aprobar
              </button>
              <button type="button" className="btn-reject" disabled={busy} onClick={() => run(() => onValidate(index, "rejected"))}>
                Rechazar
              </button>
            </>
          )}
          {canValidate && status === "approved" && item.issue_draft && !item.jira_created_issue && onCreateJira && (
            <button type="button" className="btn-jira" disabled={busy} onClick={() => run(() => onCreateJira(index))}>
              {busy ? "Creando..." : "Crear en Jira"}
            </button>
          )}
          {item.jira_created_issue && (
            <a className="jira-link" href={item.jira_created_issue.url} target="_blank" rel="noreferrer">
              Ver en Jira ↗
            </a>
          )}
          {compact && item.commitment_id && (
            <Link className="jira-link" to={`/compromisos/${item.commitment_id}`}>
              Ver compromiso →
            </Link>
          )}
        </div>
      </div>

      {expanded && hasDetail && (
        <div className="item-detail">
          {item.summary && <p>{item.summary}</p>}
          {item.evidence && (
            <p className="item-evidence">
              <span className="detail-label">Evidencia</span> “{item.evidence}”
            </p>
          )}

          {item.issue_draft && (
            <div className="detail-block">
              <div className="detail-label">Borrador de issue</div>
              <p>
                <strong>{item.issue_draft.title}</strong>
              </p>
              <p>{item.issue_draft.description}</p>
              {item.issue_draft.labels.length > 0 && (
                <div className="meta-row" style={{ marginTop: "0.4rem" }}>
                  {item.issue_draft.labels.map((l) => (
                    <Pill key={l} text={l} />
                  ))}
                </div>
              )}
            </div>
          )}

          {item.jira_matches.length > 0 && (
            <div className="detail-block">
              <div className="detail-label">Posibles issues existentes en Jira</div>
              {item.jira_matches.map((m) => (
                <p key={m.issue_key}>
                  <a href={m.url} target="_blank" rel="noreferrer">
                    {m.issue_key}
                  </a>{" "}
                  — {m.summary} <span className="muted-inline">({m.status})</span>
                </p>
              ))}
            </div>
          )}

          {item.git_evidence && (
            <div className="detail-block">
              <div className="detail-label">
                Evidencia tecnica en Git{" "}
                <Pill text={item.git_evidence.evidence_level} variant={`evidence-${item.git_evidence.evidence_level}`} />
              </div>
              <p>{item.git_evidence.explanation}</p>
              {item.git_evidence.supporting_commits.map((c) => (
                <p key={c.hash} className="commit">
                  <code>{c.hash}</code> {c.message} <span className="muted-inline">— {c.author}, {c.date}</span>
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </article>
  );
}
