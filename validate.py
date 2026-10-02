"""Read-only comparison of saved DATs; never imported by the numerical core."""
from __future__ import annotations
import csv
from decimal import Decimal, localcontext
from pathlib import Path
import numpy as np
from io_profiles import InputError, decimal_value, sha256
from storage import load_config


def read_treated(path):
    records = list(csv.reader(Path(path).read_text(encoding="utf-8-sig").splitlines(), delimiter="\t"))
    if not records:
        raise InputError("Empty treated file.")
    canonical = ["Temperature (K)", "Magnetic Field (T)", "Sample Position (deg)", "Torque (N m)", "Torque molar (N m/mol)"]
    old = ["Temperature", "Magnetic Field", "Sample Position", "Torque", "Torque molar"]
    new1 = ["Temperature", "Magnetic Field", "Sample Posiiton", "Torque", "Torque Molar"]
    width = len(records[0])
    if width not in (4, 5):
        raise InputError("Treated data must contain four or five columns.")
    start = 1
    if records[0] == canonical[:width]:
        pass
    elif records[0] in (old[:width], new1[:width]):
        if len(records) < 2 or records[1] != ["K", "T", "Deg", "Nm", "Nm/mol"][:width]:
            raise InputError("Treated units do not match K/T/Deg/Nm[/Nm/mol].")
        start = 2
        if len(records) > 2 and records[2][:4] == [""] * 4:
            if width != 5 or len(records[2]) != 5 or not records[2][4].startswith("D*"):
                raise InputError("Malformed formula annotation.")
            decimal_value(records[2][4][2:], "Formula multiplier", True)
            start = 3
    else:
        raise InputError("Unsupported treated headers/units.")
    rows = []
    for line, values in enumerate(records[start:], start + 1):
        if len(values) != width:
            raise InputError(f"Treated line {line}: expected {width} fields.")
        rows.append([decimal_value(v, f"Treated line {line}") for v in values])
    if not rows:
        raise InputError("No treated measurements.")
    return rows, records[:start]


def _metrics(a, b):
    with localcontext() as context:
        context.prec = 100
        residual = np.array([float(x - y) for x, y in zip(a, b)])
        span = float(max(b) - min(b))
    return {"max_abs": float(np.max(np.abs(residual))),
            "RMSE": float(np.sqrt(np.mean(residual ** 2))),
            "mean_residual": float(np.mean(residual)),
            "relative_to_pass_range": float(np.max(np.abs(residual)) / span) if span else None,
            "reference_range": span}


def compare(output, reference, provenance=None):
    a, ah = read_treated(output)
    b, bh = read_treated(reference)
    if len(a) != len(b) or len(a[0]) != len(b[0]):
        raise InputError(f"Comparison shape differs: output {len(a)}x{len(a[0])}, reference {len(b)}x{len(b[0])}. No rows were cropped.")
    if any(x[:3] != y[:3] for x, y in zip(a, b)):
        raise InputError("A-C coordinates or acquisition order differ. Reference was not aligned, regridded or reordered.")
    if provenance is None:
        candidate = Path(output).with_name("provenance.json")
        provenance = load_config(candidate) if candidate.exists() else None
    if provenance:
        if provenance["output_sha256"]["treated.dat"] != sha256(output):
            raise InputError("Saved DAT differs from its provenance hash.")
        bounds = [(p["pass_id"], p["output_start"], p["rows"]) for p in provenance["passes"]]
        if [i for _, start, count in bounds for i in range(start, start + count)] != list(range(len(a))):
            raise InputError("Provenance pass boundaries do not cover the exported rows exactly.")
    else:
        bounds, start = [], 0
        for i in range(1, len(a) + 1):
            if i == len(a) or a[i][0] != a[i-1][0] or a[i][2] > a[i-1][2]:
                bounds.append((f"P{len(bounds)+1:03d}", start, i-start))
                start = i
    columns = "ABCDE"[:len(a[0])]
    result = {"rows": len(a), "exact_cells": {c: sum(x[i] == y[i] for x, y in zip(a, b)) for i, c in enumerate(columns)},
              "exact_rows": sum(x == y for x, y in zip(a, b)), "passes": [],
              "output_sha256": sha256(output), "reference_sha256": sha256(reference),
              "header_equal": ah == bh, "byte_identical": Path(output).read_bytes() == Path(reference).read_bytes(),
              "residual_definition": "saved output minus reference", "units": {"D": "N m", "E": "N m/mol"}}
    for pid, start, count in bounds:
        aa, bb = a[start:start+count], b[start:start+count]
        result["passes"].append({"id": pid, "rows": count, "exact_rows": sum(x == y for x, y in zip(aa, bb)),
                                **{c: _metrics([r[j] for r in aa], [r[j] for r in bb])
                                   for j, c in enumerate(columns) if j >= 3}})
    result["exact_passes"] = sum(p["rows"] == p["exact_rows"] for p in result["passes"])
    result["pass_count"] = len(bounds)
    for j, c in enumerate(columns):
        if j >= 3:
            metrics = _metrics([r[j] for r in a], [r[j] for r in b])
            metrics.pop("relative_to_pass_range")
            ratios = [p[c]["relative_to_pass_range"] for p in result["passes"] if p[c]["relative_to_pass_range"] is not None]
            metrics["max_error_over_own_pass_range"] = max(ratios) if ratios else None
            result[c] = metrics
    with localcontext() as context:
        context.prec = 100
        result["residuals"] = [{"row": i+1, "angle_deg": str(x[2]), "D_Nm": str(x[3]-y[3]),
                                **({"E_Nm_per_mol": str(x[4]-y[4])} if len(x) == 5 else {})}
                               for i, (x, y) in enumerate(zip(a, b))]
    return result

