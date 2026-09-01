"""custom g-code placeholders that changed between 2.x and 3.x."""

from __future__ import annotations

import re

GCODE_OPTIONS = (
    'start_gcode', 'end_gcode', 'before_layer_gcode', 'layer_gcode',
    'between_objects_gcode', 'color_change_gcode', 'pause_print_gcode',
    'template_custom_gcode', 'toolchange_gcode', 'start_filament_gcode',
    'end_filament_gcode', 'output_filename_format', 'post_process',
)

# 2.x placeholders that 3.x renamed.  Verified against 3.0.0-alpha10 by slicing
# a probe G-code with each one: the old names abort the export, the new ones work.
PLACEHOLDER_RENAMES = {
    'printer_preset': 'printer_settings_id',
    'print_preset': 'print_settings_id',
    'filament_preset': 'filament_settings_id',
}

# 2.x placeholders with no 3.x counterpart; G-code using them will not export.
PLACEHOLDER_REMOVED = ('physical_printer_preset',)


def migrate_gcode(text, note, fix_removed=False):
    """Rename known-renamed placeholders and handle removed ones."""
    for old, new in PLACEHOLDER_RENAMES.items():
        pattern = r'(?<![A-Za-z_0-9])' + old + r'(?![A-Za-z_0-9])'
        text, n = re.subn(pattern, new, text)
        if n:
            note(f'custom G-code: renamed the {old!r} placeholder to {new!r} '
                 f'(3.x dropped the old name)')
    for gone in PLACEHOLDER_REMOVED:
        word = r'(?<![A-Za-z_0-9])' + gone + r'(?![A-Za-z_0-9])'
        if not re.search(word, text):
            continue
        if not fix_removed:
            note(f'custom G-code: uses the {gone!r} placeholder, which 3.x removed '
                 f'with no replacement, so this preset will not export G-code. '
                 f'Re-run with --fix-gcode to neutralise it, or edit the source')
            continue
        # An interpolation prints nothing; a bare use inside a {if ...} becomes an
        # empty string, which is how the expression would read with no physical
        # printer selected - the closest thing 3.x has to the 2.x meaning.
        text = re.sub(r'\[' + gone + r'\]|\{\s*' + gone + r'\s*\}', '', text)
        text = re.sub(word, '""', text)
        note(f'custom G-code: neutralised the {gone!r} placeholder, which has no '
             f'3.x counterpart (--fix-gcode): interpolations print nothing and '
             f'comparisons see an empty string')
    return text
