"""Deliberate reference formatting/sample settings; never inferred from filenames."""
from dataclasses import asdict
from io_profiles import PROFILES, InputError

PRESET_LABELS = {
    "previous": "Previous references: 911.63 mol^-1",
    "new_rot1": "New Rot1 reference: 1575.45 mol^-1",
    "new_rot2": "New Rot2 reference: 1575.45 mol^-1",
}
NEW_ROT2_HASH = "d7fe022a8d117006f26b5739e85ee90b3c6015a6e332e5ef8561e2eee3718933"


def apply_preset(config, name):
    """Return explicit settings. Import/profile validation is the caller's next step."""
    if name not in PRESET_LABELS:
        raise InputError("Unknown reference preset.")
    profile = "previous" if name == "previous" else "fractional"
    result = {**config, "profile": asdict(PROFILES[profile]), "export_format": name,
              "molar": {"mode": "multiplier", "factor": "911.63" if name == "previous" else "1575.45",
                        "source": PRESET_LABELS[name] + "; documented export multiplier; physical basis unverified"},
              "support_exceptions": [], "note": "Deliberately selected " + PRESET_LABELS[name]}
    if name == "new_rot2":
        if config["input_sha256"] != NEW_ROT2_HASH:
            raise InputError("This reference support permission belongs to the supplied New Rot2 fingerprint. For a new measurement select Fractional, then set its own molar metadata and support policy.")
        result["support_exceptions"] = [{
            "input_sha256": NEW_ROT2_HASH, "temperature_K": "50",
            "outside_angles_deg": [200], "background_support_deg": [0, 195],
            "source": "Implementation prompt v1.0 and completed comparison v1.2: ordinary fitted-background evaluation at existing angles is authorized for this reference acquisition.",
        }]
    return result

