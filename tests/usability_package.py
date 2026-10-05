"""Verify both release archives and replay their extracted application copies."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def extract(archive_path, destination):
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        manifest = json.loads(archive.read("PACKAGE_MANIFEST.json"))
        for name, expected in manifest["entries"].items():
            target = (destination/name).resolve()
            assert target.is_relative_to(destination.resolve()), name
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected, name
        archive.extractall(destination)
    return manifest


def main(archives, output, before):
    output.mkdir(parents=True, exist_ok=False)
    source = output/"source"
    full = extract(archives/"Torque_Postprocessing_v1.3_source.zip", source)
    update_dir = output/"update_files"
    update = extract(archives/"Torque_Postprocessing_v1.3_GitHub_update.zip", update_dir)
    assert not update["required_removals"]
    for name in update["entries"]:
        assert Path(name).parts[0] not in (".git", ".venv", "validation", "evidence", "runs", "__pycache__")
        assert not name.endswith(".dat"), name
    overlay = output/"updated_v12"
    shutil.copytree(before.parent/"before/source", overlay)
    shutil.copytree(update_dir, overlay, dirs_exist_ok=True)
    snapshot = json.loads(before.read_text(encoding="utf-8"))
    assert update["base_source_sha256"] == snapshot["source_sha256"]
    assert full["entries"]["help_content.json"] == update["entries"]["help_content.json"]
    reports = {}
    outside = output/"unrelated_cwd"
    outside.mkdir()
    for label, folder in (("source", source), ("update_overlay", overlay)):
        result = {"DATs": {}}
        for name, prior in snapshot["results"].items():
            target = outside/(label+"_"+name+".dat")
            command = [sys.executable, str(folder/"cli.py"), "process", "--session",
                       str(folder/"examples"/(name+".json")), "--dat", str(target)]
            done = subprocess.run(command, cwd=outside, capture_output=True, text=True)
            assert done.returncode == 0, done.stdout+done.stderr
            assert digest(target) == prior["dat_sha256"], name
            result["DATs"][name] = {"rows": prior["rows"], "sha256": digest(target)}
        code = '''import sys, json, tkinter as tk
sys.path.insert(0, sys.argv[1])
from app import App
from ui_help import help_topics, topics_flat
root=tk.Tk(); root.withdraw()
app=App(root); app.show_help(); root.update()
assert root.state() == 'withdrawn'
assert app.help_window.window.state() == 'withdrawn'
assert '1.3' in root.title()
app.help_window.tree.item('options', open=True)
app.help_window.tree.selection_set('temperature_list')
app.help_window.select()
assert 'spaces or commas' in app.help_window.text.get('1.0','end')
print(json.dumps({'help_topics':len(list(topics_flat())), 'hidden_app_launch':True, 'outside_cwd':True}))
app.help_window.close(); app.close()
assert not root.tk.call('after','info')
'''
        done = subprocess.run([sys.executable, "-c", code, str(folder)], cwd=outside,
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stdout+done.stderr
        result.update(json.loads(done.stdout))
        reports[label] = result
    summary = {"status": "PASS", "copies": reports, "archives": {},
               "update_compared_to_saved_v12": True, "required_removals": [],
               "windows_withdrawn": True, "desktop_input": False}
    for name in ("Torque_Postprocessing_v1.3_source.zip", "Torque_Postprocessing_v1.3_GitHub_update.zip"):
        path = archives/name
        summary["archives"][name] = {"sha256": digest(path), "bytes": path.stat().st_size}
    (output/"report.json").write_text(json.dumps(summary, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archives", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--before", type=Path, default=ROOT/"validation/usability_v1.3/before.json")
    args = parser.parse_args()
    main(args.archives.resolve(), args.output.resolve(), args.before.resolve())
