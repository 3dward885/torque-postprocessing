"""Small admission/failure tests. Synthetic data are software fixtures, not experiments."""
import copy
import csv
from dataclasses import asdict
from decimal import Decimal
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from io_profiles import GRID, INSTRUMENT_HEADER, TSV_HEADER, InputError, read_raw as load_raw, configure_acquisition, sha256
from pipeline import default_config, process, q6
from storage import export_run, treated_text, save_session, load_session
from validate import compare
from cli import main as cli_main


def synthetic(angles=GRID, background=GRID, second_background=False):
    records = []
    for field, support in [(10000, angles), (0, background)] + ([(0, background)] if second_background else []):
        for angle in support:
            torque = Decimal("1.23456789e-8") + Decimal(angle) * Decimal("1e-11")
            if field:
                torque += Decimal(angle * angle) * Decimal("2e-12")
            records.append(["5", str(field), str(angle), str(torque)])
    return records


def fixture_config(obj):
    cfg = default_config(obj)
    cfg["field_quality"].update(condition="changing", source="Synthetic test policy; not experimental approval")
    cfg["acquisition"]["temperature_setpoints_K"] = ["5"]
    cfg["acquisition"]["source"] = "Synthetic software fixture setpoint"
    return cfg


def read_raw(path, profile="fractional"):
    obj = load_raw(path, profile)
    obj = configure_acquisition(obj, fixture_config(obj)["acquisition"])
    for scan in obj.passes:
        if scan.issue:
            raise InputError(scan.issue)
    return obj


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="torque_tests_")
        self.folder = Path(self.tmp.name)
        self.path = self.folder / "SYNTHETIC_software_fixture.dat"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rows=None, header=TSV_HEADER):
        with self.path.open("w", newline="") as stream:
            writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
            writer.writerow(header)
            writer.writerows(synthetic() if rows is None else rows)
        return self.path

    def result(self, rows=None, profile="fractional"):
        obj = read_raw(self.write(rows), profile)
        return obj, fixture_config(obj)

    def test_new_hash_admission_and_torque_only(self):
        obj, cfg = self.result()
        result = process(obj, cfg)
        self.assertEqual(result["rows"], 41)
        self.assertEqual(result["raw_rows"], 82)
        self.assertEqual(len(result["output_rows"][0]), 4)
        self.assertNotIn("E", result["passes"][0])
        self.assertEqual(cfg["centering"], "midrange")
        self.assertNotIn(obj.sha256, ("365bb171e70b6c2ff1fdfde84cc7aa5c74d4620941826ee7cff185813286c2ce",
                                     "d7fe022a8d117006f26b5739e85ee90b3c6015a6e332e5ef8561e2eee3718933"))

    def test_renamed_real_input_identical(self):
        source = ROOT / "evidence/Torque_Ho2thd4Pc_pipeline_comparison_v1.2/inputs/Rot1rawHo2thd4Pc.dat"
        self.path.write_bytes(source.read_bytes())
        original = load_raw(source)
        renamed = load_raw(self.path)
        self.assertEqual(original.sha256, renamed.sha256)
        self.assertEqual([r.source_tokens for r in original.rows], [r.source_tokens for r in renamed.rows])

    def test_q6_decimal_rounding(self):
        self.assertEqual(q6(["1.234565e-8"])[0], float("1.23456e-8"))
        self.assertEqual(q6(["1.234575e-8"])[0], float("1.23458e-8"))
        self.assertEqual(q6(["1234567"])[0], 1234570)

    def test_inclusive_coordinate_and_field_tolerances(self):
        rows = synthetic()
        for row in rows:
            row[0] = "5.2"
            row[2] = str(Decimal(row[2]) + Decimal("0.05"))
            row[1] = "10001" if row[1] == "10000" else "1"
        obj, cfg = self.result(rows)
        self.assertEqual(process(obj, cfg)["rows"], 41)
        for column, bad in [(0, "5.200001"), (2, "200.050001"), (1, "10001.00001")]:
            changed = copy.deepcopy(rows)
            changed[0][column] = bad
            with self.assertRaises(InputError):
                read_raw(self.write(changed))

    def test_unknown_units_malformed_fields_and_annotation(self):
        for header in [TSV_HEADER[:1] + ["Magnetic Field (T)"] + TSV_HEADER[2:], ["A", "B", "C", "D"]]:
            with self.assertRaisesRegex(InputError, "schema/units"):
                read_raw(self.write(header=header))
        for bad in ("", "nan", "inf", "garbage"):
            rows = synthetic()
            rows[2][3] = bad
            with self.assertRaises(InputError):
                read_raw(self.write(rows))
        self.write()
        text = self.path.read_text()
        head, body = text.split("\n", 1)
        self.path.write_text(head + '\n00:00:00 2.0\t" "\t" "\t" "\n' + body)
        self.assertEqual(len(read_raw(self.path).metadata), 2)
        self.path.write_text(head + "\nunknown nonmeasurement\n" + body)
        with self.assertRaises(InputError):
            read_raw(self.path)

    def test_instrument_trailing_columns_and_metadata_positions(self):
        rows = []
        for i, source in enumerate(synthetic()):
            row = [""] * 32
            row[1], row[2], row[8], row[9], row[10], row[11], row[13], row[31] = str(i+1), "4390", "9", "10", "11", "999", "-1", "32"
            for k, value in zip((3, 4, 5, 12), source):
                row[k] = value
            rows.append(row)
        with self.path.open("w", newline="") as stream:
            stream.write("[Header]\n[Data]\n")
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(INSTRUMENT_HEADER)
            writer.writerows(rows)
        obj = read_raw(self.path)
        self.assertEqual(obj.rows[0].T, 5)
        self.assertEqual(obj.rows[0].tokens[31], "32")
        self.assertEqual(obj.rows[0].tokens[13], "-1")  # Preserved, never used as a weight.
        self.assertEqual(process(obj, fixture_config(obj))["rows"], 41)

    def test_duplicate_and_ambiguous_angle_reset_rejected(self):
        for bad_angle in ("200", "199", "195"):
            rows = synthetic()
            rows[2][2] = bad_angle
            with self.assertRaises(InputError):
                read_raw(self.write(rows))

    def test_same_labels_remain_separate_passes(self):
        rows = synthetic()
        rows = rows[:41] + rows[:41] + rows[41:]
        obj, cfg = self.result(rows)
        self.assertEqual(len(obj.passes), 3)
        self.assertEqual(process(obj, cfg)["rows"], 82)
        self.assertNotEqual(obj.passes[0].identity, obj.passes[1].identity)

    def test_changing_field_one_pass_and_reversal_error(self):
        rows = synthetic()
        for i, row in enumerate(rows[:41]):
            row[1] = str(20000 - i*100)
        obj, cfg = self.result(rows)
        self.assertTrue(obj.passes[0].trajectory)
        self.assertEqual(len(process(obj, cfg)["passes"]), 1)
        rows[4][1] = "25000"
        with self.assertRaisesRegex(InputError, "reversing"):
            read_raw(self.write(rows))
        with self.assertRaises(InputError):
            read_raw(self.write(rows), "previous")

    def test_signal_gaps_never_filled(self):
        obj, cfg = self.result(synthetic([x for x in GRID if x != 130]))
        self.assertEqual(process(obj, cfg)["rows"], 40)
        self.assertEqual(obj.passes[0].missing, [130])
        with self.assertRaisesRegex(InputError, "incomplete"):
            read_raw(self.path, "previous")

    def test_background_missing_ambiguous_and_explicit_selection(self):
        obj, cfg = self.result(synthetic()[:41])
        with self.assertRaisesRegex(InputError, "missing"):
            process(obj, cfg)
        obj, cfg = self.result(synthetic(second_background=True))
        with self.assertRaisesRegex(InputError, "multiple backgrounds"):
            process(obj, cfg)
        p = obj.passes[0]
        cfg["overrides"][p.id] = {"identity": p.identity, "background": "P003", "source": "Synthetic test selection"}
        self.assertEqual(process(obj, cfg)["passes"][0]["background_id"], "P003")

    def test_background_rank_support_and_explicit_extrapolation(self):
        obj, cfg = self.result(synthetic(background=GRID[:6]))
        with self.assertRaisesRegex(InputError, "seven unique"):
            process(obj, cfg)
        obj, cfg = self.result(synthetic(background=GRID[1:]))
        with self.assertRaisesRegex(InputError, "exceed"):
            process(obj, cfg)
        custom = asdict(obj.profile)
        custom.update(name="explicit_5deg", max_extrapolation_deg="5", provenance="Synthetic support software test only")
        obj = read_raw(self.path, custom)
        self.assertEqual(process(obj, fixture_config(obj))["rows"], 41)

    def test_legacy_molar_settings_migrate_to_torque_only(self):
        obj, cfg = self.result()
        ordinary = process(obj, cfg)
        cfg["version"] = "1.0"
        cfg["molar"] = {"mode": "multiplier", "factor": "1575.45", "source": "Archived software test"}
        result = process(obj, cfg)
        self.assertEqual(result["output_rows"], ordinary["output_rows"])
        self.assertTrue(all(len(row) == 4 for row in result["output_rows"]))
        self.assertNotIn("molar", result["config"])
        self.assertTrue(result["config"]["migration_notes"])

    def test_config_fingerprint_identity_and_no_corrections(self):
        obj, cfg = self.result()
        for field, value in [("input_sha256", "wrong"), ("correction_vector", [0]), ("centering", "automatic")]:
            changed = copy.deepcopy(cfg)
            changed[field] = value
            with self.assertRaises(InputError):
                process(obj, changed)
        cfg["overrides"]["P001"] = {"identity": "wrong", "centering": "mean", "source": "test"}
        with self.assertRaisesRegex(InputError, "identity"):
            process(obj, cfg)
        cfg = fixture_config(obj)
        p = obj.passes[0]
        cfg["overrides"][p.id] = {"identity": p.identity, "centering": "mean", "source": "Deliberate software test"}
        self.assertEqual(process(obj, cfg)["passes"][0]["centering"], "mean")
        session = self.folder / "session.json"
        save_session(session, [(obj.path, cfg)])
        self.assertEqual(load_session(session)[0][1], cfg)

    def test_atomic_export_collision_and_changed_input(self):
        obj, cfg = self.result()
        result = process(obj, cfg)
        saved = Path(export_run(result, self.folder, "run"))
        before = (saved/"treated.dat").read_bytes()
        with self.assertRaisesRegex(InputError, "collision"):
            export_run(result, self.folder, "run")
        self.assertEqual(before, (saved/"treated.dat").read_bytes())
        with patch("storage.shutil.copyfile", side_effect=OSError("injected write failure")):
            with self.assertRaises(OSError):
                export_run(result, self.folder, "incomplete")
        self.assertFalse((self.folder/"incomplete").exists())
        self.assertFalse(list(self.folder.glob(".pending_*")))
        self.path.write_text(self.path.read_text() + "\n")
        with self.assertRaisesRegex(InputError, "changed"):
            export_run(result, self.folder, "changed")

    def test_cli_same_function_and_partial_batch_reporting(self):
        obj, cfg = self.result()
        result = process(obj, cfg)
        capture = io.StringIO()
        with patch("sys.stdout", capture):
            status = cli_main(["process", "--raw", str(self.path), str(self.folder/"missing.dat"), "--setpoints", "5", "--field-condition", "changing", "--output", str(self.folder/"out")])
        reports = json.loads(capture.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual([r["status"] for r in reports], ["success", "failed"])
        self.assertEqual((Path(reports[0]["saved"])/"treated.dat").read_text(), treated_text(result))

    def test_validation_is_read_only(self):
        obj, cfg = self.result()
        result = process(obj, cfg)
        run = Path(export_run(result, self.folder, "validation"))
        reference = self.folder/"treated_reference.dat"
        reference.write_text(treated_text(result))
        before = sha256(run/"treated.dat")
        met = compare(run/"treated.dat", reference)
        self.assertEqual(met["exact_rows"], 41)
        self.assertEqual(sha256(run/"treated.dat"), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
