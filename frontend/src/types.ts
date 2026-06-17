export type ItemType = "task" | "ambiguous_task" | "technical_decision";
export type ConfidenceLevel = "high" | "medium" | "low";
export type ValidationStatus = "pending_review" | "approved" | "rejected";
export type EvidenceLevel = "sufficient" | "partial" | "none";

export type FollowupType =
  | "recurring_unresolved"
  | "scope_change"
  | "new_blocker"
  | "blocker_resolved"
  | "possible_duplicate"
  | "contradicts_decision"
  | "verbal_close";

export interface IssueDraft {
  title: string;
  description: string;
  labels: string[];
}

export interface JiraIssueMatch {
  issue_key: string;
  summary: string;
  status: string;
  issue_type: string;
  url: string;
}

export interface JiraCreatedIssue {
  issue_key: string;
  url: string;
}

export interface GitCommitRef {
  hash: string;
  message: string;
  author: string;
  date: string;
}

export interface GitEvidence {
  evidence_level: EvidenceLevel;
  explanation: string;
  supporting_commits: GitCommitRef[];
}

export interface DetectedItem {
  item_type: ItemType;
  title: string;
  summary: string;
  confidence: ConfidenceLevel;
  speaker: string;
  timestamp: string | null;
  evidence: string;
  issue_draft: IssueDraft | null;
  jira_matches: JiraIssueMatch[];
  validation_status: ValidationStatus;
  jira_created_issue: JiraCreatedIssue | null;
  git_evidence: GitEvidence | null;
  commitment_id: string | null;
}

export interface AnalysisSummary {
  total_items: number;
  clear_tasks: number;
  ambiguous_tasks: number;
  technical_decisions: number;
}

export interface AgentRun {
  agent_id: string;
  agent_name: string;
  provider: string;
  model: string;
  status: "completed" | "failed";
  output_key: string;
  raw_content: string | null;
  error: string | null;
}

export interface FollowupUpdate {
  followup_type: FollowupType;
  matched_history_title: string;
  explanation: string;
  trigger_quote: string;
  new_title: string | null;
  new_summary: string | null;
  matched_new_item_index: number | null;
}

export type CommitmentState =
  | "detected"
  | "validated"
  | "registered"
  | "in_code_review"
  | "evidenced"
  | "closed"
  | "rejected";

export type CommitmentEventType =
  | "detected"
  | "validated"
  | "rejected"
  | "jira_created"
  | "jira_status_refreshed"
  | "jira_sync_failed"
  | "jira_scope_synced"
  | "jira_blocker_labeled"
  | "jira_blocker_cleared"
  | "git_evidence_updated"
  | "github_evidence_updated"
  | "followup"
  | "scope_changed"
  | "duplicate_dismissed"
  | "closed";

// ===== GitHub evidence (D023) =====

export type GitHubEvidenceLevel = "none" | "in_code_review" | "merged";

export interface GitHubPullRequest {
  number: number;
  title: string;
  html_url: string;
  state: "open" | "closed";
  merged: boolean;
  merged_at: string | null;
  author: string | null;
  head_ref: string | null;
  base_ref: string | null;
}

export interface GitHubCommitRef {
  sha: string;
  message: string;
  date: string;
  author: string | null;
  html_url: string | null;
}

export interface GitHubEvidence {
  evidence_level: GitHubEvidenceLevel;
  explanation: string;
  repo: string;
  pull_requests_open: GitHubPullRequest[];
  pull_requests_merged: GitHubPullRequest[];
  supporting_commits: GitHubCommitRef[];
}

export interface GitHubConfig {
  configured: boolean;
  repo: string;
  token: string;
  base_url: string;
}

export interface CommitmentOrigin {
  source_run_id: string;
  transcript_id: string;
  meeting_title: string;
  meeting_date: string | null;
  sprint_id: string | null;
  segment_index: number | null;
  speaker: string;
  timestamp: string | null;
  evidence: string;
}

export interface CommitmentEvent {
  event_type: CommitmentEventType;
  run_id: string | null;
  meeting_title: string | null;
  meeting_date: string | null;
  detail: string;
  recorded_at: string;
  followup_type: FollowupType | null;
  previous_title: string | null;
  new_title: string | null;
  trigger_quote: string;
}

