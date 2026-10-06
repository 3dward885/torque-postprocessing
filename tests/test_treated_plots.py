"""Presentation exports use treated values; examples below are software fixtures."""
import copy
import csv
from decimal import Decimal, localcontext
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_core import synthetic, fixture_config, read_raw
from io_profiles import TSV_HEADER, InputError, sha256
from pipeline import process
from storage import treated_text
from treated_plots import (normalization, converted_token, grouped_samples, grouped_figure,
                           molar_text, export_treated_plots, suggested_rotation, publish_directory)
from matplotlib.backends.backend_agg import FigureCanvasAgg
from PIL import Image

MASS = {"quantity": "molar", "method": "mass", "mass_mg": "2", "molar_mass_g_mol": "400",
        "rotation": "1", "source": "Synthetic software-test normalization, not experimental"}
AMOUNT = {**MASS, "method": "amount", "amount_mol": "0.000005"}


class TreatedPlotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="torque_plot_tests_")
        self.folder = Path(self.tmp.name)
        self.raw = self.folder / "SYNTHETIC_Rot1.dat"
        data = synthetic()
        with self.raw.open("w", newline="") as stream:
            writer = csv.writer(stream, delimiter="\t")
            writer.writerow(TSV_HEADER)
            writer.writerows(data[:41] + data)  # Repeated T/B, independent acquisitions.
        obj = read_raw(self.raw)
        self.result = process(obj, fixture_config(obj))

    def tearDown(self):
        self.tmp.cleanup()

    def test_normalization_dimensions_and_invalid_values(self):
        mass, amount = normalization(MASS), normalization(AMOUNT)
        self.assertEqual(Decimal(mass["derived_amount_mol"]), Decimal("0.000005"))
        self.assertEqual(Decimal(mass["factor_mol_inverse"]), Decimal("200000"))
        for norm in (mass, amount):
            self.assertEqual(Decimal(converted_token("1e-6", norm)), Decimal("0.2"))
            self.assertEqual(Decimal(converted_token("-1e-6", norm)), Decimal("-0.2"))
        for key in ("mass_mg", "molar_mass_g_mol"):
            for invalid in ("", "NaN", "Infinity", "0", "-2", "garbage"):
                with self.assertRaises(InputError):
                    normalization({**MASS, key: invalid})
        for invalid in ("", "NaN", "0", "-1", "1e-999999"):
            with self.assertRaises(InputError):
                normalization({**AMOUNT, "amount_mol": invalid})
        with self.assertRaises(InputError):
            normalization({"quantity": "molar", "method": "mass", "molar_mass_g_mol": "400"})
        with self.assertRaises(InputError):
            converted_token("1e-250", {"quantity": "molar", "factor_mol_inverse": "1e-250"})

    def test_grouping_preserves_acquisitions_and_treated_coordinates(self):
        before = copy.deepcopy(self.result)
        rotation, norm, groups = grouped_samples(self.result, {"rotation": "2"})
        self.assertEqual(rotation, "2")
        self.assertEqual(list(groups), [Decimal("5")])
        series = groups[Decimal("5")]
        self.assertEqual(len(series), 2)
        self.assertNotEqual(series[0]["identity"], series[1]["identity"])
        self.assertEqual(sum(len(s["tokens"]) for s in series), 82)
        self.assertEqual([v for s in series for v in s["tokens"]], [r[3] for r in self.result["output_rows"]])
        self.assertEqual([v for s in series for v in s["angles"]], [float(r[2]) for r in self.result["output_rows"]])
        self.assertEqual(self.result, before)
        self.assertEqual(suggested_rotation("Sample_Rot12.dat"), "12")
        self.assertEqual(suggested_rotation("Unknown.dat"), "")
        for invalid in ("", "1.5", "0", "-1"):
            with self.assertRaises(InputError):
                grouped_samples(self.result, {"rotation": invalid})

    def test_molar_rows_are_exact_products_of_serialized_torque(self):
        ordinary = treated_text(self.result)
        norm = normalization({**AMOUNT, "amount_mol": "3e-6"})
        rows = list(csv.reader(molar_text(self.result, norm).splitlines(), delimiter="\t"))
        self.assertIn("N m/mol", rows[0][3])
        self.assertEqual(len(rows) - 1, self.result["rows"])
        for actual, original in zip(rows[1:], self.result["output_rows"]):
            self.assertEqual(actual[:3], original[:3])
            with localcontext() as context:
                context.prec = 100
                self.assertEqual(Decimal(actual[3]), Decimal(original[3]) * Decimal(norm["factor_mol_inverse"]))
        self.assertEqual(ordinary, treated_text(self.result))

    def test_figure_has_only_requested_text_markers_and_style(self):
        rotation, norm, groups = grouped_samples(self.result, MASS)
        series = groups[Decimal("5")]
        fig = grouped_figure(rotation, Decimal("5"), series, norm, {series[0]["field"]: 0})
        canvas = FigureCanvasAgg(fig)
        canvas.draw()
        ax = fig.axes[0]
        self.assertEqual(ax.get_title(), "Rotation 1, T = 5 K")
        self.assertEqual(ax.get_ylabel(), "Molar torque (N m/mol)")
        self.assertEqual(len(ax.texts), 0)
        self.assertEqual(len(fig.texts), 0)
        self.assertEqual([t.get_text() for t in ax.get_legend().texts], ["B = 1 T"])
        self.assertEqual(len(ax.lines), 2)
        self.assertTrue(all(line.get_linestyle() == "None" for line in ax.lines))
        self.assertEqual(list(fig.get_size_inches()), [8, 6])
        self.assertEqual(fig.get_facecolor(), (1, 1, 1, 1))
        self.assertEqual(ax.xaxis.label.get_fontsize(), 22)
        self.assertEqual(ax.xaxis.label.get_fontfamily(), ["Arial"])
        self.assertFalse(ax.spines["top"].get_visible())
        self.assertFalse(ax.spines["right"].get_visible())
        for text in (ax.title, ax.xaxis.label, ax.yaxis.label, *ax.get_legend().texts):
            box = text.get_window_extent(canvas.get_renderer())
            self.assertTrue(fig.bbox.contains(box.x0, box.y0) and fig.bbox.contains(box.x1, box.y1), text.get_text())

    def test_atomic_export_molar_and_torque_separate_and_no_raw_changes(self):
        original = sha256(self.raw)
        ordinary = treated_text(self.result)
        out = Path(export_treated_plots([(self.result, MASS), (self.result, {"rotation": "2"})], self.folder))
        info = json.loads((out / "plots.details/plots.json").read_text())
        self.assertEqual(len(info["files"]), 2)
        self.assertEqual(len(list(out.glob("*.dat"))), 1)
        for item in info["files"]:
            self.assertEqual(item["plots"][0]["points"], 82)
            with Image.open(out / item["plots"][0]["filename"]) as image:
                self.assertEqual(image.size, (2400, 1800))
                self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
                self.assertEqual(image.info["dpi"], (300, 300))
        self.assertEqual(sha256(self.raw), original)
        self.assertEqual(treated_text(self.result), ordinary)
        second = Path(export_treated_plots([(self.result, MASS)], self.folder))
        self.assertNotEqual(second, out)
        with patch("treated_plots.grouped_figure", side_effect=InputError("Test failure")):
            with self.assertRaisesRegex(InputError, "Test failure"):
                export_treated_plots([(self.result, MASS)], self.folder)
        self.assertFalse(list(self.folder.glob(".pending_*")))
        self.raw.write_text("changed raw")
        with self.assertRaisesRegex(InputError, "Raw input changed"):
            export_treated_plots([(self.result, MASS)], self.folder)

    def test_incomplete_and_stale_results_cannot_be_presented(self):
        bad = copy.deepcopy(self.result)
        bad["exportable"] = False
        with self.assertRaises(InputError):
            grouped_samples(bad, {"rotation": "1"})
        bad = copy.deepcopy(self.result)
        bad["passes"][0]["D"][0] = "123"
        with self.assertRaises(InputError):
            grouped_samples(bad, {"rotation": "1"})

    def test_transient_windows_publish_lock_retries_without_overwriting(self):
        stage, final = self.folder / "pending", self.folder / "published"
        stage.mkdir()
        (stage / "complete.dat").write_text("complete")
        error = PermissionError("Simulated Windows directory lock")
        error.winerror = 5
        rename = Path.rename
        attempts = []
        def once(path, target):
            attempts.append(path)
            if len(attempts) == 1:
                raise error
            return rename(path, target)
        with patch.object(Path, "rename", once), patch("treated_plots.time.sleep"):
            publish_directory(stage, final)
        self.assertEqual(len(attempts), 2)
        self.assertEqual((final / "complete.dat").read_text(), "complete")
        stage.mkdir()
        with self.assertRaisesRegex(InputError, "already exists"):
            publish_directory(stage, final)
        with patch.object(Path, "rename", side_effect=error) as locked, patch("treated_plots.time.sleep"):
            with self.assertRaises(PermissionError):
                publish_directory(stage, self.folder / "new")
        self.assertEqual(locked.call_count, 6)


if __name__ == "__main__":
    unittest.main()
