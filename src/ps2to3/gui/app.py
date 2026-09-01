"""the desktop window.

tkinter ships with python, so the app needs no dependency to install, and
closing the window ends the process. every path it offers is discovered from the
platform rather than written down.
"""

from __future__ import annotations

import contextlib
import os
import queue
import shutil
import sys
import tempfile
import threading
import tkinter as tk
import traceback
import zipfile
from tkinter import filedialog, messagebox, ttk

from .. import __author__, __license__, __url__, __version__, paths
from ..bundle import SourceError, open_bundle
from ..convert import Conversion
from ..emit import slug
from ..install import install_merge, list_injected, restore_all
from ..schema import Schema, SchemaUnavailable
from .disclaimer import Disclaimer
from .scrollable import Scrollable
from .theme import Theme

APP_NAME = 'ps2to3 importer'


class Section:
    """a titled group: bold label, hairline rule, body.

    prusaslicer groups its settings this way rather than in boxes, and a ttk
    LabelFrame cannot be made to look like it.
    """

    LABEL_COLUMN = 172      # every section lines its labels up with the others

    def __init__(self, parent, title, row, pady=(14, 0)):
        wrap = ttk.Frame(parent)
        wrap.grid(row=row, column=0, sticky='nsew', pady=pady)
        wrap.columnconfigure(0, weight=1)
        ttk.Label(wrap, text=title, style='Section.TLabel').grid(
            row=0, column=0, sticky='w')
        ttk.Separator(wrap, orient='horizontal').grid(row=1, column=0, sticky='ew',
                                                      pady=(4, 10))
        self.frame = ttk.Frame(wrap)
        self.frame.grid(row=2, column=0, sticky='nsew')
        self.frame.columnconfigure(0, minsize=self.LABEL_COLUMN)
        wrap.rowconfigure(2, weight=1)


class FileRow:
    """a label, a path box, and a browse button."""

    def __init__(self, parent, row, label, hint, patterns, hints=None):
        self.value = tk.StringVar()
        self.patterns = patterns
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky='w', pady=(8, 0))
        ttk.Entry(parent, textvariable=self.value, width=34).grid(
            row=row, column=1, sticky='ew', pady=(8, 0), padx=(10, 6))
        ttk.Button(parent, text='browse', command=self.browse, width=10).grid(
            row=row, column=2, sticky='e', pady=(8, 0))
        if hint:
            lab = ttk.Label(parent, text=hint, style='Hint.TLabel', wraplength=520,
                            justify='left')
            lab.grid(row=row + 1, column=1, columnspan=2, sticky='w', padx=(10, 0))
            if hints is not None:
                hints.append(lab)

    def browse(self):
        got = filedialog.askopenfilename(title='choose a file',
                                         filetypes=self.patterns)
        if got:
            self.value.set(got)

    def get(self):
        return self.value.get().strip() or None


