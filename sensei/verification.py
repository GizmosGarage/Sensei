"""Restricted symbolic parsing and deterministic Calculus I verification."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from enum import Enum
from typing import Collection

import sympy as sp


VERIFIER_VERSION = f"sensei-symbolic-1/sympy-{sp.__version__}"
MAX_EXPRESSION_CHARACTERS = 500
MAX_TOKENS = 120
MAX_AST_NODES = 160
MAX_AST_DEPTH = 24
MAX_OPERATIONS = 200
MAX_NUMERIC_MAGNITUDE = 10**12
MAX_CONSTANT_EXPONENT = 100


class VerificationKind(str, Enum):
    DERIVATIVE = "derivative"
    LIMIT = "limit"
    ANTIDERIVATIVE = "antiderivative"
    EQUIVALENT = "equivalent"


class VerificationStatus(str, Enum):
    VERIFIED_CORRECT = "verified_correct"
    VERIFIED_INCORRECT = "verified_incorrect"
    INCONCLUSIVE = "inconclusive"


class MathInputError(ValueError):
    """Raised when input is outside Sensei's restricted math grammar."""


@dataclass(frozen=True)
class VerificationResult:
    kind: VerificationKind
    status: VerificationStatus
    submitted: str
    expected: str | None
    detail: str
    verifier_version: str = VERIFIER_VERSION

    @property
    def is_conclusive(self) -> bool:
        return self.status is not VerificationStatus.INCONCLUSIVE

    @property
    def is_correct(self) -> bool:
        return self.status is VerificationStatus.VERIFIED_CORRECT

    def learning_summary(self) -> str:
        expected = f" Expected: {self.expected}." if self.expected else ""
        return f"{self.kind.value}: {self.status.value}. {self.detail}{expected}"


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str


TOKEN_PATTERN = re.compile(
    r"\s*(?:(?P<number>(?:\d+(?:\.\d*)?|\.\d+))|"
    r"(?P<name>[A-Za-z][A-Za-z0-9]*)|(?P<op>\*\*|[+\-*/(),]))"
)
SYMBOL_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9]*\Z")
DEFAULT_SYMBOLS = {"x", "y", "t", "u", "h", "a", "b", "c", "n", "C"}


FUNCTIONS = {
    "sin": sp.sin,
    "cos": sp.cos,
    "tan": sp.tan,
    "sec": sp.sec,
    "csc": sp.csc,
    "cot": sp.cot,
    "asin": sp.asin,
    "acos": sp.acos,
    "atan": sp.atan,
    "sinh": sp.sinh,
    "cosh": sp.cosh,
    "tanh": sp.tanh,
    "exp": sp.exp,
    "log": sp.log,
    "ln": sp.log,
    "sqrt": sp.sqrt,
    "abs": sp.Abs,
}

CONSTANTS = {
    "pi": sp.pi,
    "e": sp.E,
    "E": sp.E,
    "oo": sp.oo,
    "inf": sp.oo,
}


