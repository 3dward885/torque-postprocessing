# Torque Postprocessing 1.2

Active checkout: this folder under
`D:\OneDrive - Florida State University\FSU\Research\Instrument Characterizations\Torque Magnetometry\Codex Torque\torque-postprocessing`.
Use it for future changes and launches. Copies under Astra/ and FSU/Github are
historical. The user manages commits and pushes through GitHub Desktop.

## Start

Double-click **Launch_GUI.cmd**. From PowerShell opened in this folder:

```powershell
.\.venv\Scripts\python.exe app.py
```

To open the supplied file with its confirmed setpoints and example 0–200° range:

```powershell
.\.venv\Scripts\python.exe app.py --session examples\Ho2sq3_0_to_200.json
```

For a fresh checkout, run **Setup_Windows.cmd** first. It creates a local Python
environment (the `.venv` directory) and installs `requirements.txt`. Python 3.12
with Tkinter is required. No server or browser is involved.

Tested: Windows 11 build 26300, Python 3.12.14, NumPy 2.3.5, Matplotlib 3.10.8,
Tk 8.6.12. Other platforms have not been tested.

## Process a file

1. **Open data…** loads the raw DAT and shows a raw preview.
2. In **Acquisition settings…**, enter the experimental temperature setpoints,
   separated by commas. These are experiment settings, not values embedded in
   the program. Multiple scans can share a setpoint. A scan is assigned
   automatically only when all its temperatures match exactly one supplied
   setpoint within the allowed deviation. Use a selected-scan setpoint to
   resolve ambiguity. The current temperature deviation is 0.2 K; it is editable.
3. Optionally use **Angle range…**. Blank bounds retain all angles. Bounds such
   as 0 and 200 select the inclusive interval in the pipeline's nominal-angle
   coordinates. This interval applies to **background fitting, zero centering,
   processed previews and treated output**. Original measured angles remain in
   the row ledger. No points are interpolated or fabricated.
4. Check the selected background, then click **Subtract background**. Backgrounds
   must come from the same input and experimental temperature. A background
   acquired afterward is supported. Multiple candidates require a selection.
   Background coverage problems appear on the affected scans; other scans can
   still be reviewed. **Allow background extrapolation** is an explicit choice
   for the selected signal/background pair.
5. **Center zero…** opens the selected signal scan. Drag the baseline or enter an
   offset from its midrange. **Apply** saves that scan's adjustment; **Cancel**
   discards the draft; **Reset** creates a zero-offset draft requiring Apply;
   **Remove override** restores ordinary centering. Dirty drafts must be applied
   or cancelled before navigation, settings changes or saving.
6. **Save treated data…** opens a normal Save As dialog. Output has four columns:
   temperature (K), magnetic field (T), sample position (deg), torque (N m).
   No molar conversion is performed. A matching `.dat.details` folder contains
   settings, raw snapshot, row ledger, provenance and hashes.

Save/load settings and figure export are in the menus. Files and results are
independent. Settings can be applied to several selected scans using Ctrl/Shift
selection. The scan list reports retained/acquired point counts. To change a
previous explicit per-scan setpoint, enter the replacement for those selected
scans; changing the general setpoint list does not erase explicit assignments.

Existing output files are never overwritten. Unresolved scans and stale active
adjustments block saving; explicit exclusions are available in acquisition
settings and recorded in the ledger.

## What changed scientifically

The previous import failure came from selecting a reference on a fixed 1 K grid.
For the user's 2.5 K setting, 2.49238 K differs by 0.00762 K and passes a 0.2 K
check. The former 2 K reference differed by 0.49238 K. Comparison arithmetic
was not the fault. Temperature targets now come from saved user settings or
explicit metadata; there is no fixed temperature list or fallback rounding.

The instrument schema's `User Temperature` field is not treated as a setpoint.
The supplied Ho2sq3 file has no explicit setpoint metadata. A documented optional
header record `INFO,"t1;t2;...",TEMPERATURE_SETPOINTS_K` can supply setpoints for
other files; explicit user settings take precedence, with conflicts recorded.

The numerical method remains: six-significant-digit Decimal torque tokens;
unweighted degree-six background polynomial on the existing [0,200] scaled
basis; evaluate at retained nominal signal angles; subtract; center once;
serialize torque with binary64 `.8g`. The scaling domain does not restrict
the acquisition's angular span. Angular and field tolerances remain configurable
under More acquisition settings. Measured source tokens are preserved separately
from the nominal coordinates used for fitting and export.

The optional angle interval selects actual rows before fitting and centering.
Thus excluded endpoint artifacts cannot influence the fitted background or
the retained-vector midrange. For retained background-subtracted torque u:
`c_mid = (min(u)+max(u))/2`, `c_final = c_mid + delta`,
`treated torque = u - c_final`. Positive delta shifts corrected torque downward.
This defines the selected data's midrange zero; it is not an independent absolute
torque calibration. No automatic anomaly detector or inferred point removal is used.

A range or upstream-data change requires reprocessing and invalidates affected
accepted offsets. Dragging uses cached immutable data, never rereads/refits, and
does not accumulate shifts. Saved offsets use exact hexadecimal binary64 values
plus checked readable values. Baseline schema 2 adds independent active scan IDs,
so applying one adjustment does not activate another retained inactive setting.
Schema 1 remains readable and undergoes normal binding checks.

Supported raw layouts: the documented 32-column instrument CSV header with
14–32 recorded fields, and the documented four-column TSV in K/Oe/deg/Nm.
The importer is not a universal DAT reader. Automatic scan boundaries follow
angular sweep restarts/reversals; ambiguous short scans require explicit source
row starts. Finite-value, unit, ordering, fit-rank and coverage checks remain.

