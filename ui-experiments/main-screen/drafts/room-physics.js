(function attachRoomPhysics(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.DaengsRoomPhysics = api;
})(typeof globalThis !== "undefined" ? globalThis : window, () => {
  "use strict";

  // Browser port of the grid-footprint and axis-slide approach from
  // https://github.com/gayeoniee/isometric_test
  // (IsoMath, MiniRoomState, DogHerd, and ItemArt's per-asset anchors).
  const GRID = 16;
  const GEOMETRY = Object.freeze({
    stageAspect: 1122 / 1402,
    // The generated v7 room is not a symmetric isometric diamond. These are
    // its four visible floor corners in room-stage percentages.
    back: Object.freeze({ x: 56, y: 52.5 }),
    right: Object.freeze({ x: 96, y: 70.3 }),
    front: Object.freeze({ x: 44, y: 93 }),
    left: Object.freeze({ x: 4, y: 72.5 })
  });

  function gridToScreen(col, row) {
    const u = col / GRID;
    const v = row / GRID;
    const inverseU = 1 - u;
    const inverseV = 1 - v;
    return {
      x: inverseU * inverseV * GEOMETRY.back.x
        + u * inverseV * GEOMETRY.right.x
        + u * v * GEOMETRY.front.x
        + inverseU * v * GEOMETRY.left.x,
      y: inverseU * inverseV * GEOMETRY.back.y
        + u * inverseV * GEOMETRY.right.y
        + u * v * GEOMETRY.front.y
        + inverseU * v * GEOMETRY.left.y
    };
  }

  function screenToGrid(x, y) {
    const horizontal = {
      x: GEOMETRY.right.x - GEOMETRY.back.x,
      y: GEOMETRY.right.y - GEOMETRY.back.y
    };
    const vertical = {
      x: GEOMETRY.left.x - GEOMETRY.back.x,
      y: GEOMETRY.left.y - GEOMETRY.back.y
    };
    const fromBack = { x: x - GEOMETRY.back.x, y: y - GEOMETRY.back.y };
    const determinant = horizontal.x * vertical.y - horizontal.y * vertical.x;
    let u = (fromBack.x * vertical.y - fromBack.y * vertical.x) / determinant;
    let v = (horizontal.x * fromBack.y - horizontal.y * fromBack.x) / determinant;

    // Invert the bilinear quadrilateral. Keeping u/v unclamped is important:
    // drag code needs to know that the pointer has moved beyond an edge.
    for (let iteration = 0; iteration < 8; iteration += 1) {
      const point = gridToScreen(u * GRID, v * GRID);
      const errorX = x - point.x;
      const errorY = y - point.y;
      const derivativeU = {
        x: (1 - v) * (GEOMETRY.right.x - GEOMETRY.back.x)
          + v * (GEOMETRY.front.x - GEOMETRY.left.x),
        y: (1 - v) * (GEOMETRY.right.y - GEOMETRY.back.y)
          + v * (GEOMETRY.front.y - GEOMETRY.left.y)
      };
      const derivativeV = {
        x: (1 - u) * (GEOMETRY.left.x - GEOMETRY.back.x)
          + u * (GEOMETRY.front.x - GEOMETRY.right.x),
        y: (1 - u) * (GEOMETRY.left.y - GEOMETRY.back.y)
          + u * (GEOMETRY.front.y - GEOMETRY.right.y)
      };
      const jacobian = derivativeU.x * derivativeV.y - derivativeU.y * derivativeV.x;
      if (Math.abs(jacobian) < 1e-9) break;
      u += (errorX * derivativeV.y - errorY * derivativeV.x) / jacobian;
      v += (derivativeU.x * errorY - derivativeU.y * errorX) / jacobian;
    }

    return { col: u * GRID, row: v * GRID };
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

  function occupiedCells(items, catalog, excludeId = null, includeFlat = false) {
    const occupied = new Set();
    Object.entries(items).forEach(([id, placement]) => {
      if (id === excludeId) return;
      const asset = catalog.find((entry) => entry.id === id);
      if (!asset || (asset.flat && !includeFlat)) return;
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

  function visualBounds(asset, placement) {
    const anchor = placementAnchor(asset, placement);
    const [anchorX, anchorY] = asset.artAnchor || [50, 50];
    const width = asset.width;
    const height = width * GEOMETRY.stageAspect / asset.aspectRatio;
    return {
      left: anchor.x - width * anchorX / 100,
      right: anchor.x + width * (100 - anchorX) / 100,
      top: anchor.y - height * anchorY / 100,
      bottom: anchor.y + height * (100 - anchorY) / 100
    };
  }

  function boundsOverlap(first, second, gap = 0) {
    return first.left < second.right + gap
      && first.right + gap > second.left
      && first.top < second.bottom + gap
      && first.bottom + gap > second.top;
  }

  function floorHorizontalRange(y) {
    const corners = [GEOMETRY.back, GEOMETRY.right, GEOMETRY.front, GEOMETRY.left];
    const intersections = [];
    for (let index = 0; index < corners.length; index += 1) {
      const first = corners[index];
      const second = corners[(index + 1) % corners.length];
      const low = Math.min(first.y, second.y);
      const high = Math.max(first.y, second.y);
      if (y < low || y > high || first.y === second.y) continue;
      const ratio = (y - first.y) / (second.y - first.y);
      intersections.push(first.x + (second.x - first.x) * ratio);
    }
    if (intersections.length < 2) return null;
    return { left: Math.min(...intersections), right: Math.max(...intersections) };
  }

  function floorBoxFits(asset, placement, gap = 0) {
    const bounds = visualBounds(asset, placement);
    const [leftPercent, topPercent, rightPercent, bottomPercent] = asset.floorBox || [0, 0, 100, 100];
    const box = {
      left: bounds.left + (bounds.right - bounds.left) * leftPercent / 100,
      right: bounds.left + (bounds.right - bounds.left) * rightPercent / 100,
      top: bounds.top + (bounds.bottom - bounds.top) * topPercent / 100,
      bottom: bounds.top + (bounds.bottom - bounds.top) * bottomPercent / 100
    };
    const topRange = floorHorizontalRange(box.top);
    const bottomRange = floorHorizontalRange(box.bottom);
    if (!topRange || !bottomRange) return false;
    return box.left >= Math.max(topRange.left, bottomRange.left) + gap
      && box.right <= Math.min(topRange.right, bottomRange.right) - gap;
  }

  function depthKey(asset, placement) {
    const footprint = footprintFor(asset, placement.facing || 0);
    return placement.col + footprint.width - 1 + placement.row + footprint.height - 1;
  }

  function clampDog(point, radius = 0.58) {
    return {
      x: Math.max(radius, Math.min(GRID - radius, point.x)),
      y: Math.max(radius, Math.min(GRID - radius, point.y))
    };
  }

  function blockedAt(x, y, blocked, radius = 0.58) {
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
  function slide(from, to, blocked, radius = 0.58) {
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

  function randomFreeSpot(blocked, random = Math.random, radius = 0.58) {
    const low = Math.max(1, radius + 0.15);
    const high = GRID - low;
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
    visualBounds,
    boundsOverlap,
    floorHorizontalRange,
    floorBoxFits,
    depthKey,
    clampDog,
    blockedAt,
    slide,
    nearestFree,
    randomFreeSpot
  });
});
