"""Terminal interface for the local Sensei tutor."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from contextlib import ExitStack
from pathlib import Path

from sensei.models import (
    DEFAULT_MODEL_ID,
    DEFAULT_MODELS_DIRECTORY,
    FAST_MODEL_ID,
    ModelCatalog,
    model_path,
)
from sensei.learning import (
    LearningEvent,
    LearningEventError,
    LearningEventExtractor,
    Outcome,
)
from sensei.providers import LlamaCppProvider, ProviderError
from sensei.runtime import DEFAULT_RUNTIME_DIRECTORY, LocalLlamaRuntime, RuntimeSettings
from sensei.storage import (
    DEFAULT_DATABASE_PATH,
    LearningStore,
    ProgressUpdate,
    timestamped_data_path,
)
from sensei.tutor import TutorMode, TutorSession
from sensei.verification import (
    CalculusVerifier,
    MathInputError,
    VerificationKind,
    VerificationResult,
    VerificationStatus,
)


BANNER = """Sensei - local calculus tutor
Commands: /hint, /solve, /check, /done, /profile, /skills, /review, /new, /help, /quit
Study text is kept out of Git.
"""

HELP = """Commands
  /hint [question]  Give one hint for the active problem.
  /solve [question] Give a complete explained solution.
  /check TYPE       Deterministically check a derivative, limit, antiderivative,
                    or equivalent expression through a short input wizard.
  /done [outcome]   Record the problem. Outcome: correct, partial, or incorrect.
  /profile          Show RPG level, XP, attempts, and mastery totals.
  /skills [all]     Show practiced skills, or the complete skill catalog.
  /review           Show the next skill scheduled for review.
  /new [problem]    Clear the problem context and optionally start another.
  /status           Show the active model and bounded-context usage.
  /export [path]    Export learning records to a new JSON file.
  /backup [path]    Back up the SQLite database to a new file.
  /delete-data      Permanently clear personal learning records after confirmation.
  /help             Show this command list.
  /quit             Stop the local runtime and exit.

Plain text uses coach mode. The first plain-text message starts a problem;
later messages are treated as attempts or follow-up questions.
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the local Sensei calculus tutor."
    )
    parser.add_argument(
        "--prompt",
        help="Run one prompt and exit instead of starting the interactive shell.",
    )
    parser.add_argument(
        "--mode",
        choices=[mode.value for mode in TutorMode],
        default=TutorMode.COACH.value,
        help="Help mode for --prompt (default: coach).",
    )
    model_group = parser.add_mutually_exclusive_group()
    model_group.add_argument(
        "--model-id",
        default=None,
        help=f"Pinned model ID (default: {DEFAULT_MODEL_ID}).",
    )
    model_group.add_argument(
        "--fast",
        action="store_true",
        help=f"Use the lighter fallback model ({FAST_MODEL_ID}).",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Override the pinned model manifest path.",
    )
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=DEFAULT_MODELS_DIRECTORY,
        help="Directory containing local GGUF weights.",
    )
    parser.add_argument(
        "--runtime-dir",
        type=Path,
        default=DEFAULT_RUNTIME_DIRECTORY,
        help="Directory containing llama-server.exe.",
    )
    parser.add_argument(
        "--server-url",
        help="Use an already-running llama.cpp server instead of starting one.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help="Local SQLite learning-memory path.",
    )
    parser.add_argument(
        "--no-memory",
        action="store_true",
        help="Run an intentionally stateless interactive session.",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Wait for complete responses instead of printing tokens as they arrive.",
    )
    return parser.parse_args(argv)


def _print_reply(
    session: TutorSession,
    message: str,
    mode: TutorMode,
    *,
    starts_new_problem: bool,
    stream: bool,
) -> None:
    if stream:
        print("\nSensei: ", end="", flush=True)
        reply = session.respond(
            message,
            mode,
            starts_new_problem=starts_new_problem,
            on_token=lambda token: print(token, end="", flush=True),
        )
        print()
    else:
        reply = session.respond(
            message, mode, starts_new_problem=starts_new_problem
        )
        print(f"\nSensei: {reply.text}")