def _normalize_input(expression: str) -> str:
    normalized = expression.strip()
    replacements = {
        "−": "-",
        "–": "-",
        "×": "*",
        "·": "*",
        "÷": "/",
        "π": "pi",
        "∞": "oo",
        "^": "**",
        "\\cdot": "*",
        "\\times": "*",
        "\\pi": "pi",
        "\\sqrt": "sqrt",
        "\\sin": "sin",
        "\\cos": "cos",
        "\\tan": "tan",
        "\\ln": "ln",
        "\\log": "log",
        "\\left": "",
        "\\right": "",
        "\\(": "",
        "\\)": "",
        "$": "",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized.strip()


def _tokenize(expression: str) -> list[_Token]:
    if not expression:
        raise MathInputError("Enter a mathematical expression.")
    if len(expression) > MAX_EXPRESSION_CHARACTERS:
        raise MathInputError(
            f"Expression exceeds {MAX_EXPRESSION_CHARACTERS} characters."
        )
    tokens: list[_Token] = []
    position = 0
    while position < len(expression):
        match = TOKEN_PATTERN.match(expression, position)
        if not match:
            if expression[position:].strip() == "":
                break
            snippet = expression[position : position + 20]
            raise MathInputError(f"Unsupported syntax near {snippet!r}.")
        if match.group("number"):
            kind = "number"
        elif match.group("name"):
            kind = "name"
        else:
            kind = "op"
        value = match.group(kind)
        tokens.append(_Token(kind, value))
        position = match.end()
        if len(tokens) > MAX_TOKENS:
            raise MathInputError(f"Expression exceeds {MAX_TOKENS} tokens.")
    return tokens


def _ends_factor(token: _Token) -> bool:
    return token.kind in {"number", "name"} or token.value == ")"


def _starts_factor(token: _Token) -> bool:
    return token.kind in {"number", "name"} or token.value == "("


def _with_implicit_multiplication(tokens: list[_Token]) -> str:
    output: list[str] = []
    previous: _Token | None = None
    for token in tokens:
        if previous and _ends_factor(previous) and _starts_factor(token):
            if previous.kind == "number" and token.kind == "number":
                raise MathInputError("Adjacent numbers require an operator.")
            function_call = (
                previous.kind == "name"
                and previous.value in FUNCTIONS
                and token.value == "("
            )
            if not function_call:
                output.append("*")
        output.append(token.value)
        previous = token
    return "".join(output)


def _validate_symbol_names(names: Collection[str]) -> set[str]:
    validated = set(names)
    for name in validated:
        if not SYMBOL_PATTERN.fullmatch(name) or len(name) > 16:
            raise MathInputError(f"Invalid symbol name: {name!r}.")
        if name in FUNCTIONS or name in CONSTANTS:
            raise MathInputError(f"Symbol name is reserved: {name!r}.")
    return validated


class _AstConverter:
    def __init__(self, symbols: Collection[str]) -> None:
        names = _validate_symbol_names(symbols)
        self.symbols = {name: sp.Symbol(name) for name in names}

    def convert(self, node: ast.AST, depth: int = 0) -> sp.Expr:
        if depth > MAX_AST_DEPTH:
            raise MathInputError(f"Expression nesting exceeds {MAX_AST_DEPTH} levels.")
        if isinstance(node, ast.Expression):
            return self.convert(node.body, depth + 1)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise MathInputError("Only numeric constants are allowed.")
            if abs(node.value) > MAX_NUMERIC_MAGNITUDE:
                raise MathInputError("Numeric constant is too large.")
            if isinstance(node.value, int):
                return sp.Integer(node.value)
            return sp.Rational(str(node.value))
        if isinstance(node, ast.Name):
            if node.id in self.symbols:
                return self.symbols[node.id]
            if node.id in CONSTANTS:
                return CONSTANTS[node.id]
            raise MathInputError(f"Unknown symbol: {node.id!r}.")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            operand = self.convert(node.operand, depth + 1)
            return operand if isinstance(node.op, ast.UAdd) else -operand
        if isinstance(node, ast.BinOp):
            left = self.convert(node.left, depth + 1)
            if isinstance(node.op, ast.Pow):
                simple_exponent = isinstance(node.right, (ast.Constant, ast.Name)) or (
                    isinstance(node.right, ast.UnaryOp)
                    and isinstance(node.right.op, (ast.UAdd, ast.USub))
                    and isinstance(node.right.operand, ast.Constant)
                )
                if not simple_exponent:
                    raise MathInputError(
                        "Compound exponents are outside the supported safe grammar."
                    )
                right = self.convert(node.right, depth + 1)
                if right.is_number and right.is_real:
                    try:
                        exponent = abs(float(right))
                    except (TypeError, ValueError, OverflowError) as error:
                        raise MathInputError("Invalid numeric exponent.") from error
                    if exponent > MAX_CONSTANT_EXPONENT:
                        raise MathInputError(
                            f"Constant exponents cannot exceed {MAX_CONSTANT_EXPONENT}."
                        )
                return left**right
            right = self.convert(node.right, depth + 1)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
            raise MathInputError("Unsupported binary operator.")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                raise MathInputError("Only whitelisted mathematical functions are allowed.")
            if node.keywords or len(node.args) != 1:
                raise MathInputError("Mathematical functions require exactly one argument.")
            return FUNCTIONS[node.func.id](self.convert(node.args[0], depth + 1))
        raise MathInputError(f"Unsupported expression element: {type(node).__name__}.")


def parse_math_expression(
    expression: str,
    *,
    symbols: Collection[str] = DEFAULT_SYMBOLS,
) -> sp.Expr:
    """Parse a small, non-evaluating math grammar into a SymPy expression."""

    normalized = _normalize_input(expression)
    transformed = _with_implicit_multiplication(_tokenize(normalized))
    try:
        tree = ast.parse(transformed, mode="eval")
    except SyntaxError as error:
        raise MathInputError(f"Invalid expression syntax: {error.msg}.") from error
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        raise MathInputError(f"Expression exceeds {MAX_AST_NODES} syntax nodes.")
    converted = _AstConverter(symbols).convert(tree)
    if int(sp.count_ops(converted)) > MAX_OPERATIONS:
        raise MathInputError(f"Expression exceeds {MAX_OPERATIONS} operations.")
    return converted


def math_expression_latex(expression: str) -> str:
    """Render a validated answer expression as learner-facing LaTeX."""

    normalized_word = re.sub(r"[^a-z]", "", expression.casefold())
    if normalized_word in {"dne", "doesnotexist", "undefined"}:
        return r"\mathrm{DNE}"
    return sp.latex(parse_math_expression(expression))


def _display(expression: sp.Expr, limit: int = 300) -> str:
    text = sp.sstr(expression)
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _equivalent(left: sp.Expr, right: sp.Expr) -> tuple[bool | None, sp.Expr]:
    if left == right:
        return True, sp.S.Zero
    try:
        residual = sp.trigsimp(sp.cancel(sp.together(left - right)))
        residual = sp.simplify(residual)
    except (ArithmeticError, NotImplementedError, ValueError, TypeError):
        residual = left - right
    if residual == 0:
        return True, residual
    try:
        equality = residual.equals(0)
    except (ArithmeticError, NotImplementedError, ValueError, TypeError):
        equality = None
    return equality, residual


def _result_from_equivalence(
    *,
    kind: VerificationKind,
    submitted: sp.Expr,
    expected: sp.Expr,
    success_detail: str,
    failure_detail: str,
    submitted_display: str | None = None,
    expected_display: str | None = None,
) -> VerificationResult:
    equivalent, residual = _equivalent(submitted, expected)
    submitted_text = submitted_display or _display(submitted)
    expected_text = expected_display or _display(expected)
    if equivalent is True:
        return VerificationResult(
            kind,
            VerificationStatus.VERIFIED_CORRECT,
            submitted_text,
            expected_text,
            success_detail,
        )
    if equivalent is False:
        return VerificationResult(
            kind,
            VerificationStatus.VERIFIED_INCORRECT,
            submitted_text,
            expected_text,
            f"{failure_detail} Residual difference: {_display(residual)}.",
        )
    return VerificationResult(
        kind,
        VerificationStatus.INCONCLUSIVE,
        submitted_text,
        expected_text,
        "Symbolic comparison could not prove or disprove equivalence.",
    )


class CalculusVerifier:
    """Deterministically checks common Calculus I answer types."""

    @staticmethod
    def _variable(name: str) -> sp.Symbol:
        validated = _validate_symbol_names({name.strip()})
        return sp.Symbol(next(iter(validated)))

    def derivative(
        self, function: str, answer: str, *, variable: str = "x"
    ) -> VerificationResult:
        symbol = self._variable(variable)
        allowed = DEFAULT_SYMBOLS | {symbol.name}
        source = parse_math_expression(function, symbols=allowed)
        submitted = parse_math_expression(answer, symbols=allowed)
        expected = sp.diff(source, symbol)
        target = f"d/d{symbol} of {_display(source)}"
        return _result_from_equivalence(
            kind=VerificationKind.DERIVATIVE,
            submitted=submitted,
            expected=expected,
            success_detail=(
                f"For {target}, the proposed derivative is symbolically equivalent."
            ),
            failure_detail=f"For {target}, the proposed derivative is not equivalent.",
        )

    def antiderivative(
        self, integrand: str, answer: str, *, variable: str = "x"
    ) -> VerificationResult:
        symbol = self._variable(variable)
        allowed = DEFAULT_SYMBOLS | {symbol.name, "C"}
        source = parse_math_expression(integrand, symbols=allowed)
        submitted = parse_math_expression(answer, symbols=allowed)
        derivative = sp.diff(submitted, symbol)
        target = f"an antiderivative of {_display(source)} with respect to {symbol}"
        return _result_from_equivalence(
            kind=VerificationKind.ANTIDERIVATIVE,
            submitted=derivative,
            expected=source,
            success_detail=(
                f"For {target}, differentiating the proposal reproduces the integrand."
            ),
            failure_detail=(
                f"For {target}, differentiating the proposal does not reproduce "
                "the integrand."
            ),
            submitted_display=_display(submitted),
            expected_display=f"an expression whose derivative is {_display(source)}",
        )

    def equivalent(
        self, left: str, right: str, *, variable: str = "x"
    ) -> VerificationResult:
        symbol = self._variable(variable)
        allowed = DEFAULT_SYMBOLS | {symbol.name}
        left_expression = parse_math_expression(left, symbols=allowed)
        right_expression = parse_math_expression(right, symbols=allowed)
        target = f"{_display(left_expression)} and {_display(right_expression)}"
        return _result_from_equivalence(
            kind=VerificationKind.EQUIVALENT,
            submitted=right_expression,
            expected=left_expression,
            success_detail=(
                f"The checked expressions {target} are symbolically equivalent on "
                "their common domain."
            ),
            failure_detail=f"The checked expressions {target} are not equivalent.",
        )

    def limit(
        self,
        expression: str,
        answer: str,
        *,
        variable: str = "x",
        point: str = "0",
        direction: str = "both",
    ) -> VerificationResult:
        if direction not in {"both", "left", "right"}:
            raise MathInputError("Limit direction must be both, left, or right.")
        symbol = self._variable(variable)
        allowed = DEFAULT_SYMBOLS | {symbol.name}
        source = parse_math_expression(expression, symbols=allowed)
        limit_point = parse_math_expression(point, symbols=set())
        if limit_point.free_symbols:
            raise MathInputError("The limit point cannot contain variables.")

        try:
            if direction == "left":
                expected = sp.limit(source, symbol, limit_point, dir="-")
                does_not_exist = False
            elif direction == "right":
                expected = sp.limit(source, symbol, limit_point, dir="+")
                does_not_exist = False
            elif limit_point in {sp.oo, -sp.oo}:
                expected = sp.limit(source, symbol, limit_point)
                does_not_exist = False
            else:
                left_limit = sp.limit(source, symbol, limit_point, dir="-")
                right_limit = sp.limit(source, symbol, limit_point, dir="+")
                sides_equal, _ = _equivalent(left_limit, right_limit)
                does_not_exist = sides_equal is not True
                expected = right_limit
        except (ArithmeticError, NotImplementedError, ValueError, TypeError) as error:
            return VerificationResult(
                VerificationKind.LIMIT,
                VerificationStatus.INCONCLUSIVE,
                answer.strip(),
                None,
                f"The symbolic limit could not be computed: {error}",
            )

        answer_is_dne = answer.strip().lower().replace(" ", "") in {
            "dne",
            "doesnotexist",
            "undefined",
        }
        direction_text = {
            "both": "two-sided",
            "left": "left-hand",
            "right": "right-hand",
        }[direction]
        target = (
            f"the {direction_text} limit of {_display(source)} as {symbol} "
            f"approaches {_display(limit_point)}"
        )
        if does_not_exist:
            status = (
                VerificationStatus.VERIFIED_CORRECT
                if answer_is_dne
                else VerificationStatus.VERIFIED_INCORRECT
            )
            return VerificationResult(
                VerificationKind.LIMIT,
                status,
                answer.strip(),
                "DNE",
                f"For {target}, the one-sided limits differ, so the limit does not exist.",
            )
        if isinstance(expected, sp.Limit) or expected is sp.nan:
            return VerificationResult(
                VerificationKind.LIMIT,
                VerificationStatus.INCONCLUSIVE,
                answer.strip(),
                _display(expected),
                f"For {target}, the symbolic engine left the limit unevaluated.",
            )
        if answer_is_dne:
            return VerificationResult(
                VerificationKind.LIMIT,
                VerificationStatus.VERIFIED_INCORRECT,
                answer.strip(),
                _display(expected),
                f"For {target}, the limit has a symbolic value.",
            )
        submitted = parse_math_expression(answer, symbols=allowed)
        return _result_from_equivalence(
            kind=VerificationKind.LIMIT,
            submitted=submitted,
            expected=expected,
            success_detail=f"For {target}, the proposal matches the symbolic limit.",
            failure_detail=f"For {target}, the proposal does not match the limit.",
        )
