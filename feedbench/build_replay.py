"""Embed results/benchmark.json into the replay page.

Writes
  replay.html                   standalone page, open it in any browser (no server needed)
  results/replay_artifact.html  same page without the document wrapper (for publishing as a claude.ai artifact)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(src: str, out: str) -> None:
    data = json.loads(Path(src).read_text())
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    body = (HERE / "replay_template.html").read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "replay_artifact.html").write_text(body, encoding="utf-8")
    full = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            + body.replace("<style>", "<style>\nhtml,body{margin:0}", 1)
            + "\n</html>\n")
    Path(out).write_text(full, encoding="utf-8")
    print(f"Wrote {out} ({len(full) / 1e6:.1f} MB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE / "results" / "benchmark.json"))
    ap.add_argument("--out", default=str(HERE / "replay.html"))
    a = ap.parse_args()
    main(a.data, a.out)
