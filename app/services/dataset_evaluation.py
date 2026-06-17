from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata

from app.agents.exceptions import AgentExecutionError
from app.agents.orchestrator import MeetingAnalysisOrchestrator
from app.domain.models import (
    DatasetEvaluationResult,
    DatasetEvaluationSummary,
    DetectedItem,
    EvaluationItemLink,
    ExpectedItem,
    MeetingTranscript,
    TranscriptEvaluationResult,
)


@dataclass(frozen=True)
class _ComparisonResult:
    matches: list[EvaluationItemLink]
    misclassified_matches: list[EvaluationItemLink]
    missing_expected_items: list[ExpectedItem]
    unexpected_detected_items: list[DetectedItem]


@dataclass(frozen=True)
class _MatchLinksResult:
    links: list[EvaluationItemLink]
    used_expected_indices: set[int]
    used_detected_indices: set[int]


class DatasetEvaluationService:
    stopwords = {
        "a",
        "al",
        "con",
        "de",
        "del",
        "el",
        "en",
        "la",
        "las",
        "lo",
        "los",
        "para",
        "por",
        "que",
        "se",
        "si",
        "un",
        "una",
        "y",
    }

    def __init__(
        self,
        orchestrator: MeetingAnalysisOrchestrator | None = None,
        matching_threshold: float = 0.58,
    ) -> None:
        self.orchestrator = orchestrator or MeetingAnalysisOrchestrator()
        self.matching_threshold = matching_threshold

    def evaluate_dataset(self, transcripts: list[MeetingTranscript]) -> DatasetEvaluationResult:
        pipeline_id = self.orchestrator.describe().get("pipeline_id", "unknown_pipeline")
        transcript_results = [self.evaluate_transcript(transcript) for transcript in transcripts]
        summary = self._build_dataset_summary(transcript_results)
        return DatasetEvaluationResult(
            pipeline_id=pipeline_id,
            matching_threshold=self.matching_threshold,
            transcript_results=transcript_results,
            summary=summary,
        )

    def evaluate_transcript(self, transcript: MeetingTranscript) -> TranscriptEvaluationResult:
        expected_items = transcript.expected_items
        expected_by_type = self._count_expected_types(expected_items)

        try:
            analysis = self.orchestrator.analyze(transcript)
        except AgentExecutionError as exc:
            return TranscriptEvaluationResult(
                transcript_id=transcript.id,
                transcript_title=transcript.title,
                status="failed",
                error=str(exc),
                expected_count=len(expected_items),
                false_negative_count=len(expected_items),
                expected_by_type=expected_by_type,
                missing_expected_items=expected_items,
            )

        comparison = self._compare_items(expected_items, analysis.items)
        matched_count = len(comparison.matches)
        detected_count = len(analysis.items)
        expected_count = len(expected_items)
        false_negative_count = len(comparison.missing_expected_items)
        false_positive_count = len(comparison.unexpected_detected_items)
        precision = self._ratio(matched_count, detected_count)
        recall = self._ratio(matched_count, expected_count)

        return TranscriptEvaluationResult(
            transcript_id=transcript.id,
            transcript_title=transcript.title,
            status="completed",
            expected_count=expected_count,
            detected_count=detected_count,
            matched_count=matched_count,
            false_negative_count=false_negative_count,
            false_positive_count=false_positive_count,
            misclassified_count=len(comparison.misclassified_matches),
            precision=precision,
            recall=recall,
            f1=self._f1(precision, recall),
            expected_by_type=expected_by_type,
            detected_by_type=self._count_detected_types(analysis.items),
            matched_by_type=self._count_matched_types(comparison.matches),
            matches=comparison.matches,
            misclassified_matches=comparison.misclassified_matches,
            missing_expected_items=comparison.missing_expected_items,
            unexpected_detected_items=comparison.unexpected_detected_items,
            detected_items=analysis.items,
            agent_runs=analysis.agent_runs,
        )

    def _compare_items(
        self,
        expected_items: list[ExpectedItem],
        detected_items: list[DetectedItem],
    ) -> _ComparisonResult:
        expected_indices = list(range(len(expected_items)))
        detected_indices = list(range(len(detected_items)))

        match_result = self._match_links(
            expected_items,
            detected_items,
            expected_indices,
            detected_indices,
            require_same_type=True,
        )

        unmatched_expected_indices = [
            index
            for index in expected_indices
            if index not in match_result.used_expected_indices
        ]
        unmatched_detected_indices = [
            index
            for index in detected_indices
            if index not in match_result.used_detected_indices
        ]

        misclassified_result = self._match_links(
            expected_items,
            detected_items,
            unmatched_expected_indices,
            unmatched_detected_indices,
            require_same_type=False,
            forbid_same_type=True,
        )

        missing_expected_items = [
            expected_items[index]
            for index in unmatched_expected_indices
            if index not in misclassified_result.used_expected_indices
        ]
        unexpected_detected_items = [
            detected_items[index]
            for index in unmatched_detected_indices
            if index not in misclassified_result.used_detected_indices
        ]

        return _ComparisonResult(
            matches=match_result.links,
            misclassified_matches=misclassified_result.links,
            missing_expected_items=missing_expected_items,
            unexpected_detected_items=unexpected_detected_items,
        )

    def _match_links(
        self,
        expected_items: list[ExpectedItem],
        detected_items: list[DetectedItem],
        expected_indices: list[int],
        detected_indices: list[int],
        require_same_type: bool,
        forbid_same_type: bool = False,
    ) -> _MatchLinksResult:
        candidates: list[tuple[float, int, int]] = []

        for expected_index in expected_indices:
            for detected_index in detected_indices:
                expected_item = expected_items[expected_index]
                detected_item = detected_items[detected_index]

                if require_same_type and expected_item.item_type != detected_item.item_type:
                    continue
                if forbid_same_type and expected_item.item_type == detected_item.item_type:
                    continue

                similarity = self._item_similarity(expected_item, detected_item)
                if similarity < self.matching_threshold:
                    continue
                candidates.append((similarity, expected_index, detected_index))

        candidates.sort(key=lambda item: item[0], reverse=True)
        used_expected: set[int] = set()
        used_detected: set[int] = set()
        links: list[EvaluationItemLink] = []

        for similarity, expected_index, detected_index in candidates:
            if expected_index in used_expected or detected_index in used_detected:
                continue

            expected_item = expected_items[expected_index]
            detected_item = detected_items[detected_index]
            links.append(
                EvaluationItemLink(
                    expected_item_type=expected_item.item_type,
                    expected_title=expected_item.title,
                    detected_item_type=detected_item.item_type,
                    detected_title=detected_item.title,
                    similarity=round(similarity, 3),
                )
            )
            used_expected.add(expected_index)
            used_detected.add(detected_index)

        return _MatchLinksResult(
            links=links,
            used_expected_indices=used_expected,
            used_detected_indices=used_detected,
        )

    def _item_similarity(self, expected_item: ExpectedItem, detected_item: DetectedItem) -> float:
        title_similarity = self._text_similarity(expected_item.title, detected_item.title)
        title_to_summary_similarity = self._text_similarity(expected_item.title, detected_item.summary)
        summary_similarity = self._text_similarity(expected_item.summary or "", detected_item.summary)
        return max(
            title_similarity,
            title_to_summary_similarity * 0.9,
            summary_similarity * 0.75,
        )

    def _text_similarity(self, left: str, right: str) -> float:
        normalized_left = self._normalize_text(left)
        normalized_right = self._normalize_text(right)
        if not normalized_left or not normalized_right:
            return 0.0

        sequence_ratio = SequenceMatcher(None, normalized_left, normalized_right).ratio()
        left_tokens = self._tokenize(normalized_left)
        right_tokens = self._tokenize(normalized_right)
        if not left_tokens or not right_tokens:
            return sequence_ratio

        overlap = len(left_tokens & right_tokens)
        containment_ratio = overlap / max(len(left_tokens), len(right_tokens))
        combined_ratio = (sequence_ratio * 0.65) + (containment_ratio * 0.35)
        return max(sequence_ratio, containment_ratio, combined_ratio)

    def _normalize_text(self, value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value or "")
        without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
        lowered = without_accents.lower()
        return re.sub(r"[^a-z0-9]+", " ", lowered).strip()

    def _tokenize(self, value: str) -> set[str]:
        return {token for token in value.split() if token and token not in self.stopwords}

    def _count_expected_types(self, items: list[ExpectedItem]) -> dict[str, int]:
        counts = {"task": 0, "ambiguous_task": 0, "technical_decision": 0}
        for item in items:
            counts[item.item_type] += 1
        return counts

    def _count_detected_types(self, items: list[DetectedItem]) -> dict[str, int]:
        counts = {"task": 0, "ambiguous_task": 0, "technical_decision": 0}
        for item in items:
            counts[item.item_type] += 1
        return counts

    def _count_matched_types(self, items: list[EvaluationItemLink]) -> dict[str, int]:
        counts = {"task": 0, "ambiguous_task": 0, "technical_decision": 0}
        for item in items:
            counts[item.expected_item_type] += 1
        return counts

    def _build_dataset_summary(
        self,
        transcript_results: list[TranscriptEvaluationResult],
    ) -> DatasetEvaluationSummary:
        completed_results = [result for result in transcript_results if result.status == "completed"]
        expected_count = sum(result.expected_count for result in transcript_results)
        detected_count = sum(result.detected_count for result in transcript_results)
        matched_count = sum(result.matched_count for result in transcript_results)
        false_negative_count = sum(result.false_negative_count for result in transcript_results)
        false_positive_count = sum(result.false_positive_count for result in transcript_results)
        misclassified_count = sum(result.misclassified_count for result in transcript_results)
        precision = self._ratio(matched_count, detected_count)
        recall = self._ratio(matched_count, expected_count)

        return DatasetEvaluationSummary(
            transcript_count=len(transcript_results),
            completed_transcripts=len(completed_results),
            failed_transcripts=len(transcript_results) - len(completed_results),
            expected_count=expected_count,
            detected_count=detected_count,
            matched_count=matched_count,
            false_negative_count=false_negative_count,
            false_positive_count=false_positive_count,
            misclassified_count=misclassified_count,
            precision=precision,
            recall=recall,
            f1=self._f1(precision, recall),
        )

    def _ratio(self, numerator: int, denominator: int) -> float:
        if denominator <= 0:
            return 0.0
        return round(numerator / denominator, 4)

    def _f1(self, precision: float, recall: float) -> float:
        if precision + recall == 0:
            return 0.0
        return round((2 * precision * recall) / (precision + recall), 4)
