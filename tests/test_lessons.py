import json
import unittest

from sensei.lessons import (
    MAX_EXPLANATION_CHARACTERS,
    Lesson,
    LessonFactory,
    LessonGenerationError,
    parse_check_in_grade,
    parse_lesson,
    parse_question_answer,
)
from sensei.practice import PracticeGenerationError
from sensei.providers import CompletionResult


SKILL = {
    "id": "focus-related-rates-test",
    "course": "Calculus I",
    "name": "Related rates",
    "description": "Cones, ladders, and shadows with one unknown rate.",
}


def lesson_document(**overrides):
    document = {
        "title": "How to solve related-rates problems",
        "overview": r"Every related-rates problem asks for \(\frac{dy}{dt}\) given another rate.",
        "steps": [
            {
                "title": "Name the changing quantities",
                "explanation": r"Assign a variable to every quantity that changes with \(t\).",
                "worked_example": r"For a ladder, let \(x\) be the base distance and \(y\) the height.",
                "check_in": "Which quantities change as a ladder slides down a wall?",
                "check_in_answer": "The base distance and the height; partial credit for naming one.",
                "key_takeaway": "Variables belong to quantities that change, not to constants.",
            },
            {
                "title": "Differentiate the relationship",
                "explanation": r"Apply \(\frac{d}{dt}\) to both sides using the chain rule.",
                "worked_example": "",
                "check_in": r"Differentiate \(x^{2} + y^{2} = 100\) with respect to \(t\).",
                "check_in_answer": r"\(2x x' + 2y y' = 0\); partial credit for a missing factor of 2.",
                "key_takeaway": "Every variable picks up its own rate when you differentiate.",
            },
        ],
        "closing_summary": "Name, relate, differentiate, substitute, answer with units.",
    }
    document.update(overrides)
    return document


def approved() -> str:
    return json.dumps({"approved": True, "reason": "Every example recomputed."})


class StubProvider:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.requests: list[list[dict[str, str]]] = []

    def complete(self, messages, on_token=None):
        self.requests.append(list(messages))
        return CompletionResult(self.responses.pop(0), "stop")


class LessonParsingTests(unittest.TestCase):
    def test_parse_accepts_a_valid_lesson_and_hides_check_in_answers(self) -> None:
        lesson = parse_lesson(
            json.dumps(lesson_document()), skill_id=SKILL["id"], lesson_id="lesson-1"
        )
        self.assertEqual(2, lesson.step_count)
        self.assertEqual("", lesson.steps[1].worked_example)
        public = lesson.public_dict()
        self.assertNotIn("check_in_answer", json.dumps(public))
        self.assertEqual([0, 1], [step["index"] for step in public["steps"]])
        self.assertEqual(2, public["step_count"])
        rebuilt = Lesson.from_private_dict(
            lesson.private_dict(), lesson_id="lesson-1", skill_id=SKILL["id"]
        )
        self.assertEqual(lesson, rebuilt)

    def test_parse_rejects_malformed_lessons(self) -> None:
        good_step = lesson_document()["steps"][0]
        cases = {
            "missing field": {k: v for k, v in lesson_document().items() if k != "overview"},
            "extra field": lesson_document(extra="no"),
            "one step": lesson_document(steps=[good_step]),
            "nine steps": lesson_document(steps=[good_step] * 9),
            "empty check-in": lesson_document(steps=[{**good_step, "check_in": " "}, good_step]),
            "long explanation": lesson_document(
                steps=[{**good_step, "explanation": "x" * (MAX_EXPLANATION_CHARACTERS + 1)}, good_step]
            ),
            "unbalanced delimiter": lesson_document(overview=r"Find \(x"),
            "mismatched environment": lesson_document(
                closing_summary=r"\[\begin{array}{c} 1 \end{cases}\]"
            ),
            "extra step field": lesson_document(steps=[{**good_step, "hint": "no"}, good_step]),
        }
        for label, document in cases.items():
            with self.subTest(label):
                with self.assertRaises(PracticeGenerationError):
                    parse_lesson(json.dumps(document), skill_id="s", lesson_id="l")
        with self.assertRaises(PracticeGenerationError):
            parse_lesson("not json", skill_id="s", lesson_id="l")

    def test_grade_and_answer_parsers_validate_their_shapes(self) -> None:
        grade = parse_check_in_grade(
            json.dumps({"verdict": "Partial", "feedback": r"You found \(x\) but not \(y\)."})
        )
        self.assertEqual("partial", grade.verdict)
        self.assertTrue(grade.passed)
        self.assertFalse(parse_check_in_grade('{"verdict":"incorrect","feedback":"No."}').passed)
        with self.assertRaises(PracticeGenerationError):
            parse_check_in_grade('{"verdict":"maybe","feedback":"?"}')
        with self.assertRaises(PracticeGenerationError):
            parse_check_in_grade('{"verdict":"correct"}')
        self.assertEqual(
            r"Use \(2x\).",
            parse_question_answer('{"answer":"<think>hidden</think>Use \\\\(2x\\\\)."}'),
        )
        with self.assertRaises(PracticeGenerationError):
            parse_question_answer('{"answer":"<think>only</think>"}')
        with self.assertRaises(PracticeGenerationError):
            parse_question_answer('{"answer":"x","extra":1}')


