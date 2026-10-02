TORQUE POSTPROCESSING GUI v1.1

Start the application
---------------------
On this computer the local environment is already installed and tested.
Double-click Launch_GUI.cmd.

Equivalent PowerShell command, from this application directory:
  .\.venv\Scripts\python.exe app.py

For an extracted source ZIP on another Windows computer:
1. Extract the complete directory to a writable local folder.
2. Install/provide Python 3.12 with Tkinter. If the Codex bundled Python is
   present, Setup_Windows.cmd finds it; otherwise it uses py -3.12.
3. Double-click Setup_Windows.cmd once. This downloads pinned packages from PyPI.
4. Double-click Launch_GUI.cmd for each session. No commands or Python edits
   are needed for individual datasets.

Manual one-time setup with an installed Python 3.12:
  py -3.12 -m venv .venv
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
  .\.venv\Scripts\python.exe app.py

Python 3.12.14, NumPy 2.3.5, Matplotlib 3.10.8, Tk 8.6.12 and Windows 11
were tested. The source ZIP excludes the machine-specific .venv. There is no
native installer. Other operating systems were not tested. On macOS/Linux,
provide Python/Tk, create .venv with python3 -m venv .venv, install requirements
with .venv/bin/python -m pip install -r requirements.txt, and run
.venv/bin/python app.py. Exact serialization in other environments is unverified;
use the included regression replay to check it.

Normal workflow
---------------
1. Add raw files. Each input starts independently with the Fractional profile,
   Midrange centering, and Torque only. Contents determine the schema; filenames
   never determine processing settings, calibration or sample amount.
2. File settings selects the explicit profile, centering, molar mode and export
   labels. Reference presets deliberately fill their documented multipliers.
   Their physical basis remains unverified.
3. Inspect the pass list. Details show source lines, gaps, the selected background
   and before/after order. Distinct acquisitions keep separate pass IDs.
   Pass settings / Background permits deliberate centering overrides and saved
   selection among multiple same-input, same-temperature backgrounds.
4. Click Process all. Then select a SIGNAL pass. Preview shows measured raw
   torque, background evaluation, subtracted torque and centered torque.
   Use Background view to inspect actual Q6 background samples and the fitted
   curve; Centered view isolates the final internal torque. Missing observations
   are never plotted as invented samples.
5. Choose an output folder and click Export ready. Each successful input gets
   a new complete run directory. Failures are listed individually. The batch
   JSON records inputs that could not be exported.
6. Save configuration to retain every file's settings. Loading verifies source
   fingerprints and stable pass identities, then requires processing again.
7. Optional: after export, Validation compares the SAVED DAT with a treated
   reference. Exact cells/rows/passes and residual metrics are reported.
   Comparison and Residual views become available. Validation cannot choose
   centering or change any calculation.

Changing upstream/file settings clears that input's results and requires processing.
Baseline changes refinalize cached u and clear saved-output/validation links. The pass list shows the effective centering policy. Process uses one background worker.


Optional baseline review (1.1)
------------------------------
README.md documents the complete workflow, state rules and current test commands.
Enable Interactive baseline adjustment only when review is desired. Process and
select a signal pass, then Review baseline. New reviews preview midrange without
committing. Apply accepts only that pass; Cancel discards its draft; Reset makes
a zero-Delta draft requiring Apply; Remove override restores ordinary centering.
Unchecking retains settings inactive. Dirty edits must be applied or discarded.
Positive Delta raises c_final and lowers corrected torque. Off never disables
ordinary centering. Only committed settings are exported. Stale active bindings
block export until reaccepted, removed or disabled. No read/refit occurs on drag.

Scientific recipe and units
---------------------------
For each observed signal pass:
  r6 = six-significant-digit Decimal rounding of original torque tokens
  z6 = the same rounding of its actual raw background tokens
  p  = unweighted degree-6 numpy.polynomial.Polynomial.fit to z6 versus nominal
       background angle, domain [0,200] degrees mapped to [-1,1]
  u  = r6 - p(nominal signal angles)
  c  = (min(u)+max(u))/2 for midrange, or arithmetic mean(u) for mean
       OR an explicitly accepted c_final when interactive review is active
  D  = binary64 format(u-c, '.8g')
  E  = exact Decimal(D) * Decimal(k), only when explicitly enabled

No further intermediate rounding, averaging, smoothing, regridding, invented
points, status filtering, uncertainty weighting, calibration or signal scaling.
One c is calculated over every actual pass, including changing-field passes.
It is a calculated centering constant, not a fitted free baseline or evidence
of instrumental drift.

Raw fields are Oe; output fields are tesla (divide by 10000 once).
D is torque (N m); optional E is molar torque (N m/mol).
Molar modes:
  torque: A-D only, no factor required.
  multiplier: positive k in mol^-1 plus its source note.
  amount: positive n in mol; k=1/n.
  mass: positive m in g or mg and M in g/mol; explicit mg->g conversion, k=M/m.
Factors use Decimal arithmetic with 50-digit division; the actual saved factor
is multiplied by EXPORTED D with enough precision for an exact product.
Sample metadata are declarations, not independent physical validation.

