"use strict";
const $ = (id) => document.getElementById(id);
const EMBUTIDO = ["qt", "native"].includes(
  new URLSearchParams(location.search).get("embutido"),
);
const ls = {
  get(k) {
    try {
      return localStorage.getItem(k);
    } catch (e) {
      return null;
    }
  },
  set(k, v) {
    try {
      localStorage.setItem(k, v);
    } catch (e) {}
  },
};
// Consulta JSON no servidor
const jget = async (u) => {
  const controller = new AbortController(),
    limit = setTimeout(() => controller.abort(), 15000);
  try {
    const r = await fetch(u, { signal: controller.signal });
    if (!r.ok) throw new Error(r.status);
    return await r.json();
  } finally {
    clearTimeout(limit);
  }
};
// Alterna áudio camera
async function alternarAudioCamera(video, botao, status) {
  const faixas = video.srcObject?.getAudioTracks?.() || [];
  if (!faixas.some((faixa) => faixa.readyState === "live")) {
    status.textContent =
      "O áudio da câmera não chegou pelo WebRTC. Verifique a faixa de áudio da A28 no go2rtc.";
    return;
  }
  video.muted = !video.muted;
  if (!video.muted) {
    try {
      await video.play();
    } catch (_) {
      video.muted = true;
      status.textContent =
        "O navegador bloqueou a reprodução. Toque em Ativar áudio novamente.";
      return;
    }
  }
  botao.textContent = video.muted ? "Ativar áudio" : "Silenciar áudio";
  botao.classList.toggle("on", !video.muted);
  status.textContent = video.muted
    ? "Áudio da câmera silenciado."
    : "Áudio da câmera ativado.";
}

// Reutiliza o player dos cards
async function conectarVideoCamera(video, lenteVisualizacao = "baixo") {
  const player = window.createJarvisVideo(video, { lente: lenteVisualizacao });
  return player.ready;
}
// Desenha hud video
function desenharHudVideo(video, tela, dados) {
  if (
    !(video.videoWidth || Number(video.dataset.previaLargura)) ||
    !(video.videoHeight || Number(video.dataset.previaAltura))
  )
    return;
  const largura = tela.clientWidth,
    altura = tela.clientHeight,
    escala = devicePixelRatio || 1;
  if (!largura || !altura) return;
  if (
    tela.width !== Math.round(largura * escala) ||
    tela.height !== Math.round(altura * escala)
  ) {
    tela.width = Math.round(largura * escala);
    tela.height = Math.round(altura * escala);
  }
  const contexto = tela.getContext("2d");
  contexto.setTransform(escala, 0, 0, escala, 0, 0);
  contexto.clearRect(0, 0, largura, altura);

  const desenhar = (b, nome, cor) => {
    const x = b.x1 * largura,
      y = b.y1 * altura,
      w = (b.x2 - b.x1) * largura,
      h = (b.y2 - b.y1) * altura;
    contexto.strokeStyle = cor;
    contexto.lineWidth = 2;
    contexto.strokeRect(x, y, w, h);
    contexto.fillStyle = cor;
    contexto.font = "bold 12px system-ui";
    contexto.fillText(nome, x + 3, Math.max(13, y - 4));
  };
  for (const [indice, b] of (dados.caixas || []).entries())
    desenhar(b, "PESSOA " + (indice + 1), "#000000");
  const articulacoes = [
    [5, 6],
    [5, 7],
    [7, 9],
    [6, 8],
    [8, 10],
    [5, 11],
    [6, 12],
    [11, 12],
    [11, 13],
    [13, 15],
    [12, 14],
    [14, 16],
  ];
  for (const pose of dados.poses || []) {
    const pontos = pose.keypoints || [];
    contexto.strokeStyle = "#55e6b3";
    contexto.fillStyle = "#a7ffdf";
    contexto.lineWidth = 2;
    for (const [a, b] of articulacoes) {
      const p = pontos[a],
        q = pontos[b];
      if (!p || !q || p[2] < 0.35 || q[2] < 0.35) continue;
      contexto.beginPath();
      contexto.moveTo(p[0] * largura, p[1] * altura);
      contexto.lineTo(q[0] * largura, q[1] * altura);
      contexto.stroke();
    }
    for (const p of pontos)
      if (p && p[2] >= 0.35) {
        contexto.beginPath();
        contexto.arc(p[0] * largura, p[1] * altura, 2.6, 0, Math.PI * 2);
        contexto.fill();
      }
    const x = Number(pose.x1 || 0) * largura,
      y = Number(pose.y1 || 0) * altura;
    const identificacao = pose.nome ? pose.nome.toUpperCase() : "";
    if (identificacao) {
      contexto.font = "bold 12px system-ui";
      contexto.fillStyle = pose.nome ? "#55e6b3" : "#000000";
      contexto.fillText(identificacao, x + 3, Math.max(14, y - 5));
    }
  }
}

async function copiarTexto(texto) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(texto);
      return true;
    }
  } catch (_) {}
  const campo = document.createElement("textarea");
  campo.value = texto;
  campo.readOnly = true;
  campo.style.cssText = "position:fixed;left:-10000px;top:0;opacity:0";
  document.body.appendChild(campo);
  campo.select();
  let copiado = false;
  try {
    copiado = document.execCommand("copy");
  } catch (_) {
    copiado = false;
  }
  campo.remove();
  return copiado;
}

let state = "IDLE",
  nivel = 0;
const ROT = {
  IDLE: ["Em espera", ""],
  LISTENING: ["Ouvindo", ""],
  THINKING: ["Preparando resposta", ""],
  SPEAKING: ["Respondendo", ""],
};

function setState(s) {
  state = s;
  document.body.dataset.jarvisState = s;
  window.setJarvisCoreState?.(s);
  $("status").innerHTML = s === "IDLE" ? "Em espera" : `<b>${ROT[s][0]}</b>`;
}
setState("IDLE");
requestAnimationFrame(() =>
  requestAnimationFrame(() => document.body.classList.add("ready")),
);

function relogio() {
  const d = new Date();
  $("hm").textContent = d.toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
  });
  $("dt").textContent = d.toLocaleDateString("pt-BR", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
}
relogio();
setInterval(relogio, 15000);

function iconeClima(codigo) {
  const valor = Number(codigo);
  if (valor === 1) return "\ud83c\udf24\ufe0f";
  if ([95, 96, 99].includes(valor)) return "\u26c8\ufe0f";
  if ([71, 73, 75, 77, 85, 86].includes(valor)) return "\u2744\ufe0f";
  if ([51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82].includes(valor))
    return "\ud83c\udf27\ufe0f";
  if ([45, 48].includes(valor)) return "\ud83c\udf2b\ufe0f";
  if (valor === 3) return "\u2601\ufe0f";
  if (valor === 2) return "\u26c5";
  return "\u2600\ufe0f";
}

async function clima() {
  try {
    const d = await jget("/clima"),
      tp = d.temperatura ?? d.temp ?? d.temperature,
      ds = d.descricao ?? d.condicao ?? d.description ?? "";
    const icon = document.createElement("span");
    icon.className = "weather-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = d.icone || iconeClima(d.codigo);
    const label = document.createElement("span");
    label.className = "weather-label";
    label.textContent = [
      tp != null ? `${Math.round(tp)}\u00b0` : "",
      ds,
      d.cidade || "",
    ]
      .filter(Boolean)
      .join(" \u00b7 ");
    $("cl").replaceChildren(icon, label);
    $("cl").setAttribute("aria-label", label.textContent);
  } catch (_) {
    $("cl").replaceChildren();
    $("cl").removeAttribute("aria-label");
  }
}
clima();
setInterval(clima, 600000);

async function sistema() {
  if (document.hidden) return;
  try {
    const d = await jget("/sistema");
    for (const [k, v] of [
      ["cpu", d.cpu],
      ["ram", d.ram],
    ]) {
      $(k + "v").textContent = Math.round(v) + "%";
      $(k + "b").style.width = Math.min(100, v) + "%";
    }
  } catch (e) {}
}
sistema();
setInterval(sistema, 5000);

const chat = $("chat"),
  inp = $("inp");
const ROTULO = /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent)
  ? "CELULAR"
  : "PC";
let sessionId = ls.get("jarvis_session_id") || "principal",
  ws = null,
  atual = null,
  bruto = "",
  alheio = false;
let respostaCanceladaLocalmente = false;

const hora = () =>
  new Date().toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
  });

let notificationTimer;
// Exibe pessoal notification
window.showPersonalNotification = (texto) => {
  let aviso = document.getElementById("personalNotification");
  if (!aviso) {
    aviso = document.createElement("aside");
    aviso.id = "personalNotification";
    aviso.className = "personal-notification";
    aviso.setAttribute("role", "status");
    document.body.append(aviso);
  }
  aviso.replaceChildren();
  const copy = document.createElement("p");
  copy.textContent = texto;
  const close = document.createElement("button");
  close.className = "chip";
  close.textContent = "Fechar";
  close.onclick = () => {
    aviso.hidden = true;
    clearTimeout(notificationTimer);
  };
  aviso.append(copy, close);
  aviso.hidden = false;
  clearTimeout(notificationTimer);
  notificationTimer = setTimeout(() => {
    aviso.hidden = true;
  }, 15000);
};
// Exibe mensagem na conversa
function msg(
  papel,
  texto,
  { stream = false, notif = false, quem = null } = {},
) {
  const w = document.createElement("div");
  w.className = "m " + (notif ? "n" : papel === "jarvis" ? "j" : "u");
  const s = document.createElement("small");
  s.textContent =
    (notif
      ? "Alerta"
      : papel === "jarvis"
        ? "Jarvis"
        : quem && quem !== ROTULO
          ? quem
          : "Você") +
    " · " +
    hora();
  const p = document.createElement("p");
  p.textContent = texto;
  if (stream) p.className = "st";
  const avatar = document.createElement("span");
  avatar.className = "message-avatar";
  avatar.setAttribute("aria-hidden", "true");
  avatar.textContent = notif ? "!" : papel === "jarvis" ? "J" : "V";
  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.append(s, p);
  w.append(avatar, bubble);
  chat.appendChild(w);
  while (chat.children.length > 100) chat.firstElementChild.remove();
  chat.scrollTop = chat.scrollHeight;
  return p;
}
// Abre a conexão local
function conectar() {
  ws = new WebSocket(
    (location.protocol === "https:" ? "wss" : "ws") +
      "://" +
      location.host +
      "/ws",
  );
  ws.onopen = () => $("ws").classList.add("on");
  ws.onclose = () => {
    $("ws").classList.remove("on");
    setTimeout(conectar, 2000);
  };
  ws.onerror = () => ws.close();
  ws.onmessage = (e) => {
    let m;
    try {
      m = JSON.parse(e.data);
    } catch (_) {
      return;
    }
    if (m.type === "start") {
      if (m.session_id && m.session_id !== sessionId) {
        alheio = true;
        return;
      }
      inp.disabled = true;
      alheio = false;
      respostaCanceladaLocalmente = false;
      if (m.session_id) {
        sessionId = m.session_id;
        ls.set("jarvis_session_id", sessionId);
      }
      setState("THINKING");
      atual = msg("jarvis", "", { stream: true });
      bruto = "";
    } else if (
      m.type === "chunk" &&
      atual &&
      !alheio &&
      !respostaCanceladaLocalmente
    ) {
      bruto += m.content;
      atual.textContent = bruto;
      chat.scrollTop = chat.scrollHeight;
      setState("SPEAKING");
    } else if (m.type === "done") {
      if (alheio) {
        alheio = false;
        inp.disabled = false;
        return;
      }
      if (atual) atual.classList.remove("st");
      if (/e-?mail enviado/i.test(bruto)) window.refreshPersonalEmail?.();
      const ms = falaPcAtiva ? 1000 : 1200;
      setTimeout(() => {
        if (state === "SPEAKING" && !falaPcAtiva)
          setState(micOn ? "LISTENING" : "IDLE");
      }, ms);
      atual = null;
      bruto = "";
      inp.disabled = false;
      if (!EMBUTIDO && matchMedia("(pointer:fine)").matches) inp.focus();
    } else if (m.type === "external_assistant_message") {
      if (m.session_id && m.session_id !== sessionId) return;
      msg("jarvis", m.content, { quem: m.device_label });
    } else if (m.type === "local_interaction") {
      if (m.session_id && m.session_id !== sessionId) return;
      if (m.texto) {
        msg("u", m.texto);
        if (window.matchesDailyBriefing?.(m.texto))
          window.openDailyBriefing?.();
      }
      if (m.resposta) msg("jarvis", m.resposta);
    } else if (m.type === "user_message") {
      if (m.session_id && m.session_id !== sessionId) return;
      msg("u", m.content, { quem: m.device_label });
      window.openBriefingForCommand?.(m.content);
    } else if (m.type === "daily_briefing") {
      window.handleDailyBriefing?.(m);
      if (m.state === "reading" && m.texto) msg("jarvis", m.texto);
    } else if (m.type === "daily_briefing_open") {
      window.openDailyBriefing?.({ read: m.read });
    } else if (m.type === "briefing") {
      window.openDailyBriefing?.({ slide: m.slide || "news", read: !!m.read });
    } else if (m.type === "gmail_connected") {
      window.refreshPersonalEmail?.();
      const infoGmail = $("gmailStatus");
      if (infoGmail)
        jget("/gmail/status")
          .then((d) => {
            infoGmail.textContent = d.conectado
              ? "Conta conectada: " + d.email
              : "Cliente OAuth salvo. Conecte sua conta Google.";
            $("gmailDisconnect").disabled = !d.conectado;
            $("gmailConnect").disabled = !d.configurado;
          })
          .catch(() => {});
    } else if (m.type === "security_event") {
      if (!m.event || m.event.alertAllowed === false) return;
      window.stopDailyBriefing?.();
      window.notifyCornerAlert?.(m.event);
      if (!window.notifyCornerAlert && m.event.abrirTela !== false)
        window.openSecurityEvent?.(m.event);
      msg(
        "jarvis",
        `${m.event.zoneName || "Portão"}: ${m.event.event || "Pessoa detectada"}`,
        { notif: true },
      );
    } else if (m.type === "notification") {
      msg("jarvis", m.content, { notif: true });
      window.showPersonalNotification?.(m.content);
    } else if (m.type === "error") {
      if (m.session_id && m.session_id !== sessionId) {
        alheio = false;
        return;
      }
      if (atual) atual.classList.remove("st");
      atual = null;
      respostaCanceladaLocalmente = false;
      setState("IDLE");
      inp.disabled = false;
      if (m.content) msg("jarvis", "⚠ " + m.content, { notif: true });
    }
  };
}

