import type {
  AgentConfig,
  AnalyzeResponse,
  Commitment,
  CommitmentRefreshBatch,
  CommitmentRefreshResponse,
  DatasetEvaluationResult,
  EvaluationSummaryRow,
  FollowupEvaluationResult,
  FollowupEvaluationSummaryRow,
  JiraCreatedIssue,
  MeetingSummary,
  PersistedAnalysisRun,
  QAStreamEvent,
  QAScope,
  RunSummary,
  SegmentContext,
  SprintSummary,
  Transcript,
  TranscriptSummary,
  ValidationStatus,
} from "./types";

async function fetchJSON<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  const isJson = (response.headers.get("content-type") || "").includes("application/json");
  const payload = isJson ? await response.json() : null;

  if (!response.ok) {
    const detail = (payload && payload.detail) || `Request failed: ${response.status}`;
    throw new Error(detail);
  }

  return payload as T;
}

export type RuntimeProfile = "local" | "openai" | "anthropic";

export interface RuntimeSettings {
  profile: RuntimeProfile;
  model_overrides: Record<RuntimeProfile, string | null>;
  allowed_profiles: RuntimeProfile[];
  default_profile: RuntimeProfile;
  default_models: Record<RuntimeProfile, string | null>;
  known_models: Record<RuntimeProfile, string[]>;
}

