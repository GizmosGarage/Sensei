"""Loopback-only browser dashboard for Sensei's local learning memory."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import webbrowser
from datetime import timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sensei.quests import DEFAULT_QUESTS_PATH, QuestDeck
from sensei.storage import DEFAULT_DATABASE_PATH, DEFAULT_SKILLS_PATH, LearningStore, utc_now


LOOPBACK_HOST = "127.0.0.1"
DEFAULT_DASHBOARD_PORT = 8765
WEB_DIRECTORY = Path(__file__).resolve().parent / "web"
ASSETS = {
    "/": (WEB_DIRECTORY / "index.html", "text/html; charset=utf-8"),
    "/assets/app.js": (
        WEB_DIRECTORY / "app.js",
        "text/javascript; charset=utf-8",
    ),
    "/assets/styles.css": (
        WEB_DIRECTORY / "styles.css",
        "text/css; charset=utf-8",
    ),
}


def rank_name(level: int) -> str:
    if level >= 10:
        return "Calculus Master"
    if level >= 7:
        return "Integral Scholar"
    if level >= 4:
        return "Derivative Adept"
    if level >= 2:
        return "Limit Initiate"
    return "Dojo Novice"


class DashboardService:
    """Builds a public, answer-key-free snapshot from local application state."""

    def __init__(
        self,
        database_path: Path = DEFAULT_DATABASE_PATH,
        *,
        skills_path: Path = DEFAULT_SKILLS_PATH,
        quests_path: Path = DEFAULT_QUESTS_PATH,
    ) -> None:
        self.database_path = database_path.resolve()
        self.skills_path = skills_path.resolve()
        self.quests_path = quests_path.resolve()

    def state(self) -> dict[str, Any]:
        with LearningStore(self.database_path, self.skills_path) as store:
            deck = QuestDeck.load(
                self.quests_path,
                skills_path=self.skills_path,
            )
            profile = store.profile()
            profile["rank_name"] = rank_name(int(profile["level"]))
            recommendation = deck.recommend(store)
            review = store.review_recommendation()
            return {
                "generated_at": utc_now().astimezone(timezone.utc).isoformat(),
                "profile": profile,
                "next_quest": recommendation.public_dict(),
                "review": review,
                "skills": store.skill_progress(),
                "recent_attempts": store.recent_attempts(),
                "catalog": {
                    "quest_count": len(deck.quests),
                    "quest_skill_count": len(deck.eligible_skill_ids),
                },
                "runtime": {
                    "host": LOOPBACK_HOST,
                    "storage": "Local SQLite",
                    "model_access": "Tutor process only",
                },
            }


class SenseiDashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        service: DashboardService,
    ) -> None:
        self.service = service
        super().__init__(server_address, DashboardRequestHandler)


class DashboardRequestHandler(BaseHTTPRequestHandler):
    server: SenseiDashboardServer

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
            "form-action 'none'; frame-ancestors 'none'",
        )

    def _send_bytes(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        cache_control: str = "no-store",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, document: object) -> None:
        body = json.dumps(document, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        if path == "/healthz":
            self._send_json(200, {"status": "ok", "local": True})
            return
        if path == "/api/dashboard":
            try:
                document = self.server.service.state()
            except Exception as error:  # keep request failures inside the server
                self.log_error("Dashboard snapshot failed: %s", error)
                self._send_json(500, {"error": "Dashboard data is unavailable."})
                return
            self._send_json(200, document)
            return
        asset = ASSETS.get(path)
        if asset is None:
            self._send_json(404, {"error": "Not found."})
            return
        asset_path, content_type = asset
        try:
            body = asset_path.read_bytes()
        except OSError as error:
            self.log_error("Dashboard asset failed: %s", error)
            self._send_json(500, {"error": "Dashboard asset is unavailable."})
            return
        self._send_bytes(
            200,
            body,
            content_type,
            cache_control="no-cache",
        )

    def log_message(self, format: str, *args: object) -> None:
        print(
            f"Dashboard {self.client_address[0]} - {format % args}",
            file=sys.stderr,
        )


def create_server(
    service: DashboardService,
    *,
    port: int = DEFAULT_DASHBOARD_PORT,
) -> SenseiDashboardServer:
    if not 0 <= port <= 65_535:
        raise ValueError("Dashboard port must be from 0 to 65535.")
    return SenseiDashboardServer((LOOPBACK_HOST, port), service)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Show Sensei's local RPG learning dashboard."
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help="Local SQLite learning-memory path.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_DASHBOARD_PORT,
        help=f"Loopback port (default: {DEFAULT_DASHBOARD_PORT}).",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Start the dashboard without opening a browser.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        service = DashboardService(args.database)
        service.state()
        server = create_server(service, port=args.port)
    except (OSError, ValueError, sqlite3.Error) as error:
        print(f"Dashboard could not start: {error}", file=sys.stderr)
        return 1

    host, port = server.server_address
    url = f"http://{host}:{port}/"
    print(f"Sensei dashboard: {url}")
    print("Learning data stays in the selected local SQLite database.")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
