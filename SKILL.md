---
name: eqsans-reduce
description: Reduce EQSANS (SNS beamline 6) small-angle neutron scattering data with eqsanscli/drtsans — load an IPTS catalog, match transmission/background/empty-beam runs, set or clone reduction configurations, run reductions (including time-sliced/time-resolved kinetic runs), calibrate absolute scale from porsil, stitch and plot I(Q). Use whenever the user asks to reduce EQSANS runs or samples, continue/load an eqsanscli session, modify a drtsans reduction script (EQVar/reduceNow .py), set up time slicing, or send reduced data to per-sample output folders.
---

# EQSANS data reduction

Two ways to reduce. Pick one deliberately — do not mix them in one task.

| Path | Use when | Tool |
|---|---|---|
| **A · eqsanscli session** (default) | "reduce these samples", "load session X", "clone config", "enable time slicing" — anything table- or session-shaped | `eqcli.py` → `eqsanscli-headless` |
| **B · drtsans script** | the user names a `.py` reduction script ("based on `reduce.py`, modify so that…"), or wants every line visible | edit the script, run `drtsans <script>.py` |

Authoritative upstream docs (read when something here is not enough — do not
duplicate them into answers): `/SNS/EQSANS/shared/script/eqsanstools-cli/SKILL.md`
(full command reference), `README.md`, `knowledge/*.md`, `CLAUDE.md` (change log
— the best source for *why* a behavior exists).

---

## Path A — driving eqsanscli

```bash
python3 ~/.claude/skills/eqsans-reduce/scripts/eqcli.py -d /SNS/EQSANS/IPTS-<N>/shared \
  "/show ipts" "/config list" "/show table --name a10b10"
```

The helper starts `eqsanscli-headless`, sends the commands in order, and prints a
compact result per command (`--max-rows 0` for counts only, `--json` for raw,
`--stdin` to pipe a command list). Progress lines go to stderr.

**Rules that matter:**

- **`-d` must be the IPTS shared folder.** Session state lives in
  `<dir>/.eqsanscli/sessions/`; the session auto-resumes from there at startup and
  auto-saves after every command. That is what makes separate invocations behave
  as one continuous session. A wrong `-d` silently starts an empty session.
- **Only explicit `/commands`.** Anything without a leading `/` goes to the CLI's
  own LLM — unreliable and it rewrites state. Never send natural language.
- **Small batches.** Every command in a batch runs even if an earlier one failed.
  Send 1–5 related commands, read the results, then continue.
- **Verify after mutating.** `/set …` → `/show table --name <x>` or `/show config <id>`.
- **Long reductions run in the background** (`run_in_background: true`), stdout+stderr
  to a log file, then poll the log. Only one reduction job at a time.
- **Relay progress to the user** — a reduction is minutes per row and can be hours
  when time-sliced. Report periodically, not only at the end.

### Orientation on an unfamiliar session

```
/show ipts        /session list        /config list        /show table
```

`/session load <name>` switches to a saved session (name without `.json`, from
`<dir>/.eqsanscli/sessions/`). `/continue` resumes the autosave.

Read-only orientation needs no CLI at all: `<dir>/.eqsanscli/sessions/_autosave.json`
holds the catalog (`catalog_data`) and the resolved per-config calibration
(`configurations`, `instrument_provenance`). Mine it with `python3 -c` when you
only need facts — especially when writing a Path B script, so the script's cycle
files and offsets match the session instead of being guessed.

### Core workflow (fresh experiment)

`/autopilot <ipts> [flags]` does all of it. Reach for the manual path only when
autopilot's flags cannot express the request:

| Step | Command |
|---|---|
| 1 Catalog | `/load ipts <N>` |
| 2 Pair runs | `/matchruns` (also applies presets + cycle calibration files) |
| 3 Fix pairing | `/reclass <run> <class>` then `/matchruns`; `/assign bkg <sample>`; `/set <row> emp <run>` |
| 4 Output dir | `/set outputdir <path>` (session-wide) |
| 5 Abs. scale | `/reduce --sample porsil` → `/calibrate porsil_<cfg>_Iq.dat --applynow` |
| 6 Reduce | `/reduce all` / `/reduce --sample <pat>` / `/reduce 5-10` |
| 7 Stitch, plot | `/stitch smart`; `/plot *_Iq.dat --save x.png` |

