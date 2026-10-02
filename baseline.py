"""Accepted per-acquisition baseline settings and the shared finalization boundary."""
from __future__ import annotations
import copy
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import json
import math
import platform
import struct
import sys
import numpy as np
from io_profiles import InputError

SCHEMA_VERSION = 1
APP_VERSION = "1.1"
BINDING_FIELDS = (
    "input_sha256", "profile_id", "rotation", "pass_id", "pass_identity",
    "source_lines", "nominal_angles", "displayed_T_and_fields",
    "background_identity", "upstream_fingerprint", "u_sha256",
)
VALUE_FIELDS = ("c_final_binary64_hex", "c_mid_Nm", "delta_Nm", "c_final_Nm",
                "origin", "accepted_utc", "app_and_config_versions")


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def finite(value, label="Offset (N m)"):
    try:
        if isinstance(value, bool):
            raise ValueError()
        number = float(value)
        if not math.isfinite(number):
            raise ValueError()
        return number
    except (TypeError, ValueError, OverflowError) as exc:
        raise InputError(f"{label}: enter a finite binary64 number.") from exc


def vector(values):
    try:
        result = np.asarray(values, dtype=np.float64)
    except (ValueError, TypeError, OverflowError) as exc:
        raise InputError("Baseline review needs a finite one-dimensional torque vector.") from exc
    if result.ndim != 1 or not result.size or not np.isfinite(result).all():
        raise InputError("Baseline review needs a nonempty finite one-dimensional torque vector.")
    return result


def midrange(values):
    u = vector(values)
    with np.errstate(over="ignore", invalid="ignore"):
        return finite((np.min(u) + np.max(u)) / 2, "Calculated midrange")


def u_digest(values):
    u = vector(values)
    # Length followed by explicitly little-endian IEEE-754 binary64 values.
    return hashlib.sha256(struct.pack("<Q", len(u)) + u.astype("<f8").tobytes()).hexdigest()


def empty_review():
    return {"schema_version": SCHEMA_VERSION, "enabled": False, "overrides": {}}


def review_settings(config, signal_ids=None):
    block = config.get("baseline_review", empty_review())
    if not isinstance(block, dict) or set(block) != {"schema_version", "enabled", "overrides"}:
        raise InputError("baseline_review needs schema_version, enabled and overrides only.")
    if type(block["schema_version"]) is not int or block["schema_version"] != SCHEMA_VERSION:
        raise InputError("Unsupported baseline_review schema_version.")
    if type(block["enabled"]) is not bool or not isinstance(block["overrides"], dict):
        raise InputError("baseline_review enabled must be a Boolean; overrides must be an object.")
    for pid, record in block["overrides"].items():
        if signal_ids is not None and pid not in signal_ids:
            raise InputError(f"Unknown baseline-review signal pass key: {pid}.")
        if not isinstance(record, dict) or set(record) != set(BINDING_FIELDS + VALUE_FIELDS):
            raise InputError(f"{pid}: malformed baseline acceptance record or unknown fields.")
        if record["pass_id"] != pid:
            raise InputError(f"{pid}: baseline pass key disagrees with its record.")
    return block


def make_binding(acquisition, signal, background, u, recipe, implementation):
    identity = {
        "input_sha256": acquisition.sha256,
        "profile_id": acquisition.profile.name,
        # No physical rotation name is inferred from a filename.
        "rotation": "input-acquisition:" + acquisition.sha256,
        "pass_id": signal.id, "pass_identity": signal.identity,
        "source_lines": [r.line for r in signal.rows],
        "nominal_angles": [r.angle for r in signal.rows],
        "displayed_T_and_fields": {"temperature_K": str(signal.T),
                                  "row_fields_T": [str(r.B) for r in signal.rows]},
        "background_identity": {
            "input_sha256": acquisition.sha256, "pass_id": background.id,
            "identity": background.identity, "source_lines": [r.line for r in background.rows],
            "nominal_angles": [r.angle for r in background.rows],
        },
    }
    upstream = {
        "acquisition": identity,
        "profile": {k: v for k, v in asdict(acquisition.profile).items() if k != "provenance"},
        "recipe": {k: v for k, v in recipe.items() if k not in ("D_export", "E_export", "version")},
        "implementation_sha256": implementation,
        "environment": {"python": platform.python_version(), "numpy": np.__version__,
                        "machine": platform.machine(), "platform": platform.platform(), "byteorder": sys.byteorder},
    }
    return {**identity,
            "upstream_fingerprint": hashlib.sha256(canonical_json(upstream).encode()).hexdigest(),
            "u_sha256": u_digest(u)}


def accepted_record(binding, u, delta, previous=None):
    c_mid = midrange(u)
    delta = finite(delta, "Delta (N m)")
    c_final = finite(c_mid + delta, "Final baseline (N m)")
    # Check subtraction overflow before accepting the setting.
    finalize_pass(u, "midrange", accepted_offset=c_final)
    record = {**copy.deepcopy(binding), "c_final_binary64_hex": c_final.hex(),
              "c_mid_Nm": repr(c_mid), "delta_Nm": repr(delta), "c_final_Nm": repr(c_final),
              "origin": "accepted_midrange" if delta == 0 else "user_adjusted",
              "accepted_utc": datetime.now(timezone.utc).isoformat(),
              "app_and_config_versions": {"app": APP_VERSION, "config": "1.0", "baseline_review": SCHEMA_VERSION}}
    # Repeated Apply is a no-op, including preservation of its acceptance time.
    if previous and all(previous.get(k) == record[k] for k in BINDING_FIELDS + VALUE_FIELDS if k != "accepted_utc"):
        return copy.deepcopy(previous)
    return record


