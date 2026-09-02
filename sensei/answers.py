"""Answer contracts that turn one hidden key into a deterministic local check."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence, TypeVar

import sympy as sp

from sensei.learning import Outcome
from sensei.verification import (
    CalculusVerifier,
    MathInputError,
    VerificationKind,
    VerificationResult,
    VerificationStatus,
    expressions_equivalent,
    math_expression_latex,
    parse_math_expression,
)


ANSWER_KEY_VERSION = "sensei-answer-key-2"
SINGLE_ANSWER_TYPES = (
    "expression",
    "numeric",
    "solution_set",
    "interval",
    "point",
    "multiple_choice",
)
ANSWER_TYPES = (*SINGLE_ANSWER_TYPES, "multi_part")
CHOICE_LETTERS = ("A", "B", "C", "D")
DEFAULT_TOLERANCE = 0.01
MAX_TOLERANCE = 0.1
MAX_SET_MEMBERS = 6
MAX_POINTS = 4
MAX_KEY_CHARACTERS = 300
MAX_UNIT_CHARACTERS = 20
MAX_PARTS = 5
MIN_PARTS = 2
SPECIAL_EXPRESSION_ANSWERS = {"dne", "doesnotexist", "undefined"}
EMPTY_SET_WORDS = {
    "none",
    "nosolution",
    "nosolutions",
    "empty",
    "emptyset",
    "dne",
    "doesnotexist",
    "undefined",
}
EMPTY_SET_SYMBOLS = {"∅", "Ø", "{}", "{ }"}
ALL_REALS_WORDS = {"allreals", "allrealnumbers", "reals", "r", "everyrealnumber"}
ALL_REALS_SYMBOLS = {"ℝ"}

_T = TypeVar("_T")


class AnswerKeyError(ValueError):
    """Raised when a model-supplied answer key does not fit its contract."""


@dataclass(frozen=True)
class AnswerSpec:
    """One validated hidden answer plus the rules for checking it."""

    answer_type: str
    key: str
    options: tuple[str, ...] = ()
    tolerance: float | None = None
    unit: str | None = None


def _word(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.casefold())


def _is_empty_set(text: str) -> bool:
    stripped = text.strip()
    return stripped in EMPTY_SET_SYMBOLS or _word(stripped) in EMPTY_SET_WORDS


def _is_all_reals(text: str) -> bool:
    stripped = text.strip()
    return stripped in ALL_REALS_SYMBOLS or _word(stripped) in ALL_REALS_WORDS


def _result(
    status: VerificationStatus,
    submitted: str,
    expected: str,
    detail: str,
) -> VerificationResult:
    return VerificationResult(
        kind=VerificationKind.EQUIVALENT,
        status=status,
        submitted=submitted,
        expected=expected,
        detail=detail,
        verifier_version=ANSWER_KEY_VERSION,
    )


def _verdict(correct: bool | None) -> VerificationStatus:
    if correct is True:
        return VerificationStatus.VERIFIED_CORRECT
    if correct is False:
        return VerificationStatus.VERIFIED_INCORRECT
    return VerificationStatus.INCONCLUSIVE


def _key_text(value: object, field: str = "answer") -> str:
    if not isinstance(value, str) or not value.strip():
        raise AnswerKeyError(f"{field} must be non-empty text")
    text = value.strip()
    if len(text) > MAX_KEY_CHARACTERS:
        raise AnswerKeyError(f"{field} exceeds {MAX_KEY_CHARACTERS} characters")
    return text


# ---------------------------------------------------------------------------
# Numeric answers
# ---------------------------------------------------------------------------

_SCIENTIFIC_TIMES = re.compile(r"(?<=\d)\s*[xX×*]\s*10\s*\^")
_E_NOTATION = re.compile(r"(?<=\d)[eE]([+-]?\d+)\b")
_THOUSANDS = re.compile(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?")


def _numeric_text(text: str, unit: str | None) -> str:
    cleaned = text.strip()
    if unit:
        cleaned = re.sub(
            rf"\s*{re.escape(unit)}\s*$", "", cleaned, flags=re.IGNORECASE
        )
    cleaned = cleaned.rstrip("%").strip()
    if _THOUSANDS.fullmatch(cleaned):
        cleaned = cleaned.replace(",", "")
    cleaned = _SCIENTIFIC_TIMES.sub("*10^", cleaned)
    cleaned = _E_NOTATION.sub(r"*10^\1", cleaned)
    return cleaned


def numeric_value(text: str, unit: str | None = None) -> float:
    """Evaluate one number written in the restricted grammar."""

    expression = parse_math_expression(_numeric_text(text, unit), symbols=set())
    value = sp.N(expression, 30)
    if not getattr(value, "is_real", False) or not value.is_finite:
        raise MathInputError("Enter a single finite number.")
    return float(value)


def _check_numeric(spec: AnswerSpec, submitted: str) -> VerificationResult:
    tolerance = spec.tolerance if spec.tolerance is not None else DEFAULT_TOLERANCE
    expected = numeric_value(spec.key, spec.unit)
    value = numeric_value(submitted, spec.unit)
    allowed = tolerance * abs(expected) if expected != 0 else tolerance
    correct = abs(value - expected) <= allowed
    percent = f"{tolerance * 100:g}%"
    expected_text = spec.key + (f" {spec.unit}" if spec.unit else "")
    return _result(
        _verdict(correct),
        submitted.strip(),
        expected_text,
        (
            f"The submitted value is within {percent} of the validated answer."
            if correct
            else f"The submitted value is not within {percent} of the validated answer."
        ),
    )


# ---------------------------------------------------------------------------
# Expression answers
# ---------------------------------------------------------------------------


def _check_expression(spec: AnswerSpec, submitted: str) -> VerificationResult:
    if _word(spec.key) in SPECIAL_EXPRESSION_ANSWERS:
        correct = _word(submitted) in SPECIAL_EXPRESSION_ANSWERS
        return _result(
            _verdict(correct),
            submitted.strip(),
            "DNE",
            (
                "The submitted answer correctly identifies a nonexistent value."
                if correct
                else "The validated answer does not exist."
            ),
        )
    return CalculusVerifier().equivalent(spec.key, submitted)


# ---------------------------------------------------------------------------
# Collections: solution sets and points
# ---------------------------------------------------------------------------

_SET_SPLIT = re.compile(r"\s*(?:,|;|\bor\b|\band\b)\s*", re.IGNORECASE)
_ASSIGNMENT = re.compile(r"(?:^|(?<=[,;\s]))[A-Za-z]\s*=\s*")


def _set_members(text: str) -> list[str]:
    stripped = text.strip()
    if _is_empty_set(stripped):
        return []
    stripped = stripped.strip("{}").strip()
    stripped = _ASSIGNMENT.sub("", stripped)
    members = [member.strip() for member in _SET_SPLIT.split(stripped)]
    members = [member for member in members if member]
    if not members:
        raise MathInputError("Enter at least one solution, or none.")
    if len(members) > MAX_SET_MEMBERS:
        raise MathInputError(f"Enter at most {MAX_SET_MEMBERS} solutions.")
    return members


def _dedupe(
    items: Sequence[_T], equivalent: Callable[[_T, _T], bool | None]
) -> list[_T]:
    unique: list[_T] = []
    for item in items:
        if not any(equivalent(item, kept) is True for kept in unique):
            unique.append(item)
    return unique


def _match_collections(
    expected: Sequence[_T],
    submitted: Sequence[_T],
    equivalent: Callable[[_T, _T], bool | None],
) -> tuple[bool | None, int]:
    """Match submitted items against expected ones without regard to order."""

    remaining = list(expected)
    matched = 0
    undecided = False
    for item in submitted:
        found: int | None = None
        for index, candidate in enumerate(remaining):
            verdict = equivalent(item, candidate)
            if verdict is True:
                found = index
                break
            if verdict is None:
                undecided = True
        if found is None:
            continue
        remaining.pop(found)
        matched += 1
    if matched == len(submitted) and not remaining:
        return True, matched
    if undecided:
        return None, matched
    return False, matched


def _check_solution_set(spec: AnswerSpec, submitted: str) -> VerificationResult:
    expected = [parse_math_expression(member) for member in _set_members(spec.key)]
    proposed = _dedupe(
        [parse_math_expression(member) for member in _set_members(submitted)],
        expressions_equivalent,
    )
    correct, matched = _match_collections(expected, proposed, expressions_equivalent)
    expected_text = spec.key if expected else "none"
    if not expected and not proposed:
        correct = True
    detail = (
        "Every submitted solution matches the validated solution set."
        if correct
        else (
            f"{matched} of {len(expected)} validated solutions were matched; "
            "the submitted set is not the same."
        )
        if correct is False
        else "Symbolic comparison could not settle one of the solutions."
    )
    return _result(_verdict(correct), submitted.strip(), expected_text, detail)


Point = tuple[sp.Expr, sp.Expr]


def _split_top_level(text: str) -> list[str]:
    """Split on commas that are not nested inside brackets."""

    pieces: list[str] = []
    current: list[str] = []
    depth = 0
    for character in text:
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        if character == "," and depth == 0:
            pieces.append("".join(current))
            current = []
        else:
            current.append(character)
    pieces.append("".join(current))
    return [piece.strip() for piece in pieces if piece.strip()]


def _point_groups(text: str) -> list[str]:
    """Return the inside of every top-level parenthesized group, in order."""

    groups: list[str] = []
    depth = 0
    start: int | None = None
    for index, character in enumerate(text):
        if character == "(":
            if depth == 0:
                start = index
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                raise MathInputError("Unbalanced parentheses in the point list.")
            if depth == 0 and start is not None:
                groups.append(text[start + 1 : index])
                start = None
    if depth != 0:
        raise MathInputError("Unbalanced parentheses in the point list.")
    return groups


def _points(text: str) -> list[Point]:
    stripped = text.strip()
    if _is_empty_set(stripped):
        return []
    pairs: list[tuple[str, str]] = []
    groups = _point_groups(stripped)
    coordinates = [_split_top_level(group) for group in groups]
    if coordinates and all(len(pair) == 2 for pair in coordinates):
        pairs = [(pair[0], pair[1]) for pair in coordinates]
    else:
        bare = _split_top_level(stripped)
        if len(bare) != 2:
            raise MathInputError("Enter each point as (x, y).")
        pairs = [(bare[0], bare[1])]
    if len(pairs) > MAX_POINTS:
        raise MathInputError(f"Enter at most {MAX_POINTS} points.")
    return [(parse_math_expression(x), parse_math_expression(y)) for x, y in pairs]


def _points_equivalent(left: Point, right: Point) -> bool | None:
    first = expressions_equivalent(left[0], right[0])
    second = expressions_equivalent(left[1], right[1])
    if first is True and second is True:
        return True
    if first is False or second is False:
        return False
    return None


def _check_point(spec: AnswerSpec, submitted: str) -> VerificationResult:
    expected = _points(spec.key)
    proposed = _dedupe(_points(submitted), _points_equivalent)
    correct, matched = _match_collections(expected, proposed, _points_equivalent)
    if not expected and not proposed:
        correct = True
    detail = (
        "Every submitted point matches the validated point set."
        if correct
        else (
            f"{matched} of {len(expected)} validated points were matched; "
            "the submitted points are not the same."
        )
        if correct is False
        else "Symbolic comparison could not settle one of the coordinates."
    )
    return _result(_verdict(correct), submitted.strip(), spec.key, detail)


# ---------------------------------------------------------------------------
# Interval answers
# ---------------------------------------------------------------------------

_INTERVAL = re.compile(r"([\[(])\s*([^,\[\]()]+?)\s*,\s*([^,\[\]()]+?)\s*([\])])")
_FINITE_SET = re.compile(r"\{\s*([^{}]*?)\s*\}")
_UNION_SPLIT = re.compile(r"\s*(?:∪|\b[Uu]\b|\bunion\b)\s*")


def _endpoint(text: str) -> sp.Expr:
    expression = parse_math_expression(text, symbols=set())
    if expression.is_extended_real is not True:
        raise MathInputError(f"Interval endpoint {text.strip()!r} is not a real number.")
    return expression


def parse_interval_set(text: str) -> sp.Set:
    """Parse interval notation such as (-oo, 1) U [3, oo) into a SymPy set."""

    cleaned = text.strip().replace("∞", "oo").replace("−", "-")
    if _is_empty_set(cleaned):
        return sp.S.EmptySet
    if _is_all_reals(cleaned):
        return sp.S.Reals
    pieces = [piece.strip() for piece in _UNION_SPLIT.split(cleaned) if piece.strip()]
    if not pieces:
        raise MathInputError("Enter an interval such as (-oo, 1) U [3, oo).")
    sets: list[sp.Set] = []
    for piece in pieces:
        interval = _INTERVAL.fullmatch(piece)
        finite = _FINITE_SET.fullmatch(piece)
        if interval:
            left_bracket, left_text, right_text, right_bracket = interval.groups()
            left = _endpoint(left_text)
            right = _endpoint(right_text)
            if (right - left).is_negative:
                raise MathInputError(
                    "Interval endpoints must be written from smallest to largest."
                )
            sets.append(
                sp.Interval(left, right, left_bracket == "(", right_bracket == ")")
            )
        elif finite:
            members = [
                member for member in re.split(r"\s*,\s*", finite.group(1)) if member
            ]
            if not members:
                sets.append(sp.S.EmptySet)
            else:
                sets.append(sp.FiniteSet(*[_endpoint(member) for member in members]))
        else:
            raise MathInputError(f"Unsupported interval notation near {piece[:20]!r}.")
    return sp.Union(*sets)


def _sets_equal(expected: sp.Set, submitted: sp.Set) -> bool | None:
    if expected == submitted:
        return True
    try:
        difference = expected.symmetric_difference(submitted)
    except (TypeError, ValueError, NotImplementedError):
        return None
    if difference == sp.S.EmptySet:
        return True
    empty = difference.is_empty
    if empty is True:
        return True
    if empty is False:
        return False
    return None


def _check_interval(spec: AnswerSpec, submitted: str) -> VerificationResult:
    expected = parse_interval_set(spec.key)
    proposed = parse_interval_set(submitted)
    correct = _sets_equal(expected, proposed)
    detail = (
        "The submitted set is the same as the validated interval."
        if correct
        else "The submitted set differs from the validated interval."
        if correct is False
        else "The submitted set could not be compared with the validated interval."
    )
    return _result(_verdict(correct), submitted.strip(), spec.key, detail)


# ---------------------------------------------------------------------------
# Multiple choice
# ---------------------------------------------------------------------------


def _check_choice(spec: AnswerSpec, submitted: str) -> VerificationResult:
    normalized = submitted.upper().strip().rstrip(".)")
    if normalized in CHOICE_LETTERS:
        selected = normalized
    else:
        matches = [
            index
            for index, option in enumerate(spec.options)
            if option.casefold().strip() == submitted.casefold().strip()
        ]
        selected = chr(ord("A") + matches[0]) if len(matches) == 1 else ""
    correct = selected == spec.key
    index = ord(spec.key) - ord("A")
    return _result(
        _verdict(correct),
        submitted.strip(),
        f"{spec.key}. {spec.options[index]}",
        (
            "The selected option matches the validated answer key."
            if correct
            else "The selected option does not match the validated answer key."
        ),
    )


# ---------------------------------------------------------------------------
# Public contract
# ---------------------------------------------------------------------------

_CHECKERS: dict[str, Callable[[AnswerSpec, str], VerificationResult]] = {
    "expression": _check_expression,
    "numeric": _check_numeric,
    "solution_set": _check_solution_set,
    "interval": _check_interval,
    "point": _check_point,
    "multiple_choice": _check_choice,
}


def check_answer(spec: AnswerSpec, submitted: str) -> VerificationResult:
    """Check one learner answer against its validated key."""

    submitted = submitted.strip()
    if not submitted:
        raise ValueError("Enter an answer before checking the quest.")
    return _CHECKERS[spec.answer_type](spec, submitted)


def _members_from_key(raw_answer: object, field: str) -> list[str]:
    if isinstance(raw_answer, list):
        return [_key_text(member, field) for member in raw_answer]
    if isinstance(raw_answer, str):
        if _is_empty_set(raw_answer):
            return []
        try:
            return _set_members(raw_answer)
        except MathInputError as error:
            raise AnswerKeyError(f"{field} could not be parsed: {error}") from error
    raise AnswerKeyError(f"{field} must be a list of expressions")


def normalize_answer_key(
    answer_type: str,
    raw_answer: object,
    *,
    options: Sequence[str] = (),
    tolerance: object = None,
    unit: object = None,
    field: str = "answer",
) -> AnswerSpec:
    """Validate a model-authored key and return the canonical checkable spec."""

    if answer_type not in SINGLE_ANSWER_TYPES:
        raise AnswerKeyError(
            "answer_type must be one of " + ", ".join(SINGLE_ANSWER_TYPES)
        )
    option_texts = tuple(options)
    if answer_type == "multiple_choice":
        if (
            not isinstance(raw_answer, str)
            or raw_answer.strip().upper() not in CHOICE_LETTERS
            or len(option_texts) != 4
        ):
            raise AnswerKeyError(
                "multiple-choice quests need four options and an A-D answer"
            )
        if tolerance is not None or (isinstance(unit, str) and unit.strip()):
            raise AnswerKeyError("multiple-choice answers take no tolerance or unit")
        return AnswerSpec(answer_type, raw_answer.strip().upper(), option_texts)
    if option_texts:
        raise AnswerKeyError(f"{answer_type} quests must use an empty option list")

    unit_text: str | None = None
    if unit is not None and unit != "":
        if not isinstance(unit, str) or len(unit.strip()) > MAX_UNIT_CHARACTERS:
            raise AnswerKeyError(
                f"unit must be text of at most {MAX_UNIT_CHARACTERS} characters"
            )
        unit_text = unit.strip() or None

    if answer_type == "numeric":
        if tolerance is None:
            tolerance_value = DEFAULT_TOLERANCE
        elif (
            isinstance(tolerance, bool)
            or not isinstance(tolerance, (int, float))
            or not 0 < float(tolerance) <= MAX_TOLERANCE
        ):
            raise AnswerKeyError(
                f"tolerance must be a number above 0 and at most {MAX_TOLERANCE}"
            )
        else:
            tolerance_value = float(tolerance)
        key = _key_text(raw_answer, field)
        try:
            numeric_value(key)
        except MathInputError as error:
            raise AnswerKeyError(
                f"the numeric {field} could not be parsed: {error}"
            ) from error
        return AnswerSpec(answer_type, key, (), tolerance_value, unit_text)

    if tolerance is not None:
        raise AnswerKeyError("tolerance applies only to numeric answers")

    if answer_type == "expression":
        key = _key_text(raw_answer, field)
        if _word(key) in SPECIAL_EXPRESSION_ANSWERS:
            return AnswerSpec(answer_type, "DNE", (), None, unit_text)
        try:
            parse_math_expression(key)
        except MathInputError as error:
            raise AnswerKeyError(
                f"the expression {field} could not be parsed: {error}"
            ) from error
        return AnswerSpec(answer_type, key, (), None, unit_text)

    if answer_type == "solution_set":
        members = _members_from_key(raw_answer, field)
        if len(members) > MAX_SET_MEMBERS:
            raise AnswerKeyError(
                f"a solution_set {field} may hold at most {MAX_SET_MEMBERS} members"
            )
        try:
            for member in members:
                parse_math_expression(member)
        except MathInputError as error:
            raise AnswerKeyError(
                f"the solution_set {field} could not be parsed: {error}"
            ) from error
        return AnswerSpec(
            answer_type, ", ".join(members) if members else "none", (), None, unit_text
        )

    if answer_type == "interval":
        key = _key_text(raw_answer, field)
        try:
            parse_interval_set(key)
        except MathInputError as error:
            raise AnswerKeyError(
                f"the interval {field} could not be parsed: {error}"
            ) from error
        return AnswerSpec(answer_type, key, (), None, unit_text)

    if isinstance(raw_answer, list):
        pairs: list[str] = []
        for item in raw_answer:
            if not isinstance(item, list) or len(item) != 2:
                raise AnswerKeyError(f"each point in {field} must be an [x, y] pair")
            pairs.append(
                f"({_key_text(item[0], field)}, {_key_text(item[1], field)})"
            )
        key = ", ".join(pairs) if pairs else "none"
    else:
        key = _key_text(raw_answer, field)
    try:
        if len(_points(key)) > MAX_POINTS:
            raise MathInputError(f"Enter at most {MAX_POINTS} points.")
    except MathInputError as error:
        raise AnswerKeyError(f"the point {field} could not be parsed: {error}") from error
    return AnswerSpec(answer_type, key, (), None, unit_text)


def answer_format_hint(answer_type: str, unit: str | None = None) -> str:
    """Return the one-line entry instruction shown beside the answer box."""

    if answer_type == "numeric":
        where = f" in {unit}" if unit else ""
        return (
            f"Enter one number{where}. Scientific notation such as 6.02*10^23 is "
            "fine; a value within the accepted tolerance counts as correct."
        )
    if answer_type == "solution_set":
        return (
            "Enter every solution separated by commas, for example 2, -3. "
            "Enter none if there is no solution."
        )
    if answer_type == "interval":
        return (
            "Use interval notation, for example (-oo, 1) U [3, oo). "
            "Enter none for the empty set."
        )
    if answer_type == "point":
        return "Enter each point as (x, y); separate several points with commas."
    if answer_type == "multiple_choice":
        return "Choose A, B, C, or D."
    return (
        "Enter one expression. Use ^ for powers, sqrt() for roots, pi for π, "
        "and DNE when the value does not exist."
    )


def answer_key_latex(spec: AnswerSpec) -> str | None:
    """Render the validated key as bare LaTeX, or None for lettered choices."""

    kind = spec.answer_type
    try:
        if kind == "multiple_choice":
            return None
        if kind in {"expression", "numeric"}:
            latex = math_expression_latex(spec.key)
            if kind == "numeric" and spec.unit:
                latex += rf"\ \text{{{spec.unit}}}"
            return latex
        if kind == "solution_set":
            members = _set_members(spec.key) if not _is_empty_set(spec.key) else []
            if not members:
                return r"\varnothing"
            return ", ".join(sp.latex(parse_math_expression(m)) for m in members)
        if kind == "interval":
            return sp.latex(parse_interval_set(spec.key))
        if kind == "point":
            points = _points(spec.key)
            if not points:
                return r"\varnothing"
            return ", ".join(
                rf"\left({sp.latex(x)}, {sp.latex(y)}\right)" for x, y in points
            )
    except MathInputError:
        return None
    return None


def submitted_latex(spec: AnswerSpec, submitted: str) -> str | None:
    """Render a learner's answer in the same notation as its key when possible."""

    try:
        return answer_key_latex(
            AnswerSpec(spec.answer_type, submitted.strip(), spec.options, spec.tolerance, spec.unit)
        )
    except (MathInputError, AnswerKeyError, ValueError):
        return None