export interface Commitment {
  commitment_id: string;
  title: string;
  summary: string;
  item_type: ItemType;
  state: CommitmentState;
  origin: CommitmentOrigin;
  jira_created_issue: JiraCreatedIssue | null;
  git_evidence: GitEvidence | null;
  github_evidence: GitHubEvidence | null;
  timeline: CommitmentEvent[];
  created_at: string;
  updated_at: string;
}

export interface GitEvidenceUpdate {
  commitment_id: string;
  evidence: GitEvidence;
}

export interface AnalysisResult {
  transcript_id: string;
  transcript_title: string;
  items: DetectedItem[];
  summary: AnalysisSummary;
  pipeline_id: string;
  agent_runs: AgentRun[];
  followup_updates: FollowupUpdate[];
  git_evidence_updates: GitEvidenceUpdate[];
  run_id: string | null;
  created_at: string | null;
}

export interface TranscriptSummary {
  id: string;
  title: string;
  provider?: string;
}

export interface Transcript {
  id: string;
  title: string;
  provider: string;
  raw_text: string | null;
  meeting_date?: string | null;
}

export interface AgentConfig {
  pipeline_id: string;
  pipeline: string[];
  agents: { id: string; name: string }[];
}

export interface RunSummary {
  run_id: string;
  created_at: string;
  transcript_id: string;
  transcript_title: string;
  transcript_provider: string;
  pipeline_id: string;
  summary: AnalysisSummary;
  agent_count: number;
}

export interface MeetingSummary {
  id: string;
  title: string;
  provider: string;
  meeting_date: string | null;
  sprint_id: string | null;
  analyzed: boolean;
  analyzed_at: string | null;
  commitments_count: number;
  run_id: string | null;
}

export interface SprintSummary {
  sprint_id: string | null;
  transcript_ids: string[];
  transcript_count: number;
  meeting_dates: string[];
}

export interface SegmentContextEntry {
  index: number;
  speaker: string;
  timestamp: string | null;
  text: string;
  is_focus: boolean;
}

export interface SegmentContext {
  transcript_id: string;
  transcript_title: string;
  sprint_id: string | null;
  focus_index: number;
  segments: SegmentContextEntry[];
}

export interface PersistedAnalysisRun {
  run_id: string;
  created_at: string;
  transcript_id: string;
  transcript_title: string;
  transcript_provider: string;
  pipeline_id: string;
  analysis: AnalysisResult;
}

export interface AnalyzeResponse {
  transcript: Transcript;
  analysis: AnalysisResult;
}

export interface EvaluationItemLink {
  expected_item_type: ItemType;
  expected_title: string;
  detected_item_type: ItemType;
  detected_title: string;
  similarity: number;
}

export interface TranscriptEvaluationResult {
  transcript_id: string;
  transcript_title: string;
  status: "completed" | "failed";
  error: string | null;
  expected_count: number;
  detected_count: number;
  matched_count: number;
  false_negative_count: number;
  false_positive_count: number;
  misclassified_count: number;
  precision: number;
  recall: number;
  f1: number;
  matches: EvaluationItemLink[];
}

export interface DatasetEvaluationSummary {
  transcript_count: number;
  completed_transcripts: number;
  failed_transcripts: number;
  expected_count: number;
  detected_count: number;
  matched_count: number;
  false_negative_count: number;
  false_positive_count: number;
  misclassified_count: number;
  precision: number;
  recall: number;
  f1: number;
}

export interface DatasetEvaluationResult {
  evaluation_id: string | null;
  created_at: string | null;
  pipeline_id: string;
  matching_threshold: number;
  transcript_results: TranscriptEvaluationResult[];
  summary: DatasetEvaluationSummary;
}

export interface EvaluationSummaryRow {
  evaluation_id: string;
  created_at: string;
  pipeline_id: string;
  summary: DatasetEvaluationSummary;
}

// ----- Followup evaluation (H6) -----

export interface ExpectedFollowup {
  followup_type: FollowupType;
  matched_history_title: string;
}

