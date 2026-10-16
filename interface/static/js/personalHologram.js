(function () {
  "use strict";

  // Cria elemento da interface
  function node(tag, className, text) {
    const item = document.createElement(tag);

    if (className) item.className = className;

    if (text !== undefined) item.textContent = text;

    return item;
  }

  // Monta seção da interface
  function section(parent, title, description) {
    parent.append(node("div", "sec", title));

    if (description) parent.append(node("p", "org-note", description));
  }

  // Consulta o servidor local
  async function request(url, options) {
    const response = await fetch(url, options || {});

    const data = await response.json().catch(() => ({}));

    if (!response.ok)
      throw new Error(data.erro || "Nao foi possivel concluir a acao.");

    return data;
  }

  // Organiza informações pessoais
  function paneOrg(root) {
    root.classList.add("personal-pane");
    const nav = node("div", "org-tabs");

    const view = node("div", "org-view");

    root.replaceChildren(nav, view);

    const entries = [
      ["agenda", "Agenda"],
      ["email", "Gmail"],
      ["notes", "Notas"],
      ["news", "Notícias"],
      ["whatsapp", "WhatsApp"],
      ["memory", "Memória"],
    ];

    let active = "agenda";

    const buttons = new Map();

    const status = node("div", "org-status");

    function setStatus(message, bad) {
      status.textContent = message || "";
      status.classList.toggle("bad", !!bad);
    }

    // Exibe agenda
    async function showAgenda() {
      view.replaceChildren();

      const heading = node("div", "org-agenda-heading");
      heading.append(
        node("h2", "org-agenda-title", "Agenda"),
        node(
          "p",
          "org-note",
          "Organize seus próximos compromissos. Eles ficam salvos neste computador.",
        ),
      );

      const layout = node("div", "org-agenda-layout");
      const formCard = node("details", "org-agenda-card org-agenda-create");
      formCard.append(
        node("summary", "org-create-toggle", "+ Novo compromisso"),
      );
      formCard.append(
        node("div", "org-agenda-card-title", "Novo compromisso"),
        node("p", "org-note", "Preencha o título, o dia e o horário."),
      );

      const form = node("form", "org-form org-agenda-form");
      const title = node("input", "org-input");
      title.maxLength = 120;
      title.required = true;
      title.placeholder = "Ex.: Consulta médica";
      const titleLabel = node("label", "org-agenda-field");
      titleLabel.append(node("span", "", "Nome do compromisso"), title);

      const date = node("input", "org-input");
      date.type = "date";
      date.required = true;
      const dateLabel = node("label", "org-agenda-field");
      dateLabel.append(node("span", "", "Data"), date);

      const time = node("input", "org-input");
      time.type = "time";
      time.required = true;
      const timeLabel = node("label", "org-agenda-field");
      timeLabel.append(node("span", "", "Horário"), time);
      const when = node("div", "org-agenda-when");
      when.append(dateLabel, timeLabel);

      const details = node("textarea", "org-input org-area");
      details.placeholder = "Informações adicionais (opcional)";
      details.maxLength = 1200;
      const detailsLabel = node("label", "org-agenda-field");
      detailsLabel.append(node("span", "", "Detalhes"), details);

      const save = node("button", "btn org-submit", "Salvar compromisso");
      save.type = "submit";
      form.append(titleLabel, when, detailsLabel, save);
      formCard.append(form);

      const listCard = node("section", "org-agenda-card org-agenda-upcoming");
      const listHeading = node("div", "org-agenda-list-heading");
      const listHeadingCopy = node("div", "org-agenda-list-heading-copy");
      listHeadingCopy.append(
        node("div", "org-agenda-card-title", "Próximos compromissos"),
        node("p", "org-note", "Seus horários organizados em ordem."),
      );
      const refresh = node("button", "chip org-agenda-refresh", "Atualizar");
      refresh.type = "button";
      listHeading.append(listHeadingCopy, refresh);
      const list = node("div", "org-list org-agenda-list");
      listCard.append(listHeading, list);

      layout.append(listCard, formCard);
      view.append(heading, status, layout);

      // Carrega os dados da interface
      async function load() {
        try {
          const items = await request("/agenda?limite=100");
          list.replaceChildren();
          if (!items.length) {
            const empty = node("div", "org-agenda-empty");
            empty.append(
              node("span", "org-agenda-empty-icon", "✓"),
              node("strong", "", "Tudo em dia"),
              node("p", "org-note", "Nenhum compromisso marcado."),
            );
            list.append(empty);
            return;
          }
          for (const item of items) {
            const card = node("article", "org-card org-agenda-item");
            const text = node("div", "org-card-copy");
            const moment = new Date(item.inicio);
            const validMoment = !Number.isNaN(moment.getTime());
            const dateText = validMoment
              ? moment.toLocaleDateString("pt-BR", {
                  weekday: "short",
                  day: "2-digit",
                  month: "long",
                  year: "numeric",
                })
              : item.inicio;
            const metadata = node("div", "org-agenda-metadata");
            metadata.append(node("span", "org-agenda-date", dateText));
            if (validMoment) {
              metadata.append(
                node(
                  "span",
                  "org-agenda-time",
                  moment.toLocaleTimeString("pt-BR", {
                    hour: "2-digit",
                    minute: "2-digit",
                  }),
                ),
              );
            }
            text.append(node("strong", "", item.titulo), metadata);
            if (item.descricao)
              text.append(node("p", "org-note", item.descricao));
            const remove = node("button", "chip org-delete", "Excluir");
            remove.type = "button";
            remove.onclick = async () => {
              try {
                await request("/agenda/" + item.id, { method: "DELETE" });
                setStatus("Compromisso removido.");
                await load();
              } catch (error) {
                setStatus(error.message, true);
              }
            };
            card.append(text, remove);
            list.append(card);
          }
        } catch (error) {
          setStatus(error.message, true);
        }
      }

      refresh.onclick = load;
      form.onsubmit = async (event) => {
        event.preventDefault();
        try {
          await request("/agenda", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              titulo: title.value.trim(),
              inicio: date.value + "T" + time.value,
              descricao: details.value.trim(),
              antecedencia_minutos: 10,
            }),
          });
          form.reset();
          setStatus("Compromisso salvo.");
          await load();
        } catch (error) {
          setStatus(error.message, true);
        }
      };
      await load();
    }
    // Exibe notas
    async function showNotes() {
      view.replaceChildren();

      section(view, "Notas", "Salve notas aqui ou dite ao Jarvis: anote ...");

      const form = node("form", "org-form");

      const title = node("input", "org-input");
      title.placeholder = "Titulo";
      title.maxLength = 42;
      title.required = true;

      const area = node("select", "org-input");

      for (const [value, label] of [
        ["metas", "Metas"],
        ["trabalho", "Trabalho"],
        ["projetos", "Projetos"],
        ["financas", "Financas"],
        ["aprendizado", "Aprendizado"],
        ["saude", "Saude"],
        ["relacoes", "Relacoes"],
        ["meta", "Geral"],
      ]) {
        const option = node("option", "", label);
        option.value = value;
        area.append(option);
      }

      const body = node("textarea", "org-input org-area");
      body.placeholder = "Escreva sua nota";
      body.maxLength = 1200;
      body.required = true;

      const save = node("button", "btn org-submit", "Salvar nota");
      save.type = "submit";
      form.append(title, area, body, save);

      const create = node("details", "org-note-create");
      create.append(node("summary", "org-create-toggle", "+ Nova nota"), form);
      const list = node("div", "org-list");
      view.append(create, status, node("div", "sec", "Minhas notas"), list);

      // Carrega os dados da interface
      async function load() {
        try {
          const items = await request("/memoria/notas");
          list.replaceChildren();

          if (!items.length) {
            list.append(node("p", "org-note", "Ainda nao ha notas salvas."));
            return;
          }

          for (const item of items) {
            const card = node("article", "org-card");
            const text = node("div", "org-card-copy");

            text.append(
              node("strong", "", item.title),
              node("span", "", item.area),
              node("p", "org-note", item.body),
            );

            const remove = node("button", "chip org-delete", "Excluir");

            remove.onclick = async () => {
              try {
                await request("/memoria/notas/" + encodeURIComponent(item.id), {
                  method: "DELETE",
                });
                setStatus("Nota removida.");
                await load();
              } catch (error) {
                setStatus(error.message, true);
              }
            };

            card.append(text, remove);
            list.append(card);
          }
        } catch (error) {
          setStatus(error.message, true);
        }
      }

      form.onsubmit = async (event) => {
        event.preventDefault();
        const id =
          "nota-" +
          (crypto.randomUUID
            ? crypto.randomUUID().replaceAll("-", "")
            : Date.now().toString(36));

        try {
          await request("/memoria/notas", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              id,
              area: area.value,
              title: title.value.trim(),
              body: body.value.trim(),
            }),
          });

          form.reset();
          setStatus("Nota salva.");
          await load();
        } catch (error) {
          setStatus(error.message, true);
        }
      };

      await load();
    }

    // Exibe e-mail
    function showEmail() {
      view.replaceChildren();
      section(
        view,
        "Gmail",
        "O Jarvis destaca mensagens que podem precisar de resposta. Revise a mensagem e o texto sugerido; o envio exige sua confirmação.",
      );
      const toolbar = node("div", "org-email-toolbar");
      const account = node("span", "org-note", "Consultando conta Gmail…");
      const refresh = node("button", "btn", "Atualizar caixa de entrada");
      const list = node("div", "org-list");
      const draftHost = node("div", "org-draft-host");
      view.append(toolbar, status, list, draftHost);
      let draftId = "",
        draftSending = false;

      const forgetDraft = () => {
        window.confirmGmailDraft = null;
        draftId = "";
      };

      function manualEditor(messageId, host) {
        host.replaceChildren();
        const form = node("form", "org-form org-manual-reply");
        const body = node("textarea", "org-input org-area");
        body.placeholder = "Escreva sua resposta";
        body.maxLength = 10000;
        body.required = true;
        const prepare = node("button", "btn org-submit", "Revisar resposta");
        prepare.type = "submit";
        form.append(body, prepare);
        host.append(form);
        form.onsubmit = async (event) => {
          event.preventDefault();
          prepare.disabled = true;
          try {
            await prepareDraft(messageId, body.value, host);
          } catch (error) {
            setStatus(error.message, true);
            prepare.disabled = false;
          }
        };
      }
      // Prepara rascunho
      async function prepareDraft(messageId, body, host) {
        const data = await request("/gmail/resposta", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messageId, body: body || "" }),
        });
        draftId = data.id;
        draftSending = false;
        host.replaceChildren();
        const card = node("section", "org-email-draft");
        section(
          card,
          "Revise antes de enviar",
          "O e-mail ainda não foi enviado. Você pode editar o texto antes da confirmação.",
        );
        card.append(
          node("div", "org-draft-recipient", "Para: " + data.to),
          node("div", "org-draft-subject", "Assunto: " + data.subject),
        );
        if (data.originalFrom)
          card.append(
            node("div", "org-note", "Resposta para: " + data.originalFrom),
          );
        const text = node("textarea", "org-input org-area");
        text.value = data.body;
        text.maxLength = 10000;
        text.setAttribute("aria-label", "Texto da resposta");
        const actions = node("div", "org-email-actions");
        const send = node("button", "btn org-submit", "Confirmar e enviar");
        send.type = "button";
        const cancel = node("button", "chip org-delete", "Cancelar rascunho");
        cancel.type = "button";
        actions.append(send, cancel);
        card.append(text, actions);
        host.append(card);

        async function confirmSend() {
          if (!draftId || draftSending) return;
          draftSending = true;
          send.disabled = true;
          try {
            await request("/gmail/resposta", {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ id: draftId, body: text.value }),
            });
            const result = await request("/gmail/enviar", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ id: draftId }),
            });
            setStatus(result.mensagem);
            forgetDraft();
            host.replaceChildren();
            await load();
          } catch (error) {
            setStatus(error.message, true);
            draftSending = false;
            send.disabled = false;
          }
        }
        send.onclick = confirmSend;
        cancel.onclick = async () => {
          await fetch("/gmail/rascunho", { method: "DELETE" }).catch(() => {});
          forgetDraft();
          host.replaceChildren();
          setStatus("Rascunho cancelado.");
        };
        window.confirmGmailDraft = confirmSend;
        setStatus(
          "Rascunho aberto para " +
            data.to +
            ". Confirme somente depois de revisar o texto.",
        );
      }
      // Carrega os dados da interface
      async function load() {
        list.replaceChildren();
        draftHost.replaceChildren();
        forgetDraft();
        try {
          const stateData = await request("/gmail/status");
          if (!stateData.conectado) {
            account.textContent = "Gmail não conectado";

            const connect = node(
              "button",
              "btn org-submit",
              "Configurar conexão Gmail",
            );
            connect.onclick = () =>
              document.getElementById("settingsOpen")?.click();
            list.append(
              node(
                "p",
                "org-note",
                "Configure o cliente OAuth em Configurações e conecte sua conta Google para o Jarvis ler a caixa de entrada.",
              ),
              connect,
            );
            return;
          }
          account.textContent = stateData.email || "Conta conectada";
          const data = await request("/gmail/mensagens?limite=18");
          const messages = data.mensagens || [];
          if (!messages.length) {
            list.append(
              node(
                "p",
                "org-note",
                "Não há mensagens recentes na caixa de entrada.",
              ),
            );
            return;
          }
          for (const message of messages) {
            const card = node("article", "org-card org-email-card");
            const copy = node("div", "org-card-copy");
            copy.append(
              node("strong", "", message.subject || "(sem assunto)"),
              node(
                "span",
                "",
                [message.from, message.date].filter(Boolean).join(" · "),
              ),
              node(
                "p",
                "org-note",
                message.snippet || message.body || "Sem prévia.",
              ),
            );
            if (message.needsReply)
              copy.append(
                node("span", "org-email-badge", "Pode precisar de resposta"),
              );
            const actions = node("div", "org-email-actions");

            const read = node("button", "chip", "Ler mensagem");
            read.onclick = () => {
              if (!window.speechSynthesis)
                return setStatus(
                  "Leitura em voz alta indisponível neste navegador.",
                  true,
                );
              speechSynthesis.cancel();
              const utterance = new SpeechSynthesisUtterance(
                [message.from, message.subject, message.body]
                  .filter(Boolean)
                  .join(". "),
              );
              utterance.lang = "pt-BR";
              speechSynthesis.speak(utterance);
            };

            const draft = node("button", "btn", "Gerar resposta");
            draft.onclick = async () => {
              draft.disabled = true;
              try {
                await prepareDraft(message.id, "", draftHost);
              } catch (error) {
                setStatus(error.message, true);
                if (
                  !String(error.message || "")
                    .toLocaleLowerCase("pt-BR")
                    .includes("rascunho aberto")
                )
                  manualEditor(message.id, draftHost);
              } finally {
                draft.disabled = false;
              }
            };

            const write = node("button", "chip", "Escrever resposta");
            write.onclick = () => manualEditor(message.id, draftHost);
            actions.append(read, draft, write);
            card.append(copy, actions);
            list.append(card);
          }
        } catch (error) {
          account.textContent = "Gmail indisponível";
          list.append(
            node(
              "p",
              "org-note",
              error.message || "Não foi possível carregar a caixa de entrada.",
            ),
          );
        }
      }
      toolbar.append(account, refresh);
      refresh.onclick = load;
      window.refreshPersonalEmail = load;
      load();
    }
    // Exibe notícias
    async function showNews() {
      view.replaceChildren();
      section(view, "Notícias", "Escolha um assunto.");
      const categories = node("div", "org-tabs");
      const list = node("div", "org-list");
      view.append(categories, list);
      let generation = 0;
      // Carrega os dados da interface
      async function load(category) {
        const current = ++generation;
        list.textContent = "Carregando…";
        try {
          const data = await request("/noticias/g1?categoria=" + category);
          if (current !== generation) return;
          list.replaceChildren();
          for (const item of data.noticias || []) {
            const card = node("article", "org-card");
            const copy = node("div", "org-card-copy");
            copy.append(
              node("strong", "", item.titulo),
              node("p", "org-note", item.resumo),
            );
            const open = node("button", "chip", "Ler matéria");
            open.onclick = async () => {
              try {
                await request("/noticias/abrir", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ url: item.url }),
                });
              } catch (error) {
                setStatus(error.message, true);
              }
            };
            card.append(copy, open);
            list.append(card);
          }
          if (!list.children.length)
            list.textContent = "Nenhuma notícia disponível.";
        } catch (error) {
          if (current === generation) list.textContent = error.message;
        }
      }
      for (const [key, label] of [
        ["geral", "Destaques"],
        ["politica", "Política"],
        ["economia", "Economia"],
        ["mundo", "Mundo"],
        ["tecnologia", "Tecnologia"],
      ]) {
        const button = node("button", "chip", label);
        button.onclick = () => {
          categories
            .querySelectorAll("button")
            .forEach((b) => b.classList.toggle("on", b === button));
          load(key);
        };
        categories.append(button);
      }
      categories.firstChild.click();
    }
    // Exibe WhatsApp
    async function showWhatsapp() {
      view.replaceChildren();
      section(view, "WhatsApp", "Mensagens recebidas pelo aplicativo Android.");
      const list = node("div", "org-list");
      const refresh = node("button", "chip", "Atualizar");
      view.append(refresh, list);
      // Carrega os dados da interface
      async function load() {
        try {
          const data = await request("/pessoal/mensagens/celular");
          list.replaceChildren();
          for (const item of data) {
            const card = node("article", "org-card");
            const copy = node("div", "org-card-copy");
            copy.append(
              node("strong", "", item.remetente),
              node("p", "org-note", item.texto),
              node("small", "", new Date(item.hora).toLocaleString("pt-BR")),
            );
            card.append(copy);
            list.append(card);
          }
          if (!data.length)
            list.textContent =
              "Ative o compartilhamento de notificações no Android para receber mensagens aqui.";
        } catch (error) {
          list.textContent = error.message;
        }
      }
      refresh.onclick = load;
      await load();
    }
    // Exibe memory
    async function showMemory() {
      view.replaceChildren();
      section(view, "Memória", "Informações pessoais salvas neste computador.");
      const info = node("p", "org-note", "Verificando…");
      view.append(info);
      try {
        const data = await request("/memoria/estado");
        info.textContent = data.pronta
          ? "Memória disponível. " +
            data.notas +
            " notas, " +
            data.fatos +
            " fatos e " +
            data.compromissos +
            " compromissos."
          : "A memória precisa de atenção.";
      } catch (error) {
        info.textContent = error.message;
      }
    }
    // Seleciona a aba desejada
    async function select(name) {
      setStatus("");
      if (active === "email" && name !== "email") {
        window.confirmGmailDraft = null;
        fetch("/gmail/rascunho", { method: "DELETE" }).catch(() => {});
      }
      active = name;
      for (const [key, button] of buttons)
        button.classList.toggle("on", key === name);
      if (name === "news") return showNews();
      if (name === "whatsapp") return showWhatsapp();
      if (name === "memory") return showMemory();

      if (name === "agenda") return showAgenda();

      if (name === "notes") return showNotes();

      showEmail();
    }

    for (const [key, label] of entries) {
      const button = node("button", "chip", label);
      button.onclick = () => select(key);
      buttons.set(key, button);
      nav.append(button);
    }

    select(active);
    return {
      cleanup: () => {
        window.confirmGmailDraft = null;
        window.refreshPersonalEmail = null;
        fetch("/gmail/rascunho", { method: "DELETE" }).catch(() => {});
      },
    };
  }

  window.paneOrg = paneOrg;
})();
