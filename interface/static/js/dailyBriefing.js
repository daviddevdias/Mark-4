(() => {
  "use strict";
  // Mostra somente nome do remetente
  function senderName(item) {
    let raw = String(item.from || item.fromAddress || "Remetente");
    const match = raw.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i);
    const name = raw
      .replace(/<[^>]*>/g, "")
      .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, "")
      .replace(/["<>]/g, "")
      .replace(/^[\s–—-]+|[\s–—-]+$/g, "");
    return (
      name ||
      (match ? match[0].split("@")[0].replace(/[._]/g, " ") : "Remetente")
    );
  }
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const gmailThreadUrl = (item) => {
    const threadId = String(item?.threadId || "").trim();
    return threadId
      ? `https://mail.google.com/mail/u/0/#all/${encodeURIComponent(threadId)}`
      : "";
  };
  // Reconhece chamada do resumo
  const nomesFortes = [
    "jefferson",
    "jogos de",
    "jar vins",
    "jar vis",
    "charvis",
    "jardims",
    "jardin",
    "jarbis",
    "jarvez",
    "chaves",
    "germes",
    "ja vis",
    "jervis",
    "jarvys",
    "gervis",
    "jarvis",
    "jarves",
    "gerbis",
    "jarbas",
    "javes",
    "jarvi",
    "gerbi",
    "ja vi",
    "chave",
    "javis",
    "james",
    "gerby",
    "jesus",
    "ja",
  ];
  const nomesResumo = nomesFortes
    .map((nome) => nome.replace(/ /g, "\\s+"))
    .join("|");
  const chamadaResumo = new RegExp(
    "^(?:bom dia|boa tarde|boa noite|resumo do dia|resumo da manha|meu resumo|briefing|briefing do dia)(?: (?:" +
      nomesResumo +
      "))?$",
  );
  const matches = (text) => {
    const normal = String(text || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    return chamadaResumo.test(normal);
  };
  // Consulta dados com tempo limitado
  async function request(url, data) {
    const controller = new AbortController(),
      timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(url, {
        signal: controller.signal,
        ...(data
          ? {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(data),
            }
          : {}),
      });
      const result = await response.json();
      if (!response.ok)
        throw new Error(result.erro || "Informação indisponível");
      return result;
    } finally {
      clearTimeout(timer);
    }
  }
  let closeActive = null,
    eventActive = null;
  // Abre cartões do resumo diário
  async function openDaily(options = {}) {
    if (closeActive) return;
    const root = el("section", "daily-briefing");
    root.id = "dailyBriefing";
    root.setAttribute("aria-label", "Resumo do dia");
    const header = el("header", "daily-header"),
      title = el("div", "daily-brand");
    title.append(
      el("span", "", "JARVIS · SEU DIA"),
      el("strong", "", "Resumo pessoal"),
    );
    const actions = el("div", "daily-actions"),
      read = el("button", "chip", "Ouvir resumo"),
      stop = el("button", "chip", "Parar leitura"),
      close = el("button", "chip", "Fechar");
    for (const b of [read, stop, close]) b.type = "button";
    actions.append(read, stop, close);
    header.append(title, actions);
    const stage = el("div", "daily-stage"),
      status = el(
        "p",
        "daily-status",
        "Preparando clima, agenda e assuntos relevantes…",
      ),
      tray = el("nav", "daily-tray");
    tray.setAttribute("aria-label", "Cartões do resumo");
    root.append(header, stage, tray, status);
    document.body.append(root);
    let polling = null;
    let closed = false,
      cards = [],
      current = 0,
      runId = null,
      readingWanted = false,
      starting = false,
      finishedId = null,
      autoRead = options.read !== false;
    // Interrompe somente este resumo
    async function halt() {
      readingWanted = false;
      autoRead = false;
      const stopping = runId;
      if (stopping)
        await request("/briefing/parar", { id: stopping }).catch(() => {});
      if (runId === stopping) {
        finishedId = stopping;
        runId = null;
      }
      status.textContent = "Leitura parada. Os cartões continuam disponíveis.";
    }
    // Fecha cartões e cancela leitura
    function finish() {
      if (closed) return;
      closed = true;
      if (runId) request("/briefing/parar", { id: runId }).catch(() => {});
      readingWanted = false;
      clearInterval(polling);
      root.remove();
      closeActive = null;
      eventActive = null;
      document.removeEventListener("keydown", escape);
    }
    // Fecha resumo pela tecla Escape
    function escape(event) {
      if (event.key === "Escape") finish();
    }
    document.addEventListener("keydown", escape);
    close.onclick = finish;
    stop.onclick = halt;
    closeActive = finish;
    // Mostra o cartão selecionado
    function show(index) {
      current = index;
      const card = cards[index];
      if (!card || closed) return;
      const box = el("article", "daily-card");
      box.append(
        el("span", "daily-kicker", card.title),
        el("h2", "", card.headline),
      );
      if (card.image) {
        const image = el("img", "daily-image");
        image.src = card.image;
        image.alt = card.headline;
        image.referrerPolicy = "no-referrer";
        image.onerror = () => image.remove();
        box.append(image);
      }
      if (card.emailItems?.length) {
        for (const item of card.emailItems) {
          const email = el("article", "daily-email-item"),
            meta = el("div", "daily-email-meta"),
            sender = el(
              "span",
              "daily-email-sender",
              "De: " + senderName(item),
            );
          meta.append(sender);
          if (item.date) {
            const date = new Date(item.date);
            if (!Number.isNaN(date.getTime()))
              meta.append(
                el(
                  "time",
                  "daily-email-date",
                  date.toLocaleString("pt-BR", {
                    day: "2-digit",
                    month: "short",
                    hour: "2-digit",
                    minute: "2-digit",
                  }),
                ),
              );
          }
          const url = gmailThreadUrl(item);
          const subject = item.subject || "Sem assunto";
          if (url) {
            const link = el("a", "daily-email-subject", subject);
            link.href = url;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.setAttribute(
              "aria-label",
              "Abrir e-mail no Gmail: " + subject,
            );
            email.append(meta, link);
          } else
            email.append(meta, el("strong", "daily-email-subject", subject));
          if (item.snippet)
            email.append(el("p", "daily-email-snippet", item.snippet));
          box.append(email);
        }
      } else
        for (const line of card.lines) box.append(el("p", "daily-line", line));
      if (card.detail) {
        const details = el("details", "daily-detail");
        details.append(el("summary", "", "Ver detalhes"));
        for (const text of card.detail) details.append(el("p", "", text));
        box.append(details);
      }
      if (card.note) box.append(el("small", "daily-note", card.note));
      stage.replaceChildren(box);
      [...tray.children].forEach((button, i) => {
        button.classList.toggle("on", i === index);
        button.setAttribute("aria-current", i === index ? "true" : "false");
      });
    }
    // Lê cartões na voz do Jarvis
    async function narrate(startIndex = 0) {
      if (closed || starting || runId) return;
      starting = true;
      readingWanted = true;
      read.disabled = true;
      try {
        const data = await request("/briefing/ler", {
          itens: cards
            .slice(Number.isInteger(startIndex) ? startIndex : 0)
            .filter((c) => c.speech)
            .map((c) => ({
              key: c.key,
              texto: (c.key === "email"
                ? c.speech.replace(
                    /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi,
                    "",
                  )
                : c.speech
              ).slice(0, 3000),
            })),
        });
        if (finishedId === data.id) return;
        runId = data.id;
        if (closed || !readingWanted) {
          await request("/briefing/parar", { id: runId });
          return;
        }
        status.textContent =
          "Preparando a voz. Os cartões acompanham a leitura.";
      } catch (error) {
        if (!closed) status.textContent = error.message;
      } finally {
        starting = false;
        read.disabled = false;
      }
    }
    read.onclick = () => narrate(current);
    read.disabled = true;
    eventActive = (data) => {
      if (
        closed ||
        data.id === finishedId ||
        (runId && data.id !== runId) ||
        (!runId && !starting)
      )
        return;
      if (data.state === "reading") {
        runId = data.id;
        const index = cards.findIndex((c) => c.key === data.key);
        if (index >= 0 && index !== current) show(index);
        status.textContent =
          "Jarvis está apresentando: " + (cards[index]?.title || "seu resumo");
      } else if (data.state === "done") {
        finishedId = data.id;
        runId = null;
        readingWanted = false;
        status.textContent = data.cancelled
          ? "Leitura interrompida. Consulte os cartões abaixo."
          : data.failed
            ? "A leitura não pôde ser concluída. Consulte os cartões abaixo."
            : "";
      }
    };
    const now = new Date(),
      day =
        now.getFullYear() +
        "-" +
        String(now.getMonth() + 1).padStart(2, "0") +
        "-" +
        String(now.getDate()).padStart(2, "0");
    const results = await Promise.allSettled([
      request("/clima"),
      request("/agenda/unificada?limite=100"),
      request("/gmail/status"),
      request("/noticias/g1?categoria=tecnologia"),
      request("/memoria/notas"),
      request("/noticias/g1?categoria=politica"),
    ]);
    if (closed) return;
    const value = (i) =>
      results[i].status === "fulfilled" ? results[i].value : null;
    const weather = value(0),
      agenda = value(1),
      account = value(2),
      news = value(3),
      notes = value(4);
    const num = (v) =>
      typeof v === "number" && Number.isFinite(v)
        ? String(Math.round(v * 10) / 10).replace(".", ",")
        : "—";
    if (weather) {
      const lines = [
        weather.descricao || "",
        `Mínima ${num(weather.minima_dia)}° · Máxima ${num(weather.maxima_dia)}°`,
      ];
      if (typeof weather.chance_chuva_dia_pct === "number")
        lines.push(
          `Chance de chuva hoje: ${num(weather.chance_chuva_dia_pct)}%`,
        );
      cards.push({
        key: "weather",
        title: "Clima",
        headline: `${weather.cidade || "Sua cidade"} · ${num(weather.temperatura)}°`,
        lines,
        speech: `Em ${weather.cidade || "sua cidade"}, a temperatura é de ${num(weather.temperatura)} graus. ${weather.descricao || ""}. ${lines.slice(1).join(". ").replace(/°/g, " graus")}.`,
      });
    } else
      cards.push({
        key: "weather",
        title: "Clima",
        headline: "Previsão indisponível",
        lines: ["Não foi possível consultar o clima agora."],
        speech: "Não consegui consultar o clima agora.",
      });
    const appointments = Array.isArray(agenda) ? agenda : agenda?.compromissos;
    const today = (appointments || []).filter(
      (a) => String(a.inicio || "").slice(0, 10) === day,
    );
    const agendaLines = today
      .slice(0, 4)
      .map(
        (a) =>
          `${a.dia_inteiro ? "Dia inteiro" : String(a.inicio).slice(11, 16)} · ${a.titulo}`,
      );
    const agendaHeadline = agenda
      ? today.length
        ? `${today.length} compromisso(s) hoje`
        : "Seu dia está livre na agenda"
      : "Agenda indisponível";
    cards.push({
      key: "agenda",
      title: "Agenda de hoje",
      headline: agendaHeadline,
      lines: agendaLines.length
        ? agendaLines
        : [
            agenda
              ? "Nenhum compromisso registrado para hoje."
              : "Não foi possível consultar a agenda.",
          ],
      speech: agendaHeadline + ". " + agendaLines.join(". "),
    });
    let messages = null;
    if (account?.conectado) {
      try {
        const inbox = await request("/gmail/mensagens?limite=18");
        messages = Array.isArray(inbox)
          ? inbox
          : Array.isArray(inbox.mensagens)
            ? inbox.mensagens
            : null;
      } catch (_) {}
    }
    if (closed) return;
    const attention = (messages || []).filter((m) => m.needsReply),
      highlights = [
        ...attention,
        ...(messages || []).filter((m) => !m.needsReply),
      ].slice(0, 6),
      mailLines = highlights.map(
        (m) =>
          `${senderName(m)}. Assunto: ${m.subject || "Sem assunto"}. ${String(m.snippet || "").slice(0, 260)}`,
      );
    const mailHeadline = !account?.conectado
      ? "Conecte seu Gmail"
      : messages === null
        ? "Caixa de entrada indisponível"
        : attention.length
          ? `${attention.length} e-mail(s) merecem atenção`
          : messages.length
            ? `${messages.length} e-mail(s) recente(s)`
            : "Sem mensagens recentes";
    const fallbackLine = !account?.conectado
      ? "Configure a conexão na aba pessoal para incluir seus e-mails."
      : messages === null
        ? "Não foi possível carregar a caixa de entrada. Tente novamente."
        : "Nenhuma mensagem recente na caixa de entrada.";
    cards.push({
      key: "email",
      title: "E-mails",
      headline: mailHeadline,
      lines: mailLines.length ? mailLines : [fallbackLine],
      emailItems: highlights,
      note: attention.length
        ? "E-mails sinalizados para resposta aparecem primeiro. Clique no assunto para abrir no Gmail."
        : messages?.length
          ? "Clique no assunto para abrir o e-mail no Gmail."
          : "",
      speech: account?.conectado
        ? messages === null
          ? "Não consegui consultar seus e-mails agora."
          : attention.length
            ? "Há " +
              attention.length +
              " mensagens que podem precisar de resposta. " +
              mailLines.join(". ")
            : messages.length
              ? "Seus e-mails mais recentes. " + mailLines.join(". ")
              : "Não há mensagens recentes na caixa de entrada."
        : "Seu Gmail ainda não está conectado.",
    });
    for (const [key, title, items] of [
      ["news_tech", "Tecnologia", news?.noticias || []],
      [
        "news_ia",
        "Inteligência artificial",
        (news?.noticias || []).filter((n) =>
          /intelig[eê]ncia artificial|\bia\b|openai|chatgpt|gemini|claude/i.test(
            n.titulo + " " + n.resumo,
          ),
        ),
      ],
      ["news_politics", "Política", value(5)?.noticias || []],
    ]) {
      const headlines = items.slice(0, 3);
      cards.push({
        key,
        title: "Notícias · " + title,
        headline: headlines[0]?.titulo || "Sem notícias disponíveis agora",
        lines: headlines.slice(1).map((n) => n.titulo),
        image: headlines[0]?.imagem,
        speech: headlines.length
          ? "Em " +
            title +
            ". " +
            headlines
              .map(
                (n) => n.titulo + ". " + String(n.resumo || "").slice(0, 600),
              )
              .join(". ")
          : "Não há notícias de " + title + " disponíveis agora.",
      });
    }
    const saved = Array.isArray(notes) ? notes : notes?.notas || [];
    cards.push({
      key: "notes",
      title: "Notas e observações",
      headline: !notes
        ? "Notas indisponíveis"
        : saved.length
          ? `${saved.length} nota(s) para consultar`
          : "Nenhuma nota salva",
      lines: saved.slice(0, 3).map((n) => n.title || "Nota"),
      detail: saved.slice(0, 3).map((n) => n.body || n.title),
      speech: saved.length
        ? `Você tem ${saved.length} notas salvas. ` +
          saved
            .slice(0, 4)
            .map(
              (n) =>
                (n.title || "Nota") + ". " + String(n.body || "").slice(0, 350),
            )
            .join(". ")
        : "Notas e observações. Você não tem nenhuma nota salva no momento.",
    });
    cards.forEach((card, index) => {
      const button = el("button", "daily-mini", card.title);
      button.type = "button";
      button.append(el("span", "", card.headline));
      button.onclick = async () => {
        const resume = !!runId;
        await halt();
        show(index);
        if (resume) narrate(index);
      };
      tray.append(button);
    });
    const requestedIndex = cards.findIndex(
      (card) => card.key === options.slide,
    );
    current = requestedIndex < 0 ? 0 : requestedIndex;
    read.disabled = false;
    show(current);
    status.textContent = "Seu resumo está pronto.";
    polling = setInterval(() => {
      if (runId && !closed)
        request("/interface/resumo")
          .then((data) => {
            if (data.id === runId) eventActive?.(data);
          })
          .catch(() => {});
    }, 1200);
    if (autoRead) narrate();
  }
  const previous = window.openBriefingForCommand;
  window.openBriefingForCommand = (text) => {
    if (matches(text)) {
      openDaily();
      return true;
    }
    return previous?.(text) || false;
  };
  window.openDailyBriefing = openDaily;
  window.handleDailyBriefing = (data) => eventActive?.(data);
  window.stopDailyBriefing = () => closeActive?.();
  window.isDailyBriefingOpen = () => !!closeActive;
  window.matchesDailyBriefing = matches;
})();
