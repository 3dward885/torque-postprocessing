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
from io_profiles import (InputError, read_raw, _nominal, profile_from, check_deviation,
                         acquisition_defaults, configure_acquisition, split_scans)
from baseline import empty_review, review_settings, make_binding, resolve, finalize_pass
import field_quality

RECIPE = {
    "version": "verified-1.2/gui-1.0",
    "degree": 6, "basis": "scaled power", "domain_deg": [0, 200], "window": [-1, 1],
    "angles": "nominal", "weights": "unweighted", "input_significant_digits": 6,
    "input_rounding": "Decimal nearest, ties to even, then binary64",
    "order": "subtract_then_center", "intermediate_rounding": None,
    "D_export": "binary64 format .8g",
}


def default_config(acquisition):
    return {
        "version": "1.2", "input_sha256": acquisition.sha256,
        "profile": asdict(acquisition.profile), "centering": "midrange",
        "centering_source": "Application default: midrange",
        "acquisition": acquisition_defaults(), "overrides": {}, "support_exceptions": [],
        "note": "", "migration_notes": [], "baseline_review": empty_review(),
        "field_quality": field_quality.defaults(),
    }


def migrate_config(config):
    cfg = copy.deepcopy(config)
    legacy = cfg.get("version") == "1.0"
    if cfg.get("version") == "1.0":
        cfg["version"] = "1.2"
        cfg.setdefault("acquisition", acquisition_defaults())
        cfg.setdefault("migration_notes", []).append(
            "Older settings loaded: assign experimental temperatures in Acquisition settings; torque-only output.")
        cfg["profile"] = asdict(profile_from(cfg["profile"]))
    if "molar" in cfg or "export_format" in cfg:
        if not legacy:
            raise InputError("Molar conversion and export-format settings are not supported in version 1.2. Remove those fields.")
        cfg.pop("molar", None)
        cfg.pop("export_format", None)
        cfg.setdefault("migration_notes", []).append("Molar conversion and historical header choices removed; output is torque in N m.")
    cfg.setdefault("field_quality", field_quality.defaults())
    return cfg


def validate_config(acquisition, config):
    expected = set(default_config(acquisition))
    if set(config) - expected:
        raise InputError(f"Unknown configuration fields: {sorted(set(config)-expected)}.")
    if config.get("version") != "1.2":
        raise InputError("Unsupported configuration version.")
    if config.get("input_sha256") != acquisition.sha256:
        raise InputError("Saved configuration fingerprint does not match this raw file. Import it as a new file and set its own settings.")
    if config.get("profile") != asdict(acquisition.profile):
        raise InputError("Configuration/profile differs from the imported inventory. Re-import with the selected profile.")
    if config.get("centering") not in ("mean", "midrange"):
        raise InputError("Centering must be mean or midrange.")
    if not config.get("centering_source", "").strip():
        raise InputError("Centering selection needs a source note.")
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
        if "background" in override and override["background"] not in [p.id for p in acquisition.passes if p.zero and p.T == passes[pid].T]:
            raise InputError(f"{pid}: selected background is not in this input at the same nominal temperature.")
    for exception in config.get("support_exceptions", []):
        legacy = {"input_sha256", "temperature_K", "outside_angles_deg", "background_support_deg", "source"}
        scoped = legacy | {"signal_id", "signal_identity", "background_id", "background_identity"}
        if set(exception) not in (legacy, scoped):
            raise InputError("Malformed background extrapolation permission.")
        if exception["input_sha256"] != acquisition.sha256 or not exception["source"].strip():
            raise InputError("Background extrapolation permission does not match this input.")
        if "signal_id" in exception:
            signal, bg = passes.get(exception["signal_id"]), passes.get(exception["background_id"])
            if not signal or not bg or signal.identity != exception["signal_identity"] or bg.identity != exception["background_identity"]:
                raise InputError("Background extrapolation scan identity changed.")
    review_settings(config, {p.id for p in acquisition.passes if not p.zero})


