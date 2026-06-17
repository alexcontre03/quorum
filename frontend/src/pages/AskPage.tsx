import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type {
  ConfidenceBand,
  GuardrailRule,
  QAScope,
  QASource,
  SprintSummary,
} from "../types";
import { useToast } from "../components/Toast";
import { formatSprintId } from "../sprint";

interface SessionEntry {
  id: number;
  question: string;
  sprintLabel: string;
  scopeLabel: string;
  answer: string;
  sources: QASource[];
  status: "streaming" | "done" | "error" | "blocked";
  errorDetail?: string;
  blockRule?: GuardrailRule;
  blockDetail?: string;
  confidence?: ConfidenceBand;
  topSimilarity?: number;
  hallucinatedCitations?: number[];
}

const SUGGESTIONS: Array<{ title: string; body: string }> = [
  {
    title: "Resumen del sprint",
    body: "¿Qué se decidió en la última review y qué quedó pendiente?",
  },
  {
    title: "Bloqueos vivos",
    body: "¿Qué bloqueos siguen abiertos y a quién están esperando?",
  },
  {
    title: "Cambios de alcance",
    body: "¿Qué compromisos han cambiado de alcance esta semana?",
  },
  {
    title: "Cierres tácitos",
    body: "¿Qué tareas se han cerrado solo de palabra sin pasar por Jira?",
  },
];

