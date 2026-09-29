"""Generate the benchmark and serve its dashboard and algorithm lab: python app.py."""

import argparse
import json
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlparse

from simulate import RULES, run_experiment, write_bundle

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "runs"
EXPERIMENT_LOG = LOG_DIR / "experiment_log.jsonl"
FEEDBACK_LOG = LOG_DIR / "feedback_log.jsonl"
MAX_BODY_BYTES = 16 * 1024
MAX_TEXT = 2000
log_lock = Lock()


def append_jsonl(path, record):
    with log_lock:
        LOG_DIR.mkdir(exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jsonl(path):
    if not path.exists():
        return []
    with log_lock:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def clean_text(value, limit=MAX_TEXT):
    return str(value or "").strip()[:limit]


class LabHandler(SimpleHTTPRequestHandler):
    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/api/rules":
                return self.send_json({k: {kk: vv for kk, vv in v.items() if kk != "score"} for k, v in RULES.items()})
            if url.path == "/api/experiment":
                result = run_experiment(query.get("rule", "capped"), query.get("cap", 2))
                meta = result["meta"]
                append_jsonl(EXPERIMENT_LOG, {"at": meta["generated_at"], "rule": meta["candidate"]["rule"],
                                              "cap": meta["candidate"]["cap"], "status": meta["status"],
                                              "config_hash": meta["config_hash"], "verdict": meta["verdict"]})
                return self.send_json(result)
            if url.path == "/api/feedback":
                return self.send_json({"feedback": read_jsonl(FEEDBACK_LOG), "experiments": read_jsonl(EXPERIMENT_LOG)})
        except (ValueError, TypeError) as error:
            return self.send_json({"error": str(error)}, 400)
        return super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/feedback":
            return self.send_json({"error": "Not found"}, 404)
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_BODY_BYTES:
            return self.send_json({"error": "Feedback body is empty or too large."}, 413)
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self.send_json({"error": "Invalid JSON."}, 400)
        if not isinstance(data, dict) or not clean_text(data.get("note")):
            return self.send_json({"error": "A note is required."}, 400)
        record = {"at": datetime.now(timezone.utc).isoformat(),
                  "reviewer": clean_text(data.get("reviewer"), 80) or "anonymous",
                  "role": clean_text(data.get("role"), 40),
                  "rule": clean_text(data.get("rule"), 40), "cap": clean_text(data.get("cap"), 4),
                  "status": clean_text(data.get("status"), 20), "fixture": clean_text(data.get("fixture"), 40),
                  "config_hash": clean_text(data.get("config_hash"), 64),
                  "rating": clean_text(data.get("rating"), 20), "note": clean_text(data.get("note"))}
        append_jsonl(FEEDBACK_LOG, record)
        return self.send_json({"saved": record}, 201)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    web_root = ROOT / "web"
    print("Computing the pre-registered benchmark and cap sweep...", flush=True)
    write_bundle(web_root / "data")
    handler = partial(LabHandler, directory=str(web_root))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print("TikkunTech demo: http://127.0.0.1:%d" % args.port, flush=True)
    print("Lab runs are logged to %s. Press Ctrl+C to stop." % LOG_DIR, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
