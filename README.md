# Torque Data Postprocessing 1.4

Active checkout: this folder under
`D:\OneDrive - Florida State University\FSU\Research\Instrument Characterizations\Torque Magnetometry\Codex Torque\torque-postprocessing`.
Use it for future changes and launches. Copies under Astra/ and FSU/Github are
historical. The user manages commits and pushes through GitHub Desktop.

## Install and start on Windows

Run **Torque_Data_Postprocessing_1.4_Setup_x64.exe**, then open
**Torque Data Postprocessing** from the Start menu. Python, Tcl/Tk, NumPy,
Matplotlib and local Help are bundled. No Python installation, setup script or
internet connection is needed for ordinary use.

Setup installs for the current user under
`%LOCALAPPDATA%\Programs\Torque Data Postprocessing` without administrator rights.
A desktop shortcut is optional. Keep the default location or another short path;
Setup checks the Windows DLL path limit. The installer is unsigned because no
publisher signing certificate was supplied; it has no verified-publisher or
SmartScreen approval claim.

To update, close the application yourself and run the new Setup in the same
location. Setup never closes running programs. Uninstall through Windows Settings
> Apps. Your raw data, saved DAT/settings and unrelated files are retained.
Logs and Matplotlib cache remain in
`%LOCALAPPDATA%\Torque Data Postprocessing`; installed files are not used for
writable user data. Save outputs to your chosen folder.

See `WINDOWS_APP.txt` for end-user instructions and
`WINDOWS_INSTALLER_REPORT_v1.4.txt` for observed build/test results.

## Developer source setup and launch

Double-click **Launch_GUI.cmd**. From PowerShell opened in this folder:

```powershell
.\.venv\Scripts\python.exe app.py
```

To open the supplied file with its confirmed setpoints and example 0–200° range:

```powershell
.\.venv\Scripts\python.exe app.py --session examples\Ho2sq3_0_to_200.json
```

For a fresh checkout or newly extracted source ZIP, run **Setup_Windows.cmd**
inside that same folder first. Each copy needs its own `.venv` directory; the
source ZIP deliberately does not include one. Wait for **Setup complete** before
running **Launch_GUI.cmd**. Python 3.12 with Tkinter is required. Setup installs
the pinned `requirements.txt` packages and checks the actual application and Help
using hidden windows. No server or browser is involved.

Setup writes `setup.log`; the launcher writes `launch.log`. If either fails, the
command window displays the error and waits. The launch command window stays open
while the app runs; it can be minimized. Logs are replaced on the next run.
For a background setup check use `Setup_Windows.cmd --no-pause`; the script still
returns its success/failure code. `Launch_GUI.cmd --version` verifies the launcher
without opening the GUI. These startup checks passed for the extracted v1.3 copy.
See `STARTUP_FIX_v1.3.txt` for the repair and copy instructions.

Tested: Windows 11 build 26300, Python 3.12.14, NumPy 2.3.5, Matplotlib 3.10.8,
Tk 8.6.12. Other platforms have not been tested.

## Process a file

1. **Open data…** loads the raw DAT and shows a raw preview.
2. In **Acquisition settings…**, enter the experimental temperature setpoints,
   separated by spaces, commas, or both. These are experiment settings, not values embedded in
   the program. Multiple scans can share a setpoint. A scan is assigned
   automatically only when all its temperatures match exactly one supplied
   setpoint within the allowed deviation. Use **Override selected scan temperature (K)** to
   resolve ambiguity for highlighted scans only. The general list is labelled
   **Temperatures in this file (K)**. A blank override preserves saved assignments. The current temperature deviation is 0.2 K; it is editable.
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
   Subtraction also applies the saved automatic centering policy: midrange by
   default, or mean when explicitly selected.
5. Optionally, **Center zero…** opens the selected signal scan. Drag the baseline or enter an
   offset from its midrange. **Apply** saves that scan's adjustment; **Cancel**
   discards the draft; **Reset** creates a zero-offset draft requiring Apply;
   **Remove override** restores ordinary centering. Dirty drafts must be applied
   or cancelled before navigation, settings changes or saving.
6. **Save treated data…** opens a normal Save As dialog. Output has four columns:
   temperature (K), magnetic field (T), sample position (deg), torque (N m).
   This operation always saves torque in N m. A matching `.dat.details` folder contains
   settings, raw snapshot, row ledger, provenance and hashes.

Save/load settings and figure export are in the menus. Files and results are
independent. Settings can be applied to several selected scans using Ctrl/Shift
selection. The scan list reports retained/acquired point counts. To change a
previous explicit per-scan setpoint, enter the replacement for those selected
scans; changing the general setpoint list does not erase explicit assignments.

