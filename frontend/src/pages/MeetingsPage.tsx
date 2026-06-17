import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { MeetingSummary } from "../types";
import { useToast } from "../components/Toast";
import { formatSprintId } from "../sprint";

interface SprintBucket {
  sprintId: string | null;
  meetings: MeetingSummary[];
  analyzed: number;
  total: number;
  meetingDates: string[];
}

export function MeetingsPage() {
  const toast = useToast();
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [analyzingId, setAnalyzingId] = useState<string | null>(null);
  const [analyzingBatch, setAnalyzingBatch] = useState(false);

  async function refresh() {
    try {
      const list = await api.listMeetings();
      setMeetings(list);
    } catch (err) {
      toast.error((err as Error).message);
    }
  }

  useEffect(() => {
    refresh().finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sprints = useMemo<SprintBucket[]>(() => {
    const buckets = new Map<string | null, MeetingSummary[]>();
    for (const m of meetings) {
      const key = m.sprint_id;
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key)!.push(m);
    }
    const out: SprintBucket[] = [];
    for (const [sprintId, group] of buckets.entries()) {
      const ordered = [...group].sort((a, b) =>
        (a.meeting_date ?? "").localeCompare(b.meeting_date ?? "")
      );
      out.push({
        sprintId,
        meetings: ordered,
        analyzed: ordered.filter((m) => m.analyzed).length,
        total: ordered.length,
        meetingDates: ordered.map((m) => m.meeting_date).filter((d): d is string => !!d),
      });
    }
    out.sort((a, b) => {
      if (a.sprintId === null) return 1;
      if (b.sprintId === null) return -1;
      return a.sprintId.localeCompare(b.sprintId);
    });
    return out;
  }, [meetings]);

  const totalPending = useMemo(
    () => meetings.filter((m) => !m.analyzed).length,
    [meetings]
  );

  async function analyzeOne(id: string) {
    setAnalyzingId(id);
    try {
      const payload = await api.analyzeTranscript(id);
      toast.success(`Análisis completado · ${payload.analysis.items?.length ?? 0} ítems`);
      await refresh();
    } catch (err) {
      toast.error(`No se pudo analizar: ${(err as Error).message}`);
    } finally {
      setAnalyzingId(null);
    }
  }

  async function analyzePendingInSprint(bucket: SprintBucket) {
    const pendings = bucket.meetings.filter((m) => !m.analyzed);
    if (pendings.length === 0 || analyzingBatch) return;
    setAnalyzingBatch(true);
    try {
      for (const m of pendings) {
        setAnalyzingId(m.id);
        try {
          await api.analyzeTranscript(m.id);
        } catch (err) {
          toast.error(`Fallo en "${m.title}": ${(err as Error).message}`);
        }
      }
      toast.success(`Pendientes del sprint procesadas`);
      await refresh();
    } finally {
      setAnalyzingId(null);
      setAnalyzingBatch(false);
    }
  }

  async function analyzeAllPending() {
    if (totalPending === 0 || analyzingBatch) return;
    setAnalyzingBatch(true);
    try {
      for (const m of meetings.filter((x) => !x.analyzed)) {
        setAnalyzingId(m.id);
        try {
          await api.analyzeTranscript(m.id);
        } catch (err) {
          toast.error(`Fallo en "${m.title}": ${(err as Error).message}`);
        }
      }
      toast.success(`Pendientes procesadas`);
      await refresh();
    } finally {
      setAnalyzingId(null);
      setAnalyzingBatch(false);
    }
  }

  if (loading) {
    return (
      <div className="cb">
        <p className="cb-muted">Cargando reuniones…</p>
      </div>
    );
  }

  return (
    <div className="cb">
      <p className="cb-eyebrow">Fuentes</p>
      <div className="meetings-head">
        <div>
          <h1 className="cb-h1">Reuniones</h1>
          <p className="cb-lede">De aquí salen los compromisos. Cada una se analiza una vez.</p>
        </div>
        {totalPending > 0 && (
          <button
            type="button"
            className="cb-cta"
            onClick={analyzeAllPending}
            disabled={analyzingBatch}
          >
            {analyzingBatch
              ? "Analizando…"
              : `Analizar ${totalPending} pendiente${totalPending === 1 ? "" : "s"}`}
          </button>
        )}
      </div>

      {meetings.length === 0 && (
        <div className="cb-empty">No hay reuniones en el dataset todavía.</div>
      )}

      {sprints.map((bucket) => {
        const pending = bucket.meetings.filter((m) => !m.analyzed);
        const sprintLabel = bucket.sprintId
          ? formatSprintId(bucket.sprintId)
          : "Sin sprint asignado";
        const dateRange = formatDateRange(bucket.meetingDates);
        return (
          <section key={bucket.sprintId ?? "_no_sprint"} className="cb-section">
            <div className="meetings-sprint-head">
              <div>
                <p className="cb-section-label">{sprintLabel}</p>
                <p className="cb-row-sub">
                  {bucket.analyzed}/{bucket.total} analizadas
                  {dateRange ? ` · ${dateRange}` : ""}
                </p>
              </div>
              {pending.length > 0 && (
                <button
                  type="button"
                  className="cb-row-action"
                  onClick={() => analyzePendingInSprint(bucket)}
                  disabled={analyzingBatch}
                >
                  Analizar pendientes
                </button>
              )}
            </div>
            {bucket.meetings.map((m) => (
              <Row
                key={m.id}
                meeting={m}
                busy={analyzingId === m.id}
                onAction={() => analyzeOne(m.id)}
                actionLabel={m.analyzed ? "Reanalizar" : "Analizar"}
              />
            ))}
          </section>
        );
      })}
    </div>
  );
}

function Row({
  meeting,
  busy,
  onAction,
  actionLabel,
}: {
  meeting: MeetingSummary;
  busy: boolean;
  onAction: () => void;
  actionLabel: string;
}) {
  const sub = meeting.analyzed
    ? `analizada${meeting.analyzed_at ? ` el ${formatShort(meeting.analyzed_at)}` : ""} · ${meeting.commitments_count} compromiso${meeting.commitments_count === 1 ? "" : "s"}`
    : "añadida · aún sin procesar";
  const tone = meeting.analyzed ? "var(--success)" : "var(--text-tertiary)";
  const tagText = meeting.analyzed ? "✓ Analizada" : "Sin analizar";

  return (
    <div className="cb-row meetings-row">
      <div className="cb-row-main">
        <p className="cb-row-title">{meeting.title}</p>
        <p className="cb-row-sub">{sub}</p>
      </div>
      <span className="cb-row-tag" style={{ color: tone }}>
        {tagText}
      </span>
      <button
        type="button"
        className="cb-cta meetings-action"
        onClick={onAction}
        disabled={busy}
      >
        {busy ? "Analizando…" : actionLabel}
      </button>
    </div>
  );
}

function formatShort(iso: string): string {
  if (iso.length < 10) return iso;
  const [, mm, dd] = iso.slice(0, 10).split("-");
  const months = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
  const idx = parseInt(mm, 10) - 1;
  if (idx < 0 || idx > 11) return iso.slice(0, 10);
  return `${parseInt(dd, 10)} ${months[idx]}`;
}


function formatDateRange(dates: string[]): string {
  if (dates.length === 0) return "";
  if (dates.length === 1) return formatShort(dates[0]);
  return `${formatShort(dates[0])} – ${formatShort(dates[dates.length - 1])}`;
}
