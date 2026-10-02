"""Configuration and transactional run export."""
from __future__ import annotations
import csv
import importlib.metadata
import io
import json
import os
import platform
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from io_profiles import APP_VERSION, InputError, sha256


def json_text(value):
    return json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False, sort_keys=True) + "\n"


def atomic_json(path, value):
    path = Path(path)
    if path.suffix.lower() != ".json":
        raise InputError("Configuration/report filename must end in .json.")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json_text(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def load_config(path):
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if not isinstance(config, dict):
            raise ValueError("Expected a JSON object")
        return config
    except (ValueError, UnicodeError) as exc:
        raise InputError(f"Invalid JSON configuration: {exc}") from exc


def treated_text(result):
    fmt = result["config"]["export_format"]
    factor = result["molar"]["factor_mol_inverse"]
    molar = factor is not None
    if fmt == "canonical":
        names = ["Temperature (K)", "Magnetic Field (T)", "Sample Position (deg)", "Torque (N m)"]
        if molar:
            names.append("Torque molar (N m/mol)")
        headers = [names]
    else:
        names = ["Temperature", "Magnetic Field", "Sample Position", "Torque", "Torque molar"]
        if fmt == "new_rot1":
            names[2], names[4] = "Sample Posiiton", "Torque Molar"
        units = ["K", "T", "Deg", "Nm", "Nm/mol"]
        headers = [names if molar else names[:4], units if molar else units[:4]]
        if fmt != "new_rot1" and molar:
            headers.append(["", "", "", "", "D*" + factor])
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
    writer.writerows(headers)
    writer.writerows(result["output_rows"])
    return stream.getvalue()


def environment():
    versions = {"python": platform.python_version(), "platform": platform.platform()}
    for package in ("numpy", "matplotlib"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "unavailable"
    return versions


def export_run(result, output_folder, run_name=None):
    """Publish a complete directory in one rename; raw inputs can never be replaced."""
    from pipeline import verify_export
    verify_export(result)
    raw = Path(result["input"]["path"])
    if sha256(raw) != result["input"]["sha256"]:
        raise InputError("Raw input changed since processing. Re-import and process again.")
    root = Path(output_folder).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if run_name is None:
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw.stem)[:70]
        run_name = f"{stem}_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:8]}"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,149}", run_name) or run_name.endswith("."):
        raise InputError("Run name must be a simple filename of letters, digits, dots, underscores or hyphens.")
    final = root / run_name
    if final.exists():
        raise InputError(f"Output collision: {final}. Choose a new run name; nothing was overwritten.")
    stage = root / (".pending_" + uuid.uuid4().hex)
    stage.mkdir()
    try:
        (stage / "treated.dat").write_text(treated_text(result), encoding="utf-8", newline="")
        (stage / "settings.json").write_text(json_text(result["config"]), encoding="utf-8")
        (stage / "row_ledger.json").write_text(json_text(result["ledger"]), encoding="utf-8")
        shutil.copyfile(raw, stage / "raw_input.dat")
        if sha256(raw) != result["input"]["sha256"] or sha256(stage / "raw_input.dat") != result["input"]["sha256"]:
            raise InputError("Raw input changed during export. No successful run was published.")
        hashes = {p.name: sha256(p) for p in sorted(stage.iterdir())}
        provenance = {k: v for k, v in result.items() if k not in ("ledger", "output_rows")}
        provenance.update(app_version=APP_VERSION, created_utc=datetime.now(timezone.utc).isoformat(),
                          environment=environment(), output_sha256=hashes,
                          raw_hash_unchanged=True, complete=True)
        code_root = Path(__file__).resolve().parent
        provenance["code_sha256"] = {p.name: sha256(p) for p in sorted(code_root.glob("*.py"))}
        (stage / "provenance.json").write_text(json_text(provenance), encoding="utf-8")
        hashes["provenance.json"] = sha256(stage / "provenance.json")
        (stage / "SHA256SUMS.txt").write_text("".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items())), encoding="utf-8")
        if final.exists():
            raise InputError(f"Output collision: {final}.")
        stage.rename(final)
        return str(final)
    except BaseException:
        # Remove only the unique staging directory created by this call.
        shutil.rmtree(stage)
        raise


def save_session(path, entries):
    parent = Path(path).resolve().parent
    files = []
    for raw, config in entries:
        raw = Path(raw).resolve()
        try:
            relative = os.path.relpath(raw, parent)
        except ValueError:
            relative = str(raw)
        files.append({"path": relative, "settings": config})
    atomic_json(path, {"session_version": "1.0", "files": files})


def load_session(path):
    doc = load_config(path)
    if doc.get("session_version") != "1.0" or not isinstance(doc.get("files"), list):
        raise InputError("Expected a version 1.0 session with a files list.")
    try:
        return [(str((Path(path).resolve().parent / item["path"]).resolve()), item["settings"]) for item in doc["files"]]
    except (KeyError, TypeError) as exc:
        raise InputError("Each session file needs a path and settings object.") from exc

