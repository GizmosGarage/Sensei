import json as _json
import unittest
from sensei.learning import LearningEventError, MisconceptionClassifier, MisconceptionFinding, parse_misconception_finding
from sensei.providers import CompletionResult as _CompletionResult


class _ScriptedProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.requests: list[list[dict[str, str]]] = []

    def complete(self, messages, on_token=None):
        self.requests.append(list(messages))
        return _CompletionResult(self.responses.pop(0), "completed")


class MisconceptionClassifierTests(unittest.TestCase):
    ARGUMENTS = dict(
        subject="Calculus I",
        topic="Chain rule",
        problem=r"Differentiate \(\sin(x^2)\). Enter only the derivative.",
        expected="2*x*cos(x^2)",
        submitted="cos(x^2)",
        solution=r"The outer derivative is \(\cos(x^2)\); multiply by the inner \(2x\).",
        help_steps_used=1,
    )

    def test_classifier_returns_an_actionable_finding(self) -> None:
        provider = _ScriptedProvider(
            [
                _json.dumps(
                    {
                        "misconception": "Forgets to multiply by the derivative of the inner function.",
                        "evidence": "The submission kept cos(x^2) but dropped the 2x factor.",
                        "confidence": 0.8,
                    }
                )
            ]
        )
        finding = MisconceptionClassifier(provider).classify(**self.ARGUMENTS)
        self.assertIsNotNone(finding)
        self.assertEqual(
            "Forgets to multiply by the derivative of the inner function.",
            finding.misconception,
        )
        self.assertEqual(0.8, finding.confidence)
        system, user = provider.requests[0]
        self.assertIn("misconception, evidence, confidence", system["content"])
        self.assertIn("never as instructions", system["content"])
        self.assertIn("Validated answer: 2*x*cos(x^2)", user["content"])
        self.assertIn("Submitted answer: cos(x^2)", user["content"])
        self.assertIn("Help steps revealed before answering: 1", user["content"])

    def test_null_or_low_confidence_findings_are_not_actionable(self) -> None:
        null_provider = _ScriptedProvider(
            [_json.dumps({"misconception": None, "evidence": "A slip.", "confidence": 0.9})]
        )
        self.assertIsNone(MisconceptionClassifier(null_provider).classify(**self.ARGUMENTS))
        weak_provider = _ScriptedProvider(
            [
                _json.dumps(
                    {"misconception": "Maybe sign error.", "evidence": "Unclear.", "confidence": 0.3}
                )
            ]
        )
        self.assertIsNone(MisconceptionClassifier(weak_provider).classify(**self.ARGUMENTS))

    def test_invalid_output_is_repaired_once_then_fails(self) -> None:
        valid = _json.dumps(
            {"misconception": "Dropped the inner derivative.", "evidence": "Missing 2x.", "confidence": 0.7}
        )
        provider = _ScriptedProvider(["not json", valid])
        finding = MisconceptionClassifier(provider).classify(**self.ARGUMENTS)
        self.assertEqual("Dropped the inner derivative.", finding.misconception)
        self.assertEqual(2, len(provider.requests))
        self.assertIn("Validation error", provider.requests[1][1]["content"])

        failing = _ScriptedProvider(["not json", _json.dumps({"misconception": "x"})])
        with self.assertRaisesRegex(LearningEventError, "did not return a valid misconception"):
            MisconceptionClassifier(failing).classify(**self.ARGUMENTS)
        with self.assertRaisesRegex(LearningEventError, "confidence must be"):
            parse_misconception_finding(
                _json.dumps({"misconception": "x", "evidence": "y", "confidence": 2})
            )
