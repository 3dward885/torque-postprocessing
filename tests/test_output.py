"""Output choices never change processing or ordinary torque."""
import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout

import test_treated_plots as fixtures
from cli import main
from io_profiles import InputError, sha256
from output_settings import (default_output, validate_output, accepted_output,
                             save_output_dat, output_paths, export_output_run)
from storage import load_session, save_session, treated_text
from treated_plots import normalization, molar_text, converted_token
from plots import make_figure


class OutputTests(unittest.TestCase):
    setUp = fixtures.TreatedPlotTests.setUp
    tearDown = fixtures.TreatedPlotTests.tearDown

    def choice(self):
        return {**default_output(sha256(self.raw), self.raw), **fixtures.MASS}

    def test_session_roundtrip_old_defaults_and_independent_files(self):
        session = self.folder / "settings.json"
        cfg = self.result["config"]
        molar = self.choice()
        torque = {**molar, "quantity": "torque"}
        save_session(session, [(self.raw, cfg, molar), (self.raw, cfg, torque)])
        entries = load_session(session, include_output=True)
        self.assertEqual(entries[0][2], molar)
        self.assertEqual(entries[1][2], torque)
        self.assertEqual(len(load_session(session)[0]), 2)
        save_session(session, [(self.raw, cfg)])
        old = load_session(session, include_output=True)[0][2]
        self.assertIsNone(old)  # The GUI/CLI supplies defaults after importing the actual file.
        session.write_text(json.dumps({"session_version": "1.0", "files": [{
            "path": str(self.raw), "settings": None}]}))
        self.assertIsNone(load_session(session, include_output=True)[0][2])

    def test_binding_unknown_version_fields_and_inactive_values(self):
        for change in ({"version": 9}, {"input_sha256": "0"*64}, {"surprise": 1}, {"quantity": "unknown"}):
            with self.assertRaises(InputError):
                validate_output({**self.choice(), **change}, sha256(self.raw))
        inactive = {**self.choice(), "quantity": "torque", "amount_mol": "not used"}
        self.assertEqual(validate_output(inactive, sha256(self.raw)), inactive)
        with self.assertRaises(InputError):
            validate_output({**inactive, "quantity": "molar", "method": "amount"}, sha256(self.raw))

    def test_invalid_active_and_unrepresentable_values(self):
        for value in ("", "0", "-1", "NaN", "Infinity", "words", "1e9999", "1e-9999"):
            with self.subTest(value=value), self.assertRaises(InputError):
                accepted_output({**self.choice(), "method": "amount", "amount_mol": value},
                                sha256(self.raw), self.result)

    def test_pair_precision_metadata_and_no_accumulation(self):
        saved = copy.deepcopy(self.result)
        block = self.choice()
        path = self.folder / "sample_treated.dat"
        save_output_dat(self.result, path, block)
        self.assertEqual(path.read_text(), treated_text(self.result))
        self.assertEqual((self.folder / "sample_molar.dat").read_text(), molar_text(self.result, normalization(block)))
        details = Path(str(path)+".details")
        restored = load_session(details / "replay.json", include_output=True)[0][2]
        self.assertEqual(restored, block)
        info = json.loads((details / "output.json").read_text())
        self.assertEqual(info["normalization"]["derived_amount_mol"], "0.000005")
        again = self.folder / "again.dat"
        save_output_dat(self.result, again, block)
        self.assertEqual((self.folder / "again_molar.dat").read_bytes(), (self.folder / "sample_molar.dat").read_bytes())
        self.assertEqual(self.result["output_rows"], saved["output_rows"])
        self.assertEqual(self.result["passes"], saved["passes"])
        self.assertEqual(sha256(self.raw), block["input_sha256"])

    def test_collision_and_partial_publish_rollback(self):
        path = self.folder / "sample.dat"
        companion = self.folder / "sample_molar.dat"
        companion.write_text("keep")
        with self.assertRaisesRegex(InputError, "collision"):
            save_output_dat(self.result, path, self.choice())
        self.assertFalse(path.exists())
        self.assertEqual(companion.read_text(), "keep")
        companion.unlink()
        import os
        original = os.link
        calls = []
        def fail_second(src, dst):
            calls.append(dst)
            if len(calls) == 2:
                raise PermissionError("Synthetic publication failure")
            return original(src, dst)
        with patch("output_settings.os.link", side_effect=fail_second), self.assertRaises(PermissionError):
            save_output_dat(self.result, path, self.choice())
        self.assertFalse(path.exists())
        self.assertFalse(Path(str(path)+".details").exists())
        self.assertFalse(list(self.folder.glob(".output_*")))
        with self.assertRaises(InputError):
            save_output_dat(self.result, self.raw, self.choice())

    def test_transient_data_staging_lock_is_retried(self):
        original = Path.rename
        calls = []
        error = PermissionError("Synthetic Windows file-watcher lock")
        error.winerror = 5
        def once(src, dst):
            calls.append(src)
            if len(calls) == 1:
                raise error
            return original(src, dst)
        with patch.object(Path, "rename", once), patch("treated_plots.time.sleep"):
            save_output_dat(self.result, self.folder/"retry.dat", self.choice())
        self.assertGreaterEqual(len(calls), 3)
        self.assertEqual((self.folder/"retry.dat").read_text(), treated_text(self.result))
        self.assertTrue((self.folder/"retry_molar.dat").is_file())

    def test_preview_molar_matches_tokens_and_other_views_keep_units(self):
        p = self.result["passes"][0]
        choice = self.choice()
        before = treated_text(self.result)
        fig = make_figure(self.result, p["pass_id"], "centered", output=choice)
        self.assertEqual(fig.axes[0].get_ylabel(), "Molar torque (N m/mol)")
        self.assertEqual(list(fig.axes[0].lines[0].get_ydata()),
                         [float(converted_token(v, normalization(choice))) for v in p["D"]])
        for view in ("background", "stages"):
            fig = make_figure(self.result, p["pass_id"], view, output=choice)
            self.assertNotIn("/mol", fig.axes[0].get_ylabel())
        self.assertEqual(treated_text(self.result), before)

    def test_cli_replay_selected_outputs_and_old_route(self):
        session = self.folder / "replay.json"
        save_session(session, [(self.raw, self.result["config"], self.choice())])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["process","--session",str(session),"--dat",str(self.folder/"cli.dat")]),0)
            self.assertEqual(main(["process","--session",str(session),"--output",str(self.folder/"runs"),"--run-name","one"]),0)
        self.assertEqual((self.folder/"cli.dat").read_text(), treated_text(self.result))
        self.assertEqual((self.folder/"cli_molar.dat").read_text(), molar_text(self.result, normalization(self.choice())))
        run = self.folder/"runs/one"
        self.assertEqual((run/"molar.dat").read_bytes(), (self.folder/"cli_molar.dat").read_bytes())
        save_session(session, [(self.raw,self.result["config"])])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["process","--session",str(session),"--dat",str(self.folder/"old.dat")]),0)
        self.assertFalse((self.folder/"old_molar.dat").exists())
