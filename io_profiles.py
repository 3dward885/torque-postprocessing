"""Strict DAT readers and explicit acquisition profiles; no numerical treatment."""
from __future__ import annotations
import csv
import hashlib
import json
import math
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from pathlib import Path

APP_VERSION = "1.1"
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
    temperature_step_K: str = "1"
    temperature_tolerance_K: str = "0.2"
    field_step_T: str = "0.01"
    stable_field_tolerance_Oe: str = "1"
    angle_step_deg: str = "5"
    angle_tolerance_deg: str = "0.05"
    background_threshold_Oe: str = "1"
    angle_reset_deg: str = "100"
    allow_signal_gaps: bool = True
    allow_background_gaps: bool = True
    trajectory: str = "monotonic"
    max_extrapolation_deg: str = "0"
    provenance: str = "Fractional-field DAT profile; observed ordered gaps and monotonic field trajectories allowed."

    def validate(self):
        if not self.name or not self.provenance.strip():
            raise InputError("A profile needs a name and provenance.")
        for key in ("temperature_step_K", "field_step_T", "angle_step_deg", "angle_reset_deg"):
            decimal_value(getattr(self, key), key, True)
        for key in ("temperature_tolerance_K", "stable_field_tolerance_Oe", "angle_tolerance_deg",
                    "background_threshold_Oe", "max_extrapolation_deg"):
            if decimal_value(getattr(self, key), key) < 0:
                raise InputError(f"{key} must be nonnegative.")
        if Decimal(self.angle_step_deg) != 5:
            raise InputError("Version 1.0 supports the 5-degree nominal grid on [0,200] only.")
        if Decimal(self.angle_reset_deg) >= 200:
            raise InputError("angle_reset_deg must be less than 200.")
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
    T: Decimal
    zero: bool
    rows: list[Row]
    missing: list[int]
    trajectory: bool

    @property
    def field_label(self):
        b = [r.B for r in self.rows]
        return str(b[0]) if len(set(b)) == 1 else f"{min(b)} to {max(b)}"


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
        return [p for p in self.passes if p.zero and p.T == signal.T]


def _nominal(token, step, tolerance, label):
    value = decimal_value(token, label)
    with localcontext() as ctx:
        ctx.prec = 50
        step = Decimal(step)
        nominal = (value / step).to_integral_value(rounding=ROUND_HALF_EVEN) * step
        if abs(value - nominal) > Decimal(tolerance):
            raise InputError(f"{label}: {token} exceeds tolerance {tolerance} from the {step} grid; select an explicit compatible profile.")
        return nominal


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
        T = _nominal(tokens[3], profile.temperature_step_K, profile.temperature_tolerance_K, f"Line {line}, temperature (K)")
        angle = int(_nominal(tokens[5], profile.angle_step_deg, profile.angle_tolerance_deg, f"Line {line}, angle (deg)"))
        if angle not in GRID:
            raise InputError(f"Line {line}: nominal angle {angle} is outside the supported 200..0 degree grid.")
        zero = abs(Decimal(tokens[4])) <= Decimal(profile.background_threshold_Oe)
        with localcontext() as ctx:
            ctx.prec = 50
            step = Decimal(profile.field_step_T)
            B = Decimal(0) if zero else (Decimal(tokens[4]) / 10000 / step).to_integral_value(rounding=ROUND_HALF_EVEN) * step
        row = Row(line, lines[index], source, tokens, T, B, angle, zero)
        boundary = not rows or T != rows[-1].T or zero != rows[-1].zero
        if rows and not boundary and angle > rows[-1].angle:
            reset = Decimal(tokens[5]) - Decimal(rows[-1].tokens[5])
            if reset <= Decimal(profile.angle_reset_deg) or angle != GRID[0]:
                raise InputError(f"Line {line}: ambiguous angle reset/reversal. A new same-role pass must reset to 200 degrees by more than {profile.angle_reset_deg} degrees.")
            boundary = True
        if boundary:
            groups.append([])
        groups[-1].append(row)
        rows.append(row)
    if not rows:
        raise InputError("No measurement records.")
    passes = []
    for group in groups:
        angles = [r.angle for r in group]
        label = f"Lines {group[0].line}-{group[-1].line}"
        if len(set(angles)) != len(angles) or any(a <= b for a, b in zip(angles, angles[1:])):
            raise InputError(f"{label}: duplicate or unordered angles; rows were not averaged or removed.")
        missing = [a for a in GRID if a not in angles]
        zero = group[0].zero
        if missing and not (profile.allow_background_gaps if zero else profile.allow_signal_gaps):
            raise InputError(f"{label}: incomplete {'background' if zero else 'signal'} grid; missing {missing}.")
        nominal_fields = [r.B for r in group]
        changing = len(set(nominal_fields)) > 1
        if changing:
            if zero or profile.trajectory != "monotonic":
                raise InputError(f"{label}: changing-field trajectory not permitted by this profile.")
            differences = [b - a for a, b in zip(nominal_fields, nominal_fields[1:])]
            if not (all(d >= 0 for d in differences) or all(d <= 0 for d in differences)):
                raise InputError(f"{label}: unsupported reversing field trajectory; provide a separately documented acquisition.")
        elif not zero and any(abs(Decimal(r.tokens[4]) - r.B * 10000) > Decimal(profile.stable_field_tolerance_Oe) for r in group):
            raise InputError(f"{label}: stable field departs by more than {profile.stable_field_tolerance_Oe} Oe from the selected nominal field.")
        pid = f"P{len(passes)+1:03d}"
        identity = hashlib.sha256(json.dumps([[r.line, r.source_tokens] for r in group], separators=(",", ":")).encode()).hexdigest()
        for row in group:
            row.pass_id = pid
        passes.append(Pass(pid, len(passes)+1, identity, group[0].T, zero, group, missing, changing))
    return Acquisition(str(path), hashlib.sha256(blob).hexdigest(), len(blob), schema, header, metadata, rows, passes, profile)