def record_issue(record, binding, u):
    try:
        for key in BINDING_FIELDS:
            if record[key] != binding[key]:
                raise InputError(f"{key} changed")
        if binding["u_sha256"] != u_digest(u):
            raise InputError("cached uncentered torque digest changed")
        try:
            c_final = float.fromhex(record["c_final_binary64_hex"])
        except (TypeError, ValueError, OverflowError) as exc:
            raise InputError("invalid canonical binary64 offset") from exc
        finite(c_final)
        if c_final.hex() != record["c_final_binary64_hex"]:
            raise InputError("noncanonical binary64 hexadecimal offset")
        values = [finite(record[k], k) for k in ("c_mid_Nm", "delta_Nm", "c_final_Nm")]
        c_mid, delta, readable_final = values
        if c_mid.hex() != midrange(u).hex():
            raise InputError("saved midrange differs from current uncentered torque")
        if finite(c_mid + delta).hex() != c_final.hex() or readable_final.hex() != c_final.hex():
            raise InputError("redundant midrange/delta/final values disagree")
        expected_origin = "accepted_midrange" if delta == 0 else "user_adjusted"
        if record["origin"] != expected_origin:
            raise InputError("baseline origin disagrees with delta")
        when = datetime.fromisoformat(record["accepted_utc"].replace("Z", "+00:00"))
        if when.utcoffset() is None or when.utcoffset().total_seconds() != 0:
            raise InputError("acceptance timestamp must be UTC")
        versions = record["app_and_config_versions"]
        if versions.get("config") != "1.0" or versions.get("baseline_review") != SCHEMA_VERSION or not versions.get("app"):
            raise InputError("unsupported acceptance versions")
        finalize_pass(u, "midrange", accepted_offset=c_final)
    except (InputError, KeyError, TypeError, ValueError, OverflowError, AttributeError) as exc:
        return str(exc)
    return None


def resolve(config, binding, u, allow_stale_review=False):
    block = review_settings(config)
    record = block["overrides"].get(binding["pass_id"])
    status = {"enabled": block["enabled"], "status": "ordinary", "reason": None,
              "accepted_record": copy.deepcopy(record)}
    if record is None:
        return None, status
    issue = record_issue(record, binding, u)
    status["reason"] = issue
    if not block["enabled"]:
        status["status"] = "inactive_stale" if issue else "inactive"
        return None, status
    if issue:
        if not allow_stale_review:
            raise InputError(f"{binding['pass_id']}: stale baseline override ({issue}). Review and Apply, Remove override, or disable Interactive baseline adjustment.")
        status["status"] = "stale"
        return None, status
    status["status"] = "active"
    return float.fromhex(record["c_final_binary64_hex"]), status


def finalize_pass(values, ordinary_policy, factor=None, accepted_offset=None):
    """One subtraction and unchanged .8g/Decimal serialization for every route."""
    u = vector(values)
    if ordinary_policy not in ("mean", "midrange"):
        raise InputError("Centering must be mean or midrange.")
    with np.errstate(over="ignore", invalid="ignore"):
        c = (float(np.mean(u)) if ordinary_policy == "mean" else float((np.min(u) + np.max(u)) / 2)) if accepted_offset is None else finite(accepted_offset)
        y = u - c
    if not math.isfinite(c) or not np.isfinite(y).all():
        raise InputError("Nonfinite baseline arithmetic result.")
    d = [format(float(v), ".8g") for v in y]
    with localcontext() as ctx:
        ctx.prec = max(50, len(Decimal(factor).as_tuple().digits) + 16) if factor else 50
        e = [str(Decimal(v) * Decimal(factor)) for v in d] if factor else None
    return {"offset": c, "values": y, "D": d, "E": e}


def preview_values(values, delta):
    u = vector(values)
    c_mid = midrange(u)
    delta = finite(delta, "Delta (N m)")
    c_final = finite(c_mid + delta, "Final baseline (N m)")
    y = finalize_pass(u, "midrange", accepted_offset=c_final)["values"]
    lo, hi = float(np.min(y)), float(np.max(y))
    return {"c_mid": c_mid, "delta": delta, "c_final": c_final, "corrected": y,
            "minimum": lo, "maximum": hi, "imbalance": hi + lo,
            "range": hi - lo}


@dataclass(frozen=True)
class ReviewCache:
    """The byte-backed arrays cannot become writable during a drag."""
    u_bytes: bytes
    angles: tuple
    binding_json: str

    @classmethod
    def from_prediction(cls, pred):
        u = vector(pred["subtracted_Nm"])
        return cls(u.astype("<f8").tobytes(), tuple(pred["angles_deg"]),
                   canonical_json(pred["baseline_binding"]))

    @property
    def u(self):
        return np.frombuffer(self.u_bytes, dtype="<f8")

    @property
    def binding(self):
        return json.loads(self.binding_json)

