(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.DaengsRoomThemes = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const catalog = Object.freeze([
    Object.freeze({ id: "cherry-blossom", label: "Cherry Blossom", labelKo: "벚꽃", swatch: "#efb7c6" }),
    Object.freeze({ id: "mint", label: "Mint", labelKo: "민트", swatch: "#afd8c6" }),
    Object.freeze({ id: "lavender", label: "Lavender", labelKo: "라벤더", swatch: "#cdbce4" }),
    Object.freeze({ id: "sky-blue", label: "Sky Blue", labelKo: "하늘", swatch: "#b5d8ee" }),
    Object.freeze({ id: "butter", label: "Butter", labelKo: "버터", swatch: "#f1d991" })
  ]);

  function get(id) {
    return catalog.find((theme) => theme.id === id) || catalog[0];
  }

  return Object.freeze({ catalog, get });
});