Empty beam is mandatory (it carries the beam centre); missing trans/bkg is only a
warning. Changing a row field or config param auto-marks `done` rows `modified`,
so they re-reduce without `--force`.

### Time-resolved (time-sliced) reduction

The common request here. Full playbooks — cloning a config, per-sample folders,
both worked end to end — in **`references/time-resolved.md`**. Read it before
starting one. The essentials:

- Slicing is per **config**, not per row: `usetimeslice` / `timesliceinterval`.
  So clone the physical config and assign only the rows that should be sliced —
  never flip slicing on a config that static rows share.
- drtsans runs one **full independent reduction per slice**. `/reduce` prints
  `⏱ Time-slicing <cfg>: ~N slices/run`. Relay it; confirm with the user above
  ~200 slices per run.
- Give each sliced sample its **own folder** (`/set <row> outputdir <path>`) —
  hundreds of files per run otherwise collide in one directory.

### Per-sample output folders

`/set <rows> outputdir <path>` overrides the session-wide dir for those rows only
(row override wins over both session and config `outputdir`). There is no
`{sample}` token — issue one `/set` per row, folder named from that row's sample:

```
/set 45 outputdir /SNS/EQSANS/IPTS-38151/shared/timeseries/a10b10-1
```

Downstream discovery (`/stitch`, `/list iq`, `/plot`, `/share`) scans the
*session-wide* dir only, so point at overridden outputs explicitly:
`/list iq <dir>`, `/plot <dir>/<file>`.

---

## Path B — editing a drtsans script

One `EQVar` per reduced curve, handed to `reduceNow`. See
**`references/script-mode.md`** for the attribute map, the time-slicing and
per-sample-folder edits, and how to run it. In short: copy the script (never
edit the user's original in place unless asked), trim the run/sample arrays to
the requested samples keeping all arrays index-aligned, set `eq._usetimeslice`,
`eq._timesliceinterval`, `eq._outputdir`, then `drtsans <script>.py`.

That reference also carries the two recipes this path keeps needing: **absolute
scale in script mode** (there is no `/calibrate` — reduce porsil at scale 1.0 and
ratio it against the NG3 standard) and **building a script for a whole experiment
from the catalog** (per-config transmission runs, repeated blocks, validation
before launch).

`/export script -o <file>` writes such a script from the current table;
`/export script --like <example.py>` reproduces an existing script's style.

---

## Gotchas

| Symptom / situation | What to do |
|---|---|
| Clone name rejected | `<dst>` must contain the source's physics id (`4m2.5a30hz` → `4m2.5a30hztr` ✓, `tr` ✗) |
| Clone with `_`/uppercase (`4m2.5a30hz_TR`) | Resolves to the normalized id `4m2.5a30hztr`; both spellings work since v0.36.6, but prefer the plain lowercase name |
| Sliced row reduced an hour, then a Qt/X11 error | Not a failure if I(Q) files exist — reported `done` with a `note`. Do **not** re-reduce |
| Rows silently skipped | Status is `done`; use `--force`, or change a parameter (auto-marks `modified`) |
| `--sample` matched too little | Exact, case-insensitive by default — use `*` (`a10b10*`, `*a5b5*`) |
| Thousands of output files | Expected for slicing: `{sample}_{config}_{slice}_frame_{0,1}_Iq.dat` per slice |
| 30 Hz frame skipping | Two files per run, `_frame_0` (low-Q) and `_frame_1` (high-Q); both stitch entries |
| Reduction refuses to start | Output dir not writable, or a row has no empty beam — the message names the rows |
| Script batch dies partway through | `reduceNow()` raises `SystemExit` on a failed run — wrap it in try/except, see `references/script-mode.md` |
| Calibration returns NaN or a handful of points | The Q window is outside that config's measured range — `/calibrate`'s default `[0.01, 0.03]` is below a 2.5 m/2.5 Å curve (starts ~0.023) |
| Sample paired with the wrong transmission | A sample usually has one transmission run **per configuration** — build one mapping per config, not one global |
| Titles like `T-s1`, `T-sample3` | Placeholder transmission names. Trust the user's sample mapping over the titles, and record it in the script/session |