def _status(session: TutorSession) -> str:
    problem = session.problem_statement or "none"
    if len(problem) > 72:
        problem = f"{problem[:69]}..."
    return (
        f"Model: {session.model_name}\n"
        f"Active problem: {problem}\n"
        f"Completed tutor turns: {session.turn_count}\n"
        f"Recent context: {session.context_characters:,} / "
        f"{session.history_character_budget:,} characters"
    )


def _profile_text(profile: dict[str, object]) -> str:
    return (
        f"Level {profile['level']} | XP {profile['xp_into_level']}/"
        f"{profile['xp_for_next_level']} ({profile['total_xp']} total)\n"
        f"Attempts recorded: {profile['attempts']}\n"
        f"Skills practiced: {profile['skills_practiced']}\n"
        f"Skills mastered: {profile['skills_mastered']}"
    )


def _skills_text(progress: list[dict[str, object]], *, include_all: bool) -> str:
    visible = progress if include_all else [row for row in progress if row["attempts_count"]]
    if not visible:
        return "No skills practiced yet. Finish a problem with /done to record it."
    lines = []
    for row in visible:
        review = str(row["next_review_at"] or "-")[:10]
        lines.append(
            f"{row['name']}: {float(row['mastery_score']):.0f}/100 "
            f"({row['mastery_label']}, {row['attempts_count']} attempts, "
            f"review {review})"
        )
    return "\n".join(lines)


def _progress_text(
    update: ProgressUpdate, skill_name: str, event: LearningEvent
) -> str:
    outcome_text = event.outcome.value
    if event.effective_outcome_source == "verifier":
        outcome_text = f"verified {outcome_text}"
    reported_note = ""
    if event.reported_outcome and event.reported_outcome is not event.outcome:
        reported_note = (
            f" (reported {event.reported_outcome.value} by {event.outcome_source})"
        )
    return (
        f"Recorded {skill_name}: {outcome_text}{reported_note}.\n"
        f"+{update.xp_awarded} XP | Level {update.level} | "
        f"{update.xp_into_level}/{update.xp_for_next_level} XP to progress\n"
        f"Mastery: {update.mastery_score:.0f}/100 ({update.mastery_label})\n"
        f"Next review: {update.next_review_at[:10]}"
    )


def _verification_text(result: VerificationResult) -> str:
    heading = {
        VerificationStatus.VERIFIED_CORRECT: "VERIFIED CORRECT",
        VerificationStatus.VERIFIED_INCORRECT: "VERIFIED INCORRECT",
        VerificationStatus.INCONCLUSIVE: "INCONCLUSIVE",
    }[result.status]
    lines = [f"{heading}: {result.detail}", f"Submitted: {result.submitted}"]
    if result.expected:
        lines.append(f"Expected: {result.expected}")
    return "\n".join(lines)


def _ask_math(prompt: str, *, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    try:
        value = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt) as error:
        raise MathInputError("Verification canceled.") from error
    if not value and default is not None:
        return default
    if not value:
        raise MathInputError(f"{prompt} is required.")
    return value


def _check_problem(
    session: TutorSession,
    verifier: CalculusVerifier,
    kind_text: str,
) -> VerificationResult:
    if session.problem_statement is None:
        raise MathInputError("Start a problem before using /check.")
    try:
        kind = VerificationKind(kind_text.lower())
    except ValueError as error:
        raise MathInputError(
            "Check type must be derivative, limit, antiderivative, or equivalent."
        ) from error

    if kind is VerificationKind.DERIVATIVE:
        function = _ask_math("Function to differentiate")
        variable = _ask_math("Variable", default="x")
        answer = _ask_math("Your derivative")
        result = verifier.derivative(function, answer, variable=variable)
    elif kind is VerificationKind.LIMIT:
        expression = _ask_math("Limit expression")
        variable = _ask_math("Variable", default="x")
        point = _ask_math("Approach point", default="0")
        direction = _ask_math("Direction: both, left, or right", default="both")
        answer = _ask_math("Your limit (or DNE)")
        result = verifier.limit(
            expression,
            answer,
            variable=variable,
            point=point,
            direction=direction.lower(),
        )
    elif kind is VerificationKind.ANTIDERIVATIVE:
        integrand = _ask_math("Integrand")
        variable = _ask_math("Variable", default="x")
        answer = _ask_math("Your antiderivative")
        result = verifier.antiderivative(integrand, answer, variable=variable)
    else:
        first = _ask_math("First expression")
        second = _ask_math("Second expression")
        variable = _ask_math("Primary variable", default="x")
        result = verifier.equivalent(first, second, variable=variable)

    session.set_verification(result)
    print(_verification_text(result))
    return result


