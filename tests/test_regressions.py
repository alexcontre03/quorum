import unittest

import numpy as np

from app.domain.models import DetectedItem, ExpectedItem, TranscriptEvaluationResult
from app.services.dataset_evaluation import DatasetEvaluationService
from app.services.manual_parser import ManualTranscriptParser
from app.services.qa_service import QAService, _parse_intent


class DatasetEvaluationRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = DatasetEvaluationService()

    def test_misclassified_items_do_not_count_as_missing_and_unexpected(self) -> None:
        expected_items = [
            ExpectedItem(item_type="task", title="anadir validacion login", summary="validar errores login")
        ]
        detected_items = [
            DetectedItem(
                item_type="ambiguous_task",
                title="anadir validacion login",
                summary="validar errores login",
                confidence="medium",
                speaker="Ane",
                evidence="Podriamos anadir validacion login",
            )
        ]

        comparison = self.service._compare_items(expected_items, detected_items)

        self.assertEqual(len(comparison.matches), 0)
        self.assertEqual(len(comparison.misclassified_matches), 1)
        self.assertEqual(len(comparison.missing_expected_items), 0)
        self.assertEqual(len(comparison.unexpected_detected_items), 0)

    def test_dataset_summary_counts_failed_transcripts_in_recall(self) -> None:
        completed = TranscriptEvaluationResult(
            transcript_id="ok-case",
            transcript_title="OK case",
            status="completed",
            expected_count=1,
            detected_count=1,
            matched_count=1,
            false_negative_count=0,
            false_positive_count=0,
            misclassified_count=0,
            precision=1.0,
            recall=1.0,
            f1=1.0,
        )
        failed = TranscriptEvaluationResult(
            transcript_id="failed-case",
            transcript_title="Failed case",
            status="failed",
            expected_count=2,
            detected_count=0,
            matched_count=0,
            false_negative_count=2,
            false_positive_count=0,
            misclassified_count=0,
        )

        summary = self.service._build_dataset_summary([completed, failed])

        self.assertEqual(summary.transcript_count, 2)
        self.assertEqual(summary.completed_transcripts, 1)
        self.assertEqual(summary.failed_transcripts, 1)
        self.assertEqual(summary.expected_count, 3)
        self.assertEqual(summary.false_negative_count, 2)
        self.assertAlmostEqual(summary.precision, 1.0)
        self.assertAlmostEqual(summary.recall, 1 / 3, places=4)
        self.assertAlmostEqual(summary.f1, 0.5, places=4)


class ManualTranscriptParserRegressionTests(unittest.TestCase):
    def test_parser_accepts_accented_speaker_names(self) -> None:
        parser = ManualTranscriptParser()

        transcript = parser.parse("00:00 Jos\u00e9: Hay que revisar login", title="Demo")

        self.assertEqual(len(transcript.segments), 1)
        self.assertEqual(transcript.segments[0].timestamp, "00:00")
        self.assertEqual(transcript.segments[0].speaker, "Jos\u00e9")
        self.assertEqual(transcript.segments[0].text, "Hay que revisar login")


class _FakeTranscriptIndex:
    def __init__(self, payloads: dict[str, tuple[np.ndarray, list[dict]]]) -> None:
        self.payloads = payloads

    def list_indexed_transcripts(self) -> list[str]:
        return list(self.payloads.keys())

    def load(self, transcript_id: str) -> tuple[np.ndarray, list[dict]] | None:
        return self.payloads.get(transcript_id)


class _FakeTranscriptRetriever:
    def __init__(self, payloads: dict[str, tuple[np.ndarray, list[dict]]]) -> None:
        self.index = _FakeTranscriptIndex(payloads)


class _FakeCommitmentIndexer:
    def __init__(self, payload: tuple[np.ndarray, list[dict]] | None) -> None:
        self.payload = payload

    def load(self) -> tuple[np.ndarray, list[dict]] | None:
        return self.payload


