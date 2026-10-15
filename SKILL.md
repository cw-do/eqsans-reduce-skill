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
  `/show config` is a truncated compact view — the authoritative check is the
  `configuration` block of the drtsans input it wrote, `<outputdir>/<sample>_<cfg>.json`
  (`maskFileName`, `numQBins`, `QbinType`, `fitInelasticIncoh`, `incohfit_qmin/qmax`,
  `StandardAbsoluteScale`; thickness under `sample`). Check it on the first row reduced.
- **Long reductions run in the background** (`run_in_background: true`), stdout+stderr
  to a log file, then poll the log. Only one reduction job at a time.
- **Never touch the session while a reduction runs.** The running process autosaves
  at its end and overwrites any `/set` made meanwhile. Queue the change for after
  it finishes. Dependent steps (set → reduce porsil → calibrate → reduce → stitch)
  can be chained as consecutive `eqcli.py` calls inside **one** background Bash command.
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
| 5 Abs. scale | **Every config, independently** — see *Absolute scale* below |
| 6 Reduce | `/reduce all` / `/reduce --sample <pat>` / `/reduce 5-10` |
| 7 Stitch, plot | `/stitch smart`; `/plot *_Iq.dat --save x.png` |

Empty beam is mandatory (it carries the beam centre); missing trans/bkg is only a
warning. Changing a row field or config param auto-marks `done` rows `modified`,
so they re-reduce without `--force`.

### Absolute scale (porsil) — every configuration, from 1.0

Each configuration gets **its own** scale factor fitted from **its own** porsil
run. "Use 8m12a as the reference configuration" names the **stitch target**, not
the only config to calibrate — never calibrate one config and let the stitch
drag the others onto it; that hides a mismatch instead of fixing it.

```
/set config <cfg1> standardabsolutescale 1.0      # one line per config — mandatory
/set config <cfg2> standardabsolutescale 1.0
/reduce --sample porsil
/calibrate porsil_<cfg1>_Iq.dat --applynow        # one line per config
/calibrate porsil_<cfg2>_Iq.dat --applynow
/reduce all                                        # samples, with the new scales
/calibrate porsil_<cfg1>_Iq.dat                    # verify: each must print ~1.0
/calibrate porsil_<cfg2>_Iq.dat
```

**Why the reset to 1.0 matters:** `/matchruns` applies presets, and some presets
ship a stale non-unit scale (`conf_8m_12a_60hz.json` and `conf_4m_10a_60hz.json`
carry `StandardAbsoluteScale: 0.1916573`). Porsil reduced at that scale makes
`/calibrate` return a factor *relative* to it, and `--applynow` **replaces** the
scale rather than compounding it — the data come out wrong by exactly the preset
value (IPTS-38269: applied 10.65, correct was 10.65 × 0.1917 = 2.04). Check
`/show config <cfg>` before reducing porsil if in doubt.

**Q window:** the default `[0.01, 0.03]` is fine when the config's data reach
below ~0.015 Å⁻¹ (8m12a, 4m2.5a). Before trusting a factor, confirm it is stable
(±2 %) across a neighbouring window (`--qmin/--qmax`); a 2.5 m/2.5 Å curve
needs a higher window (see Gotchas).

**Recalibrate whenever the porsil curve changes.** A new mask, Q binning,
inelastic-incoherent fit or wavelength cut changes the reduced porsil, so that
config's factor is stale. Redo that config alone from 1.0 (porsil's row number
from `/show table --name porsil`):

```
/set config <cfg> <param> <value>
/set config <cfg> standardabsolutescale 1.0
/reduce <porsil row>
/calibrate porsil_<cfg>_Iq.dat --applynow
/reduce <that config's rows>
/calibrate porsil_<cfg>_Iq.dat          # ~1.0
```

Factors moved only 0.1–0.2 % for mask/binning/incoh changes on IPTS-38269, but
the procedure is what guarantees it.

**The check is porsil's own stitch factor ≈1** (configs agree on the standard).
Sample stitch factors may legitimately differ from 1 and depend on the overlap
window: steep curves, different Q resolution per config, an incoherent fit on
one config only, few points. On IPTS-38269 porsil stitched at 1.00 while samples
needed 0.65–1.5. Report the sample factors; do not "fix" calibration over them.

### Stitching

```
/stitch build
/stitch set all target <ref cfg>             # the "reference configuration"
/stitch set all overlap <q1> <q2>            # a user-given window; or `overlap auto`
/stitch run
```

