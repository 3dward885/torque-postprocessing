EXPLICIT SAMPLE CONFIGURATIONS

Load one of these session JSON files using Load configuration, or pass it to
cli.py process --session. Paths resolve relative to each JSON file. Each file
records its raw fingerprint, scientific profile and deliberate molar preset.

new_rot1_midrange.json, new_rot2_midrange.json, previous_rot2_midrange.json:
Fixed midrange reproduces every supplied reference row in the tested baseline.

previous_rot1_midrange.json:
Fixed midrange matches 328/943 rows. This limitation is intentional and recorded.

previous_rot1_DIAGNOSTIC.json:
DIAGNOSTIC ONLY. Its 15 mean / 8 midrange overrides come from the supplied
reference-selected table, whose hash is recorded with the settings. They give
943/943 exact rows retrospectively. They are NOT an autonomous selector, a
physical rule or a default for new data. Production never loads this file
automatically. Every override is bound to the exact input and pass identity.

All molar multipliers in these reference examples are documented export
multipliers, not independently verified sample amounts.

baseline_review_accepted.json (v1.1)
  Committed automated GUI-test setting for New Rot1 P003; delta is
  1.2345678901234567e-9 N m. Ordinary mean remains the policy for unreviewed
  passes. This is a software illustration, not a recommended physical correction.
  The explicit factor 1575.45 has verified arithmetic, unverified physical basis.
  CLI replay: python cli.py process --session examples/baseline_review_accepted.json --output runs
