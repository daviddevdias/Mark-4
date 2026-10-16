(() => {
  "use strict";
  window.createJarvisCameraCard = (root) => {
    root.classList.add("camera-card");
    const frame = document.createElement("div"),
      video = document.createElement("video");
    frame.className = "camera-card-frame";
    frame.append(video);
    root.replaceChildren(frame);
    const player = window.createJarvisVideo(video);
    player.ready.catch(() => {});
    const overlay = window.createJarvisYoloOverlay?.(frame, video, player);
    return {
      destroy: () => {
        overlay?.close();
        player.fechar();
      },
    };
  };
})();