All in **one** batch (the table does not persist). Output:
`merged_<sample>_<cfg1>_<cfg2>_Iq.txt` in the session output dir.

- **Implementation:** a native port of `drtsans.stitch.stitch_profiles`
  (`services/merge_service.py`), not drtsans itself. Verified identical to drtsans
  to 5e-7 on IPTS-38269 — say so if asked. Differences: overlap edges inclusive
  (`>=`/`<=` vs strict), and the merged file has **no dQ column** (Q, I, dI only).
- **Factor:** `sum(I_target) / sum(I_other interpolated)` over the **target's** Q
  points inside the window. Count points on both curves before reporting:
  the target's points drive the sum, but the other curve may have only 2 points
  there and is linearly interpolated between them.
- **Report the applied factor** (that ratio of sums), not a median of point
  ratios — they differ by several %.
- **Sparse low-Q points on a short-λ config:** with linear bins a 4m2.5a curve
  has a point only every ~0.0045 Å⁻¹, so a low-Q window holds 2 points.
  `/set config <cfg> qbintype log` (keeps `numqbins`) gives 4–9 there, and
  starts lower (0.0094 vs 0.0122 Å⁻¹). Recalibrate that config afterwards.
- **`/export script` writes reduction only — no stitch step.** Say so when
  handing the script over, or add a `drtsans.stitch.stitch_profiles` block.

Config parameter names for `/set config <cfg> <name> <value>`: `maskfilename`,
`numqbins`, `qbintype` (linear|log), `logqbinsperdecade`, `fitinelasticincoh`,
`incohfit_qmin`, `incohfit_qmax`, `standardabsolutescale`.

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
| `/set --sample <pat>` hit rows it should not have | A trailing `*` over-matches when sample names are prefixes of each other — `L62_0*` also catches `L62_0p06`, `L62_0p12`, `L62_0p18`, `L62_0p24`. Check with `/show table --sample <pat>` before any bulk `/set` |
| Script batch dies partway through | `reduceNow()` raises `SystemExit` on a failed run — wrap it in try/except, see `references/script-mode.md` |
| Porsil after `--applynow` re-checks far from 1.0 (e.g. 0.19 or 5×) | Porsil was reduced with a preset's non-unit scale, and `--applynow` replaced it. Set the config to 1.0, re-reduce porsil, recalibrate (see *Absolute scale*) |
| **Porsil** differs between configs by a large factor before stitching | Not every config was calibrated from its own porsil (or one went stale after a mask/binning change). Calibrate each; the stitch is not a substitute. Samples differing by 10–50 % while porsil agrees is a different matter — see *Stitching* |
| `/reduce all` re-reduced rows already `done` | Seen in practice — to redo only some rows, use `/reduce <range>` (e.g. `/reduce 13-24`) |
| `/stitch run` → "No stitch table" | The stitch table does not survive between `eqcli.py` invocations — send `/stitch build`, `/stitch set …`, `/stitch run` in **one** batch |
| `/load ipts` → "ONCat session expired"; `eqsanscli-oncat-login` not on PATH | Run the device flow in the background and give the user the printed URL: `cd /SNS/EQSANS/shared/script/eqsanstools-cli && env -u PYTHONHOME PYTHONNOUSERSITE=1 PYTHONPATH=$PWD/src EQSANSCLI_ROOT=$PWD .venv/bin/python -u -m eqsanscli.oncat_login_cli > <log> 2>&1` (`run_in_background`), then read the URL from the log. Token caches in `~/.eqsanscli/` |
| Calibration returns NaN or a handful of points | The Q window is outside that config's measured range — `/calibrate`'s default `[0.01, 0.03]` is below a 2.5 m/2.5 Å curve (starts ~0.023) |
| Sample paired with the wrong transmission | A sample usually has one transmission run **per configuration** — build one mapping per config, not one global |
| Transmissions titled by slot, not sample (`T-s1` vs `S-L62_0`) — no row matches | **Fix the titles, not the rows:** `/retitle s1 L62_0` … then `/matchruns`. One `/retitle` corrects that slot in *every* config (`T-s1` at 4 m and at 2.5 m), and `/matchruns` pairs by title, so each config gets its own transmission. Whole-word by default, so `s1` never touches `s10`. Patching rows with `/set` instead is what produces the mess below — and the next `/matchruns` discards it |
