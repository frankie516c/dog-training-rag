(() => {
  "use strict";

  const physics = window.DaengsRoomPhysics;
  if (!physics) throw new Error("DaengsRoomPhysics must load before modular-room.js");
  const dogPresets = window.DaengsDogPresets;
  if (!dogPresets) throw new Error("DaengsDogPresets must load before modular-room.js");
  const roomThemes = window.DaengsRoomThemes;
  if (!roomThemes) throw new Error("DaengsRoomThemes must load before modular-room.js");

  const STORAGE_KEY = "daengs.modular-room.v4";

  const DOG_CATALOG = dogPresets.catalog;
  const THEME_CATALOG = roomThemes.catalog;

  const CATALOG = [
    {
      id: "rug-cream",
      category: "rug",
      label: "크림 러그",
      src: "../assets/modular-rug-v1-final.png",
      themeFile: "rug-cream.png",
      width: 39,
      aspectRatio: 1155 / 620,
      artAnchor: [50, 50],
      floorBox: [6, 10, 94, 90],
      footprint: [7, 7],
      flat: true,
      defaultPlacement: { col: 5, row: 6, facing: 0 }
    },
    {
      id: "plant-tall",
      category: "plant",
      label: "큰 화분",
      src: "../assets/modular-plant-v1-final.png",
      themeFile: "plant.png",
      width: 9,
      aspectRatio: 667 / 1075,
      artAnchor: [50, 93],
      floorBox: [45, 92, 50, 99],
      footprint: [1, 2],
      flat: false,
      defaultPlacement: { col: 15, row: 0, facing: 0 }
    },
    {
      id: "doghouse-sage",
      category: "doghouse",
      label: "강아지 집",
      src: "../assets/modular-doghouse-v1-final.png",
      themeFile: "doghouse.png",
      width: 19.5,
      aspectRatio: 927 / 952,
      artAnchor: [50, 78],
      floorBox: [42, 90, 50, 98],
      footprint: [3, 4],
      flat: false,
      defaultPlacement: { col: 13, row: 3, facing: 0 }
    },
    {
      id: "ball-sage",
      category: "toy",
      label: "공",
      src: "../assets/modular-ball-v1-final.png",
      themeFile: "ball.png",
      width: 4.8,
      aspectRatio: 504 / 519,
      artAnchor: [50, 94],
      floorBox: [22, 72, 78, 98],
      footprint: [1, 1],
      flat: false,
      defaultPlacement: { col: 15, row: 12, facing: 0 }
    },
    {
      id: "cabinet-sage",
      category: "cabinet",
      label: "수납장",
      src: "../assets/modular-cabinet-v1-final.png",
      themeFile: "cabinet.png",
      width: 22,
      aspectRatio: 890 / 874,
      artAnchor: [50, 77],
      floorBox: [45, 90, 55, 98],
      footprint: [5, 2],
      flat: false,
      defaultPlacement: { col: 0, row: 0, facing: 0 }
    },
    {
      id: "toy-basket",
      category: "basket",
      label: "장난감 바구니",
      src: "../assets/modular-toy-basket-v1-final.png",
      themeFile: "basket.png",
      width: 9,
      aspectRatio: 774 / 667,
      artAnchor: [50, 78],
      floorBox: [7, 25, 93, 96],
      footprint: [2, 2],
      flat: false,
      defaultPlacement: { col: 3, row: 13, facing: 0 }
    },
    {
      id: "feeding-bowls",
      category: "feeding",
      label: "밥그릇 세트",
      src: "../assets/modular-feeding-bowls-v1-final.png",
      themeFile: "bowls.png",
      width: 9,
      aspectRatio: 873 / 446,
      artAnchor: [50, 58],
      floorBox: [5, 12, 95, 92],
      footprint: [2, 1],
      flat: false,
      defaultPlacement: { col: 11, row: 14, facing: 0 }
    },
    {
      id: "rug-sage",
      category: "rug",
      label: "패턴 러그",
      src: "../assets/modular-rug-sage-v1-final.png",
      themeFile: "rug.png",
      width: 39,
      aspectRatio: 1156 / 622,
      artAnchor: [50, 50],
      floorBox: [6, 10, 94, 90],
      footprint: [7, 7],
      flat: true,
      defaultPlacement: { col: 5, row: 6, facing: 0 }
    }
  ];

  const roomStage = document.querySelector("#roomStage");
  const roomBackground = document.querySelector("#roomBackground");
  const roomItems = document.querySelector("#roomItems");
  const inventoryList = document.querySelector("#inventoryList");
  const completeTask = document.querySelector("#completeTask");
  const resetRoom = document.querySelector("#resetRoom");
  const progressLabel = document.querySelector("#progressLabel");
  const roomHint = document.querySelector("#roomHint");
  const toast = document.querySelector("#toast");
  const developerToggle = document.querySelector("#developerToggle");
  const developerFloorOverlay = document.querySelector("#developerFloorOverlay");
  const developerPanel = document.querySelector("#developerPanel");
  const developerThemeGallery = document.querySelector("#developerThemeGallery");
  const dogWalker = document.querySelector("#dogWalker");
  const dogFacing = dogWalker.querySelector(".dog-facing");
  const dogSprite = document.querySelector("#dogSprite");
  const breedPicker = document.querySelector("#breedPicker");
  const themePicker = document.querySelector("#themePicker");

  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  let state = location.hash === "#full" ? fullPreviewState() : loadState();
  const requestedDogId = new URLSearchParams(location.search).get("dog");
  if (DOG_CATALOG.some((entry) => entry.id === requestedDogId)) state.dogId = requestedDogId;
  const requestedThemeId = new URLSearchParams(location.search).get("theme");
  if (THEME_CATALOG.some((entry) => entry.id === requestedThemeId)) state.themeId = requestedThemeId;
  let selectedId = null;
  let toastTimer;
  let lastFrameTime = 0;
  let developerMode = false;

  const DEBUG_COLORS = [
    "#e64b35",
    "#4d8fd6",
    "#7f54c7",
    "#d0921f",
    "#2f9d74",
    "#cc5a9b",
    "#608d2d",
    "#c26735"
  ];

  const dog = {
    definition: getDogDefinition(state.dogId),
    pos: { x: 4, y: 9 },
    target: null,
    restUntil: 0,
    moving: false,
    mirrored: false,
    phase: 1
  };

  function initialState() {
    return { progress: 0, items: {}, dogId: DOG_CATALOG[0].id, themeId: THEME_CATALOG[0].id };
  }

  function fullPreviewState() {
    const items = {};
    CATALOG.forEach((asset) => {
      if (asset.category === "rug" && asset.id !== "rug-sage") return;
      items[asset.id] = { ...asset.defaultPlacement };
    });
    return { progress: CATALOG.length, items, dogId: DOG_CATALOG[0].id, themeId: THEME_CATALOG[0].id };
  }

  function loadState() {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY));
      if (!parsed || typeof parsed.progress !== "number" || typeof parsed.items !== "object") return initialState();
      parsed.progress = Math.max(0, Math.min(CATALOG.length, parsed.progress));
      parsed.dogId = DOG_CATALOG.some((entry) => entry.id === parsed.dogId) ? parsed.dogId : DOG_CATALOG[0].id;
      parsed.themeId = THEME_CATALOG.some((entry) => entry.id === parsed.themeId) ? parsed.themeId : THEME_CATALOG[0].id;
      return parsed;
    } catch {
      return initialState();
    }
  }

  function saveState() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }

  function getAsset(id) {
    return CATALOG.find((asset) => asset.id === id);
  }

  function getDogDefinition(id) {
    return dogPresets.get(id);
  }

  function themedAssetSource(asset) {
    return asset.themeFile ? `../assets/themes/${state.themeId}/${asset.themeFile}` : asset.src;
  }

  function applyTheme(id, persist = true) {
    const theme = roomThemes.get(id);
    state.themeId = theme.id;
    roomStage.dataset.theme = theme.id;
    document.body.dataset.theme = theme.id;
    roomBackground.src = `../assets/themes/${theme.id}/room.png`;
    themePicker.value = theme.id;
    if (persist) saveState();
  }

  function applyDogDefinition(id, persist = true) {
    state.dogId = getDogDefinition(id).id;
    dog.definition = getDogDefinition(state.dogId);
    dog.target = null;
    dogSprite.style.backgroundImage = `url("${dog.definition.sheet}")`;
    dogSprite.style.backgroundSize = `${dog.definition.frameCount * 100}% 100%`;
    dogWalker.setAttribute("aria-label", `${dog.definition.labelKo} 강아지와 놀기`);
    dogSprite.setAttribute("aria-label", dog.definition.labelKo);
    breedPicker.value = dog.definition.id;
    if (persist) saveState();
  }

  function svgElement(tag, attributes = {}) {
    const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attributes).forEach(([name, value]) => element.setAttribute(name, String(value)));
    return element;
  }

  function svgPoints(points) {
    return points.map((point) => `${point.x},${point.y}`).join(" ");
  }

  function drawDeveloperGrid(fragment) {
    const edge = svgElement("polygon", {
      class: "dev-grid-edge",
      points: svgPoints([
        physics.GEOMETRY.back,
        physics.GEOMETRY.right,
        physics.GEOMETRY.front,
        physics.GEOMETRY.left
      ])
    });
    fragment.append(
      edge,
      svgElement("polygon", {
        class: "dev-image-floor",
        points: svgPoints(physics.GEOMETRY.actualFloor)
      })
    );

    for (let index = 0; index <= physics.GRID; index += 1) {
      const colStart = physics.gridToScreen(index, 0);
      const colEnd = physics.gridToScreen(index, physics.GRID);
      const rowStart = physics.gridToScreen(0, index);
      const rowEnd = physics.gridToScreen(physics.GRID, index);
      fragment.append(
        svgElement("line", { class: `dev-grid-line${index % 4 === 0 ? " is-major" : ""}`, x1: colStart.x, y1: colStart.y, x2: colEnd.x, y2: colEnd.y }),
        svgElement("line", { class: `dev-grid-line${index % 4 === 0 ? " is-major" : ""}`, x1: rowStart.x, y1: rowStart.y, x2: rowEnd.x, y2: rowEnd.y })
      );

      if (index % 2 === 0) {
        const colLabel = svgElement("text", { class: "dev-axis-label", x: colStart.x + 0.25, y: colStart.y - 0.55 });
        colLabel.textContent = `c${index}`;
        const rowLabel = svgElement("text", { class: "dev-axis-label", x: rowStart.x - 2.7, y: rowStart.y + 0.3 });
        rowLabel.textContent = `r${index}`;
        fragment.append(colLabel, rowLabel);
      }
    }
  }

  function drawDeveloperItem(fragment, asset, placement, color, invalid = false) {
    const footprint = physics.footprintFor(asset, placement.facing || 0);
    const drawColor = invalid ? "#ff2d20" : color;
    for (let dCol = 0; dCol < footprint.width; dCol += 1) {
      for (let dRow = 0; dRow < footprint.height; dRow += 1) {
        const col = placement.col + dCol;
        const row = placement.row + dRow;
        fragment.append(svgElement("polygon", {
          class: "dev-footprint",
          points: svgPoints([
            physics.gridToScreen(col, row),
            physics.gridToScreen(col + 1, row),
            physics.gridToScreen(col + 1, row + 1),
            physics.gridToScreen(col, row + 1)
          ]),
          fill: drawColor,
          "fill-opacity": invalid ? 0.42 : asset.flat ? 0.2 : 0.28,
          stroke: drawColor
        }));
      }
    }

    const visual = physics.visualBounds(asset, placement);
    fragment.append(svgElement("rect", {
      class: "dev-visual-box",
      x: visual.left,
      y: visual.top,
      width: visual.right - visual.left,
      height: visual.bottom - visual.top,
      stroke: drawColor
    }));

    const floorBox = physics.floorBoxBounds(asset, placement);
    fragment.append(svgElement("rect", {
      class: "dev-floor-box",
      x: floorBox.left,
      y: floorBox.top,
      width: floorBox.right - floorBox.left,
      height: floorBox.bottom - floorBox.top
    }));

    const anchor = physics.placementAnchor(asset, placement);
    fragment.append(svgElement("circle", {
      class: "dev-anchor",
      cx: anchor.x,
      cy: anchor.y,
      r: 0.52,
      stroke: drawColor
    }));
    const label = svgElement("text", {
      class: "dev-item-label",
      x: anchor.x,
      y: anchor.y - 1.25
    });
    label.textContent = `${invalid ? "× " : ""}${asset.label} [${placement.col},${placement.row}] ${footprint.width}×${footprint.height}`;
    fragment.append(label);
  }

  function renderDeveloperPanel(entries, preview) {
    developerPanel.replaceChildren();
    const title = document.createElement("strong");
    title.textContent = `실제 배치 좌표 · ${physics.GRID}×${physics.GRID}`;
    const legend = document.createElement("span");
    legend.textContent = "노랑=실제 PNG 바닥 / 청록=논리 격자 / 채움=점유 셀";
    developerPanel.append(title, legend);

    entries.forEach(([id, placement], index) => {
      const asset = getAsset(id);
      if (!asset) return;
      const footprint = physics.footprintFor(asset, placement.facing || 0);
      const bounds = physics.visualBounds(asset, placement);
      const invalid = preview?.id === id && preview.valid === false;
      const row = document.createElement("div");
      row.className = "developer-row";
      row.style.setProperty("--debug-color", invalid ? "#ff2d20" : DEBUG_COLORS[index % DEBUG_COLORS.length]);
      const swatch = document.createElement("i");
      const content = document.createElement("div");
      const name = document.createElement("b");
      name.textContent = `${asset.label}${invalid ? " · INVALID" : ""}`;
      const grid = document.createElement("code");
      grid.textContent = `col ${placement.col}, row ${placement.row} · ${footprint.width}×${footprint.height} cells`;
      const visual = document.createElement("code");
      visual.textContent = `PNG L${bounds.left.toFixed(1)} T${bounds.top.toFixed(1)} R${bounds.right.toFixed(1)} B${bounds.bottom.toFixed(1)}`;
      const blocking = document.createElement("code");
      blocking.textContent = asset.flat ? "가구 배치 차단 · 강아지 통과" : "가구 배치 + 강아지 이동 차단";
      content.append(name, grid, visual, blocking);
      row.append(swatch, content);
      developerPanel.append(row);
    });
  }

  function syncDeveloperThemeGallerySelection() {
    developerThemeGallery.querySelectorAll(".developer-theme-card").forEach((card) => {
      const selected = card.dataset.themeId === state.themeId;
      card.classList.toggle("is-active", selected);
      card.setAttribute("aria-pressed", String(selected));
    });
  }

  function renderDeveloperThemeGallery() {
    developerThemeGallery.replaceChildren();

    const header = document.createElement("div");
    header.className = "developer-theme-gallery-header";
    const title = document.createElement("strong");
    title.textContent = "PASTEL THEME ASSETS";
    const help = document.createElement("span");
    help.textContent = "ROOM + CABINET / CLICK TO APPLY";
    header.append(title, help);

    const grid = document.createElement("div");
    grid.className = "developer-theme-grid";
    THEME_CATALOG.forEach((theme) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "developer-theme-card";
      card.dataset.themeId = theme.id;
      card.setAttribute("aria-label", `Apply ${theme.label} room theme`);

      const label = document.createElement("span");
      label.className = "developer-theme-label";
      const swatch = document.createElement("i");
      swatch.style.setProperty("--theme-swatch", theme.swatch);
      const name = document.createElement("b");
      name.textContent = theme.label;
      label.append(swatch, name);

      const preview = document.createElement("span");
      preview.className = "developer-theme-preview";
      const room = document.createElement("img");
      room.className = "developer-theme-room";
      room.src = `../assets/themes/${theme.id}/room.png`;
      room.alt = "";
      room.loading = "lazy";
      const cabinet = document.createElement("img");
      cabinet.className = "developer-theme-cabinet";
      cabinet.src = `../assets/themes/${theme.id}/cabinet.png`;
      cabinet.alt = "";
      cabinet.loading = "lazy";
      preview.append(room, cabinet);
      card.append(label, preview);
      card.addEventListener("click", () => {
        applyTheme(theme.id);
        render();
        syncDeveloperThemeGallerySelection();
        showToast(`${theme.label} theme`);
      });
      grid.append(card);
    });

    developerThemeGallery.append(header, grid);
    syncDeveloperThemeGallerySelection();
  }

  function renderDeveloperOverlay(preview = null) {
    if (!developerMode) return;
    const entries = Object.entries(state.items).map(([id, placement]) => [
      id,
      preview?.id === id ? preview.placement : placement
    ]);
    const fragment = document.createDocumentFragment();
    drawDeveloperGrid(fragment);
    entries.forEach(([id, placement], index) => {
      const asset = getAsset(id);
      if (!asset) return;
      drawDeveloperItem(
        fragment,
        asset,
        placement,
        DEBUG_COLORS[index % DEBUG_COLORS.length],
        preview?.id === id && preview.valid === false
      );
    });
    developerFloorOverlay.replaceChildren(fragment);
    renderDeveloperPanel(entries, preview);
  }

  function setDeveloperMode(enabled) {
    developerMode = enabled;
    roomStage.classList.toggle("is-developer", enabled);
    developerToggle.setAttribute("aria-pressed", String(enabled));
    developerToggle.querySelector("b").textContent = enabled ? "ON" : "OFF";
    if (enabled) {
      renderDeveloperOverlay();
      renderDeveloperThemeGallery();
      showToast("개발자 모드: 실제 점유 좌표를 표시합니다.");
    } else {
      developerFloorOverlay.replaceChildren();
      developerPanel.replaceChildren();
      developerThemeGallery.replaceChildren();
    }
  }

  function showToast(message) {
    clearTimeout(toastTimer);
    toast.textContent = message;
    toast.classList.add("is-visible");
    toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 1500);
  }

  function currentOccupied(excludeId = null) {
    return physics.occupiedCells(state.items, CATALOG, excludeId, true);
  }

  function currentBlocked() {
    return physics.occupiedCells(state.items, CATALOG);
  }

  function placementIsValid(asset, placement, excludeId = null) {
    if (!physics.canPlace(asset, placement, currentOccupied(excludeId))) return false;
    const candidateBounds = physics.visualBounds(asset, placement);
    return Object.entries(state.items).every(([id, existingPlacement]) => {
      if (id === excludeId) return true;
      const existingAsset = getAsset(id);
      if (!existingAsset) return true;
      const existingBounds = physics.visualBounds(existingAsset, existingPlacement);
      return !physics.boundsOverlap(candidateBounds, existingBounds, 0.35);
    });
  }

  function firstFreePlacement(asset) {
    const midpoint = (physics.GRID - 1) / 2;
    const footprint = physics.footprintFor(asset, 0);
    const candidates = [];
    for (let col = 0; col <= physics.GRID - footprint.width; col += 1) {
      for (let row = 0; row <= physics.GRID - footprint.height; row += 1) {
        candidates.push({ col, row, facing: 0 });
      }
    }
    candidates.sort((a, b) => {
      const da = (a.col - midpoint) ** 2 + (a.row - midpoint) ** 2;
      const db = (b.col - midpoint) ** 2 + (b.row - midpoint) ** 2;
      return da - db || a.col + a.row - b.col - b.row;
    });
    return candidates.find((placement) => placementIsValid(asset, placement)) || null;
  }

  function validDefaultOrFree(asset) {
    const placement = physics.clampPlacement(asset, asset.defaultPlacement.col, asset.defaultPlacement.row, asset.defaultPlacement.facing);
    return placementIsValid(asset, placement) ? placement : firstFreePlacement(asset);
  }

  function addOrReplaceAsset(asset) {
    const existingCategoryEntry = Object.entries(state.items).find(([id]) => getAsset(id)?.category === asset.category);
    let placement = null;

    if (existingCategoryEntry) {
      const [existingId, existingPlacement] = existingCategoryEntry;
      if (existingId === asset.id) {
        delete state.items[existingId];
        selectedId = null;
        saveState();
        render();
        showToast(`${asset.label}을(를) 보관함에 넣었어요.`);
        return;
      }
      placement = { ...existingPlacement };
      delete state.items[existingId];
      placement = physics.clampPlacement(asset, placement.col, placement.row, placement.facing || 0);
      if (!placementIsValid(asset, placement)) placement = firstFreePlacement(asset);
      showToast(`${asset.label}(으)로 교체되었어요.`);
    } else {
      placement = validDefaultOrFree(asset);
      showToast(`${asset.label}을(를) 방에 놓았어요.`);
    }

    if (!placement) {
      showToast("놓을 수 있는 빈자리가 없어요.");
      return;
    }
    state.items[asset.id] = placement;
    selectedId = asset.id;
    saveState();
    render();
  }

  function itemDepth(asset, placement) {
    return asset.flat ? 40 : 100 + physics.depthKey(asset, placement) * 50;
  }

  function positionElement(element, asset, placement) {
    const anchor = physics.placementAnchor(asset, placement);
    const [artAnchorX, artAnchorY] = asset.artAnchor || [50, 50];
    element.style.setProperty("--x", anchor.x);
    element.style.setProperty("--y", anchor.y);
    element.style.setProperty("--art-anchor-x", `${-artAnchorX}%`);
    element.style.setProperty("--art-anchor-y", `${-artAnchorY}%`);
    element.style.zIndex = String(itemDepth(asset, placement));
  }

  function makeRoomItem(asset, placement) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "room-item";
    button.dataset.id = asset.id;
    button.setAttribute("aria-label", `${asset.label} 이동하기. Delete 키로 치울 수 있습니다.`);
    if (selectedId === asset.id) button.classList.add("is-selected");
    button.style.setProperty("--width", asset.width);
    positionElement(button, asset, placement);

    const image = document.createElement("img");
    image.src = themedAssetSource(asset);
    image.alt = asset.label;
    image.draggable = false;
    button.append(image);

    button.addEventListener("pointerdown", (event) => startDrag(event, asset, button));
    button.addEventListener("click", () => {
      selectedId = asset.id;
      render();
    });
    button.addEventListener("keydown", (event) => {
      if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        addOrReplaceAsset(asset);
      }
    });
    return button;
  }

  function pointerGrid(event) {
    const rect = roomStage.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * 100;
    const y = ((event.clientY - rect.top) / rect.height) * 100;
    return physics.screenToGrid(x, y);
  }

  function startDrag(event, asset, element) {
    if (event.button !== 0) return;
    event.preventDefault();
    const original = { ...state.items[asset.id] };
    const startPointer = pointerGrid(event);
    let preview = { ...original };
    let valid = true;
    let moved = false;
    selectedId = asset.id;
    element.classList.add("is-selected", "is-dragging");
    element.setPointerCapture(event.pointerId);

    function move(moveEvent) {
      const current = pointerGrid(moveEvent);
      const dCol = Math.floor(current.col) - Math.floor(startPointer.col);
      const dRow = Math.floor(current.row) - Math.floor(startPointer.row);
      preview = physics.clampPlacement(asset, original.col + dCol, original.row + dRow, original.facing || 0);
      valid = placementIsValid(asset, preview, asset.id);
      moved ||= Math.hypot(moveEvent.clientX - event.clientX, moveEvent.clientY - event.clientY) > 4;
      positionElement(element, asset, preview);
      element.classList.toggle("is-invalid", !valid);
      renderDeveloperOverlay({ id: asset.id, placement: preview, valid });
    }

    function end() {
      element.classList.remove("is-dragging", "is-invalid");
      element.removeEventListener("pointermove", move);
      element.removeEventListener("pointerup", end);
      element.removeEventListener("pointercancel", end);
      if (moved && valid) {
        state.items[asset.id] = preview;
        saveState();
        showToast("격자 위치를 저장했어요.");
      } else if (moved) {
        showToast("다른 소품과 겹쳐서 원래 자리로 돌아갔어요.");
      }
      render();
    }

    element.addEventListener("pointermove", move);
    element.addEventListener("pointerup", end);
    element.addEventListener("pointercancel", end);
  }

  function renderInventory() {
    inventoryList.replaceChildren();
    CATALOG.forEach((asset, index) => {
      const button = document.createElement("button");
      const unlocked = index < state.progress;
      button.type = "button";
      button.className = "inventory-card";
      button.disabled = !unlocked;
      button.setAttribute("aria-label", unlocked ? `${asset.label} 배치 또는 치우기` : `${asset.label} 잠김`);
      if (!unlocked) button.classList.add("is-locked");
      if (state.items[asset.id]) button.classList.add("is-active");
      const image = document.createElement("img");
      image.src = themedAssetSource(asset);
      image.alt = "";
      const label = document.createElement("span");
      label.textContent = asset.label;
      button.append(image, label);
      if (unlocked) button.addEventListener("click", () => addOrReplaceAsset(asset));
      inventoryList.append(button);
    });
  }

  function render() {
    roomItems.replaceChildren();
    Object.entries(state.items).forEach(([id, placement]) => {
      const asset = getAsset(id);
      if (asset) roomItems.append(makeRoomItem(asset, placement));
    });
    renderInventory();
    progressLabel.textContent = `방 성장도 ${state.progress} / ${CATALOG.length}`;
    roomHint.textContent = state.progress === 0
      ? "훈련을 완료해서 첫 소품을 받아보세요."
      : "소품은 격자에 맞춰 놓이고 강아지는 가구를 피해 걸어요.";
    completeTask.disabled = state.progress >= CATALOG.length;
    completeTask.querySelector("b").textContent = state.progress >= CATALOG.length ? "모두 완료" : "훈련 완료";
    completeTask.querySelector("small").textContent = state.progress >= CATALOG.length ? "모든 소품을 받았어요" : "소품 하나 받기";
    renderDeveloperOverlay();
  }

  completeTask.addEventListener("click", () => {
    if (state.progress >= CATALOG.length) return;
    const asset = CATALOG[state.progress];
    state.progress += 1;
    addOrReplaceAsset(asset);
    showToast(`새 소품 잠금 해제: ${asset.label}`);
  });

  resetRoom.addEventListener("click", () => {
    state = initialState();
    applyDogDefinition(state.dogId, false);
    applyTheme(state.themeId, false);
    dog.pos = { x: 4, y: 9 };
    dog.target = null;
    selectedId = null;
    saveState();
    render();
    showToast("빈 방으로 돌아왔어요.");
  });

  roomStage.addEventListener("pointerdown", (event) => {
    if (event.target === roomStage || event.target.classList.contains("room-background")) {
      selectedId = null;
      render();
    }
  });

  developerToggle.addEventListener("click", () => setDeveloperMode(!developerMode));
  breedPicker.addEventListener("change", () => {
    applyDogDefinition(breedPicker.value);
    renderDog();
    showToast(`${dog.definition.labelKo} 선택`);
  });
  themePicker.addEventListener("change", () => {
    applyTheme(themePicker.value);
    render();
    if (developerMode) syncDeveloperThemeGallerySelection();
    showToast(`${roomThemes.get(state.themeId).label} theme`);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key.toLowerCase() === "d" && !event.ctrlKey && !event.metaKey && !event.altKey) {
      setDeveloperMode(!developerMode);
    }
  });

  function setDogFrame(frame) {
    const count = dog.definition.frameCount;
    const index = ((frame % count) + count) % count;
    dogSprite.style.backgroundPosition = `${index * (100 / (count - 1))}% 0`;
  }

  function renderDog() {
    const point = physics.gridToScreen(dog.pos.x, dog.pos.y);
    const depth = Math.floor(dog.pos.x) + Math.floor(dog.pos.y);
    dogWalker.style.left = `${point.x}%`;
    dogWalker.style.top = `${point.y}%`;
    dogWalker.style.width = `${dog.definition.visualWidth}%`;
    dogWalker.style.zIndex = String(150 + depth * 50);
    dogFacing.style.setProperty("--facing", dog.mirrored ? -1 : 1);
    dogWalker.classList.toggle("is-moving", dog.moving);
    setDogFrame(dog.moving ? Math.floor(dog.phase) : 1);
  }

  function updateDog(now, deltaSeconds) {
    const blocked = currentBlocked();
    const radius = dog.definition.bodyRadius;
    if (!dog.target) dog.target = physics.randomFreeSpot(blocked, Math.random, radius);

    const trapped = physics.blockedAt(dog.pos.x, dog.pos.y, blocked, radius);
    if (trapped) {
      dog.target = physics.nearestFree(dog.pos, blocked);
      dog.restUntil = 0;
    } else if (now < dog.restUntil) {
      dog.moving = false;
      return;
    }

    const dx = dog.target.x - dog.pos.x;
    const dy = dog.target.y - dog.pos.y;
    const distance = Math.hypot(dx, dy);
    if (distance < 0.06) {
      dog.restUntil = now + 4000 + Math.random() * 6000;
      dog.target = physics.randomFreeSpot(blocked, Math.random, radius);
      dog.moving = false;
      return;
    }

    const step = dog.definition.speed * deltaSeconds;
    const ratio = Math.min(1, step / distance);
    const wanted = physics.clampDog({ x: dog.pos.x + dx * ratio, y: dog.pos.y + dy * ratio }, radius);
    const next = trapped ? wanted : physics.slide(dog.pos, wanted, blocked, radius);
    const movedX = next.x - dog.pos.x;
    const movedY = next.y - dog.pos.y;
    const gained = Math.hypot(movedX, movedY);

    if (gained < step * 0.2) {
      dog.target = physics.randomFreeSpot(blocked, Math.random, radius);
      dog.restUntil = now + 250;
      dog.moving = false;
      return;
    }

    const screenDirection = movedX - movedY;
    if (Math.abs(screenDirection) > 0.0005) dog.mirrored = screenDirection < 0;
    dog.pos = next;
    dog.moving = true;
    dog.phase += deltaSeconds * dog.definition.fps;
  }

  function animationLoop(now) {
    if (!lastFrameTime) lastFrameTime = now;
    const deltaSeconds = Math.max(0, Math.min(0.05, (now - lastFrameTime) / 1000));
    lastFrameTime = now;
    updateDog(now, deltaSeconds);
    renderDog();
    requestAnimationFrame(animationLoop);
  }

  dogWalker.addEventListener("click", () => {
    if (reducedMotion.matches) return;
    dog.restUntil = performance.now() + 700;
    dog.moving = false;
    dogWalker.classList.remove("is-happy");
    void dogWalker.offsetWidth;
    dogWalker.classList.add("is-happy");
    setTimeout(() => dogWalker.classList.remove("is-happy"), 760);
  });

  DOG_CATALOG.forEach((definition) => {
    const option = document.createElement("option");
    option.value = definition.id;
    option.textContent = `${definition.labelKo} · ${definition.label}`;
    breedPicker.append(option);
  });
  THEME_CATALOG.forEach((theme) => {
    const option = document.createElement("option");
    option.value = theme.id;
    option.textContent = `${theme.labelKo} · ${theme.label}`;
    themePicker.append(option);
  });
  applyDogDefinition(state.dogId, false);
  applyTheme(state.themeId, false);
  render();
  renderDog();
  if (new URLSearchParams(location.search).get("debug") === "1") setDeveloperMode(true);
  if (!reducedMotion.matches) requestAnimationFrame(animationLoop);

  window.DaengsDogCatalog = DOG_CATALOG;
  window.DaengsRoomThemeCatalog = THEME_CATALOG;
})();
