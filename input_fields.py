"""Text entry helpers shared by the desktop and command line."""
import re
from io_profiles import InputError, decimal_value


def temperature_list(text):
    """Retain decimal tokens; separators are commas or whitespace."""
    tokens = re.split(r"[\s,]+", text.strip()) if text.strip() else []
    values = [decimal_value(token, "Temperature setpoint (K)") for token in tokens]
    if len(set(values)) != len(values):
        raise InputError("Temperature setpoints contain duplicate values.")
    return tokens