def answer_key_display(spec: AnswerSpec) -> str:
    """Return learner-visible text for the key, with inline notation delimiters."""

    if spec.answer_type == "multiple_choice":
        index = ord(spec.key) - ord("A")
        return f"{spec.key}. {spec.options[index]}"
    latex = answer_key_latex(spec)
    if latex is None:
        return spec.key
    return rf"\({latex}\)"


# ---------------------------------------------------------------------------
# Multi-part problems
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MultiPartResult:
    """Per-part verification plus the aggregate outcome for one attempt."""

    parts: tuple[tuple[str, VerificationResult], ...]

    @property
    def total(self) -> int:
        return len(self.parts)

    @property
    def correct_count(self) -> int:
        return sum(
            result.status is VerificationStatus.VERIFIED_CORRECT
            for _, result in self.parts
        )

    @property
    def inconclusive(self) -> bool:
        return any(
            result.status is VerificationStatus.INCONCLUSIVE for _, result in self.parts
        )

    @property
    def outcome(self) -> Outcome:
        if self.correct_count == self.total:
            return Outcome.CORRECT
        if self.correct_count == 0:
            return Outcome.INCORRECT
        return Outcome.PARTIAL

    def summary(self) -> VerificationResult:
        if self.inconclusive:
            status = VerificationStatus.INCONCLUSIVE
        elif self.outcome is Outcome.CORRECT:
            status = VerificationStatus.VERIFIED_CORRECT
        else:
            status = VerificationStatus.VERIFIED_INCORRECT
        return _result(
            status,
            "; ".join(f"({label}) {result.submitted}" for label, result in self.parts),
            "; ".join(
                f"({label}) {result.expected}" for label, result in self.parts
            ),
            f"{self.correct_count} of {self.total} parts match the validated answers.",
        )


def check_parts(
    parts: Sequence[tuple[str, AnswerSpec]],
    submitted: Mapping[str, object],
) -> MultiPartResult:
    """Check every part of a multi-part problem from one answer mapping."""

    labels = [label for label, _ in parts]
    unknown = sorted(set(submitted) - set(labels))
    if unknown:
        raise ValueError(f"Unknown part label: {unknown[0]!r}.")
    results: list[tuple[str, VerificationResult]] = []
    for label, spec in parts:
        value = submitted.get(label)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Enter an answer for part ({label}) before checking.")
        results.append((label, check_answer(spec, value)))
    return MultiPartResult(tuple(results))
