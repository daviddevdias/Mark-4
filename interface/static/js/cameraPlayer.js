(() => {
  "use strict";
  // Compartilha captura e recuperação
  window.createJarvisVideo = (video, options = {}) => {
    const host = video.parentElement;
    let closed = false,
      paused = false,
      peer = null,
      controller = null,
      generation = 0,
      timer = 0,
      lastFrame = 0,
      image = null,
      imageUrl = null,
      frameCallback = null;
    let failures = 0,
      fallback = false,
      lastVideoTime = -1,
      visible = true,
      nextVideoAttempt = 0;
    const settings = { duas_lentes: false, lente: options.lente || "baixo" };
    const toolbar = document.createElement("div"),
      state = document.createElement("span"),
      retry = document.createElement("button"),
      expand = document.createElement("button");
    toolbar.className = "camera-tools";
    state.setAttribute("role", "status");
    retry.textContent = "Reconectar";
    expand.textContent = "Ampliar";
    for (const b of [retry, expand]) {
      b.type = "button";
      b.className = "camera-tool";
    }
    toolbar.append(state, retry, expand);
    host.append(toolbar);
    video.autoplay = true;
    video.muted = true;
    video.playsInline = true;
    let resolveReady,
      rejectReady,
      settled = false;
    const ready = new Promise((resolve, reject) => {
      resolveReady = resolve;
      rejectReady = reject;
    });
    function status(text) {
      state.textContent = text;
      options.onState?.(text);
    }
    function received() {
      if (!fallback && image) {
        image.remove();
        image = null;
        if (imageUrl) URL.revokeObjectURL(imageUrl);
        imageUrl = null;
        video.style.visibility = "";
      }
      lastFrame = Date.now();
      failures = 0;
      status(fallback ? "Ao vivo · quadros" : "Ao vivo · vídeo");
      if (!settled) {
        settled = true;
        resolveReady(player);
      }
      options.onFrame?.();
    }
    async function request(path, init = {}, kind = "json") {
      const abort = new AbortController(),
        parent = controller,
        stop = () => abort.abort();
      if (parent.signal.aborted)
        throw new DOMException("Cancelado", "AbortError");
      parent.signal.addEventListener("abort", stop, { once: true });
      const timeout = setTimeout(stop, 5000);
      try {
        const r = await fetch(path, {
          ...init,
          signal: abort.signal,
          cache: "no-store",
        });
        if (!r.ok) throw Error("Câmera indisponível");
        return await r[kind]();
      } finally {
        clearTimeout(timeout);
        parent.signal.removeEventListener("abort", stop);
      }
    }
    function fit() {
      if (!video.videoWidth || fallback) return;
      const split = settings.duas_lentes
        ? Math.min(0.95, Math.max(0.05, Number(settings.divisao_y) || 0.5))
        : 0;
      const bottom = settings.lente !== "cima",
        fraction = split ? (bottom ? 1 - split : split) : 1;
      host.style.position = "relative";
      host.style.overflow = "hidden";
      host.style.aspectRatio = `${video.videoWidth} / ${video.videoHeight * fraction}`;
      const height = host.clientHeight / fraction;
      Object.assign(video.style, {
        position: "absolute",
        left: "0",
        width: "100%",
        height: height + "px",
        maxHeight: "none",
        objectFit: "fill",
        top: (bottom ? -height * split : 0) + "px",
      });
    }
    function clear(keepImage = false) {
      generation++;
      clearTimeout(timer);
      controller?.abort();
      controller = null;
      if (frameCallback !== null && video.cancelVideoFrameCallback)
        video.cancelVideoFrameCallback(frameCallback);
      frameCallback = null;
      if (peer) {
        peer.ontrack = null;
        peer.onconnectionstatechange = null;
        peer.close();
        peer = null;
      }
      video.srcObject?.getTracks().forEach((t) => t.stop());
      video.srcObject = null;
      video.pause();
      if (!keepImage) {
        image?.remove();
        image = null;
        if (imageUrl) URL.revokeObjectURL(imageUrl);
        imageUrl = null;
        video.style.visibility = "";
      }
    }
    async function snapshots(token) {
      if (closed || token !== generation || paused) return;
      fallback = true;
      settings.previa = true;
      settings.duas_lentes = false;
      try {
        const blob = await request("/seguranca/linha/quadro.jpg", {}, "blob");
        if (token !== generation) return;
        const next = URL.createObjectURL(blob),
          probe = new Image();
        probe.src = next;
        try {
          await probe.decode();
        } catch (e) {
          URL.revokeObjectURL(next);
          throw e;
        }
        if (token !== generation) {
          URL.revokeObjectURL(next);
          return;
        }
        if (!image) {
          image = document.createElement("img");
          image.className = "camera-preview";
          image.alt = "Imagem recente da câmera inferior";
          host.insertBefore(image, toolbar);
        }
        const old = imageUrl;
        imageUrl = next;
        image.src = next;
        if (old) URL.revokeObjectURL(old);
        video.style.visibility = "hidden";
        video.dataset.previaLargura = String(probe.naturalWidth);
        video.dataset.previaAltura = String(probe.naturalHeight);
        received();
      } catch (e) {
        if (token !== generation) return;
        failures++;
        status(
          "Sem imagem · nova tentativa em " + Math.min(10, failures * 2) + " s",
        );
      }
      if (token === generation)
        timer = setTimeout(
          () => snapshots(token),
          failures
            ? Math.min(10000, failures * 2000)
            : document.body.classList.contains("economy-mode")
              ? 750
              : 180,
        );
    }
    function useSnapshots(token) {
      if (token !== generation || fallback) return;
      nextVideoAttempt = Date.now() + 30000;
      clearTimeout(timer);
      if (peer) {
        peer.onconnectionstatechange = null;
        peer.ontrack = null;
        peer.close();
        peer = null;
      }
      video.srcObject = null;
      snapshots(token);
    }
    async function start() {
      clear(true);
      paused = document.hidden || !visible;
      if (closed || paused) {
        status("Vídeo pausado fora da tela");
        return;
      }
      const token = generation;
      controller = new AbortController();
      fallback = false;
      lastFrame = 0;
      lastVideoTime = -1;
      status("Conectando câmera…");
      try {
        Object.assign(settings, await request("/seguranca/ao-vivo/stream"));
        if (token !== generation) return;
        settings.lente = options.lente || settings.lente || "baixo";
        settings.previa = false;
        const pc = new RTCPeerConnection({ iceServers: [] });
        peer = pc;
        pc.addTransceiver("video", { direction: "recvonly" });
        pc.addTransceiver("audio", { direction: "recvonly" });
        pc.ontrack = (e) => {
          if (token !== generation) return;
          let stream = video.srcObject;
          if (!stream) video.srcObject = stream = new MediaStream();
          stream.addTrack(e.track);
          video.play().catch(() => {});
        };
        await pc.setLocalDescription(await pc.createOffer());
        if (pc.iceGatheringState !== "complete")
          await new Promise((resolve) => {
            const done = () => {
                clearTimeout(wait);
                pc.removeEventListener("icegatheringstatechange", change);
                resolve();
              },
              change = () => {
                if (pc.iceGatheringState === "complete") done();
              },
              wait = setTimeout(done, 1500);
            pc.addEventListener("icegatheringstatechange", change);
          });
        if (token !== generation) return;
        const sdp = await request(
          "/seguranca/ao-vivo/webrtc",
          {
            method: "POST",
            headers: { "Content-Type": "application/sdp" },
            body: pc.localDescription.sdp,
          },
          "text",
        );
        if (token !== generation) return;
        await pc.setRemoteDescription({ type: "answer", sdp });
        pc.onconnectionstatechange = () => {
          if (["failed", "disconnected"].includes(pc.connectionState))
            useSnapshots(token);
        };
        timer = setTimeout(() => {
          if (!lastFrame) useSnapshots(token);
        }, 5000);
      } catch (e) {
        if (token === generation) useSnapshots(token);
      }
    }
    function decoded() {
      if (!closed && !paused && !fallback && video.readyState >= 2) {
        received();
        fit();
      }
    }
    video.addEventListener("loadeddata", decoded);
    video.addEventListener("loadedmetadata", fit);
    const watch = setInterval(() => {
      if (!video.isConnected) {
        player.fechar();
        return;
      }
      if (closed || paused) return;
      if (fallback && Date.now() > nextVideoAttempt && lastFrame) {
        start();
        return;
      }
      if (
        !fallback &&
        video.readyState >= 2 &&
        video.currentTime !== lastVideoTime
      ) {
        lastVideoTime = video.currentTime;
        received();
      }
      if (lastFrame) {
        const age = Math.floor((Date.now() - lastFrame) / 1000);
        state.textContent =
          (fallback ? "Quadros" : "Vídeo") +
          " · último quadro " +
          (age ? age + " s" : "agora");
        if (age > 8) {
          status("Imagem atrasada · reconectando");
          fallback ? start() : useSnapshots(generation);
        }
      }
      if (!video.isConnected) player.fechar();
    }, 1000);
    const resize = new ResizeObserver(fit);
    resize.observe(host);
    const observer = new IntersectionObserver((entries) => {
      const next = entries[0].isIntersecting;
      if (next === visible) return;
      visible = next;
      start();
    });
    observer.observe(host);
    const visibility = () => start();
    document.addEventListener("visibilitychange", visibility);
    retry.onclick = () => start();
    expand.onclick = () => {
      const action =
        document.fullscreenElement === host
          ? document.exitFullscreen()
          : host.requestFullscreen?.();
      action?.catch(() => status("Não foi possível ampliar"));
    };
    const player = {
      ready,
      configuracao: settings,
      reconectar: start,
      definirLente(lente) {
        if (fallback) {
          status("Quadros disponíveis apenas da lente inferior");
          return;
        }
        settings.lente = lente;
        options.lente = lente;
        fit();
      },
      fechar() {
        if (closed) return;
        closed = true;
        clear();
        clearInterval(watch);
        resize.disconnect();
        observer.disconnect();
        document.removeEventListener("visibilitychange", visibility);
        video.removeEventListener("loadeddata", decoded);
        video.removeEventListener("loadedmetadata", fit);
        toolbar.remove();
        delete video.dataset.previaLargura;
        delete video.dataset.previaAltura;
        if (!settled) {
          settled = true;
          rejectReady(Error("Visualizador fechado"));
        }
      },
    };
    start();
    return player;
  };
})();
