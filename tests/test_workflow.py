"""Setpoints and angular selection; synthetic rows are software fixtures only."""
import copy
import csv
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from io_profiles import (read_raw, configure_acquisition, check_deviation, _nominal,
                         InputError, TSV_HEADER, INSTRUMENT_HEADER, sha256)
from pipeline import default_config, process, refinalize, support_permission, select_background, migrate_config
from baseline import accepted_record
from storage import save_dat, load_session, save_session, treated_text
from cli import run_entry, main as cli_main
from test_core import synthetic


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "synthetic.dat"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, rows=None, target="7.375"):
        rows = synthetic(range(250, -6, -5), range(250, -6, -5)) if rows is None else rows
        with self.path.open("w", newline="") as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            writer.writerow(TSV_HEADER)
            writer.writerows([[target] + r[1:] for r in rows])
        obj = read_raw(self.path)
        cfg = default_config(obj)
        cfg["acquisition"]["temperature_setpoints_K"] = [target]
        cfg["acquisition"]["source"] = "Synthetic user-selected temperature"
        return obj, cfg

    def test_actual_temperature_error_and_inclusive_boundaries(self):
        self.assertEqual(check_deviation("2.49238", "2.5", ".2", "T (K)"), Decimal("2.5"))
        with self.assertRaisesRegex(InputError, "0.49238"):
            check_deviation("2.49238", "2", ".2", "T (K)")
        for target, tol in [("7.375", ".2"), ("-4.125", ".05"), ("-10000", "1")]:
            for sign in (-1, 1):
                for difference in [Decimal(tol)/2, Decimal(tol)]:
                    check_deviation(Decimal(target)+sign*difference, target, tol, "Software fixture")
                with self.assertRaises(InputError):
                    check_deviation(Decimal(target)+sign*(Decimal(tol)+Decimal(".000001")), target, tol, "Software fixture")
        self.assertEqual(_nominal("-5.05", "5", ".05", "Angle (deg)"), -5)
        with self.assertRaises(InputError):
            _nominal("-5.050001", "5", ".05", "Angle (deg)")

    def test_missing_ambiguous_and_explicit_user_setpoints(self):
        obj, cfg = self.write()
        cfg["acquisition"]["temperature_setpoints_K"] = []
        self.assertEqual(len(read_raw(self.path).rows), 104)
        with self.assertRaisesRegex(InputError, "Missing temperature"):
            process(obj, cfg)
        cfg["acquisition"]["temperature_setpoints_K"] = ["7.375", "7.4", "13.625"]
        with self.assertRaisesRegex(InputError, "Ambiguous temperature"):
            process(obj, cfg)
        for p in obj.passes:
            cfg["acquisition"]["scans"][p.id] = {"identity": p.identity, "temperature_K": "7.375", "source": "Explicit synthetic scan setting"}
        self.assertEqual(process(obj, cfg)["rows"], 52)
        cfg["acquisition"]["scans"]["P001"]["temperature_K"] = "13.625"
        with self.assertRaisesRegex(InputError, "reference 13.625"):
            process(obj, cfg)

    def test_metadata_setpoints_and_user_precedence(self):
        records = synthetic()
        with self.path.open("w", newline="") as f:
            f.write('[Header]\nINFO,"7.375;13.625",TEMPERATURE_SETPOINTS_K\n[Data]\n')
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(INSTRUMENT_HEADER)
            for i, row in enumerate(records):
                cells = [""]*14
                cells[1], cells[2], cells[3], cells[4], cells[5], cells[12], cells[13] = str(i), "1", "7.39", row[1], row[2], row[3], "0"
                writer.writerow(cells)
        obj = read_raw(self.path)
        cfg = default_config(obj)
        result = process(obj, cfg)
        self.assertEqual(result["output_rows"][0][0], "7.375")
        cfg["acquisition"]["temperature_setpoints_K"] = ["7.4"]
        result = process(obj, cfg)
        self.assertEqual(result["output_rows"][0][0], "7.4")
        self.assertTrue(result["reference_settings"]["metadata_conflict"])
        self.assertEqual(result["ledger"][0]["measured_temperature_K"], "7.39")

    def test_ascending_sweeps_and_manual_boundaries(self):
        obj, cfg = self.write(synthetic(range(-5, 251, 5), range(-5, 251, 5)))
        self.assertEqual(len(obj.passes), 2)
        self.assertEqual(process(obj, cfg)["rows"], 52)
        cfg["acquisition"]["scan_starts"] = [p.rows[0].line for p in obj.passes]
        self.assertEqual(process(obj, cfg)["rows"], 52)
        cfg["acquisition"]["scan_starts"] = [999999]
        with self.assertRaises(InputError):
            process(obj, cfg)

    def test_range_excludes_backlash_from_fit_and_zero(self):
        rows = synthetic(range(250, -6, -5), range(250, -6, -5))
        for r in rows:
            if int(r[2]) < 0 or int(r[2]) > 200:
                r[3] = "0.02" if int(r[2]) > 200 else "-0.01"
        obj, cfg = self.write(rows)
        original_hash = sha256(self.path)
        cfg["acquisition"]["angle_range_deg"] = ["0", "200"]
        cropped = process(obj, cfg)
        self.assertEqual(cropped["rows"], 41)
        self.assertEqual(cropped["raw_rows"], 104)
        self.assertEqual(len(cropped["fits"]["P002"]["fit_angles_deg"]), 41)
        self.assertTrue(all(0 <= a <= 200 for a in cropped["passes"][0]["angles_deg"]))
        self.assertEqual(sum(r["retention"] == "outside selected angle range" for r in cropped["ledger"]), 22)
        self.assertEqual(sha256(self.path), original_hash)
        reference_obj, reference_cfg = self.write([r for r in rows if 0 <= int(r[2]) <= 200])
        reference = process(reference_obj, reference_cfg)
        self.assertEqual(cropped["passes"][0]["D"], reference["passes"][0]["D"])
        self.assertEqual(cropped["fits"]["P002"]["coefficients_scaled"], reference["fits"]["P002"]["coefficients_scaled"])
        self.assertEqual(cropped["passes"][0]["centering_constant_Nm"], reference["passes"][0]["centering_constant_Nm"])

    def test_range_rejects_empty_invalid_and_rank_deficient(self):
        obj, cfg = self.write()
        for limits in [["200", "0"], ["0", "0"], ["nan", "200"], ["0"], ["999", "1000"], ["0", "20"]]:
            cfg["acquisition"]["angle_range_deg"] = limits
            with self.assertRaises(InputError):
                process(obj, cfg)

    def test_range_change_requires_new_baseline_and_no_cached_refit(self):
        obj, cfg = self.write()
        result = process(obj, cfg)
        p = result["passes"][0]
        block = cfg["baseline_review"]
        block.update(enabled=True, active_passes=["P001"])
        block["overrides"]["P001"] = accepted_record(p["baseline_binding"], p["subtracted_Nm"], 1e-8)
        one = process(obj, cfg)
        with patch("pipeline.fit_background", side_effect=AssertionError("refit")):
            self.assertEqual(refinalize(one, cfg)["output_rows"], one["output_rows"])
        cfg["acquisition"]["angle_range_deg"] = ["0", "200"]
        with self.assertRaisesRegex(InputError, "Upstream"):
            refinalize(one, cfg)
        with self.assertRaisesRegex(InputError, "stale"):
            process(obj, cfg)
        preview = process(obj, cfg, allow_stale_review=True)
        self.assertFalse(preview["exportable"])

    def test_support_permission_scoped_and_range_can_remove_need(self):
        rows = synthetic(range(250, -6, -5), range(205, -6, -5))
        obj, cfg = self.write(rows)
        partial = process(obj, cfg, partial=True)
        self.assertFalse(partial["exportable"])
        with self.assertRaises(InputError):
            save_dat(partial, self.root/"partial.dat")
        configured = configure_acquisition(obj, cfg["acquisition"])
        sig, bg = configured.passes
        cfg["support_exceptions"].append(support_permission(configured, sig, bg, "Explicit synthetic extrapolation choice"))
        self.assertEqual(process(obj, cfg)["rows"], 52)
        cfg["support_exceptions"][0]["background_identity"] = "wrong"
        with self.assertRaisesRegex(InputError, "identity"):
            process(obj, cfg)
        cfg["support_exceptions"] = []
        cfg["acquisition"]["angle_range_deg"] = ["0", "200"]
        result = process(obj, cfg)
        self.assertEqual(result["rows"], 41)
        self.assertFalse(result["passes"][0]["support"]["extrapolation_angles_deg"])

    def test_tolerance_field_units_and_invalid_values(self):
        obj, cfg = self.write(target="11.234")
        for p in obj.passes:
            if not p.zero:
                cfg["acquisition"]["scans"][p.id] = {"identity": p.identity, "source": "Synthetic explicit field", "field_T": "1.0001"}
        self.assertEqual(process(obj, cfg)["output_rows"][0][1], "1.0001")
        cfg["acquisition"]["scans"]["P001"]["field_T"] = "1.0001000001"
        with self.assertRaisesRegex(InputError, "field \\(Oe\\)"):
            process(obj, cfg)
        for target in ["NaN", "Infinity", True]:
            cfg["acquisition"]["temperature_setpoints_K"] = [target]
            with self.assertRaises(InputError):
                process(obj, cfg)

    def test_saved_dat_collision_raw_guard_and_replay(self):
        obj, cfg = self.write()
        cfg["acquisition"]["angle_range_deg"] = ["0", "200"]
        settings = self.root/"session.json"
        save_session(settings, [(obj.path, cfg)])
        replay = run_entry(*load_session(settings)[0])
        out = Path(save_dat(replay, self.root/"treated.dat"))
        self.assertEqual(out.read_text(), treated_text(process(obj, cfg)))
        self.assertTrue(out.with_name(out.name+".details").is_dir())
        self.assertTrue(all(len(r.split("\t")) == 4 for r in out.read_text().splitlines()))
        with self.assertRaises(InputError):
            save_dat(replay, out)
        with self.assertRaises(InputError):
            save_dat(replay, self.path)
        with patch("storage.os.link", side_effect=OSError("injected failure")):
            with self.assertRaises(OSError):
                save_dat(replay, self.root/"failed.dat")
        self.assertFalse((self.root/"failed.dat").exists())
        self.assertFalse((self.root/"failed.dat.details").exists())

    def test_new_molar_options_rejected_old_migrated(self):
        obj, cfg = self.write()
        cfg["molar"] = {"mode": "multiplier", "factor": "911.63"}
        with self.assertRaisesRegex(InputError, "not supported"):
            process(obj, cfg)
        cfg["version"] = "1.0"
        result = process(obj, cfg)
        self.assertTrue(all(len(r) == 4 for r in result["output_rows"]))
        with self.assertRaises(SystemExit):
            cli_main(["process", "--raw", str(self.path), "--factor", "911.63", "--output", str(self.root)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
