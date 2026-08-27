"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const presets = require("./dog-presets.js");

const expectedIds = [
  "beagle",
  "toy-poodle-silver",
  "toy-poodle-light-brown",
  "toy-poodle-chocolate",
  "maltese",
  "yorkshire-terrier",
  "chihuahua",
  "bichon-frise",
  "labrador-retriever",
  "jindo",
  "shiba-inu-black",
  "shiba-inu-beige",
  "shiba-inu-orange",
  "siberian-husky",
  "pomeranian-black-tan",
  "pomeranian-beige",
  "pomeranian-white",
  "border-collie",
  "welsh-corgi",
  "dachshund-short-brown",
  "dachshund-short-black",
  "dachshund-long-beige",
  "french-bulldog",
  "pug",
  "schnauzer"
];

assert.deepEqual(presets.catalog.map((entry) => entry.id), expectedIds);
assert.equal(new Set(expectedIds).size, expectedIds.length);
assert.ok(Object.isFrozen(presets.catalog));

presets.catalog.forEach((entry) => {
  assert.ok(Object.isFrozen(entry), `${entry.id} must be immutable`);
  assert.match(entry.sheet, new RegExp(`^\\.\\./assets/dogs/${entry.id}/walk\\.png$`));
  assert.match(entry.portrait, new RegExp(`^\\.\\./assets/dogs/${entry.id}/portrait\\.png$`));
  assert.equal(entry.frameCount, 4);
  assert.ok(entry.fps > 0);
  assert.ok(entry.visualWidth > 0);
  assert.ok(entry.bodyRadius > 0);
  assert.ok(entry.speed > 0);

  const file = path.resolve(__dirname, entry.sheet);
  const portraitFile = path.resolve(__dirname, entry.portrait);
  const png = fs.readFileSync(file);
  assert.equal(png.toString("hex", 0, 8), "89504e470d0a1a0a", `${entry.id} must be PNG`);
  assert.equal(png.readUInt32BE(16), 2328, `${entry.id} sheet width`);
  assert.equal(png.readUInt32BE(20), 568, `${entry.id} sheet height`);
  assert.equal(png[25], 6, `${entry.id} must use RGBA color`);
  const portrait = fs.readFileSync(portraitFile);
  assert.equal(portrait.toString("hex", 0, 8), "89504e470d0a1a0a", `${entry.id} portrait must be PNG`);
});

assert.equal(presets.get("shiba-inu-black").label, "Black Shiba Inu");
assert.equal(presets.get("missing"), presets.catalog[0]);

console.log(`dog-presets: ${presets.catalog.length} presets and sprite sheets verified`);