function enviar(texto) {
  texto = (texto || "").trim();
  if (!texto) return;
  window.openBriefingForCommand?.(texto);
  const confirmacaoEmail = texto
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("pt-BR")
    .replace(/[,!?.;:]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (
    [
      "pode enviar jarvis",
      "jarvis pode enviar",
      "confirmar e enviar email",
      "confirmar e enviar o email",
    ].includes(confirmacaoEmail) &&
    window.confirmGmailDraft
  ) {
    msg("u", texto);
    inp.value = "";
    Promise.resolve(window.confirmGmailDraft()).catch(() =>
      msg("jarvis", "Não foi possível confirmar o envio do e-mail.", {
        notif: true,
      }),
    );
    return;
  }
  if (!ws || ws.readyState !== 1) {
    msg("jarvis", "Sem conexão com o Jarvis agora. Reconectando…", {
      notif: true,
    });
    return;
  }
  msg("u", texto);
  inp.value = "";
  inp.disabled = true;
  setState("THINKING");
  ws.send(
    JSON.stringify({
      message: texto,
      session_id: sessionId,
      device_label: ROTULO,
    }),
  );
}
$("form").addEventListener("submit", (e) => {
  e.preventDefault();
  enviar(inp.value);
});
$("nova").onclick = () => {
  sessionId = "s" + Date.now().toString(36);
  ls.set("jarvis_session_id", sessionId);
  chat.replaceChildren();
  $("sess").textContent = "Nova conversa";
};
$("chatDelete").onclick = async () => {
  if (inp.disabled) {
    msg(
      "jarvis",
      "Espere a resposta terminar antes de excluir esta conversa.",
      { notif: true },
    );
    return;
  }
  if (
    !confirm(
      "Excluir permanentemente as mensagens desta conversa salvas no sistema?",
    )
  )
    return;

  const id = sessionId,
    r = await fetch(`/api/sessions/${encodeURIComponent(id)}`, {
      method: "DELETE",
    })
      .then(async (x) => ({ ok: x.ok, d: await x.json().catch(() => ({})) }))
      .catch(() => ({ ok: false, d: { erro: "Servidor inacessível." } }));
  if (!r.ok) {
    msg("jarvis", r.d.erro || "Não foi possível excluir a conversa.", {
      notif: true,
    });
    return;
  }
  chat.replaceChildren();
  if (id !== "principal") {
    sessionId = "s" + Date.now().toString(36);
    ls.set("jarvis_session_id", sessionId);
    $("sess").textContent = "Nova conversa";
  } else $("sess").textContent = "Sessão principal";
};

async function historico() {
  try {
    const r = await jget(
      `/api/sessions/${encodeURIComponent(sessionId)}/messages`,
    );
    const l = Array.isArray(r) ? r : r.messages || r.mensagens || [];
    for (const m of l) {
      const papel =
        (m.role || m.papel) === "assistant" || (m.role || m.papel) === "jarvis"
          ? "jarvis"
          : "u";
      const txt = m.content ?? m.texto ?? "";
      if (txt) msg(papel, txt);
    }
  } catch (e) {}
}
historico();
conectar();

let micOn = false,
  micCtx = null,
  micStream = null,
  micRaf = 0,
  vad = null,
  erroMicNavegador = false,
  micResumeGesture = null;
const MIC_RESUME_EVENTS = ["pointerdown", "keydown", "touchstart"];
// Remove gestos retomada microfone
function removerGestosRetomadaMicrofone() {
  if (!micResumeGesture) return;
  MIC_RESUME_EVENTS.forEach((evento) =>
    document.removeEventListener(evento, micResumeGesture),
  );
  micResumeGesture = null;
}
const vs = $("vs"),
  micBtn = $("mic");
let alvoMicrofone = 0,
  nivelVisualMicrofone = 0,
  picoVisualMicrofone = 0,
  tempoPicoMicrofone = 0;
// Atualiza medidor microfone
function atualizarMedidorMicrofone(valor, dica, classe) {
  const n = Math.max(0, Math.min(100, Number(valor) || 0)),
    painel = $("micMeter");
  alvoMicrofone = n;
  if (n >= picoVisualMicrofone) {
    picoVisualMicrofone = n;
    tempoPicoMicrofone = performance.now();
  }
  const hint = $("micHint");
  if (hint) hint.textContent = dica;
  if (!painel) return;
  painel.classList.remove("active", "warn", "error");
  if (classe) painel.classList.add(classe);
}
const barraMicrofone = $("micLevel"),
  picoMicrofone = $("micPeak"),
  trilhaMicrofone = barraMicrofone.parentElement;
let larguraTrilhaMicrofone = trilhaMicrofone.clientWidth,
  ultimoQuadroMicrofone = performance.now(),
  ultimoVermelhoMicrofone = 0;
if (window.ResizeObserver)
  new ResizeObserver((entries) => {
    larguraTrilhaMicrofone = entries[0].contentRect.width;
  }).observe(trilhaMicrofone);
const ondaSom = document.createElement("span");
ondaSom.className = "mic-sound-wave";
ondaSom.setAttribute("aria-hidden", "true");

const barrasSom = Array.from({ length: 7 }, () => {
  const barra = document.createElement("i");
  ondaSom.append(barra);
  return barra;
});
$("micMeter").append(ondaSom);
// Anima o som sem piscar

(function animarMedidorMicrofone(agora = performance.now()) {
  const fps = alvoMicrofone > 2 ? 45 : 30;
  if (
    document.hidden ||
    document.body.classList.contains("cfg") ||
    document.body.classList.contains("modal-open") ||
    agora - ultimoQuadroMicrofone < 1000 / fps - 0.25
  ) {
    requestAnimationFrame(animarMedidorMicrofone);
    return;
  }
  const delta = Math.min((agora - ultimoQuadroMicrofone) / 1000, 0.1);
  ultimoQuadroMicrofone = agora;
  if (!document.hidden) {
    const suavidade =
      1 -
      Math.exp(-delta / (alvoMicrofone > nivelVisualMicrofone ? 0.055 : 0.16));
    nivelVisualMicrofone += (alvoMicrofone - nivelVisualMicrofone) * suavidade;
    if (alvoMicrofone >= 90) ultimoVermelhoMicrofone = agora;
    $("micMeter").classList.toggle(
      "level-high",
      alvoMicrofone >= 90 || agora - ultimoVermelhoMicrofone < 450,
    );
    if (performance.now() - tempoPicoMicrofone > 650)
      picoVisualMicrofone = Math.max(
        alvoMicrofone,
        picoVisualMicrofone - delta * 24,
      );
    barraMicrofone.style.transform =
      "scaleX(" + (nivelVisualMicrofone / 100).toFixed(4) + ")";
    picoMicrofone.style.transform =
      "translateX(" +
      Math.max(
        0,
        Math.min(
          larguraTrilhaMicrofone - 2,
          (larguraTrilhaMicrofone * picoVisualMicrofone) / 100,
        ),
      ).toFixed(1) +
      "px)";
    barrasSom.forEach((barra, indice) => {
      const desenho =
        0.42 + 0.58 * Math.pow(Math.sin(agora / 280 + indice * 0.62), 2);
      const altura =
        0.14 + 0.86 * Math.min(1, nivelVisualMicrofone / 65) * desenho;
      barra.style.transform = "scaleY(" + altura.toFixed(3) + ")";
    });
    const exibido = Math.round(nivelVisualMicrofone),
      valor = $("micValue");
    if (valor.textContent !== exibido + "%") valor.textContent = exibido + "%";
  }
  requestAnimationFrame(animarMedidorMicrofone);
})();

function micOff(manual) {
  micOn = false;
  erroMicNavegador = false;
  micBtn.classList.remove("on");
  $("lv").style.height = "0";
  vs.textContent = "";
  removerGestosRetomadaMicrofone();
  atualizarMedidorMicrofone(0, "Microfone do navegador desligado", "");
  cancelAnimationFrame(micRaf);
  if (micStream) micStream.getTracks().forEach((t) => t.stop());
  if (micCtx) micCtx.close().catch(() => {});
  micStream = micCtx = vad = null;
  if (state === "LISTENING") setState("IDLE");
  if (manual) ls.set("mark2_mic_manual_off", "1");
}

async function micLigar(auto) {
  if (EMBUTIDO || micOn) return;
  if (!navigator.mediaDevices?.getUserMedia) {
    erroMicNavegador = true;
    atualizarMedidorMicrofone(
      0,
      "Microfone indisponível. Abra o Jarvis em HTTPS ou localhost.",
      "error",
    );
    return;
  }
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: true,
      video: false,
    });
  } catch (e) {
    erroMicNavegador = true;
    const detalhe =
      e.name === "NotAllowedError" || e.name === "SecurityError"
        ? "Permita o microfone do navegador e use HTTPS ou localhost."
        : "Não foi possível abrir o microfone: " +
          (e.message || e.name || "erro desconhecido");
    atualizarMedidorMicrofone(0, detalhe, "error");
    return;
  }
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) {
    micStream.getTracks().forEach((track) => track.stop());
    micStream = null;
    erroMicNavegador = true;
    atualizarMedidorMicrofone(
      0,
      "Este navegador não oferece suporte à captura de áudio.",
      "error",
    );
    return;
  }
  try {
    micCtx = new AC();
  } catch (e) {
    micStream.getTracks().forEach((track) => track.stop());
    micStream = null;
    erroMicNavegador = true;
    atualizarMedidorMicrofone(
      0,
      "Não foi possível iniciar o processamento do áudio: " +
        (e.message || "erro desconhecido"),
      "error",
    );
    return;
  }
  erroMicNavegador = false;
  micOn = true;
  micBtn.classList.add("on");
  if (!auto) ls.set("mark2_mic_manual_off", "0");

  const retomar = async () => {
    if (!micCtx || micCtx.state !== "suspended") return;
    try {
      await micCtx.resume();
      if (micCtx.state === "running") {
        removerGestosRetomadaMicrofone();
        atualizarMedidorMicrofone(
          0,
          "Microfone ativo · aguardando voz",
          "active",
        );
      }
    } catch (e) {
      erroMicNavegador = true;
      atualizarMedidorMicrofone(
        0,
        "O navegador suspendeu o áudio. Toque no microfone para tentar novamente.",
        "warn",
      );
    }
  };
  void retomar();

  micResumeGesture = () => {
    void retomar();
  };
  MIC_RESUME_EVENTS.forEach((evento) =>
    document.addEventListener(evento, micResumeGesture, { passive: true }),
  );
  const src = micCtx.createMediaStreamSource(micStream),
    an = micCtx.createAnalyser();
  an.fftSize = 256;
  an.smoothingTimeConstant = 0.6;
  src.connect(an);
  const buf = new Uint8Array(an.frequencyBinCount);

  (function medir() {
    if (!micCtx || micCtx.state !== "running") {
      micRaf = requestAnimationFrame(medir);
      return;
    }
    an.getByteFrequencyData(buf);
    let s = 0;
    for (const v of buf) s += v;
    const m = s / buf.length;
    nivel = Math.min(1, m / 70);
    const entrada = Math.min(100, m * 1.8);
    $("lv").style.height = entrada + "%";
    atualizarMedidorMicrofone(
      entrada,
      entrada > 3
        ? "Som captado pelo navegador"
        : "Microfone ativo · aguardando voz",
      "active",
    );
    micRaf = requestAnimationFrame(medir);
  })();
  vad = { falando: false, silencio: 0, chunks: [], aguarda: false };
  setState("LISTENING");
  vs.textContent = "Ouvindo · diga Jarvis + comando";
  const PAUSA_S = 0.65;
  const LIM = 0.015,
    TAM = 4096,
    corte = Math.ceil((PAUSA_S * micCtx.sampleRate) / TAM);
  let filaAudio = Promise.resolve();
  // Fecha frase
  function fecharFrase() {
    if (!vad || !vad.chunks.length) return;
    const cs = vad.chunks;
    vad.chunks = [];
    vad.falando = false;
    vad.silencio = 0;
    if ((cs.length * TAM) / micCtx.sampleRate < 0.35) return;
    vad.aguarda = true;
    setState("THINKING");
    vs.textContent = "Transcrevendo";

    const tot = cs.reduce((a, c) => a + c.length, 0),
      pcm = new Int16Array(tot);
    let o = 0;
    for (const c of cs) {
      pcm.set(c, o);
      o += c.length;
    }
    let tam = 0;

    filaAudio = filaAudio
      .catch(() => {})
      .then(() =>
        fetch("/comando/audio_bruto", {
          method: "POST",
          headers: { "X-Sample-Rate": String(micCtx.sampleRate) },
          body: new Blob([pcm.buffer]),
        }),
      )
      .then(async (r) => {
        const d = await r.json().catch(() => ({}));
        if (!r.ok)
          throw new Error(d.erro || `Falha na transcrição (${r.status}).`);
        return d;
      })
      .then((d) => {
        tam = (d.resposta || "").length;
        if (d.texto) mostrarTextoOuvido(d.texto, false, !d.ignorado);
        if (d.texto) {
          msg("u", d.texto);
          if (!d.ignorado && d.resposta) msg("jarvis", d.resposta);
        }
        if (d.ignorado)
          atualizarMedidorMicrofone(
            0,
            "Áudio recebido · diga Jarvis antes do comando",
            "warn",
          );
      })
      .catch((e) => {
        atualizarMedidorMicrofone(
          0,
          e.message || "Não foi possível transmitir o áudio ao Jarvis.",
          "error",
        );
      })
      .finally(() => {
        if (vad) vad.aguarda = false;
        if (micOn) {
          setState("LISTENING");
          vs.textContent = "Ouvindo · diga Jarvis ou navegue diretamente";
        }
      });
  }
  const pr = micCtx.createScriptProcessor(TAM, 1, 1);
  pr.onaudioprocess = (e) => {
    if (!micOn || !vad) return;
    const f = e.inputBuffer.getChannelData(0),
      i16 = new Int16Array(f.length);
    let q = 0;
    for (let i = 0; i < f.length; i++) {
      const s = Math.max(-1, Math.min(1, f[i]));
      i16[i] = s < 0 ? s * 32768 : s * 32767;
      q += s * s;
    }
    if (Math.sqrt(q / f.length) > LIM) {
      if (!vad.falando) {
        vad.falando = true;
        vs.textContent = "Gravando";
      }
      vad.silencio = 0;
      vad.chunks.push(i16);
    } else if (vad.falando) {
      vad.chunks.push(i16);
      if (++vad.silencio > corte) fecharFrase();
    }
  };
  const mudo = micCtx.createGain();
  mudo.gain.value = 0;
  src.connect(pr);
  pr.connect(mudo);
  mudo.connect(micCtx.destination);
}
micBtn.onclick = async () => {
  if (EMBUTIDO) return alternarVozPC();
  if (micOn && micCtx?.state === "suspended") {
    try {
      await micCtx.resume();
      erroMicNavegador = micCtx.state !== "running";
      atualizarMedidorMicrofone(
        0,
        erroMicNavegador
          ? "O navegador manteve o áudio suspenso."
          : "Microfone reativado.",
        erroMicNavegador ? "error" : "active",
      );
    } catch (e) {
      erroMicNavegador = true;
      atualizarMedidorMicrofone(
        0,
        "Não foi possível reativar o áudio: " +
          (e.message || "erro desconhecido"),
        "error",
      );
    }
    return;
  }
  micOn ? micOff(true) : micLigar(false);
};
addEventListener("load", () => {
  if (!EMBUTIDO && ls.get("mark2_mic_manual_off") !== "1") micLigar(true);
});

// Mostra texto ouvido
function mostrarTextoOuvido(texto, parcial, aceito) {
  const panel = $("chatHeard");
  if (!panel || !texto) return;
  panel.hidden = false;
  $("chatHeardLabel").textContent = parcial ? "Ouvindo" : "Ouvi";
  $("chatHeardText").textContent = texto;
  $("chatHeardText").title = texto;
  $("chatHeardState").textContent = parcial
    ? ""
    : aceito
      ? "Comando recebido"
      : "Não enviado como comando";
}
let vozEst = {},
  falaPcAtiva = false;
const vozEl = $("voz");

