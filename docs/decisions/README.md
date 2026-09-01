# architecture decisions

this directory holds architecture decision records (ADRs): the durable,
append-only log of *why* the system is shaped the way it is. one file per
decision, numbered in order.

## how it works

- new decision → copy `0000-template.md` to `NNNN-short-title.md`, next number, zero-padded
- a merged ADR is immutable. to overturn one, write a new ADR and set the old one's status to `superseded by ADR-NNNN`, never rewrite its body

## status values

| status | means |
|---|---|
| `proposed` | under discussion |
| `accepted` | decided and in effect |
| `superseded by ADR-NNNN` | replaced by a later decision |
| `deprecated` | no longer relevant, not replaced |

## index

| ADR | title | status |
|---|---|---|
| 0000 | template (not a real decision) | - |
| [0001](0001-merge-into-the-prusaresearch-vendor.md) | merge conversions into the PrusaResearch vendor | accepted |
| [0002](0002-derive-the-orca-mapping-from-shared-profiles.md) | derive the orca key mapping from shared profiles | accepted |
| [0003](0003-a-tkinter-window-not-a-browser-ui.md) | a tkinter window, not a browser ui | accepted |
| [0004](0004-discover-paths-by-validating-them.md) | discover prusaslicer's paths by validating them | accepted |
