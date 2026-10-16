(() => {
  "use strict";
  const keys = ["news", "agenda", "email", "notes"];
  const labels = {
    news: "G1",
    agenda: "Agenda",
    email: "E-mail",
    notes: "Notas",
  };
  const data = {
    news: [],
    agenda: [],
    email: [],
    notes: [],
    emailStatus: null,
  };
  const root = document.createElement("aside");
  root.id = "cornerPanel";
  root.setAttribute("aria-label", "Resumo do Jarvis");
  const head = document.createElement("div");
  head.className = "corner-head";
  const brand = document.createElement("span");
  brand.className = "corner-brand";
  brand.textContent = "JARVIS \u00b7 RESUMO";
  const count = document.createElement("span");
  count.className = "corner-count";
  head.append(brand, count);
  const body = document.createElement("div");
  body.className = "corner-body";
  body.setAttribute("aria-live", "polite");
  const foot = document.createElement("div");
  foot.className = "corner-foot";
  const nav = document.createElement("div");
  nav.className = "corner-nav";
  const actions = document.createElement("div");
  actions.className = "corner-actions";
  const previous = document.createElement("button");
  previous.className = "corner-button";
  previous.type = "button";
  previous.textContent = "\u2039";
  previous.setAttribute("aria-label", "Item anterior");
  const next = document.createElement("button");
  next.className = "corner-button";
  next.type = "button";
  next.textContent = "\u203a";
  next.setAttribute("aria-label", "Pr\u00f3ximo item");
  actions.append(previous, next);
  foot.append(nav, actions);
  root.append(head, body, foot);
  document.body.append(root);
  const defensePanel = document.createElement("section");
  defensePanel.id = "defensePanel";
  defensePanel.setAttribute("aria-labelledby", "defensePanelTitle");
  defensePanel.innerHTML =
    '<div class="defense-panel-copy"><strong id="defensePanelTitle">Protocolo Torre Stark</strong><span id="defensePanelStatus" role="status" aria-live="polite">Consultando estado…</span></div><button class="defense-panel-toggle" id="defensePanelToggle" type="button" aria-pressed="false" disabled>Carregando…</button>';
  document.body.append(defensePanel);
  const recentPanel = document.createElement("section");
  recentPanel.id = "recentSecurityPanel";
  recentPanel.setAttribute("aria-label", "Últimas detecções da câmera");
  recentPanel.innerHTML =
    '<strong class="corner-brand">Últimas detecções</strong><div class="recent-security-list" id="recentSecurityList"><span class="corner-empty">Consultando registros…</span></div>';
  document.body.append(recentPanel);
  let recentSignature = "";

  function drawRecentSecurity(events) {
    const records = (events || []).filter((event) => event.tipo === "pessoa");
    const signature = JSON.stringify(records);
    if (signature === recentSignature) return;
    recentSignature = signature;
    const list = document.getElementById("recentSecurityList");
    list.replaceChildren();
    if (!records.length) {
      list.append(
        node("span", "corner-empty", "Nenhuma pessoa registrada ainda."),
      );
      return;
    }
    records.forEach((record) => {
      const row = node("article", "recent-security-item");
      const photo = node("button", "recent-security-photo");
      photo.type = "button";
      photo.setAttribute("aria-label", "Ver foto da detecção");
      if (record.foto) {
        const image = node("img");
        image.src =
          "/seguranca/evento/imagem/" + encodeURIComponent(record.foto);
        image.alt = "Pessoa detectada";
        image.loading = "lazy";
        image.onerror = () => {
          image.remove();
          photo.textContent = "Foto indisponível";
        };
        photo.append(image);
      } else photo.textContent = "Sem foto";
      const copy = node("div", "recent-security-copy");
      const date = new Date(record.hora);
      copy.append(
        node(
          "span",
          "recent-security-time",
          Number.isNaN(date.getTime())
            ? "Horário indisponível"
            : date.toLocaleString("pt-BR", {
                day: "2-digit",
                month: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
              }),
        ),
        node(
          "span",
          "recent-security-meta",
          String(record.quantidade ?? record.persons ?? 1) + " pessoa(s)",
        ),
      );
      const actions = node("div", "recent-security-actions");

      const open = (focus) => {
        window.openSecurityEvent?.({
          ...record,
          event: "person",
          eventType: "person",
          zoneName: "Câmera inferior",
          manual: true,
        });
        document
          .querySelector(
            focus === "video"
              ? "#securityEventHologram .securityEvent-media-item:last-child"
              : "#securityEventHologram .securityEvent-media-item",
          )
          ?.scrollIntoView({ block: "nearest" });
      };
      photo.onclick = () => open("photo");
      [
        ["Gravação", "video"],
        ["Abrir alerta", "photo"],
      ].forEach(([label, focus]) => {
        const button = node("button", "corner-button", label);
        button.type = "button";
        button.onclick = () => open(focus);
        actions.append(button);
      });
      copy.append(actions);
      row.append(photo, copy);
      list.append(row);
    });
    positionDefensePanel();
  }

  let current = 0;
  let alertUntil = 0;
  let alertTimer = 0;
  let rotation = 0;
  let refreshTimer = 0;
  let securityTimer = 0;
  let audio = null;
  let audioUrl = "";
  let lastAlertAt = 0;
  let lastEventKey = "";
  const notifiedEvents = new Set();
  let defenseBusy = false;
  const tempoRotacao = 50000;

  // Posiciona defense painel
  function positionDefensePanel() {
    if (!root.getClientRects().length) return;
    const rect = root.getBoundingClientRect();
    defensePanel.style.top = Math.round(rect.bottom + 12) + "px";
    defensePanel.style.left = Math.round(rect.left) + "px";
    defensePanel.style.width = Math.round(rect.width) + "px";
    recentPanel.style.top =
      Math.round(defensePanel.getBoundingClientRect().bottom + 12) + "px";
    recentPanel.style.left = Math.round(rect.left) + "px";
    recentPanel.style.width = Math.round(rect.width) + "px";
  }

  // Atualiza defense painel
  async function updateDefensePanel() {
    if (document.hidden || defenseBusy || !defensePanel.getClientRects().length)
      return;
    const button = document.getElementById("defensePanelToggle");
    const status = document.getElementById("defensePanelStatus");
    try {
      const state = await request("/seguranca/estado", { cache: "no-store" });
      const active = !!state.ativa;
      const armed = !!state.armado;
      button.textContent = active
        ? armed
          ? "Desativar defesas"
          : "Ativar defesas"
        : "Ativar e armar Torre Stark";
      button.disabled = false;
      button.setAttribute("aria-pressed", String(armed));
      button.classList.toggle("is-armed", active && armed);
      status.textContent = !active
        ? "Protocolo desativado"
        : armed
          ? "Defesas ativas"
          : "Defesas desativadas";
    } catch (error) {
      button.disabled = true;
      button.textContent = "Estado indisponível";
      status.textContent =
        error.message || "Não foi possível consultar as defesas.";
    }
  }

  defensePanel.querySelector("#defensePanelToggle").onclick = async () => {
    if (defenseBusy) return;
    defenseBusy = true;
    const button = document.getElementById("defensePanelToggle");
    const status = document.getElementById("defensePanelStatus");
    button.disabled = true;
    let operationError = "";
    try {
      const state = await request("/seguranca/estado", { cache: "no-store" });
      await request(
        state.armado ? "/seguranca/desarmar" : "/seguranca/armar",
        { method: "POST" },
      );
    } catch (error) {
      operationError = error.message || "Não foi possível alterar as defesas.";
    } finally {
      defenseBusy = false;
    }
    await updateDefensePanel();
    if (operationError) status.textContent = operationError;
  };
  positionDefensePanel();
  window.addEventListener("resize", positionDefensePanel);
  window.addEventListener("scroll", positionDefensePanel, true);
  document.addEventListener("visibilitychange", () => {
    positionDefensePanel();
    updateDefensePanel();
  });
  setInterval(updateDefensePanel, 5000);
  updateDefensePanel();

  // Cria elemento da interface
  function node(tag, className, text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined) item.textContent = text;
    return item;
  }

  // Consulta o servidor local
  async function request(url, options) {
    const response = await fetch(url, options || {});

    const result = await response.json().catch(() => ({}));
    if (!response.ok)
      throw new Error(result.erro || "Informa\u00e7\u00e3o indispon\u00edvel.");
    return result;
  }

  // Desenha nav
  function drawNav() {
    nav.replaceChildren();
    keys.forEach((key, index) => {
      const dot = node(
        "button",
        "corner-dot" + (index === current ? " on" : ""),
      );
      dot.type = "button";
      dot.setAttribute("aria-label", "Mostrar " + labels[key]);
      dot.onclick = () => show(index, true);
      nav.append(dot);
    });
  }

  // Agenda rotacao
  function agendarRotacao() {
    clearInterval(rotation);
    rotation = 0;
    if (
      document.hidden ||
      document.body.classList.contains("cfg") ||
      Date.now() < alertUntil ||
      audio
    )
      return;

    rotation = setInterval(() => show(current + 1, false), tempoRotacao);
  }

  // Desenha notícias
  function drawNews() {
    const item = data.news[0];
    if (!item) {
      body.append(
        node(
          "p",
          "corner-empty",
          "Not\u00edcias do G1 indispon\u00edveis agora.",
        ),
      );
      return;
    }
    const card = node("div", "corner-news");
    if (item.imagem) {
      const image = node("img", "corner-image");
      image.src = item.imagem;
      image.alt = "Imagem da not\u00edcia";
      image.referrerPolicy = "no-referrer";
      image.onerror = () => image.remove();
      card.append(image);
    }
    const copy = node("div", "corner-copy");
    copy.append(
      node("span", "corner-source", item.fonte || "G1"),
      node("strong", "corner-title", item.titulo || "Not\u00edcia do G1"),
      node(
        "span",
        "corner-summary",
        item.resumo || "Sem resumo dispon\u00edvel.",
      ),
    );
    card.append(copy);
    body.append(card);
    const listen = node("button", "corner-button corner-listen", "Ouvir");
    listen.type = "button";
    listen.onclick = () =>
      ouvirPiper([item.titulo, item.resumo].filter(Boolean).join(". "), listen);
    actions.insertBefore(listen, next);
  }

  // Desenha agenda
  function drawAgenda() {
    const now = Date.now();

    const upcoming = data.agenda
      .filter((item) => !item.inicio || new Date(item.inicio).getTime() >= now)
      .slice(0, 3);
    if (!upcoming.length) {
      body.append(node("p", "corner-empty", "Sua agenda est\u00e1 vazia."));
      return;
    }
    const list = node("div", "corner-list");
    upcoming.forEach((item) => {
      let when = "";
      if (item.inicio)
        when = new Date(item.inicio).toLocaleString("pt-BR", {
          weekday: "short",
          hour: "2-digit",
          minute: "2-digit",
          day: "2-digit",
          month: "2-digit",
        });
      list.append(
        node(
          "div",
          "corner-item",
          [when, item.titulo].filter(Boolean).join(" \u00b7 "),
        ),
      );
    });
    body.append(list);
  }

  // Desenha e-mail
  function drawEmail() {
    if (!data.emailStatus?.conectado) {
      body.append(
        node("p", "corner-empty", "Gmail n\u00e3o est\u00e1 conectado."),
      );
      return;
    }

    const messages = data.email.filter((item) => item.needsReply);
    if (!messages.length) {
      body.append(
        node("p", "corner-empty", "Sem e-mails que pe\u00e7am resposta."),
      );
      return;
    }
    const list = node("div", "corner-list");
    messages
      .slice(0, 3)
      .forEach((item) =>
        list.append(
          node(
            "div",
            "corner-item",
            [item.from, item.subject || "Sem assunto"]
              .filter(Boolean)
              .join(" \u00b7 "),
          ),
        ),
      );
    body.append(list);
  }

  // Desenha notas
  function drawNotes() {
    if (!data.notes.length) {
      body.append(
        node("p", "corner-empty", "Ainda n\u00e3o h\u00e1 notas salvas."),
      );
      return;
    }
    const list = node("div", "corner-list");
    data.notes
      .slice(0, 3)
      .forEach((item) =>
        list.append(
          node(
            "div",
            "corner-item",
            [item.title, item.body].filter(Boolean).join(" \u00b7 "),
          ),
        ),
      );
    body.append(list);
  }

  function show(index, manual) {
    if (Date.now() < alertUntil) return;
    clearInterval(rotation);
    rotation = 0;
    current = (index + keys.length) % keys.length;
    drawNav();
    count.textContent =
      labels[keys[current]] + " \u00b7 " + (current + 1) + "/4";
    body.replaceChildren();
    actions.replaceChildren(previous, next);
    if (keys[current] === "news") drawNews();
    if (keys[current] === "agenda") drawAgenda();
    if (keys[current] === "email") drawEmail();
    if (keys[current] === "notes") drawNotes();
    agendarRotacao();
  }

  async function ouvirPiper(text, button) {
    if (!text) return;
    button.disabled = true;
    button.textContent = "Preparando voz";
    clearInterval(rotation);
    try {
      const response = await fetch("/voz/sintetizar-piper", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ texto: text }),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(result.erro || "Voz Piper indispon\u00edvel.");
      }
      if (audio) stopAudio();
      audioUrl = URL.createObjectURL(await response.blob());
      audio = new Audio(audioUrl);
      audio.onended = () => {
        stopAudio();
        button.disabled = false;
        button.textContent = "Ouvir";
        agendarRotacao();
      };
      await audio.play();
      button.textContent = "Ouvindo";
    } catch (error) {
      button.textContent = "Tentar ouvir";
      button.disabled = false;
      count.textContent = error.message || "Falha na leitura Piper.";
      agendarRotacao();
    }
  }

  // Para áudio
  function stopAudio() {
    if (audio) {
      audio.pause();
      audio.currentTime = 0;
    }
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    audio = null;
    audioUrl = "";
  }

  // Desenha alert
  function drawAlert(event) {
    stopAudio();
    clearInterval(rotation);
    clearTimeout(alertTimer);
    body.replaceChildren();
    actions.replaceChildren();
    const card = node("div", "corner-alert");
    card.append(
      node("span", "corner-alert-label", "ALERTA DE SEGURAN\u00c7A"),
      node(
        "strong",
        "corner-alert-title",
        "Pessoa detectada na \u00e1rea monitorada",
      ),
    );
    const quantity = Number(event.persons || event.quantidade || 1);
    card.append(
      node(
        "span",
        "corner-alert-meta",
        (event.zoneName || "C\u00e2mera inferior") +
          " \u00b7 " +
          quantity +
          (quantity === 1 ? " pessoa" : " pessoas"),
      ),
    );
    body.append(card);
    count.textContent = "ATEN\u00c7\u00c3O \u00b7 Torre Stark";
    const open = node(
      "button",
      "corner-button corner-alert-button",
      "Ver seguran\u00e7a",
    );
    open.onclick = () => {
      document.getElementById("settingsOpen")?.click();
      setTimeout(
        () =>
          Array.from(document.querySelectorAll(".tabs button"))
            .find((button) => button.textContent.trim() === "Seguran\u00e7a")
            ?.click(),
        100,
      );
    };
    actions.append(open);

    alertTimer = setTimeout(
      () => {
        alertUntil = 0;
        show(current, false);
      },
      Math.max(1000, alertUntil - Date.now()),
    );
  }

  // Notifica corner alert
  window.notifyCornerAlert = (event) => {
    if (!event || event.alertAllowed === false) return;
    const type = String(
      event.eventType || event.event || event.tipo || "",
    ).toLocaleLowerCase("pt-BR");
    if (
      !(
        type.includes("person") ||
        type.includes("pessoa") ||
        Number(event.persons || event.quantidade || 0) > 0
      )
    )
      return;
    const key = String(event.eventId || event.foto || event.hora || "");
    if (key && notifiedEvents.has(key)) return;
    if (Date.now() - lastAlertAt < 4500) return;
    lastEventKey = key;
    if (key) notifiedEvents.add(key);
    if (notifiedEvents.size > 100)
      notifiedEvents.delete(notifiedEvents.values().next().value);
    lastAlertAt = Date.now();
    alertUntil = Date.now() + 30000;
    drawAlert(event);
    if (event.abrirTela !== false) window.openSecurityEvent?.(event);
  };

  previous.onclick = () => show(current - 1, true);
  next.onclick = () => show(current + 1, true);

  let refreshing = false;

  async function refresh() {
    if (document.hidden || refreshing || !root.getClientRects().length) return;
    refreshing = true;
    try {
      const results = await Promise.allSettled([
        request("/noticias/g1?categoria=geral"),
        request("/agenda?limite=100"),
        request("/gmail/status"),
        request("/memoria/notas"),
      ]);
      data.news =
        results[0].status === "fulfilled"
          ? results[0].value.noticias || []
          : [];
      data.agenda =
        results[1].status === "fulfilled" && Array.isArray(results[1].value)
          ? results[1].value
          : [];
      data.emailStatus =
        results[2].status === "fulfilled" ? results[2].value : null;
      data.notes =
        results[3].status === "fulfilled" && Array.isArray(results[3].value)
          ? results[3].value
          : [];
      if (data.emailStatus?.conectado) {
        try {
          const result = await request("/gmail/mensagens?limite=18");
          data.email = result.mensagens || [];
        } catch (error) {
          data.email = [];
        }
      } else data.email = [];
      if (Date.now() >= alertUntil) show(current, false);
    } finally {
      refreshing = false;
    }
  }

  let securityBusy = false;

  async function pollSecurity() {
    if (document.hidden || securityBusy) return;
    securityBusy = true;
    try {
      const state = await request("/seguranca/estado");
      const history = await request("/seguranca/deteccoes/hoje", {
        cache: "no-store",
      });
      drawRecentSecurity(history.eventos);
      const latest = state.eventos?.[0];
      if (
        latest &&
        latest.tipo === "pessoa" &&
        latest.armado &&
        Date.now() - new Date(latest.hora).getTime() < 30000
      ) {
        const key = latest.hora || latest.timestamp || "";
        if (key && key !== lastEventKey)
          window.notifyCornerAlert({
            ...latest,
            event: "person",
            eventType: "person",
            zoneName: "C\u00e2mera inferior",
            alertAllowed: true,
          });
      }
    } catch (error) {
    } finally {
      securityBusy = false;
    }
  }

  show(current, false);
  refresh();
  refreshTimer = setInterval(refresh, 60000);
  pollSecurity();
  securityTimer = setInterval(pollSecurity, 2500);
  window.addEventListener(
    "beforeunload",
    () => {
      clearInterval(rotation);
      clearInterval(refreshTimer);
      clearInterval(securityTimer);
      stopAudio();
    },
    { once: true },
  );

  const observarConfiguracao = new MutationObserver(() => {
    agendarRotacao();
    positionDefensePanel();
  });
  observarConfiguracao.observe(document.body, {
    attributes: true,
    attributeFilter: ["class"],
  });
  document.addEventListener("visibilitychange", agendarRotacao);
})();