class _FakeRunsRepository:
    def __init__(self, analyzed_transcript_ids: set[str]) -> None:
        self.analyzed_transcript_ids = analyzed_transcript_ids

    def list_analyzed_transcript_ids(self) -> set[str]:
        return set(self.analyzed_transcript_ids)


class QAServiceRegressionTests(unittest.TestCase):
    def test_answer_reports_no_analyzed_meetings_before_retrieval(self) -> None:
        service = QAService(
            transcript_retriever=_FakeTranscriptRetriever({}),
            commitment_indexer=_FakeCommitmentIndexer(None),
            analysis_runs=_FakeRunsRepository(set()),
        )

        events = list(
            service.answer(
                "Que bloqueos siguen abiertos",
                None,
                "analyzed_only",
            )
        )

        self.assertEqual(events[0], {"type": "sources", "sources": []})
        self.assertEqual(events[1]["type"], "guardrail_block")
        self.assertEqual(events[1]["rule"], "empty_context")
        self.assertIn("Todavía no hay reuniones analizadas", events[1]["detail"])
        self.assertEqual(events[2]["type"], "token")
        self.assertIn("Todavía no hay reuniones analizadas", events[2]["text"])
        self.assertEqual(events[3], {"type": "done"})

    def test_transcript_candidates_ignore_unanalyzed_meetings_in_default_scope(self) -> None:
        transcript_payloads = {
            "payments-s1-planning": (
                np.array([[1.0, 0.0]], dtype=np.float32),
                [{
                    "text": "Hay un bloqueo con pagos",
                    "sprint_id": "payments-s1",
                    "meeting_title": "Planning S1",
                    "meeting_date": "2026-06-01",
                }],
            ),
            "payments-s1-review": (
                np.array([[0.95, 0.0]], dtype=np.float32),
                [{
                    "text": "Otro bloqueo pendiente",
                    "sprint_id": "payments-s1",
                    "meeting_title": "Review S1",
                    "meeting_date": "2026-06-05",
                }],
            ),
        }
        service = QAService(
            transcript_retriever=_FakeTranscriptRetriever(transcript_payloads),
            commitment_indexer=_FakeCommitmentIndexer(None),
            analysis_runs=_FakeRunsRepository({"payments-s1-planning"}),
        )

        scored = service._gather_transcript_candidates(
            np.array([1.0, 0.0], dtype=np.float32),
            None,
            _parse_intent("Que bloqueos siguen abiertos"),
            service._allowed_transcript_ids("analyzed_only"),
        )

        self.assertEqual(len(scored), 1)
        self.assertEqual(scored[0].payload["transcript_id"], "payments-s1-planning")

    def test_commitment_candidates_ignore_unanalyzed_origins_in_default_scope(self) -> None:
        service = QAService(
            transcript_retriever=_FakeTranscriptRetriever({}),
            commitment_indexer=_FakeCommitmentIndexer(
                (
                    np.array([[1.0, 0.0], [0.92, 0.0]], dtype=np.float32),
                    [
                        {
                            "commitment_id": "c-1",
                            "transcript_id": "payments-s1-planning",
                            "sprint_id": "payments-s1",
                            "indexed_text": "Bloqueado, esperando desbloqueo",
                        },
                        {
                            "commitment_id": "c-2",
                            "transcript_id": "payments-s1-review",
                            "sprint_id": "payments-s1",
                            "indexed_text": "Bloqueado, esperando desbloqueo",
                        },
                    ],
                )
            ),
            analysis_runs=_FakeRunsRepository({"payments-s1-planning"}),
        )

        scored = service._gather_commitment_candidates(
            np.array([1.0, 0.0], dtype=np.float32),
            None,
            _parse_intent("Que bloqueos siguen abiertos"),
            service._allowed_transcript_ids("analyzed_only"),
        )

        self.assertEqual(len(scored), 1)
        self.assertEqual(scored[0].payload["commitment_id"], "c-1")


if __name__ == "__main__":
    unittest.main()