export const api = {
  listAgents: () => fetchJSON<AgentConfig>("/api/agents"),

  getRuntimeSettings: () => fetchJSON<RuntimeSettings>("/api/settings/runtime-profile"),

  setRuntimeProfile: (profile: RuntimeProfile) =>
    fetchJSON<RuntimeSettings>("/api/settings/runtime-profile", {
      method: "PUT",
      body: JSON.stringify({ profile }),
    }),

  setChatModel: (profile: RuntimeProfile, model: string | null) =>
    fetchJSON<RuntimeSettings>("/api/settings/chat-model", {
      method: "PUT",
      body: JSON.stringify({ profile, model }),
    }),

  resetDemo: (wipeAudit: boolean) =>
    fetchJSON<{
      deleted: Record<string, number>;
      total: number;
      wiped_audit: boolean;
    }>("/api/demo/reset", {
      method: "POST",
      body: JSON.stringify({ wipe_audit: wipeAudit }),
    }),

  previewJiraCleanup: () =>
    fetchJSON<{
      configured: boolean;
      dry_run: boolean;
      issue_keys: string[];
    }>("/api/demo/cleanup-jira", {
      method: "POST",
      body: JSON.stringify({ dry_run: true }),
    }),

  cleanupJira: () =>
    fetchJSON<{
      configured: boolean;
      dry_run: boolean;
      issue_keys: string[];
      closed: number;
      closed_keys?: string[];
      failed: Array<{ key: string; reason: string }>;
    }>("/api/demo/cleanup-jira", {
      method: "POST",
      body: JSON.stringify({ dry_run: false }),
    }),

  listTranscripts: () => fetchJSON<TranscriptSummary[]>("/api/transcripts"),

  getTranscript: (id: string) => fetchJSON<Transcript>(`/api/transcripts/${id}`),

  analyzeTranscript: (id: string) =>
    fetchJSON<AnalyzeResponse>(`/api/transcripts/${id}/analyze`, { method: "POST" }),

  analyzeRaw: (title: string, provider: string, transcriptText: string) =>
    fetchJSON<AnalyzeResponse>("/api/analyze/raw", {
      method: "POST",
      body: JSON.stringify({ title, provider, transcript_text: transcriptText }),
    }),

  patchValidation: (runId: string, itemIndex: number, status: ValidationStatus) =>
    fetchJSON<{ run_id: string; item_index: number; validation_status: ValidationStatus }>(
      `/api/runs/${runId}/items/${itemIndex}`,
      { method: "PATCH", body: JSON.stringify({ validation_status: status }) }
    ),

  createJiraIssue: (runId: string, itemIndex: number) =>
    fetchJSON<{ run_id: string; item_index: number; jira_issue: JiraCreatedIssue }>(
      `/api/runs/${runId}/items/${itemIndex}/create-jira-issue`,
      { method: "POST" }
    ),

  listRuns: (limit = 20) => fetchJSON<RunSummary[]>(`/api/runs?limit=${limit}`),

  getRun: (runId: string) => fetchJSON<PersistedAnalysisRun>(`/api/runs/${runId}`),

  listMeetings: (sprintId?: string) => {
    const qs = sprintId ? `?sprint_id=${encodeURIComponent(sprintId)}` : "";
    return fetchJSON<MeetingSummary[]>(`/api/meetings${qs}`);
  },

  listSprints: () => fetchJSON<SprintSummary[]>("/api/sprints"),

  getTranscriptContext: (transcriptId: string, segmentIndex: number, window = 2) =>
    fetchJSON<SegmentContext>(
      `/api/transcripts/${transcriptId}/context?segment_index=${segmentIndex}&window=${window}`
    ),

  listEvaluations: (limit = 20) => fetchJSON<EvaluationSummaryRow[]>(`/api/evaluations?limit=${limit}`),

  getEvaluation: (id: string) => fetchJSON<DatasetEvaluationResult>(`/api/evaluations/${id}`),

  runEvaluation: () =>
    fetchJSON<{ evaluation: DatasetEvaluationResult }>("/api/evaluations", { method: "POST" }),

  listCommitments: (limit = 50, sprintId?: string) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (sprintId) params.set("sprint_id", sprintId);
    return fetchJSON<Commitment[]>(`/api/commitments?${params.toString()}`);
  },

  getCommitment: (id: string) => fetchJSON<Commitment>(`/api/commitments/${id}`),

  refreshCommitment: (id: string) =>
    fetchJSON<CommitmentRefreshResponse>(`/api/commitments/${id}/refresh`, { method: "POST" }),

  dismissDuplicate: (id: string) =>
    fetchJSON<{ commitment: Commitment; changed: boolean }>(
      `/api/commitments/${id}/dismiss-duplicate`,
      { method: "POST" }
    ),

  refreshAllCommitments: () =>
    fetchJSON<CommitmentRefreshBatch>("/api/commitments/refresh-all", { method: "POST" }),

  listFollowupEvaluations: (limit = 20) =>
    fetchJSON<FollowupEvaluationSummaryRow[]>(`/api/followup-evaluations?limit=${limit}`),

  getFollowupEvaluation: (id: string) =>
    fetchJSON<FollowupEvaluationResult>(`/api/followup-evaluations/${id}`),

  runFollowupEvaluation: (retrievalMode: "off" | "current" | "all" = "off") =>
    fetchJSON<{ evaluation: FollowupEvaluationResult }>(
      `/api/followup-evaluations?retrieval_mode=${retrievalMode}`,
      { method: "POST" }
    ),

  runFollowupAblation: () =>
    fetchJSON<{ ablation: FollowupEvaluationResult[] }>(
      "/api/followup-evaluations?ablation=true",
      { method: "POST" }
    ),

  askQuestion: async (
    question: string,
    sprintId: string | null,
    scope: QAScope,
    onEvent: (event: QAStreamEvent) => void,
    signal?: AbortSignal
  ): Promise<void> => {
    const response = await fetch("/api/qa/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, sprint_id: sprintId, scope }),
      signal,
    });
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(text || `Request failed: ${response.status}`);
    }
    if (!response.body) {
      throw new Error("Streaming not supported by this browser");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let newlineIndex = buffer.indexOf("\n");
      while (newlineIndex !== -1) {
        const line = buffer.slice(0, newlineIndex).trim();
        buffer = buffer.slice(newlineIndex + 1);
        if (line) {
          try {
            const event = JSON.parse(line) as QAStreamEvent;
            onEvent(event);
          } catch {
            /* swallow malformed line */
          }
        }
        newlineIndex = buffer.indexOf("\n");
      }
    }
    // Flush trailing line if any.
    const trailing = buffer.trim();
    if (trailing) {
      try {
        const event = JSON.parse(trailing) as QAStreamEvent;
        onEvent(event);
      } catch {
        /* swallow */
      }
    }
  },
};
