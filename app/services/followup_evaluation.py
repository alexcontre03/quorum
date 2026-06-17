"""Evaluación del razonamiento de seguimiento (H6 / Decisión 006).

Recorre los pares de seguimiento del dataset (transcripciones con `series_id`), ejecuta el
pipeline sobre reunión 1, alimenta el historial al análisis de reunión 2 y compara los
`followup_updates` predichos contra los `expected_followups` etiquetados manualmente.

Las predicciones se emparejan con las esperadas por similitud de título normalizado del
`matched_history_title`. Las métricas reportadas son matriz de confusión 7×7,
precision/recall/F1 por tipo, agregados micro y macro, y cobertura.

Importante: este servicio invoca al orquestador pero NO sincroniza compromisos (no llama
al `CommitmentSyncService`), para no contaminar el repositorio de compromisos con datos
experimentales.
"""

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import typing
import unicodedata

from app.agents.exceptions import AgentExecutionError
from app.agents.orchestrator import MeetingAnalysisOrchestrator
from app.domain.models import (
    ExpectedFollowup,
    FollowupEvaluationPairMatch,
    FollowupEvaluationResult,
    FollowupEvaluationSummary,
    FollowupPairEvaluation,
    FollowupType,
    FollowupUpdate,
    HistoryItemSummary,
    MeetingTranscript,
    RetrievalMode,
)

_FOLLOWUP_TYPES: tuple[FollowupType, ...] = (
    "recurring_unresolved",
    "scope_change",
    "new_blocker",
    "blocker_resolved",
    "possible_duplicate",
    "contradicts_decision",
    "verbal_close",
)


@dataclass(frozen=True)
class _Candidate:
    expected_index: int
    predicted_index: int
    similarity: float