def _review_text(recommendation: dict[str, object] | None) -> str:
    if recommendation is None:
        return "No review is scheduled yet. Finish a problem with /done first."
    timing = "due now" if recommendation["due"] else str(
        recommendation["next_review_at"]
    )[:10]
    text = (
        f"Review next: {recommendation['name']} - "
        f"{float(recommendation['mastery_score']):.0f}/100 "
        f"({recommendation['mastery_label']}), {timing}."
    )
    if recommendation["misconception"]:
        text += f"\nWatch for: {recommendation['misconception']}"
    return text


def _output_path(argument: str, directory: Path, prefix: str, suffix: str) -> Path:
    if argument:
        return Path(argument).expanduser()
    return timestamped_data_path(directory, prefix, suffix)


def _finish_problem(
    session: TutorSession,
    store: LearningStore,
    extractor: LearningEventExtractor,
    outcome_text: str,
) -> None:
    override = None
    if outcome_text:
        try:
            override = Outcome(outcome_text.lower())
        except ValueError as error:
            raise ValueError(
                "Outcome must be correct, partial, or incorrect."
            ) from error
    snapshot = session.learning_snapshot()
    print("Reviewing the completed problem locally...", flush=True)
    event = extractor.extract(snapshot, override)
    update = store.record_event(event)
    skill_name = store.skill_names()[event.skill_id]
    print(_progress_text(update, skill_name, event))
    session.reset()
    session.set_learner_context(store.tutor_context())


