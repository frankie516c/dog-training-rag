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
  assert.ok(Math.abs(grid.col - 3.25) < 1e-8);
  assert.ok(Math.abs(grid.row - 1.75) < 1e-8);
}

{
  const corners = [
    [0, 0, physics.GEOMETRY.back],
    [physics.GRID, 0, physics.GEOMETRY.right],
    [physics.GRID, physics.GRID, physics.GEOMETRY.front],
    [0, physics.GRID, physics.GEOMETRY.left]
  ];
  corners.forEach(([col, row, expected]) => {
    const screen = physics.gridToScreen(col, row);
    assert.ok(Math.abs(screen.x - expected.x) < 1e-9);
    assert.ok(Math.abs(screen.y - expected.y) < 1e-9);
    const grid = physics.screenToGrid(screen.x, screen.y);
    assert.ok(Math.abs(grid.col - col) < 1e-8);
    assert.ok(Math.abs(grid.row - row) < 1e-8);
  });

  for (let index = 0; index <= 20; index += 1) {
    const col = (index * 1.73) % physics.GRID;
    const row = (index * 2.41) % physics.GRID;
    const screen = physics.gridToScreen(col, row);
    const roundTrip = physics.screenToGrid(screen.x, screen.y);
    assert.ok(Math.abs(roundTrip.col - col) < 1e-8);
    assert.ok(Math.abs(roundTrip.row - row) < 1e-8);
  }

  const leftFrontCell = physics.gridToScreen(0.5, physics.GRID - 0.5);
  const deepestCell = physics.gridToScreen(physics.GRID - 0.5, physics.GRID - 0.5);
  assert.ok(leftFrontCell.x < 12, "the left floor strip must be placeable");
  assert.ok(deepestCell.y > 89, "the front floor strip must be placeable");
}

{
  const items = {
    rug: { col: 1, row: 1, facing: 0 },
    cabinet: { col: 3, row: 0, facing: 0 }
  };
  const occupied = physics.occupiedCells(items, catalog);
  assert.deepEqual([...occupied].sort(), ["3,0", "4,0"]);
  const placementOccupied = physics.occupiedCells(items, catalog, null, true);
  assert.equal(placementOccupied.size, 11, "rug cells must be reserved for asset placement");
  assert.equal(physics.canPlace(catalog[2], { col: 3, row: 0, facing: 0 }, occupied), false);
  assert.equal(physics.canPlace(catalog[2], { col: 2, row: 2, facing: 0 }, occupied), true);
}

{
  const floorAsset = {
    width: 10,
    aspectRatio: 1,
    artAnchor: [50, 80],
    floorBox: [10, 70, 90, 95],
    footprint: [2, 2]
  };
  const first = physics.visualBounds(floorAsset, { col: 5, row: 7, facing: 0 });
  const overlapping = physics.visualBounds(floorAsset, { col: 6, row: 7, facing: 0 });
  const separate = physics.visualBounds(floorAsset, { col: 12, row: 2, facing: 0 });
  assert.equal(physics.boundsOverlap(first, overlapping, 0.35), true);
  assert.equal(physics.boundsOverlap(first, separate, 0.35), false);

  const edgePlacement = { col: 0, row: physics.GRID - 2, facing: 0 };
  assert.equal(physics.canPlace(floorAsset, edgePlacement, new Set()), true, "an in-grid footprint must be placeable at the floor edge");
  assert.equal(physics.floorBoxFits(floorAsset, edgePlacement, 0.2), false, "the art box may overhang without overriding the grid boundary");
}

{
  const wall = new Set(Array.from({ length: physics.GRID }, (_, row) => physics.cellKey(2, row)));
  const from = { x: 1.3, y: 1.2 };
  const diagonal = physics.slide(from, { x: 1.7, y: 1.5 }, wall);
  assert.equal(diagonal.x, from.x, "blocked x axis must not cross the wall");
  assert.equal(diagonal.y, 1.5, "free y axis should slide along the wall");
  assert.equal(physics.blockedAt(1.5, 1.5, wall), true, "body radius must catch the wall before the center enters");
}

{
  const blocked = new Set([physics.cellKey(2, 2)]);
  const free = physics.nearestFree({ x: 2.5, y: 2.5 }, blocked);
  assert.equal(blocked.has(physics.cellKey(Math.floor(free.x), Math.floor(free.y))), false);
}

{
  const layout = [
    { id: "rug", width: 39, aspectRatio: 1156 / 622, artAnchor: [50, 50], floorBox: [6, 10, 94, 90], footprint: [7, 7], flat: true, placement: { col: 5, row: 6, facing: 0 } },
    { id: "plant", width: 9, aspectRatio: 667 / 1075, artAnchor: [50, 93], floorBox: [45, 92, 50, 99], footprint: [1, 2], flat: false, placement: { col: 15, row: 0, facing: 0 } },
    { id: "house", width: 19.5, aspectRatio: 927 / 952, artAnchor: [50, 78], floorBox: [42, 90, 50, 98], footprint: [3, 4], flat: false, placement: { col: 13, row: 3, facing: 0 } },
    { id: "ball", width: 4.8, aspectRatio: 504 / 519, artAnchor: [50, 94], floorBox: [22, 72, 78, 98], footprint: [1, 1], flat: false, placement: { col: 15, row: 12, facing: 0 } },
    { id: "cabinet", width: 22, aspectRatio: 890 / 874, artAnchor: [50, 77], floorBox: [45, 90, 55, 98], footprint: [5, 2], flat: false, placement: { col: 0, row: 0, facing: 0 } },
    { id: "basket", width: 9, aspectRatio: 774 / 667, artAnchor: [50, 78], floorBox: [7, 25, 93, 96], footprint: [2, 2], flat: false, placement: { col: 3, row: 13, facing: 0 } },
    { id: "bowls", width: 9, aspectRatio: 873 / 446, artAnchor: [50, 58], floorBox: [5, 12, 95, 92], footprint: [2, 1], flat: false, placement: { col: 11, row: 14, facing: 0 } }
  ];
  const placed = {};

  layout.forEach((asset, index) => {
    const occupied = physics.occupiedCells(placed, layout, null, true);
    assert.equal(physics.canPlace(asset, asset.placement, occupied), true, `${asset.id} footprint overlaps`);
    assert.equal(physics.floorBoxFits(asset, asset.placement, 0.2), true, `${asset.id} leaves the floor`);
    const bounds = physics.visualBounds(asset, asset.placement);
    layout.slice(0, index).forEach((existing) => {
      assert.equal(
        physics.boundsOverlap(bounds, physics.visualBounds(existing, existing.placement), 0.35),
        false,
        `${asset.id} visually overlaps ${existing.id}`
      );
    });
    placed[asset.id] = asset.placement;
  });
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
    { x: physics.GRID - 0.5, y: 0.5 },
    { x: physics.GRID - 0.5, y: physics.GRID - 0.5 },
    { x: 0.5, y: physics.GRID - 0.5 },
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