Profiles and supported inputs
-----------------------------
See profiles/previous.json and profiles/fractional.json. These human-readable
profiles are separate from fixtures/manifest.json and diagnostic examples.
Temperature: nominal 1 K, inclusive 0.2 K tolerance.
Angle: nominal 5 degrees, inclusive 0.05 degree tolerance, descending 200..0.
Background: |raw field| <= 1 Oe; signal: >1 Oe.
Stable-field tolerance: inclusive 1 Oe from its nominal value.
Previous: nominal integer tesla, full signal grids, stable-field passes.
Fractional: 0.01 T labels, ordered signal/background gaps, monotonic field
trajectories. Changing fields remain row-specific labels in a single pass.
Increasing angle within the same temperature/role must reset to 200 degrees
by more than 100 degrees. Duplicates, ambiguous resets, reversals and out-of-grid
records fail. Every pass retains acquisition order; no sorting or repair occurs.
Background association is within one input file at the same nominal temperature.
Supply one rotation/acquisition per input. Multiple backgrounds require an
explicit per-pass choice; backgrounds are never borrowed from another file.
Interior background gaps use ordinary polynomial evaluation. General profiles
allow no extrapolation. The deliberately selected New Rot2 reference preset
includes its authorized 50 K support permission, bound to that exact input hash.
It is not silently inherited by new files.

Load explicit profile JSON for legitimate changed tolerances/field steps/gap
policies or a documented max_extrapolation_deg. Include a meaningful provenance
note. Version 1.1 retains the 5-degree grid and fixed [0,200] fitted domain.
It does not validate the physical applicability of a custom policy.

Schemas:
  Instrument CSV: one [Data] marker followed by the documented 32-field header;
  14..32 actual fields, including documented populated trailing fields.
  Internal blanks keep their positions; only omitted trailing fields are padded.
  T/B/angle/torque are fields 4/5/6/13. Timestamp, status, bridge, user temperature
  and torque SD remain metadata. Timestamps must increase; SD is not a weight.
  Four-column TSV: exact K/Oe/deg/Nm headers. The documented nonmeasurement
  second line is preserved without inventing a timestamp column.
  Blank lines are explicitly retained as metadata; malformed populated lines
  are rejected. XLS/XLSX and unknown schemas/units are not supported.

Run contents
------------
treated.dat; settings.json; provenance.json; row_ledger.json; unchanged
raw_input.dat snapshot; SHA256SUMS.txt. Provenance records the recipe, environment,
code hashes, all pass boundaries, fitted coefficients/rank/support, associations,
calculated stages, centering choices/constants, sample metadata and output hashes.
Only signal rows are in treated.dat. All raw rows and original tokens/physical
lines are retained in the ledger; nonmeasurement lines are in provenance.
The final run directory is published by a rename only after all files succeed.
Raw hashes are checked before and during export. Existing run names are rejected.

Tested command examples (from this directory)
--------------------------------------------
Inspect, without fitting:
  .\.venv\Scripts\python.exe cli.py inspect evidence/Torque_Ho2thd4Pc_pipeline_comparison_v1.2/inputs/Rot1rawHo2thd4Pc.dat

Process using an explicit example session, without treated-reference access:
  .\.venv\Scripts\python.exe cli.py process --session examples/new_rot1_midrange.json --output runs

Process a new supported raw input in torque-only mode:
  .\.venv\Scripts\python.exe cli.py process --raw "your_raw.dat" --profile fractional --output runs

Validate a delivered saved output:
  .\.venv\Scripts\python.exe cli.py validate --output validation/regression/new_rot1_midrange/treated.dat --reference evidence/Torque_Ho2thd4Pc_pipeline_comparison_v1.2/inputs/Rot1treatedHo2thd4Pc.dat

Replay regressions in a NEW folder (existing named runs are protected):
  .\.venv\Scripts\python.exe tests/baseline_regression.py --output validation/replay_new
  .\.venv\Scripts\python.exe -m unittest discover -s tests -v
  .\.venv\Scripts\python.exe tests/baseline_gui.py --background --output validation/replay_gui

The GUI smoke test uses actual Tk widgets and event loop, with deterministic
paths supplied instead of interacting with native file pickers. Separate desktop
inspection exercised native controls and captured screenshots. --hold leaves the
smoke-test window open for inspection. Figure verification additionally needs
requirements-validation.txt and Poppler for rendering; neither is a normal
processing dependency.

Verified scope and limits
-------------------------
Read BASELINE_IMPLEMENTATION_REPORT_v1.1.txt and Torque_GUI_project_state_v1.0.json for current results. BUILD_REPORT.txt is historical v1.0.
All 4869 raw rows and 3519 unique reference rows are covered by the regression.
New Rot1 818/818, New Rot2 938/938 and Previous Rot2 820/820: fixed midrange exact.
Previous Rot1: fixed mean 615/943; fixed midrange 328/943.
examples/previous_rot1_DIAGNOSTIC.json matches 943/943 only with the established
reference-selected 15 mean/8 midrange choices. This is a test/example artifact,
never automatically loaded. The historical selector remains unresolved.
The documented 911.63 and 1575.45 factors are not physically validated.
Software admission of synthetic data is not experimental validation of transfer.

Plots
-----
Scientific exports use installed Arial Regular (resolved font checked); PDFs embed it.
8x6 inches (background fit 8x6.1), white; 22 pt labels, 18 pt ticks, 12 pt legends;
black left/bottom axes 1.2 pt, outward major/minor ticks 6/3 pt, no grid/title.
Background samples: 7.5 pt black circles with no joining lines; red 0.5 pt fit.
300 dpi PNG and vector PDF; existing filenames are protected. Missing font does
not block processing, but the app explicitly disables compliant scientific
export and identifies the preview fallback. See NOTICE.txt. fonts/provenance.txt
describes the unused historical Gill Sans asset, not the current Arial font.