function pintarVoz(e) {
  const t = vozEl.querySelector("span");
  vozEl.className = "voz";
  if (e.erro) {
    vozEl.classList.add("bad");
    t.textContent = "Microfone com problema";
    if (!micOn && !erroMicNavegador)
      atualizarMedidorMicrofone(0, String(e.erro), "error");
  } else if (!e.ativo) {
    t.textContent = "Voz desligada";
    if (!micOn && !erroMicNavegador)
      atualizarMedidorMicrofone(0, "Microfone do PC desligado", "");
  } else if (e.pausado) {
    vozEl.classList.add("pause");
    t.textContent = "Voz em pausa · diga Jarvis";
    if (!micOn && !erroMicNavegador)
      atualizarMedidorMicrofone(0, "Escuta pausada", "warn");
  } else if (e.ocupado) {
    vozEl.classList.add("on");
    t.textContent = "Processando";
    if (!micOn && !erroMicNavegador)
      atualizarMedidorMicrofone(
        Math.max(e.nivel || 0, e.pico || 0),
        "Comando captado · processando",
        "active",
      );
  } else if (e.janela) {
    vozEl.classList.add("on");
    t.textContent = "Escuta do PC ativa";
    if (!micOn && !erroMicNavegador)
      atualizarMedidorMicrofone(
        Math.max(e.nivel || 0, e.pico || 0),
        "Pode dizer seu comando",
        "active",
      );
  } else {
    vozEl.classList.add("on");
    t.textContent = "Escuta do PC ativa";
    if (!micOn && !erroMicNavegador)
      atualizarMedidorMicrofone(
        Math.max(e.nivel || 0, e.pico || 0),
        "Diga “Jarvis” para começar",
        "active",
      );
  }
}
let consultandoVoz = false;
// Consulta voz
async function pollVoz() {
  if (document.hidden || consultandoVoz) return;
  consultandoVoz = true;
  try {
    const e = await jget("/voz/escuta/estado");
    vozEst = e;
    pintarVoz(e);
    if (!micOn)
      mostrarTextoOuvido(
        e.texto_ouvido,
        e.transcricao_parcial,
        e.comando_reconhecido,
      );
    if (!micOn) nivel = Math.min(1, (e.nivel || 0) / 60);
    const ouvindo = e.ativo && !e.pausado;
    const falaAnterior = falaPcAtiva;
    falaPcAtiva = !!e.falando;
    if (falaPcAtiva) setState("SPEAKING");
    else if (falaAnterior && state === "SPEAKING")
      setState(ouvindo || micOn ? "LISTENING" : "IDLE");
    if (state === "IDLE" && ouvindo) setState("LISTENING");
    else if (state === "LISTENING" && !ouvindo && !micOn) setState("IDLE");
  } catch (x) {
    pintarVoz({ erro: "Servidor de voz indisponível" });
  } finally {
    consultandoVoz = false;
  }
}
// Alterna voz pc
async function alternarVozPC() {
  const ligada = vozEst.ativo && !vozEst.pausado;
  await post(ligada ? "/voz/escuta/desligar" : "/voz/escuta/ativar");
  setTimeout(pollVoz, 400);
}
vozEl.onclick = alternarVozPC;
pollVoz();
setInterval(pollVoz, 400);

const body = document.body;

function chat_(abrir) {
  body.classList.toggle("nochat", !abrir);
  ls.set("jv_nochat", abrir ? "0" : "1");
}
// Expande a conversa completa
$("chatExpand").onclick = () => {
  const expanded = body.classList.toggle("chat-expanded");
  $("chatExpand").textContent = expanded ? "Recolher" : "Expandir";
  $("chatExpand").setAttribute("aria-expanded", String(expanded));
  if (expanded)
    requestAnimationFrame(() => {
      chat.scrollTop = chat.scrollHeight;
    });
  $("chatTools").hidden = true;
  $("chatMenu").setAttribute("aria-expanded", "false");
};
$("chatMenu").onclick = () => {
  $("chatTools").hidden = !$("chatTools").hidden;
  $("chatMenu").setAttribute("aria-expanded", String(!$("chatTools").hidden));
};
document.addEventListener("click", (e) => {
  if (!e.target.closest(".chat-hd")) {
    $("chatTools").hidden = true;
    $("chatMenu").setAttribute("aria-expanded", "false");
  }
});
$("chatx").onclick = () => chat_(false);
$("chatopen").onclick = () => chat_(true);
if (ls.get("jv_nochat") === "1") body.classList.add("nochat");

// Protege texto da interface
const esc = (s) =>
  String(s ?? "").replace(
    /[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c],
  );
// Envia dados ao servidor
const post = async (u, b) => {
  try {
    const r = await fetch(u, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(b || {}),
    });
    const d = await r.json().catch(() => ({}));
    return { ok: r.ok, d };
  } catch (e) {
    return { ok: false, d: { erro: "Servidor inacessível" } };
  }
};

const servidor_localBotao = $("servidor_localToggle");
let servidor_localLigado = true;

async function sincronizarServidorLocal() {
  if (document.hidden) return;
  try {
    const estado = await jget("/llm/estado");
    servidor_localLigado = !!estado.ativo;
    servidor_localBotao.classList.toggle("on", servidor_localLigado);
    servidor_localBotao.title = servidor_localLigado
      ? "Desativar LM Studio"
      : "Ativar LM Studio";
    servidor_localBotao.setAttribute("aria-label", servidor_localBotao.title);
  } catch (e) {
    servidor_localBotao.title = "Estado do LM Studio indisponivel";
  }
}
servidor_localBotao.onclick = async () => {
  servidor_localBotao.disabled = true;
  const resultado = await post("/llm/ativo", { ativo: !servidor_localLigado });
  if (!resultado.ok)
    alert(resultado.d.erro || "Não foi possível alterar o LM Studio.");
  else servidor_localLigado = !!resultado.d.ativo;
  await sincronizarServidorLocal();
  servidor_localBotao.disabled = false;
};
$("speechStop").onclick = async () => {
  window.speechSynthesis?.cancel();
  document.querySelectorAll("audio,video").forEach((el) => el.pause());
  const botao = $("speechStop");
  botao.disabled = true;
  respostaCanceladaLocalmente = true;
  if (atual) atual.classList.remove("st");
  atual = null;
  bruto = "";
  inp.disabled = false;
  setState(micOn ? "LISTENING" : "IDLE");
  const resultados = await Promise.all([post("/assistente/parar")]);

  const falha = resultados.find((resultado) => !resultado.ok);
  if (falha)
    msg(
      "jarvis",
      falha.d.erro || "Não foi possível interromper uma das ações.",
      { notif: true },
    );
  botao.disabled = false;
};
setInterval(sincronizarServidorLocal, 5000);
sincronizarServidorLocal();
$("stop").onclick = async () => {
  if (!confirm("Pausar a IA no Jarvis? O LM Studio continuará aberto.")) return;
  $("stop").disabled = true;
  const resultado = await post("/llm/servidor/parar");
  $("stop").disabled = false;
  if (!resultado.ok || !resultado.d.sucesso) {
    await sincronizarServidorLocal();
    alert(
      resultado.d.mensagem ||
        resultado.d.erro ||
        "Não foi possível interromper o servidor.",
    );
    return;
  }
  servidor_localLigado = false;
  await sincronizarServidorLocal();
  alert(resultado.d.mensagem);
};
$("shutdownMark2").onclick = async () => {
  if (
    !confirm(
      "Encerrar o Mark 2 inteiro? A escuta, o painel e o servidor remoto serao fechados.",
    )
  )
    return;
  $("shutdownMark2").disabled = true;
  const resultado = await post("/comando", {
    texto: "sair",
    confirmar_encerramento: true,
    usar_llm: false,
    falar_no_pc: false,
  });
  if (!resultado.ok) {
    $("shutdownMark2").disabled = false;
    alert(resultado.d.erro || "Nao foi possivel encerrar o Mark 2.");
    return;
  }
  $("status").textContent = "Encerrando Mark 2";
};