Existing output files are never overwritten. Unresolved scans and stale active
adjustments block saving; explicit exclusions are available in acquisition
settings and recorded in the ledger.

## Treated JPEG plots and optional molar DAT

After subtraction/centering, choose **Tools > Export treated plots…**.
Select the processed files, check each rotation number, and choose the quantity:

- **Torque (N m)** exports one JPEG per input file, rotation and temperature.
- **Molar torque (N m/mol)** exports the same plots normalized by sample amount,
  plus a separate four-column `*_molar.dat` for each selected input.

For each sample independently, enter **sample mass (mg) and molar mass (g/mol)**,
or choose **Amount in moles** and enter the known amount. Molar mass alone cannot
normalize torque. The calculation is
`n = mass_mg / (1000 * molar_mass_g_mol)`,
`molar_torque = treated_torque / n`.
Mass must refer to the measured sample, with the same chemical basis as the molar
mass. No quantities, purity corrections or reference multipliers are inferred.

The reciprocal-amount factor is calculated with 50-digit Decimal precision.
Each molar DAT value is the exact Decimal product of that recorded factor and
the already serialized treated N m value; no background fit or zero is recalculated.
The numerical precision is not an experimental uncertainty claim.
JPEGs use the same molar values, converted to binary64 for plotting.

Images are 8 × 6 inches, 2400 × 1800 pixels at 300 dpi, with Arial Regular,
white background and experimental markers only. Text is limited to the
rotation/temperature heading, axis labels/ticks and field legend. No fits,
connecting curves, insets or extra annotations are added.
Background scans are excluded. Repeated scans remain separate samples.
Different input files are kept separate even when they have the same rotation
and temperature, to avoid mixing samples.

Rotation is an editable presentation label, suggested from an explicit Rot/Rotation
filename token. It does not alter scan identities or processing.
Unprocessed/incomplete files cannot be exported; resolve or explicitly exclude
affected scans first. Changing the plot quantity never changes ordinary DAT output,
baseline settings or numerical fingerprints.

Each export creates a new folder containing JPEGs, optional molar DATs and
`plots.details`. Its `plots.json` records sample quantities, factor, source/output
hashes and scan membership; `settings.json` retains processing replay settings.
Quantities are remembered while the application is open and recorded with each
export. They are separate from the ordinary processing-session schema.
Keep these details with the output. No actual sample mass or amount has been
supplied for Ho2sq3; distributed molar test results are labelled software fixtures.

## Usability in v1.3

**View** always identifies the displayed data. Unprocessed or invalidated scans
show **Raw**. Processed views become available for the selected signal after
subtraction; a stale manual baseline cannot be shown as a valid corrected result.
The previous preferred view returns when valid. Viewing Raw never changes treated
DAT output. The activity bar appears only during a task, without implying a
percentage complete.

Hover over a control for one second for brief help, including disabled actions.
The explanation stays while the pointer is over the control or tooltip. Leaving,
clicking, typing or pressing Esc dismisses it. **Help > User guide**, or **F1**
from the main window/settings/zero editor, opens an expandable local topic tree
with control descriptions, worked examples and troubleshooting.

This release preserves the numerical method, angle-range behavior, configuration
version 1.2 and baseline schema 2. The numerical implementation fingerprint is
unchanged; accepted v1.2 example offsets replay without reacceptance in the tested
environment. The existing source/data/environment checks still apply elsewhere.
Sample-position offset correction, shifted endpoint rules and new angular
rounding remain deferred. Torque zero adjustment in N m remains available.

## Scientific method and v1.2 import correction

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

These JSON files refer to the verified local raw file under
`20260928 Maglab Measurements - SCM6`. That directory was renamed; the
269380-byte file still has SHA-256
`04edb7daae1c04a4330cb49a2cd46de5111ee00c643cef8e6e510b1be258e04c`. If you relocate it, change
the session's file path; its SHA-256 identity must still match. Reusable temperature
values are saved as configuration data, not compiled into the processor.

```powershell
.\.venv\Scripts\python.exe cli.py process --session examples\Ho2sq3_0_to_200.json --dat runs\Ho2sq3_0_to_200.dat
.\.venv\Scripts\python.exe cli.py process --session examples\Ho2sq3_full_range.json --output runs
.\.venv\Scripts\python.exe cli.py inspect "path\to\raw.dat"
```

