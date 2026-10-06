"""Group committed treated samples for presentation; never fit or recenter."""
from collections import OrderedDict
from decimal import Decimal, DecimalException, InvalidOperation, localcontext
from datetime import datetime, timezone
import csv
import hashlib
import io
import math
from pathlib import Path
import re
import shutil
import time
import uuid

from io_profiles import APP_VERSION, InputError, sha256
from pipeline import verify_export
from storage import json_text, treated_text

COLORS = ("#000000", "#0072B2", "#D55E00", "#009E73", "#CC79A7", "#56B4E9", "#A6761D")
MARKERS = ("o", "s", "^", "D", "v", "P", "X")


def suggested_rotation(filename):
    match = re.search(r"(?i)rot(?:ation)?[ _-]*(\d+)", Path(filename).stem)
    return match.group(1) if match else ""


def positive(value, label):
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise InputError(f"{label}: enter a positive finite number.") from None
    if not number.is_finite() or number <= 0:
        raise InputError(f"{label}: enter a positive finite number.")
    return number


def normalization(choice):
    mode = choice.get("quantity", "torque")
    if mode == "torque":
        return {"quantity": "torque", "units": "N m", "factor_mol_inverse": None}
    if mode != "molar":
        raise InputError("Choose torque or molar torque.")
    try:
        with localcontext() as context:
            context.prec = 50
            if choice.get("method") == "mass":
                mass = positive(choice.get("mass_mg", ""), "Sample mass (mg)")
                molar_mass = positive(choice.get("molar_mass_g_mol", ""), "Molar mass (g/mol)")
                amount = mass / Decimal(1000) / molar_mass
                factor = molar_mass * Decimal(1000) / mass
                values = {"method": "mass", "mass_mg": str(mass), "molar_mass_g_mol": str(molar_mass)}
            elif choice.get("method") == "amount":
                amount = positive(choice.get("amount_mol", ""), "Amount (mol)")
                factor = Decimal(1) / amount
                values = {"method": "amount", "amount_mol": str(amount)}
            else:
                raise InputError("Choose sample mass and molar mass, or amount in moles.")
    except DecimalException:
        raise InputError("Normalization is outside the supported plotting range.") from None
    if not math.isfinite(float(factor)) or float(factor) == 0:
        raise InputError("Normalization is outside the supported plotting range.")
    return {"quantity": "molar", "units": "N m/mol", **values, "derived_amount_mol": str(amount),
            "factor_mol_inverse": str(factor), "factor_precision_digits": 50,
            "source": choice.get("source", "User-entered sample normalization")}


def converted_token(token, norm):
    if norm["quantity"] == "torque":
        return token
    value, factor = Decimal(token), Decimal(norm["factor_mol_inverse"])
    with localcontext() as context:
        context.prec = max(50, len(value.as_tuple().digits) + len(factor.as_tuple().digits) + 2)
        result = value * factor
    if not math.isfinite(float(result)) or (result != 0 and float(result) == 0):
        raise InputError("A molar torque value is outside the supported plotting range.")
    return str(result)


def decimal_label(value):
    value = Decimal(value)
    return format(value, "f").rstrip("0").rstrip(".") if value and value.as_tuple().exponent < 0 else format(value, "f")


def grouped_samples(result, choice):
    verify_export(result)
    rotation = str(choice.get("rotation", "")).strip()
    if not re.fullmatch(r"[1-9]\d*", rotation):
        raise InputError("Enter a positive integer rotation number for each selected file.")
    norm = normalization(choice)
    groups = OrderedDict()
    for pred in result["passes"]:
        start, count = pred["output_start"], pred["rows"]
        rows = result["output_rows"][start:start + count]
        temperatures = {Decimal(r[0]) for r in rows}
        if len(temperatures) != 1:
            raise InputError(f"{pred['pass_id']}: cannot group a scan with unresolved temperatures.")
        temperature = next(iter(temperatures))
        field = [Decimal(r[1]) for r in rows]
        key = (min(field), max(field))
        label = decimal_label(key[0]) if key[0] == key[1] else f"{decimal_label(key[0])}–{decimal_label(key[1])}"
        series = {"pass_id": pred["pass_id"], "identity": pred["identity"], "field": key,
                  "label": f"B = {label} T", "angles": [float(r[2]) for r in rows],
                  "tokens": [converted_token(r[3], norm) for r in rows]}
        groups.setdefault(temperature, []).append(series)
    if not groups:
        raise InputError("No treated signal samples are available.")
    return rotation, norm, groups


