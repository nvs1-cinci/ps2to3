# ADR-0002: derive the orca key mapping from shared profiles

- status: accepted
- date: 2026-08-31
- deciders: repo owner

## context

orcaslicer (and bambu studio, which it forked from, and snapmaker's fork of orca)
store profiles as a tree of json documents and renamed most of the option
vocabulary on the way. importing a u1 or a bambu printer means knowing which orca
option is which prusaslicer option, for a few hundred names, with no published
mapping.

guessing from the names is wrong often enough to matter, and wrong in ways that
still slice: a mis-mapped speed produces a print, just not the one the profile
described.

## decisions

chosen: derive the mapping from profiles both projects ship for the **same
machines**. orca ships prusa profiles; prusaslicer 2.x ships its own. align each
orca preset to its 2.x counterpart on the ~115 option names the two formats
already share, then read the renames off the pairs whose *values* agree across
every aligned pair.

rejected alternatives:

- reading orca's `PrintConfig.cpp` alone: it names orca's options, not what
  prusaslicer calls them
- name similarity: it produced `overhang_1_4_speed` → `overhang_speed_0`, which is
  backwards. orca counts overhang bands by supported width and prusaslicer by
  unsupported, so the four speeds run in opposite order. the value agreement says
  `overhang_speed_3`, 14 aligned pairs out of 14

the same corpus settled two keys that are simply misspelt in shipped profiles
(`detraction_speed`, `inital_layer_height`), and the inversion in
`filament_shrink`: orca states the printed size as a percentage of the intended
one, prusaslicer states the compensation, so passing 100 through scales every
model by two.

## consequences

- the mapping is evidence-backed, and each entry can be re-derived
- `orca.check_targets()` runs at every conversion and fails loudly when a rename
  target is not an option in the 3.x schema, which is how the two misspellings
  were caught
- coverage is limited to options that appear in the shared corpus. an option only
  orca has is either inlined into the g-code that reads it, or reported
- a new orca release can rename something again. the mapping is a fixed table, not
  a live derivation, so it needs re-checking against a new corpus
