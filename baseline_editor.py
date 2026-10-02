"""One-pass baseline editor; drafts never modify committed processing results."""
import copy
import tkinter as tk
from tkinter import ttk
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from baseline import ReviewCache, accepted_record, finite, preview_values
from io_profiles import InputError
from plots import baseline_figure, font_status


class ReviewToolbar(NavigationToolbar2Tk):
    toolitems = tuple(item for item in NavigationToolbar2Tk.toolitems if item[0] != "Save")


class BaselineEditor:
    def __init__(self, app, record, pid):
        self.app, self.record, self.pid = app, record, pid
        self.main_pass_id = pid
        self.dirty = False
        self.dragging = False
        self.loading = False
        self.force_dirty = False
        self.window = tk.Toplevel(app.root)
        self.window.title("Baseline review - Torque Postprocessing 1.1")
        self.window.geometry("1050x820")
        self.window.minsize(880, 740)
        self.window.transient(app.root)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        panel = ttk.Frame(self.window, padding=10)
        panel.pack(fill="both", expand=True)
        self.pass_var = tk.StringVar()
        self.delta = tk.StringVar()
        self.view = tk.StringVar(value="Uncentered")
        self.readouts = tk.StringVar()
        self.effective = tk.StringVar()
        self.notice = tk.StringVar()
        header = ttk.Frame(panel)
        header.pack(fill="x")
        ttk.Label(header, text="Acquired signal pass").pack(side="left")
        self.pass_box = ttk.Combobox(header, textvariable=self.pass_var, width=12, state="readonly",
            values=[p["pass_id"] for p in record["result"]["passes"]])
        self.pass_box.pack(side="left", padx=8)
        self.pass_box.bind("<<ComboboxSelected>>", self.navigate)
        ttk.Label(header, text="View").pack(side="left", padx=(20, 0))
        self.view_box = ttk.Combobox(header, textvariable=self.view, state="readonly",
            values=("Uncentered", "Corrected"), width=16)
        self.view_box.pack(side="left", padx=8)
        self.view_box.bind("<<ComboboxSelected>>", lambda e: self.draw_new())
        ttk.Label(panel, textvariable=self.effective, wraplength=1000).pack(fill="x", pady=5)
        ttk.Label(panel, text="Offsets are in N m. Drag the baseline upward to move corrected values downward. All retained samples define the midrange.",
                  wraplength=1000).pack(fill="x")
        controls = ttk.Frame(panel)
        controls.pack(fill="x", pady=6)
        ttk.Label(controls, text="Delta (N m)").pack(side="left")
        self.entry = ttk.Entry(controls, textvariable=self.delta, width=28)
        self.entry.pack(side="left", padx=8)
        self.buttons = {}
        for name, command in (("Apply", self.apply), ("Cancel", self.cancel),
                              ("Reset", self.reset), ("Remove override", self.remove), ("Close", self.close)):
            self.buttons[name] = ttk.Button(controls, text=name, command=command)
            self.buttons[name].pack(side="left", padx=3)
        ttk.Label(panel, textvariable=self.readouts, font=("Consolas", 10)).pack(fill="x", pady=3)
        ttk.Label(panel, textvariable=self.notice, foreground="#8b3517", wraplength=1000).pack(fill="x", pady=4)
        self.plot_area = ttk.Frame(panel)
        ttk.Label(panel, text=font_status(), wraplength=1000).pack(side="bottom", fill="x")
        self.plot_area.pack(fill="both", expand=True)
        self.canvas = self.toolbar = None
        self.delta.trace_add("write", self.edited)
        self.load_pass(pid)

    def prediction(self):
        return next(p for p in self.record["result"]["passes"] if p["pass_id"] == self.pid)

    def load_pass(self, pid):
        self.pid = pid
        self.pass_var.set(pid)
        pred = self.prediction()
        self.cache = ReviewCache.from_prediction(pred)
        record = pred["baseline_review"]["accepted_record"]
        valid = pred["baseline_review"]["status"] == "active"
        self.original_delta = finite(record["delta_Nm"]) if valid else 0.
        self.loading = True
        self.delta.set(repr(self.original_delta))
        self.loading = False
        self.dirty = self.force_dirty = False
        self.notice.set("Stale setting: review and Apply, Remove override, or disable the checkbox." if pred["baseline_review"]["status"] == "stale"
                        else "Viewing does not accept an override. Apply commits this pass only.")
        inventory = next(p for p in self.record["result"]["inventory"] if p["id"] == pid)
        state = pred["baseline_review"]["status"]
        self.effective.set(f"{pid} | {inventory['T_K']} K | {inventory['field_T']} T | {pred['rows']} actual samples | "
                           f"Export: {pred['centering']}; offset {pred['centering_constant_Nm']:.11g} N m | Review: {state}")
        self.draw_new()

    def edited(self, *unused):
        if self.loading:
            return
        try:
            value = finite(self.delta.get(), "Delta (N m)")
            self.dirty = self.force_dirty or value.hex() != self.original_delta.hex()
            stats = preview_values(self.cache.u, value)
            self.notice.set("Draft: Apply or Cancel before navigation, saving or export." if self.dirty
                            else "Apply commits this pass; viewing alone keeps its current export policy.")
            self.update_plot(stats)
        except InputError as exc:
            self.dirty = True
            self.notice.set(str(exc) + " Apply is unavailable until corrected; Cancel discards this draft.")
            self.buttons["Apply"].configure(state="disabled")

    def draw_new(self):
        if self.canvas:
            self.toolbar.destroy()
            self.canvas.get_tk_widget().destroy()
        try:
            stats = preview_values(self.cache.u, self.delta.get())
        except InputError:
            stats = preview_values(self.cache.u, self.original_delta)
        self.figure = baseline_figure(self.cache.angles, self.cache.u, stats["c_final"],
            corrected=self.view.get() == "Corrected", preview=True)
        self.axes = self.figure.axes[0]
        self.points, self.line = self.axes.lines
        self.canvas = FigureCanvasTkAgg(self.figure, master=self.plot_area)
        self.toolbar = ReviewToolbar(self.canvas, self.plot_area, pack_toolbar=False)
        self.toolbar.pack(side="bottom", fill="x")
        self.canvas.get_tk_widget().pack(side="top", fill="both", expand=True)
        self.canvas.mpl_connect("button_press_event", self.press)
        self.canvas.mpl_connect("motion_notify_event", self.motion)
        self.canvas.mpl_connect("button_release_event", self.release)
        self.update_plot(stats)

        if self.dirty:
            self.edited()

    def update_plot(self, stats):
        self.readouts.set(f"c_mid = {stats['c_mid']:.11g}   c_final = {stats['c_final']:.11g} N m\n"
                          f"Corrected min = {stats['minimum']:.11g}   max = {stats['maximum']:.11g}   "
                          f"signed imbalance (max + min) = {stats['imbalance']:.11g} N m")
        if self.view.get() == "Corrected":
            self.points.set_ydata(stats["corrected"])
            self.line.set_ydata([0., 0.])
        else:
            self.points.set_ydata(self.cache.u)
            self.line.set_ydata([stats["c_final"], stats["c_final"]])
        # Never autoscale here: mouse movement must not change its own coordinates.
        self.canvas.draw_idle()
        self.buttons["Apply"].configure(state="normal")

    def press(self, event):
        if event.button != 1 or event.inaxes != self.axes or self.toolbar.mode or self.view.get() != "Uncentered":
            return
        y = self.axes.transData.transform((0, self.line.get_ydata()[0]))[1]
        if abs(event.y-y) <= 10:
            self.dragging = True

    def motion(self, event):
        if not self.dragging or self.toolbar.mode or event.inaxes != self.axes or event.ydata is None:
            return
        try:
            value = finite(event.ydata) - preview_values(self.cache.u, 0.)["c_mid"]
            self.delta.set(repr(finite(value)))
        except InputError as exc:
            self.notice.set(str(exc))

    def release(self, event):
        self.dragging = False

    def require_clean(self):
        if self.dirty:
            self.notice.set("Apply or Cancel the draft in this editor before continuing.")
            self.window.lift()
            return False
        return True

    def navigate(self, event=None):
        chosen = self.pass_var.get()
        if not self.require_clean():
            self.pass_var.set(self.pid)
            return
        self.load_pass(chosen)

    def apply(self):
        try:
            cfg = copy.deepcopy(self.record["cfg"])
            block = cfg["baseline_review"]
            previous = block["overrides"].get(self.pid)
            block["overrides"][self.pid] = accepted_record(self.cache.binding, self.cache.u,
                                                           self.delta.get(), previous)
            self.app.commit_baseline(self.record, cfg)
            self.load_pass(self.pid)
            self.notice.set("Applied to this pass. Export now uses the accepted offset.")
        except InputError as exc:
            self.notice.set(str(exc))

    def cancel(self):
        self.load_pass(self.pid)
        self.notice.set("Draft discarded. Committed export settings are unchanged.")

    def reset(self):
        self.force_dirty = True
        self.delta.set("0.0")

    def remove(self):
        if not self.require_clean():
            return
        cfg = copy.deepcopy(self.record["cfg"])
        cfg["baseline_review"]["overrides"].pop(self.pid, None)
        self.app.commit_baseline(self.record, cfg)
        self.load_pass(self.pid)
        self.notice.set("Override removed. Export uses this pass's ordinary policy.")

    def close(self, force=False):
        if not force and not self.require_clean():
            return False
        self.window.grab_release()
        self.window.destroy()
        self.app.editor = None
        return True

