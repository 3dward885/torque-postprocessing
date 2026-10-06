"""Per-file presentation settings and transactional selected-quantity export."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from io_profiles import InputError, sha256
from treated_plots import normalization, molar_text, suggested_rotation, publish_directory

FIELDS = {"version", "input_sha256", "quantity", "method", "mass_mg",
          "molar_mass_g_mol", "amount_mol", "rotation", "source", "accepted_utc"}


def default_output(source_hash, filename=""):
    return {"version": 1, "input_sha256": source_hash, "quantity": "torque",
            "method": "mass", "mass_mg": "", "molar_mass_g_mol": "", "amount_mol": "",
            "rotation": suggested_rotation(filename), "source": "User-entered sample quantities",
            "accepted_utc": ""}


def validate_output(block, source_hash):
    if not isinstance(block, dict) or set(block) != FIELDS:
        raise InputError("Invalid output settings: unknown or missing fields.")
    if type(block["version"]) is not int or block["version"] != 1:
        raise InputError("Unsupported output settings version.")
    if any(not isinstance(block[k], str) for k in FIELDS - {"version"}):
        raise InputError("Output settings values must be text.")
    if block["input_sha256"] != source_hash or not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        raise InputError("Sample quantities do not match this raw file.")
    if block["method"] not in ("mass", "amount"):
        raise InputError("Choose sample mass and molar mass, or amount in moles.")
    if block["rotation"] and not re.fullmatch(r"[1-9]\d*", block["rotation"]):
        raise InputError("Rotation must be a positive integer.")
    normalization(block)
    return deepcopy(block)


def accepted_output(block, source_hash, result=None):
    block = validate_output(block, source_hash)
    if result is not None and block["quantity"] == "molar":
        molar_text(result, normalization(block))
    block["accepted_utc"] = datetime.now(timezone.utc).isoformat()
    return block


def output_paths(path, block):
    path = Path(path).resolve()
    if path.suffix.lower() != ".dat":
        raise InputError("Choose a DAT output filename.")
    paths = [path]
    if block["quantity"] == "molar":
        stem = path.stem
        if stem.endswith("_molar"):
            raise InputError("Choose the ordinary torque filename; the separate molar name is added automatically.")
        stem = stem[:-8] if stem.endswith("_treated") else stem
        paths.append(path.with_name(stem + "_molar.dat"))
    return paths


def _metadata(run, result, block, names):
    from storage import json_text
    norm = normalization(block)
    (run / "output.json").write_text(json_text({"settings": block, "normalization": norm,
        "files": names}), encoding="utf-8")
    # Absolute input path remains correct after the staging directory is moved.
    (run / "replay.json").write_text(json_text({"session_version": "1.0", "files": [{
        "path": result["input"]["path"], "settings": result["config"], "output": block}]}), encoding="utf-8")
    provenance = json.loads((run / "provenance.json").read_text(encoding="utf-8"))
    provenance["output_settings"] = block
    provenance["normalization"] = norm
    hashes = {p.name: sha256(p) for p in run.iterdir()
              if p.is_file() and p.name not in ("provenance.json", "SHA256SUMS.txt")}
    provenance["output_sha256"] = hashes
    (run / "provenance.json").write_text(json_text(provenance), encoding="utf-8")
    hashes["provenance.json"] = sha256(run / "provenance.json")
    (run / "SHA256SUMS.txt").write_text("".join(f"{h}  {n}\n" for n, h in sorted(hashes.items())), encoding="utf-8")


def _prepare(result, block, parent, run_name=None):
    from storage import export_run
    block = validate_output(block, result["input"]["sha256"])
    norm = normalization(block)
    text = molar_text(result, norm) if block["quantity"] == "molar" else None
    run = Path(export_run(result, parent, run_name))
    if text is not None:
        (run / "molar.dat").write_text(text, encoding="utf-8", newline="")
    return run, block


def save_output_dat(result, path, block):
    block = validate_output(block, result["input"]["sha256"])
    paths = output_paths(path, block)
    details = paths[0].with_name(paths[0].name + ".details")
    reserved = paths + [p.with_name(p.name + ".details") for p in paths]
    if any(p.exists() for p in reserved):
        raise InputError("Output collision: choose a new filename. Existing files are never overwritten.")
    if Path(result["input"]["path"]).resolve() in reserved:
        raise InputError("Choose an output different from the raw input.")
    paths[0].parent.mkdir(parents=True, exist_ok=True)
    published = []
    details_published = False
    with tempfile.TemporaryDirectory(prefix=".output_", dir=paths[0].parent) as temp:
        run, block = _prepare(result, block, temp)
        sources = [run / "treated.dat"] + ([run / "molar.dat"] if len(paths) == 2 else [])
        _metadata(run, result, block, [{"filename": p.name, "units": units, "sha256": sha256(src)}
            for p, src, units in zip(paths, sources, ("N m", "N m/mol"))])
        try:
            # Windows rename and hard links both refuse to overwrite existing targets.
            publish_directory(run, details)
            details_published = True
            for src, dst in zip(sources, paths):
                os.link(details / src.name, dst)
                published.append(dst)
        except BaseException:
            for p in published:
                p.unlink()
            if details_published:
                shutil.rmtree(details)
            raise
    return str(paths[0])


def export_output_run(result, parent, run_name, block):
    parent = Path(parent).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".output_", dir=parent) as temp:
        run, block = _prepare(result, block, temp, run_name)
        _metadata(run, result, block, [{"filename": p.name, "units": units, "sha256": sha256(p)}
            for p, units in ((run / "treated.dat", "N m"), (run / "molar.dat", "N m/mol")) if p.exists()])
        final = parent / run.name
        publish_directory(run, final)
    return str(final)
