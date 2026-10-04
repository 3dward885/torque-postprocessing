"""Strict DAT readers and explicit acquisition profiles; no numerical treatment."""
from __future__ import annotations
import csv
import copy
import hashlib
import json
import math
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from pathlib import Path

APP_VERSION = "1.2"
GRID = tuple(range(200, -1, -5))
TSV_HEADER = ["Temperature (K)", "Magnetic Field (Oe)", "Sample Position (deg)", "Torque (Nm)"]
INSTRUMENT_HEADER = (
    "Comment,Time Stamp (sec),Status (code),Temperature (K),Magnetic Field (Oe),"
    "Sample Position (deg),Bridge 1 Resistance (ohms),Bridge 1 Excitation (uA),"
    "Bridge Imbalance (ohms),Bridge Ratio,Bridge Resistance (ohms),User Temperature (K),"
    "Torque (Nm),Torque Std. Dev. (Nm),Signal 1 Vin (V),Signal 2 Vin (V),"
    "Digital Inputs (code),Drive 1 Iout (mA),Drive 1 Ipower (watts),Drive 2 Iout (mA),"
    "Drive 2 Ipower (watts),Pressure (),Map 20 (),Map 21 (),Map 22 (),Map 23 (),"
    "Map 24 (),Map 25 (),Map 26 (),Map 27 (),Map 28 (),Map 29 ()"
).split(",")


class InputError(ValueError):
    """An actionable input or configuration error."""


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def decimal_value(value, label="value", positive=False):
    try:
        if isinstance(value, bool) or len(str(value)) > 200:
            raise ValueError()
        result = Decimal(str(value))
        if not result.is_finite() or (positive and result <= 0):
            raise ValueError()
        if result and (abs(result.adjusted()) > 300 or not math.isfinite(float(result))):
            raise ValueError()
        return result
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise InputError(f"{label}: enter a finite {'positive ' if positive else ''}number.") from exc


@dataclass(frozen=True)
class Profile:
    name: str = "fractional"
    temperature_tolerance_K: str = "0.2"
    field_step_T: str = "0.01"
    stable_field_tolerance_Oe: str = "1"
    angle_step_deg: str = "5"
    angle_origin_deg: str = "0"
    angle_tolerance_deg: str = "0.05"
    background_threshold_Oe: str = "1"
    allow_signal_gaps: bool = True
    allow_background_gaps: bool = True
    trajectory: str = "monotonic"
    max_extrapolation_deg: str = "0"
    provenance: str = "Fractional-field DAT profile; observed ordered gaps and monotonic field trajectories allowed."

    def validate(self):
        if not self.name or not self.provenance.strip():
            raise InputError("A profile needs a name and provenance.")
        for key in ("field_step_T", "angle_step_deg"):
            decimal_value(getattr(self, key), key, True)
        for key in ("temperature_tolerance_K", "stable_field_tolerance_Oe", "angle_tolerance_deg",
                    "background_threshold_Oe", "max_extrapolation_deg"):
            if decimal_value(getattr(self, key), key) < 0:
                raise InputError(f"{key} must be nonnegative.")
        decimal_value(self.angle_origin_deg, "Angle origin (deg)")
        if self.trajectory not in ("stable", "monotonic"):
            raise InputError("trajectory must be stable or monotonic.")
        if not isinstance(self.allow_signal_gaps, bool) or not isinstance(self.allow_background_gaps, bool):
            raise InputError("Gap policies must be JSON true/false.")
        return self


PROFILES = {
    "fractional": Profile(),
    "previous": Profile(name="previous", field_step_T="1", allow_signal_gaps=False,
                        trajectory="stable", provenance="Previous DAT profile: full signal grids, integer tesla; interior background gaps allowed."),
}


