import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import type { AnalysisResult, DetectedItem, Transcript, TranscriptSummary, ValidationStatus } from "../types";
import { followupLabel } from "../labels";
import { ItemCard } from "../components/ItemCard";
import { Pill } from "../components/Pill";
import { useToast } from "../components/Toast";

const MANUAL_TEMPLATE = [
  "00:00 Ane: Tenemos que revisar el flujo de login para la demo del lunes.",
  "00:14 Mikel: Hay que anadir validacion de errores en el login y distinguir credenciales invalidas de fallo del proveedor.",
  "00:30 Leire: Podriamos simplificar el estado vacio del dashboard para que el equipo de negocio lo entienda mejor.",
  "00:45 Ane: Decidimos mantener FastAPI como base del backend durante esta fase.",
].join("\n");

const MANUAL_TITLE = "Reunion manual";

type Filter = "all" | ValidationStatus;

const isValidatable = (item: DetectedItem) => item.item_type !== "technical_decision";

export function AnalyzePage() {
  const toast = useToast();
  const navigate = useNavigate();
  const [samples, setSamples] = useState<TranscriptSummary[]>([]);
  const [activeSampleId, setActiveSampleId] = useState<string | null>(null);
  const [title, setTitle] = useState(MANUAL_TITLE);
  const [text, setText] = useState(MANUAL_TEMPLATE);
  const [currentTranscript, setCurrentTranscript] = useState<Transcript | null>(null);
  const [originalRawText, setOriginalRawText] = useState("");

  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [items, setItems] = useState<DetectedItem[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [editing, setEditing] = useState(true);
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => {
    api.listTranscripts().then(setSamples).catch(() => setSamples([]));
  }, []);

  async function loadSample(id: string) {
    try {
      const transcript = await api.getTranscript(id);
      setCurrentTranscript(transcript);
      setOriginalRawText(transcript.raw_text ?? "");
      setTitle(transcript.title);
      setText(transcript.raw_text ?? "");
      setActiveSampleId(id);
      setAnalysis(null);
      setItems([]);
      setRunId(null);
      setEditing(true);
    } catch (err) {
      toast.error((err as Error).message);
    }
  }

  function clearScreen() {
    setCurrentTranscript(null);
    setOriginalRawText("");
    setActiveSampleId(null);
    setTitle(MANUAL_TITLE);
    setText(MANUAL_TEMPLATE);
    setAnalysis(null);
    setItems([]);
    setRunId(null);
    setEditing(true);
  }

  async function analyze() {
    const trimmedTitle = title.trim() || MANUAL_TITLE;
    const trimmedText = text.trim();
    if (!trimmedText) {
      toast.error("Necesitas pegar una transcripcion antes de ejecutar el pipeline.");
      return;
    }

    setRunning(true);
    try {
      const isOriginalSample =
        currentTranscript && currentTranscript.title === trimmedTitle && originalRawText === trimmedText;

      const payload =
        isOriginalSample && currentTranscript
          ? await api.analyzeTranscript(currentTranscript.id)
          : await api.analyzeRaw(
              trimmedTitle,
              currentTranscript ? "edited-sample" : "manual",
              trimmedText
            );

      setAnalysis(payload.analysis);
      setItems(payload.analysis.items ?? []);
      setRunId(payload.analysis.run_id ?? null);
      setFilter("all");
      setEditing(false);
      toast.success(`Pipeline completado · ${payload.analysis.items?.length ?? 0} items detectados`);
    } catch (err) {
      toast.error(`El pipeline no pudo completarse: ${(err as Error).message}`);
    } finally {
      setRunning(false);
    }
  }

  async function handleValidate(index: number, status: "approved" | "rejected") {
    if (!runId) return;
    try {
      const updated = await api.patchValidation(runId, index, status);
      setItems((prev) => prev.map((it, i) => (i === index ? { ...it, validation_status: updated.validation_status } : it)));
      toast.success(status === "approved" ? "Item aprobado" : "Item rechazado");
    } catch (err) {
      toast.error(`No se pudo actualizar el estado: ${(err as Error).message}`);
    }
  }

  async function handleCreateJira(index: number) {
    if (!runId) return;
    try {
      const result = await api.createJiraIssue(runId, index);
      setItems((prev) => prev.map((it, i) => (i === index ? { ...it, jira_created_issue: result.jira_issue } : it)));
      toast.success(`Issue creado en Jira: ${result.jira_issue.issue_key}`);
    } catch (err) {
      toast.error(`No se pudo crear el issue en Jira: ${(err as Error).message}`);
    }
  }

  const counts = useMemo(() => {
    const validatable = items.filter(isValidatable);
    return {
      total: items.length,
      pending_review: validatable.filter((i) => i.validation_status === "pending_review").length,
      approved: validatable.filter((i) => i.validation_status === "approved").length,
      rejected: validatable.filter((i) => i.validation_status === "rejected").length,
    };
  }, [items]);

  const visibleItems = useMemo(() => {
    if (filter === "all") return items.map((item, index) => ({ item, index }));
    return items
      .map((item, index) => ({ item, index }))
      .filter(({ item }) => isValidatable(item) && item.validation_status === filter);
  }, [items, filter]);

  const followups = analysis?.followup_updates ?? [];
  const showInput = editing || !analysis;

  return (
    <>
      {showInput ? (
        <section className="card">
          <div className="section-head">
            <div>
              <h2>Ingestar reunion</h2>
              <p>
                Carga o pega una transcripcion y ejecuta el pipeline. Los compromisos detectados
                aterrizan en el <Link to="/">tablero</Link>; aqui solo haces el triaje rapido.
              </p>
            </div>
            <div className="head-actions">
              {analysis && (
                <button type="button" className="ghost-button" onClick={() => setEditing(false)}>
                  Volver a resultados
                </button>
              )}
              <button type="button" className="ghost-button" onClick={clearScreen}>
                Limpiar
              </button>
            </div>
          </div>

          {samples.length > 0 && (
            <>
              <div className="field-label">Ejemplos</div>
              <div className="sample-list">
                {samples.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    className={`sample-button${activeSampleId === s.id ? " active" : ""}`}
                    onClick={() => loadSample(s.id)}
                  >
                    {s.title}
                  </button>
                ))}
              </div>
            </>
          )}

          <label className="field-label" htmlFor="transcript-title">
            Titulo
          </label>
          <input id="transcript-title" className="text-input" value={title} onChange={(e) => setTitle(e.target.value)} />

          <label className="field-label" htmlFor="transcript-text">
            Transcripcion
          </label>
          <textarea
            id="transcript-text"
            className="transcript-area"
            spellCheck={false}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <p className="hint">
            Formato recomendado: <code>00:12 Ana: Hay que anadir validacion de errores en el login</code>
          </p>

          <div className="run-bar">
            <span className="run-bar-hint">
              El análisis siempre razona contra el historial de compromisos anteriores.
            </span>
            <button type="button" className="primary-button" onClick={analyze} disabled={running}>
              {running ? "Ejecutando pipeline..." : "Ejecutar pipeline"}
            </button>
          </div>
        </section>
      ) : (
        <section className="card collapsed-input">
          <div>
            <div className="eyebrow">Reunion ingestada</div>
            <div className="collapsed-title">{analysis?.transcript_title}</div>
            <div className="run-row-meta">
              {analysis?.run_id} · {analysis?.created_at?.slice(0, 16).replace("T", " ")}
            </div>
          </div>
          <div className="head-actions">
            <button type="button" className="ghost-button" onClick={() => setEditing(true)}>
              Editar / nueva reunion
            </button>
            <button type="button" className="primary-button" onClick={() => navigate("/")}>
              Ir al tablero ↗
            </button>
          </div>
        </section>
      )}

      {analysis && !showInput && (
        <>
          {followups.length > 0 && (
            <section className="card">
              <div className="section-head">
                <h2>Seguimiento detectado</h2>
                <Pill text={`${followups.length}`} />
              </div>
              <div className="stack">
                {followups.map((f, i) => (
                  <article key={i} className="followup-card">
                    <div className="meta-row">
                      <Pill text={followupLabel(f.followup_type)} variant="followup" />
                    </div>
                    <h4>{f.matched_history_title}</h4>
                    <p>{f.explanation}</p>
                  </article>
                ))}
              </div>
            </section>
          )}

          <section className="card">
            <div className="ingest-banner">
              <span>
                Los compromisos ya estan en el <Link to="/">tablero</Link>. Triaje aqui o alla; el estado se mantiene sincronizado.
              </span>
            </div>
            <div className="results-header">
              <div className="kpi-strip">
                <Kpi label="Detectados" value={counts.total} />
                <Kpi label="Pendientes" value={counts.pending_review} tone="pending" />
                <Kpi label="Aprobados" value={counts.approved} tone="approved" />
                <Kpi label="Rechazados" value={counts.rejected} tone="rejected" />
              </div>
              <div className="segmented">
                <FilterTab label="Todos" count={counts.total} active={filter === "all"} onClick={() => setFilter("all")} />
                <FilterTab
                  label="Pendientes"
                  count={counts.pending_review}
                  active={filter === "pending_review"}
                  onClick={() => setFilter("pending_review")}
                />
                <FilterTab label="Aprobados" count={counts.approved} active={filter === "approved"} onClick={() => setFilter("approved")} />
                <FilterTab label="Rechazados" count={counts.rejected} active={filter === "rejected"} onClick={() => setFilter("rejected")} />
              </div>
            </div>

            {visibleItems.length > 0 ? (
              <div className="item-list">
                {visibleItems.map(({ item, index }) => (
                  <ItemCard
                    key={index}
                    item={item}
                    index={index}
                    runId={runId}
                    onValidate={handleValidate}
                    onCreateJira={handleCreateJira}
                    compact
                  />
                ))}
              </div>
            ) : (
              <div className="empty-state">
                {counts.total === 0
                  ? "El pipeline no ha dejado propuestas con esta transcripcion."
                  : "No hay items en este estado."}
              </div>
            )}
          </section>
        </>
      )}
    </>
  );
}

function Kpi({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className={`kpi${tone ? ` kpi-${tone}` : ""}`}>
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function FilterTab({ label, count, active, onClick }: { label: string; count: number; active: boolean; onClick: () => void }) {
  return (
    <button type="button" className={`seg-tab${active ? " active" : ""}`} onClick={onClick}>
      {label} <span className="seg-count">{count}</span>
    </button>
  );
}