class FollowupEvaluationService:
    def __init__(
        self,
        orchestrator: MeetingAnalysisOrchestrator | None = None,
        matching_threshold: float = 0.75,
    ) -> None:
        self.orchestrator = orchestrator or MeetingAnalysisOrchestrator()
        self.matching_threshold = matching_threshold

    def evaluate_dataset(
        self,
        transcripts: list[MeetingTranscript],
        retrieval_mode: RetrievalMode = "off",
    ) -> FollowupEvaluationResult:
        chains = self._collect_chains(transcripts)
        pair_results: list[FollowupPairEvaluation] = []
        # Cache de "análisis sin historial" por id de transcripción, reutilizable entre transiciones
        # de la misma serie (cada predecesor se analiza UNA vez por modo).
        predecessor_cache: dict[str, list[HistoryItemSummary]] = {}

        for predecessors, current in chains:
            pair_results.append(
                self._evaluate_transition(
                    predecessors, current, predecessor_cache, retrieval_mode
                )
            )

        summary = self._summarize(pair_results)
        catalog = self.orchestrator.catalog_loader.load()
        return FollowupEvaluationResult(
            pipeline_id=catalog.pipeline_id,
            matching_threshold=self.matching_threshold,
            retrieval_mode=retrieval_mode,
            pair_results=pair_results,
            summary=summary,
        )

    def evaluate_ablation(
        self,
        transcripts: list[MeetingTranscript],
    ) -> list[FollowupEvaluationResult]:
        """Ablación de tres puntos (Decisión 012): `off`, `current`, `all`."""
        return [
            self.evaluate_dataset(transcripts, retrieval_mode=mode)
            for mode in ("off", "current", "all")
        ]

    def _collect_chains(
        self, transcripts: list[MeetingTranscript]
    ) -> list[tuple[list[MeetingTranscript], MeetingTranscript]]:
        """Para cada serie, devuelve una lista de transiciones (predecesores, actual).

        Genera una transición por cada meeting con `series_order >= 2` que tenga
        `expected_followups`. Los predecesores son **todos** los anteriores en la serie,
        de modo que el follow-up agent recibe historial combinado.
        """
        by_series: dict[str, list[MeetingTranscript]] = {}
        for t in transcripts:
            sid = t.metadata.get("series_id") if isinstance(t.metadata, dict) else None
            if not sid:
                continue
            by_series.setdefault(sid, []).append(t)

        chains: list[tuple[list[MeetingTranscript], MeetingTranscript]] = []
        for sid, items in by_series.items():
            ordered = sorted(items, key=lambda t: (t.metadata or {}).get("series_order", 0))
            for i in range(1, len(ordered)):
                current = ordered[i]
                if not current.expected_followups:
                    continue
                chains.append((ordered[:i], current))
        return chains

    def _evaluate_transition(
        self,
        predecessors: list[MeetingTranscript],
        current: MeetingTranscript,
        predecessor_cache: dict[str, list[HistoryItemSummary]],
        retrieval_mode: RetrievalMode = "off",
    ) -> FollowupPairEvaluation:
        series_id = (current.metadata or {}).get("series_id", "")
        immediate = predecessors[-1]

        # 1) Analizar cada predecesor (sin historial) una sola vez. Los resultados se
        #    funden como `HistoryItemSummary` y se cachean por id de transcripción.
        history: list[HistoryItemSummary] = []
        for pred in predecessors:
            if pred.id not in predecessor_cache:
                try:
                    analysis = self.orchestrator.analyze(pred, retrieval_mode=retrieval_mode)
                except AgentExecutionError as exc:
                    return FollowupPairEvaluation(
                        series_id=series_id,
                        meeting_1_id=immediate.id,
                        meeting_2_id=current.id,
                        expected_count=len(current.expected_followups),
                        predicted_count=0,
                        matched_count=0,
                        correct_type_count=0,
                        missing_expected=list(current.expected_followups),
                        status="failed",
                        error=f"predecessor analysis failed ({pred.id}): {exc}",
                    )
                predecessor_cache[pred.id] = [
                    HistoryItemSummary(
                        run_id=f"eval-{pred.id}",
                        meeting_title=pred.title,
                        meeting_date=pred.meeting_date,
                        item_type=item.item_type,
                        title=item.title,
                        validation_status="pending_review",
                        jira_issue_key=None,
                        commitment_id=None,
                    )
                    for item in analysis.items
                ]
            history.extend(predecessor_cache[pred.id])

        # 2) Analizar la transcripción actual con el historial combinado.
        try:
            analysis_current = self.orchestrator.analyze(
                current, history=history, retrieval_mode=retrieval_mode
            )
        except AgentExecutionError as exc:
            return FollowupPairEvaluation(
                series_id=series_id,
                meeting_1_id=immediate.id,
                meeting_2_id=current.id,
                expected_count=len(current.expected_followups),
                predicted_count=0,
                matched_count=0,
                correct_type_count=0,
                missing_expected=list(current.expected_followups),
                status="failed",
                error=f"current analysis failed ({current.id}): {exc}",
            )

        predicted = analysis_current.followup_updates
        expected = list(current.expected_followups)
        return self._score_pair(immediate, current, expected, predicted)

    def _score_pair(
        self,
        m1: MeetingTranscript,
        m2: MeetingTranscript,
        expected: list[ExpectedFollowup],
        predicted: list[FollowupUpdate],
    ) -> FollowupPairEvaluation:
        candidates: list[_Candidate] = []
        for ei, exp in enumerate(expected):
            exp_norm = self._normalize(exp.matched_history_title)
            for pi, pred in enumerate(predicted):
                pred_norm = self._normalize(pred.matched_history_title)
                sim = SequenceMatcher(None, exp_norm, pred_norm).ratio()
                if sim >= self.matching_threshold:
                    candidates.append(_Candidate(ei, pi, sim))

        candidates.sort(key=lambda c: c.similarity, reverse=True)
        used_expected: set[int] = set()
        used_predicted: set[int] = set()
        matches: list[FollowupEvaluationPairMatch] = []
        correct = 0

        for cand in candidates:
            if cand.expected_index in used_expected or cand.predicted_index in used_predicted:
                continue
            exp = expected[cand.expected_index]
            pred = predicted[cand.predicted_index]
            is_correct = exp.followup_type == pred.followup_type
            if is_correct:
                correct += 1
            matches.append(
                FollowupEvaluationPairMatch(
                    expected_title=exp.matched_history_title,
                    expected_type=exp.followup_type,
                    predicted_type=pred.followup_type,
                    similarity=cand.similarity,
                    correct_type=is_correct,
                )
            )
            used_expected.add(cand.expected_index)
            used_predicted.add(cand.predicted_index)

        missing = [exp for i, exp in enumerate(expected) if i not in used_expected]
        unexpected = [pred for i, pred in enumerate(predicted) if i not in used_predicted]

        return FollowupPairEvaluation(
            series_id=(m2.metadata or {}).get("series_id", ""),
            meeting_1_id=m1.id,
            meeting_2_id=m2.id,
            expected_count=len(expected),
            predicted_count=len(predicted),
            matched_count=len(matches),
            correct_type_count=correct,
            matches=matches,
            missing_expected=missing,
            unexpected_predicted=unexpected,
            status="completed",
        )

    def _summarize(
        self, pair_results: list[FollowupPairEvaluation]
    ) -> FollowupEvaluationSummary:
        completed = [p for p in pair_results if p.status == "completed"]
        failed = [p for p in pair_results if p.status == "failed"]

        expected_total = sum(p.expected_count for p in pair_results)
        predicted_total = sum(p.predicted_count for p in pair_results)
        matched_total = sum(p.matched_count for p in pair_results)
        correct_total = sum(p.correct_type_count for p in pair_results)

        tp_by_type: dict[str, int] = {t: 0 for t in _FOLLOWUP_TYPES}
        fp_by_type: dict[str, int] = {t: 0 for t in _FOLLOWUP_TYPES}
        fn_by_type: dict[str, int] = {t: 0 for t in _FOLLOWUP_TYPES}
        confusion: dict[str, dict[str, int]] = {
            exp_t: {pred_t: 0 for pred_t in _FOLLOWUP_TYPES} for exp_t in _FOLLOWUP_TYPES
        }

        for p in completed:
            for m in p.matches:
                if m.expected_type and m.predicted_type:
                    confusion[m.expected_type][m.predicted_type] += 1
                    if m.expected_type == m.predicted_type:
                        tp_by_type[m.expected_type] += 1
                    else:
                        fn_by_type[m.expected_type] += 1
                        fp_by_type[m.predicted_type] += 1
            for exp in p.missing_expected:
                fn_by_type[exp.followup_type] += 1
            for pred in p.unexpected_predicted:
                fp_by_type[pred.followup_type] += 1

        precision_by_type: dict[str, float] = {}
        recall_by_type: dict[str, float] = {}
        f1_by_type: dict[str, float] = {}
        for t in _FOLLOWUP_TYPES:
            tp = tp_by_type[t]
            fp = fp_by_type[t]
            fn = fn_by_type[t]
            precision_by_type[t] = tp / (tp + fp) if (tp + fp) else 0.0
            recall_by_type[t] = tp / (tp + fn) if (tp + fn) else 0.0
            denom = precision_by_type[t] + recall_by_type[t]
            f1_by_type[t] = (
                2 * precision_by_type[t] * recall_by_type[t] / denom if denom else 0.0
            )

        tp_total = sum(tp_by_type.values())
        fp_total = sum(fp_by_type.values())
        fn_total = sum(fn_by_type.values())
        precision_micro = tp_total / (tp_total + fp_total) if (tp_total + fp_total) else 0.0
        recall_micro = tp_total / (tp_total + fn_total) if (tp_total + fn_total) else 0.0
        f1_micro_denom = precision_micro + recall_micro
        f1_micro = (
            2 * precision_micro * recall_micro / f1_micro_denom if f1_micro_denom else 0.0
        )

        precision_macro = sum(precision_by_type.values()) / len(_FOLLOWUP_TYPES)
        recall_macro = sum(recall_by_type.values()) / len(_FOLLOWUP_TYPES)
        f1_macro = sum(f1_by_type.values()) / len(_FOLLOWUP_TYPES)

        coverage = matched_total / expected_total if expected_total else 0.0

        return FollowupEvaluationSummary(
            pair_count=len(pair_results),
            completed_pairs=len(completed),
            failed_pairs=len(failed),
            expected_count=expected_total,
            predicted_count=predicted_total,
            matched_count=matched_total,
            correct_type_count=correct_total,
            coverage=coverage,
            precision_micro=precision_micro,
            recall_micro=recall_micro,
            f1_micro=f1_micro,
            precision_macro=precision_macro,
            recall_macro=recall_macro,
            f1_macro=f1_macro,
            precision_by_type=precision_by_type,
            recall_by_type=recall_by_type,
            f1_by_type=f1_by_type,
            confusion_matrix=confusion,
        )

    @staticmethod
    def _normalize(text: str) -> str:
        if not text:
            return ""
        normalized = unicodedata.normalize("NFKD", text)
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        ascii_text = ascii_text.lower()
        ascii_text = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
        ascii_text = re.sub(r"\s+", " ", ascii_text).strip()
        return ascii_text
