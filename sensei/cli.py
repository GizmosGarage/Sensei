"""Terminal interface for the local Sensei tutor."""

from __future__ import annotations

import argparse
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
from sensei.providers import LlamaCppProvider, ProviderError
from sensei.runtime import DEFAULT_RUNTIME_DIRECTORY, LocalLlamaRuntime, RuntimeSettings
from sensei.tutor import TutorMode, TutorSession


BANNER = """Sensei - local calculus tutor
Commands: /hint, /solve, /new, /status, /help, /quit
Study text is kept out of Git.
"""

HELP = """Commands
  /hint [question]  Give one hint for the active problem.
  /solve [question] Give a complete explained solution.
  /new [problem]    Clear the problem context and optionally start another.
  /status           Show the active model and bounded-context usage.
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


def run_interactive(session: TutorSession, *, stream: bool = True) -> int:
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
            return run_interactive(session, stream=not args.no_stream)
    except (FileNotFoundError, ProviderError, RuntimeError, ValueError) as error:
        print(f"Sensei could not start: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