For another experiment, enter its own settings in the GUI and save them for
replay. CLI `--setpoints`, `--temperature-tolerance` and `--angle-range MIN MAX`
also accept explicit settings. Quote a whitespace list as one argument, for
example `--setpoints "7.375 13.625"`; these are illustrative values, not defaults.
Comma/mixed lists use the same Decimal parser. No target grid is inferred; `--allow-extrapolation P001` requires a deliberate
choice for the named scan. No treated reference is accessed during processing.

Older configurations retain ordinary centering and recorded baseline choices.
They need explicit temperature assignments if none were saved. Molar fields and
historical header-format choices are removed during version 1.0 migration, with
a recorded notice. Legacy molar CLI options/config fields remain rejected by the
processing command; optional molar presentation export is separate. Historical
molar outputs and archival packages remain unchanged.

## Build and validate v1.4

Tested on Windows 11 build 26300 x64, Python 3.12.14, NumPy 2.3.5,
Matplotlib 3.10.8 and Tk 8.6.12. PyInstaller 6.22.3 and Inno Setup 7.1.0 x64
build the offline application. `windows/dependency_wheels.json` records official
download URLs and wheel hashes. The builder verifies the pinned compiler download
and its vendor signature; no publisher certificate signs the resulting application.

Observed: 49 unit tests; withdrawn GUI workflow/Help/plot checks; three exact
pre-packaging DAT replays with unchanged accepted bindings; six historical cases
with 5405 exact A–D case rows; 196 protected files unchanged. Actual installed
GUI/CLI data agree. Silent installation, repeat update, locked-file rollback,
shortcut targets and uninstall/data preservation passed.

A clean Windows machine without development tools was not available. Executables
passed with Python-related environment variables cleared and System32-only PATH.
This is not a clean-machine test. Whole-window and visible installer UI review
were not performed under the background-only instruction. JPEGs were inspected
offscreen; Arial resolution and PDF embedding were checked.

Maintainer commands from this checkout (choose unused output names on repeat):

```powershell
py -3.12 -m venv .build-venv
.\.build-venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.build-venv\Scripts\python.exe tools\build_windows.py --output releases\Torque_Data_Postprocessing_1.4_build3
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tests\windows_bundle.py --bundle "validation\d é\Torque Data Postprocessing" --before validation\windows_app_v1.4_build1\before.json --output validation\v14_bundle_final
.\.venv\Scripts\python.exe tests\windows_installer.py --setup releases\Torque_Data_Postprocessing_1.4_build3\Torque_Data_Postprocessing_1.4_Setup_x64.exe --manifest releases\Torque_Data_Postprocessing_1.4_build3\bundle_manifest.json --before validation\windows_app_v1.4_build1\before.json --output validation\w14j
```

The build environment requires the recorded Python 3.12.14 runtime; the shown
`py` command is a setup example and must resolve to that version. The actual build
command above was tested with the existing isolated environment. The installer
harness refuses to run if an existing real installation is registered. It creates
only a temporary test installation and removes its shortcuts/registration.
Extract the portable ZIP to a short path before running the bundle check.
Installation directories are limited to 180 UTF-16 code units for the bundled
Windows DLL loader; Setup enforces this without changing Windows settings.

Installed CLI replay (use your actual settings/output paths):

```powershell
& "$env:LOCALAPPDATA\Programs\Torque Data Postprocessing\TorqueDataCLI.exe" process --session "C:\data\settings.json" --dat "C:\data\treated.dat"
```

The final source/update ZIP contains packaging code, tests and Help, with
paths preserved for a manual GitHub copy. No files require deletion. Research
measurements and generated evidence are excluded; `FIXTURE_LOCATIONS_v1.4.json`
records exact local fixture paths/hashes for the full regression suite. Generic
synthetic tests are included. Keep existing local research fixtures to run all
tests; a source ZIP alone deliberately contains no experimental raw data.

Current report: `WINDOWS_INSTALLER_REPORT_v1.4.txt`. Earlier reports below remain
historical evidence.

To verify a delivered source archive from an extracted copy:

```powershell
.\.venv\Scripts\python.exe tests\windows_source.py --archive releases\Torque_Data_Postprocessing_1.4_build3\Torque_Data_Postprocessing_v1.4_source_update.zip --output validation\v14_source_final
```

## Historical v1.3 validation

Current evidence: `USABILITY_IMPLEMENTATION_REPORT_v1.3.txt` and
`validation/usability_v1.3/`. The actual pre-patch v1.2 files/settings/hashes and
three representative outputs were saved before editing.

- 42 unit tests passed (37 existing plus 5 new).
- Hidden real Tk checks passed for list entry/scope, all view states, busy/error
  cleanup, hover timer/events/disabled controls, Help tree and modal access.
