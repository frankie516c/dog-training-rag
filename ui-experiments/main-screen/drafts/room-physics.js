(function attachRoomPhysics(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.DaengsRoomPhysics = api;
})(typeof globalThis !== "undefined" ? globalThis : window, () => {
  "use strict";

  // Browser port of the grid-footprint and axis-slide approach from
  // https://github.com/gayeoniee/isometric_test (IsoMath, MiniRoomState, DogHerd).
  const GRID = 6;
  const GEOMETRY = Object.freeze({
    originX: 56,
    originY: 52.5,
    halfTileWidth: 6.25,
    halfTileHeight: 3.05
  });

  function gridToScreen(col, row) {
    return {
      x: GEOMETRY.originX + (col - row) * GEOMETRY.halfTileWidth,
      y: GEOMETRY.originY + (col + row) * GEOMETRY.halfTileHeight
    };
  }

  function screenToGrid(x, y) {
    const dx = (x - GEOMETRY.originX) / GEOMETRY.halfTileWidth;
    const dy = (y - GEOMETRY.originY) / GEOMETRY.halfTileHeight;
    return { col: (dx + dy) / 2, row: (dy - dx) / 2 };
  }

  function footprintFor(asset, facing = 0) {
    const [width, height] = asset.footprint || [1, 1];
    return facing === 1 ? { width: height, height: width } : { width, height };
  }

  function clampPlacement(asset, col, row, facing = 0) {
    const footprint = footprintFor(asset, facing);
    return {
      col: Math.max(0, Math.min(GRID - footprint.width, Math.floor(col))),
      row: Math.max(0, Math.min(GRID - footprint.height, Math.floor(row))),
      facing
    };
  }

  function placementAnchor(asset, placement) {
    const footprint = footprintFor(asset, placement.facing || 0);
    return gridToScreen(
      placement.col + footprint.width / 2,
      placement.row + footprint.height / 2
    );
  }

  function cellKey(col, row) {
    return `${col},${row}`;
  }

  function occupiedCells(items, catalog, excludeId = null) {
    const occupied = new Set();
    Object.entries(items).forEach(([id, placement]) => {
      if (id === excludeId) return;
      const asset = catalog.find((entry) => entry.id === id);
      if (!asset || asset.flat) return;
      const footprint = footprintFor(asset, placement.facing || 0);
      for (let dc = 0; dc < footprint.width; dc += 1) {
        for (let dr = 0; dr < footprint.height; dr += 1) {
          occupied.add(cellKey(placement.col + dc, placement.row + dr));
        }
      }
    });
    return occupied;
  }

  function canPlace(asset, placement, occupied) {
    const footprint = footprintFor(asset, placement.facing || 0);
    if (placement.col < 0 || placement.row < 0) return false;
    if (placement.col + footprint.width > GRID || placement.row + footprint.height > GRID) return false;
    if (asset.flat) return true;
    for (let dc = 0; dc < footprint.width; dc += 1) {
      for (let dr = 0; dr < footprint.height; dr += 1) {
        if (occupied.has(cellKey(placement.col + dc, placement.row + dr))) return false;
      }
    }
    return true;
  }

  function depthKey(asset, placement) {
    const footprint = footprintFor(asset, placement.facing || 0);
    return placement.col + footprint.width - 1 + placement.row + footprint.height - 1;
  }

  function clampDog(point, radius = 0.22) {
    return {
      x: Math.max(radius, Math.min(GRID - radius, point.x)),
      y: Math.max(radius, Math.min(GRID - radius, point.y))
    };
  }

  function blockedAt(x, y, blocked, radius = 0.22) {
    if (!blocked.size) return false;
    for (const dx of [-radius, radius]) {
      for (const dy of [-radius, radius]) {
        if (blocked.has(cellKey(Math.floor(x + dx), Math.floor(y + dy)))) return true;
      }
    }
    return false;
  }

  // Try each axis separately so a dog glides around a corner instead of
  // stopping or tunnelling through the obstacle on a diagonal step.
  function slide(from, to, blocked, radius = 0.22) {
    let x = from.x;
    let y = from.y;
    if (!blockedAt(to.x, y, blocked, radius)) x = to.x;
    if (!blockedAt(x, to.y, blocked, radius)) y = to.y;
    return { x, y };
  }

  function nearestFree(from, blocked) {
    let best = { ...from };
    let bestDistance = Number.POSITIVE_INFINITY;
    for (let col = 0; col < GRID; col += 1) {
      for (let row = 0; row < GRID; row += 1) {
        if (blocked.has(cellKey(col, row))) continue;
        const point = { x: col + 0.5, y: row + 0.5 };
        const distance = (point.x - from.x) ** 2 + (point.y - from.y) ** 2;
        if (distance < bestDistance) {
          best = point;
          bestDistance = distance;
        }
      }
    }
    return best;
  }

  function randomFreeSpot(blocked, random = Math.random, radius = 0.22) {
    const low = 0.4;
    const high = GRID - 0.4;
    for (let attempt = 0; attempt < 16; attempt += 1) {
      const point = {
        x: low + random() * (high - low),
        y: low + random() * (high - low)
      };
      if (!blockedAt(point.x, point.y, blocked, radius)) return point;
    }
    return nearestFree({ x: GRID / 2, y: GRID / 2 }, blocked);
  }

  return Object.freeze({
    GRID,
    GEOMETRY,
    gridToScreen,
    screenToGrid,
    footprintFor,
    clampPlacement,
    placementAnchor,
    cellKey,
    occupiedCells,
    canPlace,
    depthKey,
    clampDog,
    blockedAt,
    slide,
    nearestFree,
    randomFreeSpot
  });
});
