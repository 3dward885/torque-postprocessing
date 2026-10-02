# Torque Postprocessing 1.1

Local Python desktop application for torque magnetometry. The Tkinter GUI and
command-line processor share the same numerical core. Version 1.1 adds optional,
independent baseline review for each acquired signal pass.

## Launch on Windows

The environment in this local repository is installed and tested. Double-click
**Launch_GUI.cmd**, or run this from the repository folder in PowerShell:

```powershell
.\.venv\Scripts\python.exe app.py
```

For a fresh extracted copy, run **Setup_Windows.cmd** once first. It finds the
bundled or installed Python 3.12 with Tkinter, creates a local environment (an
isolated folder of Python dependencies), and installs the pinned requirements.
The ZIP excludes that machine-specific environment. No server is needed.

Tested here: Windows 11, Python 3.12.14, NumPy 2.3.5, Matplotlib 3.10.8, Tk 8.6.12.
Other operating systems have not been tested. Arial Regular must be installed
for compliant scientific exports; the app reports an unavailable font explicitly.

## Process and review

1. Add a supported raw DAT file. Select its profile, ordinary centering and
   optional molar settings in **File settings**. New files start with midrange
   centering, torque-only output and **Interactive baseline adjustment** unchecked.
2. **Process all**, select an acquired signal pass, then enable **Interactive
   baseline adjustment** for that input and click **Review baseline**.
3. A new review starts at midrange over all retained samples. Viewing it does
   not accept a setting: export still uses that pass's ordinary mean/midrange
   policy until **Apply**.
4. Drag the baseline in the uncentered view or enter Delta in N m. Positive
   Delta moves corrected values downward. The corrected view has a fixed zero.
   Pan/zoom leaves the baseline unchanged; zoom never changes the samples used.
5. **Apply** commits only this pass. **Cancel** discards its draft. **Reset**
   creates a zero-Delta draft that still needs Apply. **Remove override**
   restores its ordinary policy. Apply or Cancel before leaving a dirty editor,
   disabling the feature, saving/loading, processing or exporting.
6. Unchecking retains accepted records but uses ordinary centering. Rechecking
   validates them. Stale active settings visibly block export until reviewed
   and applied, removed, or disabled. Each pass shows its effective export mode.
7. Save configuration; **Export ready** writes committed data to a new run
   directory. Preview export includes baseline_uncentered and baseline_corrected.
   The independent treated-reference comparison is available after data export.

For each pass, u is the original background-subtracted vector. The editor uses
c_mid = (min(u)+max(u))/2, c_final = c_mid + Delta, and u-c_final exactly once.
Neither dragging nor Apply rereads the input or refits the background. Repeated
processing never accumulates shifts. These are user-provided centering choices,
not measured calibration constants or fitted drift parameters.

## Scientific contract

The recipe is unchanged: original torque tokens are rounded to six significant
digits using Decimal semantics; an unweighted degree-six background polynomial
is fitted against nominal angles on [0,200] degrees; the evaluated background is
subtracted; centering follows; D is serialized with binary64 .8g; E is the exact
Decimal product of **exported D** and the explicit factor. D remains N m and E
is labelled N m/mol. No extra rounding, smoothing, synthetic points or rescaling.

Both existing profiles support the feature. Supported inputs remain the strict
32-column instrument CSV schema (14-32 recorded columns) and documented
four-column TSV, with their existing coordinate tolerances and acquisition rules.
The fractional profile preserves supported missing samples and monotonic changing
fields. Previous requires complete signal grids and stable fields. One input is
one acquisition/rotation; same-temperature backgrounds stay within that input,
including backgrounds acquired afterward. Multiple candidates require a choice.
This is not an arbitrary-file parser. Details remain in README.txt and profiles/.

Scientific figures use Arial Regular, 8 x 6 inches (background fits 8 x 6.1),
22 pt labels, 18 pt ticks, 12 pt legends, black left/bottom axes and outward ticks,
without grids/titles. Background samples are filled black 7.5 pt circles; the
stored polynomial is a solid red 0.5 pt curve. The baseline is a control, not a fit.
The old Gill Sans requirement is superseded; historical figures are unchanged.

## Save and replay accepted settings

The optional baseline_review block has schema_version 1, enabled, and independent
overrides keyed by pass ID. Old configurations without it preserve old behavior.
Each record binds the source SHA-256, profile, acquisition identity and source
rows/angles, selected background, upstream numerical recipe/environment and
little-endian binary64 u digest. Temperature/field labels alone are not identities.
The accepted offset is lossless binary64 hexadecimal; readable round-trip decimal
values are checked against it. Unknown feature versions and pass keys are errors.

