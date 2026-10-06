Torque Data Postprocessing 1.4

Read README.md for current launch, workflow, replay and validation instructions.
End users: run Torque_Data_Postprocessing_1.4_Setup_x64.exe, then open
Torque Data Postprocessing from the Start menu. No Python/setup scripts required.
See WINDOWS_APP.txt. The installer is unsigned.
Developers: use Setup_Windows.cmd, then Launch_GUI.cmd or python app.py.

Current workflow: open DAT, set experiment conditions/background, center zero,
save treated DAT. Temperature setpoints are configurable. Optional angle bounds
apply before background fitting and centering. Ordinary DAT output stays in N m.
Tools > Export treated plots saves JPEGs grouped by rotation and temperature.
Choose N m or N m/mol; molar mode also saves a separate molar DAT and requires
sample mass plus molar mass, or amount in moles. No sample amount is inferred.

Historical BUILD_REPORT.txt, BASELINE_IMPLEMENTATION_REPORT_v1.1.txt and older
execution prompts record earlier releases. Current results are described in
WINDOWS_INSTALLER_REPORT_v1.4.txt. The v1.3 usability report is historical.

Help > User guide or F1 opens the local guide. Hover help appears after one second.
Temperature lists accept spaces or commas. Position correction remains deferred.

Newly extracted source copies need Setup_Windows.cmd in that same folder first.
Wait for Setup complete, then run Launch_GUI.cmd. Setup and startup errors are
saved in setup.log and launch.log. See STARTUP_FIX_v1.3.txt.
