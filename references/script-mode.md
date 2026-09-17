# Script-mode reduction (EQVar + drtsans)

The classic path: a Python script builds one `EQVar` per reduced curve and calls
`reduceNow(eq)`. The wrapper lives at
`/SNS/EQSANS/shared/script/eqsanstools/eqsans_drtsans_script.py`; templates and
worked examples are in `/SNS/EQSANS/shared/script/eqsanstools-cli/examples/`
(`reduce_template.py`, `ipts*_reduce.py`).

Run it with:

```bash
cd /SNS/EQSANS/IPTS-<N>/shared
drtsans reduce_xxx.py            # --qa / --dev builds exist; use plain drtsans unless asked
```

Long jobs: run in the background with output to a log (`… > reduce.log 2>&1`) and
poll the log. Each reduction also writes `<filename>.out`/`.err` into its own
output directory.

## How an attribute becomes a drtsans parameter

`updateJsonFile()` loads the template `eqsans_reduction.json`, then for **every
key under `configuration`** copies `eqvar._<key.lower()>` if that attribute
exists (printing a warning if it does not). So the JSON key `useTimeSlice` is
driven by `eq._usetimeslice`, `timeSliceInterval` by `eq._timesliceinterval`,
`outputDir` by `eq._outputdir`, and so on — the JSON schema is the source of
truth for spelling. Runs, thickness and transmissions are mapped explicitly
(`sample`, `background`, `emptyTransmission`, `beamCenter`).

Most-used attributes:

| Attribute | Meaning |
|---|---|
| `_samscatt`, `_samtrans` | sample scattering / transmission run |
| `_bkgscatt`, `_bkgtrans` | background scattering / transmission run |
| `_empty` | empty beam — transmission reference **and** beam centre (mandatory) |
| `_beamcenter` | separate beam-centre run, if measured apart from `_empty` |
| `_ipts`, `_thickness`, `_filename` | experiment, cm, output name base |
| `_outputdir` | output folder (created if missing; also sets `dataDirectories`) |
| `_standardabsolutescale` | absolute scale from the porsil calibration |
| `_maskfilename`, `_sensitivityfilename`, `_darkfilename`, `_beamfluxfilename` | mask + cycle calibration files |
| `_sampleoffset`, `_detectoroffset`, `_scalecomponents` | geometry, per-panel scale |
| `_numqbins`, `_numqxqybins`, `_qbintype`, `_wavelengthstep`, `_cuttofmin/max` | binning |
| `_usetimeslice`, `_timesliceinterval`, `_timesliceoffset`, `_timesliceperiod` | time slicing |
| `_uselogslice`, `_logslicename`, `_logsliceinterval` | slicing on a sample-environment log |
| `_filterbytimestart` / `_filterbytimestop` | reduce only a time window of the run |
| `_fitinelasticincoh`, `_selectminincoh`, `_incohfit_qmin/qmax` | inelastic/incoherent correction |

A transmission field holding a number > 1 is read as a run number, ≤ 1 as a fixed
transmission value, and a comma-separated string as multiple runs.

## Recipe — time-slice a subset of samples into per-sample folders

Request shape: *"based on `reduce.py`, modify it so these samples are reduced
with time slicing at 60 s, each sample into
`/SNS/EQSANS/IPTS-38151/shared/timeseries/<sample>/`."*

1. **Copy, never edit in place** (unless the user says to):
   `cp reduce.py reduce_timeslice.py`. Say which file you wrote.
2. **Trim the parallel arrays to the requested samples, keeping every array
   index-aligned** — `samscatt`, `samtrans`, `bkgscatt`, `bkgtrans`, `emptybeam`,
   `sample_thick`, `sample_names` are indexed by the same `i`. Filter them
   together (see the snippet below) instead of hand-editing seven long literals;
   a mis-shifted array silently reduces the wrong pairing.
3. **Turn on slicing and per-sample output** inside the loop.
4. Keep everything else — scale factor, mask, cycle files, binning — byte for
   byte, so the sliced result is comparable to the static one.

