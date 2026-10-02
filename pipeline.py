"""Fixed verified numerical core, adapted from the supplied v1.2/previous v1.0.

Only coefficients and the selected centering statistic are calculated from data.
No treated-reference imports, file admission hashes, or mode selector live here.
"""
from __future__ import annotations
from dataclasses import asdict
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import copy
import hashlib
import inspect
import numpy as np
from numpy.polynomial import Polynomial
from io_profiles import InputError, decimal_value, read_raw, _nominal
from baseline import empty_review, review_settings, make_binding, resolve, finalize_pass

RECIPE = {
    "version": "verified-1.2/gui-1.0",
    "degree": 6, "basis": "scaled power", "domain_deg": [0, 200], "window": [-1, 1],
    "angles": "nominal", "weights": "unweighted", "input_significant_digits": 6,
    "input_rounding": "Decimal nearest, ties to even, then binary64",
    "order": "subtract_then_center", "intermediate_rounding": None,
    "D_export": "binary64 format .8g", "E_export": "exact Decimal(exported D) * k",
}


def default_config(acquisition):
    return {
        "version": "1.0", "input_sha256": acquisition.sha256,
        "profile": asdict(acquisition.profile), "centering": "midrange",
        "centering_source": "Application default: midrange",
        "molar": {"mode": "torque", "source": "No sample amount supplied"},
        "export_format": "canonical", "overrides": {}, "support_exceptions": [],
        "note": "", "baseline_review": empty_review(),
    }


def molar_settings(settings):
    mode = settings.get("mode", "torque")
    if mode == "torque":
        return {"mode": mode, "factor_mol_inverse": None, "source": settings.get("source", "")}
    source = settings.get("source", "").strip()
    if not source:
        raise InputError("Molar output needs a source note for the multiplier or sample metadata.")
    with localcontext() as ctx:
        ctx.prec = 50
        if mode == "multiplier":
            factor = decimal_value(settings.get("factor", ""), "Multiplier k (mol^-1)", True)
            amount = None
        elif mode == "amount":
            amount = decimal_value(settings.get("amount_mol", ""), "Sample amount (mol)", True)
            factor = 1 / amount
        elif mode == "mass":
            mass = decimal_value(settings.get("mass", ""), "Sample mass", True)
            molar_mass = decimal_value(settings.get("molar_mass_g_mol", ""), "Molar mass (g/mol)", True)
            unit = settings.get("mass_unit")
            if unit not in ("g", "mg"):
                raise InputError("Mass unit must be g or mg; molar mass must be in g/mol.")
            mass_g = mass if unit == "g" else mass / 1000
            amount = mass_g / molar_mass
            factor = molar_mass / mass_g
        else:
            raise InputError("Molar mode must be torque, multiplier, amount, or mass.")
        decimal_value(factor, "Calculated multiplier", True)
    return {**settings, "factor_mol_inverse": str(factor), "amount_mol_calculated": str(amount) if amount is not None else None,
            "arithmetic_precision": 50, "physical_validation": "User-supplied metadata; not independently verified"}


def validate_config(acquisition, config):
    expected = set(default_config(acquisition))
    if set(config) - expected:
        raise InputError(f"Unknown configuration fields: {sorted(set(config)-expected)}.")
    if config.get("version") != "1.0":
        raise InputError("Unsupported configuration version.")
    if config.get("input_sha256") != acquisition.sha256:
        raise InputError("Saved configuration fingerprint does not match this raw file. Import it as a new file and set its own settings.")
    if config.get("profile") != asdict(acquisition.profile):
        raise InputError("Configuration/profile differs from the imported inventory. Re-import with the selected profile.")
    if config.get("centering") not in ("mean", "midrange"):
        raise InputError("Centering must be mean or midrange.")
    if not config.get("centering_source", "").strip():
        raise InputError("Centering selection needs a source note.")
    if config.get("export_format") not in ("canonical", "previous", "new_rot1", "new_rot2"):
        raise InputError("Unknown export format.")
    passes = {p.id: p for p in acquisition.passes}
    for pid, override in config.get("overrides", {}).items():
        if set(override) - {"identity", "centering", "background", "source"}:
            raise InputError(f"{pid}: unknown override field.")
        if pid not in passes or override.get("identity") != passes[pid].identity or passes[pid].zero:
            raise InputError(f"{pid}: saved per-pass override has a mismatched acquisition identity.")
        if override.get("centering", config["centering"]) not in ("mean", "midrange"):
            raise InputError(f"{pid}: invalid centering override.")
        if not override.get("source", "").strip():
            raise InputError(f"{pid}: override needs a source note.")
        if "background" in override and override["background"] not in [p.id for p in acquisition.candidates(passes[pid])]:
            raise InputError(f"{pid}: selected background is not in this input at the same nominal temperature.")
    for exception in config.get("support_exceptions", []):
        if set(exception) != {"input_sha256", "temperature_K", "outside_angles_deg", "background_support_deg", "source"}:
            raise InputError("Malformed support permission.")
        if exception["input_sha256"] != acquisition.sha256 or not exception["source"].strip():
            raise InputError("Support permission fingerprint/source mismatch; select an explicit general support policy.")
    review_settings(config, {p.id for p in acquisition.passes if not p.zero})
    molar_settings(config["molar"])


