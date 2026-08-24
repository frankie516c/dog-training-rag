# Dog breed presets

## Branch strategy

`feature/dog-breed-presets` is a child of `feature/modular-room-collision-dogs`.
The parent branch owns room geometry, furniture collision, and dog movement. This
child branch owns breed data, art, selection UI, and breed-specific size tuning.
Keeping those concerns separate lets collision fixes land without carrying a
large binary-art review and lets individual breed sheets be regenerated safely.

Recommended merge order:

1. Review and stabilize `feature/modular-room-collision-dogs`.
2. Merge or rebase `feature/dog-breed-presets` onto that result.
3. Merge the child branch into the eventual UI integration branch.

## Folder and runtime contract

Each breed has one versionable folder:

```text
ui-experiments/main-screen/
├── assets/dogs/<breed-id>/walk.png
└── drafts/
    ├── dog-presets.js
    └── dog-presets.test.js
```

`dog-presets.js` is the only catalog. A preset contains:

- stable `id`, English `label`, and Korean `labelKo`;
- `sheet`, `frameCount`, and `fps` for rendering;
- `visualWidth` for apparent size;
- `bodyRadius` for floor collision;
- `speed` for movement tuning.

The art contract is a 2328×568 RGBA PNG containing four 582×568 right-facing
walk frames. Art size stays constant across all four frames. The room renderer
does not contain breed conditionals.

## Included IDs

The requested informal spellings were normalized to canonical breed names and
stable kebab-case IDs:

`beagle`, `toy-poodle`, `maltese`, `yorkshire-terrier`, `chihuahua`,
`bichon-frise`, `labrador-retriever`, `jindo`, `shiba-inu`,
`siberian-husky`, `pomeranian`, `border-collie`, `welsh-corgi`,
`french-bulldog`, `pug`, and `schnauzer`.

Use the in-room picker or `?dog=<breed-id>` to preview a preset, for example:

```text
v7-growing-pixel-room.html?dog=jindo
```

## Adding a breed

1. Generate one four-pose landscape sheet using the existing poodle sheet as
   the style and pose reference. The built-in image-generation path used this
   prompt template:

   ```text
   Use case: stylized-concept
   Asset type: production game walk-cycle sprite sheet
   Input image: style and four-pose animation reference only.
   Primary request: create <breed description>.
   Scene/backdrop: perfectly flat solid #00ff00 chroma-key background, with no
   shadows, gradients, texture, checkerboard, or floor.
   Style/medium: match the reference's polished cute high-resolution pixel art.
   Composition/framing: one horizontal strip with exactly four non-overlapping
   equal cells; one full right-facing dog per cell; same walk poses and baseline.
   Constraints: consistent scale and pixel density; full ears, paws, and tail;
   unmistakable breed traits; no collar; do not use #00ff00 on the dog.
   Avoid: extra dogs, merged frames, dividers, text, watermark, scenery, cast
   shadow, crop, photorealism, blur, or transparency checkerboard.
   ```

2. Remove the chroma key with the installed image-generation helper.
3. Normalize the alpha output:

   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts/normalize_dog_sprite.ps1 `
     -InputPath <alpha-source.png> `
     -OutputPath ui-experiments/main-screen/assets/dogs/<breed-id>/walk.png
   ```

4. Append one preset to `dog-presets.js` and run
   `node ui-experiments/main-screen/drafts/dog-presets.test.js`.