function paneSeg(el) {
  el.classList.add("security-pane");
  el.innerHTML =
    '<div class="security-heading"><div><div class="sec" id="securityHeading">Segurança e câmera A28</div><p class="note">Acompanhe o Protocolo Torre Stark e acesse os controles da câmera em um só lugar.</p></div><span class="security-live-indicator"><i></i> Câmera inferior</span></div>' +
    '<div id="securityDetails" class="security-counts" aria-live="polite"></div>' +
    '<div class="security-actions"><button class="btn" id="securityToggle">Consultar seguran\u00e7a</button><button class="btn" id="lineOpen">Configurar linha</button></div>' +
    '<p class="note" id="cameraModeNote">A lente inferior é usada pelo sistema de segurança. A superior fica disponível para visualização ao vivo.</p>' +
    '<div id="securityStatus" class="msgline" role="status"></div>' +
    '<section id="securityCamera" class="security-live"><video id="securityFrame" autoplay playsinline muted></video><canvas id="securityLiveHud" aria-hidden="true"></canvas><div class="camera-overlay-status"><span id="cameraLensBadge" class="camera-badge">LENTE INFERIOR · SEGURANÇA</span><span id="cameraCountBadge" class="camera-badge">PESSOAS AGORA: 0</span><span id="cameraModeBadge" class="camera-badge">AGUARDANDO DEFESAS</span></div><div id="securityFrameMessage" class="security-frame-message">Conectando à câmera…</div><div class="security-live-actions"><button class="btn" id="cameraAudioOutput">Ativar áudio</button><button class="btn" id="liveLensTop" hidden>Câmera de cima</button><button class="btn on" id="liveLensBottom" hidden>Câmera de baixo</button></div></section>' +
    '<div class="sec" id="securityVisionSection">Detec\u00e7\u00e3o de pessoas</div><section class="security-vision-panel"><p class="note">O Jarvis confirma a presença de pessoas antes de avisar.</p><label><input type="checkbox" id="poseToggle"><span>Ativar confirma\u00e7\u00e3o por YOLO11-Pose</span></label><div class="msgline" id="visionStatus" role="status" aria-live="polite">Carregando estado do detector...</div></section>' +
    '<div class="sec" id="cameraAudioSection">Áudio da câmera</div><div class="security-audio"><label for="cameraVolume">Volume do alto-falante da câmera</label><input id="cameraVolume" type="range" min="0" max="100" step="1"><span id="cameraVolumeValue">—</span><button class="btn" id="cameraVolumeTest">Testar</button><button class="btn" id="cameraSpeechToggle">Carregando fala…</button></div><div id="cameraAudioStatus" class="msgline" role="status"></div>' +
    '<div class="sec" id="cameraSpeechSection">Falas rápidas</div><p class="note">Escolha uma frase para a câmera reproduzir quando precisar falar com alguém no portão.</p><div id="cameraSpeeches" class="grid"></div><div class="security-custom-speech"><input id="cameraCustomSpeech" maxlength="300" placeholder="Escreva uma fala de até 300 caracteres" aria-label="Fala personalizada da câmera"><button class="btn" id="cameraCustomSpeak">Falar pela câmera</button></div>' +
    '<section class="security-media" id="securityMedia"><div><strong>Fotos e grava\u00e7\u00f5es</strong><p class="note">As fotos abrem na pasta da c\u00e2mera. A grava\u00e7\u00e3o mais recente abre no reprodutor padr\u00e3o do Windows, como VLC ou Filmes e TV.</p></div><div class="security-media-actions"><button class="btn" id="openSecurityPhotos">Abrir fotos</button><button class="btn" id="openSecurityRecording">Abrir grava\u00e7\u00e3o</button></div><div class="msgline" id="securityMediaStatus" role="status"></div></section>';
  // Isola elementos desta aba
  const elementos = new Map(
    [...el.querySelectorAll("[id]")].map((item) => [item.id, item]),
  );
  const $ = (id) => elementos.get(id);

  const status = $("securityStatus"),
    details = $("securityDetails"),
    wrap = $("securityCamera"),
    frame = $("securityFrame"),
    liveHud = $("securityLiveHud"),
    frameMessage = $("securityFrameMessage"),
    speechToggle = $("cameraSpeechToggle"),
    volume = $("cameraVolume"),
    volumeLabel = $("cameraVolumeValue"),
    audioStatus = $("cameraAudioStatus");
  $("cameraAudioOutput").onclick = () =>
    alternarAudioCamera(frame, $("cameraAudioOutput"), audioStatus);
  let ativo = true,
    cameraAberta = false,
    volumeTemporizador = 0,
    liveHudTimer = 0,
    liveGeneration = 0,
    playerCamera = null,
    lenteAoVivo = "baixo";
  el.querySelectorAll(".security-nav [data-target]").forEach(
    (botao) =>
      (botao.onclick = () => {
        $(botao.dataset.target)?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      }),
  );

  function ajustarTelaCheia() {
    const cheia =
      document.fullscreenElement === wrap ||
      wrap.classList.contains("security-live-fullscreen");
    wrap.classList.toggle("security-live-fullscreen", cheia);
  }
  // Atualiza selos camera
  function atualizarSelosCamera(dados) {
    const seloLente = $("cameraLensBadge");
    if (seloLente) {
      seloLente.textContent =
        lenteAoVivo === "baixo"
          ? "LENTE INFERIOR · SEGURANÇA"
          : "LENTE SUPERIOR · SÓ VISUALIZAÇÃO";
      seloLente.classList.toggle(
        "camera-badge-view-only",
        lenteAoVivo === "cima",
      );
    }
    const seloModo = $("cameraModeBadge");
    if (seloModo && dados) {
      seloModo.textContent = !dados.armado
        ? "DEFESAS DESARMADAS"
        : dados.linha_ativa
          ? "LINHA ATIVA"
          : "AGUARDANDO CÂMERA";
    }
  }

  async function atualizar() {
    if (!ativo) return;
    try {
      const d = await jget("/seguranca/estado");
      if (!ativo) return;
      const armado = !!d.armado;
      const botaoSeguranca = $("securityToggle");
      botaoSeguranca.textContent = armado
        ? "Desativar Torre Stark"
        : "Ativar Torre Stark";
      botaoSeguranca.classList.toggle("on", armado);
      atualizarSelosCamera(d);
      speechToggle.textContent = d.fala?.ativa
        ? "Desativar fala da câmera"
        : "Ativar fala da câmera";
      speechToggle.classList.toggle("on", !!d.fala?.ativa);
      for (const botao of $("cameraSpeeches").querySelectorAll("button"))
        botao.disabled = !d.fala?.ativa;
      $("cameraCustomSpeech").disabled = !d.fala?.ativa;
      $("cameraCustomSpeak").disabled = !d.fala?.ativa;
      details.replaceChildren();
      document.body.classList.toggle("veronica-armed", armado && d.ativa);
      window.setJarvisVeronicaArmed?.(armado && d.ativa);
      const cameraOnline = !!d.camera?.conectada;
      el.querySelector(".security-live-indicator")?.classList.toggle(
        "is-connected",
        cameraOnline,
      );
      const cameraMovida = !!d.camera?.camera_movida;
      const linhaStatus = d.linha_ativa
        ? "Ativa e validada"
        : d.camera?.camera_posicao_validada
          ? "Pausada"
          : "Aguardando posição estável";
      const deteccaoStatus = !d.camera?.ativo
        ? "Monitoramento desligado"
        : !cameraOnline
          ? "C\u00e2mera desconectada"
          : d.camera?.deteccao_nativa || "Aguardando ret\u00e2ngulo amarelo";
      const gravacaoStatus = !d.camera?.gravar_video
        ? "Desativada"
        : d.camera?.gravando
          ? "Gravando"
          : !cameraOnline
            ? "C\u00e2mera desconectada"
            : d.camera?.movimento
              ? "Retentando grava\u00e7\u00e3o"
              : "Aguardando movimento";
      const protocoloStatus = !d.ativa
        ? "Desativado"
        : armado
          ? "Armado"
          : "Em espera";
      const valores = [["Pessoas agora", String(d.camera?.pessoas || 0)]];
      for (const [nome, valor] of valores) {
        const linha = document.createElement("div");
        linha.className = "security-state-row";
        const rotulo = document.createElement("span");
        rotulo.textContent = nome;
        const conteudo = document.createElement("strong");
        conteudo.textContent = valor;
        linha.append(rotulo, conteudo);
        details.appendChild(linha);
      }
      const estadoCamera = !d.camera?.ativo
        ? "Monitoramento da c\u00e2mera desligado"
        : cameraOnline
          ? "C\u00e2mera conectada"
          : "C\u00e2mera desconectada; reconectando";
      const estadoProtocolo = !d.ativa
        ? "Protocolo Torre Stark desativado nas configura\u00e7\u00f5es"
        : armado
          ? "Protocolo Torre Stark ativo; defesas armadas"
          : "Protocolo Torre Stark em espera; defesas desarmadas";
      status.textContent =
        estadoCamera +
        " · " +
        (armado && !d.linha_ativa
          ? "Proteção parcial · linha suspensa. Revise a área monitorada."
          : estadoProtocolo) +
        (cameraMovida ? " · Câmera deslocada" : "");
      status.dataset.warning = String(armado && !d.linha_ativa);
      const securityToggle = $("securityToggle");
      securityToggle.disabled = false;
      securityToggle.textContent =
        !d.ativa && !armado
          ? "Ativar e armar Torre Stark"
          : armado
            ? "Desarmar seguran\u00e7a"
            : "Armar seguran\u00e7a";
      if (!cameraAberta) abrirCameraAoVivo();
      const pose = d.pose || {};
      $("poseToggle").checked = pose.ativo !== false;
      $("visionStatus").textContent =
        `${pose.status || "indispon\u00edvel"}${pose.modelo ? " \u00b7 " + pose.modelo : ""}${pose.erro ? " \u00b7 " + pose.erro : ""}`;
    } catch (_) {
      if (ativo)
        status.textContent =
          "Não foi possível consultar o estado da segurança.";
    }
  }
  let consultandoQuadro = false;

  async function quadro() {
    if (!ativo || !cameraAberta || consultandoQuadro) return;
    consultandoQuadro = true;
    try {
      const dados = await jget("/seguranca/hud");
      const contador = $("cameraCountBadge");
      if (contador)
        contador.textContent =
          "PESSOAS AGORA: " + Math.max(0, Number(dados.pessoas) || 0);
      if (lenteAoVivo === "baixo") desenharHudVideo(frame, liveHud, dados);
      else
        liveHud.getContext("2d").clearRect(0, 0, liveHud.width, liveHud.height);
    } catch (_) {
    } finally {
      consultandoQuadro = false;
    }
  }

  async function falar(dados) {
    const resultado = await post("/seguranca/falar", dados);
    audioStatus.textContent =
      resultado.d.mensagem ||
      resultado.d.erro ||
      "Não foi possível enviar a fala.";
  }
  // Carrega falas
  async function carregarFalas() {
    try {
      const data = await jget("/seguranca/falas");
      const essenciais = new Set([
        "Indisponível",
        "Deixe recado",
        "Aguarde",
        "Identifique-se",
        "Encomenda",
        "Área monitorada",
        "Aguarde identificação",
        "Encerrar",
      ]);
      $("cameraSpeeches").replaceChildren(
        ...(data.falas || [])
          .filter((item) => essenciais.has(item.rotulo))
          .map((item) => {
            const botao = document.createElement("button");
            botao.className = "btn";
            botao.textContent = item.rotulo;
            botao.onclick = () => falar({ predefinida: item.id });
            return botao;
          }),
      );
    } catch (_) {
      $("cameraSpeeches").textContent =
        "Não foi possível carregar as falas rápidas.";
    }
  }
  $("securityToggle").onclick = async () => {
    const botao = $("securityToggle");
    botao.disabled = true;
    try {
      const d = await jget("/seguranca/estado");
      const r = await post(d.armado ? "/seguranca/desarmar" : "/seguranca/armar");
      status.textContent = r.ok
        ? (r.d.mensagem || "Estado da segurança atualizado.")
        : (r.d.erro || "Não foi possível alterar a segurança.");
    } catch (e) {
      status.textContent = e.message || "Não foi possível consultar a segurança.";
    } finally {
      botao.disabled = false;
      atualizar();
    }
  };
  // Salva visao opcao
  const salvarVisaoOpcao = async (chave, valor) => {
    const r = await post("/preferencias", { chave, valor });
    if (!r.ok) {
      $("visionStatus").textContent =
        r.d.erro || "Não foi possível salvar a opção.";
      atualizar();
      return;
    }
    $("visionStatus").textContent = "Preferência atualizada.";
    atualizar();
  };
  $("poseToggle").onchange = (evento) =>
    salvarVisaoOpcao("VIGIA_POSE_ATIVO", evento.currentTarget.checked);
  // Abre midia seguranca
  const abrirMidiaSeguranca = async (tipo, botao) => {
    const mediaStatus = $("securityMediaStatus");
    botao.disabled = true;
    const resultado = await post("/seguranca/midia/abrir", { tipo });
    botao.disabled = false;
    mediaStatus.textContent =
      resultado.d.mensagem ||
      resultado.d.erro ||
      "N\u00e3o foi poss\u00edvel abrir a m\u00eddia.";
  };
  $("openSecurityPhotos").onclick = (evento) =>
    abrirMidiaSeguranca("fotos", evento.currentTarget);
  $("openSecurityRecording").onclick = (evento) =>
    abrirMidiaSeguranca("gravacao", evento.currentTarget);
  $("lineOpen").onclick = () => abrir("line");
  // Abre camera ao vivo
  async function abrirCameraAoVivo() {
    if (!ativo || cameraAberta) return;
    cameraAberta = true;
    lenteAoVivo = "baixo";
    wrap.hidden = false;
    frameMessage.hidden = false;
    frameMessage.textContent = "Conectando ao v\u00eddeo ao vivo...";
    const generation = ++liveGeneration;
    try {
      const novoPlayer = await conectarVideoCamera(frame, lenteAoVivo, () => {
        if (generation !== liveGeneration || !ativo) return;
        playerCamera?.fechar();
        playerCamera = null;
        clearInterval(liveHudTimer);
        cameraAberta = false;
        frameMessage.textContent =
          "Imagem interrompida. Reconectando a camera...";
        frameMessage.hidden = false;
      });
      if (!cameraAberta || generation !== liveGeneration) {
        novoPlayer.fechar();
        return;
      }
      playerCamera = novoPlayer;
      $("liveLensTop").hidden = !playerCamera.configuracao.duas_lentes;
      $("liveLensBottom").hidden = !playerCamera.configuracao.duas_lentes;
      $("liveLensTop").classList.toggle("on", lenteAoVivo === "cima");
      $("liveLensBottom").classList.toggle("on", lenteAoVivo === "baixo");
      atualizarSelosCamera(await jget("/seguranca/estado").catch(() => null));
      frameMessage.hidden = true;
      await quadro();
      liveHudTimer = setInterval(quadro, 100);
    } catch (_) {
      if (generation !== liveGeneration) return;
      cameraAberta = false;
      $("liveLensTop").hidden = true;
      $("liveLensBottom").hidden = true;
      frameMessage.textContent =
        "N\u00e3o foi poss\u00edvel conectar ao v\u00eddeo ao vivo. Tentando novamente...";
      frameMessage.hidden = false;
    }
  }
  // Encerra camera ao vivo
  function encerrarCameraAoVivo() {
    cameraAberta = false;
    liveGeneration++;
    clearInterval(liveHudTimer);
    playerCamera?.fechar();
    playerCamera = null;
    lenteAoVivo = "baixo";
    $("liveLensTop").hidden = true;
    $("liveLensBottom").hidden = true;
    liveHud.getContext("2d").clearRect(0, 0, liveHud.width, liveHud.height);
  }

  const escolherLenteAoVivo = (lente) => {
    if (!cameraAberta || !playerCamera?.configuracao.duas_lentes) return;
    lenteAoVivo = lente === "cima" ? "cima" : "baixo";
    playerCamera.definirLente(lenteAoVivo);
    $("liveLensTop").classList.toggle("on", lenteAoVivo === "cima");
    $("liveLensBottom").classList.toggle("on", lenteAoVivo === "baixo");
    atualizarSelosCamera();
    quadro();
  };
  $("liveLensTop").onclick = () => escolherLenteAoVivo("cima");
  $("liveLensBottom").onclick = () => escolherLenteAoVivo("baixo");

  document.addEventListener("fullscreenchange", ajustarTelaCheia);
  $("cameraSpeechToggle").onclick = async () => {
    const d = await jget("/seguranca/estado").catch(() => null);
    if (!d) return;
    const r = await post("/preferencias", {
      chave: "CAMERA_FALA_ATIVA",
      valor: !d.fala?.ativa,
    });
    audioStatus.textContent = r.ok
      ? "Configuração da fala da câmera atualizada."
      : r.d.erro || "Não foi possível alterar a fala da câmera.";
    atualizar();
  };
  $("cameraVolume").oninput = () => {
    volumeLabel.textContent = volume.value + "%";
    clearTimeout(volumeTemporizador);
    volumeTemporizador = setTimeout(async () => {
      const r = await post("/seguranca/camera/volume", {
        volume: Number(volume.value),
      });
      if (!r.ok)
        audioStatus.textContent =
          r.d.erro || "Não foi possível ajustar o volume.";
    }, 250);
  };
  $("cameraVolumeTest").onclick = async () => {
    const r = await post("/seguranca/camera/volume", {
      volume: Number(volume.value),
      testar: true,
    });
    audioStatus.textContent =
      r.d.mensagem || r.d.erro || "Não foi possível testar o volume.";
  };
  $("cameraCustomSpeak").onclick = () => {
    const texto = $("cameraCustomSpeech").value.trim();
    if (texto) falar({ texto });
  };
  $("cameraCustomSpeech").addEventListener("keydown", (evento) => {
    if (evento.key === "Enter") {
      evento.preventDefault();
      $("cameraCustomSpeak").click();
    }
  });
  jget("/seguranca/camera/volume")
    .then((d) => {
      volume.value = d.volume;
      volumeLabel.textContent = d.volume + "%";
    })
    .catch(() => {
      audioStatus.textContent =
        "Não foi possível consultar o volume da câmera.";
    });
  carregarFalas();
  atualizar();
  abrirCameraAoVivo();
  return {
    poll: atualizar,
    every: 3000,
    cleanup: () => {
      ativo = false;
      clearTimeout(volumeTemporizador);
      document.removeEventListener("fullscreenchange", ajustarTelaCheia);
      encerrarCameraAoVivo();
      if (document.fullscreenElement === wrap)
        document.exitFullscreen().catch(() => {});
    },
  };
}
const TABS = {
  ctl: ["Controles", paneCtl],
  line: ["Configurar linha", paneVis],
  seg: ["Seguran\u00e7a", paneSeg],
  org: ["Pessoal", window.paneOrg],
  cmd: ["Comandos de voz", paneComandos],
  log: ["Log", paneLog],
  cfg: ["Configura\u00e7\u00f5es", paneCfg],
};
let tab = ls.get("jv_tab") || "ctl",
  tim = 0,
  paneCleanup = null,
  paneGeneration = 0,
  paneResultado = null,
  paneTab = null;
if (!TABS[tab]) tab = "ctl";
// Monta tabs
function montarTabs() {
  $("tabs").replaceChildren(
    ...Object.entries(TABS)
      .filter(([k]) => k !== "line")
      .map(([k, [n]]) => {
        const b = document.createElement("button");
        b.className = "chip" + (k === tab ? " on" : "");
        b.textContent = n;
        b.onclick = () => abrir(k);
        return b;
      }),
  );
}

function abrir(t) {
  if (body.classList.contains("cfg") && tab === t) return;
  tab = TABS[t] ? t : "ctl";
  ls.set("jv_tab", tab);
  body.classList.add("cfg");
  montarTabs();
  paneGeneration++;
  clearTimeout(tim);
  if (tab === "cfg")
    document
      .querySelectorAll(".security-live-fullscreen")
      .forEach((camera) => camera.classList.remove("security-live-fullscreen"));
  if (paneCleanup) {
    paneCleanup();
    paneCleanup = null;
  }
  const geracao = paneGeneration,
    p = $("pane"),
    reutilizar = paneTab === tab && paneResultado && !paneResultado.cleanup;
  p.scrollTop = 0;
  if (!reutilizar) {
    p.replaceChildren();
    p.classList.remove(
      "security-pane",
      "line-config-pane",
      "controls-pane",
      "logs-pane",
      "commands-pane",
      "settings-pane",
      "personal-pane",
    );
  }
  performance.mark("jarvis-tab-start");
  const r = reutilizar ? paneResultado : TABS[tab][1](p) || {};
  paneResultado = r;
  paneTab = tab;
  performance.mark("jarvis-tab-end");
  performance.measure("jarvis-tab-build", "jarvis-tab-start", "jarvis-tab-end");
  window.dispatchEvent(new CustomEvent("jarvis-pane", { detail: { tab } }));
  if (!r) return;
  paneCleanup = r.cleanup || null;
  if (r.poll) {
    const consultar = async () => {
      if (geracao !== paneGeneration || !body.classList.contains("cfg")) return;
      if (!document.hidden) {
        try {
          await r.poll();
        } catch (e) {}
      }
      if (geracao === paneGeneration && body.classList.contains("cfg"))
        tim = setTimeout(consultar, Math.max(500, r.every || 2000));
    };
    tim = setTimeout(consultar, Math.max(500, r.every || 2000));
  }
}

window.openJarvisSection = abrir;
const fechar = () => {
  paneGeneration++;
  body.classList.remove("cfg");
  clearTimeout(tim);
  tim = 0;
  if (paneCleanup) {
    paneCleanup();
    paneCleanup = null;
  }
};
document
  .querySelectorAll("[data-open]")
  .forEach(
    (b) =>
      (b.onclick = () =>
        abrir(b.id === "settingsOpen" ? "ctl" : b.dataset.open)),
  );
$("cfgx").onclick = fechar;
$("shade").onclick = fechar;
addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !document.querySelector("dialog[open]")) {
    fechar();
    $("lb").classList.remove("on");
  }
});
$("lb").onclick = () => $("lb").classList.remove("on");

let ultimoCruz = null;

async function vigiarCruzamento() {
  if (document.hidden) return;
  let d;
  try {
    d = await jget("/seguranca/hud?leve=1");
  } catch (x) {
    return;
  }
  const veronicaArmada = !!(d.armado && d.protocolo_ativo);
  document.body.classList.toggle("veronica-armed", veronicaArmada);
  window.setJarvisVeronicaArmed?.(veronicaArmada);
  const id = d.cruzamento ? d.cruzamento.id : 0;
  if (ultimoCruz === null) {
    ultimoCruz = id;
    return;
  }
  if (id && id !== ultimoCruz) {
    ultimoCruz = id;
    if (d.abrir_auto && !body.classList.contains("cfg")) {
      abrir("seg");
      setTimeout(() => {
        if (body.classList.contains("cfg") && tab === "seg")
          $("secLinha")?.scrollIntoView({ block: "start", behavior: "smooth" });
      }, 120);
    }
  }
}
setInterval(vigiarCruzamento, 3000);
vigiarCruzamento();