export function AskPage() {
  const toast = useToast();
  const [sprints, setSprints] = useState<SprintSummary[]>([]);
  const [selectedSprintId, setSelectedSprintId] = useState<string | null>(null);
  const [scope, setScope] = useState<QAScope>("analyzed_only");
  const [question, setQuestion] = useState("");
  const [session, setSession] = useState<SessionEntry[]>([]);
  const [running, setRunning] = useState(false);
  const [expandedSources, setExpandedSources] = useState<Set<string>>(new Set());
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const threadEndRef = useRef<HTMLDivElement | null>(null);
  const counterRef = useRef(0);

  useEffect(() => {
    api
      .listSprints()
      .then((list) => setSprints(list.filter((s) => s.sprint_id !== null)))
      .catch(() => setSprints([]));
  }, []);

  // Auto-grow textarea
  useLayoutEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "0px";
    const next = Math.min(ta.scrollHeight, 240);
    ta.style.height = `${next}px`;
  }, [question]);

  // Scroll to the latest exchange when the thread grows
  useEffect(() => {
    if (threadEndRef.current && session.length > 0) {
      threadEndRef.current.scrollIntoView({ behavior: "smooth", block: "end" });
    }
  }, [session.length]);

  const sprintLabel = useMemo(() => {
    if (selectedSprintId === null) return "Todos los sprints";
    return formatSprintId(selectedSprintId);
  }, [selectedSprintId]);
  const scopeLabel = scope === "analyzed_only" ? "Solo analizadas" : "Dataset completo";

  async function handleAsk(forcedText?: string) {
    const sourceText = forcedText ?? question;
    const trimmed = sourceText.trim();
    if (!trimmed || running) return;
    counterRef.current += 1;
    const entryId = counterRef.current;
    const entry: SessionEntry = {
      id: entryId,
      question: trimmed,
      sprintLabel,
      scopeLabel,
      answer: "",
      sources: [],
      status: "streaming",
    };
    setSession((prev) => [...prev, entry]);
    setQuestion("");
    setRunning(true);
    try {
      await api.askQuestion(trimmed, selectedSprintId, scope, (event) => {
        setSession((prev) =>
          prev.map((e) => {
            if (e.id !== entryId) return e;
            if (event.type === "sources") {
              return { ...e, sources: event.sources };
            }
            if (event.type === "token") {
              return { ...e, answer: e.answer + event.text };
            }
            if (event.type === "done") {
              return e.status === "streaming" ? { ...e, status: "done" } : e;
            }
            if (event.type === "error") {
              return { ...e, status: "error", errorDetail: event.detail };
            }
            if (event.type === "guardrail_block") {
              return {
                ...e,
                status: "blocked",
                blockRule: event.rule,
                blockDetail: event.detail,
                topSimilarity: event.top_similarity,
              };
            }
            if (event.type === "confidence") {
              return {
                ...e,
                confidence: event.band,
                topSimilarity: event.top_similarity,
              };
            }
            if (event.type === "citation_audit") {
              return {
                ...e,
                hallucinatedCitations: event.hallucinated,
              };
            }
            return e;
          })
        );
      });
    } catch (err) {
      setSession((prev) =>
        prev.map((e) =>
          e.id === entryId
            ? { ...e, status: "error", errorDetail: (err as Error).message }
            : e
        )
      );
      toast.error(`No se pudo preguntar: ${(err as Error).message}`);
    } finally {
      setRunning(false);
    }
  }

  function toggleSource(entryId: number, sourceIndex: number) {
    const key = `${entryId}:${sourceIndex}`;
    setExpandedSources((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleAsk();
    }
  }

  function clearSession() {
    setSession([]);
    setExpandedSources(new Set());
    setQuestion("");
  }

  const isEmpty = session.length === 0;

  return (
    <div className={`ask-page${isEmpty ? " is-empty" : ""}`}>
      {isEmpty ? (
        <div className="ask-empty">
          <div className="ask-empty-inner">
            <h1 className="ask-hero">¿En qué quieres profundizar?</h1>
            <p className="ask-hero-sub">
              Pregunta sobre lo que se dijo en las reuniones o sobre el estado de los
              compromisos. La respuesta cita los fragmentos que la sostienen.
            </p>

            <Composer
              question={question}
              setQuestion={setQuestion}
              running={running}
              onSubmit={() => handleAsk()}
              onKeyDown={handleKeyDown}
              textareaRef={textareaRef}
              sprints={sprints}
              selectedSprintId={selectedSprintId}
              setSelectedSprintId={setSelectedSprintId}
              scope={scope}
              setScope={setScope}
            />

            <div className="ask-suggestions">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s.title}
                  type="button"
                  className="ask-suggestion"
                  onClick={() => handleAsk(s.body)}
                  disabled={running}
                >
                  <span className="ask-suggestion-title">{s.title}</span>
                  <span className="ask-suggestion-body">{s.body}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="ask-thread">
            {session.map((entry) => (
              <article key={entry.id} className="ask-turn">
                <div className="ask-msg ask-msg-user">
                  <div className="ask-avatar ask-avatar-user" aria-hidden>
                    Tú
                  </div>
                  <div className="ask-msg-body">
                    <p className="ask-msg-text">{entry.question}</p>
                    <span className="ask-msg-meta">
                      {entry.sprintLabel} · {entry.scopeLabel}
                    </span>
                  </div>
                </div>

                <div className="ask-msg ask-msg-assistant">
                  <div className="ask-avatar ask-avatar-assistant" aria-hidden>
                    ◆
                  </div>
                  <div className="ask-msg-body">
                    {entry.status === "streaming" &&
                      entry.answer === "" &&
                      entry.sources.length === 0 && (
                        <p className="ask-thinking">
                          <span className="ask-thinking-dot" />
                          <span className="ask-thinking-dot" />
                          <span className="ask-thinking-dot" />
                        </p>
                      )}

                    {entry.status === "blocked" && entry.blockDetail && (
                      <GuardrailNotice
                        rule={entry.blockRule}
                        detail={entry.blockDetail}
                      />
                    )}

                    {entry.answer && (
                      <div className="ask-msg-text">
                        {renderAnswerWithCitations(
                          entry.answer,
                          entry.id,
                          expandedSources,
                          toggleSource,
                          entry.hallucinatedCitations
                        )}
                        {entry.status === "streaming" && (
                          <span className="ask-cursor" aria-hidden />
                        )}
                      </div>
                    )}

                    {(entry.status === "done" || entry.status === "streaming") &&
                      entry.confidence && (
                        <ConfidenceBadge
                          band={entry.confidence}
                          topSimilarity={entry.topSimilarity}
                          sourceCount={entry.sources.length}
                          hallucinated={entry.hallucinatedCitations}
                        />
                      )}

                    {entry.status === "error" && (
                      <p className="ask-error">
                        No se pudo completar. {entry.errorDetail}
                      </p>
                    )}

                    {entry.sources.length > 0 && (
                      <Sources
                        entry={entry}
                        expanded={expandedSources}
                        onToggle={toggleSource}
                      />
                    )}
                  </div>
                </div>
              </article>
            ))}
            <div ref={threadEndRef} />
          </div>

          <div className="ask-bottom">
            <div className="ask-bottom-meta">
              <button
                type="button"
                className="ask-new-thread"
                onClick={clearSession}
                disabled={running}
              >
                + Nueva pregunta
              </button>
            </div>
            <Composer
              question={question}
              setQuestion={setQuestion}
              running={running}
              onSubmit={() => handleAsk()}
              onKeyDown={handleKeyDown}
              textareaRef={textareaRef}
              sprints={sprints}
              selectedSprintId={selectedSprintId}
              setSelectedSprintId={setSelectedSprintId}
              scope={scope}
              setScope={setScope}
            />
          </div>
        </>
      )}
    </div>
  );
}