class Importer(tk.Tk):
    HINT_MARGIN = 250

    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.protocol('WM_DELETE_WINDOW', self.quit_app)
        self._queue: queue.Queue = queue.Queue()
        self._result_zip = None
        self._hints: list[ttk.Label] = []
        self._data_dirs = paths.data_dirs()
        self._build()
        self._size_to_screen()
        self.after(80, self._drain)
        self.after(120, self._show_disclaimer)

    # ---------------------------------------------------------------- startup
    def _show_disclaimer(self):
        dlg = Disclaimer(self, self.theme)
        self.wait_window(dlg)
        if not dlg.accepted:
            self.quit_app()

    class _Ev:
        def __init__(self, width):
            self.width = width

    def _size_to_screen(self):
        """open at a size that fits this screen, and never clip the form."""
        max_w = self.winfo_screenwidth() - 80
        max_h = self.winfo_screenheight() - 140

        self._rewrap(self._Ev(self.HINT_MARGIN + 200))
        self.update_idletasks()
        min_w = self.scroll.inner.winfo_reqwidth() + 22

        self._rewrap(self._Ev(900))
        self.update_idletasks()
        want_w = self.scroll.inner.winfo_reqwidth() + 22
        want_h = self.scroll.inner.winfo_reqheight() + 22

        self.minsize(min(min_w, max_w), min(420, max_h))
        self.geometry(f'{min(max(want_w, min_w), max_w)}x{min(want_h, max_h)}')
        self.scroll.bind_wheel(skip=(self.log,))

    # ---------------------------------------------------------------- layout
    def _build(self):
        self.theme = Theme(self)

        self.scroll = Scrollable(self)
        self.scroll.pack(fill='both', expand=True)
        self.theme.surface(self.scroll.canvas, 'canvas')
        outer = ttk.Frame(self.scroll.inner, padding=(20, 16))
        outer.pack(fill='both', expand=True)
        outer.columnconfigure(0, weight=1)
        self.scroll.canvas.bind('<Configure>', self._rewrap, add='+')

        self._build_header(outer)
        self._build_profiles(outer)
        self._build_artwork(outer)
        self._build_options(outer)
        self._build_actions(outer)
        self._build_log(outer)

    def _build_header(self, outer):
        bar = ttk.Frame(outer)
        bar.grid(row=0, column=0, sticky='ew')
        bar.columnconfigure(1, weight=1)

        # the accent bar prusaslicer puts beside a heading, drawn rather than
        # borrowed: the app's own logo is prusa's, and this tool is not theirs
        mark = tk.Canvas(bar, width=6, height=30, highlightthickness=0,
                         borderwidth=0, takefocus=0)
        mark.grid(row=0, column=0, rowspan=2, sticky='ns', padx=(0, 12))
        mark.create_rectangle(0, 0, 6, 30, fill=self.theme.palette.accent, width=0)
        self._mark = mark

        ttk.Label(bar, text='profile importer', style='Title.TLabel').grid(
            row=0, column=1, sticky='w')
        sub = ttk.Label(bar, style='Hint.TLabel', wraplength=520, justify='left',
                        text='prusaslicer 2.x bundles, orca and bambu profiles, or a '
                             '3mf, converted to the prusaslicer 3.x preset format')
        sub.grid(row=1, column=1, sticky='w')
        self._hints.append(sub)

        self.theme_btn = ttk.Button(bar, text=self._theme_label(), width=7,
                                    command=self._flip_theme)
        self.theme_btn.grid(row=0, column=2, rowspan=2, sticky='e')

        # the licence asks a derivative to keep this visible in the interface,
        # so the interface has somewhere to keep it
        credit = ttk.Frame(bar)
        credit.grid(row=2, column=1, columnspan=2, sticky='e', pady=(6, 0))
        ttk.Label(credit, style='Hint.TLabel',
                  text=f'ps2to3 {__version__}  ·  by {__author__}  ·  '
                  ).pack(side='left')
        self.site = ttk.Label(credit, style='Link.TLabel', cursor='hand2',
                              text=__url__.split('//')[-1])
        self.site.pack(side='left')
        self.site.bind('<Button-1>', lambda _e: self._open(__url__))
        ttk.Label(credit, style='Hint.TLabel',
                  text=f'  ·  {__license__}').pack(side='left')

        ttk.Separator(outer, orient='horizontal').grid(row=1, column=0, sticky='ew',
                                                       pady=(14, 0))

    @staticmethod
    def _open(url):
        """the credit's link, opened in whatever the desktop uses."""
        import webbrowser
        webbrowser.open(url)

    def _theme_label(self):
        return 'light' if self.theme.is_dark else 'dark'

    def _flip_theme(self):
        self.theme.toggle()
        self.theme_btn.configure(text=self._theme_label())
        self._mark.itemconfigure(1, fill=self.theme.palette.accent)

    def _build_profiles(self, outer):
        box = Section(outer, 'profiles', row=2).frame
        box.columnconfigure(1, weight=1)
        self.source = FileRow(
            box, 0, 'profile source',
            'a 2.x vendor or config bundle (.ini), an orca or bambu vendor index '
            '(.json), or a .3mf whose embedded configuration becomes one printer',
            [('profiles', '*.ini *.json *.3mf'), ('all files', '*.*')],
            hints=self._hints)
        self.library = FileRow(
            box, 2, 'orca filament library',
            'optional. orca keeps generic materials in OrcaFilamentLibrary.json, '
            'needed when a machine\'s materials are named "... @System"',
            [('orca index', '*.json'), ('all files', '*.*')], hints=self._hints)

        installed = paths.legacy_bundles()
        if installed:
            ttk.Label(box, text='installed 2.x bundles').grid(
                row=4, column=0, sticky='w', pady=(10, 0))
            self.installed_pick = ttk.Combobox(box, state='readonly', values=installed)
            self.installed_pick.grid(row=4, column=1, sticky='ew', padx=(10, 6),
                                     pady=(10, 0))
            ttk.Button(box, text='use', width=10,
                       command=self._use_installed).grid(row=4, column=2, sticky='e',
                                                         pady=(10, 0))
            hint = ttk.Label(box, style='Hint.TLabel', wraplength=520, justify='left',
                             text=f'found on this machine in '
                                  f'{", ".join(paths.legacy_vendor_dirs())}')
            hint.grid(row=5, column=1, columnspan=2, sticky='w', padx=(10, 0))
            self._hints.append(hint)

    def _use_installed(self):
        got = self.installed_pick.get()
        if got:
            self.source.value.set(got)

    def _build_artwork(self, outer):
        box = Section(outer, 'printer artwork', row=3).frame
        box.columnconfigure(1, weight=1)
        self.bed_texture = FileRow(box, 0, 'bed texture', '',
                                   [('texture', '*.svg *.png'), ('all files', '*.*')])
        self.bed_model = FileRow(box, 1, 'bed model', '',
                                 [('model', '*.stl'), ('all files', '*.*')])
        self.thumbnail = FileRow(
            box, 2, 'printer image',
            'shown in the printer picker. a source that names its own artwork keeps '
            'it, these fill in what it does not name, which is everything for a '
            'config bundle or a 3mf',
            [('image', '*.png *.svg *.jpg'), ('all files', '*.*')], hints=self._hints)

    def _build_options(self, outer):
        box = Section(outer, 'naming and options', row=4).frame
        box.columnconfigure(1, weight=1)
        box.columnconfigure(3, weight=1)
        self.vendor_id = tk.StringVar()
        self.vendor_name = tk.StringVar()
        ttk.Label(box, text='vendor id').grid(row=0, column=0, sticky='w')
        ttk.Entry(box, textvariable=self.vendor_id).grid(row=0, column=1, sticky='ew',
                                                        padx=(10, 16))
        ttk.Label(box, text='vendor name').grid(row=0, column=2, sticky='w')
        ttk.Entry(box, textvariable=self.vendor_name).grid(row=0, column=3, sticky='ew',
                                                          padx=(10, 0))
        blank = ttk.Label(box, text='left blank, both come from the source',
                          style='Hint.TLabel', wraplength=520, justify='left')
        blank.grid(row=1, column=0, columnspan=4, sticky='w', pady=(2, 8))
        self._hints.append(blank)

        self.fix_gcode = tk.BooleanVar(value=True)
        self.do_install = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text='repair custom g-code that uses removed placeholders',
                        variable=self.fix_gcode).grid(row=2, column=0, columnspan=4,
                                                      sticky='w')
        ttk.Checkbutton(box, text='install into a prusaslicer 3 data directory',
                        variable=self.do_install,
                        command=self._toggle_datadir).grid(row=3, column=0,
                                                           columnspan=4, sticky='w')

        self.dd_label = ttk.Label(box, text='data directory')
        self.dd_label.grid(row=4, column=0, sticky='w', pady=(6, 0))
        self.datadir = tk.StringVar(value=paths.default_data_dir())
        values = [d.path for d in self._data_dirs] or [self.datadir.get()]
        self.dd_pick = ttk.Combobox(box, textvariable=self.datadir, values=values)
        self.dd_pick.grid(row=4, column=1, columnspan=2, sticky='ew', padx=(10, 6),
                          pady=(6, 0))
        self.dd_btn = ttk.Button(box, text='browse', width=10, command=self._pick_dd)
        self.dd_btn.grid(row=4, column=3, sticky='e', pady=(6, 0))
        detected = ttk.Label(box, style='Hint.TLabel', wraplength=520, justify='left',
                             text=self._datadir_hint())
        detected.grid(row=5, column=0, columnspan=4, sticky='w', pady=(4, 0))
        self._hints.append(detected)
        self._toggle_datadir()

    def _datadir_hint(self):
        if not self._data_dirs:
            return ('no prusaslicer 3 data directory found on this machine. install '
                    'and run prusaslicer 3 once, or point this at one')
        return 'detected: ' + '; '.join(d.label for d in self._data_dirs)

    def _toggle_datadir(self):
        state = 'readonly' if self.do_install.get() else 'disabled'
        self.dd_pick.configure(state=state)
        self.dd_btn.configure(state='normal' if self.do_install.get() else 'disabled')
        self.dd_label.configure(style='' if self.do_install.get() else 'Hint.TLabel')

    def _pick_dd(self):
        got = filedialog.askdirectory(title='prusaslicer 3 data directory',
                                      initialdir=self.datadir.get())
        if got:
            self.datadir.set(got)

    def _build_actions(self, outer):
        bar = ttk.Frame(outer)
        bar.grid(row=5, column=0, sticky='ew', pady=(18, 10))
        self.go = ttk.Button(bar, text='convert', command=self.start,
                             style='Accent.TButton')
        self.go.pack(side='left')
        self.save_btn = ttk.Button(bar, text='save repository', command=self.save_zip,
                                   state='disabled')
        self.save_btn.pack(side='left', padx=(10, 0))
        ttk.Button(bar, text='restore after a prusa update',
                   command=self.restore).pack(side='left', padx=(10, 0))
        # an idle indeterminate bar still draws a chunk, which reads as progress
        self.progress = ttk.Progressbar(bar, mode='indeterminate', length=170)
        self.progress_shown = False

    def _build_log(self, outer):
        box = Section(outer, 'result', row=6, pady=(0, 0)).frame
        outer.rowconfigure(6, weight=1)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.log = tk.Text(box, height=10, wrap='word', relief='flat',
                           padx=10, pady=8, borderwidth=0,
                           font=(self.theme.mono, 9))
        self.log.grid(row=0, column=0, sticky='nsew')
        bar = ttk.Scrollbar(box, command=self.log.yview)
        bar.grid(row=0, column=1, sticky='ns')
        self.log.configure(yscrollcommand=bar.set, state='disabled')
        self.theme.surface(self.log, 'text')

    def _show_progress(self, on):
        if on and not self.progress_shown:
            self.progress.pack(side='right')
            self.progress.start(14)
            self.progress_shown = True
        elif not on and self.progress_shown:
            self.progress.stop()
            self.progress.pack_forget()
            self.progress_shown = False

    def _rewrap(self, event):
        width = max(event.width - self.HINT_MARGIN, 200)
        for lab in self._hints:
            lab.configure(wraplength=width)

    # ---------------------------------------------------------------- logging
    def say(self, text='', tag=None):
        self._queue.put(('log', text, tag))

    def clear(self):
        self.log.configure(state='normal')
        self.log.delete('1.0', 'end')
        self.log.configure(state='disabled')

    def _drain(self):
        try:
            while True:
                kind, a, b = self._queue.get_nowait()
                if kind == 'log':
                    self.log.configure(state='normal')
                    self.log.insert('end', a + '\n', b or ())
                    self.log.see('end')
                    self.log.configure(state='disabled')
                elif kind == 'done':
                    self._show_progress(False)
                    self.go.configure(state='normal')
                    self._result_zip = a
                    self.save_btn.configure(state='normal' if a else 'disabled')
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(80, self._drain)

    # ---------------------------------------------------------------- convert
    def start(self):
        src = self.source.get()
        if not src:
            messagebox.showinfo(APP_NAME, 'choose a profile source first')
            return
        self.clear()
        self.go.configure(state='disabled')
        self.save_btn.configure(state='disabled')
        self._show_progress(True)
        opts = {
            'src': src,
            'library': self.library.get(),
            'bed_model': self.bed_model.get(),
            'bed_texture': self.bed_texture.get(),
            'thumbnail': self.thumbnail.get(),
            'vendor_id': self.vendor_id.get().strip(),
            'vendor_name': self.vendor_name.get().strip(),
            'fix_gcode': self.fix_gcode.get(),
            'install': self.do_install.get(),
            'datadir': self.datadir.get().strip(),
        }
        threading.Thread(target=self._work, args=(opts,), daemon=True).start()

    def _work(self, opts):
        try:
            self.convert(opts)
        except (SourceError, OSError) as e:
            # something about the chosen files, not about this app: a traceback
            # would bury the one line that says which file and why
            self.say()
            self.say(str(e), 'err')
            self._queue.put(('done', None, None))
        except Exception:
            self.say()
            self.say(traceback.format_exc(), 'err')
            self._queue.put(('done', None, None))

    def convert(self, opts):
        work = tempfile.mkdtemp(prefix='ps2to3-app-')
        assets = os.path.join(work, 'assets')
        os.makedirs(assets)
        visual = {}
        for key in ('bed_model', 'bed_texture', 'thumbnail'):
            path = opts.get(key)
            if path and os.path.isfile(path):
                shutil.copy2(path, assets)
                visual[key] = os.path.basename(path)

        vendor_id = opts['vendor_id'] or slug(
            os.path.splitext(os.path.basename(opts['src']))[0]) or 'Imported'

        self.say(f'reading {os.path.basename(opts["src"])}', 'head')
        try:
            schema = Schema.load()
        except SchemaUnavailable as e:
            self.say(str(e), 'err')
            self._queue.put(('done', None, None))
            return

        notes: list[str] = []
        bundle = open_bundle(opts['src'], note=notes.append,
                             extra_trees=(opts['library'],) if opts['library'] else (),
                             valid_names=schema.names(),
                             fix_gcode=opts['fix_gcode'], schema=schema)
        conv = Conversion(bundle, schema, vendor_id=vendor_id,
                          vendor_name=opts['vendor_name'] or None,
                          assets_dir=assets, fix_gcode=opts['fix_gcode'],
                          visual=visual)
        for m in notes:
            conv.conv.note(m)
        out = os.path.join(work, 'build')
        info = conv.emit(out)

        self.say()
        self.say(f'{conv.vendor_name}  [{conv.vendor_id}]', 'ok')
        self.say(f'  printer models    {info["models"]}')
        for m in conv.models.values():
            shape = (f'{m.extruders}-tool changer' if m.is_toolchanger
                     else f'one tool, {m.extruders}-slot mmu feeder' if m.is_mmu
                     else 'single tool')
            self.say(f'      {m.display} - {shape}, nozzles '
                     + ', '.join(t.label for t in m.tools))
        self.say(f'  print presets     {info["print_presets"]}')
        self.say(f'  filament presets  {info["filament_presets"]}')
        self.say(f'  assets            {info["assets"]}')

        zip_path = os.path.join(work, f'{slug(vendor_id)}-3x-repository.zip')
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
            for root, _dirs, fns in os.walk(out):
                for fn in fns:
                    p = os.path.join(root, fn)
                    z.write(p, os.path.relpath(p, out))

        if opts['install']:
            self.say()
            try:
                got = install_merge(out, opts['datadir'], vendor_id)
                self.say(f'installed {got["files"]} files into', 'ok')
                self.say(f'  {got["target"]}')
                self.say('a preset update replaces that vendor and removes this. '
                         'use "restore after a prusa update"', 'warn')
            except (SystemExit, OSError) as e:
                self.say(f'install failed: {e}', 'err')

        self._report_notes(conv)
        self.say()
        self.say('done. "save repository" writes the zip wherever you like', 'ok')
        self._queue.put(('done', zip_path, None))

    def _report_notes(self, conv):
        if conv.skipped:
            self.say()
            self.say(f'{len(conv.skipped)} preset(s) skipped, their compatibility '
                     f'condition matches no printer in this source', 'warn')
            for kind, name in conv.skipped[:25]:
                self.say(f'    {kind}: {name}')
            if len(conv.skipped) > 25:
                self.say(f'    and {len(conv.skipped) - 25} more')
        if conv.conv.notes:
            self.say()
            self.say(f'{sum(conv.conv.notes.values())} conversion note(s)', 'warn')
            for msg, n in conv.conv.notes.most_common():
                self.say(f'  x{n:<4} {msg}')

    # ---------------------------------------------------------------- restore
    def restore(self):
        datadir = self.datadir.get().strip() or paths.default_data_dir()
        self.clear()
        try:
            listing = list_injected(datadir)
        except SystemExit as e:
            self.say(str(e), 'err')
            return
        if not listing:
            self.say('nothing has been installed from this app yet', 'warn')
            return
        self.say(datadir, 'head')
        for rec in listing:
            state = ('installed' if rec['present']
                     else 'missing, restoring' if rec['buildable']
                     else 'missing, and its build folder is gone')
            self.say(f'  {rec["vendor_id"]:16} {state}',
                     'ok' if rec['present'] else 'warn')
        done, skipped = restore_all(datadir)
        self.say()
        if done:
            self.say('restored ' + ', '.join(done), 'ok')
        for rec in skipped:
            self.say(f'{rec["vendor_id"]}: convert it again, its build folder '
                     f'({rec["build"] or "unknown"}) is gone', 'err')
        if not done and not skipped:
            self.say('everything is already installed', 'ok')

    def save_zip(self):
        if not self._result_zip:
            return
        got = filedialog.asksaveasfilename(
            title='save the 3.x repository', defaultextension='.zip',
            initialfile=os.path.basename(self._result_zip),
            filetypes=[('zip archive', '*.zip')])
        if got:
            shutil.copy2(self._result_zip, got)
            self.say(f'saved to {got}', 'ok')

    def quit_app(self):
        """closing the window ends the process, background thread and all.

        the exit does not depend on the teardown: tk may already be gone (a
        pending callback firing after the window went away), and the process
        still has to end rather than linger with a converter thread in it.
        """
        with contextlib.suppress(tk.TclError):
            self.destroy()
        os._exit(0)


def main():
    try:
        Importer().mainloop()
    except tk.TclError as e:
        print(f'{APP_NAME}: no display available ({e})', file=sys.stderr)
        print('on a headless machine use the command line: python -m ps2to3 --help',
              file=sys.stderr)
        return 1
    return 0
