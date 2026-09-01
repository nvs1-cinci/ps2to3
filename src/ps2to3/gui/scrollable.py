"""a vertically scrolling container."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class Scrollable(ttk.Frame):
    """A vertically scrolling container.

    The scrollbar appears only when the content is taller than the window, and
    the content is kept as wide as the viewport so it reflows rather than being
    clipped horizontally.
    """

    def __init__(self, master):
        super().__init__(master)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0,
                                takefocus=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.vbar = ttk.Scrollbar(self, orient='vertical',
                                  command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._sync_bar)
        self.inner = ttk.Frame(self.canvas)
        self._item = self.canvas.create_window((0, 0), window=self.inner,
                                               anchor='nw')
        self.inner.bind('<Configure>', self._on_inner)
        self.canvas.bind('<Configure>', self._on_canvas)
        self._bar_shown = False

    # -- geometry -------------------------------------------------------- #
    def _on_inner(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox(self._item))
        self._update_bar()

    def _on_canvas(self, event):
        self.canvas.itemconfigure(self._item, width=event.width)
        self._update_bar()

    def _update_bar(self):
        need = self.inner.winfo_reqheight() > self.canvas.winfo_height()
        if need and not self._bar_shown:
            self.vbar.grid(row=0, column=1, sticky='ns')
            self._bar_shown = True
        elif not need and self._bar_shown:
            self.vbar.grid_remove()
            self._bar_shown = False
            self.canvas.yview_moveto(0)

    def _sync_bar(self, first, last):
        self.vbar.set(first, last)
        self._update_bar()

    # -- wheel ----------------------------------------------------------- #
    def bind_wheel(self, widget=None, skip=()):
        """Give the wheel to this container, except over widgets that scroll."""
        widget = widget if widget is not None else self.inner
        if widget not in skip:
            widget.bind('<MouseWheel>', self._wheel)
            widget.bind('<Button-4>', self._wheel)
            widget.bind('<Button-5>', self._wheel)
        for child in widget.winfo_children():
            self.bind_wheel(child, skip)

    def _wheel(self, event):
        if not self._bar_shown:
            return None
        if getattr(event, 'num', None) == 4:
            step = -1
        elif getattr(event, 'num', None) == 5:
            step = 1
        else:
            step = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(step, 'units')
        return 'break'
