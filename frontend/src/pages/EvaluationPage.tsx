import { useEffect, useState } from "react";
import { api } from "../api";
import type {
  DatasetEvaluationResult,
  EvaluationSummaryRow,
  FollowupEvaluationResult,
  FollowupEvaluationSummaryRow,
  FollowupPairEvaluation,
  FollowupType,
  RetrievalMode,
} from "../types";
import { followupLabel } from "../labels";
import { Pill } from "../components/Pill";
import { useToast } from "../components/Toast";

const pct = (value: number) => `${(value * 100).toFixed(1)}%`;

const FOLLOWUP_TYPES: FollowupType[] = [
  "recurring_unresolved",
  "scope_change",
  "new_blocker",
  "blocker_resolved",
  "possible_duplicate",
  "contradicts_decision",
  "verbal_close",
];

const shortType: Record<FollowupType, string> = {
  recurring_unresolved: "recurring",
  scope_change: "scope",
  new_blocker: "blocker+",
  blocker_resolved: "blocker-",
  possible_duplicate: "duplicate",
  contradicts_decision: "contradic.",
  verbal_close: "close",
};

type Section = "extraccion" | "seguimiento";

export function EvaluationPage() {
  const [section, setSection] = useState<Section>("extraccion");

  return (
    <>
      <section className="card">
        <div className="section-head">
          <div>
            <h2>Evaluación</h2>
            <p>
              Dos miradas complementarias: <strong>extracción</strong> (precision/recall/F1 sobre
              los items esperados) y <strong>seguimiento</strong> (razonamiento entre reuniones,
              matriz de confusión sobre los 7 tipos).
            </p>
          </div>
          <div className="segmented">
            <button
              type="button"
              className={`seg-tab${section === "extraccion" ? " active" : ""}`}
              onClick={() => setSection("extraccion")}
            >
              Extracción
            </button>
            <button
              type="button"
              className={`seg-tab${section === "seguimiento" ? " active" : ""}`}
              onClick={() => setSection("seguimiento")}
            >
              Seguimiento
            </button>
          </div>
        </div>
      </section>

      {section === "extraccion" ? <ExtractionPanel /> : <FollowupPanel />}
    </>
  );
}

// ---------------- Extracción (la evaluación previa) ----------------