- The complete hidden workflow passed: load, settings, process, manual zero,
  save/load and byte-identical GUI/CLI export. Draft guards, drag/pan/zoom,
  zero-delta, independent settings and nonaccumulation remain intact.
- Three current example DATs are byte-identical to pre-patch v1.2; every saved
  upstream binding remains identical. 196 protected files are unchanged.
- Six historical cases retain exact A–D values across 5405 case rows, covering
  3519 distinct reference rows and 4869 distinct raw rows. Reference D matches:
  818/818, 938/938, 820/820, and previous Rot1 mean 615/943, midrange 328/943,
  diagnostic choices 943/943. These differences are unchanged.
- The new sample retains 1754 raw rows/34 scans: 1296 full-range signal rows and
  458 background rows. The 0–200° example retains 1023 signal/368 background rows,
  with 363 rows outside the interval recorded in the ledger.
- Isolated CLI processing passed with unrelated data/reference reads denied.
- Three Arial Regular PDF/300-dpi PNG pairs passed font embedding, size/style
  and clipping checks. Background and corrected images were inspected offscreen.
- Extracted source and v1.2+update copies replay all three examples exactly and
  load Help in withdrawn windows from an unrelated working directory.
- No full-window screenshot or visible desktop interaction was performed.

Reproduce from this folder; each output directory/filename must be unused:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
$raw = (Get-Content examples\Ho2sq3_0_to_200.json -Raw | ConvertFrom-Json).files[0].path
if (-not [IO.Path]::IsPathRooted($raw)) { $raw = [IO.Path]::GetFullPath((Join-Path (Join-Path $PWD 'examples') $raw)) }
.\.venv\Scripts\python.exe tests\usability_gui.py --raw "$raw" --output validation\replay_usability_v13
.\.venv\Scripts\python.exe tests\workflow_gui.py --raw "$raw" --output validation\replay_workflow_v13
.\.venv\Scripts\python.exe tests\workflow_regression.py --raw "$raw" --output validation\replay_regression_v13
.\.venv\Scripts\python.exe tests\workflow_isolation.py --session examples\Ho2sq3_manual_demo.json --output validation\replay_isolation_v13
.\.venv\Scripts\python.exe tests\usability_preservation.py --before validation\usability_v1.3\before.json --output validation\replay_preservation_v13.json
.\.venv\Scripts\python.exe -m pip install -r requirements-validation.txt
.\.venv\Scripts\python.exe tests\figures.py --session examples\Ho2sq3_0_to_200.json --output validation\replay_figures_v13
```

Both GUI harnesses withdraw all windows and use no desktop input. Hidden keyboard
checks invoke the actual registered Tcl event callback because withdrawn windows
cannot receive physical keyboard focus. These are widget/event tests, not a
whole-window visual review. Tcl initialization failed inside the restricted
sandbox; hidden GUI checks passed outside it. One isolated-run directory rename
was denied in the sandbox; replay passed outside it with its audit guard intact.
No dependency changes were required.

The source archive includes the raw/historical fixtures for current regression
checks. The GitHub update intentionally excludes research data and generated
validation; keep those local. The preservation test additionally verifies the
original absolute protected paths recorded in `before.json`. It is intended for
the original workspace; use packaged hashes and regression/replay when relocated.
Package verification (requires both ZIPs and the pre-patch snapshot):

```powershell
.\.venv\Scripts\python.exe tests\usability_package.py --archives . --output validation\replay_packages_v13
```

Older standalone scripts/reports describe their named historical versions.

## Limits

No treated reference was supplied for Ho2sq3, so its new exports are not claimed
to reproduce an independent historical treatment. Previous Rot1 diagnostic
centering choices remain reference-selected; an autonomous selector, historical
algorithm uniqueness and the physical basis of historical molar factors remain
unresolved scientific questions. Optional v1.4 normalization uses explicit user
quantities; it does not validate those historical factors.

This working tree is based on commit
`b9517f489a35dcf3984ea48356fc3d12956e7c5c`; current working changes remain uncommitted in this active checkout.
The project-state filename remains `Torque_GUI_project_state_v1.0.json` for
continuity; its current version field is 1.4.

Historical source/test/help archive: `Torque_Postprocessing_v1.3_source.zip`.
Its example paths point to the included raw fixture. The separate
`Torque_Postprocessing_v1.3_GitHub_update.zip` contains changed/new project files
relative to the saved v1.2 working contents. Read `UPDATE_v1.3.txt` before copying.
No files were copied into the GitHub checkout and no commit/push was performed.