def _memory_command(
    command: str,
    argument: str,
    session: TutorSession,
    store: LearningStore | None,
    extractor: LearningEventExtractor | None,
) -> bool:
    memory_commands = {
        "/done",
        "/profile",
        "/skills",
        "/review",
        "/export",
        "/backup",
        "/delete-data",
    }
    if command not in memory_commands:
        return False
    if store is None or extractor is None:
        print("Learning memory is disabled for this session.")
        return True
    if command == "/done":
        _finish_problem(session, store, extractor, argument)
    elif command == "/profile":
        print(_profile_text(store.profile()))
    elif command == "/skills":
        if argument not in {"", "all"}:
            raise ValueError("Use /skills or /skills all.")
        print(_skills_text(store.skill_progress(), include_all=argument == "all"))
    elif command == "/review":
        if argument:
            raise ValueError("Use /review without arguments.")
        print(_review_text(store.review_recommendation()))
    elif command == "/export":
        path = _output_path(
            argument,
            store.database_path.parent / "exports",
            "sensei-export",
            ".json",
        )
        print(f"Exported learning data to {store.export_json(path)}")
    elif command == "/backup":
        path = _output_path(
            argument,
            store.database_path.parent / "backups",
            "sensei-backup",
            ".db",
        )
        print(f"Backed up learning database to {store.backup(path)}")
    elif command == "/delete-data":
        if argument:
            raise ValueError("Use /delete-data without arguments.")
        try:
            confirmation = input(
                "Type DELETE to permanently clear learning data: "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            confirmation = ""
        if confirmation == "DELETE":
            deleted = store.delete_learning_data()
            session.reset()
            session.set_learner_context(None)
            print(f"Deleted {deleted} learning attempts. The empty schema remains ready.")
        else:
            print("Deletion canceled.")
    return True


def run_interactive(
    session: TutorSession,
    *,
    store: LearningStore | None = None,
    extractor: LearningEventExtractor | None = None,
    verifier: CalculusVerifier | None = None,
    stream: bool = True,
) -> int:
    verifier = verifier or CalculusVerifier()
    print(BANNER)
    while True:
        try:
            raw = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nStopping Sensei.")
            return 0
        if not raw:
            continue

        command, _, argument = raw.partition(" ")
        command = command.lower()
        argument = argument.strip()
        if command in {"/quit", "/exit"}:
            print("Stopping Sensei.")
            return 0
        if command == "/help":
            print(HELP)
            continue
        if command == "/status":
            print(_status(session))
            continue
        if command == "/check":
            try:
                _check_problem(session, verifier, argument)
            except (MathInputError, RuntimeError, ValueError) as error:
                print(f"Verification failed: {error}", file=sys.stderr)
            continue
        try:
            if _memory_command(command, argument, session, store, extractor):
                continue
        except (
            FileExistsError,
            LearningEventError,
            OSError,
            ProviderError,
            RuntimeError,
            ValueError,
            sqlite3.Error,
        ) as error:
            print(f"Memory operation failed: {error}", file=sys.stderr)
            continue
        if command == "/new":
            session.reset()
            if not argument:
                print("Problem context cleared. Enter the next problem when ready.")
                continue
            mode = TutorMode.COACH
            starts_new = True
            message = argument
        elif command in {"/hint", "/solve"}:
            mode = TutorMode.HINT if command == "/hint" else TutorMode.SOLVE
            if argument:
                message = argument
                starts_new = session.problem_statement is None
            elif session.problem_statement is not None:
                message = (
                    "Give me the next hint."
                    if mode is TutorMode.HINT
                    else "Now show me the complete solution."
                )
                starts_new = False
            else:
                print(f"Enter a problem after {command} or start one first.")
                continue
        elif command.startswith("/"):
            print(f"Unknown command {command!r}. Use /help.")
            continue
        else:
            mode = TutorMode.COACH
            message = raw
            starts_new = session.problem_statement is None

        try:
            _print_reply(
                session,
                message,
                mode,
                starts_new_problem=starts_new,
                stream=stream,
            )
        except (ProviderError, ValueError) as error:
            print(f"\nSensei could not answer: {error}", file=sys.stderr)


def _runtime_context(
    args: argparse.Namespace,
    selected_path: Path,
    model_id: str,
    stack: ExitStack,
) -> str:
    if args.server_url:
        return args.server_url
    executable = args.runtime_dir.resolve() / "llama-server.exe"
    print(
        f"Starting local model {model_id}; initial loading may take a moment...",
        file=sys.stderr,
    )
    runtime = LocalLlamaRuntime(
        RuntimeSettings(
            executable=executable,
            model_path=selected_path,
            model_alias=model_id,
        )
    )
    return stack.enter_context(runtime).base_url


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        catalog = (
            ModelCatalog.load(args.manifest.resolve())
            if args.manifest
            else ModelCatalog.load()
        )
        selected_id = FAST_MODEL_ID if args.fast else args.model_id or DEFAULT_MODEL_ID
        candidate = catalog.get(selected_id)
        selected_path = model_path(candidate, args.models_dir)
        if not args.server_url and not selected_path.is_file():
            raise FileNotFoundError(
                f"Model is missing: {selected_path}\n"
                f"Download it with: python scripts\\download_models.py "
                f"--model {selected_id}"
            )

        with ExitStack() as stack:
            base_url = _runtime_context(
                args, selected_path, selected_id, stack
            )
            provider = LlamaCppProvider(base_url, selected_id)
            session = TutorSession(provider, selected_id)
            if args.prompt:
                _print_reply(
                    session,
                    args.prompt,
                    TutorMode(args.mode),
                    starts_new_problem=True,
                    stream=not args.no_stream,
                )
                return 0
            if args.no_memory:
                return run_interactive(session, stream=not args.no_stream)
            store = stack.enter_context(LearningStore(args.database))
            session.set_learner_context(store.tutor_context())
            extractor = LearningEventExtractor(provider, store.skill_names())
            return run_interactive(
                session,
                store=store,
                extractor=extractor,
                stream=not args.no_stream,
            )
    except (
        FileNotFoundError,
        OSError,
        ProviderError,
        RuntimeError,
        ValueError,
        sqlite3.Error,
    ) as error:
        print(f"Sensei could not start: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
