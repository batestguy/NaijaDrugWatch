"""Serve the verification desk and save every answer to disk as it is given.

WHY THIS EXISTS. The desk was built as a self-contained page that kept answers in the browser, so the
only way they left it was a manual download. That put the most fragile step of the whole check - get
the file out and send it - on the person doing the work, and it failed in exactly the way that step
always fails. This server removes it: the page posts its state after every answer, the server writes
the file atomically, and the answers are on disk whether or not anyone remembers to press anything.

WHAT IT WILL DO. Serve `site/verify/` over http on the loopback interface, and accept one POST path,
`/save`, which writes the posted JSON to `.agent/verify-results.json`. Nothing else. No auth, because
it binds to 127.0.0.1 and is a one-person tool on one machine; do not put it on a public interface.

    .venv\\Scripts\\python.exe -X utf8 scripts/desk_server.py
    .venv\\Scripts\\python.exe -X utf8 scripts/desk_server.py --port 8814 --out .agent/verify-results.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVE = ROOT / "site" / "verify"


def count_progress(payload: dict) -> tuple[int, int]:
    """(cards judged, lines answered) from an export, using the export's own shape.

    `cards` is keyed by item id; each value holds one answer per numbered line plus a recomputed
    `outcome`. A card counts as judged only when its outcome is pass or fail - an incomplete card has
    some lines answered and is not a verdict.
    """
    cards = payload.get("cards") or {}
    judged = 0
    lines = 0
    for entry in cards.values():
        if not isinstance(entry, dict):
            continue
        lines += len([key for key in entry if str(key).isdigit() and entry[key]])
        if entry.get("outcome") in ("pass", "fail"):
            judged += 1
    return judged, lines


class DeskHandler(SimpleHTTPRequestHandler):
    out_path: Path = ROOT / ".agent" / "verify-results.json"
    serve_dir: Path = SERVE

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(self.serve_dir), **kwargs)

    def log_message(self, fmt: str, *args) -> None:  # quieter than the default
        if "/save" in (args[0] if args else ""):
            return
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def do_POST(self) -> None:  # noqa: N802 - http.server's spelling
        if self.path.rstrip("/") != "/save":
            self.send_error(404, "only POST /save is accepted")
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 8_000_000:
            self.send_error(400, "empty or oversized body")
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self.send_error(400, f"not JSON: {exc}")
            return

        saved_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        payload["saved_by"] = "desk_server"
        payload["saved_at_utc"] = saved_at

        path = self.out_path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)  # atomic: a half-written answer set never replaces a whole one

        cards, lines = count_progress(payload)
        print(f"saved {path.name}: {cards} card(s) judged, {lines} line(s) answered ({saved_at})",
              flush=True)

        body = json.dumps({
            "ok": True,
            "saved_at_utc": saved_at,
            "judged": cards,
            "lines": lines,
            "file": str(path.relative_to(ROOT)),
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8814)
    parser.add_argument("--out", default=".agent/verify-results.json")
    parser.add_argument("--serve", default=None)
    args = parser.parse_args(argv[1:])

    serve = Path(args.serve).resolve() if args.serve else SERVE
    if not (serve / "index.html").exists():
        print(f"no desk at {serve}\\index.html - build it with scripts/build_verify_desk.py",
              file=sys.stderr)
        return 2
    DeskHandler.serve_dir = serve
    DeskHandler.out_path = (ROOT / args.out).resolve()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), DeskHandler)
    print(f"desk: http://127.0.0.1:{args.port}/", flush=True)
    print(f"answers save to: {DeskHandler.out_path}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