Changing background/data/upstream arithmetic invalidates affected records.
Changing zoom/font or ordinary policy does not. A molar-factor change leaves the
N m baseline valid and recomputes E. Different numerical/platform environments
can require explicit reacceptance. Provenance and the existing row ledger record
the ordinary and effective policies, offset, origin and acceptance record.
Malformed inactive values remain inactive and are identified; they cannot become
active without validation.

The committed example is an **automated software test choice**, not a physical
correction for the sample: P003 Delta = 1.2345678901234567e-9 N m, ordinary mean,
explicit reference multiplier 1575.45 mol^-1. Run:

```powershell
.\.venv\Scripts\python.exe cli.py process --session examples/baseline_review_accepted.json --output runs
.\.venv\Scripts\python.exe cli.py process --raw "your_raw.dat" --profile fractional --output runs
```

No GUI or treated reference is needed for processing. Each export includes DAT,
settings, provenance, original-token row ledger, raw snapshot and file hashes.
Completed directories are published atomically (only after every file succeeds).
Existing run names and plot paths are rejected instead of overwritten.

## Observed validation and reproducible commands

A-I passed. All six ordinary outputs match version 1.0 byte for byte. Accepted
Delta=0 reproduces all 3519 midrange rows exactly in D and E. All 4869 raw rows
remain accounted for. Manual shifts are tested against the specified floating
point bound, never against historical reference equality.

| Historical reference | Policy | Exact D / exact E rows |
| --- | --- | --- |
| Ho2thd4Pc Rot1 | Midrange | 818 / 818 of 818 |
| Ho2thd4Pc Rot2 | Midrange | 938 / 938 of 938 |
| Previous Rot2 | Midrange | 820 / 820 of 820 |
| Previous Rot1 | Mean | 615 / 615 of 943 |
| Previous Rot1 | Midrange | 328 / 328 of 943 |
| Previous Rot1 | Explicit diagnostic choices | 943 / 943 of 943 |

26 unit tests passed. The actual Windows GUI completed load/process/review,
drag/numeric input, pan/zoom, invalid-input/state checks, save/load and export.
GUI and CLI DAT files match byte for byte. The CLI also passed with reference
reads denied; comparison ran separately afterward. One live editor screenshot
and three inspected vector-PDF/300-dpi-PNG figure pairs are included. After the
request to free the PC, all further GUI tests used withdrawn windows and no
desktop input. These are automated widget/event tests and agent visual
inspection, not human manual acceptance.

From this directory, choose unused output folders for repeat runs:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tests/baseline_regression.py --output validation/replay_baseline
.\.venv\Scripts\python.exe tests/baseline_gui.py --background --output validation/replay_gui
.\.venv\Scripts\python.exe -m pip install -r requirements-validation.txt
.\.venv\Scripts\python.exe tests/figures.py --session examples/baseline_review_accepted.json --output validation/replay_figures
```

Omit --background only when you want visible GUI testing; --hold keeps that test
window open. The regression requires immutable evidence at
evidence/Torque_Ho2thd4Pc_pipeline_comparison_v1.2 and the six pre-change
validation/regression/<case_policy>/{settings.json,treated.dat} fixtures.
These are included in the v1.1 ZIP, but remain local and Git-ignored.
The evidence ZIP SHA-256 is
71b5c9bd246648fd52ad6cdaf48626ce6b9051facbbb31bea35347fcdffdc605.
Do not run the archived validate_compare.py main or historical package builder
against the edited application. Current packaging: tools/package_baseline_release.py.

See BASELINE_IMPLEMENTATION_REPORT_v1.1.txt and validation/baseline_v1.1.
The current compact state remains Torque_GUI_project_state_v1.0.json for
continuity; its version field is 1.1. BUILD_REPORT.txt and old validation folders
describe the historical v1.0 release.

## Remaining scientific limits and Git workflow

The autonomous previous-Rot1 centering selector remains unresolved; diagnostic
choices are reference-selected. Factors 911.63 and 1575.45 have verified
arithmetic but unverified physical normalization. Exact reproduction does not
establish a unique historical algorithm or transferability to new samples.
Manual offsets do not resolve those scientific questions.

Changes are in the existing local repository, based on commit
266ff17d1b3d5c18b97d924b204d2264ff875082. No commit or push was performed for this
feature. Review and commit through GitHub Desktop, then push when ready.
Source and compact documentation are tracked; raw/evidence/generated output and
the Python environment remain local. The downloadable v1.1 ZIP includes the
immutable fixtures needed for replay. Original inputs and archives are unchanged.