def select_background(acquisition, signal, config):
    candidates = acquisition.candidates(signal)
    chosen = config.get("overrides", {}).get(signal.id, {}).get("background")
    if chosen:
        candidates = [p for p in candidates if p.id == chosen]
    if not candidates:
        raise InputError(f"{signal.id}, {signal.T} K: missing same-input, same-temperature background. Supply it in this acquisition.")
    if len(candidates) != 1:
        raise InputError(f"{signal.id}, {signal.T} K: multiple backgrounds ({', '.join(p.id for p in candidates)}). Select Background for this pass and save the association.")
    if candidates[0].issue:
        raise InputError(candidates[0].issue)
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
                and ("signal_id" not in permission or (permission["signal_id"] == signal.id and permission["background_id"] == background.id))
                and Decimal(permission["temperature_K"]) == signal.T
                and permission["background_support_deg"] == [low, high]
                and set(outside) <= set(permission["outside_angles_deg"])):
            return {**info, "policy": "explicit background extrapolation permission", "source": permission["source"]}
    raise InputError(f"{signal.id}: signal angles [{min(r.angle for r in signal.rows)},{max(r.angle for r in signal.rows)}] exceed background {background.id} support [{low},{high}] deg. Select another background or explicitly allow extrapolation.")


def support_permission(acquisition, signal, background, source):
    low, high = min(r.angle for r in background.rows), max(r.angle for r in background.rows)
    return {"input_sha256": acquisition.sha256, "temperature_K": str(signal.T),
            "signal_id": signal.id, "signal_identity": signal.identity,
            "background_id": background.id, "background_identity": background.identity,
            "outside_angles_deg": [r.angle for r in signal.rows if r.angle < low or r.angle > high],
            "background_support_deg": [low, high], "source": source}


def prepare_signal(signal, fit):
    x = np.asarray([r.angle for r in signal.rows], dtype=float)
    r6 = q6([r.tokens[12] for r in signal.rows])
    b = fit(x)
    return x, r6, b, r6 - b


# Only code that defines u participates; plotting and timestamps
# and the centering/finalization implementation do not invalidate N m choices.
UPSTREAM_IMPLEMENTATION = hashlib.sha256("\n".join(inspect.getsource(f) for f in
    (read_raw, split_scans, configure_acquisition, check_deviation, _nominal, q6, fit_background, prepare_signal, select_background, check_support)).encode()).hexdigest()


def finalize_prediction(pred, config, allow_stale_review=False):
    ordinary = config.get("overrides", {}).get(pred["pass_id"], {})
    mode = ordinary.get("centering", config["centering"])
    offset, review = resolve(config, pred["baseline_binding"], pred["subtracted_Nm"], allow_stale_review)
    if review["status"] == "active" and RECIPE["order"] != "subtract_then_center":
        raise InputError("Interactive baselines support subtract_then_center only.")
    finalized = finalize_pass(pred["subtracted_Nm"], mode, accepted_offset=offset)
    effective = review["accepted_record"]["origin"] if review["status"] == "active" else mode
    if review["status"] == "stale":
        effective = "stale override - export blocked"
    pred.update(ordinary_centering=mode, centering=effective,
                centering_source=("User-provided accepted baseline setting" if review["status"] == "active"
                                  else ordinary.get("source", config["centering_source"])),
                centering_constant_Nm=finalized["offset"],
                centered_internal_Nm=finalized["values"].tolist(),
                D=finalized["D"], baseline_review=review)
    return finalized


