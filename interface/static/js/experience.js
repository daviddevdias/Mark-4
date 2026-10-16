(() => {
  "use strict";
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    n.className = cls || "";
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const normal = (s) =>
    String(s)
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase();
  function preference() {
    let active = false;
    try {
      active = localStorage.getItem("jarvis-economy") === "true";
    } catch (_) {}
    document.body.classList.toggle("economy-mode", active);
    return active;
  }
  preference();
  window.addEventListener("storage", (e) => {
    if (e.key === "jarvis-economy") preference();
  });
  function settings() {
    const pane = document.getElementById("pane");
    if (
      !pane?.classList.contains("settings-pane") ||
      pane.querySelector(".settings-search")
    )
      return;
    const bar = el("div", "settings-search"),
      input = el("input"),
      clear = el("button", "btn", "Limpar busca"),
      result = el("span", "mac-meta");
    input.type = "search";
    input.placeholder = "Buscar configuração: câmera, Gmail, voz…";
    input.setAttribute("aria-label", "Buscar configurações");
    const empty = el("p", "settings-empty", "Nenhuma configuração encontrada.");
    empty.hidden = true;
    empty.setAttribute("role", "status");
    const controls = el("details", "settings-group"),
      summary = el(
        "summary",
        "settings-group-heading",
        "Aparência e desempenho",
      ),
      label = el("label", "economy-control"),
      check = el("input");
    check.type = "checkbox";
    check.checked = preference();
    label.append(
      check,
      document.createTextNode(
        "Modo econômico · núcleo a 30 FPS e menos atualizações visuais",
      ),
    );
    controls.append(
      summary,
      label,
      el(
        "p",
        "note",
        "A segurança e a escuta continuam ativas. As preferências de movimento reduzido do sistema também são respeitadas.",
      ),
    );
    check.onchange = () => {
      try {
        localStorage.setItem("jarvis-economy", String(check.checked));
      } catch (_) {}
      preference();
    };
    let before = new Map();
    function filter() {
      const query = normal(input.value.trim());
      const groups = [...pane.querySelectorAll(":scope > .settings-group")];
      let count = 0;
      for (const group of groups) {
        const matches = !query || normal(group.textContent).includes(query);
        group.hidden = !matches;
        if (query) {
          if (!before.has(group)) before.set(group, group.open);
          if (matches) group.open = true;
        } else if (before.has(group)) {
          group.open = before.get(group);
          before.delete(group);
        }
        if (matches) count++;
      }
      empty.hidden = count > 0;
      result.textContent = query ? count + " seção(ões) encontrada(s)" : "";
    }
    input.oninput = filter;
    clear.onclick = () => {
      input.value = "";
      filter();
      input.focus();
    };
    bar.append(input, clear, result);
    pane.prepend(bar, empty, controls);
  }
  function decorate() {
    const icons = ["☷", "◇", "▣", "♫", "≡", "⚙"];
    document.querySelectorAll("#tabs button").forEach((b, i) => {
      if (b.querySelector(".nav-icon")) return;
      const icon = el("span", "nav-icon");
      icon.dataset.icon = icons[i] || "•";
      icon.setAttribute("aria-hidden", "true");
      b.prepend(icon);
      b.setAttribute(
        "aria-current",
        b.classList.contains("on") ? "page" : "false",
      );
    });
    settings();
  }
  window.addEventListener("jarvis-pane", () => {
    decorate();
    requestAnimationFrame(decorate);
  });
  let palette = null;
  window.openJarvisQuickActions = () => {
    if (palette) {
      palette.querySelector("input").focus();
      return;
    }
    const dialog = el("dialog", "quick-actions"),
      head = el("header"),
      title = el("strong", "", "Ir para…"),
      close = el("button", "chip", "Fechar"),
      input = el("input"),
      list = el("div", "quick-list");
    dialog.setAttribute("aria-label", "Acesso rápido do Jarvis");
    input.type = "search";
    input.placeholder = "Buscar tela ou ação";
    input.setAttribute("aria-label", "Buscar tela ou ação");
    head.append(title, close);
    dialog.append(head, input, list);
    document.body.append(dialog);
    palette = dialog;
    const actions = [
      ["Dashboard · saúde e processos", () => window.openJarvisDashboard?.()],
      ["Controles · casa, TV e PC", () => window.openJarvisSection?.("ctl")],
      [
        "Segurança · câmera e Torre Stark",
        () => window.openJarvisSection?.("seg"),
      ],
      ["Revisar linha de segurança", () => window.openJarvisSection?.("line")],
      [
        "Pessoal · agenda, e-mails e notas",
        () => window.openJarvisSection?.("org"),
      ],
      ["Comandos de voz", () => window.openJarvisSection?.("cmd")],
      ["Logs · avisos e erros", () => window.openJarvisSection?.("log")],
      ["Configurações e integrações", () => window.openJarvisSection?.("cfg")],
      ["Organizar elementos", () => window.personalizeJarvisScreens?.()],
      ["Meu dia", () => window.openDailyBriefing?.()],
    ];
    function draw() {
      list.replaceChildren();
      for (const [label, action] of actions.filter(([label]) =>
        normal(label).includes(normal(input.value)),
      )) {
        const b = el("button", "quick-item", label);
        b.onclick = () => {
          dialog.close();
          action();
        };
        list.append(b);
      }
      if (!list.children.length)
        list.append(el("p", "mac-meta", "Nenhuma ação encontrada."));
    }
    input.oninput = draw;
    input.onkeydown = (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        list.querySelector("button")?.focus();
      }
      if (e.key === "Enter") {
        e.preventDefault();
        list.querySelector("button")?.click();
      }
    };
    close.onclick = () => dialog.close();
    dialog.addEventListener("close", () => {
      dialog.remove();
      palette = null;
    });
    draw();
    dialog.showModal();
    input.focus();
  };
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      window.openJarvisQuickActions();
    }
    if (
      e.key !== "Tab" ||
      !document.body.classList.contains("cfg") ||
      document.querySelector("dialog[open]")
    )
      return;
    const drawer = document.getElementById("drawer"),
      items = [
        ...drawer.querySelectorAll(
          'button:not([disabled]),a[href],input:not([disabled]),select,textarea,summary,[tabindex="0"]',
        ),
      ].filter((n) => n.getClientRects().length && !n.closest("[hidden]"));
    if (!items.length) return;
    const first = items[0],
      last = items[items.length - 1];
    if (
      e.shiftKey &&
      (document.activeElement === first ||
        !drawer.contains(document.activeElement))
    ) {
      e.preventDefault();
      last.focus();
    } else if (
      !e.shiftKey &&
      (document.activeElement === last ||
        !drawer.contains(document.activeElement))
    ) {
      e.preventDefault();
      first.focus();
    }
  });
  decorate();
})();
