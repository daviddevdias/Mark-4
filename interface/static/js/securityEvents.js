(() => {
  "use strict";
  const create = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  };
  const key = (e) => e.foto || e.hora;
  window.openSecurityEvent = (initial) => {
    if (!initial?.event) return;
    document.getElementById("securityEventHologram")?._close?.();
    const previousFocus = document.activeElement;
    const panel = create("section", null, "securityEvent-hologram");
    panel.id = "securityEventHologram";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.setAttribute("aria-label", "Histórico Torre Stark");
    const head = create("header"),
      close = create("button", "Fechar", "chip");
    head.append(create("strong", "JARVIS · TORRE STARK"), close);
    const nav = create("nav", null, "securityEvent-navigation"),
      older = create("button", "← Anterior", "btn"),
      newer = create("button", "Próximo →", "btn"),
      select = create("select"),
      count = create("span", "Carregando histórico…");
    select.setAttribute(
      "aria-label",
      "Escolher acontecimento por data e horário",
    );
    count.setAttribute("role", "status");
    nav.append(older, select, newer, count);
    const body = create("div", null, "securityEvent-hologram-body"),
      title = create("h2"),
      zone = create("p"),
      details = create("p");
    const media = create("div", null, "securityEvent-media"),
      photo = create("div", null, "securityEvent-media-item"),
      movie = create("div", null, "securityEvent-media-item");
    const img = create("img"),
      video = create("video"),
      status = create("p", null, "securityEvent-video-status"),
      retry = create("button", "Tentar vídeo novamente", "btn");
    video.controls = true;
    video.playsInline = true;
    video.preload = "metadata";
    photo.append(
      create("div", "Imagem do evento", "securityEvent-media-title"),
      img,
    );
    movie.append(
      create("div", "Gravação do evento", "securityEvent-media-title"),
      status,
      video,
      retry,
    );
    media.append(photo, movie);
    const actions = create("div", null, "securityEvent-review"),
      review = create("span");
    review.setAttribute("role", "status");
    const audio = new Audio("/seguranca/aviso/audio");
    let events = [initial],
      current = initial,
      index = 0,
      generation = 0,
      timer = 0,
      autoClose = 0,
      requestController = null,
      historyController = new AbortController(),
      closed = false;
    const timeoutHistory = setTimeout(() => historyController.abort(), 10000);
    let format = video.canPlayType('video/mp4; codecs="avc1.42E01E, mp4a.40.2"')
      ? "mp4"
      : "webm";
    const label = (e) =>
      new Date(e.hora).toLocaleString("pt-BR") +
      " · " +
      (e.quantidade ?? e.persons ?? 1) +
      " pessoa(s)";
    function updateNavigation() {
      index = events.findIndex((e) => key(e) === key(current));
      select.replaceChildren(
        ...events.map((e, i) => {
          const o = create("option", label(e));
          o.value = String(i);
          return o;
        }),
      );
      select.value = String(index);
      older.disabled = index <= 0;
      newer.disabled = index < 0 || index >= events.length - 1;
      count.textContent = `${index + 1} de ${events.length} · últimos 7 dias`;
    }
    function cancelVideo() {
      clearTimeout(timer);
      requestController?.abort();
      video.pause();
      video.removeAttribute("src");
      video.load();
      audio.pause();
    }
    async function loadVideo(token) {
      if (closed || token !== generation) return;
      requestController?.abort();
      const controller = new AbortController();
      requestController = controller;
      const deadline = setTimeout(() => controller.abort(), 12000);
      retry.hidden = true;
      try {
        const q = new URLSearchParams({
          foto: current.foto || "",
          hora: current.hora || "",
          formato: format,
        });
        const response = await fetch("/seguranca/evento/video?" + q, {
          signal: controller.signal,
          cache: "no-store",
        });
        const data = await response.json();
        if (closed || token !== generation) return;
        if (response.status === 202) {
          status.textContent =
            data.status === "gravando"
              ? "Gravando este acontecimento. O vídeo ficará pronto após a saída."
              : "Preparando a gravação para reprodução…";
          timer = setTimeout(() => loadVideo(token), 2000);
          return;
        }
        if (!response.ok || !data.url)
          throw Error(data.erro || "Gravação indisponível para este evento.");
        if (!data.url.startsWith("/seguranca/evento/arquivo/"))
          throw Error("Endereço de gravação inválido");
        video.src = data.url;
        video.hidden = false;
        status.textContent = "Carregando vídeo…";
        video.load();
      } catch (e) {
        if (closed || token !== generation) return;
        status.textContent =
          e.name === "AbortError"
            ? "A consulta demorou. Tente novamente."
            : e.message;
        retry.hidden = false;
      } finally {
        clearTimeout(deadline);
      }
    }
    function show(e) {
      generation++;
      cancelVideo();
      current = e;
      clearTimeout(autoClose);
      review.textContent = "";
      title.textContent = e.message || "Pessoa detectada pela câmera";
      zone.textContent = e.zoneName || "Câmera A28";
      details.textContent = label(e);
      img.alt = "Captura de " + new Date(e.hora).toLocaleString("pt-BR");
      img.src = e.foto
        ? "/seguranca/evento/imagem/" + encodeURIComponent(e.foto)
        : "/seguranca/linha/quadro.jpg";
      video.hidden = true;
      status.textContent = "Localizando gravação…";
      updateNavigation();
      loadVideo(generation);
    }
    function move(delta) {
      const next = events[index + delta];
      if (next) show(next);
    }
    older.onclick = () => move(-1);
    newer.onclick = () => move(1);
    select.onchange = () => {
      const e = events[Number(select.value)];
      if (e) show(e);
    };
    retry.onclick = () => {
      clearTimeout(timer);
      video.pause();
      loadVideo(generation);
    };
    video.onloadedmetadata = () => {
      status.textContent = "Pronto para reproduzir";
    };
    video.onerror = () => {
      if (!video.getAttribute("src")) return;
      status.textContent =
        "Não foi possível reproduzir. Tente o formato alternativo.";
      retry.hidden = false;
      format = format === "mp4" ? "webm" : "mp4";
    };
    for (const [text, rating] of [
      ["Detecção correta", "correta"],
      ["Falso alerta", "falso"],
    ]) {
      const b = create("button", text, "btn");
      b.onclick = async () => {
        const selected = current,
          token = generation;
        b.disabled = true;
        try {
          const r = await fetch("/seguranca/eventos/revisar", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              rating,
              eventTime: selected.hora,
              eventType: selected.eventType || selected.event || "person",
              zoneId: selected.zoneId || "",
            }),
            signal: AbortSignal.timeout(10000),
          });
          if (!r.ok) throw Error("Não foi possível salvar a revisão");
          if (token === generation) review.textContent = "Revisão registrada.";
        } catch (e) {
          if (token === generation) review.textContent = e.message;
        } finally {
          b.disabled = false;
        }
      };
      actions.append(b);
    }
    const listen = create("button", "Ouvir aviso", "btn");
    listen.onclick = () =>
      audio.play().catch(() => (review.textContent = "Áudio indisponível"));
    actions.append(listen, review);
    function keyboard(e) {
      if (e.key === "Escape") {
        e.preventDefault();
        panel._close();
        return;
      }
      if (e.key === "Tab") {
        const nodes = [
            ...panel.querySelectorAll("button:not(:disabled),select,video"),
          ].filter((n) => !n.hidden),
          first = nodes[0],
          last = nodes[nodes.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
        return;
      }
      if (e.target.closest("select,input,textarea,video")) return;
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        move(-1);
      }
      if (e.key === "ArrowRight") {
        e.preventDefault();
        move(1);
      }
    }
    panel._close = () => {
      closed = true;
      generation++;
      cancelVideo();
      clearTimeout(autoClose);
      clearTimeout(timeoutHistory);
      historyController.abort();
      panel.removeEventListener("keydown", keyboard);
      panel.remove();
      previousFocus?.focus?.();
    };
    close.onclick = panel._close;
    panel.addEventListener("keydown", keyboard);
    body.append(title, zone, details, media, actions);
    panel.append(head, nav, body);
    document.body.append(panel);
    show(initial);
    close.focus();
    if (!initial.manual) {
      autoClose = setTimeout(panel._close, 30000);
      if (new URLSearchParams(location.search).get("embutido") !== "qt")
        audio.play().catch(() => {});
    }
    fetch("/seguranca/eventos/historico", {
      cache: "no-store",
      signal: historyController.signal,
    })
      .then((r) => {
        if (!r.ok) throw Error();
        return r.json();
      })
      .then((data) => {
        if (closed) return;
        const map = new Map(
          (data.eventos || [])
            .filter((e) => e.foto && e.hora)
            .map((e) => [key(e), e]),
        );
        map.set(key(initial), initial);
        events = [...map.values()].sort(
          (a, b) => new Date(a.hora) - new Date(b.hora),
        );
        updateNavigation();
      })
      .catch(() => {
        if (!closed)
          count.textContent =
            "Histórico indisponível · captura atual preservada";
      })
      .finally(() => clearTimeout(timeoutHistory));
  };
})();
