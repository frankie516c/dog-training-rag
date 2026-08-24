(() => {
  "use strict";

  const STORAGE_KEY = "daengs.modular-room.v2";
  const DOG_IDLE = "../assets/modular-dog-v1-final.png";
  const DOG_WALK_FRAMES = [1, 2, 3, 4].map((frame) => `../assets/modular-dog-walk-${frame}.png`);

  const CATALOG = [
    {
      id: "rug-cream",
      category: "rug",
      anchor: "center",
      label: "크림 러그",
      src: "../assets/modular-rug-v1-final.png",
      width: 40,
      defaultPosition: { x: 49, y: 73 }
    },
    {
      id: "plant-tall",
      category: "plant",
      anchor: "ground",
      label: "큰 화분",
      src: "../assets/modular-plant-v1-final.png",
      width: 11.5,
      defaultPosition: { x: 83, y: 70 }
    },
    {
      id: "doghouse-sage",
      category: "doghouse",
      anchor: "ground",
      label: "강아지 집",
      src: "../assets/modular-doghouse-v1-final.png",
      width: 19.5,
      defaultPosition: { x: 72, y: 72 }
    },
    {
      id: "ball-sage",
      category: "toy",
      anchor: "center",
      label: "초록 공",
      src: "../assets/modular-ball-v1-final.png",
      width: 4.8,
      defaultPosition: { x: 56, y: 77 }
    },
    {
      id: "cabinet-sage",
      category: "cabinet",
      anchor: "ground",
      label: "세이지 수납장",
      src: "../assets/modular-cabinet-v1-final.png",
      width: 22,
      defaultPosition: { x: 68, y: 63 }
    },
    {
      id: "toy-basket",
      category: "basket",
      anchor: "ground",
      label: "장난감 바구니",
      src: "../assets/modular-toy-basket-v1-final.png",
      width: 10,
      defaultPosition: { x: 30, y: 75 }
    },
    {
      id: "feeding-bowls",
      category: "feeding",
      anchor: "center",
      label: "밥그릇 세트",
      src: "../assets/modular-feeding-bowls-v1-final.png",
      width: 9,
      defaultPosition: { x: 51, y: 68 }
    },
    {
      id: "rug-sage",
      category: "rug",
      anchor: "center",
      label: "세이지 러그",
      src: "../assets/modular-rug-sage-v1-final.png",
      width: 40,
      defaultPosition: { x: 49, y: 73 }
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
  const dogSprite = dogWalker.querySelector("img");

  const previewFull = location.hash === "#full";
  let state = previewFull ? fullPreviewState() : loadState();
  let selectedId = null;
  let toastTimer;
  let dogTimer;
  let dogFrameTimer;
  let dogMoveEndTimer;
  let dogFrame = 0;
  let dogPosition = { x: 43, y: 75 };

  function initialState() {
    return { progress: 0, items: {} };
  }

  function fullPreviewState() {
    const items = {};
    CATALOG.forEach((asset) => {
      if (asset.category === "rug" && asset.id !== "rug-sage") return;
      items[asset.id] = { ...asset.defaultPosition };
    });
    return { progress: CATALOG.length, items };
  }

  function loadState() {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY));
      if (!parsed || typeof parsed.progress !== "number" || typeof parsed.items !== "object") return initialState();
      parsed.progress = Math.max(0, Math.min(CATALOG.length, parsed.progress));
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

  function isUnlocked(index) {
    return index < state.progress;
  }

  function showToast(message) {
    clearTimeout(toastTimer);
    toast.textContent = message;
    toast.classList.add("is-visible");
    toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 1500);
  }

  function addOrReplaceAsset(asset) {
    const existingCategoryEntry = Object.entries(state.items).find(([id]) => getAsset(id)?.category === asset.category);
    let position = asset.defaultPosition;

    if (existingCategoryEntry) {
      const [existingId, existingPosition] = existingCategoryEntry;
      if (existingId === asset.id) {
        delete state.items[existingId];
        selectedId = null;
        showToast(`${asset.label}을(를) 보관함에 넣었어요.`);
        saveState();
        render();
        return;
      }
      position = existingPosition;
      delete state.items[existingId];
      showToast(`${asset.label}(으)로 교체되었어요.`);
    } else {
      showToast(`${asset.label}을(를) 방에 놓았어요.`);
    }

    state.items[asset.id] = floorConstraint(asset, position.x, position.y);
    selectedId = asset.id;
    saveState();
    render();
  }

  function removeAsset(id) {
    const asset = getAsset(id);
    delete state.items[id];
    if (selectedId === id) selectedId = null;
    saveState();
    render();
    showToast(`${asset.label}을(를) 보관함에 넣었어요.`);
  }

  // The visible floor is an asymmetric perspective polygon. Positions use an
  // object's floor-contact point, not the center of its transparent PNG.
  function backEdgeAt(x) {
    return x <= 56 ? 52 + (56 - x) / 1.58 : 52 + (x - 56) / 2.55;
  }

  function frontEdgeAt(x) {
    return x <= 50 ? 85 - Math.max(0, 34 - x) * 0.035 : 85 - (x - 50) * 0.3;
  }

  function horizontalEdgesAt(y) {
    const depth = Math.max(0, y - 52);
    return {
      left: Math.max(5, 56 - depth * 1.58),
      right: Math.min(96, 56 + depth * 2.55)
    };
  }

  function floorConstraint(asset, x, y) {
    const isRug = asset.category === "rug";
    const centerFloorAsset = asset.anchor === "center";
    const halfWidth = asset.width / 2;
    const sideInset = isRug ? halfWidth * 0.65 : centerFloorAsset ? halfWidth * 0.7 : halfWidth * 0.5;
    const backMargin = isRug ? 4.5 : centerFloorAsset ? 1.8 : 1.2;
    const frontMargin = isRug ? 5.5 : centerFloorAsset ? 2.2 : 1.6;

    let safeX = Math.max(12, Math.min(91, Number(x) || asset.defaultPosition.x));
    let minY = backEdgeAt(safeX) + backMargin;
    let maxY = frontEdgeAt(safeX) - frontMargin;
    let safeY = Math.max(minY, Math.min(maxY, Number(y) || asset.defaultPosition.y));

    const horizontal = horizontalEdgesAt(safeY);
    safeX = Math.max(horizontal.left + sideInset, Math.min(horizontal.right - sideInset, safeX));
    minY = backEdgeAt(safeX) + backMargin;
    maxY = frontEdgeAt(safeX) - frontMargin;
    safeY = Math.max(minY, Math.min(maxY, safeY));

    return { x: Number(safeX.toFixed(2)), y: Number(safeY.toFixed(2)) };
  }

  function groundDepth(y) {
    return 100 + Math.round(y * 10);
  }

  function itemDepth(asset, y) {
    return asset.category === "rug" ? 40 : groundDepth(y);
  }

  function makeRoomItem(asset, rawPosition) {
    const position = floorConstraint(asset, rawPosition.x, rawPosition.y);
    state.items[asset.id] = position;
    const button = document.createElement("button");
    button.type = "button";
    button.className = `room-item anchor-${asset.anchor}`;
    button.dataset.id = asset.id;
    button.setAttribute("aria-label", `${asset.label} 이동하기. Delete 키로 치울 수 있습니다.`);
    if (selectedId === asset.id) button.classList.add("is-selected");
    button.style.setProperty("--x", position.x);
    button.style.setProperty("--y", position.y);
    button.style.setProperty("--width", asset.width);
    button.style.zIndex = itemDepth(asset, position.y);

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
        removeAsset(asset.id);
      }
    });
    return button;
  }

  function startDrag(event, asset, element) {
    if (event.button !== 0) return;
    event.preventDefault();
    selectedId = asset.id;
    element.classList.add("is-selected", "is-dragging");
    element.setPointerCapture(event.pointerId);
    let moved = false;
    const startX = event.clientX;
    const startY = event.clientY;

    function move(moveEvent) {
      const rect = roomStage.getBoundingClientRect();
      const rawX = ((moveEvent.clientX - rect.left) / rect.width) * 100;
      const rawY = ((moveEvent.clientY - rect.top) / rect.height) * 100;
      const position = floorConstraint(asset, rawX, rawY);
      moved ||= Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) > 4;
      state.items[asset.id] = position;
      element.style.setProperty("--x", position.x);
      element.style.setProperty("--y", position.y);
      element.style.zIndex = itemDepth(asset, position.y);
    }

    function end() {
      element.classList.remove("is-dragging");
      element.removeEventListener("pointermove", move);
      element.removeEventListener("pointerup", end);
      element.removeEventListener("pointercancel", end);
      saveState();
      if (moved) showToast("위치를 저장했어요.");
    }

    element.addEventListener("pointermove", move);
    element.addEventListener("pointerup", end);
    element.addEventListener("pointercancel", end);
  }

  function renderInventory() {
    inventoryList.replaceChildren();
    CATALOG.forEach((asset, index) => {
      const button = document.createElement("button");
      const unlocked = isUnlocked(index);
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
    Object.entries(state.items).forEach(([id, position]) => {
      const asset = getAsset(id);
      if (asset) roomItems.append(makeRoomItem(asset, position));
    });
    renderInventory();
    progressLabel.textContent = `방 성장도 ${state.progress} / ${CATALOG.length}`;
    roomHint.textContent = state.progress === 0
      ? "훈련을 완료해서 첫 소품을 받아보세요."
      : "소품을 드래그해 옮기고 보관함에서 교체할 수 있어요.";
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

  function stopDogWalk() {
    clearInterval(dogFrameTimer);
    clearTimeout(dogMoveEndTimer);
    dogWalker.classList.remove("is-walking");
    dogSprite.src = DOG_IDLE;
  }

  function happyDog() {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    stopDogWalk();
    dogWalker.classList.remove("is-happy");
    void dogWalker.offsetWidth;
    dogWalker.classList.add("is-happy");
    setTimeout(() => dogWalker.classList.remove("is-happy"), 760);
  }

  function startDogWalk(duration) {
    stopDogWalk();
    dogFrame = 0;
    dogSprite.src = DOG_WALK_FRAMES[dogFrame];
    dogWalker.classList.add("is-walking");
    dogFrameTimer = setInterval(() => {
      dogFrame = (dogFrame + 1) % DOG_WALK_FRAMES.length;
      dogSprite.src = DOG_WALK_FRAMES[dogFrame];
    }, 135);
    dogMoveEndTimer = setTimeout(stopDogWalk, duration + 80);
  }

  function moveDog() {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const points = [
      { x: 39, y: 75 },
      { x: 53, y: 77 },
      { x: 32, y: 79 },
      { x: 62, y: 72 },
      { x: 48, y: 67 }
    ];
    let next = points[Math.floor(Math.random() * points.length)];
    if (Math.hypot(next.x - dogPosition.x, next.y - dogPosition.y) < 4) {
      next = points[(points.indexOf(next) + 1) % points.length];
    }
    const distance = Math.hypot(next.x - dogPosition.x, (next.y - dogPosition.y) * 1.4);
    const duration = Math.max(1700, Math.min(3400, Math.round(distance * 145)));

    dogFacing.style.setProperty("--facing", next.x < dogPosition.x ? -1 : 1);
    dogWalker.style.setProperty("--walk-duration", `${duration}ms`);
    startDogWalk(duration);
    dogWalker.style.left = `${next.x}%`;
    dogWalker.style.top = `${next.y}%`;
    dogWalker.style.zIndex = String(groundDepth(next.y));
    dogPosition = next;

    clearTimeout(dogTimer);
    dogTimer = setTimeout(moveDog, duration + 1700 + Math.random() * 1800);
  }

  dogWalker.addEventListener("click", happyDog);

  dogWalker.style.left = `${dogPosition.x}%`;
  dogWalker.style.top = `${dogPosition.y}%`;
  dogWalker.style.zIndex = String(groundDepth(dogPosition.y));
  render();
  dogTimer = setTimeout(moveDog, 1200);
})();
