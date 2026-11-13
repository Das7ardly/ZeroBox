# ZeroBox

Windows desktop app that turns a dieline into a folded 3D box with the artwork on it.

Open a die from a PDF / Illustrator file, paste it from Illustrator, or pull it from an
open Illustrator / Photoshop document. ZeroBox finds the panels, folds the box, and
exports product-shot images (JPEG / PNG / TIFF).

## Features

- Reads dielines from `.pdf` / `.ai` files, the clipboard (Illustrator), and open
  Illustrator / Photoshop documents.
- Finds the die among the artwork automatically; every line group can be set to
  cut / crease / perforation / not die, and the choice is remembered for later files.
- Folds any kind of die: tuck boxes, shipping cartons, trays, mailers, sleeves, polygon
  tubes, pyramids, tapered boxes, two-piece boxes. Dies drawn at an angle are folded
  upright.
- Checks the folded box (panels sticking out, crossing, hanging free, open seams) and
  repairs fold angles.
- Manual tools in the 2D view: front panel, fold / cut, keep flat, exclude a panel, or
  draw the panels yourself.
- Camera with real lens focal lengths, straight verticals (shift), adjustable light.
- Colour-managed artwork (ICC), sRGB-tagged export, optional removal of die lines.

## Run from source

```
py -m pip install -r requirements.txt
py main.py
```

Python 3.12+ on Windows. `pywin32` is only needed for the Illustrator / Photoshop link.

## Build the portable exe

```
py -m pip install pyinstaller
py -m PyInstaller --noconfirm --clean --distpath release zerobox-portable.spec
```

The result is a single file, `release/ZeroBox-Portable-<version>.exe`.

## Tests

```
py tests/test_core.py     # unit tests
py tests/stress.py        # 42 box styles x drawing styles x rotation / mirror / scale
py tests/stress2.py       # harder inputs: details, junk, degenerate shapes, manual edits
py tests/two_colour.py    # dies in two colours with creases drawn short, artwork in the die colour
py tests/ui_fuzz.py       # random clicks, drags, keys, edits and exports on the window
```

Some unit tests use a real die when one is given:
`set ZEROBOX_TEST_DIE=C:\path\to\die.ai`. `ui_fuzz.py` takes extra files from
`ZEROBOX_TEST_FILES` (paths separated by `;`).

## Layout

| Path | What |
| --- | --- |
| `main.py` | entry point |
| `zerobox/dieline.py` | reading dies (PDF / AI / clipboard), picking the die lines |
| `zerobox/roles.py` | cut / crease roles and remembered rules |
| `zerobox/geometry.py` | panels, hinges, the fold tree |
| `zerobox/solver.py` | fold angles that close the box |
| `zerobox/check.py` | checking and repairing the folded box |
| `zerobox/fold3d.py` | folding in 3D and the camera |
| `zerobox/adobe.py` | Illustrator / Photoshop link |
| `zerobox/ui/` | the window, 2D / 3D views, rendering, theme |
| `tests/` | unit tests, stress grids, window fuzz |