class LessonFactoryTests(unittest.TestCase):
    def test_factory_writes_and_independently_reviews_a_lesson(self) -> None:
        provider = StubProvider([json.dumps(lesson_document()), approved()])
        lesson = LessonFactory(provider).generate(
            SKILL,
            materials=[
                {
                    "id": "m1",
                    "kind": "example_problem",
                    "body": "A 10 ft ladder slides down a wall.",
                    "solution": "dy/dt = -3/4 ft/s",
                    "source_label": "HW 4 #2",
                }
            ],
            subject_profile="No calculators; answers carry units.",
            learner_signal={
                "attempts_count": 3,
                "mastery_score": 40,
                "mastery_label": "developing",
                "recent_outcomes": ["incorrect", "correct", "incorrect"],
                "success_streak": 0,
                "misconceptions": ["Forgets to differentiate constants to zero"],
                "difficulty_tier": "standard",
            },
        )
        self.assertTrue(lesson.id.startswith("lesson-"))
        self.assertEqual(SKILL["id"], lesson.skill_id)
        self.assertEqual(2, len(provider.requests))
        system, user = provider.requests[0][0]["content"], provider.requests[0][-1]["content"]
        self.assertIn("lesson architect", system)
        self.assertIn("KaTeX-compatible LaTeX", system)
        self.assertIn(r"\ce{2H2 + O2 -> 2H2O}", system)
        self.assertIn("Subject: Calculus I", user)
        self.assertIn("Topic or skill: Related rates", user)
        self.assertIn("Course profile: No calculators", user)
        self.assertIn("A 10 ft ladder slides down a wall.", user)
        self.assertIn("Known weak spots to exercise:", user)
        self.assertIn("Forgets to differentiate constants", user)
        review = provider.requests[1][-1]["content"]
        self.assertIn("Requested Subject: Calculus I", review)
        self.assertIn("check_in_answer", review)
        self.assertIn("strict independent teacher", provider.requests[1][0]["content"])

    def test_factory_revises_after_a_rejected_review(self) -> None:
        provider = StubProvider(
            [
                json.dumps(lesson_document()),
                json.dumps({"approved": False, "reason": "Step 2 drops a factor of 2."}),
                json.dumps(lesson_document()),
                approved(),
            ]
        )
        LessonFactory(provider).generate(SKILL)
        self.assertEqual(4, len(provider.requests))
        retry = provider.requests[2][-1]["content"]
        self.assertIn("Reviewer feedback: Step 2 drops a factor of 2.", retry)
        self.assertIn("Prior draft:", retry)

    def test_factory_starts_over_when_feedback_rejects_the_design(self) -> None:
        provider = StubProvider(
            [
                json.dumps(lesson_document()),
                json.dumps(
                    {"approved": False, "reason": "The lesson does not match the target subject."}
                ),
                json.dumps(lesson_document()),
                approved(),
            ]
        )
        LessonFactory(provider).generate(SKILL)
        retry = provider.requests[2][-1]["content"]
        self.assertIn("Start over with a clean lesson", retry)
        self.assertNotIn("Prior draft:", retry)

    def test_factory_raises_when_attempts_are_exhausted(self) -> None:
        provider = StubProvider(["not json"])
        with self.assertRaises(LessonGenerationError) as failure:
            LessonFactory(provider, validation_attempts=1).generate(SKILL)
        self.assertIn("invalid JSON", str(failure.exception))

    def _lesson(self) -> Lesson:
        return parse_lesson(json.dumps(lesson_document()), skill_id=SKILL["id"], lesson_id="lesson-1")

    def test_grader_uses_the_coach_provider_and_retries_invalid_output(self) -> None:
        generator = StubProvider([])
        coach = StubProvider(
            [
                json.dumps({"verdict": "sort of", "feedback": "x"}),
                json.dumps({"verdict": "correct", "feedback": "Both quantities named."}),
            ]
        )
        factory = LessonFactory(generator, coach_provider=coach)
        grade = factory.grade_check_in(SKILL, self._lesson(), 0, "base and height")
        self.assertEqual("correct", grade.verdict)
        self.assertEqual(2, len(coach.requests))
        self.assertEqual(0, len(generator.requests))
        first = coach.requests[0][-1]["content"]
        self.assertIn("Expected answer and rubric: The base distance and the height", first)
        self.assertIn("Learner answer: base and height", first)
        self.assertIn("Step 1 of 2: Name the changing quantities", first)
        self.assertIn("Your previous output was invalid", coach.requests[1][-1]["content"])

    def test_grader_rejects_control_characters_then_accepts_a_clean_retry(self) -> None:
        # Some models emit  or  where a LaTeX backslash belongs.
        coach = StubProvider(
            [
                '{"verdict":"correct","feedback":"Difference law: \\u000c(5)-(-2)=7\\u000c."}',
                '{"verdict":"correct","feedback":"Difference law: \\\\(5-(-2)=7\\\\)."}',
            ]
        )
        factory = LessonFactory(StubProvider([]), coach_provider=coach)
        grade = factory.grade_check_in(SKILL, self._lesson(), 1, "7")
        self.assertEqual(r"Difference law: \(5-(-2)=7\).", grade.feedback)
        self.assertIn("control characters", coach.requests[1][-1]["content"])
        with self.assertRaises(PracticeGenerationError):
            parse_lesson(
                json.dumps(lesson_document(overview="Bad (x)")),
                skill_id="s",
                lesson_id="l",
            )

    def test_grader_rejects_empty_answers_and_repeated_bad_output(self) -> None:
        factory = LessonFactory(StubProvider(["{}", "{}"]))
        with self.assertRaises(ValueError):
            factory.grade_check_in(SKILL, self._lesson(), 0, "   ")
        with self.assertRaises(LessonGenerationError):
            factory.grade_check_in(SKILL, self._lesson(), 0, "guess")
        with self.assertRaises(ValueError):
            factory.grade_check_in(SKILL, self._lesson(), 5, "guess")

    def test_answer_question_strips_hidden_reasoning(self) -> None:
        coach = StubProvider(
            [json.dumps({"answer": "<think>secret</think>Because \\(x\\) changes with time."})]
        )
        factory = LessonFactory(StubProvider([]), coach_provider=coach)
        answer = factory.answer_question(SKILL, self._lesson(), 1, "Why does x get a rate?")
        self.assertEqual(r"Because \(x\) changes with time.", answer)
        request = coach.requests[0][-1]["content"]
        self.assertIn("Lesson overview:", request)
        self.assertIn("Step 2 of 2: Differentiate the relationship", request)
        self.assertIn("Learner question: Why does x get a rate?", request)
        self.assertNotIn("check_in_answer", request)
        self.assertNotIn("missing factor of 2", request)


if __name__ == "__main__":
    unittest.main()
