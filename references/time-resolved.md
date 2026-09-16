# Time-resolved (time-sliced) reduction

drtsans slices a run into equal time bins and reduces **each slice as a full,
independent reduction** — one `_Iq.dat` / `_Iqxqy.dat` / `_processed.nxs` /
`.png` set per slice, named
`{sample}_{config}_{slice}_frame_{0,1}_Iq.dat`. A 1-hour run at 60 s is 60
slices; at 5 s it is 720. Compute and disk scale with the slice count.

Before launching, always:

1. Work out the slice count (`duration ÷ interval`) and tell the user. `/reduce`
   prints `⏱ Time-slicing <cfg>: ~N slices/run (Ds ÷ Is)` — relay it, and confirm
   with the user above ~200 slices/run.
2. Give each sliced sample its own output folder (below), or hundreds of files
   from different samples land in one directory.
3. Keep static rows on the unsliced config — slicing is a **config** property.

Parameters (config-level): `usetimeslice` (bool), `timesliceinterval` (seconds),
`timesliceoffset`, `timesliceperiod`, plus the log-slicing pair `uselogslice` /
`logslicename` / `logsliceinterval`.

---

## Playbook 1 — clone a config, slice it, reduce to per-sample folders

The request shape: *"load session yyy; clone `4m2.5a30hz` as `4m2.5a30hztr`;
enable time slicing at 60 s; apply it to the a10b10 / a20a0 / a20d2o / a5b5 runs;
reduce each into its own folder named after the sample."*

Before starting, settle one ambiguity with the user if it exists: a name fragment
like `a10b10` also matches variants such as `a10b10T40-1`. Say which rows you
matched (list them) rather than assuming silently.

**Step 1 — load and look.**

```bash
EQ="python3 ~/.claude/skills/eqsans-reduce/scripts/eqcli.py -d /SNS/EQSANS/IPTS-38151/shared"
$EQ "/session load yyy" "/show ipts" "/config list" "/show table"
```

**Step 2 — clone the config and turn on slicing.** `<dst>` must contain the
source's physics id (`4m2.5a30hz` ✓). The clone inherits every parameter —
presets, mask, cycle calibration files, absolute scale — so only slicing differs.

```bash
$EQ "/config clone 4m2.5a30hz 4m2.5a30hztr" \
    "/set config 4m2.5a30hztr usetimeslice true" \
    "/set config 4m2.5a30hztr timesliceinterval 60" \
    "/show config 4m2.5a30hztr"
```

Check in `/show config` that `usetimeslice=True`, `timesliceinterval=60`, and
that the physics parameters still match the original (`/compare 4m2.5a30hz
4m2.5a30hztr` shows the diff — it should be the slicing keys only).

**Step 3 — build the exact row list, then assign config + folder per row.**
There is no `{sample}` token for `outputdir`, so generate one `/set` pair per
row. Generating from the live table (rather than typing indices) keeps them
aligned and reviewable:

```bash
DIR=/SNS/EQSANS/IPTS-38151/shared
BASE=$DIR/timeseries
python3 ~/.claude/skills/eqsans-reduce/scripts/eqcli.py -d $DIR --json "/show table" 2>/dev/null \
  | python3 -c "
import json, sys
rows = []
for ln in sys.stdin:
    d = (json.loads(ln).get('data') or {})
    if d.get('type') == 'working_table':
        rows = d['rows']
pats = ('a10b10', 'a20a0', 'a20d2o', 'a5b5')
for r in rows:
    s = r['Sample']
    if any(p in s.lower() for p in pats):
        print('/set %s cfg 4m2.5a30hztr' % r['Idx'])
        print('/set %s outputdir $BASE/%s' % (r['Idx'], s))
" > cmds.txt   # a scratch file
head -40 cmds.txt        # review before sending
$EQ --stdin < cmds.txt
```

(Quick alternative when the glob is unambiguous: `/set --sample a10b10* cfg
4m2.5a30hztr` — but the folders still need one `/set <row> outputdir` each.)

A row only accepts a config with matching physics, so a `/set … cfg` on a row of
a different distance/wavelength fails loudly — good, that is the guard rail.

**Check for duplicate sample names before sending.** Two rows can carry the same
sample name (a repeat measurement — IPTS-38151 has two `a10b10T40-3` rows). They
would share one folder *and* one output filename, so the second silently
overwrites the first. Flag it to the user and disambiguate — rename a row
(`/set <idx> sample <newname>`) or give it its own folder suffix.

**Step 4 — verify, then reduce in the background.**

```bash
$EQ "/show table --name a10b10" "/config rows 4m2.5a30hztr"
```

`/config rows` must list exactly the rows you intended. Then reduce those rows
(run in background, log to a file, poll it):

```bash
$EQ "/reduce 45-49" > reduce_tr.log 2>&1      # run_in_background: true
tail -30 reduce_tr.log
```

The first lines carry the `⏱` slice estimate; progress arrives as
`⏳ <sample>: slice N/60 (P%)`. drtsans's own `.out`/`.err` logs stream live into
each row's output folder — `tail -f <folder>/<sample>_<config>.out`.

**Step 5 — report.** Per sample: folder, number of slices written, any `note` or
error. Files in a per-row folder are not auto-discovered, so plot explicitly:
`/plot $BASE/a10b10-1/*_Iq.dat --save a10b10-1_slices.png`.

---

## Playbook 2 — same thing from a script

When the user points at a `.py` reduction script instead of a session, see
`script-mode.md` — time slicing there is three attributes on the `EQVar`
(`_usetimeslice`, `_timesliceinterval`, `_outputdir` per sample) and no cloning
is involved.

---

## Notes

- Changing `usetimeslice`/`timesliceinterval` marks `done` rows of that config
  `modified`, so they re-reduce without `--force`. Changing only `outputdir`
  deliberately does **not** — moving output does not invalidate the science, and
  an hour-long sliced run must not silently re-run.
- A sliced row that runs to completion and then exits non-zero on a Qt/X11
  teardown is reported `done` with a `note`. That is not a failure; do not
  re-reduce it.
- Transmission is measured once for the whole run — every slice of a sample uses
  the same transmission, background and empty beam as the static reduction.
- Stitching across configs is not meaningful slice-by-slice unless both configs
  were sliced on the same clock; treat stitching of sliced data as an explicit
  user request, not a default step.