```python
# ---- select the samples to time-slice (keeps all arrays aligned) ----
WANTED = ('a10b10', 'a20a0', 'a20d2o', 'a5b5')
keep = [i for i, n in enumerate(sample_names) if any(w in n.lower() for w in WANTED)]
samscatt, samtrans = [samscatt[i] for i in keep], [samtrans[i] for i in keep]
bkgscatt, bkgtrans = [bkgscatt[i] for i in keep], [bkgtrans[i] for i in keep]
emptybeam = [emptybeam[i] for i in keep]
sample_thick = [sample_thick[i] for i in keep]
sample_names = [sample_names[i] for i in keep]
print('time-slicing %d samples: %s' % (len(keep), ', '.join(sample_names)))

timeseries_dir = '/SNS/EQSANS/IPTS-38151/shared/timeseries'

for i in range(len(samscatt)):
    eq = EQVar()
    eq._outputdir = os.path.join(timeseries_dir, sample_names[i])   # own folder per sample
    os.makedirs(eq._outputdir, exist_ok=True)
    ...                                                              # unchanged parameters
    eq._usetimeslice = True
    eq._timesliceinterval = 60
    ...
    reduceNow(eq)
```

Print the sample list the filter selected and show it to the user before running
— a fragment like `a10b10` also matches `a10b10T40-1`. Watch for **repeated
sample names** (two rows measured under one name): with a per-sample folder they
would share a filename and overwrite each other — give those a distinct
`_filename`/folder suffix.

5. **Sanity-check the slice count** before launching: slices ≈ run duration ÷ 60.
   Run durations come from the catalog (`/show catalog`, or the `oncat-catalog`
   skill). Tell the user the total (samples × slices ≈ full reductions).
6. Run it, then report per sample: folder, slice files written
   (`ls <folder>/*_Iq.dat | wc -l`), and anything in `.err`.

## Absolute scale in script mode

There is no `/calibrate` here — reproduce it in the script:

1. Reduce the porsil standard with `eq._standardabsolutescale = 1.0`, once per
   configuration.
2. `scale = mean(I_ref(Q) / I_meas(Q))` over a Q window, evaluated at the
   *reference* Q points with the measured curve interpolated onto them
   (`np.interp(..., left=np.nan, right=np.nan)`, then keep finite and positive).
3. Feed the number back as `_standardabsolutescale` for that configuration.

Reference standards (NG3 is the default), 4 columns `Q I dI dQ`, `#`-commented,
read with `np.loadtxt(f, comments='#')`:

```
/SNS/EQSANS/shared/script/eqsanstools-cli/absscale_reference/NG3_B1_1413_4col.dat
/SNS/EQSANS/shared/script/eqsanstools-cli/absscale_reference/NG7_ORNL_B1_All_4col.dat
```

NG3 spans Q = 0.0038–0.44, so it covers every EQSANS configuration.

**The Q window is per configuration.** `/calibrate`'s default `[0.01, 0.03]`
only works where the measured curve reaches that low. A 2.5 m/2.5 Å curve starts
at Q ≈ 0.023, so the default window sits almost entirely below its range and the
interpolation returns NaN. Pick a window inside the measured range, and say
which one you used:

| Configuration | measured Q (1/A) | window that works |
|---|---|---|
| 4 m / 10 A | ~0.008 – 0.12 | 0.01 – 0.03 (the default) |
| 2.5 m / 2.5 A | ~0.023 – 0.50 | 0.03 – 0.10 |

Report the spread of the ratio (`np.std`) next to the mean — flat (≲2 % of the
scale) says the window is right, tilted says it is not. Plot the reference
against `I_meas × scale` with the window shaded and write the number to a text
file the user can copy from; `matplotlib.use('Agg')` before `pyplot`, there is
no X11 on the analysis nodes.

Two configurations give two different scale factors (13 % apart in IPTS-36552) —
normal, they have different sensitivity and flux. Keep one constant per
configuration in a marked block at the top of the reduction script, so a new
value can be typed in without hunting for it.

## Recipe — a whole experiment, built from the catalog

Request shape: *"make a script to reduce IPTS-36552, path length 1 mm, with
stitching, into `<shared>/output`."*

