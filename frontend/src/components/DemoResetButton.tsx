import { useEffect, useState } from "react";

import { api } from "../api";
import { useToast } from "./Toast";

/**
 * "Reiniciar demo" en la cabecera. Borra los datos derivados locales
 * (analysis_runs, commitments, evaluations, retrieval_index). Pide
 * confirmación con un modal porque la acción es destructiva. Opcionalmente
 * lista los issues de Jira creados por el sistema y deja que el usuario
 * los cierre desde el mismo modal.
 *
 * Lo que NUNCA toca:
 *   - Transcripciones del dataset
 *   - Settings de runtime
 *   - GitHub (los PRs siguen ahí; los cierras tú)
 */
export function DemoResetButton() {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [wipeAudit, setWipeAudit] = useState(false);
  const [jiraPreview, setJiraPreview] = useState<{
    configured: boolean;
    issue_keys: string[];
  } | null>(null);

  useEffect(() => {
    if (!open) return;
    api
      .previewJiraCleanup()
      .then((res) => setJiraPreview({ configured: res.configured, issue_keys: res.issue_keys }))
      .catch(() => setJiraPreview(null));
  }, [open]);

  async function handleReset() {
    if (busy) return;
    setBusy(true);
    try {
      const res = await api.resetDemo(wipeAudit);
      toast.info(`Reset completado: ${res.total} ficheros eliminados.`);
      setOpen(false);
      // Recarga para que las pantallas vuelvan al estado vacío sin caché.
      setTimeout(() => window.location.reload(), 400);
    } catch (err) {
      toast.error(`No se pudo reiniciar: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function handleCleanupJira() {
    if (busy) return;
    setBusy(true);
    try {
      const res = await api.cleanupJira();
      if (res.closed > 0) {
        toast.info(`Cerrados en Jira: ${res.closed} issues.`);
      } else if (res.failed.length > 0) {
        toast.error(`Algunos no se pudieron cerrar (${res.failed.length}).`);
      } else {
        toast.info("No había issues que cerrar.");
      }
      // Refresca el preview para reflejar que ya se cerraron
      const refreshed = await api.previewJiraCleanup();
      setJiraPreview({ configured: refreshed.configured, issue_keys: refreshed.issue_keys });
    } catch (err) {
      toast.error(`Cleanup Jira falló: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        className="demo-reset-trigger"
        onClick={() => setOpen(true)}
        title="Borra runs, compromisos e índices locales"
      >
        Reiniciar demo
      </button>

      {open && (
        <div className="demo-reset-overlay" onClick={() => !busy && setOpen(false)}>
          <div
            className="demo-reset-modal"
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="demo-reset-title">Reiniciar la demo</h2>
            <p className="demo-reset-lede">
              Vacía los datos derivados de la app para empezar desde cero. El
              dataset de transcripciones y tus credenciales no se tocan.
            </p>

            <div className="demo-reset-block">
              <p className="demo-reset-block-title">Lo que se borrará en tu disco</p>
              <ul className="demo-reset-list">
                <li>Análisis de reuniones</li>
                <li>Compromisos persistidos</li>
                <li>Resultados de evaluación</li>
                <li>Índices del RAG (se regeneran al volver a analizar)</li>
              </ul>
              <label className="demo-reset-check">
                <input
                  type="checkbox"
                  checked={wipeAudit}
                  onChange={(e) => setWipeAudit(e.target.checked)}
                />
                <span>
                  Borrar también el audit log del Q&A (D022). Por defecto se
                  conserva.
                </span>
              </label>
            </div>

            <div className="demo-reset-block">
              <p className="demo-reset-block-title">Lo que NO toca este botón</p>
              <ul className="demo-reset-list">
                <li>Issues que ya hayas creado en Jira (botón aparte abajo)</li>
                <li>
                  Branches y pull requests de GitHub (los gestionas tú desde
                  GitHub o relanzando el script <code>bootstrap_github_demo.ps1</code>)
                </li>
                <li>
                  Settings de runtime (provider/modelo activo) y archivo
                  <code>.env</code>
                </li>
              </ul>
            </div>

            {jiraPreview && jiraPreview.configured && jiraPreview.issue_keys.length > 0 && (
              <div className="demo-reset-block demo-reset-jira">
                <p className="demo-reset-block-title">
                  Jira: {jiraPreview.issue_keys.length} issues creados por la app
                </p>
                <p className="demo-reset-jira-keys">
                  {jiraPreview.issue_keys.slice(0, 6).join(", ")}
                  {jiraPreview.issue_keys.length > 6 ? ", …" : ""}
                </p>
                <button
                  type="button"
                  className="demo-reset-action-secondary"
                  onClick={handleCleanupJira}
                  disabled={busy}
                >
                  Cerrar estos issues en Jira
                </button>
              </div>
            )}

            <div className="demo-reset-actions">
              <button
                type="button"
                className="demo-reset-action-cancel"
                onClick={() => setOpen(false)}
                disabled={busy}
              >
                Cancelar
              </button>
              <button
                type="button"
                className="demo-reset-action-primary"
                onClick={handleReset}
                disabled={busy}
              >
                {busy ? "Reiniciando…" : "Reiniciar datos locales"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