def select_background(acquisition, signal, config):
    candidates = acquisition.candidates(signal)
    chosen = config.get("overrides", {}).get(signal.id, {}).get("background")
    if chosen:
        candidates = [p for p in candidates if p.id == chosen]
    if not candidates:
        raise InputError(f"{signal.id}, {signal.T} K: missing same-input, same-temperature background. Supply it in this acquisition.")
    if len(candidates) != 1:
        raise InputError(f"{signal.id}, {signal.T} K: multiple backgrounds ({', '.join(p.id for p in candidates)}). Select Background for this pass and save the association.")
    return candidates[0]


def q6(tokens):
    with localcontext() as ctx:
        ctx.prec = 50
        ctx.rounding = ROUND_HALF_EVEN
        return np.asarray([float(format(Decimal(token), ".6g")) for token in tokens])


def fit_background(background):
    angles = np.asarray([r.angle for r in background.rows], dtype=float)
    values = q6([r.tokens[12] for r in background.rows])
    if len(set(angles)) < 7:
        raise InputError(f"{background.id}: degree 6 needs at least seven unique background angles; found {len(set(angles))}.")
    fit, status = Polynomial.fit(angles, values, 6, domain=[0, 200], full=True)
    if status[1] != 7 or not np.isfinite(fit.coef).all():
        raise InputError(f"{background.id}: background polynomial is rank deficient or nonfinite.")
    info = {
        "background_id": background.id, "source_lines": [r.line for r in background.rows],
        "fit_angles_deg": angles.tolist(), "q6_background_Nm": values.tolist(),
        "degree": 6, "basis": "scaled power", "domain_deg": [0, 200], "window": [-1, 1],
        "coefficients_scaled": fit.coef.tolist(), "rank": int(status[1]),
        "singular_values": status[2].tolist(), "rcond": float(status[3]), "weights": "unweighted",
        "support_deg": [float(min(angles)), float(max(angles))],
        "missing_angles_deg": background.missing,
        "fit_at_samples_Nm": fit(angles).tolist(),
        "fit_residual_Nm": (fit(angles) - values).tolist(),
    }
    return fit, info


def check_support(acquisition, signal, background, config):
    low, high = min(r.angle for r in background.rows), max(r.angle for r in background.rows)
    outside = [r.angle for r in signal.rows if r.angle < low or r.angle > high]
    interior = [r.angle for r in signal.rows if low <= r.angle <= high and r.angle in background.missing]
    info = {"interior_gap_evaluation_angles_deg": interior, "extrapolation_angles_deg": outside,
            "policy": "within measured support"}
    if not outside:
        return info
    allowance = Decimal(acquisition.profile.max_extrapolation_deg)
    if max(max(low - a, a - high, 0) for a in outside) <= allowance:
        info["policy"] = "explicit profile extrapolation"
        info["source"] = acquisition.profile.provenance
        return info
    for permission in config.get("support_exceptions", []):
        if (permission["input_sha256"] == acquisition.sha256
                and Decimal(permission["temperature_K"]) == signal.T
                and permission["background_support_deg"] == [low, high]
                and set(outside) <= set(permission["outside_angles_deg"])):
            return {**info, "policy": "explicit fingerprint-bound reference permission", "source": permission["source"]}
    raise InputError(f"{signal.id}: angles {outside} exceed {background.id} measured support [{low},{high}] deg. Choose a supported background or load a documented profile with an explicit extrapolation allowance.")


def prepare_signal(signal, fit):
    x = np.asarray([r.angle for r in signal.rows], dtype=float)
    r6 = q6([r.tokens[12] for r in signal.rows])
    b = fit(x)
    return x, r6, b, r6 - b


# Only code that defines u participates; plotting, timestamps, molar settings
# and the centering/finalization implementation do not invalidate N m choices.
UPSTREAM_IMPLEMENTATION = hashlib.sha256("\n".join(inspect.getsource(f) for f in
    (read_raw, _nominal, q6, fit_background, prepare_signal, select_background, check_support)).encode()).hexdigest()