function ExtractionPanel() {
  const toast = useToast();
  const [history, setHistory] = useState<EvaluationSummaryRow[]>([]);
  const [current, setCurrent] = useState<DatasetEvaluationResult | null>(null);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const rows = await api.listEvaluations(20);
        setHistory(rows);
        if (rows.length > 0) loadEvaluation(rows[0].evaluation_id);
      } catch (err) {
        toast.error((err as Error).message);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadEvaluation(id: string) {
    setLoading(true);
    try {
      setCurrent(await api.getEvaluation(id));
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function runEvaluation() {
    setRunning(true);
    try {
      const { evaluation } = await api.runEvaluation();
      setCurrent(evaluation);
      const rows = await api.listEvaluations(20);
      setHistory(rows);
      toast.success("Evaluación de extracción completada");
    } catch (err) {
      toast.error(`No se pudo completar: ${(err as Error).message}`);
    } finally {
      setRunning(false);
    }
  }

  const summary = current?.summary;

  return (
    <>
      <section className="card">
        <div className="section-head">
          <div>
            <h3>Extracción de items</h3>
            <p>Compara items detectados vs esperados por similitud de título.</p>
          </div>
          <button type="button" className="primary-button" onClick={runEvaluation} disabled={running}>
            {running ? "Evaluando..." : "Ejecutar evaluación"}
          </button>
        </div>

        {history.length > 0 && (
          <>
            <div className="field-label">Evaluaciones anteriores</div>
            <div className="sample-list">
              {history.map((row) => (
                <button
                  key={row.evaluation_id}
                  type="button"
                  className={`sample-button${current?.evaluation_id === row.evaluation_id ? " active" : ""}`}
                  onClick={() => loadEvaluation(row.evaluation_id)}
                >
                  {row.created_at?.slice(0, 16).replace("T", " ")} · F1 {pct(row.summary.f1)}
                </button>
              ))}
            </div>
          </>
        )}
      </section>

      {loading && <section className="card empty-state">Cargando evaluación...</section>}

      {summary && !loading && (
        <>
          <section className="card">
            <div className="headline-metric">
              <div className="headline-f1">
                <span className="headline-label">F1 global</span>
                <strong>{pct(summary.f1)}</strong>
              </div>
              <div className="headline-side">
                <Metric label="Precision" value={pct(summary.precision)} />
                <Metric label="Recall" value={pct(summary.recall)} />
                <Metric
                  label="Transcripciones"
                  value={`${summary.completed_transcripts}/${summary.transcript_count}`}
                />
              </div>
            </div>
            <div className="kpi-grid" style={{ marginTop: "1rem" }}>
              <Kpi label="Esperados" value={summary.expected_count} />
              <Kpi label="Detectados" value={summary.detected_count} />
              <Kpi label="Aciertos" value={summary.matched_count} tone="approved" />
              <Kpi label="No detectados" value={summary.false_negative_count} tone="pending" />
              <Kpi label="Falsos positivos" value={summary.false_positive_count} tone="rejected" />
              <Kpi label="Mal clasificados" value={summary.misclassified_count} />
            </div>
          </section>

          <section className="card">
            <div className="section-head">
              <h3>Detalle por transcripción</h3>
            </div>
            <table className="eval-table">
              <thead>
                <tr>
                  <th>Transcripción</th>
                  <th>Estado</th>
                  <th className="num">Esp.</th>
                  <th className="num">Det.</th>
                  <th className="num">Aciertos</th>
                  <th className="num">P</th>
                  <th className="num">R</th>
                  <th className="num">F1</th>
                </tr>
              </thead>
              <tbody>
                {current!.transcript_results.map((row) => (
                  <tr key={row.transcript_id}>
                    <td>{row.transcript_title}</td>
                    <td>
                      <Pill
                        text={row.status === "completed" ? "ok" : "fallo"}
                        variant={row.status === "completed" ? "validation-approved" : "validation-rejected"}
                      />
                    </td>
                    <td className="num">{row.expected_count}</td>
                    <td className="num">{row.detected_count}</td>
                    <td className="num">{row.matched_count}</td>
                    <td className="num">{pct(row.precision)}</td>
                    <td className="num">{pct(row.recall)}</td>
                    <td className="num">{pct(row.f1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}

      {!summary && !loading && (
        <section className="card empty-state">
          Todavía no hay evaluaciones de extracción. Pulsa "Ejecutar evaluación" para generar la primera.
        </section>
      )}
    </>
  );
}

// ---------------- Seguimiento (H6 / CDIA) ----------------

const RETRIEVAL_LABEL: Record<RetrievalMode, string> = {
  off: "Sin RAG",
  current: "RAG sprint actual",
  all: "RAG todos los sprints",
};

function FollowupPanel() {
  const toast = useToast();
  const [history, setHistory] = useState<FollowupEvaluationSummaryRow[]>([]);
  const [current, setCurrent] = useState<FollowupEvaluationResult | null>(null);
  const [ablation, setAblation] = useState<FollowupEvaluationResult[] | null>(null);
  const [retrievalMode, setRetrievalMode] = useState<RetrievalMode>("off");
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const rows = await api.listFollowupEvaluations(20);
        setHistory(rows);
        if (rows.length > 0) load(rows[0].evaluation_id);
      } catch (err) {
        toast.error((err as Error).message);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function load(id: string) {
    setLoading(true);
    try {
      setCurrent(await api.getFollowupEvaluation(id));
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function run() {
    setRunning(true);
    try {
      const { evaluation } = await api.runFollowupEvaluation(retrievalMode);
      setCurrent(evaluation);
      setAblation(null);
      const rows = await api.listFollowupEvaluations(20);
      setHistory(rows);
      toast.success(`Evaluación completada (${RETRIEVAL_LABEL[retrievalMode]})`);
    } catch (err) {
      toast.error(`No se pudo completar: ${(err as Error).message}`);
    } finally {
      setRunning(false);
    }
  }

  async function runAblation() {
    setRunning(true);
    try {
      const { ablation: results } = await api.runFollowupAblation();
      setAblation(results);
      if (results.length > 0) setCurrent(results[0]);
      const rows = await api.listFollowupEvaluations(20);
      setHistory(rows);
      toast.success("Ablación de 3 configuraciones completada");
    } catch (err) {
      toast.error(`No se pudo completar la ablación: ${(err as Error).message}`);
    } finally {
      setRunning(false);
    }
  }

  const summary = current?.summary;

  return (
    <>
      <section className="card">
        <div className="section-head">
          <div>
            <h3>Razonamiento entre reuniones</h3>
            <p>
              Por cada par etiquetado, ejecuta el pipeline sobre reunión 1 y luego sobre reunión 2 con
              historial. Compara los <code>followup_updates</code> predichos contra los esperados. El
              modo de recuperación controla qué contexto del historial recibe el agente de seguimiento.
            </p>
          </div>
        </div>

        <div className="field-label" style={{ marginTop: "0.6rem" }}>
          Modo de recuperación
        </div>
        <div className="segmented" style={{ width: "fit-content" }}>
          {(["off", "current", "all"] as RetrievalMode[]).map((m) => (
            <button
              key={m}
              type="button"
              className={`seg-tab${retrievalMode === m ? " active" : ""}`}
              onClick={() => setRetrievalMode(m)}
              disabled={running}
            >
              {RETRIEVAL_LABEL[m]}
            </button>
          ))}
        </div>

        <div style={{ marginTop: "0.8rem", display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
          <button type="button" className="primary-button" onClick={run} disabled={running}>
            {running ? "Evaluando..." : `Ejecutar (${RETRIEVAL_LABEL[retrievalMode]})`}
          </button>
          <button type="button" className="primary-button" onClick={runAblation} disabled={running}>
            {running ? "Evaluando..." : "Ablación (3 modos)"}
          </button>
        </div>

        {history.length > 0 && (
          <>
            <div className="field-label" style={{ marginTop: "0.8rem" }}>
              Evaluaciones anteriores
            </div>
            <div className="sample-list">
              {history.map((row) => (
                <button
                  key={row.evaluation_id}
                  type="button"
                  className={`sample-button${current?.evaluation_id === row.evaluation_id ? " active" : ""}`}
                  onClick={() => load(row.evaluation_id)}
                >
                  {row.created_at?.slice(0, 16).replace("T", " ")} ·{" "}
                  {row.retrieval_mode ? RETRIEVAL_LABEL[row.retrieval_mode] : "—"} · F1 macro{" "}
                  {pct(row.summary.f1_macro)}
                </button>
              ))}
            </div>
          </>
        )}
      </section>

      {ablation && ablation.length > 0 && (
        <section className="card">
          <div className="section-head">
            <h3>Ablación: tres configuraciones</h3>
            <span className="muted-inline">
              comparativa de F1 macro y por tipo entre <em>sin RAG</em> / <em>sprint actual</em> /{" "}
              <em>todos los sprints</em>
            </span>
          </div>
          <table className="eval-table">
            <thead>
              <tr>
                <th>Métrica</th>
                {ablation.map((r) => (
                  <th key={r.retrieval_mode} className="num">
                    {RETRIEVAL_LABEL[r.retrieval_mode]}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>F1 macro</td>
                {ablation.map((r) => (
                  <td key={r.retrieval_mode} className="num">
                    <strong>{pct(r.summary.f1_macro)}</strong>
                  </td>
                ))}
              </tr>
              <tr>
                <td>F1 micro</td>
                {ablation.map((r) => (
                  <td key={r.retrieval_mode} className="num">
                    {pct(r.summary.f1_micro)}
                  </td>
                ))}
              </tr>
              <tr>
                <td>Cobertura</td>
                {ablation.map((r) => (
                  <td key={r.retrieval_mode} className="num">
                    {pct(r.summary.coverage)}
                  </td>
                ))}
              </tr>
              <tr>
                <td>Emparejados / esperados</td>
                {ablation.map((r) => (
                  <td key={r.retrieval_mode} className="num">
                    {r.summary.matched_count}/{r.summary.expected_count}
                  </td>
                ))}
              </tr>
              <tr>
                <td>Tipo correcto</td>
                {ablation.map((r) => (
                  <td key={r.retrieval_mode} className="num">
                    {r.summary.correct_type_count}
                  </td>
                ))}
              </tr>
              {FOLLOWUP_TYPES.map((t) => (
                <tr key={t}>
                  <td>F1 · {followupLabel(t)}</td>
                  {ablation.map((r) => (
                    <td key={r.retrieval_mode} className="num">
                      {pct(r.summary.f1_by_type[t] ?? 0)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="field-label" style={{ marginTop: "0.8rem" }}>
            Detalle por modo
          </div>
          <div className="sample-list">
            {ablation.map((r) => (
              <button
                key={r.retrieval_mode}
                type="button"
                className={`sample-button${current?.evaluation_id === r.evaluation_id ? " active" : ""}`}
                onClick={() => r.evaluation_id && load(r.evaluation_id)}
              >
                {RETRIEVAL_LABEL[r.retrieval_mode]}
              </button>
            ))}
          </div>
        </section>
      )}

      {loading && <section className="card empty-state">Cargando evaluación...</section>}

      {summary && !loading && (
        <>
          <section className="card">
            <div className="headline-metric">
              <div className="headline-f1">
                <span className="headline-label">F1 macro</span>
                <strong>{pct(summary.f1_macro)}</strong>
              </div>
              <div className="headline-side">
                <Metric label="Precision macro" value={pct(summary.precision_macro)} />
                <Metric label="Recall macro" value={pct(summary.recall_macro)} />
                <Metric label="F1 micro" value={pct(summary.f1_micro)} />
                <Metric label="Cobertura" value={pct(summary.coverage)} />
              </div>
            </div>
            <div className="kpi-grid" style={{ marginTop: "1rem" }}>
              <Kpi label="Pares" value={summary.pair_count} />
              <Kpi label="Esperados" value={summary.expected_count} />
              <Kpi label="Predichos" value={summary.predicted_count} />
              <Kpi label="Emparejados" value={summary.matched_count} tone="approved" />
              <Kpi label="Tipo correcto" value={summary.correct_type_count} tone="approved" />
              <Kpi label="Pares fallidos" value={summary.failed_pairs} tone="rejected" />
            </div>
          </section>

          <section className="card">
            <div className="section-head">
              <h3>Métricas por tipo</h3>
            </div>
            <table className="eval-table">
              <thead>
                <tr>
                  <th>Tipo</th>
                  <th className="num">P</th>
                  <th className="num">R</th>
                  <th className="num">F1</th>
                </tr>
              </thead>
              <tbody>
                {FOLLOWUP_TYPES.map((t) => (
                  <tr key={t}>
                    <td>{followupLabel(t)}</td>
                    <td className="num">{pct(summary.precision_by_type[t] ?? 0)}</td>
                    <td className="num">{pct(summary.recall_by_type[t] ?? 0)}</td>
                    <td className="num">{pct(summary.f1_by_type[t] ?? 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="card">
            <div className="section-head">
              <h3>Matriz de confusión</h3>
              <span className="muted-inline">filas = esperado · columnas = predicho</span>
            </div>
            <ConfusionMatrix matrix={summary.confusion_matrix} />
          </section>

          <section className="card">
            <div className="section-head">
              <h3>Detalle por par</h3>
            </div>
            <div className="stack">
              {current!.pair_results.map((p) => (
                <PairCard key={`${p.meeting_1_id}-${p.meeting_2_id}`} pair={p} />
              ))}
            </div>
          </section>
        </>
      )}

      {!summary && !loading && (
        <section className="card empty-state">
          Todavía no hay evaluaciones de seguimiento. Pulsa "Ejecutar evaluación" para generar la primera.
        </section>
      )}
    </>
  );
}

function ConfusionMatrix({ matrix }: { matrix: Record<string, Record<string, number>> }) {
  let max = 0;
  for (const row of Object.values(matrix)) {
    for (const v of Object.values(row)) if (v > max) max = v;
  }
  return (
    <div className="confusion-wrapper">
      <table className="eval-table confusion-table">
        <thead>
          <tr>
            <th></th>
            {FOLLOWUP_TYPES.map((t) => (
              <th key={t} className="num" title={followupLabel(t)}>
                {shortType[t]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {FOLLOWUP_TYPES.map((expT) => (
            <tr key={expT}>
              <td title={followupLabel(expT)}>{shortType[expT]}</td>
              {FOLLOWUP_TYPES.map((predT) => {
                const val = matrix[expT]?.[predT] ?? 0;
                const isDiag = expT === predT;
                const intensity = max > 0 ? val / max : 0;
                return (
                  <td
                    key={predT}
                    className={`num confusion-cell${isDiag ? " diag" : ""}`}
                    style={{
                      background:
                        val > 0
                          ? isDiag
                            ? `rgba(4, 120, 87, ${0.15 + intensity * 0.5})`
                            : `rgba(190, 18, 60, ${0.1 + intensity * 0.45})`
                          : "transparent",
                    }}
                  >
                    {val}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PairCard({ pair }: { pair: FollowupPairEvaluation }) {
  const isOk = pair.status === "completed";
  return (
    <article className="pair-card">
      <div className="pair-head">
        <div>
          <div className="pair-title">{pair.series_id}</div>
          <div className="run-row-meta">
            {pair.meeting_1_id} → {pair.meeting_2_id}
          </div>
        </div>
        <Pill
          text={isOk ? "ok" : "fallo"}
          variant={isOk ? "validation-approved" : "validation-rejected"}
        />
      </div>
      <div className="pair-stats">
        <span>Esperados: <strong>{pair.expected_count}</strong></span>
        <span>Predichos: <strong>{pair.predicted_count}</strong></span>
        <span>Emparejados: <strong>{pair.matched_count}</strong></span>
        <span>Tipo correcto: <strong>{pair.correct_type_count}</strong></span>
      </div>
      {pair.error && <p className="trace-explanation">{pair.error}</p>}
      {pair.matches.length > 0 && (
        <table className="eval-table" style={{ marginTop: "0.6rem" }}>
          <thead>
            <tr>
              <th>Esperado</th>
              <th>Esp. tipo</th>
              <th>Pred. tipo</th>
              <th className="num">Sim.</th>
              <th>OK</th>
            </tr>
          </thead>
          <tbody>
            {pair.matches.map((m, i) => (
              <tr key={i}>
                <td>{m.expected_title}</td>
                <td>{m.expected_type ? shortType[m.expected_type as FollowupType] : "—"}</td>
                <td>{m.predicted_type ? shortType[m.predicted_type as FollowupType] : "—"}</td>
                <td className="num">{pct(m.similarity)}</td>
                <td>
                  <Pill
                    text={m.correct_type ? "✓" : "✗"}
                    variant={m.correct_type ? "validation-approved" : "validation-rejected"}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {pair.missing_expected.length > 0 && (
        <div style={{ marginTop: "0.5rem" }}>
          <div className="detail-label">No detectados ({pair.missing_expected.length})</div>
          {pair.missing_expected.map((e, i) => (
            <p key={i} className="commit">
              {shortType[e.followup_type]} · {e.matched_history_title}
            </p>
          ))}
        </div>
      )}
      {pair.unexpected_predicted.length > 0 && (
        <div style={{ marginTop: "0.5rem" }}>
          <div className="detail-label">Falsos positivos ({pair.unexpected_predicted.length})</div>
          {pair.unexpected_predicted.map((p, i) => (
            <p key={i} className="commit">
              {shortType[p.followup_type as FollowupType]} · {p.matched_history_title}
            </p>
          ))}
        </div>
      )}
    </article>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="side-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
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