const CTL = {
  Casa: [
    [
      "Atalhos",
      [
        ["Status da casa", "status"],
        ["Clima", "clima"],
        ["Cheguei", "cheguei em casa"],
        ["Saída", "saída"],
      ],
    ],
    [
      "Música de chegada",
      [
        ["Ligar", "ativar música de chegada"],
        ["Desligar", "desativar música de chegada"],
      ],
    ],
  ],
  TV: [
    [
      "Energia",
      [
        ["Ligar TV", "ligar a tv"],
        ["Desligar TV", "desligar a tv"],
        ["Sincronizar", "@sync"],
      ],
    ],
    [
      "Volume",
      [
        ["Vol +", "aumentar o volume da tv"],
        ["Vol −", "abaixar o volume da tv"],
        ["Mudo", "mutar a tv"],
        ["Desmutar", "desmutar a tv"],
      ],
    ],
    [
      "Canal",
      [
        ["Canal +", "próximo canal"],
        ["Canal −", "canal anterior"],
      ],
    ],
    [
      "Mídia",
      [
        ["Voltar", "retroceder a tv"],
        ["Avançar", "avançar a tv"],
      ],
    ],
    [
      "Apps",
      [
        ["Netflix", "abrir netflix na tv"],
        ["YouTube", "abrir youtube na tv"],
        ["Prime Video", "abrir prime video na tv"],
        ["Disney+", "abrir disney+ na tv"],
        ["Spotify", "abrir spotify na tv"],
      ],
    ],
  ],
  PC: [
    [
      "Volume",
      [
        ["Vol +", "@pc/volume:subir"],
        ["Vol −", "@pc/volume:descer"],
        ["Mudo", "@pc/volume:mudo"],
      ],
    ],
    [
      "Mídia",
      [
        ["Anterior", "@pc/midia:anterior"],
        ["Play/Pausa", "@pc/midia:play_pausa"],
        ["Próxima", "@pc/midia:proxima"],
      ],
    ],
    [
      "Sistema",
      [
        ["Bloquear tela", "@pc/bloquear"],
        ["Reiniciar PC", "@pc/reiniciar", 1],
        ["Desligar PC", "@pc/desligar", 1],
        ["Cancelar desligamento", "@pc/cancelar_desligamento"],
      ],
    ],
  ],
  Jarvis: [["Sistema", [["Encerrar Jarvis", "@exit", 1]]]],
};
// Mostra controles principais
function paneCtl(el) {
  el.classList.add("controls-pane");
  let sub = ls.get("jv_sub");
  if (!CTL[sub]) sub = "TV";
  let msg = "";
  let volJ = null;

  const say = (t) => {
    msg = t;
    const m = el.querySelector(".msgline");
    if (m) m.textContent = t;
  };

  async function run(l, a, perigo) {
    if (a === "@sync") {
      const r = await jget("/api/smarthome/dispositivos").catch(() => null);
      return say(
        r
          ? `${r.length} dispositivo(s) sincronizado(s).`
          : "Falha ao sincronizar.",
      );
    }
    if (a === "@exit") {
      if (!confirm("Encerrar o Mark 2 agora?")) return;
      return enviar("sair");
    }
    if (a.startsWith("@post:")) {
      const r = await post(a.slice(6));
      setTimeout(pollVoz, 400);
      return say(r.d.mensagem || r.d.erro || (r.ok ? "Pronto." : "Falhou."));
    }
    if (a.startsWith("@pc/")) {
      if (perigo && !confirm(l + "?")) return;
      const [rota, v] = a.slice(1).split(":");
      const r = await post(
        "/" + rota,
        /volume|midia/.test(rota) ? { acao: v } : { confirmar: true },
      );
      return say(r.d.mensagem || r.d.erro || (r.ok ? "Pronto." : "Falhou."));
    }
    enviar(a);
    say("Enviado: " + l);
  }

  function blocoVolume() {
    const box = document.createElement("div");
    box.className = "control-volume-card";
    const h = document.createElement("div");
    h.className = "sec";
    h.style.marginTop = "0";
    h.textContent = "Volume do Jarvis";
    const row = document.createElement("div");
    row.className = "row2";
    row.style.alignItems = "center";
    const sl = document.createElement("input");
    sl.type = "range";
    sl.min = 5;
    sl.max = 100;
    sl.step = 1;
    sl.value = volJ == null ? 100 : volJ;
    sl.style.cssText = "flex:1;padding:0;accent-color:var(--accent)";
    const lb = document.createElement("span");
    lb.style.cssText = "min-width:42px;text-align:right";
    lb.textContent = sl.value + "%";
    const ts = document.createElement("button");
    ts.className = "btn";
    ts.textContent = "Testar";
    let tm;
    // Envia vol
    const enviarVol = async (teste) => {
      const r = await post("/voz/volume", {
        volume: Number(sl.value),
        testar: !!teste,
      });
      say(r.ok ? r.d.mensagem : r.d.erro || "Falha ao ajustar o volume.");
    };
    sl.oninput = () => {
      lb.textContent = sl.value + "%";
      volJ = Number(sl.value);
      clearTimeout(tm);
      tm = setTimeout(() => enviarVol(false), 300);
    };
    ts.onclick = () => {
      clearTimeout(tm);
      enviarVol(true);
    };
    row.append(sl, lb, ts);
    box.append(h, row);
    return box;
  }

  function desenhar() {
    el.replaceChildren();
    const intro = document.createElement("div");
    intro.className = "panel-intro";
    const titulo = document.createElement("strong");
    titulo.textContent = "Controles rápidos";
    const descricao = document.createElement("p");
    descricao.textContent = "Escolha Casa, TV ou PC para ver ações agrupadas.";
    intro.append(titulo, descricao);
    el.appendChild(intro);
    el.appendChild(blocoVolume());
    const s = document.createElement("div");
    s.className = "sub";
    for (const k of Object.keys(CTL)) {
      const b = document.createElement("button");
      b.className = "chip" + (k === sub ? " on" : "");
      b.textContent = k;
      b.onclick = () => {
        sub = k;
        ls.set("jv_sub", k);
        desenhar();
      };
      s.appendChild(b);
    }
    el.appendChild(s);
    for (const [t, bs] of CTL[sub]) {
      const h = document.createElement("div");
      h.className = "sec control-group-title";
      h.textContent = t;
      const g = document.createElement("div");
      g.className = "grid";
      for (const [l, a, d] of bs) {
        const b = document.createElement("button");
        b.className = "btn" + (d ? " danger" : "");
        b.textContent = l;
        b.onclick = () => run(l, a, d);
        g.appendChild(b);
      }
      el.append(h, g);
    }
    const m = document.createElement("div");
    m.className = "msgline";
    m.textContent = msg;
    el.appendChild(m);
  }
  desenhar();
  jget("/voz/volume")
    .then((d) => {
      volJ = d.volume;
      const slider = el.querySelector("input[type=range]"),
        label = slider && slider.nextElementSibling;
      if (slider) slider.value = d.volume;
      if (label) label.textContent = d.volume + "%";
    })
    .catch(() => {});
}

