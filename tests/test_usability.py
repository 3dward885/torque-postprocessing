"""v1.3 input and help checks; fixture temperatures are software examples."""
import contextlib
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cli import main as cli_main, run_entry
from input_fields import temperature_list
from io_profiles import InputError, TSV_HEADER, read_raw, configure_acquisition
from pipeline import default_config
from storage import load_session, save_session
from test_core import synthetic


class UsabilityTests(unittest.TestCase):
    def test_temperature_separators_and_decimal_tokens(self):
        expected = ["7.375", "13.625", "2.01e2"]
        for text in ("7.375 13.625 2.01e2", "7.375, 13.625, 2.01e2", " 7.375,\t13.625\n2.01e2 "):
            self.assertEqual(temperature_list(text), expected)
        self.assertEqual(temperature_list(" \t\n"), [])

    def test_invalid_temperature_list_entries(self):
        for text in ("NaN", "Infinity", "1e999", "7.375 K", "7.375;13.625", "7.375 -", "7.375 7.3750"):
            with self.subTest(text=text), self.assertRaises(InputError):
                temperature_list(text)

    def write(self, folder, targets):
        path = folder / "synthetic.dat"
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
            writer.writerow(TSV_HEADER)
            for target in targets:
                writer.writerows([[target, *row[1:]] for row in synthetic()])
        return path

    def test_cli_lists_save_load_and_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            raw = self.write(folder, ("7.375", "13.625"))
            outputs = []
            for i, value in enumerate(("7.375,13.625", "7.375 13.625", "7.375,  13.625")):
                path = folder / f"output{i}.dat"
                with contextlib.redirect_stdout(io.StringIO()):
                    status = cli_main(["process", "--raw", str(raw), "--setpoints", value, "--field-condition", "changing", "--dat", str(path)])
                self.assertEqual(status, 0)
                outputs.append(path.read_bytes())
                settings = json.loads(path.with_name(path.name + ".details").joinpath("settings.json").read_text())
                self.assertEqual(settings["acquisition"]["temperature_setpoints_K"], ["7.375", "13.625"])
                self.assertEqual(settings["profile"]["temperature_tolerance_K"], "0.2")
                session = folder / f"session{i}.json"
                save_session(session, [(str(raw), settings)])
                src, loaded = load_session(session)[0]
                self.assertEqual(loaded, settings)
                self.assertEqual(run_entry(src, loaded)["rows"], 82)
            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(outputs[1], outputs[2])

    def test_nonuniform_targets_and_override_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            raw = self.write(Path(temp), ("7.375", "13.625"))
            obj = read_raw(raw)
            cfg = default_config(obj)
            cfg["acquisition"]["temperature_setpoints_K"] = temperature_list("7.4 13.625")
            first = obj.passes[0]
            cfg["acquisition"]["scans"][first.id] = {
                "identity": first.identity, "temperature_K": "7.375", "source": "Explicit software fixture assignment"}
            configured = configure_acquisition(obj, cfg["acquisition"])
            self.assertEqual([str(p.T) for p in configured.passes], ["7.375", "7.4", "13.625", "13.625"])
            self.assertFalse(any(p.issue for p in configured.passes))
            cfg["acquisition"]["temperature_setpoints_K"] = temperature_list("7.3 7.4 13.625")
            configured = configure_acquisition(obj, cfg["acquisition"])
            self.assertEqual(str(configured.passes[0].T), "7.375")
            self.assertIn("Ambiguous", configured.passes[1].issue)

    def test_help_loads_outside_project_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            code = "import sys; sys.path.insert(0, sys.argv[1]); from ui_help import topics_flat, help_tip; topics=list(topics_flat()); assert len({t['id'] for t in topics})==len(topics); assert all(t['text'].strip() for t in topics); assert 'optional' in help_tip('center_zero'); print(len(topics))"
            done = subprocess.run([sys.executable, "-c", code, str(ROOT)], cwd=temp, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertGreater(int(done.stdout), 50)


if __name__ == "__main__":
    unittest.main()
