"""Local help viewer and delayed tooltips; no numerical processing."""
import json
from functools import lru_cache
from pathlib import Path
import tkinter as tk
from tkinter import ttk


@lru_cache(maxsize=1)
def help_topics():
    return json.loads(Path(__file__).with_name("help_content.json").read_text(encoding="utf-8"))


def topics_flat(topics=None):
    for topic in help_topics() if topics is None else topics:
        yield topic
        yield from topics_flat(topic.get("children", []))


def help_tip(key):
    topic = next(topic for topic in topics_flat() if topic["id"] == key)
    return topic.get("tip", topic["text"])


class HoverHelp:
    """One tooltip per window. All timers and bindings run on the Tk thread."""
    delay_ms = 1000

    def __init__(self, window):
        self.window = window
        self.source = self.popup = None
        self.pending = self.leaving = None
        self.over_source = self.over_popup = self.suppressed = False
        self.text = ""
        self.bindings = []
        window.bind("<Escape>", self.escape, add="+")
        window.bind("<ButtonPress>", self.interact, add="+")
        window.bind("<KeyPress>", self.interact, add="+")
        window.bind("<Destroy>", self.destroyed, add="+")

    def attach(self, widget, key=None, text=None):
        message = text if text is not None else help_tip(key)
        widget.bind("<Enter>", lambda event: self.enter(widget, message), add="+")
        widget.bind("<Leave>", lambda event: self.leave(widget), add="+")
        widget.bind("<Destroy>", self.destroyed, add="+")
        self.bindings.append((str(widget), key))
        return widget

    def cancel(self, name):
        token = getattr(self, name)
        if token:
            try:
                self.window.after_cancel(token)
            except tk.TclError:
                pass
            setattr(self, name, None)

    def enter(self, widget, text):
        self.cancel("leaving")
        if self.source is widget:
            if not self.over_source and not self.over_popup:
                self.suppressed = False
            self.over_source = True
            if self.suppressed or self.popup or self.pending:
                return
        else:
            self.dismiss()
            self.source = widget
            self.suppressed = False
        self.text = text
        self.over_source = True
        self.pending = self.window.after(self.delay_ms, self.show)

    def leave(self, widget):
        if widget is self.source:
            self.over_source = False
            self.cancel("pending")
            self.queue_leave()

    def queue_leave(self):
        self.cancel("leaving")
        # Allow crossing the small gap from the control into the tooltip.
        self.leaving = self.window.after(150, self.finish_leave)

    def finish_leave(self):
        self.leaving = None
        if not self.over_source and not self.over_popup:
            self.dismiss()
            self.source = None
            self.suppressed = False

    def popup_enter(self, event=None):
        self.over_popup = True
        self.cancel("leaving")

    def popup_leave(self, event=None):
        self.over_popup = False
        self.queue_leave()

    def show(self):
        self.pending = None
        if self.suppressed or not self.over_source or not self.source or not self.source.winfo_exists():
            return
        text = self.text() if callable(self.text) else self.text
        popup = self.popup = tk.Toplevel(self.window)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.transient(self.window)
        label = tk.Label(popup, text=text, justify="left", wraplength=360,
                         background="#fffde7", foreground="black", relief="solid",
                         borderwidth=1, padx=9, pady=7, takefocus=False)
        label.pack()
        popup.bind("<Enter>", self.popup_enter)
        popup.bind("<Leave>", self.popup_leave)
        popup.bind("<ButtonPress>", self.interact)
        popup.bind("<Escape>", self.escape)
        popup.update_idletasks()
        x = self.source.winfo_rootx()
        y = self.source.winfo_rooty() + self.source.winfo_height() + 2
        width, height = popup.winfo_reqwidth(), popup.winfo_reqheight()
        x = max(0, min(x, popup.winfo_screenwidth() - width - 4))
        if y + height > popup.winfo_screenheight():
            y = max(0, self.source.winfo_rooty() - height - 2)
        popup.geometry(f"+{x}+{y}")
        if self.window.winfo_viewable():
            popup.deiconify()

    def dismiss(self):
        self.cancel("pending")
        self.cancel("leaving")
        popup, self.popup = self.popup, None
        self.over_popup = False
        if popup:
            popup.destroy()

    def interact(self, event=None):
        self.suppressed = self.source is not None
        self.dismiss()

    def escape(self, event=None):
        if self.popup or self.pending:
            self.interact()
            return "break"

    def destroyed(self, event):
        if event.widget is self.window or event.widget is self.source:
            self.dismiss()
            self.source = None


class HelpWindow:
    def __init__(self, parent):
        self.parent = parent
        self.previous_grab = parent.grab_current()
        self.window = tk.Toplevel(parent)
        self.window.withdraw()
        self.window.title("Torque Postprocessing Help")
        self.window.geometry("980x680")
        self.window.minsize(760, 500)
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", lambda event: self.close())
        panes = ttk.Panedwindow(self.window, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=10, pady=10)
        left, right = ttk.Frame(panes), ttk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=3)
        self.tree = ttk.Treeview(left, show="tree", selectmode="browse")
        self.tree.column("#0", width=230, minwidth=160)
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.text = tk.Text(right, wrap="word", width=65, font=("Segoe UI", 11),
                            padx=14, pady=12, borderwidth=0, state="disabled")
        scroll = ttk.Scrollbar(right, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("heading", font=("Segoe UI", 15, "bold"), spacing3=14)
        self.topics = {}
        def add(topics, parent=""):
            for topic in topics:
                self.topics[topic["id"]] = topic
                self.tree.insert(parent, "end", iid=topic["id"], text=topic["title"], open=False)
                add(topic.get("children", []), topic["id"])
        add(help_topics())
        self.tree.bind("<<TreeviewSelect>>", self.select)
        self.tree.selection_set("summary")
        self.select()
        ttk.Button(self.window, text="Close", command=self.close).pack(anchor="e", padx=12, pady=(0, 10))
        if parent.winfo_viewable():
            self.window.deiconify()
        if self.previous_grab:
            self.window.grab_set()

    def select(self, event=None):
        selected = self.tree.selection()
        if not selected:
            return
        topic = self.topics[selected[0]]
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("end", topic["title"] + "\n", "heading")
        self.text.insert("end", topic["text"])
        self.text.configure(state="disabled")
        self.text.yview_moveto(0)

    def close(self):
        self.window.destroy()
        if self.previous_grab and self.previous_grab.winfo_exists():
            self.previous_grab.grab_set()
