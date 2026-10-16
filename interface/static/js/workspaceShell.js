(() => {
  "use strict";
  let current = null;
  const element = (tag, cls, text) => {
    const n = document.createElement(tag);
    n.className = cls || "";
    if (text !== undefined) n.textContent = text;
    return n;
  };
  window.openJarvisDashboard = async function () {
    if (current) {
      current.focus();
      return;
    }
    const panel = element("dialog", "jarvis-dashboard"),
      header = element("header"),
      title = element("h2", "", "Saúde do Jarvis"),
      close = element("button", "chip", "Fechar"),
      body = element("div", "dashboard-body"),
      grid = element("div", "dashboard-grid"),
      connections = element("div", "dashboard-connections"),
      telemetry = element("div", "dashboard-telemetry"),
      pressure = element("p", "resource-pressure"),
      breakdown = element("div", "dashboard-breakdown"),
      footer = element("footer"),
      stamp = element("span", "mac-meta", "Consultando…"),
      exportButton = element("button", "chip", "Exportar diagnóstico"),
      sort = element("select"),
      processes = element("div", "resource-processes");
    panel.setAttribute("aria-label", "Saúde e desempenho do Jarvis");
    header.append(title, close);
    for (const [value, label] of [
      ["processos_memoria", "Ordenar por memória"],
      ["processos", "Ordenar por CPU"],
    ]) {
      const option = element("option", "", label);
      option.value = value;
      sort.append(option);
    }
    sort.setAttribute("aria-label", "Ordenação dos processos");
    body.append(
      grid,
      pressure,
      telemetry,
      element("h3", "", "Aplicativos com maior consumo"),
      sort,
      processes,
      element("h3", "", "Processos do Jarvis"),
      breakdown,
      connections,
    );
    footer.append(stamp, exportButton);
    panel.append(header, body, footer);
    document.body.append(panel);
    current = panel;
    document.body.classList.add("modal-open");
    panel.showModal();
    let timer = null,
      controller = null,
      alive = true,
      latest = null;
    const cards = {};
    for (const [key, label] of [
      ["cpu", "CPU"],
      ["ram", "RAM do PC"],
      ["disco", "Espaço em disco usado"],
      ["jarvis_mb", "Jarvis e subprocessos"],
    ]) {
      const card = element("article"),
        value = element("strong", "", "—");
      card.append(element("span", "", label), value);
      grid.append(card);
      cards[key] = value;
    }
    function paintProcesses() {
      processes.replaceChildren();
      for (const p of latest?.[sort.value] || []) {
        const row = element("div");
        row.append(
          element("span", "", p.nome),
          element("strong", "", p.cpu + "% CPU · " + p.ram_mb + " MB"),
        );
        processes.append(row);
      }
    }
    sort.onchange = paintProcesses;
    close.onclick = () => panel.close();
    panel.addEventListener("close", () => {
      alive = false;
      clearTimeout(timer);
      controller?.abort();
      panel.remove();
      current = null;
      document.body.classList.remove("modal-open");
    });
    exportButton.onclick = () => {
      if (!latest) return;
      const safe = {
        gerado_em: new Date().toISOString(),
        cpu: latest.cpu,
        ram: latest.ram,
        disco: latest.disco,
        jarvis_mb: latest.jarvis_mb,
        pressao_memoria: latest.pressao_memoria,
        componentes: latest.componentes,
        processos: latest.processos,
        historico: latest.historico,
        desempenho: window.jarvisPerformanceStats || null,
      };
      const url = URL.createObjectURL(
          new Blob([JSON.stringify(safe, null, 2)], {
            type: "application/json",
          }),
        ),
        link = element("a");
      link.href = url;
      link.download = "jarvis-diagnostico.json";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
    async function poll() {
      if (!alive) return;
      if (document.hidden) {
        timer = setTimeout(poll, 5000);
        return;
      }
      controller = new AbortController();
      const limit = setTimeout(() => controller.abort(), 8000);
      try {
        const r = await fetch("/interface/dashboard", {
          signal: controller.signal,
        });
        if (!r.ok) throw Error();
        const data = await r.json();
        if (!alive) return;
        latest = data;
        for (const key in cards)
          cards[key].textContent =
            data[key] + (key === "jarvis_mb" ? " MB" : "%");
        pressure.dataset.level = data.pressao_memoria;
        pressure.textContent =
          data.pressao_memoria === "alta"
            ? "Memória sob pressão. Veja os maiores consumidores abaixo; nenhum programa será encerrado automaticamente."
            : data.pressao_memoria === "atencao"
              ? "Memória em atenção · " +
                data.ram_disponivel_mb +
                " MB disponíveis"
              : "Memória em nível normal · " +
                data.ram_disponivel_mb +
                " MB disponíveis";
        await window.updateJarvisResources(telemetry, async () => data);
        telemetry
          .querySelector(".resource-processes")
          ?.setAttribute("hidden", "");
        paintProcesses();
        breakdown.replaceChildren();
        const grouped = new Map();
        for (const p of data.componentes || [])
          grouped.set(p.nome, (grouped.get(p.nome) || 0) + p.ram_mb);
        for (const [name, mb] of grouped) {
          const row = element("div");
          row.append(
            element("span", "", name),
            element("strong", "", mb + " MB"),
          );
          breakdown.append(row);
        }
        breakdown.append(
          element(
            "small",
            "mac-meta",
            "Valores de RAM residente por processo; bibliotecas compartilhadas podem aparecer em mais de um processo. Voz e visão podem compartilhar o serviço Jarvis.",
          ),
        );
        connections.replaceChildren();
        for (const [name, ready] of [
          ["Câmera", data.camera],
          ["HTTPS configurado", data.https],
          ["Gmail", data.gmail],
          ["Google Agenda", data.google_agenda],
          ["Celular recente", data.celular?.conectado],
        ]) {
          const row = element(
            "span",
            "connection-badge",
            (ready ? "● " : "○ ") + name,
          );
          row.dataset.ready = String(!!ready);
          connections.append(row);
        }
        stamp.textContent =
          "Atualizado às " +
          new Date(data.atualizado_em * 1000).toLocaleTimeString("pt-BR");
      } catch (e) {
        if (alive)
          stamp.textContent = "Dados desatualizados · tentando novamente";
      } finally {
        clearTimeout(limit);
        if (alive)
          timer = setTimeout(
            poll,
            document.body.classList.contains("economy-mode") ? 10000 : 5000,
          );
      }
    }
    poll();
  };
  // Abre dados de conexao do app
  window.openJarvisPairing = () => {
    document.getElementById("settingsOpen")?.click();
    [...document.querySelectorAll("#tabs button")]
      .find((b) => b.textContent === "Configurações")
      ?.click();
    requestAnimationFrame(() => {
      const d = document.getElementById("cellPairingSetup");
      if (d) {
        d.open = true;
        d.scrollIntoView({ block: "start", behavior: "smooth" });
      }
    });
  };
  // Adiciona integrações nas opções
  function mount() {
    const host = document.getElementById("gmailGroup");
    if (!host || document.getElementById("cellPairingSetup")) return;
    const ai = document.createElement("details");
    ai.className = "settings-group";
    ai.innerHTML =
      '<summary class="settings-group-heading">IA local · LM Studio e Hermes</summary><p class="note">Carregue o Qwen3-8B Q4_K_M e inicie o servidor do LM Studio na porta configurada no servidor local. O identificador é reconhecido automaticamente.</p><p role="status">Verificando conexão…</p><button class="btn" type="button">Verificar conexão</button>';
    host.before(ai);
    const verify = async () => {
      const out = ai.querySelector('[role="status"]');
      try {
        const d = await fetch("/interface/ia").then((r) => r.json());
        out.textContent =
          (d.hermes_instalado
            ? "Hermes Agent instalado. "
            : "Hermes Agent ainda não instalado. ") +
          (d.servidor
            ? d.modelo_disponivel
              ? "Modelo identificado: " + d.modelo
              : "Servidor conectado; carregue o Qwen3-8B."
            : "Aguardando o servidor LM Studio em " +
              (d.url || "endereço configurado") +
              ".");
      } catch (e) {
        out.textContent = "Não consegui verificar a conexão.";
      }
    };
    ai.querySelector("button").onclick = verify;
    verify();
    const pairing = document.createElement("details");
    pairing.className = "settings-group";
    pairing.id = "cellPairingSetup";
    pairing.innerHTML =
      '<summary class="settings-group-heading">Conexão segura do celular</summary><p class="note">Copie a chave de acesso e a impressão digital para as configurações do aplicativo.</p><button class="btn">Mostrar dados de pareamento</button><pre hidden></pre>';
    host.after(pairing);
    pairing.querySelector("button").onclick = async () => {
      try {
        const r = await fetch("/interface/pareamento"),
          d = await r.json();
        if (!r.ok) throw new Error(d.erro);
        const out = pairing.querySelector("pre");
        out.hidden = false;
        out.textContent =
          "IP do PC: " +
          (d.ips || []).join(" ou ") +
          "\nPorta HTTPS: " +
          d.porta +
          "\nChave de acesso do Jarvis: " +
          d.chave +
          "\nCertificado SHA256 do PC: " +
          d.certificado;
      } catch (e) {
        pairing.querySelector("pre").textContent = e.message;
      }
    };
  }
  if (document.getElementById("pane")) {
    new MutationObserver(mount).observe(document.getElementById("pane"), {
      childList: true,
    });
    mount();
  }
})();

// Alterna IA no menu lateral
(function () {
  const buttons = {
    lm_studio: document.getElementById("lmControl"),
    hermes: document.getElementById("hermesControl"),
  };
  let state = {};
  // Atualiza somente estado dos botoes
  function paint(data) {
    state = data;
    for (const [key, button] of Object.entries(buttons)) {
      if (!button) continue;
      button.textContent =
        (key === "lm_studio" ? "LM Studio" : "Hermes") +
        " · " +
        (data[key] ? "Ativo" : "Desativado");
      button.setAttribute("aria-pressed", String(!!data[key]));
      button.title = data[key] ? "Desativar no Jarvis" : "Ativar no Jarvis";
    }
  }
  // Consulta sem carregar modelo
  async function refresh() {
    if (document.hidden) return;
    try {
      const r = await fetch("/assistente/estado");
      if (r.ok) paint(await r.json());
    } catch (e) {}
  }
  for (const [key, button] of Object.entries(buttons)) {
    if (!button) continue;
    button.onclick = async () => {
      button.disabled = true;
      try {
        const r = await fetch("/assistente/ativo", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ferramenta: key, ativo: !state[key] }),
        });
        const d = await r.json();
        if (!r.ok) throw Error(d.erro);
        paint(d);
      } catch (e) {
        button.title = e.message;
      } finally {
        button.disabled = false;
      }
    };
  }
  refresh();
  setInterval(refresh, 5000);
})();
