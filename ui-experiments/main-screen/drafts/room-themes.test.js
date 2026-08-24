"use strict";

const assert = require("node:assert/strict");
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

console.log(`room-themes: ${themes.catalog.length} pastel themes verified`);