export interface FollowupEvaluationPairMatch {
  expected_title: string;
  expected_type: FollowupType | null;
  predicted_type: FollowupType | null;
  similarity: number;
  correct_type: boolean;
}

export interface FollowupPairEvaluation {
  series_id: string;
  meeting_1_id: string;
  meeting_2_id: string;
  expected_count: number;
  predicted_count: number;
  matched_count: number;
  correct_type_count: number;
  matches: FollowupEvaluationPairMatch[];
  missing_expected: ExpectedFollowup[];
  unexpected_predicted: FollowupUpdate[];
  status: "completed" | "failed";
  error: string | null;
}

export interface FollowupEvaluationSummary {
  pair_count: number;
  completed_pairs: number;
  failed_pairs: number;
  expected_count: number;
  predicted_count: number;
  matched_count: number;
  correct_type_count: number;
  coverage: number;
  precision_micro: number;
  recall_micro: number;
  f1_micro: number;
  precision_macro: number;
  recall_macro: number;
  f1_macro: number;
  precision_by_type: Record<string, number>;
  recall_by_type: Record<string, number>;
  f1_by_type: Record<string, number>;
  confusion_matrix: Record<string, Record<string, number>>;
}

export type RetrievalMode = "off" | "current" | "all";

export interface CommitmentRefreshChange {
  source: "jira" | "git";
  event_type: string;
  detail: string;
  previous_state: string | null;
  new_state: string | null;
}

export interface CommitmentRefreshResult {
  commitment_id: string;
  changed: boolean;
  jira_configured: boolean;
  git_configured: boolean;
  changes: CommitmentRefreshChange[];
  reason: string | null;
}

export interface CommitmentRefreshResponse {
  refresh: CommitmentRefreshResult;
  commitment?: Commitment;
}

export interface CommitmentRefreshBatch {
  refreshed: number;
  changed: number;
  per_commitment: CommitmentRefreshResult[];
}

export type QASourceType = "transcript" | "commitment";
export type QAScope = "analyzed_only" | "all";

export interface QASource {
  index: number;
  source_type: QASourceType;
  sprint_id: string | null;
  title: string;
  subtitle: string;
  text: string;
  similarity: number;
  transcript_id: string | null;
  segment_indices: number[];
  commitment_id: string | null;
  commitment_state: string | null;
}

export interface QAStreamSourcesEvent {
  type: "sources";
  sources: QASource[];
}

export interface QAStreamTokenEvent {
  type: "token";
  text: string;
}

export interface QAStreamDoneEvent {
  type: "done";
}

export interface QAStreamErrorEvent {
  type: "error";
  detail: string;
}

// ----- Guardrails (Decisión 022) -----

export type GuardrailRule =
  | "length"
  | "prompt_injection"
  | "empty_context"
  | "out_of_scope";

export interface QAStreamGuardrailEvent {
  type: "guardrail_block";
  rule: GuardrailRule;
  detail: string;
  pattern_matched?: string;
  top_similarity?: number;
}

export type ConfidenceBand = "high" | "medium" | "low";

export interface QAStreamConfidenceEvent {
  type: "confidence";
  band: ConfidenceBand;
  top_similarity: number;
  source_count: number;
}

export interface QAStreamCitationAuditEvent {
  type: "citation_audit";
  cited: number[];
  valid_indices: number[];
  hallucinated: number[];
  unused: number[];
}

export type QAStreamEvent =
  | QAStreamSourcesEvent
  | QAStreamTokenEvent
  | QAStreamDoneEvent
  | QAStreamErrorEvent
  | QAStreamGuardrailEvent
  | QAStreamConfidenceEvent
  | QAStreamCitationAuditEvent;

export interface FollowupEvaluationResult {
  evaluation_id: string | null;
  created_at: string | null;
  pipeline_id: string;
  matching_threshold: number;
  retrieval_mode: RetrievalMode;
  pair_results: FollowupPairEvaluation[];
  summary: FollowupEvaluationSummary;
}

export interface FollowupEvaluationSummaryRow {
  evaluation_id: string;
  created_at: string;
  pipeline_id: string;
  retrieval_mode?: RetrievalMode;
  summary: FollowupEvaluationSummary;
}
