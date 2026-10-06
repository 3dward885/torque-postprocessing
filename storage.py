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
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
    writer.writerow(["Temperature (K)", "Magnetic Field (T)", "Sample Position (deg)", "Torque (N m)"])
    for row in result["output_rows"]:
        if len(row) != 4:
            raise InputError("Treated data must have exactly four torque-only columns.")
        writer.writerow(row)
    return stream.getvalue()


def save_dat(result, path):
    """Publish the audit folder first, then the DAT; never replace existing paths."""
    from pipeline import verify_export
    verify_export(result)
    path = Path(path).resolve()
    raw = Path(result["input"]["path"]).resolve()
    if path.suffix.lower() != ".dat" or path == raw:
        raise InputError("Choose a .dat output path different from the raw input.")
    sidecar = path.with_name(path.name + ".details")
    if path.exists() or sidecar.exists():
        raise InputError("Output collision: choose a new filename. Existing files are never overwritten.")
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(".pending_" + uuid.uuid4().hex)
    published = None
    try:
        # Reuse the existing transactional export and all its preservation checks.
        run = Path(export_run(result, path.parent))
        published = run
        pending.write_bytes((run / "treated.dat").read_bytes())
        run.rename(sidecar)
        published = sidecar
        # Windows rename refuses to overwrite; link gives the same guarantee elsewhere.
        os.link(pending, path)
        return str(path)
    except BaseException:
        if published and published.exists():
            shutil.rmtree(published)
        raise
    finally:
        pending.unlink(missing_ok=True)


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
        from treated_plots import publish_directory
        publish_directory(stage, final)
        return str(final)
    except BaseException:
        # Remove only the unique staging directory created by this call.
        shutil.rmtree(stage)
        raise


def save_session(path, entries):
    parent = Path(path).resolve().parent
    files = []
    for entry in entries:
        raw, config = entry[:2]
        raw = Path(raw).resolve()
        try:
            relative = os.path.relpath(raw, parent)
        except ValueError:
            relative = str(raw)
        item = {"path": relative, "settings": config}
        if len(entry) == 3:
            from output_settings import validate_output
            item["output"] = validate_output(entry[2], config["input_sha256"])
        files.append(item)
    atomic_json(path, {"session_version": "1.0", "files": files})


def load_session(path, include_output=False):
    doc = load_config(path)
    if doc.get("session_version") != "1.0" or not isinstance(doc.get("files"), list):
        raise InputError("Expected a version 1.0 session with a files list.")
    try:
        entries = []
        for item in doc["files"]:
            raw = str((Path(path).resolve().parent / item["path"]).resolve())
            cfg = item["settings"]
            from output_settings import validate_output
            output = validate_output(item["output"], cfg["input_sha256"]) if "output" in item else None
            entries.append((raw, cfg, output) if include_output else (raw, cfg))
        return entries
    except (KeyError, TypeError) as exc:
        raise InputError("Each session file needs a path and settings object.") from exc
