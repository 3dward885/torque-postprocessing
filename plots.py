"""Figures from saved numerical stages; no refitting or synthetic signal points."""
from pathlib import Path
import hashlib
import numpy as np
import matplotlib as mpl
from matplotlib import font_manager
from matplotlib.figure import Figure
from matplotlib.ticker import AutoMinorLocator
from numpy.polynomial import Polynomial
from io_profiles import InputError

# Tick formatters run again on Tk redraw, after the figure's local style context.
mpl.rcParams["axes.unicode_minus"] = False

try:
    FONT = Path(font_manager.findfont(font_manager.FontProperties(
        family="Arial", style="normal", weight="normal"), fallback_to_default=False))
except ValueError:
    FONT = None
FONT_SHA = hashlib.sha256(FONT.read_bytes()).hexdigest() if FONT else None


def font_status():
    if FONT is None or not FONT.is_file():
        return "NONCOMPLIANT preview: Arial Regular unavailable; scientific export disabled."
    name = font_manager.FontProperties(fname=str(FONT)).get_name()
    if name != "Arial":
        return "NONCOMPLIANT preview: resolved font is not Arial; scientific export disabled."
    return "Arial Regular verified: " + str(FONT)


def style(preview=False):
    good = font_status().startswith("Arial Regular verified:")
    return {
        "font.family": font_manager.FontProperties(fname=str(FONT)).get_name() if good else "sans-serif",
        "font.size": 12 if preview else 18, "axes.labelsize": 14 if preview else 22,
        "xtick.labelsize": 11 if preview else 18, "ytick.labelsize": 11 if preview else 18,
        "legend.fontsize": 10 if preview else 12, "axes.linewidth": 1.2,
        "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "black",
        "axes.grid": False, "axes.facecolor": "white", "figure.facecolor": "white",
        "xtick.direction": "out", "ytick.direction": "out", "xtick.major.size": 6,
        "ytick.major.size": 6, "xtick.minor.size": 3, "ytick.minor.size": 3,
        "pdf.fonttype": 42, "ps.fonttype": 42, "axes.unicode_minus": False,
    }


def make_figure(result, pass_id, view="stages", reference=None, preview=False):
    pred = next((p for p in result["passes"] if p["pass_id"] == pass_id), None)
    if pred is None:
        raise InputError("Select a processed signal pass for preview.")
    if view in ("baseline_uncentered", "baseline_corrected"):
        return baseline_figure(pred["angles_deg"], pred["subtracted_Nm"], pred["centering_constant_Nm"],
                               corrected=view == "baseline_corrected", preview=preview)
    with mpl.rc_context(style(preview)):
        fig = Figure(figsize=(8, 6.1 if view == "background" else 6), dpi=100)
        ax = fig.add_subplot()
        fig.subplots_adjust(left=.19, bottom=.18, right=.96, top=.94)
        x = pred["angles_deg"]
        if view == "background":
            info = result["fits"][pred["background_id"]]
            ax.plot(info["fit_angles_deg"], info["q6_background_Nm"], "o", color="black",
                    markersize=7.5, linestyle="none", label="Background samples")
            fit = Polynomial(info["coefficients_scaled"], domain=[0, 200], window=[-1, 1])
            support = info["support_deg"]
            dense = np.linspace(support[0], support[1], 600)
            ax.plot(dense, fit(dense), color="#FF0000", linewidth=.5, label="Degree 6 fit")
            ax.set_ylabel("Background torque (N m)")
        elif view in ("comparison", "residual"):
            if reference is None:
                raise InputError("Compare a saved export with a reference first.")
            start = pred["output_start"]
            ref = reference[start:start+pred["rows"]]
            d = [float(v) for v in pred["D"]]
            r = [float(v[3]) for v in ref]
            if view == "comparison":
                ax.plot(x, r, "o", color="black", markersize=6, linestyle="none", label="Reference")
                ax.plot(x, d, "x", color="#FF0000", markersize=6, linestyle="none", label="Saved output")
                ax.set_ylabel("Torque (N m)")
            else:
                from decimal import Decimal
                residual = [float(Decimal(v) - w[3]) for v, w in zip(pred["D"], ref)]
                ax.plot(x, residual, "o", color="black", markersize=4, linestyle="none")
                ax.set_ylabel("Output - reference (N m)")
                if not any(residual):
                    ax.set_ylim(-1e-15, 1e-15)
                    ax.set_yticks([0])
        else:
            series = [("Raw measured", "raw_Nm", "#777777"), ("Background evaluated", "background_Nm", "#FF0000"),
                      ("Subtracted", "subtracted_Nm", "#0072B2"), ("Centered", "centered_internal_Nm", "black")]
            if view == "centered":
                series = [series[-1]]
            for name, key, color in series:
                ax.plot(x, pred[key], "o", color=color, markersize=3.5, linestyle="none", label=name)
            ax.set_ylabel("Torque (N m)")
        ax.set_xlabel("Sample position (deg)")
        angle_limits(ax, x)
        ax.xaxis.set_minor_locator(AutoMinorLocator(2))
        if view != "residual":
            ax.yaxis.set_minor_locator(AutoMinorLocator(2))
        if ax.get_legend_handles_labels()[0]:
            ax.legend(frameon=False, loc="best")
        return fig