def profile_from(value):
    try:
        if isinstance(value, dict):
            value = {k: v for k, v in value.items() if k not in ("temperature_step_K", "angle_reset_deg")}
        return (PROFILES[value] if isinstance(value, str) else Profile(**value)).validate()
    except (KeyError, TypeError) as exc:
        raise InputError("Unknown profile or profile field. Choose previous/fractional or load a documented profile JSON.") from exc


@dataclass
class Row:
    line: int
    source_text: str
    source_tokens: list[str]
    tokens: list[str]
    T: Decimal
    B: Decimal
    angle: int
    zero: bool
    pass_id: str = ""


@dataclass
class Pass:
    id: str
    order: int
    identity: str
    T: Decimal | None
    zero: bool
    rows: list[Row]
    missing: list[int]
    trajectory: bool
    issue: str = ""
    excluded: bool = False
    acquired_rows: list[Row] = field(default_factory=list)

    @property
    def field_label(self):
        b = [r.B for r in self.rows or self.acquired_rows]
        return str(b[0]) if len(set(b)) == 1 else f"{min(b)} to {max(b)}"

    @property
    def measured_temperature(self):
        values = [Decimal(r.tokens[3]) for r in self.acquired_rows or self.rows]
        return f"{min(values):.7g}–{max(values):.7g}"


@dataclass
class Acquisition:
    path: str
    sha256: str
    bytes: int
    schema: str
    header: list[str]
    metadata: list[dict]
    rows: list[Row]
    passes: list[Pass]
    profile: Profile
    units: dict = field(default_factory=lambda: {
        "temperature": "K", "raw_field": "Oe", "export_field": "T", "angle": "deg", "torque": "N m"})

    def candidates(self, signal):
        return [p for p in self.passes if p.zero and not p.excluded and p.T is not None and p.T == signal.T]


def check_deviation(token, reference, tolerance, label):
    value = decimal_value(token, label)
    reference = decimal_value(reference, label + " reference")
    tolerance = decimal_value(tolerance, label + " allowed deviation")
    if tolerance < 0:
        raise InputError(f"{label}: allowed deviation must be nonnegative.")
    with localcontext() as ctx:
        ctx.prec = 50
        difference = abs(value - reference)
        if difference > tolerance:
            raise InputError(f"{label}: measured {value}, reference {reference}, deviation {difference} exceeds allowed deviation {tolerance}.")
    return reference


def _nominal(token, step, tolerance, label, origin="0"):
    value = decimal_value(token, label)
    with localcontext() as ctx:
        ctx.prec = 50
        step = Decimal(step)
        origin = Decimal(origin)
        nominal = ((value - origin) / step).to_integral_value(rounding=ROUND_HALF_EVEN) * step + origin
        return check_deviation(value, nominal, tolerance, label)