def finalize_prediction(pred, config, factor, allow_stale_review=False):
    ordinary = config.get("overrides", {}).get(pred["pass_id"], {})
    mode = ordinary.get("centering", config["centering"])
    offset, review = resolve(config, pred["baseline_binding"], pred["subtracted_Nm"], allow_stale_review)
    if review["status"] == "active" and RECIPE["order"] != "subtract_then_center":
        raise InputError("Interactive baselines support subtract_then_center only.")
    finalized = finalize_pass(pred["subtracted_Nm"], mode, factor, offset)
    effective = review["accepted_record"]["origin"] if review["status"] == "active" else mode
    if review["status"] == "stale":
        effective = "stale override - export blocked"
    pred.update(ordinary_centering=mode, centering=effective,
                centering_source=("User-provided accepted baseline setting" if review["status"] == "active"
                                  else ordinary.get("source", config["centering_source"])),
                centering_constant_Nm=finalized["offset"],
                centered_internal_Nm=finalized["values"].tolist(),
                D=finalized["D"], E=finalized["E"], baseline_review=review)
    return finalized


def review_summary(result):
    blockers = [p["pass_id"] for p in result["passes"] if p["baseline_review"]["status"] == "stale"]
    result["exportable"] = not blockers
    result["export_blockers"] = blockers
    return result


def baseline_ledger(pred):
    return {"ordinary_centering": pred["ordinary_centering"], "centering": pred["centering"],
            "centering_constant_Nm": pred["centering_constant_Nm"],
            "baseline_status": pred["baseline_review"]["status"],
            "baseline_record_pass_id": pred["pass_id"] if pred["baseline_review"]["accepted_record"] else None,
            "c_final_binary64_hex": float(pred["centering_constant_Nm"]).hex(),
            "centering_source": pred["centering_source"]}


def refinalize(result, config, allow_stale_review=False):
    """Replay committed choices from cached u; never reread raw data or refit."""
    review_settings(config, {p["pass_id"] for p in result["passes"]})
    for key in ("input_sha256", "profile", "support_exceptions"):
        if config.get(key) != result["config"].get(key):
            raise InputError("Upstream settings changed; process again before reviewing the baseline.")
    old, new = result["config"].get("overrides", {}), config.get("overrides", {})
    for pid in set(old) | set(new):
        if old.get(pid, {}).get("background") != new.get(pid, {}).get("background"):
            raise InputError("Background changed; process again before baseline review.")
    updated = copy.deepcopy(result)
    updated["config"] = copy.deepcopy(config)
    updated["molar"] = molar_settings(config["molar"])
    ledger = {r["line"]: r for r in updated["ledger"]}
    for pred in updated["passes"]:
        finalize_prediction(pred, config, updated["molar"]["factor_mol_inverse"], allow_stale_review)
        for i, line in enumerate(pred["baseline_binding"]["source_lines"]):
            row = updated["output_rows"][pred["output_start"] + i]
            updated["output_rows"][pred["output_start"] + i] = row[:3] + [pred["D"][i]] + ([pred["E"][i]] if pred["E"] else [])
            ledger[line].update(**baseline_ledger(pred), centered_internal_Nm=pred["centered_internal_Nm"][i],
                                exported_D_Nm=pred["D"][i], exported_E_Nm_per_mol=pred["E"][i] if pred["E"] else None)
    return review_summary(updated)


def verify_export(result):
    if result.get("exportable") is False:
        raise InputError("Stale active baseline overrides block export: " + ", ".join(result["export_blockers"]))
    if "baseline_review" in result["config"]:
        review_settings(result["config"], {p["pass_id"] for p in result["passes"]})
        for pred in result["passes"]:
            checked = copy.deepcopy(pred)
            finalize_prediction(checked, result["config"], result["molar"]["factor_mol_inverse"])
            if any(checked[k] != pred[k] for k in ("D", "E", "centering_constant_Nm", "centered_internal_Nm")):
                raise InputError("Processed output differs from committed baseline settings. Process again.")
            if "output_rows" in result:
                rows = result["output_rows"][pred["output_start"]:pred["output_start"]+pred["rows"]]
                expected = [[d]+([pred["E"][i]] if pred["E"] else []) for i, d in enumerate(pred["D"])]
                if [r[3:] for r in rows] != expected:
                    raise InputError("Export rows differ from committed values. Process again.")


