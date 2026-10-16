(() => {
  "use strict";
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const svg = (tag, attrs) => {
    const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    return n;
  };
  // Consulta dados com prazo limitado
  async function api(url, data) {
    const c = new AbortController(),
      t = setTimeout(() => c.abort(), 240000);
    try {
      const r = await fetch(url, {
        signal: c.signal,
        ...(data
          ? {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(data),
            }
          : {}),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.erro || "Não foi possível consultar");
      return d;
    } finally {
      clearTimeout(t);
    }
  }
  const observed = new WeakSet(),
    visibility = new IntersectionObserver(
      (entries) => {
        for (const entry of entries)
          entry.target.classList.toggle(
            "weather-paused",
            !entry.isIntersecting,
          );
      },
      { threshold: 0.05 },
    );
  window.observeJarvisAnimation = (element) => {
    const card = element?.closest(".screen-widget");
    if (card && !observed.has(card)) {
      observed.add(card);
      visibility.observe(card);
    }
  };
  document.addEventListener("visibilitychange", () =>
    document.body.classList.toggle("weather-paused", document.hidden),
  );
  // Organiza texto sem executar HTML
  function mailBody(text) {
    const body = el("div", "mail-body");
    const clean = String(text)
      .replace(/\r\n?/g, "\n")
      .replace(/[-_=]{8,}/g, "\n")
      .replace(/\n[ \t]*\n(?:[ \t]*\n)+/g, "\n\n")
      .trim();
    for (const block of clean.split(/\n\s*\n/)) {
      const p = el("p");
      let offset = 0;
      for (const match of block.matchAll(/https?:\/\/[^\s<>"']+/gi)) {
        p.append(document.createTextNode(block.slice(offset, match.index)));
        const raw = match[0],
          href = raw.replace(/[.,;!?)]+$/g, "");
        try {
          const url = new URL(href),
            host = url.hostname.replace(/^www\./, "");
          const link = el(
            "a",
            "mail-link",
            host === "linkedin.com" || host.endsWith(".linkedin.com")
              ? "Abrir no LinkedIn"
              : "Abrir link · " + host,
          );
          link.href = url.href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.title = "Abrir em " + host;
          p.append(link, document.createTextNode(raw.slice(href.length)));
        } catch (_) {
          p.append(document.createTextNode(raw));
        }
        offset = match.index + raw.length;
      }
      p.append(document.createTextNode(block.slice(offset)));
      body.append(p);
    }
    return body;
  }
  // Mostra email em janela superior
  window.openJarvisEmail = (message) => {
    document.querySelector(".jarvis-card-dialog")?.close();
    const dialog = el("dialog", "jarvis-card-dialog"),
      header = el("header"),
      footer = el("footer", "mail-actions"),
      close = el("button", "mac-btn", "Fechar"),
      content = el("div", "mail-detail"),
      draft = el("textarea", "mail-draft"),
      status = el("p", "card-feedback"),
      generate = el("button", "mac-btn", "Gerar resposta");
    let draftId = null,
      closed = false;
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-label", "Mensagem do Gmail");
    header.append(el("strong", "", "GMAIL · MENSAGEM"), close);
    const metadata = el("div", "mail-metadata"),
      avatar = el(
        "span",
        "mail-avatar",
        (message.from || "E").trim()[0].toLocaleUpperCase("pt-BR"),
      ),
      sender = el("div"),
      date = new Date(message.date);
    sender.append(el("strong", "mail-sender", message.from || "Remetente"));
    if (!Number.isNaN(date.getTime()))
      sender.append(
        el(
          "time",
          "mail-date",
          date.toLocaleString("pt-BR", {
            dateStyle: "long",
            timeStyle: "short",
          }),
        ),
      );
    metadata.append(avatar, sender);
    content.append(
      el("h2", "", message.subject || "Sem assunto"),
      metadata,
      mailBody(message.body || message.snippet || "Sem conteúdo disponível"),
    );
    draft.hidden = true;
    draft.maxLength = 10000;
    draft.setAttribute("aria-label", "Resposta sugerida");
    content.append(draft);
    footer.append(generate, status);
    dialog.append(header, content, footer);
    document.body.append(dialog);
    const copyMessage = el("button", "mac-btn", "Copiar mensagem");
    copyMessage.onclick = () =>
      navigator.clipboard
        .writeText(
          [message.subject, message.body || message.snippet]
            .filter(Boolean)
            .join("\n\n"),
        )
        .then(() => (status.textContent = "Mensagem copiada."))
        .catch(() => (status.textContent = "Não foi possível copiar."));
    footer.append(copyMessage);
    const gmail = el("a", "mail-link", "Abrir no Gmail");
    gmail.href =
      "https://mail.google.com/mail/u/0/#search/" +
      encodeURIComponent(message.subject || "");
    gmail.target = "_blank";
    gmail.rel = "noopener noreferrer";
    footer.append(gmail);
    const saveNote = el("button", "mac-btn", "Salvar como nota");
    footer.append(saveNote);
    saveNote.onclick = async () => {
      saveNote.disabled = true;
      try {
        await api("/memoria/notas", {
          id:
            "email-" +
            String(message.id || Date.now())
              .toLowerCase()
              .replace(/[^a-z0-9-]/g, "")
              .slice(0, 60),
          area: "trabalho",
          title: (message.subject || "E-mail").slice(0, 42),
          body: [
            message.from,
            message.body || message.snippet || "Sem conteúdo",
          ]
            .filter(Boolean)
            .join("\n")
            .slice(0, 1200),
        });
        status.textContent = "Nota salva em Pessoal → Notas.";
      } catch (e) {
        status.textContent = e.message;
        saveNote.disabled = false;
      }
    };
    const remind = el("button", "mac-btn", "Criar lembrete"),
      form = el("form", "mail-reminder"),
      when = el("input"),
      save = el("button", "mac-btn", "Salvar lembrete");
    form.hidden = true;
    when.type = "datetime-local";
    when.required = true;
    when.setAttribute("aria-label", "Data e hora do lembrete");
    save.type = "submit";
    form.append(el("label", "", "Quando lembrar deste e-mail?"), when, save);
    content.append(form);
    footer.append(remind);
    remind.onclick = () => {
      form.hidden = !form.hidden;
      if (!form.hidden) {
        form.scrollIntoView({ block: "nearest" });
        when.focus();
      }
    };
    form.onsubmit = async (e) => {
      e.preventDefault();
      const date = new Date(when.value);
      if (!Number.isFinite(date.getTime()) || date <= new Date()) {
        status.textContent = "Escolha uma data e hora futura.";
        return;
      }
      save.disabled = true;
      try {
        await api("/agenda", {
          titulo: ("Responder: " + (message.subject || "E-mail")).slice(0, 150),
          inicio: date.toISOString(),
          descricao: "E-mail de " + (message.from || "Remetente"),
          antecedencia_minutos: 10,
        });
        status.textContent = "Lembrete salvo na agenda.";
        form.hidden = true;
        remind.disabled = true;
      } catch (e) {
        status.textContent = e.message;
      } finally {
        save.disabled = false;
      }
    };

    close.onclick = () => dialog.close();
    dialog.addEventListener("close", () => {
      closed = true;
      dialog.remove();
      if (draftId)
        fetch("/gmail/rascunho", { method: "DELETE" }).catch(() => {});
    });
    generate.onclick = async () => {
      generate.disabled = true;
      generate.setAttribute("aria-busy", "true");
      status.textContent = "Preparando uma resposta para você revisar…";
      try {
        const d = await api("/gmail/resposta", {
          messageId: message.id,
          body: "",
        });
        draftId = d.id;
        if (closed) {
          fetch("/gmail/rascunho", { method: "DELETE" }).catch(() => {});
          return;
        }
        draft.hidden = false;
        draft.value = d.body || "";
        draft.scrollIntoView({ block: "nearest" });
        status.textContent = "Sugestão pronta. Nenhuma mensagem foi enviada.";
        footer.querySelector(".mail-copy")?.remove();
        const copy = el("button", "mac-btn mail-copy", "Copiar resposta");
        copy.onclick = () =>
          navigator.clipboard
            .writeText(draft.value)
            .then(() => (status.textContent = "Resposta copiada."))
            .catch(
              () => (status.textContent = "Selecione o texto para copiar."),
            );
        footer.append(copy);
      } catch (e) {
        if (!closed) status.textContent = e.message;
      } finally {
        generate.disabled = false;
        generate.removeAttribute("aria-busy");
      }
    };
    dialog.showModal();
  };
  // Atualiza grafico sem animacao
  window.updateJarvisResources = async (box, get) => {
    if (!box) return;
    const d = await get("/interface/recursos", 5000);
    if (!box._telemetry) {
      box.replaceChildren();
      const metrics = el("div", "resource-metrics"),
        values = {};
      for (const [key, label] of [
        ["cpu", "CPU"],
        ["ram", "RAM"],
        ["vram", "VRAM"],
      ]) {
        const cell = el("div"),
          value = el("strong", "", "—");
        cell.append(el("span", "", label), value);
        metrics.append(cell);
        values[key] = value;
      }
      const chart = svg("svg", {
          viewBox: "0 0 300 100",
          preserveAspectRatio: "none",
          class: "resource-chart",
          role: "img",
          "aria-label": "Histórico de uso CPU e RAM",
        }),
        caption = el(
          "div",
          "chart-caption",
          "CPU · azul   RAM · violeta | histórico recente",
        ),
        list = el("div", "resource-processes");
      box.append(metrics, chart, caption, list);
      box._telemetry = { values, chart, list, history: [] };
    }
    const t = box._telemetry;
    t.values.cpu.textContent = Math.round(d.cpu || 0) + "%";
    t.values.ram.textContent = Math.round(d.ram || 0) + "%";
    const gpu = d.gpu;
    t.values.vram.textContent = gpu?.vram_total_mb
      ? Math.round((gpu.vram_usada_mb / gpu.vram_total_mb) * 100) + "%"
      : "—";
    t.values.vram.title = gpu?.vram_total_mb
      ? "Memória de vídeo"
      : "Medição indisponível neste hardware";
    if (d.historico?.length) t.history = d.historico.slice(-60);
    else {
      t.history.push({ cpu: Number(d.cpu) || 0, ram: Number(d.ram) || 0 });
      if (t.history.length > 60) t.history.shift();
    }
    t.chart.replaceChildren();
    for (const y of [10, 35, 60, 85])
      t.chart.append(
        svg("line", {
          x1: 0,
          x2: 300,
          y1: y,
          y2: y,
          stroke: "#29465a",
          "stroke-width": 0.5,
        }),
      );
    for (const [key, color] of [
      ["cpu", "#3dc5ff"],
      ["ram", "#a78bfa"],
    ]) {
      const points = t.history
        .map(
          (p, i) =>
            (i * 300) / Math.max(1, t.history.length - 1) +
            "," +
            (95 - Math.min(100, Math.max(0, p[key])) * 0.85),
        )
        .join(" ");
      t.chart.append(
        svg("polyline", {
          points,
          stroke: color,
          fill: "none",
          "stroke-width": 2,
          "stroke-linejoin": "round",
        }),
      );
    }
    const entries = d.processos || [];
    const sig = JSON.stringify(entries);
    if (t.signature !== sig) {
      t.signature = sig;
      t.list.replaceChildren(el("small", "", "MAIOR CONSUMO AGORA"));
      for (const p of entries.slice(0, 3)) {
        const row = el("div");
        row.append(
          el("span", "", p.nome),
          el("strong", "", p.cpu + "% · " + p.ram_mb + " MB"),
        );
        t.list.append(row);
      }
    }
  };
  // Reune avisos do celular
  window.updateJarvisMobile = async (box, get) => {
    if (!box) return;
    const [d, connection] = await Promise.all([
      get("/pessoal/mensagens/celular", 10000),
      get("/interface/celular", 10000),
    ]);
    const items = Array.isArray(d) ? d : d.mensagens || [];
    const sig = JSON.stringify([items, connection.conectado]);
    if (box.dataset.mobile === sig) return;
    box.dataset.mobile = sig;
    box.replaceChildren(
      el("div", "mobile-count", items.length + " notificações"),
      el(
        "p",
        "mac-meta",
        connection.conectado
          ? "Celular conectado recentemente"
          : "Celular desconectado · exibindo avisos salvos",
      ),
    );
    if (!items.length)
      box.append(
        el(
          "p",
          "mac-meta",
          connection.conectado
            ? "Nenhum aviso recebido. O acesso às notificações deve estar habilitado no Android."
            : "Conecte o Android para receber novos avisos.",
        ),
      );
    for (const m of items.slice(0, 8)) {
      const row = el("article", "mobile-message"),
        date = new Date(m.hora);
      row.append(
        el("strong", "", m.remetente || m.titulo || "Celular"),
        el("p", "", m.texto || "Nova notificação"),
      );
      if (Number.isFinite(date.getTime()))
        row.append(el("time", "mac-meta", date.toLocaleString("pt-BR")));
      box.append(row);
    }
  };
})();