def read_raw(path, profile="fractional"):
    """Contents select the schema. The caller, never the filename, selects the profile."""
    profile = profile_from(profile) if not isinstance(profile, Profile) else profile.validate()
    path = Path(path).resolve()
    blob = path.read_bytes()
    try:
        lines = blob.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        raise InputError("DAT must be UTF-8/ASCII text; XLS/XLSX is not supported.") from exc
    if not lines:
        raise InputError("Empty DAT file.")
    metadata = []
    if "[Data]" in lines:
        if lines.count("[Data]") != 1:
            raise InputError("Ambiguous schema: expected one [Data] marker.")
        index = lines.index("[Data]") + 1
        if index >= len(lines):
            raise InputError("Missing instrument header after [Data].")
        header = next(csv.reader([lines[index]], strict=True))
        if header != INSTRUMENT_HEADER:
            raise InputError("Unsupported instrument header/units: expected 32 documented fields; T/B/angle/torque at positions 4/5/6/13 in K/Oe/deg/Nm.")
        start, delimiter, schema = index + 1, ",", "instrument CSV (32 declared)"
    else:
        header = next(csv.reader([lines[0]], delimiter="\t", strict=True))
        if header != TSV_HEADER:
            raise InputError("Unknown schema/units. Expected instrument [Data] or exactly four tab-separated headers in K, Oe, deg, Nm.")
        start, delimiter, schema = 1, "\t", "four-column TSV"
        if len(lines) > 1:
            annotation = next(csv.reader([lines[1]], delimiter="\t", strict=True))
            if len(annotation) == 4 and annotation[0] == "00:00:00 2.0" and all(not x.strip() for x in annotation[1:]):
                start = 2
    metadata.extend({"line": n + 1, "text": text, "role": "nonmeasurement"}
                    for n, text in enumerate(lines[:start]))
    rows, groups = [], []
    for index in range(start, len(lines)):
        line = index + 1
        if not lines[index].strip():
            metadata.append({"line": line, "text": lines[index], "role": "blank nonmeasurement"})
            continue
        try:
            source = next(csv.reader([lines[index]], delimiter=delimiter, strict=True))
        except csv.Error as exc:
            raise InputError(f"Line {line}: malformed delimited record: {exc}") from exc
        if delimiter == ",":
            if not 14 <= len(source) <= 32:
                raise InputError(f"Line {line}: expected 14..32 fields; found {len(source)}. Internal blanks must retain their positions.")
            tokens = source + [""] * (32 - len(source))
            for k in (1, 2, 3, 4, 5, 12, 13):
                decimal_value(tokens[k], f"Line {line}, {header[k]}")
            for k in range(6, 32):
                if tokens[k].strip():
                    decimal_value(tokens[k], f"Line {line}, {header[k]}")
            if rows and Decimal(tokens[1]) <= Decimal(rows[-1].tokens[1]):
                raise InputError(f"Line {line}: non-increasing timestamp; supply separate acquisitions/files.")
        else:
            if len(source) != 4:
                raise InputError(f"Line {line}: expected four tab-separated fields; found {len(source)}.")
            tokens = [""] * 32
            for k, value in zip((3, 4, 5, 12), source):
                decimal_value(value, f"Line {line}, field {k+1}")
                tokens[k] = value
        T, B = Decimal(tokens[3]), Decimal(tokens[4]) / 10000
        angle = float(tokens[5])
        zero = abs(Decimal(tokens[4])) <= Decimal(profile.background_threshold_Oe)
        rows.append(Row(line, lines[index], source, tokens, T, B, angle, zero))
    if not rows:
        raise InputError("No measurement records.")
    acquisition = Acquisition(str(path), hashlib.sha256(blob).hexdigest(), len(blob), schema,
                              header, metadata, rows, [], profile)
    acquisition.passes = split_scans(rows)
    return acquisition


def split_scans(rows, starts=None):
    """Split sweep reversals/restarts in acquisition order, never by measured T."""
    groups, direction = [], 0
    if starts is not None:
        if not isinstance(starts, list) or any(type(n) is not int for n in starts):
            raise InputError("Scan starts must be a list of physical row numbers.")
        if starts != sorted(set(starts)) or not starts or starts[0] != rows[0].line:
            raise InputError("Scan starts must be unique, increasing, and include the first measurement row.")
        if set(starts) - {r.line for r in rows}:
            raise InputError("A scan start does not identify a measurement row.")
    for row in rows:
        boundary = not groups
        if groups:
            difference = Decimal(row.tokens[5]) - Decimal(groups[-1][-1].tokens[5])
            sign = (difference > 0) - (difference < 0)
            boundary = row.line in starts if starts is not None else bool(direction and sign and sign != direction)
            if not boundary and sign:
                direction = sign
        if boundary:
            groups.append([])
            direction = 0
        groups[-1].append(row)
    passes = []
    for group in groups:
        pid = f"P{len(passes)+1:03d}"
        identity = hashlib.sha256(json.dumps([[r.line, r.source_tokens] for r in group], separators=(",", ":")).encode()).hexdigest()
        for row in group:
            row.pass_id = pid
        issue = f"{pid}: ambiguous short scan at an angle reversal; confirm scan starts in Acquisition settings." if starts is None and len(group) < 3 and len(groups) > 1 else ""
        passes.append(Pass(pid, len(passes)+1, identity, None, all(r.zero for r in group), group, [], False, issue=issue, acquired_rows=list(group)))
    return passes


