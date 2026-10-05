Torque Postprocessing 1.3

Read README.md for current launch, workflow, replay and validation instructions.
Double-click Launch_GUI.cmd, or run .\.venv\Scripts\python.exe app.py.

Current workflow: open DAT, set experiment conditions/background, center zero,
save treated DAT. Temperature setpoints are configurable. Optional angle bounds
apply before background fitting and centering. Output is torque in N m only.

Historical BUILD_REPORT.txt, BASELINE_IMPLEMENTATION_REPORT_v1.1.txt and older
execution prompts record earlier releases. Current results are described in
USABILITY_IMPLEMENTATION_REPORT_v1.3.txt.

Help > User guide or F1 opens the local guide. Hover help appears after one second.
Temperature lists accept spaces or commas. Position correction remains deferred.

Newly extracted copies need Setup_Windows.cmd in that same folder first.
Wait for Setup complete, then run Launch_GUI.cmd. Setup and startup errors are
saved in setup.log and launch.log. See STARTUP_FIX_v1.3.txt.
