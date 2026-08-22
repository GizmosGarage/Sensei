import json
import unittest

from sensei.learning import (
    LearningEventError,
    LearningEventExtractor,
    Outcome,
    parse_learning_event,
)
from sensei.providers import CompletionResult
from sensei.tutor import LearningSnapshot
from sensei.verification import (
    VerificationKind,
    VerificationResult,
    VerificationStatus,
)


def snapshot(
    verification: VerificationResult | None = None,
    *,
    quest_id: str | None = None,
    quest_skill_id: str | None = None,
) -> LearningSnapshot:
    return LearningSnapshot(
        problem="Differentiate sin(x^2)",
        messages=(
            {"role": "user", "content": "I think I use the chain rule."},
            {"role": "assistant", "content": "What is the inner derivative?"},
        ),
        tutor_turns=1,
        hints_used=0,
        solution_revealed=False,
        verification=verification,
        quest_id=quest_id,
        quest_skill_id=quest_skill_id,
    )


class FakeProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.requests: list[list[dict[str, str]]] = []

    def complete(self, messages, on_token=None) -> CompletionResult:
        self.requests.append(list(messages))
        return CompletionResult(self.responses.pop(0), "stop")


class LearningEventTests(unittest.TestCase):
    def test_parse_valid_event_and_honor_student_override(self) -> None:
        content = json.dumps(
            {
                "skill_id": "chain_rule",
                "outcome": "partial",
                "misconception": "Forgot the inner derivative.",
                "evidence": "The student identified the chain rule.",
                "confidence": 0.9,
            }
        )
        event = parse_learning_event(
            content,
            valid_skill_ids={"chain_rule"},
            snapshot=snapshot(),
            outcome_override=Outcome.CORRECT,
        )
        self.assertEqual(Outcome.CORRECT, event.outcome)
        self.assertEqual("student", event.outcome_source)
        self.assertEqual("chain_rule", event.skill_id)
        self.assertEqual(1, event.tutor_turns)

    def test_parse_rejects_extra_fields(self) -> None:
        content = json.dumps(
            {
                "skill_id": "chain_rule",
                "outcome": "correct",
                "misconception": None,
                "evidence": "Observable work.",
                "confidence": 0.8,
                "extra": True,
            }
        )
        with self.assertRaises(LearningEventError):
            parse_learning_event(
                content,
                valid_skill_ids={"chain_rule"},
                snapshot=snapshot(),
            )

    def test_extractor_retries_invalid_json_with_one_system_message(self) -> None:
        valid = json.dumps(
            {
                "skill_id": "chain_rule",
                "outcome": "partial",
                "misconception": None,
                "evidence": "The student named the chain rule.",
                "confidence": 0.8,
            }
        )
        provider = FakeProvider(["not json", valid])
        extractor = LearningEventExtractor(
            provider,
            {"calculus_foundations": "Foundations", "chain_rule": "Chain rule"},
        )
        event = extractor.extract(snapshot())
        self.assertEqual("chain_rule", event.skill_id)
        self.assertEqual(2, len(provider.requests))
        self.assertTrue(
            all(
                sum(message["role"] == "system" for message in request) == 1
                for request in provider.requests
            )
        )

    def test_verified_result_overrides_report_without_losing_provenance(self) -> None:
        verification = VerificationResult(
            VerificationKind.DERIVATIVE,
            VerificationStatus.VERIFIED_INCORRECT,
            "cos(x**2)",
            "2*x*cos(x**2)",
            "The inner derivative is missing.",
        )
        content = json.dumps(
            {
                "skill_id": "chain_rule",
                "outcome": "correct",
                "misconception": "Missing the inner derivative.",
                "evidence": "The submitted derivative omitted 2x.",
                "confidence": 1.0,
            }
        )
        event = parse_learning_event(
            content,
            valid_skill_ids={"chain_rule"},
            snapshot=snapshot(verification),
            outcome_override=Outcome.CORRECT,
        )
        self.assertEqual(Outcome.INCORRECT, event.outcome)
        self.assertEqual(Outcome.CORRECT, event.reported_outcome)
        self.assertEqual("student", event.outcome_source)
        self.assertEqual("verifier", event.effective_outcome_source)
        self.assertEqual("verified_incorrect", event.verification_status)

    def test_curated_quest_owns_skill_classification_and_provenance(self) -> None:
        verification = VerificationResult(
            VerificationKind.DERIVATIVE,
            VerificationStatus.VERIFIED_CORRECT,
            "3*x**2*cos(x**3)",
            "3*x**2*cos(x**3)",
            "The quest answer is equivalent.",
        )
        content = json.dumps(
            {
                "skill_id": "basic_derivative_rules",
                "outcome": "correct",
                "misconception": None,
                "evidence": "The student supplied the verified derivative.",
                "confidence": 0.2,
            }
        )
        event = parse_learning_event(
            content,
            valid_skill_ids={"basic_derivative_rules", "chain_rule"},
            snapshot=snapshot(
                verification,
                quest_id="chain-sine-cubic",
                quest_skill_id="chain_rule",
            ),
        )
        self.assertEqual("chain_rule", event.skill_id)
        self.assertEqual("chain-sine-cubic", event.quest_id)
        self.assertEqual(1.0, event.confidence)
        self.assertEqual("verifier", event.effective_outcome_source)


if __name__ == "__main__":
    unittest.main()