def review_summary(result):
    blockers = list(result.get("processing_errors", {})) + [p["pass_id"] for p in result["passes"] if p["baseline_review"]["status"] == "stale"]
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
    config = migrate_config(config)
    review_settings(config, {p["id"] for p in result["inventory"] if p["role"] == "signal"})
    for key in ("input_sha256", "profile", "acquisition", "support_exceptions", "field_quality"):
        if config.get(key) != result["config"].get(key):
            raise InputError("Upstream settings changed; process again before reviewing the baseline.")
    old, new = result["config"].get("overrides", {}), config.get("overrides", {})
    for pid in set(old) | set(new):
        if old.get(pid, {}).get("background") != new.get(pid, {}).get("background"):
            raise InputError("Background changed; process again before baseline review.")
    updated = copy.deepcopy(result)
    updated["config"] = copy.deepcopy(config)
    ledger = {r["line"]: r for r in updated["ledger"]}
    for pred in updated["passes"]:
        finalize_prediction(pred, config, allow_stale_review)
        for i, line in enumerate(pred["baseline_binding"]["source_lines"]):
            row = updated["output_rows"][pred["output_start"] + i]
            updated["output_rows"][pred["output_start"] + i] = row[:3] + [pred["D"][i]]
            ledger[line].update(**baseline_ledger(pred), centered_internal_Nm=pred["centered_internal_Nm"][i],
                                exported_D_Nm=pred["D"][i])
    return review_summary(updated)


def verify_export(result):
    field_quality.verify_result(result)
    if result.get("exportable") is False:
        raise InputError("Resolve unprocessed scans or stale adjustments before saving: " + ", ".join(result["export_blockers"]))
    if "baseline_review" in result["config"]:
        review_settings(result["config"], {p["id"] for p in result["inventory"] if p["role"] == "signal"})
        for pred in result["passes"]:
            checked = copy.deepcopy(pred)
            finalize_prediction(checked, result["config"])
            if any(checked[k] != pred[k] for k in ("D", "centering_constant_Nm", "centered_internal_Nm")):
                raise InputError("Processed output differs from committed baseline settings. Process again.")
            if "output_rows" in result:
                rows = result["output_rows"][pred["output_start"]:pred["output_start"]+pred["rows"]]
                expected = [[d] for d in pred["D"]]
                if [r[3:] for r in rows] != expected:
                    raise InputError("Export rows differ from committed values. Process again.")


