(function attachDogPresets(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.DaengsDogPresets = api;
})(typeof globalThis !== "undefined" ? globalThis : window, () => {
  "use strict";

  const animation = Object.freeze({ frameCount: 4, fps: 5 });

  function preset(id, label, labelKo, visualWidth, bodyRadius, speed) {
    return Object.freeze({
      id,
      label,
      labelKo,
      sheet: `../assets/dogs/${id}/walk.png`,
      portrait: `../assets/dogs/${id}/portrait.png`,
      frameCount: animation.frameCount,
      fps: animation.fps,
      visualWidth,
      bodyRadius,
      speed
    });
  }

  // visualWidth controls the on-screen art size. bodyRadius independently
  // controls the dog's floor footprint so fluffy coats do not over-collide.
  const catalog = Object.freeze([
    preset("beagle", "Beagle", "비글", 13, 0.58, 0.54),
    preset("toy-poodle-silver", "Silver Toy Poodle", "실버 푸들", 12, 0.5, 0.5),
    preset("toy-poodle-light-brown", "Light Brown Toy Poodle", "연갈색 푸들", 12, 0.5, 0.5),
    preset("toy-poodle-chocolate", "Chocolate Toy Poodle", "초코 푸들", 12, 0.5, 0.5),
    preset("maltese", "Maltese", "말티즈", 11, 0.46, 0.53),
    preset("yorkshire-terrier", "Yorkshire Terrier", "요크셔테리어", 10.5, 0.45, 0.57),
    preset("chihuahua", "Chihuahua", "치와와", 9.5, 0.42, 0.61),
    preset("bichon-frise", "Bichon Frise", "비숑 프리제", 11.5, 0.48, 0.52),
    preset("labrador-retriever", "Labrador Retriever", "래브라도 리트리버", 16.5, 0.75, 0.48),
    preset("jindo", "Jindo", "진돗개", 14.5, 0.64, 0.54),
    preset("shiba-inu-black", "Black Shiba Inu", "검정 시바", 13.5, 0.59, 0.56),
    preset("shiba-inu-beige", "Beige Shiba Inu", "베이지 시바", 13.5, 0.59, 0.56),
    preset("shiba-inu-orange", "Orange Shiba Inu", "오렌지 시바", 13.5, 0.59, 0.56),
    preset("siberian-husky", "Siberian Husky", "시베리안 허스키", 16, 0.72, 0.52),
    preset("pomeranian-black-tan", "Black-and-Tan Pomeranian", "블랙탄 포메라니안", 11.5, 0.46, 0.57),
    preset("pomeranian-beige", "Beige Pomeranian", "베이지 포메라니안", 11.5, 0.46, 0.57),
    preset("pomeranian-white", "White Pomeranian", "흰색 포메라니안", 11.5, 0.46, 0.57),
    preset("border-collie", "Border Collie", "보더 콜리", 15.5, 0.68, 0.59),
    preset("welsh-corgi", "Welsh Corgi", "웰시 코기", 14.8, 0.65, 0.54),
    preset("dachshund-short-brown", "Short-Haired Brown Dachshund", "단모 갈색 닥스훈트", 16.5, 0.67, 0.52),
    preset("dachshund-short-black", "Short-Haired Black Dachshund", "단모 검정 닥스훈트", 16.5, 0.67, 0.52),
    preset("dachshund-long-beige", "Long-Haired Beige Dachshund", "장모 베이지 닥스훈트", 17, 0.69, 0.5),
    preset("french-bulldog", "French Bulldog", "프렌치 불도그", 12, 0.55, 0.47),
    preset("pug", "Pug", "퍼그", 11.5, 0.52, 0.47),
    preset("schnauzer", "Schnauzer", "슈나우저", 12.5, 0.54, 0.52)
  ]);

  function get(id) {
    return catalog.find((entry) => entry.id === id) || catalog[0];
  }

  return Object.freeze({ animation, catalog, get });
});