interface ComposerProps {
  question: string;
  setQuestion: (q: string) => void;
  running: boolean;
  onSubmit: () => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  textareaRef: React.MutableRefObject<HTMLTextAreaElement | null>;
  sprints: SprintSummary[];
  selectedSprintId: string | null;
  setSelectedSprintId: (id: string | null) => void;
  scope: QAScope;
  setScope: (scope: QAScope) => void;
}

function Composer({
  question,
  setQuestion,
  running,
  onSubmit,
  onKeyDown,
  textareaRef,
  sprints,
  selectedSprintId,
  setSelectedSprintId,
  scope,
  setScope,
}: ComposerProps) {
  const canSubmit = !running && question.trim().length > 0;
  return (
    <div className="ask-composer">
      <div className="ask-composer-frame">
        <textarea
          ref={textareaRef}
          className="ask-composer-input"
          placeholder="Pregunta lo que quieras…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          disabled={running}
        />
        <div className="ask-composer-bar">
          <div className="ask-scope" role="tablist" aria-label="Ámbito de la pregunta">
            <button
              type="button"
              role="tab"
              aria-selected={selectedSprintId === null}
              className="ask-scope-chip"
              data-on={selectedSprintId === null ? "true" : "false"}
              onClick={() => setSelectedSprintId(null)}
              disabled={running}
            >
              Todos
            </button>
            {sprints.map((s) => (
              <button
                key={s.sprint_id as string}
                type="button"
                role="tab"
                aria-selected={selectedSprintId === s.sprint_id}
                className="ask-scope-chip"
                data-on={selectedSprintId === s.sprint_id ? "true" : "false"}
                onClick={() => setSelectedSprintId(s.sprint_id)}
                disabled={running}
              >
                {formatSprintId(s.sprint_id as string)}
              </button>
            ))}
          </div>
          <div className="ask-scope" role="tablist" aria-label="Fuente del contexto">
            <button
              type="button"
              role="tab"
              aria-selected={scope === "analyzed_only"}
              className="ask-scope-chip"
              data-on={scope === "analyzed_only" ? "true" : "false"}
              onClick={() => setScope("analyzed_only")}
              disabled={running}
            >
              Solo analizadas
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={scope === "all"}
              className="ask-scope-chip"
              data-on={scope === "all" ? "true" : "false"}
              onClick={() => setScope("all")}
              disabled={running}
            >
              Dataset completo
            </button>
          </div>
          <button
            type="button"
            className="ask-submit"
            onClick={onSubmit}
            disabled={!canSubmit}
            aria-label="Enviar pregunta"
            title="Enviar (Enter)"
          >
            {running ? (
              <Spinner />
            ) : (
              <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden>
                <path
                  d="M7 1.5v11M7 1.5L2.5 6M7 1.5L11.5 6"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  fill="none"
                />
              </svg>
            )}
          </button>
        </div>
      </div>
      <p className="ask-hint">
        <kbd>Enter</kbd> para preguntar, <kbd>Shift</kbd>+<kbd>Enter</kbd> para
        nueva línea
      </p>
      <p className="ask-hint">
        El modo normal usa solo reuniones ya analizadas; el dataset completo queda para pruebas.
      </p>
    </div>
  );
}

function Sources({
  entry,
  expanded,
  onToggle,
}: {
  entry: SessionEntry;
  expanded: Set<string>;
  onToggle: (entryId: number, sourceIndex: number) => void;
}) {
  return (
    <section className="ask-sources">
      <p className="ask-sources-label">Fragmentos usados</p>
      {entry.sources.map((source) => {
        const key = `${entry.id}:${source.index}`;
        const isOpen = expanded.has(key);
        return (
          <button
            key={source.index}
            type="button"
            className="ask-source"
            data-open={isOpen ? "true" : "false"}
            onClick={() => onToggle(entry.id, source.index)}
          >
            <div className="ask-source-head">
              <span className="ask-source-num">[{source.index}]</span>
              <span className="ask-source-type" data-kind={source.source_type}>
                {source.source_type === "transcript" ? "Transcripción" : "Compromiso"}
              </span>
              <span className="ask-source-title">{source.title}</span>
              {source.sprint_id && (
                <span className="ask-source-sprint">
                  {formatSprintId(source.sprint_id)}
                </span>
              )}
              <span className="ask-source-sim">
                {(source.similarity * 100).toFixed(0)}%
              </span>
            </div>
            {source.subtitle && <p className="ask-source-sub">{source.subtitle}</p>}
            {isOpen && (
              <div className="ask-source-body">
                <p>{source.text || "(sin texto)"}</p>
                {source.commitment_id && (
                  <Link
                    to={`/compromisos/${source.commitment_id}`}
                    className="ask-source-link"
                    onClick={(e) => e.stopPropagation()}
                  >
                    Ver compromiso →
                  </Link>
                )}
              </div>
            )}
          </button>
        );
      })}
    </section>
  );
}