def process(acquisition, config, allow_stale_review=False):
    """Pure shared GUI/CLI computation. Does not read or write any files."""
    validate_config(acquisition, config)
    molar = molar_settings(config["molar"])
    factor = molar["factor_mol_inverse"]
    signals = [p for p in acquisition.passes if not p.zero]
    if not signals:
        raise InputError("No signal passes above the selected near-zero threshold.")
    fits = {}
    for bg in acquisition.passes:
        if bg.zero:
            fits[bg.id] = fit_background(bg)
    predictions, output_rows, stages = [], [], {}
    for bg in acquisition.passes:
        if bg.zero:
            _, info = fits[bg.id]
            for i, row in enumerate(bg.rows):
                stages[row.line] = {
                    "q6_background_Nm": info["q6_background_Nm"][i],
                    "fit_at_sample_Nm": info["fit_at_samples_Nm"][i],
                    "fit_residual_Nm": info["fit_residual_Nm"][i],
                }
    for signal in signals:
        bg = select_background(acquisition, signal, config)
        support = check_support(acquisition, signal, bg, config)
        fit, fit_info = fits[bg.id]
        x, r6, b, u = prepare_signal(signal, fit)
        timing = "before" if bg.rows[-1].line < signal.rows[0].line else "after"
        gap = None
        if bg.rows[0].tokens[1] and signal.rows[0].tokens[1]:
            gap = str(Decimal(signal.rows[0].tokens[1]) - Decimal(bg.rows[-1].tokens[1])) if timing == "before" else str(Decimal(bg.rows[0].tokens[1]) - Decimal(signal.rows[-1].tokens[1]))
        pred = {
            "pass_id": signal.id, "identity": signal.identity, "background_id": bg.id,
            "background_order": timing, "background_time_gap_s": gap, "support": support,
            "angles_deg": x.tolist(),
            "baseline_binding": make_binding(acquisition, signal, bg, u, RECIPE, UPSTREAM_IMPLEMENTATION),
            "raw_Nm": [float(r.tokens[12]) for r in signal.rows], "q6_signal_Nm": r6.tolist(),
            "background_Nm": b.tolist(), "subtracted_Nm": u.tolist(),
            "output_start": len(output_rows), "rows": len(signal.rows),
        }
        finalized = finalize_prediction(pred, config, factor, allow_stale_review)
        y, d, e = finalized["values"], pred["D"], pred["E"]
        for i, row in enumerate(signal.rows):
            output_rows.append([str(row.T), str(row.B), str(row.angle), d[i]] + ([e[i]] if e else []))
            stages[row.line] = {
                "background_id": bg.id, "q6_signal_Nm": float(r6[i]),
                "evaluated_background_Nm": float(b[i]), "subtracted_Nm": float(u[i]),
                **baseline_ledger(pred),
                "centered_internal_Nm": float(y[i]), "exported_D_Nm": d[i],
                "exported_E_Nm_per_mol": e[i] if e else None,
            }
        predictions.append(pred)
    ledger = []
    for row in acquisition.rows:
        ledger.append({
            **asdict(row), "T": str(row.T), "B": str(row.B),
            "role": "background" if row.zero else "signal",
            "retention": "background fit only; excluded from treated DAT" if row.zero else "retained in treated DAT",
            "measured_temperature_K": row.tokens[3], "measured_field_Oe": row.tokens[4],
            "measured_angle_deg": row.tokens[5], "raw_torque_Nm": row.tokens[12],
            "record_width": len(row.source_tokens), **stages[row.line],
        })
    return review_summary({
        "recipe": copy.deepcopy(RECIPE), "config": copy.deepcopy(config), "molar": molar,
        "input": {"path": acquisition.path, "filename": acquisition.path.replace("\\", "/").rsplit("/", 1)[-1],
                  "sha256": acquisition.sha256, "bytes": acquisition.bytes, "schema": acquisition.schema,
                  "header": acquisition.header, "units": acquisition.units,
                  "nonmeasurement_records": acquisition.metadata},
        "inventory": [{"id": p.id, "identity": p.identity, "order": p.order, "T_K": str(p.T),
                       "field_T": p.field_label, "role": "background" if p.zero else "signal",
                       "first_line": p.rows[0].line, "last_line": p.rows[-1].line, "rows": len(p.rows),
                       "missing_angles_deg": p.missing, "changing_field": p.trajectory}
                      for p in acquisition.passes],
        "fits": {key: info for key, (_, info) in fits.items()},
        "passes": predictions, "output_rows": output_rows, "ledger": ledger,
        "reference_inputs": [], "rows": len(output_rows), "raw_rows": len(ledger),
    })