1. **Read the session autosave instead of launching the CLI.**
   `<ipts shared>/.eqsanscli/sessions/_autosave.json` is plain JSON:
   `catalog_data` (every run with `title`, `detector_distance`, `wavelength`,
   `frequency`, `duration`, `run_class`) and `configurations` /
   `instrument_provenance` (cycle files, sample and detector offsets,
   `scaleComponents`, per-config presets that `/matchruns` already resolved).
   Copy those constants into the script verbatim — it then agrees with the
   session instead of guessing at cycle files. No session yet → `/load ipts <N>`
   once, or the `oncat-catalog` skill.
2. **Derive the run table from catalog titles, not from the session table.** A
   table that has been hand-`/set` may carry half-finished edits; titles are what
   the instrument recorded.
3. **One transmission dict per configuration.** Scattering runs come in blocks
   per configuration and the same sample usually has a transmission run in
   *each* — in IPTS-36552 T-s1…T-s11 exist at both 4 m/10 Å (181470–181480) and
   2.5 m/2.5 Å (181494–181504). A single mapping silently pairs every high-Q
   sample with a low-Q transmission. When the user hands you a
   sample → transmission mapping, apply it by index to both lists, or ask which
   configuration it is for.
4. **Placeholder transmission titles are common** (`T-s1`, `T-sample3`). The
   fix belongs in the session, not the script: `/retitle s1 L62_0` … then
   `/matchruns` — one `/retitle` corrects the slot in every configuration and
   `/matchruns` re-pairs by title. Only build the mapping into the script when
   there is no session to fix; then put it in the docstring so the next reader
   knows why `T-s3` is `L62_0p12`.
5. **Label repeated and partial blocks.** A temperature series often repeats a
   block (40 C and 55 C measured twice) and ends mid-block. Same label → same
   output filename → silent overwrite. Suffix repeats (`_rep2`); where one
   configuration is missing, reduce the one that exists and skip the stitch.
6. **Validate the generated table against the catalog before running:**

```python
assert len(set(labels)) == len(labels)                 # no overwrites
runs = [r for e in table for r in (e.scatt1, e.scatt2) if r]
assert len(set(runs)) == len(runs)                     # no run used twice
assert not (catalog_sample_runs - set(runs))           # nothing dropped
for e in table:                                        # right config column
    assert cat[e.scatt1]['detector_distance'] == 4.0
```

   Print the entry count and a few rows for the user before launching. The
   existing warning about index-aligned arrays is only enforceable this way.
7. **Smoke-test one entry** (`drtsans <script>.py 0 1`) before the full batch,
   and check the Q range of each config's `_Iq.dat` — that also confirms the
   stitch overlap window lies inside both.

## Notes

- **`reduceNow()` raises `SystemExit` when a run fails** — one bad run ends a
  132-entry loop hours in. Wrap it:

  ```python
  def safe_reduce(eq):
      try:
          reduceNow(eq)
          return True
      except (SystemExit, Exception) as err:
          print('[!] reduction FAILED for %s : %s' % (eq._filename, err))
          return False
  ```
- **Budget before launching a batch**: ~60 s per single-config reduction and
  ~95 MB of output per reduction (the `_processed.nxs` dominates) on the 2026
  analysis nodes. A 132-entry two-configuration run with stitching is ~4.7 h and
  ~25 GB. Quote both to the user before starting.
- `EQVar()` loads `Default.json` from `/SNS/EQSANS/shared/script/eqsanstools/`,
  so every JSON key already has a value — including `maskFileName`, which points
  at a 2023A mask. Recent cycles ship no mask of their own and eqsanscli does not
  set one either; leave it alone unless the user has a mask.
- `_scalecomponents` is special-cased by `updateJsonFile` (it becomes
  `configuration.scaleComponents.detector1`); every other attribute is a plain
  lowercased copy of its JSON key.
- `reduction_confirm(<ipts>)` at the end registers the reduction as complete —
  keep it in a production run, drop it for a test.
- `_filename` sets the output base name; drtsans appends `_frame_0`/`_frame_1`
  for 30 Hz frame skipping and a slice index when slicing
  (`{name}_{slice}_frame_{0,1}_Iq.dat`).
- The first row of a table-exported script is often the background sample itself
  (`bkgscatt`/`bkgtrans` empty) — it must not be background-subtracted against
  itself. Preserve that when filtering.
- `/export script -o <file>` (eqsanscli) regenerates such a script from a
  session's table; `--like <example.py>` keeps an existing script's style.