def acquisition_defaults():
    return {"schema_version": 1, "temperature_setpoints_K": [], "source": "User settings",
            "scan_starts": None, "angle_range_deg": None, "scans": {}}


def metadata_setpoints(acquisition):
    # Optional explicit INFO metadata; never interpret measured User Temperature as a setpoint.
    values = []
    for record in acquisition.metadata:
        fields = next(csv.reader([record["text"]]))
        if len(fields) == 3 and fields[0].strip() == "INFO" and fields[2].strip() == "TEMPERATURE_SETPOINTS_K":
            values.extend(str(decimal_value(v.strip(), "Metadata temperature setpoint (K)"))
                          for v in fields[1].split(";") if v.strip())
    return values


def configure_acquisition(acquisition, settings):
    """Validate references on a detached inventory; retain unresolved scans for review."""
    obj = copy.deepcopy(acquisition)
    if not isinstance(settings, dict) or set(settings) != set(acquisition_defaults()) or type(settings["schema_version"]) is not int or settings["schema_version"] != 1:
        raise InputError("Unsupported acquisition settings; expected schema version 1.")
    if not isinstance(settings["source"], str) or not settings["source"].strip():
        raise InputError("Acquisition settings need a source.")
    if not isinstance(settings["temperature_setpoints_K"], list) or not isinstance(settings["scans"], dict):
        raise InputError("Setpoints must be a list; scan settings must be an object.")
    supplied = [decimal_value(v, "Temperature setpoint (K)") for v in settings["temperature_setpoints_K"]]
    recorded = [Decimal(v) for v in metadata_setpoints(obj)]
    targets = supplied or recorded
    limits = settings["angle_range_deg"]
    if limits is not None:
        if not isinstance(limits, list) or len(limits) != 2:
            raise InputError("Angle range needs a lower and upper bound in degrees.")
        limits = [decimal_value(v, "Angle range (deg)") for v in limits]
        if limits[0] >= limits[1]:
            raise InputError("Angle range: the lower bound must be smaller than the upper bound.")
    obj.analysis_range_deg = [str(v) for v in limits] if limits else None
    if len(set(targets)) != len(targets):
        raise InputError("Temperature setpoints contain duplicate values.")
    obj.passes = split_scans(obj.rows, settings["scan_starts"])
    keys = {p.id for p in obj.passes}
    if set(settings["scans"]) - keys:
        raise InputError("Unknown acquisition scan assignment.")
    obj.reference_metadata = {"recorded_setpoints_K": [str(v) for v in recorded],
                              "configured_setpoints_K": [str(v) for v in targets],
                              "source": settings["source"] if supplied else "Explicit raw INFO metadata" if recorded else None,
                              "metadata_conflict": bool(recorded and supplied and set(recorded) != set(supplied))}
    tolerance = Decimal(obj.profile.temperature_tolerance_K)
    for p in obj.passes:
        choice = settings["scans"].get(p.id, {})
        allowed = {"identity", "temperature_K", "source", "role", "exclude", "field_T"}
        if not isinstance(choice, dict) or set(choice) - allowed:
            raise InputError(f"{p.id}: unknown scan setting.")
        if choice and (choice.get("identity") != p.identity or not choice.get("source", "").strip()):
            raise InputError(f"{p.id}: scan assignment identity/source mismatch.")
        if type(choice.get("exclude", False)) is not bool:
            raise InputError(f"{p.id}: exclude must be true or false.")
        p.excluded = choice.get("exclude", False)
        try:
            temperatures = [Decimal(r.tokens[3]) for r in p.rows]
            if "temperature_K" in choice:
                target = decimal_value(choice["temperature_K"], "Temperature setpoint (K)")
            else:
                with localcontext() as ctx:
                    ctx.prec = 50
                    matches = [t for t in targets if all(abs(v-t) <= tolerance for v in temperatures)]
                if len(matches) != 1:
                    reason = "Missing" if not matches else "Ambiguous"
                    raise InputError(f"{p.id}: {reason} temperature setpoint for measured {p.measured_temperature} K. Assign a setpoint in Acquisition settings.")
                target = matches[0]
            p.T = target
            for r in p.rows:
                check_deviation(r.tokens[3], target, tolerance, f"Line {r.line}, temperature (K)")
                r.T = target
                angle = _nominal(r.tokens[5], obj.profile.angle_step_deg, obj.profile.angle_tolerance_deg,
                                 f"Line {r.line}, angle (deg)", obj.profile.angle_origin_deg)
                r.angle = int(angle) if angle == int(angle) else float(angle)
            angles = [r.angle for r in p.rows]
            differences = [b-a for a,b in zip(angles, angles[1:])]
            if not differences or not (all(v > 0 for v in differences) or all(v < 0 for v in differences)):
                raise InputError(f"{p.id}: duplicate or reversing angles; check scan starts in Acquisition settings.")
            step = Decimal(obj.profile.angle_step_deg)
            count = int((Decimal(str(max(angles))) - Decimal(str(min(angles)))) / step)
            if count > 100000:
                raise InputError(f"{p.id}: angle grid is too large; check the step and units.")
            nominal = [Decimal(str(min(angles))) + i*step for i in range(count+1)]
            p.missing = [float(v) for v in nominal if float(v) not in angles]
            role = choice.get("role")
            if role not in (None, "signal", "background"):
                raise InputError(f"{p.id}: role must be signal or background.")
            p.zero = role == "background" if role else all(abs(Decimal(r.tokens[4])) <= Decimal(obj.profile.background_threshold_Oe) for r in p.rows)
            for r in p.rows:
                r.zero = p.zero
                field = Decimal(r.tokens[4])
                if p.zero:
                    check_deviation(field, 0, obj.profile.background_threshold_Oe, f"Line {r.line}, background field (Oe)")
                    r.B = Decimal(0)
                elif "field_T" in choice:
                    r.B = check_deviation(field, decimal_value(choice["field_T"])*10000,
                                          obj.profile.stable_field_tolerance_Oe, f"Line {r.line}, field (Oe)")/10000
                else:
                    with localcontext() as ctx:
                        ctx.prec = 50
                        step_b = Decimal(obj.profile.field_step_T)
                        r.B = (field / 10000 / step_b).to_integral_value(rounding=ROUND_HALF_EVEN)*step_b
            fields = [r.B for r in p.rows]
            p.trajectory = len(set(fields)) > 1
            if p.trajectory:
                differences = [b-a for a,b in zip(fields, fields[1:])]
                if obj.profile.trajectory == "stable" or not (all(v >= 0 for v in differences) or all(v <= 0 for v in differences)):
                    raise InputError(f"{p.id}: reversing or unexpected changing field; check scan boundaries/settings.")
            elif not p.zero:
                for r in p.rows:
                    check_deviation(r.tokens[4], r.B*10000, obj.profile.stable_field_tolerance_Oe,
                                    f"Line {r.line}, field (Oe)")
            if p.missing and not (obj.profile.allow_background_gaps if p.zero else obj.profile.allow_signal_gaps):
                raise InputError(f"{p.id}: incomplete scan; missing angles {p.missing} deg.")
        except InputError as exc:
            p.issue = str(exc)
        if limits:
            p.rows = [r for r in p.rows if limits[0] <= Decimal(str(r.angle)) <= limits[1]]
            p.missing = [v for v in p.missing if limits[0] <= Decimal(str(v)) <= limits[1]]
            if not p.rows and not p.excluded:
                p.issue = f"{p.id}: no samples in the selected angle range. Change the range or explicitly exclude this scan."
    return obj