function Spinner() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 14 14"
      className="ask-spinner"
      aria-hidden
    >
      <circle
        cx="7"
        cy="7"
        r="5"
        stroke="currentColor"
        strokeOpacity="0.25"
        strokeWidth="2"
        fill="none"
      />
      <path
        d="M12 7a5 5 0 00-5-5"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

const RULE_LABEL: Record<GuardrailRule, string> = {
  length: "Pregunta demasiado larga",
  prompt_injection: "Intento de manipular el asistente",
  empty_context: "Sin información relevante",
  out_of_scope: "Fuera del alcance de las reuniones",
};

function GuardrailNotice({
  rule,
  detail,
}: {
  rule?: GuardrailRule;
  detail: string;
}) {
  const label = rule ? RULE_LABEL[rule] : "Bloqueado por guardrails";
  const tone = rule === "prompt_injection" ? "warn" : "info";
  return (
    <div className="ask-guardrail" data-tone={tone} role="status">
      <div className="ask-guardrail-head">
        <ShieldIcon />
        <span className="ask-guardrail-title">{label}</span>
      </div>
      <p className="ask-guardrail-detail">{detail}</p>
    </div>
  );
}

const BAND_LABEL: Record<ConfidenceBand, string> = {
  high: "Confianza alta",
  medium: "Confianza media",
  low: "Confianza baja",
};

function ConfidenceBadge({
  band,
  topSimilarity,
  sourceCount,
  hallucinated,
}: {
  band: ConfidenceBand;
  topSimilarity?: number;
  sourceCount: number;
  hallucinated?: number[];
}) {
  const simPct =
    topSimilarity !== undefined ? `${Math.round(topSimilarity * 100)}%` : null;
  const tooltip = [
    simPct ? `Mejor similitud: ${simPct}` : null,
    `${sourceCount} fuente${sourceCount === 1 ? "" : "s"}`,
    hallucinated && hallucinated.length > 0
      ? `${hallucinated.length} cita${hallucinated.length === 1 ? "" : "s"} sin respaldo`
      : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="ask-confidence" data-band={band} title={tooltip}>
      <span className="ask-confidence-dot" aria-hidden />
      <span className="ask-confidence-label">{BAND_LABEL[band]}</span>
      <span className="ask-confidence-meta">{tooltip}</span>
    </div>
  );
}

function ShieldIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 14 14"
      fill="none"
      aria-hidden
      className="ask-guardrail-icon"
    >
      <path
        d="M7 1.5L2.5 3v3.5C2.5 9 4.5 11.3 7 12.5c2.5-1.2 4.5-3.5 4.5-6V3L7 1.5z"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function renderAnswerWithCitations(
  text: string,
  entryId: number,
  expanded: Set<string>,
  toggle: (entryId: number, sourceIndex: number) => void,
  hallucinated?: number[]
): React.ReactNode {
  const parts: React.ReactNode[] = [];
  const regex = /\[(\d+)\]/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let keyCounter = 0;
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const sourceIndex = parseInt(match[1], 10);
    const key = `cite-${keyCounter++}`;
    const isExpanded = expanded.has(`${entryId}:${sourceIndex}`);
    const isHallucinated = (hallucinated || []).includes(sourceIndex);
    parts.push(
      <button
        key={key}
        type="button"
        className="ask-cite"
        data-active={isExpanded ? "true" : "false"}
        data-hallucinated={isHallucinated ? "true" : "false"}
        onClick={() => (isHallucinated ? undefined : toggle(entryId, sourceIndex))}
        aria-label={
          isHallucinated
            ? `Cita ${sourceIndex} sin respaldo en las fuentes`
            : `Fuente ${sourceIndex}`
        }
        title={
          isHallucinated
            ? `[${sourceIndex}] no corresponde a ninguna fuente recuperada`
            : `Ver fuente [${sourceIndex}]`
        }
      >
        {sourceIndex}
      </button>
    );
    lastIndex = regex.lastIndex;
  }
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }
  return parts;
}
