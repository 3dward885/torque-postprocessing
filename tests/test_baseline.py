"""Focused A/B/C/E/H gates; synthetic vectors are software fixtures only."""
import copy
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from baseline import accepted_record, finalize_pass, preview_values, ReviewCache, empty_review
from io_profiles import read_raw, InputError, TSV_HEADER
from pipeline import default_config, process, refinalize, verify_export
from storage import treated_text, save_session, load_session
from test_core import synthetic, fixture_config


def bound(u, c_mid, c_final, delta):
    scale = max(np.max(np.abs(u)), abs(c_mid), abs(c_final), abs(delta))
    return 16*np.finfo(float).eps*scale + 8*np.nextafter(0., 1.)


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/"SYNTHETIC.dat"
        rows = synthetic()
        # Two distinct acquisitions with identical T/B.
        with self.path.open("w", newline="") as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            writer.writerow(TSV_HEADER)
            writer.writerows(rows[:41] + rows[:41] + rows[41:])
        self.obj = read_raw(self.path)
        self.cfg = fixture_config(self.obj)
        self.cfg["centering"] = "mean"
        self.result = process(self.obj, self.cfg)
        self.pred = self.result["passes"][0]

    def tearDown(self):
        self.temp.cleanup()

    def accepted(self, delta=0.):
        cfg = copy.deepcopy(self.cfg)
        cfg["baseline_review"]["enabled"] = True
        cfg["baseline_review"]["active_passes"] = ["P001"]
        cfg["baseline_review"]["overrides"]["P001"] = accepted_record(
            self.pred["baseline_binding"], self.pred["subtracted_Nm"], delta)
        return cfg

    def test_old_default_inactive_and_unreviewed(self):
        old = copy.deepcopy(self.cfg)
        del old["baseline_review"]
        self.assertEqual(treated_text(process(self.obj, old)), treated_text(self.result))
        enabled = copy.deepcopy(self.cfg)
        enabled["baseline_review"]["enabled"] = True
        self.assertEqual(treated_text(process(self.obj, enabled)), treated_text(self.result))
        inactive = self.accepted(1e-9)
        inactive["baseline_review"]["enabled"] = False
        inactive["baseline_review"]["overrides"]["P001"]["upstream_fingerprint"] = "stale"
        self.assertEqual(treated_text(process(self.obj, inactive)), treated_text(self.result))

    def test_zero_and_repeated_replay_no_accumulation(self):
        cfg = self.accepted()
        result = process(self.obj, cfg)
        expected = copy.deepcopy(self.cfg)
        expected["overrides"]["P001"] = {"identity": self.obj.passes[0].identity,
            "centering": "midrange", "source": "Explicit synthetic test"}
        self.assertEqual(treated_text(result), treated_text(process(self.obj, expected)))
        for _ in range(3):
            result = refinalize(result, cfg)
            self.assertEqual(treated_text(result), treated_text(process(self.obj, cfg)))
        record = cfg["baseline_review"]["overrides"]["P001"]
        self.assertEqual(record, accepted_record(self.pred["baseline_binding"],
            self.pred["subtracted_Nm"], 0., record))
        cfg["baseline_review"]["overrides"].clear()
        cfg["baseline_review"]["active_passes"].clear()
        self.assertEqual(treated_text(refinalize(result, cfg)), treated_text(self.result))

    def test_roundtrip_and_no_refit(self):
        cfg = self.accepted(1.2345678901234567e-9)
        path = Path(self.temp.name)/"session.json"
        save_session(path, [(self.obj.path, cfg)])
        loaded = load_session(path)[0][1]
        self.assertEqual(loaded, cfg)
        with patch("pipeline.fit_background", side_effect=AssertionError("refit")), patch("pipeline.read_raw", side_effect=AssertionError("read")):
            cached = refinalize(self.result, loaded)
        self.assertEqual(treated_text(cached), treated_text(process(self.obj, loaded)))
        cache = ReviewCache.from_prediction(self.pred)
        with self.assertRaises(ValueError):
            cache.u[0] = 0
        with self.assertRaises(ValueError):
            cache.u.setflags(write=True)

    def test_stale_records_and_unknown_versions(self):
        for key, value in [("input_sha256", "wrong"), ("pass_identity", "wrong"),
                           ("background_identity", {}), ("upstream_fingerprint", "wrong"),
                           ("u_sha256", "wrong"), ("c_final_Nm", "nan"),
                           ("delta_Nm", "1"), ("accepted_utc", None),
                           ("c_final_binary64_hex", "0x0p+0")]:
            cfg = self.accepted()
            cfg["baseline_review"]["overrides"]["P001"][key] = value
            with self.assertRaisesRegex(InputError, "stale"):
                process(self.obj, cfg)
            display = process(self.obj, cfg, allow_stale_review=True)
            self.assertFalse(display["exportable"])
            with self.assertRaises(InputError):
                verify_export(display)
        for field, value in [("schema_version", 3), ("enabled", "yes")]:
            cfg = self.accepted()
            cfg["baseline_review"][field] = value
            with self.assertRaises(InputError):
                process(self.obj, cfg)
        cfg = self.accepted()
        cfg["baseline_review"]["active_passes"] = ["UNKNOWN"]
        cfg["baseline_review"]["overrides"]["UNKNOWN"] = cfg["baseline_review"]["overrides"].pop("P001")
        with self.assertRaisesRegex(InputError, "Unknown"):
            process(self.obj, cfg)

    def test_same_labels_cannot_share_offset(self):
        cfg = self.accepted(1e-9)
        result = process(self.obj, cfg)
        self.assertEqual(result["passes"][1]["D"], self.result["passes"][1]["D"])
        record = copy.deepcopy(cfg["baseline_review"]["overrides"]["P001"])
        record["pass_id"] = "P002"
        cfg["baseline_review"]["overrides"]["P002"] = record
        cfg["baseline_review"]["active_passes"].append("P002")
        with self.assertRaisesRegex(InputError, "stale"):
            process(self.obj, cfg)

    def test_molar_and_ordinary_policy_not_upstream(self):
        cfg = self.accepted(1e-9)
        one = process(self.obj, cfg)
        cfg["version"] = "1.0"
        cfg["molar"] = {"mode":"multiplier","factor":"911.63","source":"Provided software test factor; physical basis unverified"}
        cfg["centering"] = "midrange"
        two = process(self.obj, cfg)
        self.assertEqual(one["passes"][0]["D"], two["passes"][0]["D"])
        self.assertEqual(one["passes"][0]["baseline_binding"], two["passes"][0]["baseline_binding"])
        self.assertNotIn("E", two["passes"][0])
        self.assertTrue(all(len(r) == 4 for r in two["output_rows"]))

    def test_recipe_and_raw_changes_invalidate(self):
        cfg = self.accepted()
        with patch.dict("pipeline.RECIPE", {"degree": 5}):
            with self.assertRaisesRegex(InputError, "stale"):
                process(self.obj, cfg)
        self.path.write_text(self.path.read_text()+"\n")
        new = read_raw(self.path)
        cfg["input_sha256"] = new.sha256
        with self.assertRaisesRegex(InputError, "stale"):
            process(new, cfg)

    def test_different_background_invalidates_even_with_identical_u(self):
        with self.path.open("w", newline="") as f:
            writer = csv.writer(f, delimiter="\t", lineterminator="\n")
            writer.writerow(TSV_HEADER)
            writer.writerows(synthetic(second_background=True))
        obj = read_raw(self.path)
        cfg = fixture_config(obj)
        cfg["overrides"]["P001"] = {"identity": obj.passes[0].identity,
            "background": "P002", "source": "Explicit synthetic background choice"}
        pred = process(obj, cfg)["passes"][0]
        cfg["baseline_review"]["enabled"] = True
        cfg["baseline_review"]["active_passes"] = ["P001"]
        cfg["baseline_review"]["overrides"]["P001"] = accepted_record(pred["baseline_binding"], pred["subtracted_Nm"], 1e-9)
        cfg["overrides"]["P001"]["background"] = "P003"
        with self.assertRaisesRegex(InputError, "background_identity"):
            process(obj, cfg)

    def test_arithmetic_bound_constant_subnormal_and_invalid(self):
        vectors = [np.array([0., 0.]), np.full(5, 1.2e-8),
                   np.array([-3e-8, 4e-8, 7e-9]),
                   np.array([-1., 1., .25])*np.nextafter(0., 1.)*8,
                   np.array(self.pred["subtracted_Nm"])]
        for u in vectors:
            zero = preview_values(u, 0.)
            b = bound(u, zero["c_mid"], zero["c_final"], 0.)
            self.assertLessEqual(abs(zero["imbalance"]), b)
            for delta in [0., 1e-9, -1e-9]:
                p = preview_values(u, delta)
                b = bound(u, p["c_mid"], p["c_final"], delta)
                self.assertLessEqual(max(abs(p["corrected"]-zero["corrected"]+delta)), b)
                self.assertLessEqual(abs(np.ptp(u)-np.ptp(p["corrected"])), b)
                self.assertLessEqual(abs(p["imbalance"]+2*delta), b)
            if np.ptp(u) == 0:
                self.assertTrue(np.all(zero["corrected"] == 0))
        for values in [[], [float("nan")], [float("inf")]]:
            with self.assertRaises(InputError):
                finalize_pass(values, "midrange")
        for delta in ["", "nan", "inf", "-inf", "1e9999"]:
            with self.assertRaises(InputError):
                preview_values([0, 1], delta)


if __name__ == "__main__":
    unittest.main(verbosity=2)
