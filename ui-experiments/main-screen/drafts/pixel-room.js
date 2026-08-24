(() => {
  "use strict";

  const canvas = document.querySelector("#pixelRoom");
  const ctx = canvas.getContext("2d", { alpha: false });
  const lightButton = document.querySelector("#lightButton");
  const W = canvas.width;
  const H = canvas.height;
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

  ctx.imageSmoothingEnabled = false;

  const C = {
    ink: "#4a3b2b",
    ink2: "#6c5840",
    cream0: "#fffaf0",
    cream1: "#f7eddc",
    cream2: "#eadbc2",
    cream3: "#d8c6a8",
    wallL: "#eee1ca",
    wallR: "#e7d8bf",
    wallShade: "#d6c4a6",
    floor0: "#d9b683",
    floor1: "#c89c63",
    floor2: "#ae7e48",
    floorLight: "#edca96",
    sage0: "#c7d49d",
    sage1: "#96aa71",
    sage2: "#6f8557",
    sage3: "#4f6443",
    leafLight: "#aabd7c",
    leaf: "#758f59",
    leafDark: "#536b43",
    sky0: "#9ed3e6",
    sky1: "#bce5ee",
    sky2: "#e5f5ef",
    cloud: "#fffdf3",
    wood0: "#b88952",
    wood1: "#97683e",
    wood2: "#704a2e",
    gold0: "#f3d26d",
    gold1: "#d9a93e",
    peach: "#df9b78",
    pink: "#e79a94",
    fur0: "#fff8df",
    fur1: "#efddbb",
    fur2: "#d8bc8c",
    dark: "#30271f",
    night: "#566278",
    nightSky: "#657a96",
    lamp: "#ffe699"
  };

  const state = { lightsOn: false, blink: false, tailFrame: 0, tick: 0 };

  function rect(x, y, w, h, color) {
    ctx.fillStyle = color;
    ctx.fillRect(x | 0, y | 0, w | 0, h | 0);
  }

  function poly(points, color) {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(points[0][0], points[0][1]);
    for (let i = 1; i < points.length; i += 1) ctx.lineTo(points[i][0], points[i][1]);
    ctx.closePath();
    ctx.fill();
  }

  function pxLine(x0, y0, x1, y1, color, size = 1) {
    let x = x0 | 0;
    let y = y0 | 0;
    const tx = x1 | 0;
    const ty = y1 | 0;
    const dx = Math.abs(tx - x);
    const sx = x < tx ? 1 : -1;
    const dy = -Math.abs(ty - y);
    const sy = y < ty ? 1 : -1;
    let err = dx + dy;
    while (true) {
      rect(x, y, size, size, color);
      if (x === tx && y === ty) break;
      const e2 = err * 2;
      if (e2 >= dy) { err += dy; x += sx; }
      if (e2 <= dx) { err += dx; y += sy; }
    }
  }

  function ellipse(cx, cy, rx, ry, color) {
    const left = Math.floor(cx - rx);
    const right = Math.ceil(cx + rx);
    const top = Math.floor(cy - ry);
    const bottom = Math.ceil(cy + ry);
    for (let y = top; y <= bottom; y += 1) {
      const yy = (y - cy) / ry;
      const half = Math.floor(rx * Math.sqrt(Math.max(0, 1 - yy * yy)));
      rect(cx - half, y, half * 2 + 1, 1, color);
    }
  }

  function ringEllipse(cx, cy, rx, ry, thickness, outer, inner) {
    ellipse(cx, cy, rx, ry, outer);
    ellipse(cx, cy, Math.max(1, rx - thickness), Math.max(1, ry - thickness), inner);
  }

  function dither(x, y, w, h, color, step = 4, phase = 0) {
    for (let py = y; py < y + h; py += step) {
      for (let px = x + ((py / step + phase) % 2) * Math.floor(step / 2); px < x + w; px += step) {
        rect(px, py, 1, 1, color);
      }
    }
  }

  const FONT = {
    A: ["01110", "10001", "11111", "10001", "10001"],
    D: ["11110", "10001", "10001", "10001", "11110"],
    E: ["11111", "10000", "11110", "10000", "11111"],
    G: ["01111", "10000", "10111", "10001", "01110"],
    H: ["10001", "10001", "11111", "10001", "10001"],
    M: ["10001", "11011", "10101", "10001", "10001"],
    N: ["10001", "11001", "10101", "10011", "10001"],
    O: ["01110", "10001", "10001", "10001", "01110"],
    R: ["11110", "10001", "11110", "10100", "10010"],
    S: ["01111", "10000", "01110", "00001", "11110"],
    T: ["11111", "00100", "00100", "00100", "00100"],
    Y: ["10001", "01010", "00100", "00100", "00100"],
    "1": ["00100", "01100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00010", "00100", "11111"],
    "0": ["01110", "10011", "10101", "11001", "01110"],
    "·": ["0", "0", "1", "0", "0"],
    " ": ["000", "000", "000", "000", "000"]
  };

  function pixelText(text, x, y, color, scale = 1, spacing = 1) {
    let cursor = x;
    for (const raw of text.toUpperCase()) {
      const glyph = FONT[raw] || FONT[" "];
      for (let gy = 0; gy < glyph.length; gy += 1) {
        for (let gx = 0; gx < glyph[gy].length; gx += 1) {
          if (glyph[gy][gx] === "1") rect(cursor + gx * scale, y + gy * scale, scale, scale, color);
        }
      }
      cursor += (glyph[0].length + spacing) * scale;
    }
  }

  function drawArchitecture() {
    rect(0, 0, W, H, C.cream1);

    // Back walls and their shared corner.
    poly([[8, 50], [181, 17], [181, 236], [8, 282]], C.wallL);
    poly([[181, 17], [352, 55], [352, 282], [181, 236]], C.wallR);
    dither(14, 66, 160, 176, "#e5d6bb", 7, 0);
    dither(190, 64, 154, 177, "#ddceb2", 8, 1);

    // Pixel-stepped crown moulding.
    pxLine(8, 49, 181, 16, C.cream0, 7);
    pxLine(181, 16, 352, 54, C.cream0, 7);
    pxLine(8, 56, 181, 23, C.cream3, 2);
    pxLine(181, 23, 352, 61, C.cream3, 2);
    pxLine(181, 24, 181, 238, C.wallShade, 2);
    rect(178, 25, 2, 210, "#fff4e2");

    // Floor plane.
    poly([[8, 282], [181, 236], [352, 282], [352, 391], [181, 425], [8, 390]], C.floor0);
    for (let x = -10; x < 390; x += 31) {
      pxLine(181, 236, x, 425, C.floor1, 1);
      pxLine(181, 238, x + 2, 425, C.floorLight, 1);
    }
    for (let y = 281; y < 414; y += 20) {
      pxLine(8, y, 181, Math.min(425, y + 44), C.floor2, 1);
      pxLine(352, y, 181, Math.min(425, y + 44), C.floor2, 1);
    }
    dither(28, 305, 300, 88, "#c08f57", 9, 1);

    // Thick room base and clipped front corners.
    pxLine(8, 282, 181, 236, C.cream3, 3);
    pxLine(181, 236, 352, 282, C.cream3, 3);
    poly([[0, 276], [9, 280], [9, 391], [181, 426], [181, 430], [0, 394]], C.cream0);
    poly([[360, 276], [351, 280], [351, 391], [181, 426], [181, 430], [360, 394]], C.cream0);
    pxLine(8, 391, 181, 426, C.cream3, 3);
    pxLine(352, 391, 181, 426, C.cream3, 3);
  }

  function drawWindow() {
    // Deep shadow and a fully stepped arch casing.
    const cx = 152;
    for (let y = 0; y < 36; y += 1) {
      const half = Math.floor(47 * Math.sqrt(Math.max(0, 1 - ((35 - y) / 35) ** 2)));
      rect(cx + 2 - half, 68 + y, half * 2, 1, C.ink2);
    }
    rect(107, 103, 94, 102, C.ink2);
    for (let y = 0; y < 34; y += 1) {
      const half = Math.floor(44 * Math.sqrt(Math.max(0, 1 - ((33 - y) / 33) ** 2)));
      rect(cx - half, 70 + y, half * 2, 1, C.cream0);
    }
    rect(108, 103, 88, 98, C.cream0);

    // Glass arch, also built row-by-row instead of a smooth vector curve.
    const top = 76;
    for (let y = 0; y < 31; y += 1) {
      const half = Math.floor(39 * Math.sqrt(Math.max(0, 1 - ((30 - y) / 30) ** 2)));
      rect(cx - half, top + y, half * 2, 1, state.lightsOn ? C.nightSky : C.sky0);
    }
    rect(113, 106, 78, 88, state.lightsOn ? C.nightSky : C.sky0);

    if (state.lightsOn) {
      rect(172, 88, 2, 2, C.lamp); rect(129, 101, 1, 1, C.cream0); rect(183, 116, 1, 1, C.cream0);
      rect(143, 84, 1, 1, C.cream0); rect(119, 124, 1, 1, C.cream0);
      ellipse(127, 91, 8, 8, C.lamp); ellipse(130, 88, 7, 8, C.nightSky);
    } else {
      rect(117, 116, 25, 6, C.cloud); rect(123, 111, 11, 13, C.cloud);
      rect(162, 94, 25, 6, C.cloud); rect(168, 89, 10, 12, C.cloud);
      rect(146, 136, 33, 7, C.cloud); rect(154, 131, 12, 14, C.cloud);
    }

    // Layered foliage outside.
    const greens = [C.sage2, C.sage3, C.leaf, C.leafLight];
    for (let i = 0; i < 22; i += 1) {
      const x = 116 + ((i * 17) % 72);
      const y = 164 + ((i * 11) % 28);
      ellipse(x, y, 7 + (i % 3), 5 + (i % 4), greens[i % greens.length]);
    }
    rect(149, 77, 6, 120, C.cream0);
    rect(113, 132, 78, 6, C.cream0);
    rect(152, 78, 2, 116, C.cream3);
    rect(114, 134, 76, 2, C.cream3);
    rect(104, 194, 92, 7, C.cream0);
    rect(108, 201, 84, 4, C.cream3);
    rect(111, 80, 3, 113, "#d3c09e");
  }

  function drawCalendar() {
    // Hanging card, shadow, binding rings and curled bottom.
    rect(17, 72, 75, 76, "#bda883");
    rect(14, 68, 75, 76, C.cream0);
    rect(18, 72, 67, 68, C.cream1);
    rect(18, 72, 67, 3, C.gold1);
    rect(24, 65, 8, 9, C.ink2); rect(70, 65, 8, 9, C.ink2);
    rect(25, 64, 6, 8, C.cream3); rect(71, 64, 6, 8, C.cream3);
    pixelText("TODAY", 24, 82, C.sage3, 1, 1);
    pixelText("20·1", 25, 98, C.ink, 2, 1);
    rect(24, 113, 53, 1, C.cream3);
    pixelText("SUNNY", 24, 121, C.ink2, 1, 1);
    // Tiny sun.
    rect(72, 83, 5, 5, C.gold0); rect(73, 80, 2, 2, C.gold1); rect(73, 90, 2, 2, C.gold1);
    rect(68, 85, 2, 2, C.gold1); rect(79, 85, 2, 2, C.gold1);
  }

  function drawDoor() {
    // Left arched door in a thick stone casing.
    rect(24, 159, 66, 117, C.cream0);
    for (let y = 0; y < 28; y += 1) {
      const half = Math.floor(30 * Math.sqrt(Math.max(0, 1 - ((27 - y) / 27) ** 2)));
      rect(57 - half, 144 + y, half * 2, 1, C.cream0);
    }
    rect(29, 159, 56, 112, C.sage3);
    for (let y = 0; y < 25; y += 1) {
      const half = Math.floor(26 * Math.sqrt(Math.max(0, 1 - ((24 - y) / 24) ** 2)));
      rect(57 - half, 149 + y, half * 2, 1, C.sage2);
    }
    rect(34, 169, 46, 97, C.sage2);
    rect(38, 174, 38, 88, "#7f9061");
    // Raised inset panel.
    rect(42, 188, 30, 48, C.sage3);
    rect(45, 185, 27, 48, C.sage1);
    rect(48, 188, 21, 42, C.sage2);
    // Paw relief.
    ellipse(58, 207, 7, 6, C.sage3);
    ellipse(49, 199, 3, 4, C.sage3); ellipse(55, 195, 3, 4, C.sage3);
    ellipse(62, 195, 3, 4, C.sage3); ellipse(68, 200, 3, 4, C.sage3);
    // Hardware and hinges.
    rect(72, 221, 5, 7, C.wood2); rect(73, 220, 5, 6, C.gold0); rect(74, 221, 2, 2, C.cream0);
    rect(30, 184, 3, 11, C.ink2); rect(30, 239, 3, 11, C.ink2);
    // Switch and welcome mat.
    rect(95, 224, 12, 15, C.cream3); rect(97, 222, 12, 15, C.cream0); rect(102, 228, 2, 4, C.ink2);
    poly([[27, 276], [82, 266], [107, 278], [49, 290]], C.wood2);
    poly([[31, 275], [81, 267], [102, 278], [50, 286]], C.wood0);
    pixelText("HOME", 48, 274, C.wood2, 1, 1);
  }

  function drawShelfAndPlants() {
    // Hanging vine from ceiling.
    pxLine(226, 35, 226, 81, C.wood1, 1);
    rect(216, 75, 22, 4, C.wood2); rect(219, 79, 16, 14, C.wood0); rect(221, 91, 12, 3, C.wood2);
    pxLine(219, 77, 226, 67, C.wood1, 1); pxLine(234, 77, 226, 67, C.wood1, 1);
    for (let i = 0; i < 10; i += 1) {
      const x = 214 + ((i * 11) % 25);
      const y = 62 + ((i * 13) % 33);
      ellipse(x, y, 4 + (i % 2), 3 + ((i + 1) % 2), i % 3 === 0 ? C.leafLight : C.leafDark);
    }
    pxLine(229, 91, 241, 126, C.leafDark, 1);
    ellipse(236, 104, 4, 3, C.leaf); ellipse(240, 114, 4, 3, C.leafLight); ellipse(241, 124, 4, 3, C.leafDark);

    // Right wall shelf and supports.
    rect(235, 130, 92, 8, C.wood2); rect(232, 126, 96, 8, C.wood0); rect(236, 126, 88, 3, "#d3ad78");
    poly([[242, 134], [249, 134], [245, 151], [240, 151]], C.wood1);
    poly([[310, 134], [317, 134], [314, 151], [309, 151]], C.wood1);

    // Books, all with one-pixel trim.
    rect(240, 102, 11, 24, C.ink2); rect(241, 100, 10, 26, C.sage1); rect(243, 103, 2, 19, C.cream1);
    rect(252, 106, 12, 20, C.wood2); rect(253, 104, 11, 22, C.gold0); rect(256, 107, 2, 16, C.gold1);
    rect(265, 99, 10, 27, C.ink2); rect(266, 98, 9, 28, C.cream2); rect(268, 102, 1, 19, C.wood1);
    rect(276, 111, 16, 15, C.ink2); rect(276, 109, 17, 15, C.sky1); rect(280, 112, 9, 2, C.cream0);

    // Small shelf plant.
    rect(297, 114, 14, 12, C.cream0); rect(299, 125, 10, 2, C.cream3);
    pxLine(304, 115, 304, 101, C.leafDark, 1);
    ellipse(299, 105, 7, 3, C.leaf); ellipse(309, 103, 7, 3, C.leafLight); ellipse(304, 98, 4, 7, C.leafDark);

    // Cloud light at the end of shelf.
    rect(314, 116, 20, 10, state.lightsOn ? C.lamp : C.cream0);
    ellipse(319, 116, 8, 8, state.lightsOn ? C.lamp : C.cream0);
    ellipse(327, 114, 7, 10, state.lightsOn ? "#fff0ad" : C.cream0);
    if (state.lightsOn) dither(310, 105, 26, 20, "#fff8d2", 3, state.tick % 2);
  }

  function drawCabinet() {
    rect(225, 201, 73, 55, C.ink2);
    rect(221, 196, 75, 56, C.cream0);
    rect(225, 202, 67, 46, C.cream2);
    rect(225, 202, 33, 46, C.sage2);
    rect(228, 205, 27, 18, C.sage1); rect(228, 226, 27, 18, C.sage1);
    rect(260, 205, 29, 18, C.cream1); rect(260, 226, 29, 18, C.cream1);
    rect(257, 202, 3, 46, C.cream3); rect(225, 223, 67, 3, C.cream3);
    for (const [x, y] of [[242, 214], [242, 235], [274, 214], [274, 235]]) {
      rect(x, y, 4, 4, C.wood2); rect(x + 1, y, 2, 2, C.gold0);
    }
    rect(228, 248, 5, 8, C.wood1); rect(284, 248, 5, 8, C.wood1);

    // Plant pot and framed portrait on cabinet.
    rect(228, 185, 19, 12, C.wood2); rect(230, 183, 17, 13, C.gold1); rect(234, 185, 4, 3, C.wood1);
    pxLine(238, 184, 238, 170, C.leafDark, 1);
    ellipse(231, 174, 7, 4, C.leaf); ellipse(245, 173, 7, 4, C.leafLight); ellipse(238, 166, 4, 8, C.leafDark);
    rect(252, 174, 22, 23, C.wood2); rect(254, 172, 21, 24, C.gold0); rect(258, 176, 13, 16, C.cream1);
    ellipse(264, 184, 4, 4, C.sage2); rect(260, 187, 8, 4, C.sage2);

    // Table lamp with pixel shade.
    rect(279, 184, 17, 4, C.cream3); rect(285, 169, 5, 17, C.wood1);
    rect(277, 167, 21, 4, C.cream3);
    rect(280, 158, 15, 3, state.lightsOn ? C.lamp : C.cream0);
    rect(277, 161, 21, 7, state.lightsOn ? C.lamp : C.cream0);
    rect(274, 167, 27, 3, state.lightsOn ? "#efd16b" : C.cream3);
  }

  function drawDogHouse() {
    // Cast shadow.
    ellipse(300, 302, 46, 14, "#9a744a");
    // Kennel body with rounded pixel roof.
    rect(272, 246, 63, 58, C.sage3);
    rect(268, 251, 71, 47, C.sage2);
    rect(272, 243, 61, 5, C.sage1);
    rect(277, 239, 51, 5, C.sage1);
    rect(283, 236, 39, 4, C.sage0);
    rect(268, 259, 4, 32, C.sage1); rect(335, 259, 4, 32, C.sage3);
    // Entry arch.
    ellipse(303, 274, 23, 27, C.ink2);
    rect(280, 273, 47, 29, C.ink2);
    ellipse(303, 277, 18, 22, "#2f3828");
    rect(285, 276, 37, 27, "#2f3828");
    // Cushion and checker pattern.
    ellipse(303, 293, 20, 8, C.cream3);
    rect(285, 290, 37, 9, C.cream2);
    for (let y = 290; y < 299; y += 4) {
      for (let x = 286; x < 321; x += 8) rect(x + ((y / 4) % 2) * 4, y, 4, 4, C.sage1);
    }
    rect(285, 299, 37, 3, C.sage3);
    // Bone name tag.
    pxLine(330, 261, 338, 247, C.wood1, 1);
    rect(330, 254, 18, 9, C.cream1);
    ellipse(330, 258, 4, 4, C.cream1); ellipse(348, 258, 4, 4, C.cream1);
    rect(336, 257, 6, 2, C.ink2);
  }

  function drawFloorPlant() {
    // Pot behind leaves.
    ellipse(330, 306, 17, 6, C.ink2);
    poly([[315, 300], [345, 300], [341, 326], [320, 326]], C.cream2);
    rect(320, 321, 21, 6, C.cream3);
    dither(319, 304, 23, 18, C.wood0, 4, 0);
    // Leaves have highlight and center vein pixels.
    const leaves = [
      [330, 297, 330, 250, 9], [329, 294, 310, 259, 8], [331, 294, 348, 257, 8],
      [327, 300, 305, 279, 7], [333, 300, 353, 280, 7], [330, 301, 319, 270, 7]
    ];
    for (let i = 0; i < leaves.length; i += 1) {
      const [x0, y0, x1, y1, width] = leaves[i];
      pxLine(x0, y0, x1, y1, C.leafDark, width);
      pxLine(x0, y0, x1, y1, i % 2 ? C.leaf : C.leafLight, Math.max(2, width - 4));
      pxLine(x0, y0, x1, y1, "#d3dc9d", 1);
    }
  }

  function drawRug() {
    ellipse(163, 329, 83, 46, "#98734f");
    ellipse(163, 325, 83, 45, C.cream0);
    ellipse(163, 325, 76, 38, C.cream2);
    ellipse(163, 325, 70, 33, C.cream0);
    // Pixel scallops and woven floral motifs.
    for (let i = 0; i < 28; i += 1) {
      const a = (i / 28) * Math.PI * 2;
      const x = Math.round(163 + Math.cos(a) * 72);
      const y = Math.round(325 + Math.sin(a) * 35);
      rect(x, y, 2, 2, i % 2 ? C.cream3 : C.gold0);
    }
    for (let y = 300; y < 348; y += 6) {
      for (let x = 108 + ((y / 6) % 2) * 3; x < 218; x += 8) {
        const nx = (x - 163) / 68;
        const ny = (y - 325) / 31;
        if (nx * nx + ny * ny < .86) rect(x, y, 1, 1, C.cream3);
      }
    }
    // Center paw medallion.
    ellipse(164, 330, 8, 6, C.cream2);
    ellipse(154, 322, 3, 4, C.cream2); ellipse(161, 318, 3, 4, C.cream2);
    ellipse(168, 318, 3, 4, C.cream2); ellipse(175, 323, 3, 4, C.cream2);
  }

  function drawDog() {
    // Warm shadow under dog.
    ellipse(148, 331, 32, 8, "#d3b884");
    const ox = 114;
    const oy = 256;

    // Tail, discrete two-frame wag.
    if (state.tailFrame === 0) {
      rect(58 + ox, 43 + oy, 18, 7, C.ink); rect(61 + ox, 39 + oy, 17, 8, C.fur2);
      rect(72 + ox, 35 + oy, 8, 9, C.fur1);
    } else {
      rect(61 + ox, 39 + oy, 17, 7, C.ink); rect(65 + ox, 35 + oy, 16, 8, C.fur2);
      rect(76 + ox, 31 + oy, 8, 9, C.fur1);
    }

    // Body and back legs.
    ellipse(34 + ox, 51 + oy, 25, 22, C.ink);
    ellipse(34 + ox, 48 + oy, 23, 21, C.fur1);
    rect(18 + ox, 55 + oy, 12, 24, C.ink); rect(20 + ox, 54 + oy, 10, 23, C.fur1);
    rect(43 + ox, 54 + oy, 13, 24, C.ink); rect(44 + ox, 53 + oy, 10, 23, C.fur0);
    rect(18 + ox, 75 + oy, 14, 5, C.ink); rect(44 + ox, 75 + oy, 14, 5, C.ink);
    rect(20 + ox, 74 + oy, 11, 4, C.fur0); rect(45 + ox, 74 + oy, 12, 4, C.fur0);

    // Ears behind head.
    ellipse(15 + ox, 23 + oy, 12, 17, C.ink);
    ellipse(16 + ox, 23 + oy, 10, 15, C.fur2);
    rect(7 + ox, 24 + oy, 8, 14, C.fur2);
    ellipse(50 + ox, 23 + oy, 12, 17, C.ink);
    ellipse(49 + ox, 23 + oy, 10, 15, C.fur2);
    rect(50 + ox, 24 + oy, 8, 14, C.fur2);

    // Curly head silhouette with small clusters.
    ellipse(33 + ox, 25 + oy, 25, 24, C.ink);
    ellipse(33 + ox, 24 + oy, 23, 22, C.fur0);
    const curls = [[15, 14], [23, 7], [33, 5], [43, 8], [51, 15], [12, 25], [54, 27], [18, 37], [47, 39]];
    for (let i = 0; i < curls.length; i += 1) {
      const [x, y] = curls[i];
      ellipse(x + ox, y + oy, 7, 6, C.fur2);
      ellipse(x + ox, y - 1 + oy, 5, 4, i % 3 === 0 ? C.fur0 : C.fur1);
      rect(x - 2 + ox, y - 3 + oy, 2, 2, C.cream0);
    }

    // Face patch and muzzle.
    ellipse(34 + ox, 29 + oy, 15, 13, C.fur0);
    ellipse(34 + ox, 36 + oy, 11, 8, C.fur1);
    if (state.blink) {
      rect(24 + ox, 27 + oy, 6, 2, C.dark); rect(39 + ox, 27 + oy, 6, 2, C.dark);
    } else {
      rect(25 + ox, 25 + oy, 5, 6, C.dark); rect(40 + ox, 25 + oy, 5, 6, C.dark);
      rect(26 + ox, 25 + oy, 2, 2, C.cream0); rect(41 + ox, 25 + oy, 2, 2, C.cream0);
    }
    rect(31 + ox, 33 + oy, 7, 5, C.dark); rect(33 + ox, 32 + oy, 3, 2, "#745a42");
    rect(33 + ox, 38 + oy, 2, 5, C.dark);
    rect(35 + ox, 42 + oy, 6, 3, C.pink); rect(36 + ox, 44 + oy, 4, 2, C.peach);
    rect(17 + ox, 31 + oy, 5, 3, C.pink); rect(47 + ox, 31 + oy, 5, 3, C.pink);

    // Collar and gold tag.
    rect(21 + ox, 43 + oy, 26, 5, C.sage3); rect(24 + ox, 43 + oy, 20, 2, C.sage0);
    rect(31 + ox, 47 + oy, 7, 7, C.gold1); rect(33 + ox, 49 + oy, 3, 3, C.gold0);

    // Fur highlights keep the dog from reading as one big block.
    rect(23 + ox, 59 + oy, 3, 3, C.cream0); rect(39 + ox, 53 + oy, 3, 3, C.cream0);
    rect(29 + ox, 66 + oy, 2, 4, C.fur2); rect(49 + ox, 63 + oy, 2, 5, C.fur2);
  }

  function drawBallAndSmallProps() {
    // Ball on the rug with directional highlight.
    ellipse(218, 344, 15, 14, C.sage3);
    ellipse(217, 342, 13, 13, C.sage1);
    rect(210, 334, 5, 4, C.sage0); rect(226, 348, 3, 3, C.sage2);
    rect(217, 329, 3, 2, C.cream0);

    // Flower pot beside the door.
    rect(88, 251, 18, 19, C.cream3); rect(91, 253, 13, 17, C.cream0); rect(89, 268, 17, 3, C.wood0);
    pxLine(97, 253, 97, 239, C.leafDark, 1);
    const flowers = [[90, 242], [96, 238], [102, 242], [94, 247], [105, 248]];
    for (const [x, y] of flowers) {
      rect(x - 2, y, 5, 2, C.cream0); rect(x, y - 2, 2, 5, C.cream0); rect(x, y, 1, 1, C.gold1);
    }

    // Foreground flower box and low fence from the reference composition.
    poly([[12, 365], [91, 381], [91, 399], [12, 382]], C.wood2);
    poly([[15, 360], [89, 375], [89, 393], [15, 379]], C.sage3);
    for (let i = 0; i < 12; i += 1) {
      const x = 20 + i * 6;
      const y = 365 + ((i * 7) % 10);
      ellipse(x, y, 5, 3, i % 2 ? C.leaf : C.leafLight);
      if (i % 3 === 0) { rect(x - 2, y - 4, 5, 2, C.cream0); rect(x, y - 6, 2, 5, C.cream0); rect(x, y - 4, 1, 1, C.gold1); }
    }

    // Pixel fence on right foreground.
    pxLine(238, 390, 348, 367, C.wood2, 5);
    pxLine(239, 383, 348, 360, C.wood0, 5);
    for (const x of [242, 279, 315, 347]) {
      rect(x, 361 - Math.floor((x - 238) * .21), 8, 32, C.wood2);
      rect(x + 1, 357 - Math.floor((x - 238) * .21), 6, 30, C.wood0);
      rect(x + 2, 354 - Math.floor((x - 238) * .21), 4, 4, C.gold1);
    }
  }

  function drawAmbientLight() {
    if (!state.lightsOn) return;
    // Ordered dither conveys glow without any smooth gradient.
    for (let y = 139; y < 238; y += 4) {
      for (let x = 252; x < 326; x += 4) {
        const dx = (x - 288) / 42;
        const dy = (y - 174) / 58;
        if (dx * dx + dy * dy < 1 && ((x + y) / 4) % 3 === 0) rect(x, y, 2, 2, "#f6d98a");
      }
    }
  }

  function draw() {
    drawArchitecture();
    drawWindow();
    drawCalendar();
    drawDoor();
    drawShelfAndPlants();
    drawAmbientLight();
    drawCabinet();
    drawRug();
    drawDogHouse();
    drawFloorPlant();
    drawDog();
    drawBallAndSmallProps();
  }

  lightButton.addEventListener("click", () => {
    state.lightsOn = !state.lightsOn;
    lightButton.setAttribute("aria-pressed", String(state.lightsOn));
    draw();
  });

  draw();

  if (!reducedMotion) {
    setInterval(() => {
      state.tick += 1;
      state.tailFrame = state.tick % 2;
      draw();
    }, 520);

    setInterval(() => {
      state.blink = true;
      draw();
      setTimeout(() => {
        state.blink = false;
        draw();
      }, 130);
    }, 3400);
  }
})();