## Supplied experiment and replay

The user confirmed the Ho2sq3 setpoints
2.5, 5, 10, 25, 50, 100, 150, 200 and 250 K, its nine near-zero-field backgrounds,
and extrapolation of the approximately 100 K background where needed.

- `examples/Ho2sq3_full_range.json`: 1296 signal rows; the explicit extrapolation
  permission applies only to P022–P024.
- `examples/Ho2sq3_0_to_200.json`: 1023 signal rows; no extrapolation is needed.
  All 1754 raw rows remain accounted for, including 368 retained background rows
  and 363 rows outside the selected range.
- `examples/Ho2sq3_manual_demo.json`: an automated software-test offset on P001,
  not a measured calibration or a recommended physical correction.

These JSON files refer to the original local raw file. If you relocate it, change
the session's file path; its SHA-256 identity must still match. Reusable temperature
values are saved as configuration data, not compiled into the processor.

```powershell
.\.venv\Scripts\python.exe cli.py process --session examples\Ho2sq3_0_to_200.json --dat runs\Ho2sq3_0_to_200.dat
.\.venv\Scripts\python.exe cli.py process --session examples\Ho2sq3_full_range.json --output runs
.\.venv\Scripts\python.exe cli.py inspect "path\to\raw.dat"
```

For another experiment, enter its own settings in the GUI and save them for
replay. CLI `--setpoints`, `--temperature-tolerance` and `--angle-range MIN MAX`
also accept explicit settings; `--allow-extrapolation P001` requires a deliberate
choice for the named scan. No treated reference is accessed during processing.

Older configurations retain ordinary centering and recorded baseline choices.
They need explicit temperature assignments if none were saved. Molar fields and
historical header-format choices are removed during version 1.0 migration, with
a recorded notice. New molar CLI options/config fields are rejected. Historical
molar outputs and archival packages remain unchanged.

## Validation

Observed results are in `WORKFLOW_IMPLEMENTATION_REPORT_v1.2.txt` and
`validation/import_workflow_v1.2/`.

- 37 unit/regression tests passed, including tolerance boundaries, arbitrary
  noninteger setpoints, range selection, endpoint-artifact exclusion, independent
  offsets, dirty edits, stale binding checks and output preservation.
- All six frozen historical cases retain exact A–D values: 5405 case rows,
  covering 3519 distinct reference rows and 4869 distinct raw rows.
  Historical D reference counts remain 818/818, 938/938, 820/820, and previous
  Rot1 mean 615/943, midrange 328/943, diagnostic choices 943/943.
- Actual Tk widgets and Matplotlib mouse events passed with all windows
  withdrawn. GUI/CLI DAT exports match byte for byte.
- CLI replay passed with unrelated data/reference reads denied.
- Arial Regular, embedded PDF fonts, 300-dpi PNG dimensions, scientific figure
  styling and clipping checks passed; representative plot images were inspected.
- Full-window visual inspection was not performed, to leave the desktop free.

Reproduce from this folder, using unused output directories:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tests\workflow_regression.py --raw "D:\OneDrive - Florida State University\FSU\Research\Instrument Characterizations\Torque Magnetometry\20260928 Maglab Measurements\[Ho2sq3(OH2)8]\Crystal 1\Raw Data\Ho2sq3_Rot1_00001.dat" --output validation\replay_v12
.\.venv\Scripts\python.exe tests\workflow_gui.py --raw "D:\OneDrive - Florida State University\FSU\Research\Instrument Characterizations\Torque Magnetometry\20260928 Maglab Measurements\[Ho2sq3(OH2)8]\Crystal 1\Raw Data\Ho2sq3_Rot1_00001.dat" --output validation\replay_gui_v12
.\.venv\Scripts\python.exe tests\workflow_isolation.py --session examples\Ho2sq3_manual_demo.json --output validation\replay_isolation_v12
.\.venv\Scripts\python.exe -m pip install -r requirements-validation.txt
.\.venv\Scripts\python.exe tests\figures.py --session examples\Ho2sq3_0_to_200.json --output validation\replay_figures_v12
```

The GUI harness always withdraws its windows and uses no desktop input. The
restricted execution sandbox could not initialize Tcl; the successful GUI checks
ran outside that sandbox with windows still withdrawn. The existing bundled
pypdf 6.10.0 was copied into this project's environment for PDF validation; no
download was needed for this run.

The frozen historical regression requires local
`evidence/Torque_Ho2thd4Pc_pipeline_comparison_v1.2/` and
`validation/regression/<case>/`. Tests never overwrite those fixtures.
Earlier standalone regression/GUI scripts and release reports describe v1.0/1.1;
use the commands above for v1.2.

## Limits

No treated reference was supplied for Ho2sq3, so its new exports are not claimed
to reproduce an independent historical treatment. Previous Rot1 diagnostic
centering choices remain reference-selected; an autonomous selector, historical
algorithm uniqueness and physical molar normalization remain unresolved scientific
questions outside this torque-only release.

This working tree is based on commit
`b9517f489a35dcf3984ea48356fc3d12956e7c5c`; v1.2 changes are uncommitted.
The project-state filename remains `Torque_GUI_project_state_v1.0.json` for
continuity; its current version field is 1.2.

Portable source/evidence archive: Torque_Postprocessing_v1.2_source.zip. Its example sessions point to the included raw fixture; the historical raw/reference files and frozen regression fixtures required by the current tests are included. The workspace continues to use the original raw-file location.
