"""Acquisition review, separate from coordinate tolerances and torque arithmetic."""
from __future__ import annotations
import copy
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import json
from io_profiles import InputError, configure_acquisition, decimal_value

RULE = "span rounded to 0.01 T (nearest, ties away from zero); review at or above limit"
UNRESOLVED = {"Review required", "Policy/limit not configured"}


def defaults():
    return {"schema_version": 1, "condition": "fixed", "limit_T": "",
            "rule": RULE, "source": "New or migrated settings; limit requires user entry", "decisions": {}}


def validate(block):
    if not isinstance(block, dict) or set(block) != set(defaults()) or block.get("schema_version") != 1:
        raise InputError("Unknown or malformed acquisition-quality settings.")
    if block["condition"] not in ("fixed", "changing") or block["rule"] != RULE:
        raise InputError("Unsupported field condition or field-review rule.")
    if not isinstance(block["source"], str) or not block["source"].strip():
        raise InputError("Field condition requires a source note.")
    if block["limit_T"] != "":
        if decimal_value(block["limit_T"], "Maximum field change (T)") < 0:
            raise InputError("Maximum field change (T) must be nonnegative.")
    if not isinstance(block["decisions"], dict):
        raise InputError("Malformed field-review decisions.")
    return block


def field_evidence(scan):
    rows = scan.acquired_rows or scan.rows
    with localcontext() as ctx:
        ctx.prec = 50
        fields = [Decimal(r.tokens[4]) / Decimal(10000) for r in rows]
        span = max(fields) - min(fields)
        rounded = span.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {"source_lines": [r.line for r in rows],
            "field_Oe_tokens": [r.tokens[4] for r in rows],
            "minimum_T": str(min(fields)), "maximum_T": str(max(fields)),
            "span_T": str(span), "review_span_T": str(rounded), "units": "T"}


def binding(source_hash, scan, evidence, policy):
    return {"source_sha256": source_hash, "scan_id": scan.id, "scan_identity": scan.identity,
            "evidence": evidence, "policy": {k: policy[k] for k in ("condition", "limit_T", "rule", "source")}}


def decide(acquisition, config, scan_id, action, source):
    """Called only by an explicit GUI action or a labelled test action."""
    if action not in ("exclude", "permit_changing") or not str(source).strip():
        raise InputError("Choose an explicit decision and give its source/reason.")
    configured = configure_acquisition(acquisition, config["acquisition"])
    scan = next((p for p in configured.passes if p.id == scan_id), None)
    if scan is None:
        raise InputError("The selected acquisition no longer exists.")
    cfg = copy.deepcopy(config)
    policy = validate(cfg.setdefault("field_quality", defaults()))
    policy["decisions"][scan_id] = {"action": action, "source": str(source).strip(),
        "time_UTC": datetime.now(timezone.utc).isoformat(),
        "binding": binding(configured.sha256, scan, field_evidence(scan), policy)}
    return cfg


def assess(acquisition, config):
    policy = validate(config.get("field_quality", defaults()))
    ids = {p.id for p in acquisition.passes}
    if set(policy["decisions"]) - ids:
        raise InputError("A saved field decision refers to a missing acquisition; review its settings.")
    reviews = {}
    for scan in acquisition.passes:
        evidence = field_evidence(scan)
        expected = binding(acquisition.sha256, scan, evidence, policy)
        record = policy["decisions"].get(scan.id)
        reason = ""
        if record is not None:
            valid = (isinstance(record, dict) and set(record) == {"action", "source", "time_UTC", "binding"}
                     and record.get("action") in ("exclude", "permit_changing")
                     and isinstance(record.get("source"), str) and record["source"].strip()
                     and isinstance(record.get("time_UTC"), str) and record["time_UTC"]
                     and record.get("binding") == expected)
            if not valid:
                status, reason = "Review required", "Saved field decision does not match source, acquisition or policy; review again."
            else:
                status = "Excluded by decision" if record["action"] == "exclude" else "Changing field permitted"
                reason = record["source"]
        elif scan.excluded:
            status, reason = "Excluded by decision", "Existing explicit acquisition exclusion (identity checked on import)."
        elif policy["condition"] == "changing":
            status, reason = "Changing field permitted", policy["source"]
        elif policy["limit_T"] == "":
            status, reason = "Policy/limit not configured", "Set the maximum field change in Acquisition settings."
        elif Decimal(evidence["review_span_T"]) >= Decimal(policy["limit_T"]):
            status = "Review required"
            reason = f"Field changed during sweep: measured span {evidence['span_T']} T; rounded span {evidence['review_span_T']} T reaches/exceeds {policy['limit_T']} T."
        else:
            status, reason = "Check passed", "Rounded measured span is below the configured limit."
        reviews[scan.id] = {"status": status, "reason": reason, **expected, "decision": record}
    return reviews


def configure(acquisition, config):
    acquisition = configure_acquisition(acquisition, config["acquisition"])
    acquisition.field_review = assess(acquisition, config)
    for scan in acquisition.passes:
        review = acquisition.field_review[scan.id]
        if review["status"] == "Excluded by decision":
            scan.excluded = True
        elif review["status"] in UNRESOLVED:
            # A stale decision must not continue excluding an acquisition.
            scan.excluded = False
            scan.issue = " ".join(filter(None, [scan.issue, scan.id + ": " + review["reason"]]))
    return acquisition


def settings_digest(config):
    return hashlib.sha256(json.dumps(config.get("field_quality", defaults()), sort_keys=True).encode()).hexdigest()


def verify_result(result):
    if result.get("field_quality_digest") != settings_digest(result["config"]):
        raise InputError("Field-review settings changed or are missing; process again before export.")
    unresolved = [pid for pid, r in result.get("field_review", {}).items() if r["status"] in UNRESOLVED]
    if unresolved:
        raise InputError("Field review required before export: " + ", ".join(unresolved))
