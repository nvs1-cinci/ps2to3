"""the modal that has to be acknowledged before the app will do anything."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

DISCLAIMER_TITLE = 'HEY!  Read this before you use it'

DISCLAIMER = [
    ('h', 'PrusaSlicer 3 is an early Alpha Preview.'),
    ('p', 'At this time Prusa is only focused on testing the slicer with '
          'INCLUDED printers, which is the current consumer Prusa lineup. '
          'Everything outside that list is untested territory as far as Prusa '
          'is concerned.'),
    ('h', 'This is a quick and dirty way to add non-Prusa printers.'),
    ('p', 'It IS NOT MEANT TO BE OFFICIAL IN ANY CAPACITY. Third-party printer '
          'support will arrive later down the line, once the app is more stable '
          'and Prusa builds it properly. Nothing here is endorsed by, supported '
          'by, or connected to Prusa Research.'),
    ('p', 'It works by translating profiles into the 3.x format and merging them '
          'into the PrusaResearch vendor, because this alpha only exposes that '
          'one vendor. Your converted printers therefore sit inside Prusa\'s own '
          'preset bundle rather than beside it, and a PrusaSlicer preset update '
          'will silently remove them - use "Restore after a Prusa update" to put '
          'them back.'),
    ('h', 'I OFFER NO GUARANTEES OR PROMISES. This app is likely to break something.'),
    ('p', 'A converted profile is a translation, not a copy. Options whose units '
          'or meaning changed between versions are dropped rather than guessed, '
          'settings that only exist in the source slicer are dropped, and custom '
          'G-code is rewritten where the old placeholders no longer exist. Read '
          'the conversion notes the app prints - they list every one of those '
          'decisions.'),
    ('p', 'Check the G-code before you trust it. Look at the temperatures, the '
          'bed size, the start and end macros and the first layer. Do not start '
          'an unattended print from a converted profile without watching one '
          'through first. Keep your working 2.x install for real work, and back '
          'up your PrusaSlicer 3 data directory before installing anything.'),
    ('h', 'If PrusaSlicer 3 crashes, DO NOT REPORT IT AS A BUG TO PRUSA.'),
    ('p', 'Not while a non-standard printer profile is involved - one this app '
          'added, or any profile that did not ship with the alpha. A crash caused '
          'by a converted profile is noise in their tracker and wastes the time '
          'of people trying to ship the thing.'),
    ('p', 'Instead: remove the converted printers, restart, and try to reproduce '
          'the same bug using only the profiles PrusaSlicer 3 shipped with. If it '
          'still happens on stock profiles, then it is a real bug and worth '
          'submitting - and say which stock printer you reproduced it on. If it '
          'only happens with a converted profile, it is this tool\'s problem, not '
          'Prusa\'s.'),
]

class Disclaimer(tk.Toplevel):
    """A modal that has to be acknowledged before the app can be used."""

    def __init__(self, master, theme=None):
        super().__init__(master)
        self.accepted = False
        self.theme = theme
        self.title(DISCLAIMER_TITLE)
        self.transient(master)
        self.protocol('WM_DELETE_WINDOW', self.decline)
        palette = theme.palette if theme else None
        if palette:
            self.configure(background=palette.bg)

        frame = ttk.Frame(self, padding=18)
        frame.pack(fill='both', expand=True)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        head = ttk.Frame(frame)
        head.grid(row=0, column=0, sticky='ew', pady=(0, 12))
        if palette:
            mark = tk.Canvas(head, width=6, height=26, highlightthickness=0,
                             borderwidth=0, takefocus=0, background=palette.bg)
            mark.grid(row=0, column=0, sticky='ns', padx=(0, 12))
            mark.create_rectangle(0, 0, 6, 26, fill=palette.accent, width=0)
        ttk.Label(head, text='HEY!', style='Title.TLabel' if theme else '',
                  font=None if theme else ('TkDefaultFont', 15, 'bold')).grid(
            row=0, column=1, sticky='w')

        box = ttk.Frame(frame)
        box.grid(row=1, column=0, sticky='nsew')
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        text = tk.Text(box, wrap='word', relief='flat', padx=14, pady=10,
                       borderwidth=0, width=72, height=22, cursor='arrow')
        text.grid(row=0, column=0, sticky='nsew')
        bar = ttk.Scrollbar(box, orient='vertical', command=text.yview)
        bar.grid(row=0, column=1, sticky='ns')
        text.configure(yscrollcommand=bar.set)

        ui = theme.ui if theme else 'TkDefaultFont'
        text.tag_configure('h', font=(ui, 10, 'bold'), spacing1=12, spacing3=4,
                           foreground=palette.accent if palette else '#a33')
        text.tag_configure('p', font=(ui, 10), spacing3=8, lmargin1=2, lmargin2=2)
        if theme:
            theme.surface(text, 'text')
        for kind, body in DISCLAIMER:
            text.insert('end', body + '\n', kind)
        text.configure(state='disabled')

        row = ttk.Frame(frame)
        row.grid(row=2, column=0, sticky='ew', pady=(14, 0))
        ttk.Button(row, text='quit', command=self.decline).pack(side='right')
        ok = ttk.Button(row, text='i understand, continue', command=self.accept,
                        style='Accent.TButton' if theme else 'TButton')
        ok.pack(side='right', padx=(0, 10))
        ok.focus_set()
        self.bind('<Return>', lambda _e: self.accept())
        self.bind('<Escape>', lambda _e: self.decline())

        self.update_idletasks()
        w = min(self.winfo_reqwidth(), master.winfo_screenwidth() - 120)
        h = min(self.winfo_reqheight(), master.winfo_screenheight() - 160)
        self.minsize(min(520, w), min(360, h))
        x = master.winfo_rootx() + max((master.winfo_width() - w) // 2, 0)
        y = master.winfo_rooty() + 40
        self.geometry(f'{w}x{h}+{x}+{y}')
        self.grab_set()

    def accept(self):
        self.accepted = True
        self.destroy()

    def decline(self):
        self.accepted = False
        self.destroy()