def baseline_figure(angles, uncentered, offset, corrected=False, preview=False):
    with mpl.rc_context(style(preview)):
        fig = Figure(figsize=(8, 6), dpi=100)
        ax = fig.add_subplot()
        fig.subplots_adjust(left=.19, bottom=.18, right=.96, top=.94)
        values = np.asarray(uncentered)
        ax.plot(angles, values-offset if corrected else values, "o", color="black",
                markersize=3.5, linestyle="none", label="Corrected" if corrected else "Uncentered")
        ax.axhline(0 if corrected else offset, color="#0072B2", linewidth=1.2,
                   label="Fixed zero" if corrected else "Baseline")
        ax.set(xlabel="Sample position (deg)", ylabel="Torque (N m)")
        angle_limits(ax, angles)
        ax.xaxis.set_minor_locator(AutoMinorLocator(2))
        ax.yaxis.set_minor_locator(AutoMinorLocator(2))
        ax.legend(frameon=False, loc="best")
        return fig


def angle_limits(ax, angles):
    if not len(angles):
        raise InputError("No samples in the selected angle range.")
    low, high = min(angles), max(angles)
    margin = (high-low)*.025 or 1
    ax.set_xlim(low-margin, high+margin)


def raw_figure(scan, preview=False):
    if not scan.rows:
        raise InputError("No samples in the selected angle range.")
    with mpl.rc_context(style(preview)):
        fig = Figure(figsize=(8, 6), dpi=100)
        fig.subplots_adjust(left=.19, bottom=.18, right=.96, top=.94)
        ax = fig.add_subplot()
        x = [float(r.tokens[5]) for r in scan.rows]
        ax.plot(x, [float(r.tokens[12]) for r in scan.rows], "o", color="black", markersize=3.5, linestyle="none")
        ax.set(xlabel="Measured sample position (deg)", ylabel="Raw torque (N m)")
        angle_limits(ax, x)
        ax.xaxis.set_minor_locator(AutoMinorLocator(2))
        ax.yaxis.set_minor_locator(AutoMinorLocator(2))
        return fig


def export_figure(result, pass_id, folder, view="stages", reference=None):
    if not font_status().startswith("Arial Regular verified:"):
        raise InputError(font_status())
    from pipeline import verify_export
    verify_export(result)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    paths = [folder / f"{pass_id}_{view}.{extension}" for extension in ("pdf", "png")]
    if any(p.exists() for p in paths):
        raise InputError("Plot filename collision; choose a new plot folder.")
    with mpl.rc_context(style()):
        fig = make_figure(result, pass_id, view, reference)
        for path in paths:
            fig.savefig(path, dpi=300, facecolor="white")
    return [str(p) for p in paths]
