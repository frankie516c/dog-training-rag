"use strict";

const assert = require("node:assert/strict");
const physics = require("./room-physics.js");

const catalog = [
  { id: "rug", footprint: [3, 3], flat: true },
  { id: "cabinet", footprint: [2, 1], flat: false },
  { id: "plant", footprint: [1, 1], flat: false }
];

{
  const point = physics.gridToScreen(3.25, 1.75);
  const grid = physics.screenToGrid(point.x, point.y);
  assert.ok(Math.abs(grid.col - 3.25) < 1e-9);
  assert.ok(Math.abs(grid.row - 1.75) < 1e-9);
}

{
  const items = {
    rug: { col: 1, row: 1, facing: 0 },
    cabinet: { col: 3, row: 0, facing: 0 }
  };
  const occupied = physics.occupiedCells(items, catalog);
  assert.deepEqual([...occupied].sort(), ["3,0", "4,0"]);
  assert.equal(physics.canPlace(catalog[2], { col: 3, row: 0, facing: 0 }, occupied), false);
  assert.equal(physics.canPlace(catalog[2], { col: 2, row: 2, facing: 0 }, occupied), true);
}

{
  const wall = new Set(Array.from({ length: 6 }, (_, row) => physics.cellKey(2, row)));
  const from = { x: 1.7, y: 1.2 };
  const diagonal = physics.slide(from, { x: 2.1, y: 1.5 }, wall);
  assert.equal(diagonal.x, from.x, "blocked x axis must not cross the wall");
  assert.equal(diagonal.y, 1.5, "free y axis should slide along the wall");
  assert.equal(physics.blockedAt(1.9, 1.5, wall), true, "body radius must catch the wall before the center enters");
}

{
  const blocked = new Set([physics.cellKey(2, 2)]);
  const free = physics.nearestFree({ x: 2.5, y: 2.5 }, blocked);
  assert.equal(blocked.has(physics.cellKey(Math.floor(free.x), Math.floor(free.y))), false);
}

{
  const blocked = new Set([
    physics.cellKey(2, 1),
    physics.cellKey(2, 2),
    physics.cellKey(3, 1),
    physics.cellKey(3, 2),
    physics.cellKey(4, 4)
  ]);
  const targets = [
    { x: 5.5, y: 0.5 },
    { x: 5.5, y: 5.5 },
    { x: 0.5, y: 5.5 },
    { x: 0.5, y: 0.5 }
  ];
  let dog = { x: 0.5, y: 0.5 };

  for (let step = 0; step < 2400; step += 1) {
    const target = targets[Math.floor(step / 600)];
    const dx = target.x - dog.x;
    const dy = target.y - dog.y;
    const distance = Math.hypot(dx, dy) || 1;
    const wanted = physics.clampDog({
      x: dog.x + (dx / distance) * 0.025,
      y: dog.y + (dy / distance) * 0.025
    });
    dog = physics.slide(dog, wanted, blocked);
    assert.equal(physics.blockedAt(dog.x, dog.y, blocked), false, `dog entered furniture at step ${step}`);
  }
}

console.log("room physics tests passed");
