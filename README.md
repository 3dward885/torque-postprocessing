# Torque Postprocessing

Local Python desktop application for processing torque-magnetometry DAT files.
The Tkinter interface and command-line entry point use the same numerical core.

## Run on Windows

This repository was copied without the machine-specific Python environment.
Run **Setup_Windows.cmd** once in this folder, then **Launch_GUI.cmd**.
The setup finds the existing bundled Python 3.12 or an installed Python 3.12
with Tkinter and downloads the pinned dependencies. The original delivered
application remains available in its original folder with its tested environment.
Equivalent launch command after setup, from this repository directory:

```powershell
.\.venv\Scripts\python.exe app.py
```

Tested: Python 3.12.14, NumPy 2.3.5, Matplotlib 3.10.8, Tk 8.6.12, Windows 11.
Other platforms and numerical environments have not been validated.

## Workflow

Add raw files, inspect passes and their backgrounds, select settings, process,
preview, and export. Each new file defaults to midrange centering and torque-only
output. Molar output requires explicit sample metadata or a documented multiplier.
Optional treated-reference comparison occurs only after export.

The fixed recipe uses six-significant-digit torque inputs, an unweighted
degree-six background fit on the nominal [0, 200] degree domain, subtraction,
explicit centering, eight-significant-digit D export and exact Decimal E from
the exported D. The application never invents missing signal observations.

Read [README.txt](README.txt) for the full workflow, units, profiles and commands.
[BUILD_REPORT.txt](BUILD_REPORT.txt) records the observed version 1.0 acceptance.

## Validated baseline

| Dataset | Centering | Exact saved rows |
| --- | --- | ---: |
| New Rot1 | Midrange | 818/818 |
| New Rot2 | Midrange | 938/938 |
| Previous Rot2 | Midrange | 820/820 |
| Previous Rot1 | Mean | 615/943 |
| Previous Rot1 | Midrange | 328/943 |
| Previous Rot1 | Explicit diagnostic choices | 943/943 |

The old Rot1 diagnostic example uses reference-selected choices; the automatic
selector remains unresolved. The physical basis of multipliers 911.63 and
1575.45 remains unverified. Synthetic tests establish software behavior, not
experimental validity for new samples.

## Repository and local evidence

This repository tracks source, explicit profiles, tests, synthetic fixtures,
sample configurations and documentation. The original research data, generated
outputs, personal session and Python environment remain local and are ignored
by Git. The complete delivered source ZIP remains the immutable version 1.0
archive, including the original evidence and validation artifacts.

Real-data tests require the supplied evidence package at:

```text
evidence/Torque_Ho2thd4Pc_pipeline_comparison_v1.2/
```

The source archive SHA-256 is
`71b5c9bd246648fd52ad6cdaf48626ce6b9051facbbb31bea35347fcdffdc605`.
Exact fixture identities are in [fixtures/manifest.json](fixtures/manifest.json).
Restore the evidence from the original archive before running:

```powershell
.\.venv\Scripts\python.exe tests/test_core.py
.\.venv\Scripts\python.exe tests/regression.py --output validation/replay_new
.\.venv\Scripts\python.exe tests/isolation.py
.\.venv\Scripts\python.exe tests/gui_smoke.py
```

The supplied Gill Sans MT font is retained in the local application package
and is excluded from Git. For compliant scientific plot exports in a fresh
clone, restore the supplied `fonts/GIL_____.TTF` from that package.
Its required SHA-256 is
`f6664b244192ab4cf3a58bb6a653700d1f345d03bb8879888bcea1b6f8f3f97c`.
Without it, numerical processing works and previews identify the fallback;
compliant scientific PDF/PNG export is disabled.
See [NOTICE.txt](NOTICE.txt) for source and font provenance.

Historical reports and `tools/package_release.py` describe the complete local
delivery, including files intentionally excluded from Git. They are not claims
that a fresh clone includes private data or generated validation artifacts.

## Tracking changes

The repository is initialized on main with no initial commit. Add this folder
as an existing local repository in GitHub Desktop, review the changes, and
create the initial commit when ready. Publishing and pushing are manual.
Make future source edits in this same Git checkout. Review `git diff`, commit related changes with a useful
message, and push to GitHub. Commits are saved versions; pushing uploads them.
Changes are not uploaded automatically.

Keep raw measurements and generated runs outside tracked source files.
Line-ending conversion is disabled to preserve the verified source hashes.
