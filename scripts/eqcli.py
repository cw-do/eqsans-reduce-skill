#!/usr/bin/env python3
"""Drive eqsanscli (headless JSON mode) from a single shell command.

The headless CLI reads one /command per line on stdin and answers with one JSON
object per line. This wrapper sends a batch, prints a compact human-readable
result per command, and keeps big payloads (catalogs, tables) from flooding the
transcript.

Session state lives in <workdir>/.eqsanscli/sessions/, so ALWAYS pass the IPTS
shared folder as --dir: the session auto-resumes from there and auto-saves after
every command, which is what makes separate invocations behave like one session.

Usage:
    eqcli.py -d /SNS/EQSANS/IPTS-38151/shared "/show table" "/config list"
    eqcli.py -d ... --stdin < commands.txt
    eqcli.py -d ... --max-rows 0 "/show catalog"     # suppress row dump
    eqcli.py -d ... --json "/show table"             # raw JSON lines

Exit status is 1 if any command reported success=false.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

LAUNCHER = "/SNS/EQSANS/shared/script/eqsanstools-cli/eqsanscli-headless"

# Columns worth showing per data type; anything else falls back to all keys.
PREFERRED = {
    "working_table": ["Idx", "Sample", "Config", "Scatt", "Trans", "Bkg",
                      "BkgTr", "Empty", "Thick", "Status"],
    "catalog": ["run_number", "title", "run_class", "detector_distance",
                "wavelength", "duration"],
}


def cell(value) -> str:
    """One line per cell — display rows carry the run title on a second line."""
    return str(value).split("\n")[0].strip()


def render_rows(data: dict, max_rows: int) -> list[str]:
    rows = data.get("rows") or data.get("results") or data.get("groups") or []
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return []
    cols = [c for c in PREFERRED.get(data.get("type", ""), []) if c in rows[0]]
    if not cols:
        cols = list(rows[0].keys())
    out = [f"  [{data.get('type')}: {len(rows)} rows]"]
    if max_rows == 0:
        return out
    shown = rows[:max_rows]
    widths = [max(len(c), *(len(cell(r.get(c, ""))) for r in shown)) for c in cols]
    out.append("  " + "  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    for r in shown:
        out.append("  " + "  ".join(cell(r.get(c, "")).ljust(w)
                                   for c, w in zip(cols, widths)))
    if len(rows) > len(shown):
        out.append(f"  … {len(rows) - len(shown)} more rows (raise --max-rows)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-d", "--dir", required=True,
                    help="working directory (the IPTS shared folder)")
    ap.add_argument("--max-rows", type=int, default=30,
                    help="rows to print per table (0 = count only, default 30)")
    ap.add_argument("--json", action="store_true", help="print raw JSON lines")
    ap.add_argument("--stdin", action="store_true",
                    help="read commands from stdin, one per line")
    ap.add_argument("commands", nargs="*")
    args = ap.parse_args()

    cmds = list(args.commands)
    if args.stdin:
        cmds += [ln.strip() for ln in sys.stdin if ln.strip()]
    if not cmds:
        ap.error("no commands given")

    proc = subprocess.Popen(
        [LAUNCHER], cwd=args.dir, text=True, bufsize=1,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE,  # stderr inherited: progress
    )
    proc.stdin.write("".join(c + "\n" for c in cmds) + "/exit\n")
    proc.stdin.flush()

    failures = 0
    pending = list(cmds)
    # Startup preamble: an optional "Resumed session ..." line, then always
    # "eqsanscli headless mode ready". Responses to our commands start after it.
    started = False
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        if args.json:
            print(line, flush=True)
            continue
        try:
            resp = json.loads(line)
        except json.JSONDecodeError:
            print(f"  ?? {line}", flush=True)
            continue
        if not started:
            msg = (resp.get("message") or "").strip()
            if msg.startswith("Resumed session"):
                print(f"  ({msg})", flush=True)
            started = msg == "eqsanscli headless mode ready"
            continue
        label = pending.pop(0) if pending else "/exit"
        ok = resp.get("success")
        if not ok:
            failures += 1
        print(f"\n▸ {label}\n  {'ok' if ok else 'FAILED'}: "
              f"{(resp.get('message') or '').strip()}", flush=True)
        data = resp.get("data")
        if isinstance(data, dict):
            for ln in render_rows(data, args.max_rows):
                print(ln, flush=True)
    proc.wait()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
