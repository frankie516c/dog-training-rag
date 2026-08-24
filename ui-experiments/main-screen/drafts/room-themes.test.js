"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const themes = require("./room-themes.js");

const expectedIds = ["cherry-blossom", "mint", "lavender", "sky-blue", "butter"];

assert.deepEqual(themes.catalog.map((theme) => theme.id), expectedIds);
assert.ok(Object.isFrozen(themes.catalog));
themes.catalog.forEach((theme) => {
  assert.ok(Object.isFrozen(theme), `${theme.id} must be immutable`);
  assert.match(theme.swatch, /^#[0-9a-f]{6}$/i);
});
assert.equal(themes.get("mint").label, "Mint");
assert.equal(themes.get("missing"), themes.catalog[0]);

const assetNames = ["room", "ball", "cabinet", "doghouse", "bowls", "plant", "rug", "rug-cream", "basket"];
const sourceDimensions = {
  room: [1122, 1402],
  ball: [504, 519],
  cabinet: [890, 874],
  doghouse: [927, 952],
  bowls: [873, 446],
  plant: [667, 1075],
  rug: [1156, 622],
  "rug-cream": [1155, 620],
  basket: [774, 667]
};

themes.catalog.forEach((theme) => {
  assetNames.forEach((name) => {
    const file = path.resolve(__dirname, `../assets/themes/${theme.id}/${name}.png`);
    const png = fs.readFileSync(file);
    assert.equal(png.toString("hex", 0, 8), "89504e470d0a1a0a", `${theme.id}/${name} must be PNG`);
    assert.deepEqual([png.readUInt32BE(16), png.readUInt32BE(20)], sourceDimensions[name], `${theme.id}/${name} dimensions`);
  });
});

console.log(`room-themes: ${themes.catalog.length} palettes and ${themes.catalog.length * assetNames.length} themed PNGs verified`);
