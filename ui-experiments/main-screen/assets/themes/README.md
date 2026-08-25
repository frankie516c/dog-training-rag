# Pastel room theme assets

Each theme is a complete, material-aware PNG pack rather than a color overlay. All files retain the dimensions and transparent silhouettes of their source assets, so placement and collision metadata remain unchanged.

## Packs

| Theme | Wall | Floor | Door / main accent | Secondary accent | Trim |
| --- | --- | --- | --- | --- | --- |
| Cherry Blossom | `#f4d7df` sakura plaster | `#c9958e` rose oak | `#a95e76` dusty rose | `#d9849b` blush | `#fff3e1` warm ivory |
| Mint | `#d8efe5` mint plaster | `#c4b69a` pale oak | `#5f9d85` eucalyptus | `#83bfa8` soft mint | `#fff7e8` warm ivory |
| Lavender | `#e7dcf2` lilac plaster | `#b9a6b8` mauve ash | `#79629a` deep lavender | `#a18bc0` soft lavender | `#fff5e9` warm ivory |
| Sky Blue | `#dceef7` powder-blue plaster | `#b6b8b1` cool driftwood | `#4f83aa` denim blue | `#79add0` sky blue | `#fff8ec` warm ivory |
| Butter | `#fff0bd` buttercream plaster | `#d3a866` honey oak | `#b68737` ochre | `#d7ad55` golden butter | `#fff8de` cream |

## Material rules

- The room exports recolor plaster, trim, floorboards, and the door separately. Wood grain and pixel shading are preserved.
- Doghouse shells, patterned cushions, all four cabinet drawer fronts, rugs, balls, toy textiles, bowls, and planter ceramics use their theme's accents.
- Cabinet drawers use a main-accent/soft-accent pair while retaining natural brass hardware. Foreground fences use main-accent structure and soft-accent faces/highlights instead of unthemed natural wood.
- Window scenery, plant foliage, soil, food, water, natural wicker, brass hardware, bones, and the dogs' coat colors remain natural.
- `room.png` is opaque. Decor PNGs preserve their original alpha channel.

## Folder contract

Every theme directory contains the same filenames:

```text
themes/<theme-id>/
  room.png
  ball.png
  basket.png
  bowls.png
  cabinet.png
  doghouse.png
  plant.png
  rug.png
  rug-cream.png
```

Run `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_room_theme_assets.ps1` from the repository root to rebuild all 45 files deterministically from the canonical source PNGs.
