"""Check an OASIS profile file before simulating with it.

  python check_oasis_profiles.py data/oasis/user_data_36.json
  python check_oasis_profiles.py data/oasis/197_progressive.csv

Accepts the two OASIS formats:
  JSON (Reddit-style):  [{"realname", "username", "bio", "persona", "age", "gender", "mbti", "country", ...}]
  CSV  (Twitter-style): columns name, username, description, user_char [, following_agentid_list]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from feedbench.profiles import _read_oasis_profiles


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    a = ap.parse_args()
    path = Path(a.path)
    rows = _read_oasis_profiles(path)
    problems = []
    if not rows:
        problems.append("no profiles found")
    handles = [r["handle"] for r in rows]
    if len(set(h.lower() for h in handles)) != len(handles):
        problems.append("duplicate usernames (they will be made unique)")
    missing = {k: sum(1 for r in rows if not r[k]) for k in ("name", "handle", "bio", "persona")}
    for k, n in missing.items():
        if n:
            problems.append(f"{n} profiles without {k}")
    graph = [r.get("following") for r in rows if r.get("following") is not None]
    edges = sum(len(g) for g in graph)
    out_of_range = sum(1 for g in graph for f in g if not 0 <= f < len(rows))

    print(f"File:      {path}  ({'JSON, Reddit-style' if path.suffix.lower() == '.json' else 'CSV, Twitter-style'})")
    print(f"Profiles:  {len(rows)}  -> the simulation will have {len(rows)} users")
    print(f"Graph:     {'real follow graph, ' + str(edges) + ' edges' if graph else 'none in file, synthetic graph from network.py'}"
          + (f" ({out_of_range} edges point outside the file and are dropped)" if out_of_range else ""))
    if path.suffix.lower() == ".csv":
        print("Privacy:   CSV profiles are treated as real accounts: names/handles become user_N and bios are hidden")
    print("Sample:")
    for r in rows[:3]:
        print(f"  @{r['handle'] or '?'} · {r['name'] or '?'} · {(r['bio'] or '')[:70]}")
    print("Status:    " + ("OK" if not problems or problems == ["duplicate usernames (they will be made unique)"] else "WARN"))
    for p in problems:
        print("  - " + p)
    print(f"\nRun it:    python build_lab.py --profiles {path.as_posix()} --quick")


if __name__ == "__main__":
    main()
