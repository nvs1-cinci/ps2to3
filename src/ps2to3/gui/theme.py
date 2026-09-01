"""prusaslicer 3's look, as far as ttk carries it.

the palette is read off prusaslicer 3's own resources rather than invented:

| colour | where it comes from |
|---|---|
| `#ED6B21` | the accent in 433 of the icons the app ships |
| `#FA6831` | the same orange in its newer web assets, used here for hover |
| `#F7F7F7` `#D1D1D1` `#808080` | the greys those icons are drawn on |
| `#f6f6f6` `#333333` | the light ground and text of its fallback web pages |
| `#121212` `#e0e0e0` `#d3d3d3` `#555555` | the dark ones |
| `#ED0000` | attention.svg |
| Inter | the ui font it ships in resources/fonts |

so a converted printer is set up in a window that looks like the app it is being
set up for. flat surfaces, hairline borders, square corners, one orange button
for the action that does the work.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont
from tkinter import ttk

ACCENT = '#ED6B21'
ACCENT_HOT = '#FA6831'
ERROR = '#ED0000'


@dataclass(frozen=True)
class Palette:
    name: str
    bg: str            # window ground
    panel: str         # a section's ground
    field: str         # entry and text ground
    border: str
    text: str
    muted: str         # hints, disabled labels
    accent: str
    accent_hot: str
    on_accent: str     # text on an accent button
    ok: str
    warn: str
    err: str
    head: str
    sel_bg: str
    sel_fg: str


LIGHT = Palette(
    name='light',
    bg='#F7F7F7', panel='#FFFFFF', field='#FFFFFF', border='#D1D1D1',
    text='#333333', muted='#808080',
    accent=ACCENT, accent_hot=ACCENT_HOT, on_accent='#FFFFFF',
    ok='#1C7C4A', warn='#8A5A00', err=ERROR, head='#333333',
    sel_bg=ACCENT, sel_fg='#FFFFFF',
)

DARK = Palette(
    name='dark',
    bg='#121212', panel='#1B1B1B', field='#232323', border='#555555',
    text='#E0E0E0', muted='#9A9A9A',
    accent=ACCENT, accent_hot=ACCENT_HOT, on_accent='#FFFFFF',
    ok='#4CAF7D', warn='#E0A030', err='#FF5A5A', head='#E0E0E0',
    sel_bg=ACCENT, sel_fg='#FFFFFF',
)

# prusaslicer ships Inter and uses it; the rest are each platform's own ui face,
# so the window looks native when Inter is not installed
FONT_CANDIDATES = ('Inter', 'Inter UI', 'Segoe UI', 'SF Pro Text', 'Helvetica Neue',
                   'Cantarell', 'Noto Sans', 'DejaVu Sans')
MONO_CANDIDATES = ('JetBrains Mono', 'Cascadia Mono', 'SF Mono', 'DejaVu Sans Mono',
                   'Consolas', 'Menlo')


def prefers_dark() -> bool:
    """the desktop's own light/dark preference, or light when it does not say."""
    try:
        if sys.platform == 'darwin':
            done = subprocess.run(['defaults', 'read', '-g', 'AppleInterfaceStyle'],
                                  capture_output=True, text=True, timeout=5)
            return 'dark' in done.stdout.lower()
        if sys.platform == 'win32':
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize')
            with key:
                light, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
            return not light
        done = subprocess.run(
            ['gsettings', 'get', 'org.gnome.desktop.interface', 'color-scheme'],
            capture_output=True, text=True, timeout=5)
        return 'prefer-dark' in done.stdout
    except (OSError, subprocess.SubprocessError, ValueError, ImportError):
        return False


def _first_installed(root, candidates, fallback):
    available = {f.lower() for f in tkfont.families(root)}
    for name in candidates:
        if name.lower() in available:
            return name
    return fallback


