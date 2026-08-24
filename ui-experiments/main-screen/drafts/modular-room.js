(() => {
  "use strict";

  const physics = window.DaengsRoomPhysics;
  if (!physics) throw new Error("DaengsRoomPhysics must load before modular-room.js");

  const STORAGE_KEY = "daengs.modular-room.v3";

  // Adding the later 20 breeds means appending catalog entries with the same
  // frame contract. Size is deliberately constant per breed and never changes
  // between idle/walk states.
  const DOG_CATALOG = [
    {
      id: "toy-poodle",
      label: "크림 토이푸들",
      sheet: "../assets/modular-dog-poodle-walk-stable-v2.png",
      frameCount: 4,
      fps: 8,
      visualWidth: 13.5,
      bodyRadius: 0.22,
      speed: 0.72
    }
  ];

  const CATALOG = [
    {
      id: "rug-cream",
      category: "rug",
      label: "크림 러그",
      src: "../assets/modular-rug-v1-final.png",
      width: 40,
      artAnchor: [50, 50],
      footprint: [3, 3],
      flat: true,
      defaultPlacement: { col: 2, row: 2, facing: 0 }
    },
    {
      id: "plant-tall",
      category: "plant",
      label: "큰 화분",
      src: "../assets/modular-plant-v1-final.png",
      width: 11.5,
      artAnchor: [50, 93],
      footprint: [1, 1],
      flat: false,
      defaultPlacement: { col: 5, row: 1, facing: 0 }
    },
    {
      id: "doghouse-sage",
      category: "doghouse",
      label: "강아지 집",
      src: "../assets/modular-doghouse-v1-final.png",
      width: 19.5,
      artAnchor: [50, 78],
      footprint: [2, 2],
      flat: false,
      defaultPlacement: { col: 4, row: 2, facing: 0 }
    },
    {
      id: "ball-sage",
      category: "toy",
      label: "초록 공",
      src: "../assets/modular-ball-v1-final.png",
      width: 4.8,
      artAnchor: [50, 94],
      footprint: [1, 1],
      flat: false,
      defaultPlacement: { col: 3, row: 4, facing: 0 }
    },
    {
      id: "cabinet-sage",
      category: "cabinet",
      label: "세이지 수납장",
      src: "../assets/modular-cabinet-v1-final.png",
      width: 22,
      artAnchor: [50, 77],
      footprint: [2, 1],
      flat: false,
      defaultPlacement: { col: 3, row: 0, facing: 0 }
    },
    {
      id: "toy-basket",
      category: "basket",
      label: "장난감 바구니",
      src: "../assets/modular-toy-basket-v1-final.png",
      width: 10,
      artAnchor: [50, 78],
      footprint: [1, 1],
      flat: false,
      defaultPlacement: { col: 1, row: 5, facing: 0 }
    },
    {
      id: "feeding-bowls",
      category: "feeding",
      label: "밥그릇 세트",
      src: "../assets/modular-feeding-bowls-v1-final.png",
      width: 9,
      artAnchor: [50, 58],
      footprint: [1, 1],
      flat: false,
      defaultPlacement: { col: 3, row: 3, facing: 0 }
    },
    {
      id: "rug-sage",
      category: "rug",
      label: "세이지 러그",
      src: "../assets/modular-rug-sage-v1-final.png",
      width: 40,
      artAnchor: [50, 50],
      footprint: [3, 3],
      flat: true,
      defaultPlacement: { col: 2, row: 2, facing: 0 }
    }
  ];

  const roomStage = document.querySelector("#roomStage");
  const roomItems = document.querySelector("#roomItems");
  const inventoryList = document.querySelector("#inventoryList");
  const completeTask = document.querySelector("#completeTask");
  const resetRoom = document.querySelector("#resetRoom");
  const progressLabel = document.querySelector("#progressLabel");
  const roomHint = document.querySelector("#roomHint");
  const toast = document.querySelector("#toast");
  const dogWalker = document.querySelector("#dogWalker");
  const dogFacing = dogWalker.querySelector(".dog-facing");
  const dogSprite = document.querySelector("#dogSprite");

  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
  let state = location.hash === "#full" ? fullPreviewState() : loadState();
  let selectedId = null;
  let toastTimer;
  let lastFrameTime = 0;

  const dog = {
    definition: getDogDefinition(state.dogId),
    pos: { x: 1.5, y: 3.5 },
    target: null,
    restUntil: 0,
    moving: false,
    mirrored: false,
    phase: 1
  };

  function initialState() {
    return { progress: 0, items: {}, dogId: DOG_CATALOG[0].id };
  }

  function fullPreviewState() {
    const items = {};
    CATALOG.forEach((asset) => {
      if (asset.category === "rug" && asset.id !== "rug-sage") return;
      items[asset.id] = { ...asset.defaultPlacement };
    });
    return { progress: CATALOG.length, items, dogId: DOG_CATALOG[0].id };
  }

  function loadState() {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY));
      if (!parsed || typeof parsed.progress !== "number" || typeof parsed.items !== "object") return initialState();
      parsed.progress = Math.max(0, Math.min(CATALOG.length, parsed.progress));
      parsed.dogId = DOG_CATALOG.some((entry) => entry.id === parsed.dogId) ? parsed.dogId : DOG_CATALOG[0].id;
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
    return DOG_CATALOG.find((entry) => entry.id === id) || DOG_CATALOG[0];
  }

  function showToast(message) {
    clearTimeout(toastTimer);
    toast.textContent = message;
    toast.classList.add("is-visible");
    toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 1500);
  }

  function currentOccupied(excludeId = null) {
    return physics.occupiedCells(state.items, CATALOG, excludeId);
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
    const occupied = currentOccupied();
    return candidates.find((placement) => physics.canPlace(asset, placement, occupied)) || null;
  }

  function validDefaultOrFree(asset) {
    const placement = physics.clampPlacement(asset, asset.defaultPlacement.col, asset.defaultPlacement.row, asset.defaultPlacement.facing);
    return physics.canPlace(asset, placement, currentOccupied()) ? placement : firstFreePlacement(asset);
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
    return asset.flat ? 40 : 100 + physics.depthKey(asset, placement) * 100;
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
    image.src = asset.src;
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
      valid = physics.canPlace(asset, preview, currentOccupied(asset.id));
      moved ||= Math.hypot(moveEvent.clientX - event.clientX, moveEvent.clientY - event.clientY) > 4;
      positionElement(element, asset, preview);
      element.classList.toggle("is-invalid", !valid);
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
      image.src = asset.src;
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
    dog.definition = getDogDefinition(state.dogId);
    dog.pos = { x: 1.5, y: 3.5 };
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
    dogWalker.style.zIndex = String(150 + depth * 100);
    dogFacing.style.setProperty("--facing", dog.mirrored ? -1 : 1);
    dogWalker.classList.toggle("is-moving", dog.moving);
    setDogFrame(dog.moving ? Math.floor(dog.phase) : 1);
  }

  function updateDog(now, deltaSeconds) {
    const blocked = currentOccupied();
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
      dog.restUntil = now + 2500 + Math.random() * 5000;
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
    dog.phase += gained * 18;
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

  dogSprite.style.backgroundImage = `url("${dog.definition.sheet}")`;
  dogSprite.style.backgroundSize = `${dog.definition.frameCount * 100}% 100%`;
  render();
  renderDog();
  if (!reducedMotion.matches) requestAnimationFrame(animationLoop);

  // A future breed picker only needs to change state.dogId and dog.definition.
  window.DaengsDogCatalog = Object.freeze(DOG_CATALOG.map((entry) => Object.freeze({ ...entry })));
})();