function paneVis(el) {
  el.classList.add("line-config-pane");
  el.innerHTML =
    '<div class="line-config-heading"><button class="chip" id="lineBack" type="button">\u2039 Voltar</button><span class="note">Seguran\u00e7a da c\u00e2mera inferior</span></div><div class="sec">Configurar linha</div><p class="note">Marque a linha sobre a imagem da câmera e escolha quando o Jarvis deve avisar. A direção aparece pela seta.</p>' +
    '<div class="line-camera-preview" style="position:relative;max-width:100%;margin:10px 0 14px;border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#050910;min-height:180px">' +
    '<video id="hq" autoplay playsinline muted style="display:block;width:100%;aspect-ratio:16/9;object-fit:fill"></video><canvas id="hc" style="position:absolute;inset:0;width:100%;height:100%;pointer-events:none"></canvas><div class="camera-overlay-status"><span id="lineLensBadge" class="camera-badge">LENTE INFERIOR · SEGURANÇA</span><span id="lineModeBadge" class="camera-badge">AGUARDANDO DEFESAS</span></div><span id="lineAreaBadge" class="camera-badge camera-area-badge">ÁREA IGNORADA · 0%</span><div id="hmsg" style="display:flex;position:absolute;inset:0;align-items:center;justify-content:center;padding:20px;background:rgba(0,0,0,.65);color:var(--text)">Conectando à câmera ao vivo…</div></div>' +
    '<p id="lineDetectionStatus" class="line-detection-status" role="status" aria-live="polite">Conferindo o detector nativo da câmera…</p>' +
    '<div class="row2" id="lineLensPicker" style="margin:6px 0 10px"><button class="chip on" id="lineLensBottom" type="button" hidden>Câmera de baixo</button><button class="chip" id="lineLensTop" type="button" hidden>Câmera de cima · visualização</button></div>' +
    '<div class="row2" style="margin-bottom:10px"><button class="chip on" id="hbasicTab" role="tab" aria-selected="true">Básico</button><button class="chip" id="hadvancedTab" role="tab" aria-selected="false">Avançado</button></div>' +
    '<div id="hl" role="tabpanel"></div><div id="ha" role="tabpanel" hidden></div>' +
    '<div class="row2" style="margin-top:12px"><button class="btn" id="hed">Editar linha</button><button class="btn" id="hcl">Apagar linha</button><button class="btn" id="hts">Testar alerta</button><button class="btn on" id="hsv">Salvar</button></div>' +
    '<div class="msgline" id="lineMessage" role="status"></div>';
  // Isola elementos desta aba
  const elementos = new Map(
    [...el.querySelectorAll("[id]")].map((item) => [item.id, item]),
  );
  const $ = (id) => elementos.get(id);

  $("lineBack").onclick = () => abrir("seg");
  let ativo = true,
    cfg = null,
    hud = {
      cruzamento: null,
      caixas: [],
      camera_movida: false,
      camera_posicao_validada: false,
      linha_ativa: false,
      referencia_disponivel: false,
      zona_topo_pct: null,
      conectada: false,
      deteccao_nativa: "aguardando retangulo amarelo",
      pessoas: 0,
      movimento: false,
    },
    editar = false,
    editarArea = false,
    carregando = false,
    backup = null,
    drag = null,
    playerLinha = null,
    lenteLinha = "baixo",
    areaSaveTimer = 0,
    areaRevision = 0,
    areaSaving = false;

  const nota = (t, ruim) => {
    const m = $("lineMessage");
    m.textContent = t;
    m.style.color = ruim ? "var(--bad)" : "var(--accent)";
  };

  const marcar = () => nota("Alterações não salvas.");
  // Salva area automaticamente
  const salvarAreaAutomaticamente = async () => {
    clearTimeout(areaSaveTimer);
    if (!cfg || areaSaving || !ativo) return;
    areaSaving = true;
    const revision = areaRevision,
      pedido = JSON.parse(JSON.stringify(cfg));
    try {
      const r = await post("/seguranca/linha", pedido);
      if (!ativo) return;
      if (revision !== areaRevision) return;
      if (r.ok) {
        cfg = r.d;
        atualizarModoLinha();
        desenhar();
        nota("Área ignorada salva; usada quando armado.");
      } else nota(r.d.erro || "Não foi possível salvar a área.", true);
    } finally {
      areaSaving = false;
      if (ativo && revision !== areaRevision)
        areaSaveTimer = setTimeout(salvarAreaAutomaticamente, 0);
    }
  };
  // Agenda salvar area
  const agendarSalvarArea = () => {
    areaRevision++;
    clearTimeout(areaSaveTimer);
    areaSaveTimer = setTimeout(salvarAreaAutomaticamente, 400);
  };
  const estIn =
    "background:var(--raise);border:1px solid var(--line);border-radius:8px;padding:7px";

  const kv = (box, rotulo, c) => {
    const r = document.createElement("div");
    r.className = "kv";
    const n = document.createElement("span");
    n.textContent = rotulo;
    r.append(n, c);
    box.appendChild(r);
  };

  const cBool = (o, k) => {
    const b = document.createElement("button");
    const pinta = () => {
      b.className = "btn" + (o[k] ? " on" : "");
      b.textContent = o[k] ? "Ligado" : "Desligado";
    };
    pinta();
    b.onclick = () => {
      o[k] = !o[k];
      if (k === "ativa") atualizarModoLinha();
      pinta();
      marcar();
      desenhar();
    };
    return b;
  };

  const cSel = (o, k, ops) => {
    const s = document.createElement("select");
    s.style.cssText = estIn;
    for (const [v, n] of ops) {
      const op = document.createElement("option");
      op.value = v;
      op.textContent = n;
      s.appendChild(op);
    }
    s.value = o[k];
    s.onchange = () => {
      o[k] = s.value;
      marcar();
      desenhar();
    };
    return s;
  };

  // Seleciona aba
  function selecionarAba(avancado) {
    $("hl").hidden = avancado;
    $("ha").hidden = !avancado;
    for (const [id, selecionada] of [
      ["hbasicTab", !avancado],
      ["hadvancedTab", avancado],
    ]) {
      $(id).classList.toggle("on", selecionada);
      $(id).setAttribute("aria-selected", String(selecionada));
    }
  }
  $("hbasicTab").onclick = () => selecionarAba(false);
  $("hadvancedTab").onclick = () => selecionarAba(true);

  const cNum = (chave, min, max, passo) => {
    const input = document.createElement("input");
    input.type = "number";
    input.min = min;
    input.max = max;
    input.step = passo;
    input.value = cfg[chave];
    input.style.cssText = estIn + ";width:96px";
    input.onchange = () => {
      const valor = Number(input.value);
      if (
        !input.value.trim() ||
        !Number.isFinite(valor) ||
        !input.checkValidity()
      ) {
        input.value = cfg[chave];
        nota("Informe um valor entre " + min + " e " + max + ".", true);
        return;
      }
      cfg[chave] = valor;
      marcar();
      desenhar();
    };
    return input;
  };

  const cArea = (chave) => {
    const box = document.createElement("div"),
      input = document.createElement("input"),
      valor = document.createElement("strong");
    box.className = "row2";
    box.style.alignItems = "center";
    input.type = "range";
    input.min = 0;
    input.max = 95;
    input.step = 1;
    input.value = cfg[chave];
    input.id = "area_" + chave;
    input.style.width = "min(260px, 60vw)";
    valor.id = "valor_" + chave;
    valor.textContent = cfg[chave] + "%";
    input.oninput = () => {
      cfg[chave] = Number(input.value);
      valor.textContent = input.value + "%";
      atualizarModoLinha();
      marcar();
      desenhar();
      agendarSalvarArea();
    };
    box.append(input, valor);
    return box;
  };

  const areaAtualKey = () => "zona_topo_pct";
  // Atualiza modo linha
  const atualizarModoLinha = () => {
    if (!cfg) return;
    const linhaAtiva = Boolean(
      hud.linha_ativa &&
      hud.camera_posicao_validada &&
      cfg.ativa &&
      cfg.definida,
    );
    const referenciaAusente = Boolean(
      cfg.definida && !hud.referencia_disponivel,
    );
    const areaAtual = Number(cfg.zona_topo_pct ?? 65);
    const seloModo = $("lineModeBadge"),
      seloArea = $("lineAreaBadge"),
      resumoArea = $("lineIgnoreSummary"),
      resumoModo = $("lineModeSummary");
    if (seloModo)
      seloModo.textContent =
        lenteLinha === "cima"
          ? "CÂMERA SUPERIOR · SÓ VISUALIZAÇÃO"
          : linhaAtiva
            ? "DEFESAS ARMADAS · LINHA ATIVA · CÂMERA FIXA"
            : hud.armado && referenciaAusente
              ? "DEFESAS ARMADAS · SALVE A LINHA COM A CÂMERA ATIVA"
              : hud.armado
                ? "DEFESAS ARMADAS · AGUARDANDO CÂMERA FIXA"
                : "DEFESAS DESARMADAS";
    if (seloArea) {
      seloArea.hidden = lenteLinha === "cima";
      seloArea.textContent = "ÁREA IGNORADA · " + areaAtual + "%";
    }
    if (resumoArea)
      resumoArea.textContent =
        areaAtual + "% · aplicada com as defesas armadas";
    if (resumoModo)
      resumoModo.textContent = linhaAtiva
        ? "Com o Protocolo Torre Stark armado e a câmera fixa, o Jarvis avisa ao detectar uma pessoa na área ou ao cruzar a linha."
        : hud.armado && referenciaAusente
          ? "Não há referência visual da câmera para validar a linha. Ative a câmera e salve a configuração da linha."
          : hud.armado
            ? "A linha de segurança aguarda a câmera fixa na posição validada. A detecção de pessoas continua usando a lente inferior."
            : "A defesa está desarmada. A câmera de cima é apenas para visualização; a detecção de segurança usa a lente inferior.";
  };
  // Atualiza estado deteccao
  const atualizarStatusDeteccao = () => {
    const status = $("lineDetectionStatus");
    if (!status) return;
    if (lenteLinha === "cima") {
      status.dataset.state = "info";
      status.textContent =
        "A lente superior serve apenas para visualização; a segurança usa a lente inferior.";
    } else if (!hud.conectada) {
      status.dataset.state = "offline";
      status.textContent =
        "Câmera inferior desconectada. O detector nativo não pode confirmar pessoas.";
    } else if (Number(hud.pessoas) > 0) {
      status.dataset.state = "person";
      status.textContent = `IA detectou ${hud.pessoas} pessoa(s) presentes no quadro.`;
    } else if (hud.movimento) {
      status.dataset.state = "waiting";
      status.textContent =
        "Movimento e gravação ativos; aguardando o retângulo amarelo da câmera para confirmar pessoa.";
    } else {
      status.dataset.state = "waiting";
      status.textContent =
        "Detector nativo aguardando o retângulo amarelo de pessoa da câmera.";
    }
  };

  // Monta form
  function montarForm() {
    const L = $("hl");
    L.replaceChildren();
    const comportamento = document.createElement("p");
    comportamento.className = "note";
    comportamento.textContent =
      "Com o Protocolo Torre Stark armado, a c\u00e2mera fica parada no port\u00e3o. O Jarvis avisa ao detectar uma pessoa na \u00e1rea monitorada ou ao cruzar a linha.";
    L.appendChild(comportamento);
    kv(
      L,
      "Direção do cruzamento",
      cSel(cfg, "sentido", [
        ["ambos", "Ambos os sentidos"],
        ["positivo", "Direção da seta 1"],
        ["negativo", "Direção da seta 2"],
      ]),
    );
    const A = $("ha");
    A.replaceChildren();
    const area = document.createElement("strong");
    area.id = "lineIgnoreSummary";
    area.textContent = "";
    kv(A, "Área ignorada", area);
    kv(A, "Ignorar parte superior quando armado", cArea("zona_topo_pct"));
    kv(
      A,
      "Intervalo entre alertas da linha (segundos)",
      cNum("cooldown_s", 0, 600, 1),
    );

    const arrastarArea = document.createElement("button");
    arrastarArea.id = "lineAreaDragButton";
    arrastarArea.className = "btn";
    arrastarArea.textContent = editarArea
      ? "Concluir ajuste da área"
      : "Ajustar área pela imagem";
    arrastarArea.onclick = () => {
      if (lenteLinha === "cima") escolherLenteLinha("baixo");
      editarArea = !editarArea;
      if (editarArea) editar = false;
      arrastarArea.classList.toggle("on", editarArea);
      arrastarArea.textContent = editarArea
        ? "Concluir ajuste da área"
        : "Ajustar área pela imagem";
      $("hed").textContent = "Editar linha";
      $("hed").classList.remove("on");
      cv.style.pointerEvents = editarArea ? "auto" : editar ? "auto" : "none";
      cv.style.cursor = editarArea ? "ns-resize" : "default";
      desenhar();
    };
    A.appendChild(arrastarArea);
    const dica = document.createElement("p");
    dica.className = "note";
    dica.textContent =
      "Ajuste a área pelos controles ou arraste o limite pontilhado. O corte é aplicado à detecção de pessoas enquanto as defesas estão armadas.";
    A.appendChild(dica);
    const modo = document.createElement("p");
    modo.className = "note";
    modo.id = "lineModeSummary";
    modo.textContent =
      "A segurança usa somente a lente inferior. O comportamento e a área ignorada acompanham o modo ativo.";
    A.appendChild(modo);
  }

  function seta(c, x, y, dx, dy, cor, rot) {
    const tam = 30,
      ex = x + dx * tam,
      ey = y + dy * tam,
      a = Math.atan2(dy, dx),
      k = 9;
    c.strokeStyle = cor;
    c.fillStyle = cor;
    c.lineWidth = 2.5;
    c.setLineDash([]);
    c.beginPath();
    c.moveTo(x, y);
    c.lineTo(ex, ey);
    c.stroke();
    c.beginPath();
    c.moveTo(ex, ey);
    c.lineTo(ex - k * Math.cos(a - 0.45), ey - k * Math.sin(a - 0.45));
    c.lineTo(ex - k * Math.cos(a + 0.45), ey - k * Math.sin(a + 0.45));
    c.closePath();
    c.fill();
    if (rot) {
      c.font = "bold 12px system-ui";
      c.fillText(rot, ex + dx * 10 - 4, ey + dy * 10 + 4);
    }
  }

  function desenhar() {
    const img = $("hq"),
      cv = $("hc");
    if (!ativo || !cfg || !img || !cv) return;
    const w = cv.clientWidth,
      h = cv.clientHeight;
    if (!w || !h) return;
    const d = devicePixelRatio || 1;
    if (cv.width !== Math.round(w * d) || cv.height !== Math.round(h * d)) {
      cv.width = Math.round(w * d);
      cv.height = Math.round(h * d);
    }
    const c = cv.getContext("2d");
    c.setTransform(d, 0, 0, d, 0, 0);
    c.clearRect(0, 0, w, h);
    if (lenteLinha === "cima") return;
    const H = cfg.hud || {},
      cz = hud.cruzamento,
      alarme = !!(cz && cz.idade_s < (H.flash_s || 3));
    const cor = alarme ? H.cor_alarme : H.cor_linha;

    const areaIgnorada = Number(cfg[areaAtualKey()] ?? hud.zona_topo_pct ?? 0);
    if (areaIgnorada > 0) {
      const zy = (h * areaIgnorada) / 100;
      c.fillStyle = "rgba(0,0,0,.5)";
      c.fillRect(0, 0, w, zy);
      c.strokeStyle = editarArea ? "#000000" : "#8aa";
      c.lineWidth = editarArea ? 3 : 1.5;
      c.setLineDash([6, 5]);
      c.beginPath();
      c.moveTo(0, zy);
      c.lineTo(w, zy);
      c.stroke();
      c.setLineDash([]);
      c.fillStyle = editarArea ? "#F4F3F8" : "#cde";
      c.font = "bold 11px system-ui";
      c.fillText(
        (editarArea ? "ARRASTE O LIMITE · " : "área ignorada · ") +
          areaIgnorada +
          "%",
        8,
        Math.max(14, zy - 6),
      );
    }

    if (H.caixas)
      for (const b of hud.caixas || []) {
        const x = b.x1 * w,
          y = b.y1 * h,
          bw = (b.x2 - b.x1) * w,
          bh = (b.y2 - b.y1) * h,
          cc = alarme ? H.cor_alarme : "#5fd39a";
        c.setLineDash([]);
        c.strokeStyle = cc;
        c.lineWidth = 2;
        c.strokeRect(x, y, bw, bh);
        c.fillStyle = cc;
        c.beginPath();
        c.arc(x + bw / 2, y + bh, 4, 0, 7);
        c.fill();
        if (H.rotulos) {
          c.font = "bold 11px system-ui";
          c.fillText("PESSOA " + b.id, x + 2, Math.max(11, y - 4));
        }
      }

    if (cfg.definida && (hud.linha_ativa || editar)) {
      const ax = cfg.p1[0] * w,
        ay = cfg.p1[1] * h,
        bx = cfg.p2[0] * w,
        by = cfg.p2[1] * h,
        len = Math.hypot(bx - ax, by - ay);
      c.strokeStyle = cor;
      c.lineWidth = H.espessura;
      c.setLineDash(editar ? [] : [12, 7]);
      c.beginPath();
      c.moveTo(ax, ay);
      c.lineTo(bx, by);
      c.stroke();
      c.setLineDash([]);
      if (len > 2) {
        const ux = (bx - ax) / len,
          uy = (by - ay) / len,
          nx = -uy,
          ny = ux,
          mx = (ax + bx) / 2,
          my = (ay + by) / 2;
        if (H.seta || editar) {
          if (cfg.sentido !== "negativo")
            seta(c, mx, my, nx, ny, cor, cfg.sentido === "positivo" ? "1" : "");
          if (cfg.sentido !== "positivo")
            seta(
              c,
              mx,
              my,
              -nx,
              -ny,
              cor,
              cfg.sentido === "negativo" ? "2" : "",
            );
        }
      }
      for (const [p, n] of [
        [[ax, ay], "A"],
        [[bx, by], "B"],
      ]) {
        c.fillStyle = cor;
        c.beginPath();
        c.arc(p[0], p[1], editar ? 9 : 6, 0, 7);
        c.fill();
        c.fillStyle = "#111";
        c.font = "bold 10px system-ui";
        c.fillText(n, p[0] - 3.5, p[1] + 3.5);
      }
    }

    if (hud.camera_movida && !alarme) {
      c.fillStyle = "rgba(0,0,0,.65)";
      c.fillRect(0, 0, w, 28);
      c.fillStyle = "#62d3ff";
      c.font = "bold 13px system-ui";
      c.fillText("CÂMERA FORA DA POSIÇÃO · LINHA PAUSADA", 10, 19);
    }

    if (alarme) {
      c.globalAlpha = 0.75 + 0.25 * Math.sin(Date.now() / 120);
      c.fillStyle = H.cor_alarme;
      c.fillRect(0, 0, w, 28);
      c.globalAlpha = 1;
      c.fillStyle = "#fff";
      c.font = "bold 13px system-ui";
      c.fillText(
        `⚠ LINHA CRUZADA · ${cz.sentido === "negativo" ? "SENTIDO 2" : "SENTIDO 1"} · ${String(cz.hora || "").slice(11, 19)}`,
        10,
        19,
      );
      c.strokeStyle = H.cor_alarme;
      c.lineWidth = 4;
      c.setLineDash([]);
      c.strokeRect(2, 2, w - 4, h - 4);
    }
  }

  const cv = $("hc"),
    img = $("hq");
  // Atualiza seletor lente linha
  const atualizarSeletorLenteLinha = () => {
    const seletor = $("lineLensPicker");
    const badge = $("lineLensBadge");
    if (seletor) seletor.hidden = !playerLinha?.configuracao.duas_lentes;
    if (badge)
      badge.textContent =
        lenteLinha === "baixo"
          ? "LENTE INFERIOR \u00b7 SEGURAN\u00c7A"
          : "LENTE SUPERIOR \u00b7 S\u00d3 VISUALIZA\u00c7\u00c3O";
    $("lineLensBottom").classList.toggle("on", lenteLinha === "baixo");
    $("lineLensTop").classList.toggle("on", lenteLinha === "cima");
  };

  const escolherLenteLinha = (lente) => {
    lenteLinha = lente === "cima" ? "cima" : "baixo";
    playerLinha?.definirLente(lenteLinha);
    if (lenteLinha === "cima") {
      editar = false;
      editarArea = false;
      cv.style.pointerEvents = "none";
      cv.style.cursor = "default";
      $("hed").textContent = "Editar linha";
      $("hed").classList.remove("on");
      const botaoArea = $("lineAreaDragButton");
      if (botaoArea) {
        botaoArea.textContent = "Ajustar \u00e1rea pela imagem";
        botaoArea.classList.remove("on");
      }
    }
    atualizarSeletorLenteLinha();
    atualizarModoLinha();
    desenhar();
  };
  $("lineLensBottom").onclick = () => escolherLenteLinha("baixo");
  $("lineLensTop").onclick = () => escolherLenteLinha("cima");
  // Converte posição na imagem
  const pos = (e) => {
    const r = cv.getBoundingClientRect();
    return [
      Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
      Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
    ];
  };
  cv.style.pointerEvents = "none";

  const mudarAreaPelaImagem = (y) => {
    const chave = areaAtualKey();
    const valor = Math.round(Math.max(0, Math.min(0.95, y)) * 100);
    cfg[chave] = valor;
    const input = $("area_" + chave),
      texto = $("valor_" + chave);
    if (input) input.value = valor;
    if (texto) texto.textContent = valor + "%";
    atualizarModoLinha();
    desenhar();
    agendarSalvarArea();
  };
  cv.onpointerdown = (e) => {
    if (!cfg) return;
    const [x, y] = pos(e),
      r = cv.getBoundingClientRect();
    if (editarArea) {
      const limite = Number(cfg[areaAtualKey()]) / 100;
      if (Math.abs(y - limite) * r.height > 24) {
        nota("Arraste o limite pontilhado para mudar a \u00e1rea ignorada.");
        return;
      }
      drag = "area";
      cv.setPointerCapture(e.pointerId);
      mudarAreaPelaImagem(y);
      return;
    }
    if (!editar) return;

    const perto = (p) =>
      Math.hypot((p[0] - x) * r.width, (p[1] - y) * r.height) < 24;
    backup = { p1: [...cfg.p1], p2: [...cfg.p2], definida: cfg.definida };
    if (cfg.definida && perto(cfg.p1)) drag = "p1";
    else if (cfg.definida && perto(cfg.p2)) drag = "p2";
    else {
      cfg.p1 = [x, y];
      cfg.p2 = [x, y];
      cfg.definida = true;
      drag = "p2";
    }
    cv.setPointerCapture(e.pointerId);
    desenhar();
  };
  cv.onpointermove = (e) => {
    if (!drag) return;
    const [x, y] = pos(e);
    if (drag === "area") {
      mudarAreaPelaImagem(y);
      return;
    }
    cfg[drag] = [x, y];
    desenhar();
  };
  cv.onpointerup = () => {
    if (!drag) return;
    drag = null;
    if (editarArea) {
      marcar();
      agendarSalvarArea();
      return;
    }
    const curta =
      Math.hypot(cfg.p2[0] - cfg.p1[0], cfg.p2[1] - cfg.p1[1]) < 0.03;
    if (curta && backup) {
      cfg.p1 = backup.p1;
      cfg.p2 = backup.p2;
      cfg.definida = backup.definida;
      nota("Linha muito curta: arraste mais.", true);
    } else marcar();
    desenhar();
  };

  $("hed").onclick = () => {
    if (lenteLinha === "cima") escolherLenteLinha("baixo");
    editar = !editar;
    if (editar) editarArea = false;
    const bArea = $("lineAreaDragButton");
    if (bArea) {
      bArea.textContent = "Ajustar \u00e1rea pela imagem";
      bArea.classList.remove("on");
    }
    $("hed").textContent = editar
      ? "Concluir edi\u00e7\u00e3o"
      : "Editar linha";
    $("hed").classList.toggle("on", editar);
    cv.style.pointerEvents = editar ? "auto" : "none";
    cv.style.cursor = editar ? "crosshair" : "default";
    desenhar();
  };
  $("hcl").onclick = () => {
    if (!cfg) return;
    cfg.definida = false;
    cfg.ativa = false;
    atualizarModoLinha();
    montarForm();
    marcar();
    desenhar();
  };
  $("hts").onclick = async () => {
    const r = await post("/seguranca/linha/testar");
    nota(r.ok ? "HUD de teste acionado." : r.d.erro || "Falhou.", !r.ok);
    atualizar();
  };
  $("hsv").onclick = async () => {
    if (!cfg) return;
    clearTimeout(areaSaveTimer);
    const r = await post("/seguranca/linha", cfg);
    if (r.ok) {
      cfg = r.d;
      atualizarModoLinha();
      montarForm();
      desenhar();
      nota(
        "Salvo. A linha e a \u00e1rea ignorada ser\u00e3o usadas quando o Protocolo Torre Stark estiver armado.",
      );
    } else nota(r.d.erro || "Não foi possível salvar.", true);
  };

  async function atualizar() {
    if (!ativo) return;
    try {
      hud = await jget("/seguranca/hud");
    } catch (x) {}
    if (!ativo) return;
    atualizarModoLinha();
    atualizarStatusDeteccao();
    desenhar();
    if (!carregando && !playerLinha) {
      carregando = true;
      const aviso = $("hmsg");
      try {
        playerLinha = await conectarVideoCamera(img, lenteLinha);
        if (!ativo) {
          playerLinha?.fechar();
          playerLinha = null;
          return;
        }
        atualizarSeletorLenteLinha();
        if (aviso) aviso.style.display = "none";
      } catch (erro) {
        if (aviso) {
          aviso.style.display = "flex";
          aviso.textContent = "Não foi possível abrir o vídeo ao vivo da A28.";
        }
      }
      carregando = false;
      desenhar();
    }
  }
  jget("/seguranca/linha")
    .then((d) => {
      if (!ativo) return;
      cfg = d;
      atualizarModoLinha();
      montarForm();
      desenhar();
      atualizar();
    })
    .catch(() => {
      if (ativo) nota("Falha ao carregar a linha.", true);
    });

  const redimensionar = () => desenhar();
  addEventListener("resize", redimensionar);
  return {
    poll: atualizar,
    every: 800,
    cleanup: () => {
      ativo = false;
      clearTimeout(areaSaveTimer);
      playerLinha?.fechar();
      playerLinha = null;
      cv.onpointerdown = cv.onpointermove = cv.onpointerup = null;
      removeEventListener("resize", redimensionar);
    },
  };
}

