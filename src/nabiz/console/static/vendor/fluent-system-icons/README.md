# Fluent System Icons — console navigation subset

Source: [Microsoft Fluent System Icons](https://github.com/microsoft/fluentui-system-icons),
commit [`a563cf9166f4f91aa617557ed272612b7f0a2f72`](https://github.com/microsoft/fluentui-system-icons/tree/a563cf9166f4f91aa617557ed272612b7f0a2f72).
The selected assets use the **24 regular** style. `LICENSE` is the upstream MIT licence,
Copyright (c) 2020 Microsoft Corporation; `NOTICE` is the upstream notice, both unchanged.

These are local SVG assets. No Fluent runtime, package, font, script or stylesheet is loaded.
The unmodified source SVGs and their SHA-256 checksums are kept with `manifest.json` so the
console sprite can be checked against the exact reviewed source.

| Console symbol | Official source icon |
|---|---|
| `i-home` | Home |
| `i-chat` | Chat |
| `i-city` | City |
| `i-chart` | Data Bar Vertical |
| `i-map` | Map |
| `i-transport` | Vehicle Bus |
| `i-profile` | Person |
| `i-bookmark` | Bookmark |
| `i-memory` | Brain |
| `i-accessibility` | Accessibility |

## Sprite conversion

The console's `../../icons.svg` keeps all existing symbol IDs. Only `i-map` replaces a
previous Tabler glyph; the other Fluent symbols are added under new semantic IDs. All
remaining Tabler geometry is unchanged, with its original licence in `../../icons.LICENSE.txt`.

To reproduce the Fluent contribution, read each `manifest.json` entry and verify its source
file's SHA-256 checksum. Copy its path `d` attribute without modifying coordinates into
`<symbol id="…" viewBox="0 0 24 24">`. Set each path to `fill="currentColor" stroke="none"`
instead of the source's fixed ink colour, and replace or append that symbol in the console
sprite. The explicit no-stroke setting prevents the existing Tabler stroke rule from making
Fluent's filled outline geometry heavier. These paint attributes inherit the page's light,
dark and high-contrast foreground; source assets remain byte-for-byte unchanged.

The older `scripts/design/build_icon_sprite.py` builds the separate web application's Tabler
sprite. It does not incorporate this console-only subset. Preserve this mapping when syncing
the web glyphs into the console sprite.
