Current v1.3 examples (unchanged scientific settings from v1.2)

Ho2sq3_full_range.json: user-confirmed temperatures/backgrounds; 1296 signal rows;
explicit permission to extrapolate the 100 K background for P022, P023 and P024.
Ho2sq3_0_to_200.json: inclusive nominal-angle range 0–200 deg for background
fitting, centering and export; 1023 signal rows; no extrapolation needed.
Ho2sq3_manual_demo.json: automated GUI software test with P001 delta=1e-9 N m;
not an experimental calibration or recommended physical correction.

Load through File > Load settings, then Subtract background. CLI replay examples
and raw fixture identity/location are in ../README.md and the implementation report.
Other example JSON files belong to older releases and require settings migration.

Local paths reflect the renamed 20260928 Maglab Measurements - SCM6 directory.
Raw identity and all accepted offsets are unchanged. Portable source ZIP examples
point to its included fixture. Do not apply the software-test offset as calibration.