// Exibe registros do aplicativo
function paneLog(el) {
  el.classList.add("logs-pane");
  const est = { nivel: "INFO", mod: "", pausado: false };
  el.innerHTML =
    '<div class="logbar" id="lvl"></div>' +
    '<div class="row2"><input id="lq" maxlength="80" placeholder="Filtrar (ex.: vigia, seguranca, erro)"><button class="btn" id="lp">Pausar</button></div>' +
    '<div class="logbar" style="margin-top:8px" id="lmod"></div>' +
    '<div class="logbox" id="lbx"><div class="t">Carregando…</div></div>' +
    '<div class="row2" style="margin-top:8px"><button class="btn" id="lc">Copiar</button><span class="msgline" id="lm"></span></div>';
  // Isola elementos desta aba
  const elementos = new Map(
    [...el.querySelectorAll("[id]")].map((item) => [item.id, item]),
  );
  const $ = (id) => elementos.get(id);

  const NIVEIS = [
    ["Tudo", "INFO"],
    ["Avisos", "WARNING"],
    ["Erros", "ERROR"],
  ];
  const MODS = [
    ["Todos", ""],
    ["Vigia", "vigia"],
    ["Segurança", "seguranca"],
    ["Presença", "presenca"],
    ["Câmera", "camera"],
  ];

  function chips(id, lista, atual, set) {
    $(id).replaceChildren(
      ...lista.map(([n, v]) => {
        const b = document.createElement("button");
        b.className = "chip" + (v === atual ? " on" : "");
        b.textContent = n;
        b.onclick = () => {
          set(v);
          chips(id, lista, v, set);
          atualizar();
        };
        return b;
      }),
    );
  }
  chips("lvl", NIVEIS, est.nivel, (v) => (est.nivel = v));
  chips("lmod", MODS, est.mod, (v) => (est.mod = v));
  let ultimas = [];

  async function atualizar() {
    if (est.pausado) return;
    const q = $("lq").value.trim() || est.mod;
    let d;
    try {
      d = await jget(
        "/logs/arquivo?limite=400&nivel=" +
          est.nivel +
          "&q=" +
          encodeURIComponent(q),
      );
    } catch (x) {
      $("lm").textContent = "Servidor não respondeu.";
      return;
    }
    $("lm").textContent = "";
    const box = $("lbx"),
      fim = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
    ultimas = d.linhas || [];

    const conteudo = ultimas.length
      ? ultimas
          .map(
            (l) =>
              `<div class="ln ${esc(l.nivel)}"><span class="t">${esc(l.hora)}</span> <span class="n">${esc(l.nivel.slice(0, 4))}</span> <span class="m">${esc(l.modulo)}</span> ${esc(l.msg)}</div>`,
          )
          .join("")
      : '<div class="t">Nada com esse filtro.</div>';
    if (box.innerHTML !== conteudo) box.innerHTML = conteudo;
    if (fim) box.scrollTop = box.scrollHeight;
  }
  $("lq").oninput = () => {
    clearTimeout($("lq")._t);
    $("lq")._t = setTimeout(atualizar, 300);
  };
  $("lp").onclick = () => {
    est.pausado = !est.pausado;
    $("lp").textContent = est.pausado ? "Retomar" : "Pausar";
    $("lp").classList.toggle("on", est.pausado);
    if (!est.pausado) atualizar();
  };
  $("lc").onclick = async () => {
    const t = ultimas
      .map((l) => `${l.data} ${l.hora} ${l.nivel} ${l.modulo}: ${l.msg}`)
      .join("\n");
    $("lm").textContent = (await copiarTexto(t))
      ? "Log copiado para a \u00e1rea de transfer\u00eancia."
      : "A c\u00f3pia foi bloqueada pelo sistema.";
  };
  atualizar();
  return { poll: atualizar, every: 2000 };
}

// Lista comandos disponíveis
function paneComandos(el) {
  el.classList.add("commands-pane");
  const grupos = [
    [
      "Pesquisa",
      [
        "pesquisar no Google por notícias de tecnologia",
        "pesquisar no YouTube por música do Queen",
        "pesquisar na Wikipédia por Santos Dumont",
      ],
    ],
    [
      "TV e mídia",
      [
        "ligar a TV",
        "desligar a TV",
        "aumentar o volume",
        "abaixar o volume",
        "colocar o volume em 30",
        "próximo canal",
        "canal anterior",
        "abrir Netflix na TV",
      ],
    ],
    [
      "Segurança Torre Stark",
      [
        "ativar Torre Stark",
        "desativar Torre Stark",
        "status da segurança",
        "quantas detecções de pessoas hoje",
        "últimos eventos de segurança",
      ],
    ],
    ["Análise visual com LM Studio", ["analisar câmera", "analisar tela"]],
    [
      "Navegador controlado pelo Jarvis",
      [
        "abrir navegador",
        "abrir aba",
        "fechar navegador",
        "listar abas",
        "selecionar aba 2",
        "parar carregamento",
        "pesquisar no YouTube por música do Queen",
        "clicar no vídeo [título exato]",
        "abrir https://example.com",
        "abrir nova aba",
        "fechar aba",
        "próxima aba",
        "aba anterior",
        "voltar página",
        "avançar página",
        "atualizar página",
      ],
    ],
    [
      "Clima",
      [
        "qual é a previsão do tempo",
        "previsão para amanhã",
        "previsão estendida",
        "comparar o clima de amanhã com hoje",
        "resumo completo do clima",
      ],
    ],
    [
      "Rotinas",
      [
        "cheguei em casa",
        "confirmar saída",
        "ativar música da chegada",
        "desativar música da chegada",
        "abrir aplicativos ao chegar",
        "fechar aplicativos ao sair",
      ],
    ],
    [
      "Mensagens e pedidos pessoais",
      [
        "mandar mensagem para [nome] [texto]",
        "criar uma nota com [texto]",
        "anotar [texto]",
        "o que tenho na agenda hoje",
        "marcar um compromisso amanhã às 15 horas",
        "ler minhas notícias",
        "Jarvis, resumo do dia",
        "leia minha agenda",
        "leia minhas notas",
        "leia meus e-mails",
        "tem e-mail para responder",
        "responder e-mail",
        "pode enviar Jarvis",
        "enviar um e-mail para [contato]",
      ],
    ],
    [
      "Conversa",
      ["lembre disso: [informação]", "o que você lembra sobre [assunto]?"],
    ],
  ];
  const recentes = [
    "Jarvis, resumo do dia",
    "cheguei em casa",
    "leia as duas not\u00edcias principais",
    "leia minha agenda",
    "leia minhas notas",
    "tem e-mail para responder",
    "anote [o que devo lembrar]",
    "pode salvar",
    "pode enviar Jarvis",
    "abrir c\u00e2mera ao vivo",
    "configurar linha de seguran\u00e7a",
  ];
  let somenteRecentes = false;
  el.innerHTML =
    '<div class="sec">Comandos diretos e exemplos de pedidos por voz. Recursos pessoais dependem das integrações habilitadas.</div><div class="row2" id="voiceViews" style="margin:8px 0 12px"></div><input id="voiceSearch" type="search" placeholder="Filtrar comandos" aria-label="Filtrar comandos" style="width:100%;margin:0 0 12px;padding:10px;background:var(--raise);border:1px solid var(--line);border-radius:9px;color:var(--text)"><div id="voiceGroups"></div>';
  const abas = [
    [false, "Todos os comandos"],
    [true, "Adicionados recentemente"],
  ];
  $("voiceViews").replaceChildren(
    ...abas.map(([valor, rotulo]) => {
      const botao = document.createElement("button");
      botao.className = "chip" + (valor === somenteRecentes ? " on" : "");
      botao.textContent = rotulo;
      botao.onclick = () => {
        somenteRecentes = valor;
        for (const [ativo, texto] of abas) {
          const aba = Array.from($("voiceViews").children).find(
            (item) => item.textContent === texto,
          );
          if (aba) aba.classList.toggle("on", ativo === somenteRecentes);
        }
        desenhar();
      };
      return botao;
    }),
  );

  const desenhar = () => {
    const termo = $("voiceSearch").value.trim().toLocaleLowerCase("pt-BR"),
      raiz = $("voiceGroups");
    raiz.replaceChildren();
    const fontes = somenteRecentes
      ? [["Adicionados recentemente", recentes]]
      : grupos;
    for (const [nome, frases] of fontes) {
      const filtradas = frases.filter(
        (frase) =>
          !termo ||
          (nome + " " + frase).toLocaleLowerCase("pt-BR").includes(termo),
      );
      if (!filtradas.length) continue;
      const titulo = document.createElement("div");
      titulo.className = "sec";
      titulo.textContent = nome;
      raiz.appendChild(titulo);
      const lista = document.createElement("div");
      lista.style.cssText =
        "display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:8px";
      for (const frase of filtradas) {
        const item = document.createElement("div");
        item.className = "kv";
        item.style.cssText =
          "min-height:42px;padding:10px 12px;border:1px solid var(--line);border-radius:9px;background:var(--raise)";
        item.textContent = frase;
        lista.appendChild(item);
      }
      raiz.appendChild(lista);
    }
    if (!raiz.childElementCount)
      raiz.textContent = "Nenhum exemplo corresponde à busca.";
  };
  $("voiceSearch").oninput = desenhar;
  desenhar();
}