def process(acquisition, config, allow_stale_review=False, partial=False):
    """Shared computation; partial review never permits silently incomplete export."""
    config = migrate_config(config)
    acquisition = field_quality.configure(acquisition, config)
    validate_config(acquisition, config)
    fits, predictions, output_rows, stages, errors = {}, [], [], {}, {}
    errors.update({pid: r["reason"] for pid, r in acquisition.field_review.items()
                   if r["status"] in field_quality.UNRESOLVED})
    if errors and not partial:
        raise InputError("Field review required; inspect scans and resolve in Acquisition settings / Review scan: " +
                         "; ".join(f"{pid}: {reason}" for pid, reason in errors.items()))
    signals = [p for p in acquisition.passes if not p.zero and not p.excluded]
    if not signals:
        raise InputError("No included signal scans.")
    for signal in signals:
        try:
            if signal.issue:
                raise InputError(signal.issue)
            bg = select_background(acquisition, signal, config)
            if bg.id not in fits:
                fits[bg.id] = fit_background(bg)
            support = check_support(acquisition, signal, bg, config)
            fit, fit_info = fits[bg.id]
            for i, row in enumerate(bg.rows):
                stages[row.line] = {"q6_background_Nm": fit_info["q6_background_Nm"][i],
                                    "fit_at_sample_Nm": fit_info["fit_at_samples_Nm"][i],
                                    "fit_residual_Nm": fit_info["fit_residual_Nm"][i]}
            x, r6, b, u = prepare_signal(signal, fit)
            timing = "before" if bg.rows[-1].line < signal.rows[0].line else "after"
            gap = None
            acquired_bg, acquired_signal = bg.acquired_rows, signal.acquired_rows
            if acquired_bg[0].tokens[1] and acquired_signal[0].tokens[1]:
                gap = str(Decimal(acquired_signal[0].tokens[1]) - Decimal(acquired_bg[-1].tokens[1])) if timing == "before" else str(Decimal(acquired_bg[0].tokens[1]) - Decimal(acquired_signal[-1].tokens[1]))
            pred = {
                "pass_id": signal.id, "identity": signal.identity, "background_id": bg.id,
                "background_order": timing, "background_time_gap_s": gap,
                "support": support, "angles_deg": x.tolist(),
                "baseline_binding": make_binding(acquisition, signal, bg, u, RECIPE, UPSTREAM_IMPLEMENTATION),
                "raw_Nm": [float(r.tokens[12]) for r in signal.rows], "q6_signal_Nm": r6.tolist(),
                "background_Nm": b.tolist(), "subtracted_Nm": u.tolist(),
                "output_start": len(output_rows), "rows": len(signal.rows),
            }
            finalized = finalize_prediction(pred, config, allow_stale_review)
            y, d = finalized["values"], pred["D"]
            for i, row in enumerate(signal.rows):
                output_rows.append([str(row.T), str(row.B), str(row.angle), d[i]])
                stages[row.line] = {"background_id": bg.id, "q6_signal_Nm": float(r6[i]),
                    "evaluated_background_Nm": float(b[i]), "subtracted_Nm": float(u[i]),
                    **baseline_ledger(pred), "centered_internal_Nm": float(y[i]), "exported_D_Nm": d[i]}
            predictions.append(pred)
        except InputError as exc:
            if not partial:
                raise
            errors[signal.id] = str(exc)
    ledger = []
    passes = {p.id: p for p in acquisition.passes}
    for row in acquisition.rows:
        p = passes[row.pass_id]
        ledger.append({**asdict(row), "T": str(row.T), "B": str(row.B),
            "field_review_status": acquisition.field_review[p.id]["status"],
            "field_review_reason": acquisition.field_review[p.id]["reason"],
            "role": "background" if p.zero else "signal",
            "retention": "explicitly excluded" if p.excluded else "outside selected angle range" if row.line not in {r.line for r in p.rows} else "retained in treated DAT" if row.line in stages and not p.zero else "background fit only" if row.line in stages else "unprocessed",
            "measured_temperature_K": row.tokens[3], "measured_field_Oe": row.tokens[4],
            "measured_angle_deg": row.tokens[5], "raw_torque_Nm": row.tokens[12],
            "record_width": len(row.source_tokens), **stages.get(row.line, {})})
    return review_summary({
        "recipe": copy.deepcopy(RECIPE), "config": copy.deepcopy(config),
        "field_review": acquisition.field_review,
        "field_quality_digest": field_quality.settings_digest(config),
        "reference_settings": acquisition.reference_metadata,
        "processing_errors": errors,
        "input": {"path": acquisition.path, "filename": acquisition.path.replace("\\", "/").rsplit("/", 1)[-1],
                  "sha256": acquisition.sha256, "bytes": acquisition.bytes, "schema": acquisition.schema,
                  "header": acquisition.header, "units": acquisition.units, "nonmeasurement_records": acquisition.metadata},
        "inventory": [{"id": p.id, "identity": p.identity, "order": p.order, "T_K": str(p.T),
                       "measured_T_K": p.measured_temperature, "field_T": p.field_label,
                       "role": "background" if p.zero else "signal", "excluded": p.excluded,
                       "issue": p.issue, "first_line": p.acquired_rows[0].line, "last_line": p.acquired_rows[-1].line,
                       "rows": len(p.rows), "acquired_rows": len(p.acquired_rows),
                       "missing_angles_deg": p.missing, "changing_field": p.trajectory}
                      for p in acquisition.passes],
        "fits": {key: info for key, (_, info) in fits.items()},
        "passes": predictions, "output_rows": output_rows, "ledger": ledger,
        "reference_inputs": [], "rows": len(output_rows), "raw_rows": len(ledger),
    })
