import unittest

from sensei.providers import CompletionResult
from sensei.tutor import TutorMode, TutorSession, student_facing_text


class FakeProvider:
    def __init__(self) -> None:
        self.requests: list[list[dict[str, str]]] = []

    def complete(self, messages, on_token=None) -> CompletionResult:
        self.requests.append(list(messages))
        text = "What is the inner function?"
        if on_token:
            on_token(text)
        return CompletionResult(text, "stop", 100, 8)


class TutorSessionTests(unittest.TestCase):
    def test_first_message_starts_problem_scoped_context(self) -> None:
        provider = FakeProvider()
        session = TutorSession(provider, "test-model")
        reply = session.respond("Differentiate (x^2+1)^3")
        request = provider.requests[0]
        self.assertEqual("Differentiate (x^2+1)^3", session.problem_statement)
        self.assertTrue(any("Current problem" in item["content"] for item in request))
        self.assertEqual(1, sum(item["role"] == "system" for item in request))
        self.assertEqual(TutorMode.COACH, reply.mode)
        self.assertEqual(1, session.turn_count)
        self.assertIn("exactly one conceptual first step", request[-1]["content"])

    def test_hint_mode_has_explicit_no_answer_boundary(self) -> None:
        provider = FakeProvider()
        session = TutorSession(provider, "test-model")
        session.respond("Differentiate sin(x^2)", TutorMode.HINT)
        system_text = "\n".join(
            message["content"]
            for message in provider.requests[0]
            if message["role"] == "system"
        )
        self.assertIn("exactly one", system_text)
        self.assertIn("Do not calculate", system_text)

    def test_history_is_bounded_but_problem_is_always_repeated(self) -> None:
        provider = FakeProvider()
        session = TutorSession(provider, "test-model", history_character_budget=140)
        session.respond("Find the limit as x approaches zero")
        session.respond("A" * 100)
        session.respond("my latest attempt")
        request = provider.requests[-1]
        all_text = "\n".join(message["content"] for message in request)
        self.assertIn("Find the limit as x approaches zero", all_text)
        self.assertIn("my latest attempt", all_text)
        self.assertEqual(2, len(session.context_messages()))
        self.assertLessEqual(session.context_characters, 140)

    def test_reset_clears_turns_and_history(self) -> None:
        provider = FakeProvider()
        session = TutorSession(provider, "test-model")
        session.respond("Differentiate x^2")
        session.reset()
        self.assertIsNone(session.problem_statement)
        self.assertEqual(0, session.turn_count)
        self.assertEqual((), session.context_messages())

    def test_learning_snapshot_tracks_help_without_unbounded_history(self) -> None:
        provider = FakeProvider()
        session = TutorSession(provider, "test-model")
        session.respond("Differentiate sin(x^2)", TutorMode.HINT)
        session.respond("Show the solution", TutorMode.SOLVE)
        snapshot = session.learning_snapshot()
        self.assertEqual(2, snapshot.tutor_turns)
        self.assertEqual(1, snapshot.hints_used)
        self.assertTrue(snapshot.solution_revealed)
        self.assertEqual(tuple(session.context_messages()), snapshot.messages)

    def test_persistent_context_is_added_without_an_extra_system_message(self) -> None:
        provider = FakeProvider()
        session = TutorSession(provider, "test-model")
        session.set_learner_context(
            "- Chain rule: beginning; watch for: missing inner derivative"
        )
        session.respond("Differentiate sin(x^2)")
        request = provider.requests[0]
        self.assertEqual(1, sum(item["role"] == "system" for item in request))
        self.assertIn("missing inner derivative", request[0]["content"])

    def test_tagged_reasoning_is_removed(self) -> None:
        text = student_facing_text("<think>private plan</think>Use the chain rule.")
        self.assertEqual("Use the chain rule.", text)


if __name__ == "__main__":
    unittest.main()
