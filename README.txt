Torque Data Postprocessing 1.6

Read README.md for current launch, workflow, replay and validation instructions.
End users: run Torque_Data_Postprocessing_1.6_Setup_x64.exe, then open
Torque Data Postprocessing from the Start menu. No Python/setup scripts required.
See WINDOWS_APP.txt. The installer is unsigned.
Developers: use Setup_Windows.cmd, then Launch_GUI.cmd or python app.py.

Current workflow: open DAT, set experiment conditions/background, center zero,
save treated DAT. Temperature setpoints are configurable. Optional angle bounds
apply before background fitting and centering. Ordinary DAT output stays in N m.
The main Output section selects Torque or Molar torque per file. Enter sample
mass (mg) plus molar mass (g/mol), or amount (mol), then Apply. Save both data
files preserves ordinary torque and adds separate molar DAT. Save plots creates
JPEGs only. Settings retain committed choices. No sample amount is inferred.

Historical BUILD_REPORT.txt, BASELINE_IMPLEMENTATION_REPORT_v1.1.txt and older
execution prompts record earlier releases. Current results are described in
WINDOWS_INSTALLER_REPORT_v1.6.txt. The v1.3 usability report is historical.

Help > User guide or F1 opens the local guide. Hover help appears after one second.
Temperature lists accept spaces or commas. Position correction remains deferred.

Newly extracted source copies need Setup_Windows.cmd in that same folder first.
Wait for Setup complete, then run Launch_GUI.cmd. Setup and startup errors are
saved in setup.log and launch.log. See STARTUP_FIX_v1.3.txt.

FIELD REVIEW (v1.6)
New and migrated sessions require an explicit field policy. For Fixed field, enter your review limit in T in Acquisition settings. No experimental default is supplied.
The full acquired measured field span is rounded to 0.01 T (nearest; ties away from zero). At or above the limit requires review. This does not alter field measurements or nominal coordinates.
Review scan shows original rows and the field trace. Detection never excludes. Enter a reason and explicitly exclude the entire scan or permit an intended changing-field acquisition. Closing review leaves it unresolved. All final exports are blocked while an included scan is unresolved. Raw snapshots and the row ledger retain excluded measurements.
Save a new session for CLI replay. Old monotonic parsing does not constitute changing-field permission. Changing the source, scan identity or field policy invalidates affected decisions; display and molar settings do not.