def grouped_figure(rotation, temperature, series, norm, field_styles):
    import matplotlib as mpl
    from matplotlib.figure import Figure
    from matplotlib.ticker import AutoMinorLocator
    from plots import style, font_status, angle_limits
    if not font_status().startswith("Arial Regular verified:"):
        raise InputError(font_status())
    with mpl.rc_context(style()):
        fig = Figure(figsize=(8, 6), dpi=100)
        ax = fig.add_subplot()
        fig.subplots_adjust(left=.19, bottom=.18, right=.76, top=.87)
        seen = set()
        for item in series:
            index = field_styles[item["field"]]
            ax.plot(item["angles"], [float(v) for v in item["tokens"]], linestyle="none",
                    marker=MARKERS[(index // len(COLORS)) % len(MARKERS)], markersize=5,
                    color=COLORS[index % len(COLORS)],
                    label=item["label"] if item["field"] not in seen else "_nolegend_")
            seen.add(item["field"])
        ax.set_xlabel("Sample position (deg)")
        ax.set_ylabel("Torque (N m)" if norm["quantity"] == "torque" else "Molar torque (N m/mol)")
        ax.set_title(f"Rotation {rotation}, T = {decimal_label(temperature)} K", fontsize=18, fontweight="normal")
        angle_limits(ax, [x for s in series for x in s["angles"]])
        ax.xaxis.set_minor_locator(AutoMinorLocator(2))
        ax.yaxis.set_minor_locator(AutoMinorLocator(2))
        dense = len(seen) > 6 or any(len(s["label"]) > 18 for s in series)
        ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(1.01, 1), borderaxespad=0,
                  fontsize=9 if dense else 12)
        return fig


def molar_text(result, norm):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
    writer.writerow(["Temperature (K)", "Magnetic Field (T)", "Sample Position (deg)", "Molar Torque (N m/mol)"])
    for row in result["output_rows"]:
        writer.writerow([*row[:3], converted_token(row[3], norm)])
    return stream.getvalue()


def publish_directory(stage, final):
    # A Windows file watcher can briefly hold a newly written directory open.
    # This runs in the export worker; never overwrite an existing destination.
    for attempt in range(6):
        if final.exists():
            raise InputError("Plot output already exists. Choose a new export.")
        try:
            stage.rename(final)
            return
        except PermissionError as exc:
            if getattr(exc, "winerror", None) not in (5, 32) or attempt == 5:
                raise
            time.sleep(.05 * 2 ** attempt)


def export_treated_plots(entries, parent):
    """entries contains (processed result, user plot choices), independently per file."""
    from plots import font_status
    prepared = []
    for result, choice in entries:
        if "version" in choice:
            from output_settings import validate_output
            choice = validate_output(choice, result["input"]["sha256"])
        if sha256(result["input"]["path"]) != result["input"]["sha256"]:
            raise InputError("Raw input changed since processing. Reprocess before exporting plots.")
        prepared.append((result, choice, grouped_samples(result, choice)))
    if not prepared:
        raise InputError("Select at least one processed file.")
    parent = Path(parent).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    name = f"treated_plots_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:8]}"
    stage, final = parent / (".pending_" + uuid.uuid4().hex), parent / name
    stage.mkdir()
    details = stage / "plots.details"
    details.mkdir()
    manifest = {"app_version": APP_VERSION, "plot_export_version": 1, "files": [], "font": font_status(),
                "figure": {"inches": [8, 6], "dpi": 300, "format": "JPEG", "background": "white"}}
    try:
        sessions = []
        for index, (result, choice, (rotation, norm, groups)) in enumerate(prepared, 1):
            stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(result["input"]["filename"]).stem)[:50]
            prefix = f"{index:02d}_{stem}_Rot{rotation}"
            field_styles = {field: i for i, field in enumerate(sorted({s["field"] for series in groups.values() for s in series}))}
            item = {"source": result["input"], "choices": choice, "normalization": norm, "plots": [],
                    "treated_DAT_sha256": hashlib.sha256(treated_text(result).encode("utf-8")).hexdigest()}
            for temperature, series in groups.items():
                temp = decimal_label(temperature).replace(".", "p").replace("-", "minus")
                filename = f"{prefix}_T{temp}K_{norm['quantity']}.jpg"
                figure = grouped_figure(rotation, temperature, series, norm, field_styles)
                figure.savefig(stage / filename, dpi=300, facecolor="white", format="jpeg",
                               pil_kwargs={"quality": 95, "subsampling": 0})
                figure.clear()
                item["plots"].append({"filename": filename, "temperature_K": str(temperature),
                                      "pass_ids": [s["pass_id"] for s in series],
                                      "points": sum(len(s["tokens"]) for s in series), "sha256": sha256(stage / filename)})
            manifest["files"].append(item)
            sessions.append((result["input"]["path"], result["config"], choice))
        # Raw paths are saved absolutely because the staging directory is renamed.
        (details / "settings.json").write_text(json_text({"session_version": "1.0", "files": [
            {"path": str(Path(raw).resolve()), "settings": config, **({"output": choice} if "version" in choice else {})}
            for raw, config, choice in sessions]}), encoding="utf-8")
        (details / "plots.json").write_text(json_text(manifest), encoding="utf-8")
        for result, _, _ in prepared:
            if sha256(result["input"]["path"]) != result["input"]["sha256"]:
                raise InputError("Raw input changed during plot export. Reprocess before exporting.")
        publish_directory(stage, final)
        return str(final)
    except BaseException:
        shutil.rmtree(stage)
        raise