// Organiza configurações do Jarvis
function paneCfg(el) {
  el.classList.add("settings-pane");
  el.innerHTML =
    "" +
    '<details class="settings-group" id="connectionGroup"><summary class="settings-group-heading"><span class="sec" id="connectionSettings">Rede</span></summary><div id="connectionInfo"><div class="kv"><span>Buscando IP e porta…</span></div></div></details>' +
    '<details class="settings-group" id="gmailGroup"><summary class="settings-group-heading"><span class="sec" id="gmailSettings">Gmail</span></summary>' +
    '<p class="note">Conecte sua conta para usar o Gmail com o Jarvis.</p><details class="settings-help"><summary>Ajuda de configuração</summary><p>No Google Cloud, ative a Gmail API, configure a tela de consentimento OAuth e crie um cliente OAuth para aplicativo de computador. Se necessário, adicione sua conta como usuária de teste. O Jarvis pedirá confirmação antes de enviar mensagens.</p></details>' +
    '<div class="row2"><input id="gmailClientId" autocomplete="off" placeholder="ID do cliente OAuth do Google" aria-label="ID do cliente OAuth do Gmail"><input id="gmailClientSecret" type="password" autocomplete="new-password" placeholder="Segredo do cliente, se fornecido" aria-label="Segredo do cliente OAuth do Gmail"></div>' +
    '<div class="row2 settings-actions"><button class="btn" id="gmailSave">Salvar integração Gmail</button><button class="btn on" id="gmailConnect">Conectar conta Google</button><button class="btn" id="gmailDisconnect">Desconectar</button></div>' +
    '<div class="note">Retorno local: <code id="gmailRedirect">http://127.0.0.1:5678</code></div><div class="msgline" id="gmailStatus"></div></details>' +
    '<details class="settings-group" id="preferencesGroup"><summary class="settings-group-heading"><span class="sec" id="preferencesSettings">Sistema</span></summary><div class="msgline" id="cm"></div><div id="cp"><div class="kv"><span>Carregando…</span></div></div></details>';
  // Isola elementos desta aba
  const elementos = new Map(
    [...el.querySelectorAll("[id]")].map((item) => [item.id, item]),
  );
  const $ = (id) => elementos.get(id);

  const cameraPtzSettings = document.createElement("details");
  cameraPtzSettings.id = "cameraPtzSettings";
  cameraPtzSettings.className = "settings-group settings-camera-ptz";
  cameraPtzSettings.innerHTML =
    '<summary class="settings-group-heading"><span class="sec">Câmera e PTZ</span></summary><p class="note">Ajuste a conexão e movimente a câmera.</p>' +
    '<div class="settings-ptz-preview" id="ptzPreview"><video id="ptzFrame" autoplay playsinline muted></video><div id="ptzPreviewMessage" class="security-frame-message">Conectando à câmera ao vivo…</div><div class="settings-ptz-preview-actions"><button class="btn" id="ptzAudioOutput">Ativar áudio</button><button class="btn" id="ptzLensTop" hidden>Câmera de cima</button><button class="btn on" id="ptzLensBottom" hidden>Câmera de baixo</button></div></div><div class="msgline" id="ptzAudioStatus" role="status"></div>' +
    '<div class="security-onvif"><label>IP ou nome da câmera<input id="onvifHost" autocomplete="off" placeholder="Ex.: 192.168.1.50"></label><label>Porta ONVIF<input id="onvifPort" type="number" min="1" max="65535" value="8899"></label><label>Usuário<input id="onvifUser" autocomplete="username" placeholder="Usuário do iCSee"></label><label>Senha<input id="onvifPassword" type="password" autocomplete="new-password" placeholder="Deixe vazio para manter a salva"></label><button class="btn on" id="onvifSave">Salvar e conectar</button></div><div id="onvifStatus" class="msgline" role="status"></div>' +
    '<div class="settings-ptz-manual"><div><strong>Movimento manual</strong><p class="note">Cada toque envia um movimento curto e para a câmera automaticamente.</p></div><div class="security-manual-ptz" id="manualPtz"></div></div><div id="manualPtzStatus" class="msgline" role="status" aria-live="polite">Aguardando capacidades ONVIF confirmadas.</div>' +
    "";
  cameraPtzSettings
    .querySelectorAll("[id]")
    .forEach((item) => elementos.set(item.id, item));

  $("gmailGroup").after(cameraPtzSettings);
  el.querySelectorAll(".settings-nav [data-target]").forEach(
    (botao) =>
      (botao.onclick = () => {
        const target = $(botao.dataset.target);
        if (target instanceof HTMLDetailsElement) target.open = true;
        target?.scrollIntoView({ behavior: "smooth", block: "start" });
      }),
  );
  let ptzPreviewPlayer = null,
    ptzPreviewConnecting = false,
    ptzPreviewActive = true,
    ptzPreviewLens = "baixo";
  // Conecta previa PTZ
  async function conectarPreviaPtz() {
    if (
      !ptzPreviewActive ||
      !cameraPtzSettings.open ||
      ptzPreviewPlayer ||
      ptzPreviewConnecting
    )
      return;
    ptzPreviewConnecting = true;
    const video = $("ptzFrame"),
      mensagem = $("ptzPreviewMessage");
    mensagem.hidden = false;
    mensagem.textContent = "Conectando à câmera ao vivo…";
    try {
      const player = await conectarVideoCamera(video, ptzPreviewLens);
      if (!ptzPreviewActive) {
        player.fechar();
        return;
      }
      ptzPreviewPlayer = player;
      $("ptzLensTop").hidden = !player.configuracao.duas_lentes;
      $("ptzLensBottom").hidden = !player.configuracao.duas_lentes;
      mensagem.hidden = true;
    } catch (_) {
      mensagem.textContent =
        "Não foi possível conectar ao vídeo ao vivo. Tentando novamente…";
    } finally {
      ptzPreviewConnecting = false;
    }
  }

  const mudarLentePtz = (lente) => {
    ptzPreviewLens = lente === "cima" ? "cima" : "baixo";
    ptzPreviewPlayer?.definirLente(ptzPreviewLens);
    $("ptzLensTop").classList.toggle("on", ptzPreviewLens === "cima");
    $("ptzLensBottom").classList.toggle("on", ptzPreviewLens === "baixo");
  };
  $("ptzLensTop").onclick = () => mudarLentePtz("cima");
  $("ptzLensBottom").onclick = () => mudarLentePtz("baixo");
  $("ptzAudioOutput").onclick = () =>
    alternarAudioCamera(
      $("ptzFrame"),
      $("ptzAudioOutput"),
      $("ptzAudioStatus"),
    );

  cameraPtzSettings.ontoggle = () => {
    if (cameraPtzSettings.open) conectarPreviaPtz();
    else {
      ptzPreviewPlayer?.fechar();
      ptzPreviewPlayer = null;
    }
  };
  conectarPreviaPtz();
  for (const [comando, rotulo] of [
    ["up", "\u2191"],
    ["left", "\u2190"],
    ["stop", "Parar"],
    ["right", "\u2192"],
    ["down", "\u2193"],
    ["zoom_out", "Zoom \u2212"],
    ["zoom_in", "Zoom +"],
  ]) {
    const botao = document.createElement("button");
    botao.className = "btn";
    botao.dataset.ptz = comando;
    botao.textContent = rotulo;
    botao.setAttribute(
      "aria-label",
      comando === "stop" ? "Parar câmera" : "Comando PTZ " + comando,
    );
    botao.disabled = true;
    $("manualPtz").appendChild(botao);
  }
  let cameraPtzOnline = false;
  // Carrega PTZ configuracao
  async function carregarPtzConfiguracao() {
    try {
      const dados = await jget("/seguranca/onvif");
      cameraPtzOnline = dados.ptz_estado === "conectado";
      $("onvifHost").value = dados.host || "";
      $("onvifPort").value = dados.porta || 8899;
      $("onvifUser").value = dados.usuario || "";
      $("onvifStatus").textContent = dados.senha_configurada
        ? "Acesso salvo neste computador \u00b7 " + dados.ptz_estado
        : "Informe o usuário e a senha ONVIF da câmera.";
      cameraPtzSettings
        .querySelectorAll("#manualPtz [data-ptz]")
        .forEach((botao) => {
          botao.disabled =
            !cameraPtzOnline || !dados.capacidades?.[botao.dataset.ptz];
        });
      $("manualPtzStatus").textContent = cameraPtzOnline
        ? "ONVIF conectado; comandos limitados às capacidades anunciadas pela câmera."
        : "Controles aguardam conexão ONVIF/PTZ.";
      return dados;
    } catch (_) {
      $("onvifStatus").textContent =
        "Não foi possível consultar o acesso ONVIF.";
      return null;
    }
  }
  $("onvifSave").onclick = async () => {
    const b = $("onvifSave");
    b.disabled = true;
    $("onvifStatus").textContent = "Salvando o acesso e conectando...";
    const resultado = await post("/seguranca/onvif", {
      host: $("onvifHost").value,
      porta: Number($("onvifPort").value),
      usuario: $("onvifUser").value,
      senha: $("onvifPassword").value,
    });
    b.disabled = false;
    $("onvifStatus").textContent = resultado.ok
      ? "Acesso salvo; conectando via ONVIF..."
      : resultado.d.erro || "Não foi possível salvar o acesso.";
    if (resultado.ok) $("onvifPassword").value = "";
    await carregarPtzConfiguracao();
  };
  cameraPtzSettings.querySelectorAll("#manualPtz [data-ptz]").forEach(
    (botao) =>
      (botao.onclick = async () => {
        botao.disabled = true;
        $("manualPtzStatus").textContent = "Enviando toque para a câmera...";
        const resultado = await post("/seguranca/ptz", {
          comando: botao.dataset.ptz,
          velocidade: 0.2,
          duracao: 0.2,
        });
        $("manualPtzStatus").textContent =
          resultado.d.mensagem ||
          resultado.d.erro ||
          "A câmera não confirmou o movimento.";
        await carregarPtzConfiguracao();
      }),
  );
  carregarPtzConfiguracao();

  const nota = (t, ruim) => {
    const m = $("cm");
    m.textContent = t;
    m.style.color = ruim ? "var(--bad)" : "var(--accent)";
  };

  async function salvar(it, v) {
    const r = await post("/preferencias", { chave: it.chave, valor: v });
    if (r.ok) {
      it.valor = v;
      nota(
        r.d.reinicia
          ? "Salvo. Reinicie o Jarvis para aplicar."
          : "Salvo e aplicado.",
      );
      return true;
    }
    nota(r.d.erro || "Não foi possível salvar.", true);
    return false;
  }
  const gmailStatus = $("gmailStatus");
  // Carrega Gmail estado
  const carregarGmailStatus = async () => {
    try {
      const d = await jget("/gmail/status");
      $("gmailClientId").value = d.clientId || "";
      $("gmailRedirect").textContent = d.redirectUri || "http://127.0.0.1:5678";
      gmailStatus.textContent = d.conectado
        ? "Conta conectada: " + d.email
        : d.configurado
          ? "Cliente OAuth salvo. Conecte sua conta Google."
          : "Configure o cliente OAuth para ativar o Gmail.";
      $("gmailDisconnect").disabled = !d.conectado;
      $("gmailConnect").disabled = !d.configurado;
    } catch (_) {
      gmailStatus.textContent = "Não foi possível consultar a conexão Gmail.";
    }
  };
  $("gmailSave").onclick = async () => {
    const r = await post("/gmail/config", {
      clientId: $("gmailClientId").value.trim(),
      clientSecret: $("gmailClientSecret").value,
    });
    gmailStatus.textContent = r.ok
      ? "Cliente OAuth salvo neste computador."
      : r.d.erro || "Não foi possível salvar a integração.";
    if (r.ok) {
      $("gmailClientSecret").value = "";
      carregarGmailStatus();
    }
  };
  $("gmailConnect").onclick = async () => {
    const r = await post("/gmail/conectar", {});
    gmailStatus.textContent =
      r.d.mensagem ||
      r.d.erro ||
      (r.ok
        ? "Autorização iniciada."
        : "Não foi possível iniciar a autorização.");
  };
  $("gmailDisconnect").onclick = async () => {
    const r = await fetch("/gmail/conectar", { method: "DELETE" })
      .then((x) => x.json().then((d) => ({ ok: x.ok, d })))
      .catch(() => ({ ok: false, d: {} }));
    gmailStatus.textContent = r.ok
      ? "Conta Gmail desconectada."
      : "Não foi possível desconectar o Gmail.";
    carregarGmailStatus();
  };
  carregarGmailStatus();
  jget("/api/endereco")
    .then((d) => {
      const box = $("connectionInfo"),
        ips = d.ips || [],
        porta = d.porta_https || "?";
      box.replaceChildren();
      if (!ips.length) {
        box.innerHTML =
          '<div class="kv"><span>Nenhum IP de rede dispon\u00edvel.</span></div>';
        return;
      }
      for (const ip of ips) {
        const row = document.createElement("div");
        row.className = "kv connection-row";
        const info = document.createElement("span");
        info.textContent = `Host ${ip} \u00b7 HTTPS ${porta}`;
        const copy = document.createElement("button");
        copy.className = "btn";
        copy.textContent = "Copiar endereço";

        const url = `https://${ip}:${porta}`;
        copy.onclick = async () => {
          copy.textContent = (await copiarTexto(url)) ? "Copiado" : "Falhou";
          setTimeout(() => {
            copy.textContent = "Copiar endereço";
          }, 1800);
        };
        row.append(info, copy);
        box.appendChild(row);
      }
    })
    .catch(() => {
      $("connectionInfo").innerHTML =
        '<div class="kv"><span>Não foi possível consultar os endereços locais.</span></div>';
    });
  jget("/preferencias")
    .then((d) => {
      const itens = (d.itens || []).filter(
          (it) =>
            !/^(VIGIA_|CAMERA_)/.test(it.chave) && it.chave !== "VOLUME_PADRAO",
        ),
        box = $("cp");
      box.replaceChildren();
      let grupo = null;
      for (const it of itens) {
        if (it.grupo !== grupo) {
          grupo = it.grupo;
          const h = document.createElement("div");
          h.className = "sec";
          h.textContent = grupo || "Geral";
          box.appendChild(h);
        }
        const row = document.createElement("div");
        row.className = "kv";
        const nome = document.createElement("span");
        nome.textContent = it.rotulo || it.chave;
        if (it.reinicia) {
          const sm = document.createElement("small");
          sm.style.cssText = "display:block;color:var(--dim);font-size:11px";
          sm.textContent = "aplica ao reiniciar";
          nome.appendChild(sm);
        }
        let c;
        if (it.tipo === "bool") {
          c = document.createElement("button");
          c.className = "btn" + (it.valor ? " on" : "");
          c.textContent = it.valor ? "Ativado" : "Desativado";
          c.setAttribute("aria-pressed", String(!!it.valor));
          c.onclick = async () => {
            const nv = !it.valor;
            c.disabled = true;
            if (await salvar(it, nv)) {
              c.className = "btn" + (nv ? " on" : "");
              c.textContent = nv ? "Ativado" : "Desativado";
              c.setAttribute("aria-pressed", String(nv));
            }
            c.disabled = false;
          };
        } else if (it.tipo === "numero") {
          c = document.createElement("input");
          c.type = "number";
          c.value = it.valor;
          if (it.minimo != null) c.min = it.minimo;
          if (it.maximo != null) c.max = it.maximo;
          c.step = it.passo || 1;
          c.style.cssText =
            "width:96px;background:var(--raise);border:1px solid var(--line);border-radius:8px;padding:7px";
          c.onchange = async () => {
            if (!(await salvar(it, Number(c.value)))) c.value = it.valor;
          };
        } else if (it.tipo === "hora") {
          c = document.createElement("input");
          c.type = "time";
          c.value = it.valor || "06:00";
          c.style.cssText =
            "width:120px;background:var(--raise);border:1px solid var(--line);border-radius:8px;padding:7px;color:var(--text)";
          c.onchange = async () => {
            if (!(await salvar(it, c.value))) c.value = it.valor;
          };
        } else {
          c = document.createElement("select");
          c.style.cssText =
            "background:var(--raise);border:1px solid var(--line);border-radius:8px;padding:7px";
          for (const o of it.opcoes || []) {
            const op = document.createElement("option");
            op.value = op.textContent = o;
            c.appendChild(op);
          }
          c.value = it.valor;
          c.onchange = async () => {
            if (!(await salvar(it, c.value))) c.value = it.valor;
          };
        }
        row.append(nome, c);
        box.appendChild(row);
        if (it.chave === "SEGURANCA_AGENDA_ATIVA") {
          const note = document.createElement("p");
          note.className = "note";
          note.textContent =
            "Todos os dias: no início o Jarvis anuncia e ativa o Protocolo Torre Stark; no fim do horário, desarma. A segurança usa somente a lente inferior.";
          box.appendChild(note);
        }
      }
      if (!itens.length)
        box.innerHTML =
          '<div class="kv"><span>Nenhuma opção disponível.</span></div>';
    })
    .catch(() => {
      $("cp").innerHTML =
        '<div class="kv"><span>Servidor não respondeu.</span></div>';
    });
  return {
    poll: conectarPreviaPtz,
    every: 3000,
    cleanup: () => {
      ptzPreviewActive = false;
      ptzPreviewPlayer?.fechar();
      ptzPreviewPlayer = null;
    },
  };
}

// Suspende fundo das janelas
(() => {
  // Atualiza camadas
  const atualizarCamadas = () => {
    const aberta =
      document.body.classList.contains("cfg") ||
      !!document.querySelector(
        ".securityEvent-hologram, .news-hologram, .personal-hologram, #lb.on, [role=dialog]",
      );
    if (document.body.classList.contains("modal-open") !== aberta)
      document.body.classList.toggle("modal-open", aberta);
  };
  new MutationObserver(atualizarCamadas).observe(document.body, {
    childList: true,
    attributes: true,
    attributeFilter: ["class"],
  });
  const lightbox = document.getElementById("lb");
  if (lightbox)
    new MutationObserver(atualizarCamadas).observe(lightbox, {
      attributes: true,
      attributeFilter: ["class"],
    });
  atualizarCamadas();
})();
