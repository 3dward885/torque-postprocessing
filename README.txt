Torque Data Postprocessing 1.5

Read README.md for current launch, workflow, replay and validation instructions.
End users: run Torque_Data_Postprocessing_1.5_Setup_x64.exe, then open
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
WINDOWS_INSTALLER_REPORT_v1.5.txt. The v1.3 usability report is historical.

Help > User guide or F1 opens the local guide. Hover help appears after one second.
Temperature lists accept spaces or commas. Position correction remains deferred.

Newly extracted source copies need Setup_Windows.cmd in that same folder first.
Wait for Setup complete, then run Launch_GUI.cmd. Setup and startup errors are
saved in setup.log and launch.log. See STARTUP_FIX_v1.3.txt.