class Theme:
    """holds the palette in use and repaints on a switch.

    ttk styles are re-read by every widget that uses them, so switching is a
    matter of reconfiguring the styles and recolouring the plain tk widgets,
    which are the only ones that carry their own colours.
    """

    def __init__(self, root: tk.Misc, dark: bool | None = None):
        self.root = root
        self.style = ttk.Style(root)
        self.ui = _first_installed(root, FONT_CANDIDATES, 'TkDefaultFont')
        self.mono = _first_installed(root, MONO_CANDIDATES, 'TkFixedFont')
        self._surfaces: list[tuple[tk.Misc, str]] = []
        self.palette = DARK if (prefers_dark() if dark is None else dark) else LIGHT
        self.apply()

    # -- registration ----------------------------------------------------- #
    def surface(self, widget, role='panel'):
        """a plain tk widget that has to be recoloured by hand on a switch."""
        self._surfaces.append((widget, role))
        self._paint(widget, role)
        return widget

    # -- switching -------------------------------------------------------- #
    def toggle(self):
        self.palette = LIGHT if self.palette is DARK else DARK
        self.apply()
        for widget, role in list(self._surfaces):
            if widget.winfo_exists():
                self._paint(widget, role)

    @property
    def is_dark(self):
        return self.palette is DARK

    # -- painting --------------------------------------------------------- #
    def _paint(self, widget, role):
        p = self.palette
        if role == 'canvas':
            widget.configure(background=p.bg)
        elif role == 'text':
            widget.configure(background=p.field, foreground=p.text,
                             insertbackground=p.text,
                             highlightthickness=1, highlightbackground=p.border,
                             highlightcolor=p.border,
                             selectbackground=p.sel_bg, selectforeground=p.sel_fg)
            for tag, colour in (('ok', p.ok), ('warn', p.warn), ('err', p.err),
                                ('head', p.accent)):
                widget.tag_configure(tag, foreground=colour)
        elif role == 'rule':
            widget.configure(background=p.border)
        else:
            widget.configure(background=p.panel)

    def apply(self):
        p, st = self.palette, self.style
        # clam is the only built-in theme that takes colours from a style
        with contextlib.suppress(tk.TclError):
            st.theme_use('clam')
        self.root.configure(background=p.bg)

        base = (self.ui, 10)
        st.configure('.', background=p.bg, foreground=p.text, fieldbackground=p.field,
                     bordercolor=p.border, darkcolor=p.panel, lightcolor=p.panel,
                     troughcolor=p.bg, focuscolor=p.accent, font=base)

        st.configure('TFrame', background=p.bg)
        st.configure('Card.TFrame', background=p.panel)
        st.configure('Rule.TFrame', background=p.border)

        st.configure('TLabel', background=p.bg, foreground=p.text, font=base)
        st.configure('Card.TLabel', background=p.panel, foreground=p.text)
        st.configure('Hint.TLabel', background=p.bg, foreground=p.muted,
                     font=(self.ui, 9))
        st.configure('Title.TLabel', background=p.bg, foreground=p.head,
                     font=(self.ui, 15, 'bold'))
        st.configure('Section.TLabel', background=p.bg, foreground=p.text,
                     font=(self.ui, 10, 'bold'))
        st.configure('Accent.TLabel', background=p.bg, foreground=p.accent,
                     font=(self.ui, 10, 'bold'))
        st.configure('Link.TLabel', background=p.bg, foreground=p.accent,
                     font=(self.ui, 9, 'underline'))

        # square, hairline-bordered buttons, the way the slicer draws them
        st.configure('TButton', background=p.panel, foreground=p.text,
                     bordercolor=p.border, focusthickness=0, relief='flat',
                     padding=(12, 6), font=base)
        st.map('TButton',
               background=[('pressed', p.border), ('active', p.bg),
                           ('disabled', p.panel)],
               foreground=[('disabled', p.muted)],
               bordercolor=[('active', p.accent), ('focus', p.accent),
                            ('disabled', p.border)])

        st.configure('Accent.TButton', background=p.accent, foreground=p.on_accent,
                     bordercolor=p.accent, relief='flat', padding=(14, 7),
                     font=(self.ui, 10, 'bold'))
        st.map('Accent.TButton',
               background=[('pressed', p.accent), ('active', p.accent_hot),
                           ('disabled', p.border)],
               foreground=[('disabled', p.muted)],
               bordercolor=[('active', p.accent_hot), ('disabled', p.border)])

        st.configure('TEntry', fieldbackground=p.field, foreground=p.text,
                     bordercolor=p.border, insertcolor=p.text, padding=5,
                     relief='flat')
        st.map('TEntry', bordercolor=[('focus', p.accent)],
               foreground=[('disabled', p.muted)])

        st.configure('TCombobox', fieldbackground=p.field, background=p.panel,
                     foreground=p.text, bordercolor=p.border, arrowcolor=p.text,
                     padding=4, relief='flat')
        st.map('TCombobox', bordercolor=[('focus', p.accent)],
               fieldbackground=[('disabled', p.bg), ('readonly', p.field)],
               foreground=[('disabled', p.muted)], arrowcolor=[('disabled', p.muted)])
        # the dropdown list is a tk widget behind the ttk one
        self.root.option_add('*TCombobox*Listbox.background', p.field)
        self.root.option_add('*TCombobox*Listbox.foreground', p.text)
        self.root.option_add('*TCombobox*Listbox.selectBackground', p.sel_bg)
        self.root.option_add('*TCombobox*Listbox.selectForeground', p.sel_fg)

        st.configure('TCheckbutton', background=p.bg, foreground=p.text,
                     indicatorcolor=p.field, bordercolor=p.border, focusthickness=0,
                     padding=3, font=base)
        st.map('TCheckbutton',
               indicatorcolor=[('selected', p.accent), ('pressed', p.accent_hot)],
               foreground=[('disabled', p.muted)])

        st.configure('Horizontal.TProgressbar', background=p.accent,
                     troughcolor=p.field, bordercolor=p.border, lightcolor=p.accent,
                     darkcolor=p.accent, thickness=6)

        st.configure('Vertical.TScrollbar', background=p.border, troughcolor=p.bg,
                     bordercolor=p.bg, arrowcolor=p.text, relief='flat', width=12)
        st.map('Vertical.TScrollbar', background=[('active', p.muted)])

        st.configure('TSeparator', background=p.border)
