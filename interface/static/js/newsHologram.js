(function () {
  "use strict";
  const categories = ["geral", "politica", "economia", "mundo", "tecnologia"];
  const labels = {
    geral: "Destaques",
    politica: "Politica",
    economia: "Economia",
    mundo: "Mundo",
    tecnologia: "Tecnologia",
  };

  // Abre notícias hologram
  function openNewsHologram() {
    document.getElementById("newsHologram")?.remove();
    const panel = document.createElement("section");
    panel.id = "newsHologram";
    panel.className = "news-hologram";
    const header = document.createElement("header");
    const brand = document.createElement("div");
    brand.className = "news-brand";
    const eyebrow = document.createElement("span");
    eyebrow.textContent = "JARVIS INTELLIGENCE";
    const title = document.createElement("strong");
    title.textContent = "Central de notícias";
    brand.append(eyebrow, title);
    const actions = document.createElement("div");
    actions.className = "news-actions";
    const refresh = document.createElement("button");
    refresh.className = "chip";
    refresh.textContent = "Atualizar";
    const close = document.createElement("button");
    close.className = "chip";
    close.textContent = "Fechar";
    actions.append(refresh, close);
    header.append(brand, actions);
    const tabs = document.createElement("nav");
    tabs.className = "news-tabs";
    const content = document.createElement("div");
    content.className = "news-content";
    const status = document.createElement("div");
    status.className = "news-status";
    status.setAttribute("role", "status");
    panel.append(header, tabs, content, status);
    document.body.appendChild(panel);

    let category = "geral";
    let busy = false;
    let closed = false;
    const buttons = new Map();
    // Desenha tabs
    const drawTabs = () => {
      tabs.replaceChildren();
      for (const item of categories) {
        const button = document.createElement("button");
        button.className = "chip" + (category === item ? " on" : "");
        button.textContent = labels[item];
        button.onclick = () => {
          category = item;
          drawTabs();
          loadNews();
        };
        buttons.set(item, button);
        tabs.appendChild(button);
      }
    };
    // Carrega notícias
    const loadNews = async () => {
      if (busy || closed) return;
      busy = true;
      refresh.disabled = true;
      status.textContent = "Buscando manchetes do G1...";
      try {
        const response = await fetch(
          "/noticias/g1?categoria=" + encodeURIComponent(category),
          { cache: "no-store" },
        );
        const data = await response.json();
        if (!response.ok)
          throw new Error(data.erro || "Noticias indisponiveis.");
        content.replaceChildren();
        for (const item of data.noticias || []) {
          const card = document.createElement("article");
          card.className = "news-card";
          const source = document.createElement("span");
          source.className = "news-source";
          source.textContent = item.fonte || "G1";
          const heading = document.createElement("h2");
          heading.textContent = item.titulo || "Sem titulo";
          const summary = document.createElement("p");
          summary.textContent =
            item.resumo || "Abra a materia para ler os detalhes.";
          if (item.imagem) {
            const image = document.createElement("img");
            image.className = "news-card-image";
            image.src = item.imagem;
            image.alt = "Imagem da notícia: " + (item.titulo || "G1");
            image.loading = "lazy";
            image.referrerPolicy = "no-referrer";
            card.appendChild(image);
          }
          const footer = document.createElement("div");
          footer.className = "news-card-footer";
          const date = document.createElement("time");
          date.textContent = item.publicada || "";
          const link = document.createElement("a");
          link.href = item.url;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.textContent = "Ler no G1";
          link.onclick = async (event) => {
            event.preventDefault();
            try {
              const opened = await fetch("/noticias/abrir", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url: item.url }),
              });

              const result = await opened.json().catch(() => ({}));
              if (!opened.ok)
                throw new Error(
                  result.erro || "Não foi possível abrir o navegador.",
                );
              status.textContent =
                "Notícia aberta no navegador padrão deste computador.";
            } catch (error) {
              status.textContent =
                error.message || "Não foi possível abrir o navegador.";
            }
          };
          const listen = document.createElement("button");
          listen.className = "chip news-listen";
          listen.type = "button";
          listen.textContent = "Ouvir resumo";
          listen.onclick = () => {
            if (!("speechSynthesis" in window)) {
              status.textContent =
                "Leitura em voz alta indisponível neste navegador.";
              return;
            }
            speechSynthesis.cancel();
            const utterance = new SpeechSynthesisUtterance(
              [item.titulo, item.resumo].filter(Boolean).join(". "),
            );
            utterance.lang = "pt-BR";
            speechSynthesis.speak(utterance);
          };
          footer.append(date, listen, link);
          card.append(source, heading, summary, footer);
          content.appendChild(card);
        }
        if (!content.children.length) {
          const empty = document.createElement("div");
          empty.className = "news-empty";
          empty.textContent = "O feed não retornou manchetes agora.";
          content.appendChild(empty);
        }
        status.textContent =
          (data.desatualizado
            ? "Exibindo notícias salvas; a fonte está indisponível. "
            : "Fonte: G1 · ") +
          "Atualizado " +
          new Date(data.atualizado).toLocaleTimeString("pt-BR", {
            hour: "2-digit",
            minute: "2-digit",
          });
      } catch (error) {
        content.replaceChildren();
        const empty = document.createElement("div");
        empty.className = "news-empty";
        empty.textContent =
          error.message || "Não foi possível carregar as notícias.";
        content.appendChild(empty);
        status.textContent = "Verifique a conexão e tente atualizar.";
      } finally {
        busy = false;
        refresh.disabled = false;
      }
    };
    // Fecha painel
    const closePanel = () => {
      closed = true;
      document.removeEventListener("keydown", onKey);
      panel.remove();
    };
    // Trata key
    const onKey = (event) => {
      if (event.key === "Escape") closePanel();
    };
    close.onclick = closePanel;
    refresh.onclick = loadNews;
    document.addEventListener("keydown", onKey);
    drawTabs();
    loadNews();
  }

  window.openNewsHologram = openNewsHologram;
  document
    .getElementById("newsQuick")
    ?.addEventListener("click", openNewsHologram);
})();
