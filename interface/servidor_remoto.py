import asyncio
import base64
import tempfile

import gzip
import html

import io
import ipaddress

import json

import logging

import re

import sqlite3

import threading

import time

import unicodedata

import uuid

import urllib.error
import urllib.request

import xml.etree.ElementTree as ElementTree

from collections import deque

from contextlib import closing

from datetime import datetime, timedelta

from pathlib import Path

from urllib.parse import quote, urlparse

import os
import platform
import shutil
import secrets
import socket
import subprocess
import webbrowser

import psutil

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from flask import (
    Flask,
    g,
    jsonify,
    make_response,
    Response,
    redirect,
    request,
    send_file,
    has_request_context,
)

try:
    from flask_sock import Sock
except ImportError:
    Sock = None

from werkzeug.serving import make_server

import config

from comandos import (
    controller,
    https_local,
    llm_local,
    memoria,
    painel_log,
    pc_controle,
    visao,
)


from comandos.automacao import (
    clima,
    fala_camera,
    presenca,
    seguranca_stark,
    smart_home,
    visao_inteligente,
    vigia_camera,
    zonasCamera,
)

from comandos.automacao.reproducao_eventos import reprodutor_eventos
from comandos.briefing_dia import leitor_dia

from . import gmail, voz, telas_widgets, google_agenda

log = logging.getLogger("mark2.servidor_remoto")

app = Flask(__name__)

app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
app.config["SOCK_SERVER_OPTIONS"] = {"max_message_size": 64 * 1024, "ping_interval": 25}

_CALLBACK_ENCERRAMENTO_REMOTO = None
SERVIDORES_HTTP = set()
SERVIDORES_HTTP_LOCK = threading.RLock()
SERVIDORES_HTTP_PARAR = threading.Event()



# Registra retorno encerramento
def registrar_callback_encerramento(callback):
    global _CALLBACK_ENCERRAMENTO_REMOTO
    _CALLBACK_ENCERRAMENTO_REMOTO = callback




def acionar_encerramento_remoto():
    if _CALLBACK_ENCERRAMENTO_REMOTO is None:
        log.warning(
            "Comando de encerramento remoto recebido, mas nenhuma janela "
            "está registrada para atendê-lo (rodando sem interface?)."
        )
        return
    try:
        _CALLBACK_ENCERRAMENTO_REMOTO()
    except Exception:
        log.exception("Falha ao acionar o encerramento remoto do sistema.")



# Aplica cabecalhos seguranca
@app.after_request
def aplicar_cabecalhos_seguranca(resposta):
    resposta.headers["Cache-Control"] = "no-store"
    resposta.headers["Referrer-Policy"] = "no-referrer"
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    resposta.headers["X-Frame-Options"] = "DENY"
    resposta.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    resposta.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    resposta.headers["Permissions-Policy"] = (
        "camera=(self), geolocation=(), microphone=(self)"
    )
    resposta.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "style-src-elem 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net "
        "https://cdnjs.cloudflare.com https://sdk.scdn.co; "
        "script-src-elem 'self' 'unsafe-inline' https://cdn.jsdelivr.net "
        "https://cdnjs.cloudflare.com https://sdk.scdn.co; "
        "img-src 'self' data: blob: https://openweathermap.org https://*.glbimg.com https://g1.globo.com "
        "https://cdn.simpleicons.org https://cdn.jsdelivr.net; "
        "media-src 'self' blob:; "
        "worker-src 'self' blob:; "
        "connect-src 'self' ws://127.0.0.1:5678 wss://127.0.0.1:5679 https://api.spotify.com; "
        "object-src 'none'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    )
    return resposta


PORTA_PADRAO = 5678

PORTA_HTTPS_PADRAO = PORTA_PADRAO + 1

REDES_BASE = (
    "127.0.0.0/8",
    "::1/128",
    "100.64.0.0/10",
    "fd7a:115c:a1e0::/48",
)




def como_lista(valor):
    if not valor:
        return []
    if isinstance(valor, str):
        return [valor]
    return list(valor)



# Carrega redes permitidas
def carregar_redes_permitidas():
    redes = []
    extras = como_lista(getattr(config, "REDES_REMOTAS_PERMITIDAS", ()))
    for texto in (*REDES_BASE, *extras):
        try:
            redes.append(ipaddress.ip_network(str(texto).strip(), strict=False))
        except ValueError:
            log.error("Rede inválida em REDES_REMOTAS_PERMITIDAS: %r", texto)
    return tuple(redes)


REDES_PERMITIDAS = carregar_redes_permitidas()

HOSTS_EXTRAS = tuple(
    str(item).strip().lower()
    for item in como_lista(getattr(config, "HOSTS_REMOTOS_PERMITIDOS", ()))
    if str(item).strip()
)




def ip_em_redes_permitidas(ip) -> bool:
    if getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    return any(ip in rede for rede in REDES_PERMITIDAS)




def ip_permitido(endereco) -> bool:
    try:
        ip = ipaddress.ip_address((endereco or "").split("%")[0])
    except ValueError:
        return False
    return ip_em_redes_permitidas(ip)




HOSTS_LOCAIS = frozenset({"localhost", socket.gethostname().rstrip(".").lower()})


def host_permitido(host_header, *, permitir_nome_tailscale=False) -> bool:
    try:
        nome = (urlparse("//" + (host_header or "")).hostname or "").rstrip(".").lower()
    except ValueError:
        return False
    if not nome or not re.fullmatch(r"[a-z0-9:.-]+",nome):
        return False
    try:
        return ip_em_redes_permitidas(ipaddress.ip_address(nome))
    except ValueError:
        pass
    if nome in HOSTS_LOCAIS:
        return True
    if permitir_nome_tailscale and nome.endswith(".ts.net"):
        return True
    return any(
        nome.endswith(extra) if extra.startswith(".") else nome == extra
        for extra in HOSTS_EXTRAS
    )




def acesso_permitido(req) -> bool:
    if not ip_permitido(req.remote_addr):
        return False
    endereco = ipaddress.ip_address((req.remote_addr or "").split("%", 1)[0])
    if getattr(endereco, "ipv4_mapped", None) is not None:
        endereco = endereco.ipv4_mapped
    return host_permitido(req.host, permitir_nome_tailscale=not endereco.is_loopback)



# Controla acesso
@app.before_request
def controlar_acesso():
    if not acesso_permitido(request):
        log.warning("Acesso negado a %s (Host: %s).", request.remote_addr, request.host)
        return jsonify({"erro": "acesso negado"}), 403
    origem = request.headers.get("Origin")
    if origem and urlparse(origem).netloc.lower() != (request.host or "").lower():
        return jsonify({"erro": "origem não autorizada"}), 403
    local = ipaddress.ip_address(request.remote_addr.split("%",1)[0]).is_loopback
    if not local and request.path != "/status":
        if not request.is_secure: return jsonify({"erro":"Use HTTPS para conectar o celular"}),403
        auth=request.headers.get("Authorization","")
        token=auth[7:] if auth.startswith("Bearer ") else ""
        if len(token)>512 or not secrets.compare_digest(token.encode("utf-8"),config.TOKEN_REMOTO.encode("utf-8")):
            return jsonify({"erro":"Chave de acesso ausente ou inválida"}),401
        if request.path.startswith(("/pc/","/interface/","/gmail/","/api/smarthome/","/preferencias","/logs","/dev/")) or request.path in {"/comando","/comando/audio_bruto","/ws"}:
            return jsonify({"erro":"Ação disponível apenas no PC"}),403
    if not local and request.path in {"/agenda/google/config","/agenda/google/conectar","/agenda/google/callback"}:
        return jsonify({"erro":"Configure a conta no PC"}),403
    return None



INICIO_SERVIDOR = time.time()
JANELA_CONECTADO_S = 75
CLIENTES_VISTOS = {}
CLIENTES_VISTOS_LOCK = threading.Lock()
WS_INFO = {}
FEEDS_NOTICIAS = {
    "geral": "https://g1.globo.com/rss/g1/",
    "politica": "https://g1.globo.com/rss/g1/politica/",
    "economia": "https://g1.globo.com/rss/g1/economia/",
    "mundo": "https://g1.globo.com/rss/g1/mundo/",
    "tecnologia": "https://g1.globo.com/rss/g1/tecnologia/",
}
NOTICIAS_CACHE = {}
NOTICIAS_CACHE_LOCK = threading.RLock()




def classificar_cliente(req):
    agente = (req.headers.get("User-Agent") or "").lower()
    rotulo = (req.headers.get("X-Mark2-Dispositivo") or "").strip()[:40]
    ip = req.remote_addr or "?"
    if "okhttp" in agente or rotulo:
        return "celular", (rotulo or "App Android")
    if ip in ("127.0.0.1", "::1"):
        return "pc", "Painel neste PC"
    return "navegador", f"Navegador ({ip})"



# Registra cliente visto
@app.before_request
def registrar_cliente_visto():
    try:
        tipo, rotulo = classificar_cliente(request)
        chave = f"{tipo}:{request.remote_addr}"
        agora = time.time()
        with CLIENTES_VISTOS_LOCK:
            item = CLIENTES_VISTOS.setdefault(
                chave,
                {
                    "tipo": tipo,
                    "ip": request.remote_addr,
                    "primeiro": agora,
                    "requisicoes": 0,
                },
            )
            item["rotulo"] = rotulo
            item["ultimo"] = agora
            item["rota"] = request.path
            item["requisicoes"] += 1
    except Exception:
        pass
    return None


MAX_REQUISICOES_SIMULTANEAS = 64
_SEMAFORO_REQUISICOES = threading.BoundedSemaphore(MAX_REQUISICOES_SIMULTANEAS)
_TRAVA_LIMITES_TAXA = threading.Lock()
_JANELAS_TAXA = {}
_LIMITES_TAXA = {
    "/comando": (12, 60),
    "/comando/audio_bruto": (8, 60),
    "/visao/foto": (6, 60),
    "/api/smarthome/token": (5, 60),
    "/seguranca/testar": (3, 60),
    "/seguranca/linha/testar": (6, 60),
    "/seguranca/zonas": (12, 60),
    "/seguranca/eventos/revisar": (20, 60),
    "/seguranca/falar": (12, 60),
    "/voz/falar": (12, 60),
    "/assistente/ativo": (12, 60),
    "/central/aparelhos/acao": (15, 60),
    "/central/rotinas": (20, 60),
    "/central/fontes": (20, 60),
    "/assistente/parar": (30, 60),
    "/pessoal/aviso": (12, 60),
    "/pessoal/comando": (12, 60),
    "/pessoal/seguranca/ativo": (12, 60),
    "/preferencias": (20, 60),
    "/logs/limpar": (2, 60),
}



# Consome limite taxa
def consumir_limite_taxa(chave, limite, janela_s):
    agora = time.monotonic()
    with _TRAVA_LIMITES_TAXA:
        janela = _JANELAS_TAXA.setdefault(chave, deque())
        while janela and agora - janela[0] >= janela_s:
            janela.popleft()
        if len(janela) >= limite:
            return False
        janela.append(agora)
        if len(_JANELAS_TAXA) > 4096:
            expirados = [
                nome
                for nome, eventos in _JANELAS_TAXA.items()
                if not eventos or agora - eventos[-1] >= 600
            ]
            for nome in expirados:
                _JANELAS_TAXA.pop(nome, None)
        return True




@app.before_request
def limitar_carga_do_servidor():
    if not _SEMAFORO_REQUISICOES.acquire(blocking=False):
        return jsonify({"erro": "servidor ocupado; tente novamente em instantes"}), 503
    g.mark2_slot_requisicao = True

    limite = _LIMITES_TAXA.get(request.path)
    if limite and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        maximo, janela_s = limite
        chave = f"{request.remote_addr or '?'}:{request.path}"
        if not consumir_limite_taxa(chave, maximo, janela_s):
            return (
                jsonify({"erro": "Request rate limit reached; try again shortly."}),
                429,
            )
    return None




@app.teardown_request
def liberar_slot_requisicao(_erro=None):
    if getattr(g, "mark2_slot_requisicao", False):
        g.mark2_slot_requisicao = False
        _SEMAFORO_REQUISICOES.release()


HISTORICO = deque(maxlen=100)

HISTORICO_LOCK = threading.Lock()

HISTORICO_VERSAO = 0

HISTORICO_CONDICAO = threading.Condition()

TIMEOUT_LONG_POLL_SEGUNDOS = 25

ACOES_MIDIA_TELEFONE_VALIDAS = (
    "proxima",
    "anterior",
    "tocar",
    "pausar",
    "parar",
    "play_pausa",
    "volume_mais",
    "volume_menos",
    "silenciar",
    "desmutar",
)

COMANDO_MIDIA_TELEFONE_LOCK = threading.Lock()

COMANDO_MIDIA_TELEFONE_CONDICAO = threading.Condition()

COMANDO_MIDIA_TELEFONE_VERSAO = 0

COMANDO_MIDIA_TELEFONE_ACAO = None



# Define comando midia telefone
def definir_comando_midia_telefone(acao: str) -> bool:
    global COMANDO_MIDIA_TELEFONE_VERSAO, COMANDO_MIDIA_TELEFONE_ACAO
    if acao not in ACOES_MIDIA_TELEFONE_VALIDAS:
        return False
    with COMANDO_MIDIA_TELEFONE_LOCK:
        COMANDO_MIDIA_TELEFONE_ACAO = acao
    with COMANDO_MIDIA_TELEFONE_CONDICAO:
        COMANDO_MIDIA_TELEFONE_VERSAO += 1
        COMANDO_MIDIA_TELEFONE_CONDICAO.notify_all()
    return True


PALAVRAS_CONTEXTO_MUSICA = {
    "musica",
    "musicas",
    "faixa",
    "faixas",
    "cancao",
    "cancoes",
    "song",
    "songs",
    "playlist",
    "playlists",
    "spotify",
    "player",
    "reprodutor",
    "album",
    "albums",
    "audio",
    "midia",
}

VERBOS_PROXIMA_MUSICA = {
    "proxima",
    "pula",
    "pule",
    "pular",
    "avanca",
    "avance",
    "avancar",
    "troca",
    "troque",
    "trocar",
    "muda",
    "mude",
    "mudar",
    "next",
    "skip",
}

VERBOS_MUSICA_ANTERIOR = {
    "anterior",
    "volta",
    "volte",
    "voltar",
    "retrocede",
    "retroceda",
    "retroceder",
    "previous",
}

VERBOS_TOCAR_MUSICA = {
    "toca",
    "toque",
    "tocar",
    "play",
    "reproduz",
    "reproduza",
    "reproduzir",
    "inicia",
    "inicie",
    "iniciar",
    "continua",
    "continue",
    "continuar",
    "despausa",
    "despause",
    "despausar",
    "resume",
    "retoma",
    "retome",
    "retomar",
}

VERBOS_PAUSAR_MUSICA = {"pausa", "pause", "pausar", "suspende", "suspender"}
VERBOS_PARAR_MUSICA = {"para", "pare", "parar", "stop", "interrompe", "interromper"}
VERBOS_VOLUME_MAIS = {
    "aumenta",
    "aumente",
    "aumentar",
    "sobe",
    "suba",
    "subir",
    "mais",
    "cima",
}
VERBOS_VOLUME_MENOS = {
    "diminui",
    "diminua",
    "diminuir",
    "abaixa",
    "abaixe",
    "baixar",
    "menos",
    "baixo",
}
VERBOS_SILENCIAR = {"muta", "mute", "mutar", "silencia", "silenciar"}
VERBOS_DESMUTAR = {"desmuta", "desmutar", "reativa", "reativar"}
VERBOS_ALTERNAR_MUSICA = {"alternar", "alterna", "toggle"}

COMANDOS_CURTOS_PROXIMA = {"proxima", "pula", "next", "skip", "pular"}
COMANDOS_CURTOS_ANTERIOR = {"anterior", "volta", "previous"}
COMANDOS_CURTOS_TOCAR = {
    "toca",
    "toque",
    "tocar",
    "play",
    "continua",
    "continue",
    "retoma",
    "retomar",
    "resume",
}
COMANDOS_CURTOS_PAUSAR = {"pausa", "pause", "pausar"}
COMANDOS_CURTOS_PARAR = {"para", "pare", "parar", "stop"}

RESPOSTAS_ACAO_MUSICA_TELEFONE = {
    "proxima": "Pulando pra próxima.",
    "anterior": "Voltando a música.",
    "tocar": "Tocando música.",
    "pausar": "Pausando a música.",
    "parar": "Parando a música.",
    "play_pausa": "Alternando a reprodução.",
    "volume_mais": "Aumentando o volume da música.",
    "volume_menos": "Diminuindo o volume da música.",
    "silenciar": "Silenciando a música.",
    "desmutar": "Ativando o som da música.",
}




def identificar_comando_musica(texto: str) -> str | None:
    normalizado = voz.remover_chamada_jarvis(texto)
    if not normalizado:
        return None

    palavras = set(normalizado.split())
    tem_contexto_musica = bool(palavras & PALAVRAS_CONTEXTO_MUSICA)

    if palavras & VERBOS_PROXIMA_MUSICA and (
        tem_contexto_musica or normalizado in COMANDOS_CURTOS_PROXIMA
    ):
        return "proxima"

    if palavras & VERBOS_MUSICA_ANTERIOR and (
        tem_contexto_musica or normalizado in COMANDOS_CURTOS_ANTERIOR
    ):
        return "anterior"

    if tem_contexto_musica:
        if "volume" in palavras:
            if palavras & VERBOS_VOLUME_MAIS:
                return "volume_mais"
            if palavras & VERBOS_VOLUME_MENOS:
                return "volume_menos"
        if palavras & VERBOS_SILENCIAR:
            return "silenciar"
        if palavras & VERBOS_DESMUTAR:
            return "desmutar"
        if palavras & VERBOS_ALTERNAR_MUSICA:
            return "play_pausa"
        if palavras & VERBOS_TOCAR_MUSICA:
            return "tocar"
        if palavras & VERBOS_PAUSAR_MUSICA:
            return "pausar"
        if palavras & VERBOS_PARAR_MUSICA:
            return "parar"

    if normalizado in COMANDOS_CURTOS_TOCAR:
        return "tocar"
    if normalizado in COMANDOS_CURTOS_PAUSAR:
        return "pausar"
    if normalizado in COMANDOS_CURTOS_PARAR:
        return "parar"

    return None


COMANDO_LOCK = threading.Lock()

SERVIDOR_THREAD_LOCK = threading.Lock()

SERVIDOR_THREAD = None

SERVIDOR_THREAD_HTTPS = None

ESCUTA_VOZ_ATIVAR = threading.Event()

ESCUTA_VOZ_DIRETA = threading.Event()

ESCUTA_VOZ_ENCERRAR = threading.Event()

ESCUTA_VOZ_DESLIGAR = threading.Event()

ESCUTA_VOZ_PAUSAR = threading.Event()



TRAVA_JANELA_REMOTA = threading.Lock()



ESTADO_ESCUTA_PC = {
    "ativo": False,
    "pausado": False,
    "janela": False,
    "nivel": 0,
    "erro": "",
    "ocupado": False,
    "dono": 0,
    "pico": 0,
    "texto_ouvido": "",
    "transcricao_parcial": False,
    "transcricao_ts": 0,
    "comando_reconhecido": False,
}

DB_PATH_ROTINA = config.DATA_DIR / "historico_rotinas.db"

ROTINA_LOCK = threading.Lock()

COMANDOS_RAPIDOS = [
    "cheguei em casa",
    "status",
    "ligar tv",
    "desligar tv",
]

PROCESSOS_OBSERVADOS = {
    "VS Code": ("Code.exe",),
    "Discord": ("Discord.exe",),
    "Navegador": ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"),
}

ICONES_APPS = {
    "VS Code": "visualstudiocode",
    "Discord": "discord",
    "Navegador": "googlechrome",
}




def renderizar_arquivo_html(caminho):
    if not caminho.is_file():
        return jsonify({"erro": "interface não encontrada"}), 404
    try:
        pagina = caminho.read_text(encoding="utf-8")
        if os.environ.get("JARVIS_DEV_RELOAD") == "1":
            recarregador = """<script>(function(){let versao=null;async function consultar(){try{const r=await fetch('/dev/reload-state',{cache:'no-store'});if(!r.ok)return false;const d=await r.json();if(versao===null){versao=d.version;return true}if(d.version!==versao){location.reload();return false}return true}catch(_){return false}}consultar().then(ok=>{if(ok){const t=setInterval(async()=>{if(!await consultar())clearInterval(t)},1500)}})})();</script>"""
            pagina = pagina.replace("</body>", recarregador + "</body>", 1)
        resposta = make_response(pagina)
    except (OSError, UnicodeError):
        log.exception("Falha ao carregar a interface HTML: %s", caminho)
        return jsonify({"erro": "não foi possível carregar a interface"}), 500
    resposta.headers["Content-Type"] = "text/html; charset=utf-8"
    return resposta


PADRAO_ENCERRAR_SISTEMA_REMOTO = re.compile(
    r"^(?:(?:por favor|por gentileza|pode|poderia)[, ]+)?"
    r"(?:sair|(?:desligar|desligue|encerrar|encerre)\s+(?:o\s+)?sistema)$"
)




def json_objeto():
    if not request.is_json:
        return None
    dados = request.get_json(silent=True)
    return dados if isinstance(dados, dict) else None



# Inicializa historico rotinas
def inicializar_historico_rotinas():
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with ROTINA_LOCK, closing(
            sqlite3.connect(DB_PATH_ROTINA, timeout=10)
        ) as conexao:
            conexao.execute(
                "CREATE TABLE IF NOT EXISTS eventos ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL, "
                "hora TEXT NOT NULL, origem TEXT NOT NULL, mensagem TEXT NOT NULL DEFAULT '')"
            )
            conexao.execute(
                "CREATE INDEX IF NOT EXISTS idx_eventos_hora ON eventos(hora)"
            )
            conexao.execute(
                "DELETE FROM eventos WHERE hora < ?",
                ((datetime.now().astimezone() - timedelta(days=90)).isoformat(),),
            )
            conexao.commit()
    except (OSError, sqlite3.Error):
        log.exception("Não foi possível inicializar o histórico de rotinas.")



# Registra evento rotina
def registrar_evento_rotina(
    tipo: str, origem: str = "sistema", mensagem: str = ""
) -> bool:
    if tipo not in {"chegada", "saida"}:
        return False
    if not isinstance(origem, str):
        origem = "sistema"
    if not isinstance(mensagem, str):
        mensagem = ""
    agora = datetime.now().astimezone()
    limite_duplicado = (agora - timedelta(seconds=2)).isoformat()
    try:
        with ROTINA_LOCK, closing(
            sqlite3.connect(DB_PATH_ROTINA, timeout=10)
        ) as conexao:
            duplicado = conexao.execute(
                "SELECT 1 FROM eventos WHERE tipo = ? AND origem = ? AND hora >= ? LIMIT 1",
                (tipo, origem[:120], limite_duplicado),
            ).fetchone()
            if duplicado:
                return False
            conexao.execute(
                "INSERT INTO eventos (tipo, hora, origem, mensagem) VALUES (?, ?, ?, ?)",
                (tipo, agora.isoformat(), origem[:120], mensagem[:2000]),
            )
            conexao.commit()
        return True
    except sqlite3.Error:
        log.exception("Não foi possível registrar o evento de rotina.")
        return False



# Lista eventos rotina hoje
def listar_eventos_rotina_hoje() -> list:
    inicio = datetime.combine(datetime.now().astimezone().date(), datetime.min.time())
    fim = inicio + timedelta(days=1)
    try:
        with ROTINA_LOCK, closing(
            sqlite3.connect(DB_PATH_ROTINA, timeout=10)
        ) as conexao:
            conexao.row_factory = sqlite3.Row
            linhas = conexao.execute(
                "SELECT tipo, hora, origem, mensagem FROM eventos "
                "WHERE hora >= ? AND hora < ? ORDER BY hora ASC",
                (inicio.isoformat(), fim.isoformat()),
            ).fetchall()
        return [dict(linha) for linha in linhas]
    except sqlite3.Error:
        log.exception("Não foi possível ler o histórico de rotinas.")
        return []



# Normaliza comando rotina
def normalizar_comando_rotina(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto.casefold())
    normalizado = "".join(
        caractere for caractere in normalizado if not unicodedata.combining(caractere)
    )
    return " ".join(normalizado.split())



# Registra evento detectado
def registrar_evento_detectado(texto: str, resposta: str, origem: str):
    comando = normalizar_comando_rotina(texto)
    resposta_normalizada = normalizar_comando_rotina(resposta)
    if any(
        termo in resposta_normalizada
        for termo in ("erro", "falha", "nao foi possivel", "cancelad")
    ):
        return
    if re.fullmatch(r"cheguei(?: em casa)?[.!]?", comando):
        registrar_evento_rotina("chegada", origem, resposta)
    elif re.fullmatch(r"confirmar saida[.!]?", comando):
        registrar_evento_rotina("saida", origem, resposta)


inicializar_historico_rotinas()



# Registra historico
def registrar_historico(texto: str, resposta: str, origem: str):
    global HISTORICO_VERSAO
    texto = texto if isinstance(texto, str) else str(texto or "")
    resposta = resposta if isinstance(resposta, str) else str(resposta or "")
    origem = origem if isinstance(origem, str) else str(origem or "")
    log.info("Interação (%s) | Você: %s | Jarvis: %s", origem, texto, resposta)
    with HISTORICO_LOCK:
        HISTORICO.appendleft(
            {
                "hora": datetime.now().astimezone().isoformat(),
                "texto": texto,
                "resposta": resposta,
                "origem": origem,
            }
        )

    with HISTORICO_CONDICAO:
        HISTORICO_VERSAO += 1
        HISTORICO_CONDICAO.notify_all()
    registrar_evento_detectado(texto, resposta, origem)




# Envia evento painel local
def enviar_evento_painel_local(evento):
    payload = json.dumps(evento)
    with CLIENTES_WS_LOCK:
        locais = [cliente for cliente in CLIENTES_WS if WS_INFO.get(cliente, {}).get("ip") in ("127.0.0.1", "::1")]
    for cliente in locais:
        try:
            cliente.send(payload)
        except Exception:
            remover_cliente_ws(cliente)


# Registra fala ouvida
def registrar_fala_ouvida(texto):
    if not texto:
        return
    salvar_mensagem_sessao(SESSAO_PRINCIPAL_ID, "user", texto)
    enviar_evento_painel_local({"type": "local_interaction", "session_id": SESSAO_PRINCIPAL_ID,
                               "texto": texto, "resposta": ""})


# Registra interacao local
def registrar_interacao_local(texto: str, resposta: str, origem: str = "painel-pc", usuario_registrado=False):
    if not texto:
        return
    registrar_historico(texto, resposta or "", origem)
    if origem == "voz-pc" and resposta != "SHUTDOWN_SIGNAL":
        if not usuario_registrado:
            salvar_mensagem_sessao(SESSAO_PRINCIPAL_ID, "user", texto)
        if resposta:
            salvar_mensagem_sessao(SESSAO_PRINCIPAL_ID, "assistant", resposta)
        enviar_evento_painel_local({"type": "local_interaction", "session_id": SESSAO_PRINCIPAL_ID,
                                   "texto": "" if usuario_registrado else texto, "resposta": resposta or ""})


# Registra alerta rede
def registrar_alerta_rede(dispositivo: dict, mensagem: str):
    if not isinstance(dispositivo, dict):
        dispositivo = {}
    registrar_historico("[Alerta de Rede]", mensagem, dispositivo.get("ip", ""))




@app.route("/", methods=["GET"])
def raiz():
    if request.args.get("code") or request.args.get("error"):
        return resposta_gmail_oauth()
    return redirect("/painel")



def resposta_gmail_oauth():
    if request.args.get("error"):
        mensagem = "A autorização do Gmail foi cancelada. Volte ao Jarvis e tente novamente."
    else:
        sucesso, mensagem = gmail.exchangeCode(request.args.get("code"), request.args.get("state"))
        if not sucesso:
            mensagem = "Não foi possível conectar o Gmail. " + mensagem
        else:
            broadcast_ws({"type": "gmail_connected"})
    pagina = "<!doctype html><html lang=pt-BR><meta charset=utf-8><title>Jarvis Mark 2</title><body style='font:16px system-ui;background:#080e17;color:#eaf4fc;padding:48px'><h1>Jarvis Mark 2</h1><p>" + html.escape(mensagem) + "</p><p>Volte ao painel do Jarvis para continuar.</p></body></html>"
    resposta = make_response(pagina)
    resposta.headers["Content-Type"] = "text/html; charset=utf-8"
    return resposta




@app.route("/api/endereco", methods=["GET"])
def api_endereco():
    enderecos = set()
    try:
        for interfaces in psutil.net_if_addrs().values():
            for item in interfaces:
                if item.family != socket.AF_INET:
                    continue
                try:
                    ip = ipaddress.ip_address(item.address)
                except ValueError:
                    continue
                if ip.is_loopback or not any(ip in rede for rede in REDES_PERMITIDAS):
                    continue
                enderecos.add(str(ip))
    except Exception:
        log.debug("Não consegui listar endereços de rede.", exc_info=True)
    ordenados = sorted(enderecos, key=lambda ip: (not ip.startswith("100."), ip))
    return jsonify({"ips": ordenados, "porta_https": PORTA_HTTPS_PADRAO,
                    "urls": [f"https://{ip}:{PORTA_HTTPS_PADRAO}" for ip in ordenados]})




@app.route("/status", methods=["GET"])
def status():
    return jsonify({"status": "online"}), 200



@app.route("/dev/reload-state", methods=["GET"])
def estado_recarregamento_desenvolvimento():
    if os.environ.get("JARVIS_DEV_RELOAD") != "1":
        return jsonify({"erro": "não encontrado"}), 404
    endereco = request.remote_addr or ""
    if endereco not in {"127.0.0.1", "::1", "::ffff:127.0.0.1"}:
        return jsonify({"erro": "não encontrado"}), 404
    marcador = os.environ.get("JARVIS_DEV_ASSET_TOKEN_FILE", "")
    try:
        versao = Path(marcador).read_text(encoding="ascii").strip() if marcador else ""
    except OSError:
        versao = ""
    resposta = jsonify({"version": versao})
    resposta.headers["Cache-Control"] = "no-store"
    return resposta, 200




@app.route("/historico", methods=["GET"])
def historico():
    with HISTORICO_LOCK:
        return jsonify(list(HISTORICO)), 200




@app.route("/historico/versao", methods=["GET"])
def historico_versao():
    return jsonify({"versao": HISTORICO_VERSAO}), 200




@app.route("/comando/audio_bruto", methods=["POST"])
def comando_audio_bruto():
    origem = request.remote_addr

    dados_audio = request.data
    if not dados_audio:
        return jsonify({"erro": "áudio vazio"}), 400

    try:
        taxa_amostragem = int(request.headers.get("X-Sample-Rate", 48000))
    except ValueError:
        taxa_amostragem = 48000

    if not COMANDO_LOCK.acquire(blocking=False):
        return jsonify({"erro": "ocupado"}), 429

    try:
        if voz.sr is None or voz.reconhecedor is None:
            return jsonify({"erro": "speech_recognition indisponível"}), 500

        audio_data = voz.sr.AudioData(dados_audio, taxa_amostragem, 2)
        try:
            texto = voz.transcrever_audio(audio_data)
            print(f"[OUVIDO NAVEGADOR] {texto}", flush=True)
            log.info("Áudio do navegador transcrito: %s", texto)
        except voz.sr.UnknownValueError:
            return jsonify({"erro": "Não entendi o áudio"}), 400
        except Exception as e:
            log.error("Falha na api de voz: %s", e)
            return jsonify({"erro": "Falha na transcrição"}), 500

        from comandos import linguagem
        if not voz.wake_word.ativado(texto) and not linguagem.comando_direto(texto) and linguagem.chave(texto) not in ("eai", "e ai", "oi", "ola", "alo", "cheguei em casa"):
            log.info("Áudio ignorado porque não contém 'Jarvis': %s", texto)
            return jsonify({"ignorado": True, "texto": texto}), 200
        versao_pedido = llm_local.versao_cancelamento()
        llm_local.bloquear_requisicao(not linguagem.autoriza_ia_voz(texto))
        texto_original = texto
        texto = voz.wake_word.remover(texto)
        if not texto:
            resposta = "Às ordens, senhor."
            if config.VOZ_ATIVA:
                threading.Thread(target=voz.falar, args=(resposta,), daemon=True).start()
            return jsonify({"texto": texto_original, "resposta": resposta}), 200
        dispararPainelPessoal(texto)

        encerrando = voz.frase_encerra_conversa(texto)
        if encerrando:
            resposta = voz.RESPOSTA_ENCERRAMENTO
        else:
            try:
                resposta = asyncio.run(
                    controller.processar_comando(texto, permitir_acesso_codigo=False)
                )
            except Exception:
                resposta = "Erro interno ao processar o comando."

        if llm_local.versao_cancelamento() != versao_pedido:
            return jsonify({"resposta": "", "cancelado": True}), 200
        resposta_final = (
            voz.RESPOSTA_ENCERRAMENTO
            if encerrando
            else voz.com_pergunta_continuidade(resposta)
        )

        if resposta_final == "SHUTDOWN_SIGNAL":
            acionar_encerramento_remoto()
            resposta_final = "Encerramento solicitado."

        registrar_historico(texto, resposta_final, origem)

        if config.VOZ_ATIVA:
            threading.Thread(
                target=voz.falar, args=(resposta_final,), daemon=True
            ).start()

        return jsonify({"texto": texto, "resposta": resposta_final})

    finally:
        COMANDO_LOCK.release()




@app.route("/historico/aguardar", methods=["GET"])
def historico_aguardar():
    try:
        versao_recebida = int(request.args.get("versao", 0))
    except (TypeError, ValueError):
        versao_recebida = 0
    versao_recebida = max(0, versao_recebida)

    with HISTORICO_CONDICAO:
        HISTORICO_CONDICAO.wait_for(
            lambda: HISTORICO_VERSAO != versao_recebida,
            timeout=TIMEOUT_LONG_POLL_SEGUNDOS,
        )
        versao_atual = HISTORICO_VERSAO

    with HISTORICO_LOCK:
        itens = list(HISTORICO)

    return jsonify({"versao": versao_atual, "itens": itens}), 200




@app.route("/sistema", methods=["GET"])
def sistema():
    cpu = psutil.cpu_percent(interval=0.3)
    ram = psutil.virtual_memory().percent

    nomes_rodando = set()
    for processo in psutil.process_iter(["name"]):
        try:
            nome_processo = processo.info.get("name")
            if nome_processo:
                nomes_rodando.add(nome_processo.lower())
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue

    apps = {
        nome_app: any(processo.lower() in nomes_rodando for processo in processos)
        for nome_app, processos in PROCESSOS_OBSERVADOS.items()
    }

    icones = {nome: ICONES_APPS[nome] for nome in apps if nome in ICONES_APPS}
    return (
        jsonify(
            {
                "cpu": cpu,
                "ram": ram,
                "apps": apps,
                "icones": icones,
                "camera_ao_vivo": visao.captura_ao_vivo_ativa(),
            }
        ),
        200,
    )




@app.route("/visao/ao-vivo/quadro.jpg", methods=["GET"])
def visao_quadro_ao_vivo():
    imagem = visao.ultimo_quadro_ao_vivo_jpeg()
    if imagem is None:
        return jsonify({"erro": "A camera ao vivo ainda nao forneceu um quadro."}), 503
    resposta = make_response(imagem)
    resposta.headers["Content-Type"] = "image/jpeg"
    resposta.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resposta.headers["Pragma"] = "no-cache"
    return resposta



@app.route("/atividade/llm", methods=["GET"])
def atividade_llm():
    return jsonify(llm_local.obter_atividade()), 200



# Cancela atividade IA
@app.route("/atividade/llm/cancelar", methods=["POST"])
def cancelar_atividade_llm():
    quantidade = llm_local.cancelar_tudo()
    log.info(
        "Cancelamento do LM Studio solicitado pelo painel (%s origem).",
        request.remote_addr,
    )
    return jsonify({"canceladas": quantidade}), 200




@app.route("/llm/estado", methods=["GET"])
def llm_estado():
    return jsonify({"ativo": llm_local.servidor_local_ativo()}), 200




@app.route("/llm/ativo", methods=["POST"])
def llm_definir_ativo():
    dados = json_objeto()
    if dados is None:
        return jsonify({"erro": "envie um objeto JSON válido"}), 400
    ativo = dados.get("ativo")
    if not isinstance(ativo, bool):
        return jsonify({"erro": "campo 'ativo' precisa ser true ou false"}), 400
    if not llm_local.definir_servidor_local_ativo(ativo):
        return jsonify({"erro": "não consegui salvar o estado do LM Studio"}), 500
    log.info(
        "LM Studio %s pelo aplicativo (%s).",
        "ativado" if ativo else "desativado",
        request.remote_addr,
    )
    return jsonify({"ativo": llm_local.servidor_local_ativo()}), 200



@app.route("/llm/servidor/parar", methods=["POST"])
def llm_parar_servidor():
    resultado = llm_local.parar_servidor_servidor_local()
    status = 200 if resultado["sucesso"] else 409
    log.info("Parada do servidor LM Studio solicitada por %s: %s", request.remote_addr, resultado["mensagem"])
    return jsonify(resultado), status



# Recebe comando
@app.route("/comando", methods=["POST"])
def receber_comando():
    origem = request.remote_addr

    dados = json_objeto()
    if dados is None:
        return jsonify({"erro": "envie um objeto JSON válido"}), 400
    texto = dados.get("texto")

    if not isinstance(texto, str) or not texto.strip():
        return jsonify({"erro": "campo 'texto' não informado"}), 400
    texto = texto.strip()
    dispararPainelPessoal(texto)
    falar_no_pc = dados.get("falar_no_pc", True)
    if not isinstance(falar_no_pc, bool):
        falar_no_pc = True
    llm_local.bloquear_requisicao(dados.get("usar_llm", True) is False)
    versao_pedido = llm_local.versao_cancelamento()
    encerrando_conversa = voz.frase_encerra_conversa(texto)
    texto_sem_chamada = voz.remover_chamada_jarvis(texto).lower().strip(" .!?,;")
    if (
        PADRAO_ENCERRAR_SISTEMA_REMOTO.fullmatch(texto_sem_chamada)
        and dados.get("confirmar_encerramento") is not True
    ):
        log.warning(
            "Encerramento do sistema por voz/texto bloqueado (origem %s).", origem
        )
        return (
            jsonify(
                {
                    "erro": "encerrar o sistema só é aceito pelo botão de desligar do aplicativo"
                }
            ),
            403,
        )
    if len(texto) > 4000:
        return jsonify({"erro": "comando excede o limite de 4.000 caracteres"}), 400

    log.info(
        "Comando remoto recebido de %s com %d caractere(s).",
        origem,
        len(texto),
    )

    acao_musica = identificar_comando_musica(texto) if not encerrando_conversa else None

    if encerrando_conversa:
        resposta = voz.RESPOSTA_ENCERRAMENTO
    elif acao_musica:
        try:
            enviado = definir_comando_midia_telefone(acao_musica)
        except Exception:
            log.error("Falha ao mandar o comando de música pro celular.", exc_info=True)
            enviado = False
        resposta = (
            RESPOSTAS_ACAO_MUSICA_TELEFONE.get(acao_musica, "Prontinho.")
            if enviado
            else "Não consegui mandar o comando pro celular agora."
        )
    else:
        if not COMANDO_LOCK.acquire(timeout=8):
            return jsonify({"erro": "outro comando ainda está em processamento"}), 429
        try:
            try:
                resposta = asyncio.run(
                    controller.processar_comando(
                        texto,
                        permitir_acesso_codigo=False,
                    )
                )
            except Exception:
                log.exception("Erro ao processar comando remoto.")
                resposta_erro = "Erro interno ao processar o comando."
                registrar_historico(texto, resposta_erro, origem)
                return resposta_erro, 500
        finally:
            COMANDO_LOCK.release()

    if llm_local.versao_cancelamento() != versao_pedido:
        return jsonify({"resposta": "", "cancelado": True}), 200
    if not isinstance(resposta, str):
        resposta = str(resposta or "")
    if resposta == "" and not encerrando_conversa and not llm_local.servidor_local_ativo():
        resposta_muda = make_response("", 200)
        resposta_muda.headers["X-Mark2-Conversation"] = "continue"
        return resposta_muda
    if encerrando_conversa:
        resposta = voz.RESPOSTA_ENCERRAMENTO
    else:
        resposta = voz.com_pergunta_continuidade(resposta)
    if resposta == "SHUTDOWN_SIGNAL":
        acionar_encerramento_remoto()
    elif resposta and config.VOZ_ATIVA and falar_no_pc:
        threading.Thread(target=voz.falar, args=(resposta,), daemon=True).start()

    resposta_final = resposta or "Comando não reconhecido."
    registrar_historico(texto, resposta_final, origem)

    # O Android escreve na mesma sessão persistente que o chat desktop utiliza.
    sessao_atual = dados.get("session_id")
    if isinstance(sessao_atual, str) and sessao_atual.strip():
        sessao_atual = sessao_atual.strip()[:120]
        criar_ou_tocar_sessao(sessao_atual)
        salvar_mensagem_sessao(sessao_atual, "user", texto)
        salvar_mensagem_sessao(sessao_atual, "assistant", resposta_final)
        rotulo = rotulo_dispositivo({**dados, "device_label": "Android"})
        broadcast_ws({
            "type": "user_message", "session_id": sessao_atual,
            "content": texto, "device_label": rotulo,
        })
        broadcast_ws({
            "type": "external_assistant_message", "session_id": sessao_atual,
            "content": resposta_final, "device_label": rotulo,
        })

    resposta_http = make_response(resposta_final, 200)
    resposta_http.headers["X-Mark2-Conversation"] = (
        "closed" if encerrando_conversa or resposta == "SHUTDOWN_SIGNAL" else "continue"
    )
    return resposta_http



# Limpa conversa route
@app.route("/limpar", methods=["POST"])
def limpar_conversa_route():
    origem = request.remote_addr

    if not COMANDO_LOCK.acquire(blocking=False):
        return jsonify({"erro": "outro comando ainda está em processamento"}), 429
    try:
        controller.amigo.limpar_conversa()
        global HISTORICO_VERSAO
        with HISTORICO_LOCK:
            HISTORICO.clear()
        with HISTORICO_CONDICAO:
            HISTORICO_VERSAO += 1
            HISTORICO_CONDICAO.notify_all()
    finally:
        COMANDO_LOCK.release()

    log.info(f"Conversa limpa via painel remoto por {origem}.")
    return jsonify({"status": "ok"}), 200




@app.route("/visao/foto", methods=["POST"])
def visao_foto_remota():
    origem = request.remote_addr

    dados = json_objeto()
    if dados is None:
        return jsonify({"erro": "envie um objeto JSON válido"}), 400

    imagem = dados.get("imagem")
    if not isinstance(imagem, str) or not imagem.strip():
        return jsonify({"erro": "campo 'imagem' não informado"}), 400
    imagem = imagem.strip()
    if imagem.startswith("data:") and "," in imagem:
        imagem = imagem.split(",", 1)[1]
    if not llm_local.imagem_valida(imagem):
        return jsonify({"erro": "imagem inválida ou grande demais"}), 400

    pergunta = dados.get("pergunta")
    pergunta = pergunta.strip()[:500] if isinstance(pergunta, str) else ""
    pergunta = pergunta or None

    sessao_atual = dados.get("session_id")
    sessao_atual = (
        sessao_atual.strip()
        if isinstance(sessao_atual, str) and sessao_atual.strip()
        else SESSAO_PRINCIPAL_ID
    )
    rotulo = rotulo_dispositivo(dados)

    if not COMANDO_LOCK.acquire(blocking=False):
        return jsonify({"erro": "outro comando ainda está em processamento"}), 429
    try:
        resposta, caminho_salvo = visao.analisar_foto_recebida(imagem, pergunta)
    finally:
        COMANDO_LOCK.release()

    if not isinstance(resposta, str):
        resposta = str(resposta or "")

    texto_historico = (
        f"[Foto do celular] {pergunta}" if pergunta else "[Foto enviada pelo celular]"
    )
    registrar_historico(texto_historico, resposta, origem)

    nome_arquivo = caminho_salvo.name if caminho_salvo else None

    if nome_arquivo:
        criar_ou_tocar_sessao(sessao_atual)
        conteudo_salvo = f"[[foto:{nome_arquivo}]]\n{resposta}"
        if pergunta:
            salvar_mensagem_sessao(sessao_atual, "user", pergunta)
            broadcast_ws(
                {
                    "type": "user_message",
                    "session_id": sessao_atual,
                    "content": pergunta,
                    "device_label": rotulo,
                }
            )
        salvar_mensagem_sessao(sessao_atual, "assistant", conteudo_salvo)
        broadcast_ws(
            {
                "type": "foto",
                "session_id": sessao_atual,
                "arquivo": nome_arquivo,
                "resposta": resposta,
                "device_label": rotulo,
            }
        )

    falar_no_pc = dados.get("falar_no_pc", True) is True
    if config.VOZ_ATIVA and falar_no_pc:
        threading.Thread(target=voz.falar, args=(resposta,), daemon=True).start()

    log.info("Foto do celular analisada (origem %s).", origem)
    return jsonify({"resposta": resposta, "arquivo": nome_arquivo}), 200




@app.route("/visao/video", methods=["POST"])
def visao_video_remota():
    arquivo = request.files.get("arquivo")
    pergunta = str(request.form.get("pergunta") or "Descreva os acontecimentos visíveis").strip()[:500]
    sessao = str(request.form.get("session_id") or SESSAO_PRINCIPAL_ID).strip()[:120]
    falar_no_pc = request.form.get("falar_no_pc", "false").lower() == "true"
    if arquivo is None or not arquivo.filename:
        return jsonify({"erro": "Selecione um vídeo para analisar."}), 400
    conteudo = arquivo.read(12 * 1024 * 1024 + 1)
    if len(conteudo) > 12 * 1024 * 1024:
        return jsonify({"erro": "O vídeo excede o limite de 12 MiB."}), 413
    motor_video = vigia_camera.cv2
    numpy = vigia_camera.np
    if motor_video is None or numpy is None:
        return jsonify({"erro": "Análise de vídeo indisponível: OpenCV não está instalado no computador."}), 503
    temporario = None
    try:
        with tempfile.NamedTemporaryFile(suffix=Path(arquivo.filename).suffix or ".mp4", delete=False) as alvo:
            alvo.write(conteudo)
            temporario = Path(alvo.name)
        captura = motor_video.VideoCapture(str(temporario))
        if not captura.isOpened():
            captura.release()
            return jsonify({"erro": "Não foi possível ler este formato de vídeo."}), 415
        total = int(captura.get(motor_video.CAP_PROP_FRAME_COUNT) or 0)
        quadros = []
        indices = sorted(set(round(i * max(0, total - 1) / 5) for i in range(6))) if total else [0]
        for indice in indices:
            if indice and not captura.set(motor_video.CAP_PROP_POS_FRAMES, indice):
                continue
            ok, quadro = captura.read()
            if not ok or quadro is None:
                continue
            escala = min(1.0, 960 / max(quadro.shape[1], 1))
            if escala < 1:
                quadro = motor_video.resize(quadro, None, fx=escala, fy=escala)
            ok, codificado = motor_video.imencode(".jpg", quadro, [motor_video.IMWRITE_JPEG_QUALITY, 82])
            if ok:
                quadros.append(base64.b64encode(codificado.tobytes()).decode("ascii"))
        captura.release()
        if not quadros:
            return jsonify({"erro": "Não foi possível extrair quadros legíveis do vídeo."}), 422
        if not llm_local.servidor_local_ativo():
            return jsonify({"erro": "LM Studio está desligado; não foi possível analisar os quadros."}), 503
        if not COMANDO_LOCK.acquire(blocking=False):
            return jsonify({"erro": "Outra análise está em andamento. Tente novamente."}), 429
        try:
            resposta = llm_local.chamar_visao_multiplas(
                f"{pergunta} A análise foi feita somente a partir de {len(quadros)} quadros amostrados do vídeo, não do vídeo inteiro.",
                quadros, timeout=180,
            )
        finally:
            COMANDO_LOCK.release()
        if not resposta:
            return jsonify({"erro": visao.mensagem_falha_servidor_local()}), 502
        resposta = f"Análise de {len(quadros)} quadros amostrados: {resposta}"
        criar_ou_tocar_sessao(sessao)
        salvar_mensagem_sessao(sessao, "user", f"[Vídeo enviado pelo Android — análise de {len(quadros)} quadros] {pergunta}")
        salvar_mensagem_sessao(sessao, "assistant", resposta)
        rotulo = rotulo_dispositivo({"device_label": "Android"})
        broadcast_ws({"type": "user_message", "session_id": sessao, "content": f"[Vídeo para análise] {pergunta}", "device_label": rotulo})
        broadcast_ws({"type": "external_assistant_message", "session_id": sessao, "content": resposta, "device_label": rotulo})
        if config.VOZ_ATIVA and falar_no_pc:
            threading.Thread(target=voz.falar, args=(resposta,), daemon=True).start()
        return jsonify({"resposta": resposta, "quadros_analisados": len(quadros)}), 200
    except Exception:
        log.exception("Falha ao analisar vídeo recebido do Android.")
        return jsonify({"erro": "O computador não conseguiu analisar este vídeo."}), 500
    finally:
        if temporario is not None:
            temporario.unlink(missing_ok=True)


@app.route("/fotos/<string:nome_arquivo>", methods=["GET"])
def servir_foto_recebida(nome_arquivo):
    nome_seguro = Path(nome_arquivo).name
    if nome_seguro != nome_arquivo or Path(nome_seguro).suffix.lower() != ".jpg":
        return jsonify({"erro": "não encontrado"}), 404

    caminho = (visao.PASTA_FOTOS_RECEBIDAS / nome_seguro).resolve()
    try:
        caminho.relative_to(visao.PASTA_FOTOS_RECEBIDAS.resolve())
    except ValueError:
        return jsonify({"erro": "não encontrado"}), 404

    if not caminho.is_file():
        return jsonify({"erro": "não encontrado"}), 404

    resposta = make_response(caminho.read_bytes())
    resposta.headers["Content-Type"] = "image/jpeg"
    resposta.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    return resposta




@app.route("/telefone/midia/aguardar", methods=["GET"])
def telefone_midia_aguardar():
    try:
        versao_recebida = int(request.args.get("versao", 0))
    except (TypeError, ValueError):
        versao_recebida = 0
    versao_recebida = max(0, versao_recebida)

    with COMANDO_MIDIA_TELEFONE_CONDICAO:
        COMANDO_MIDIA_TELEFONE_CONDICAO.wait_for(
            lambda: COMANDO_MIDIA_TELEFONE_VERSAO != versao_recebida,
            timeout=TIMEOUT_LONG_POLL_SEGUNDOS,
        )
        versao_atual = COMANDO_MIDIA_TELEFONE_VERSAO

    with COMANDO_MIDIA_TELEFONE_LOCK:
        acao_atual = (
            COMANDO_MIDIA_TELEFONE_ACAO if versao_atual != versao_recebida else None
        )

    return jsonify({"versao": versao_atual, "acao": acao_atual}), 200




@app.route("/pc/apps", methods=["GET"])
def pc_apps_disponiveis():
    return jsonify(pc_controle.listar_apps()), 200




@app.route("/pc/abrir_app", methods=["POST"])
def pc_abrir_app():
    origem = request.remote_addr
    dados = json_objeto() or {}
    nome = dados.get("app")
    if not isinstance(nome, str) or not nome.strip():
        return jsonify({"erro": "campo 'app' não informado"}), 400
    sucesso, mensagem = pc_controle.abrir_app(nome.strip())
    registrar_historico(f"[PC] abrir {nome.strip()}", mensagem, origem)
    return jsonify({"sucesso": sucesso, "mensagem": mensagem}), (
        200 if sucesso else 400
    )




@app.route("/pc/volume", methods=["POST"])
def pc_volume():
    origem = request.remote_addr
    dados = json_objeto() or {}
    acao = dados.get("acao")
    mensagem = pc_controle.controlar_volume(acao)
    registrar_historico(f"[PC] volume {acao}", mensagem, origem)
    return jsonify({"mensagem": mensagem}), 200




@app.route("/voz/volume", methods=["GET"])
def voz_volume_obter():
    return jsonify({"volume": round(voz.volume_percentual())}), 200




@app.route("/voz/volume", methods=["POST"])
def voz_volume_definir():
    dados = json_objeto() or {}
    try:
        pct = voz.definir_volume_percentual(dados.get("volume"))
    except (TypeError, ValueError, OSError):
        return jsonify({"erro": "Volume inválido."}), 400
    if dados.get("testar"):
        threading.Thread(
            target=voz.falar, args=("Volume ajustado, senhor.",), daemon=True
        ).start()
    return (
        jsonify(
            {"volume": round(pct), "mensagem": f"Volume do Jarvis em {round(pct)}%."}
        ),
        200,
    )




@app.route("/pc/midia", methods=["POST"])
def pc_midia():
    origem = request.remote_addr
    dados = json_objeto() or {}
    acao = dados.get("acao")
    mensagem = pc_controle.controlar_midia(acao)
    registrar_historico(f"[PC] mídia {acao}", mensagem, origem)
    return jsonify({"mensagem": mensagem}), 200




@app.route("/pc/bloquear", methods=["POST"])
def pc_bloquear():
    origem = request.remote_addr
    mensagem = pc_controle.bloquear_tela()
    registrar_historico("[PC] bloquear tela", mensagem, origem)
    return jsonify({"mensagem": mensagem}), 200




@app.route("/pc/desligar", methods=["POST"])
def pc_desligar():
    origem = request.remote_addr
    dados = json_objeto() or {}
    if not dados.get("confirmar"):
        return jsonify({"erro": "confirmação obrigatória (envie confirmar: true)"}), 400
    mensagem = pc_controle.desligar_pc()
    registrar_historico("[PC] desligar", mensagem, origem)
    log.warning("Desligamento do PC agendado remotamente por %s.", origem)
    return jsonify({"mensagem": mensagem}), 200




@app.route("/pc/reiniciar", methods=["POST"])
def pc_reiniciar():
    origem = request.remote_addr
    dados = json_objeto() or {}
    if not dados.get("confirmar"):
        return jsonify({"erro": "confirmação obrigatória (envie confirmar: true)"}), 400
    mensagem = pc_controle.reiniciar_pc()
    registrar_historico("[PC] reiniciar", mensagem, origem)
    log.warning("Reinício do PC agendado remotamente por %s.", origem)
    return jsonify({"mensagem": mensagem}), 200




@app.route("/pc/cancelar_desligamento", methods=["POST"])
def pc_cancelar_desligamento():
    origem = request.remote_addr
    mensagem = pc_controle.cancelar_desligamento()
    registrar_historico("[PC] cancelar desligamento/reinício", mensagem, origem)
    return jsonify({"mensagem": mensagem}), 200




@app.route("/painel", methods=["GET"])
def painel_web():
    return renderizar_arquivo_html(config.BASE_DIR / "jarvis.html")




# Abre painel separado de widgets
@app.route("/telas", methods=["GET"])
def painel_widgets():
    return renderizar_arquivo_html(config.BASE_DIR / "telas.html")

CALLBACK_TELA = None

# Registra abertura na janela nativa
def registrar_abertura_tela(callback):
    global CALLBACK_TELA
    CALLBACK_TELA = callback


@app.route("/interface/telas", methods=["GET","POST"])
def interface_telas():
    if request.method == "GET": return jsonify(telas_widgets.publico())
    if not ipaddress.ip_address(request.remote_addr or "0.0.0.0").is_loopback: return jsonify({"erro":"Edite as telas no computador"}),403
    try: return jsonify(telas_widgets.salvar(json_objeto()))
    except ValueError as erro: return jsonify({"erro":str(erro)}),400
    except RuntimeError as erro: return jsonify({"erro":str(erro)}),409

# Salva edição isolada da tela
@app.route("/interface/telas/editar", methods=["POST"])
def editar_tela_widgets():
    if not ipaddress.ip_address(request.remote_addr or "0.0.0.0").is_loopback: return jsonify({"erro":"Edite no computador"}),403
    try: return jsonify(telas_widgets.alterar(json_objeto()))
    except ValueError as erro: return jsonify({"erro":str(erro)}),400

# Solicita tela no monitor escolhido
@app.route("/interface/telas/abrir", methods=["POST"])
def abrir_tela_widgets():
    if not ipaddress.ip_address(request.remote_addr or "0.0.0.0").is_loopback: return jsonify({"erro":"Ação disponível no computador"}),403
    dados=json_objeto() or {}
    ident=dados.get("id")
    if ident != "principal" and not any(t["id"]==ident for t in telas_widgets.carregar()["telas"]): return jsonify({"erro":"Tela inexistente"}),404
    if CALLBACK_TELA is None: return jsonify({"erro":"Janela nativa indisponível"}),409
    CALLBACK_TELA(ident)
    return jsonify({"aberta":True})


# Mostra chave somente no PC local
@app.route("/interface/pareamento", methods=["GET"])
def interface_pareamento():
    if not ipaddress.ip_address(request.remote_addr or "0.0.0.0").is_loopback:return jsonify({"erro":"Disponível no PC"}),403
    fingerprint=""
    if https_local.ARQ_CERT.exists():
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes
        cert=x509.load_pem_x509_certificate(https_local.ARQ_CERT.read_bytes())
        fingerprint=cert.fingerprint(hashes.SHA256()).hex().upper()
    return jsonify({"chave":config.TOKEN_REMOTO,"certificado":fingerprint,"porta":PORTA_HTTPS_PADRAO,"ips":api_endereco().get_json().get("ips",[])})


@app.route("/interface/dashboard", methods=["GET"])
def interface_dashboard():
    processo=psutil.Process()
    processos=[processo]+processo.children(recursive=True)
    memoria_jarvis=0
    componentes=[]
    for item in processos:
        try:
            rss = item.memory_info().rss
            memoria_jarvis += rss
            componentes.append({"nome": "Serviço Jarvis" if item.pid == processo.pid else item.name(), "ram_mb": round(rss/2**20)})
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
    with CLIENTES_VISTOS_LOCK:
        clientes=[{"tipo":i["tipo"],"rotulo":i.get("rotulo"),"ultimo_segundos":round(time.time()-i["ultimo"])} for i in CLIENTES_VISTOS.values() if time.time()-i["ultimo"]<300]
    net=psutil.net_io_counters()
    return jsonify({**recursos_sistema.consultar(gpu_nvidia),"componentes":componentes,"celular":{k:v for k,v in resumo_celular().items() if k not in {"ip","rotulo"}},"disco":psutil.disk_usage(str(config.BASE_DIR)).percent,"jarvis_mb":round(memoria_jarvis/1024**2),"quantidade_processos_jarvis":len(processos),"rede_recebida":net.bytes_recv,"rede_enviada":net.bytes_sent,"clientes":clientes,"https":https_local.ARQ_CERT.exists(),"gmail":gmail.status()["conectado"],"google_agenda":google_agenda.status()["conectado"],"camera":vigia_camera.estado_atual().get("conectada",False)})

@app.route("/interface/sistema", methods=["GET"])
def sistema_widgets():
    return jsonify({"cpu":psutil.cpu_percent(interval=None),"ram":psutil.virtual_memory().percent,"disco":psutil.disk_usage(str(config.BASE_DIR)).percent})

# Consulta segurança sem nova captura
@app.route("/interface/seguranca", methods=["GET"])
def seguranca_widgets():
    estado=seguranca_stark.estado_atual()
    camera=vigia_camera.estado_atual()
    linha = vigia_camera.carregar_linha()
    linha_ativa = bool(estado.get("armado") and camera.get("conectada") and camera.get("camera_posicao_validada") and linha.get("ativa", True) and linha.get("definida"))
    return jsonify({"armado":bool(estado.get("armado")),"conectada":bool(camera.get("conectada")),"pessoas":int(camera.get("pessoas",0)),"ultima_deteccao":camera.get("ultimo_alerta"),"camera_movida":bool(camera.get("camera_movida")),"linha_ativa":linha_ativa,"linha_definida":bool(linha.get("definida")),"atualizado_em":time.time()})

@app.route("/painel-legado", methods=["GET"])
def painel_web_legado():
    return renderizar_arquivo_html(config.BASE_DIR / "jarvis.html")




@app.route("/comandos-rapidos", methods=["GET"])
def comandos_rapidos_api():
    return jsonify(COMANDOS_RAPIDOS), 200


_TIPOS_MIME_ESTATICOS = {
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".map": "application/json; charset=utf-8",
}

_EXTENSOES_TEXTO_ESTATICO = {".js", ".mjs", ".css", ".html", ".json", ".map"}

_PASTAS_ESTATICAS_BLOQUEADAS = {
    "data",
    "venv",
    "node_modules",
    "__pycache__",
    "sessao_whatsapp",
}




@app.route("/<path:nome_arquivo>", methods=["GET"])
def arquivo_estatico(nome_arquivo):
    extensao = Path(nome_arquivo).suffix.lower()
    tipo_mime = _TIPOS_MIME_ESTATICOS.get(extensao)
    if tipo_mime is None:
        return jsonify({"erro": "não encontrado"}), 404

    base = config.BASE_DIR.resolve()
    caminho = (base / nome_arquivo).resolve()
    try:
        relativo = caminho.relative_to(base)
    except ValueError:
        return jsonify({"erro": "não encontrado"}), 404

    if any(
        parte.startswith(".") or parte in _PASTAS_ESTATICAS_BLOQUEADAS
        for parte in relativo.parts
    ) or caminho.is_relative_to(config.DATA_DIR.resolve()):
        return jsonify({"erro": "não encontrado"}), 404

    # Publica somente arquivos da interface, nunca JSON de backups ou ferramentas.
    recurso = relativo.as_posix()
    if not (
        recurso in {"jarvis.html", "telas.html"}
        or relativo.parts[0] == "hud"
        or relativo.parts[:2] == ("interface", "static")
    ):
        return jsonify({"erro": "não encontrado"}), 404

    if not caminho.is_file():
        return jsonify({"erro": "não encontrado"}), 404

    try:
        if extensao in _EXTENSOES_TEXTO_ESTATICO:
            conteudo = caminho.read_text(encoding="utf-8")
            resposta = make_response(conteudo)
        else:
            resposta = make_response(caminho.read_bytes())
    except OSError:
        log.exception("Falha ao ler arquivo estático: %s", caminho)
        return jsonify({"erro": "não foi possível ler o arquivo"}), 500

    resposta.headers["Content-Type"] = tipo_mime
    resposta.headers["Cache-Control"] = "no-cache"
    return resposta




@app.route("/api/sessions", methods=["GET"])
def api_listar_sessoes():
    return jsonify(listar_sessoes_chat()), 200




@app.route("/api/sessions/<string:sessao_id>/messages", methods=["GET"])
def api_mensagens_sessao(sessao_id):
    try:
        limite = int(request.args.get("limit", 30))
    except (TypeError, ValueError):
        limite = 30
    return jsonify(listar_mensagens_sessao(sessao_id, limite)), 200




@app.route("/api/sessions/<string:sessao_id>", methods=["DELETE"])
def api_excluir_sessao(sessao_id):

    agora = datetime.now().astimezone().isoformat()
    try:
        with SESSOES_LOCK, closing(
            sqlite3.connect(DB_PATH_SESSOES, timeout=10)
        ) as conexao:
            conexao.execute("BEGIN IMMEDIATE")
            existe = conexao.execute(
                "SELECT 1 FROM sessoes WHERE id = ?", (sessao_id,)
            ).fetchone()
            if not existe:
                conexao.rollback()
                return jsonify({"mensagem": "Conversa ja estava excluida."}), 200
            conexao.execute("DELETE FROM mensagens WHERE sessao_id = ?", (sessao_id,))
            if sessao_id == SESSAO_PRINCIPAL_ID:
                conexao.execute(
                    "UPDATE sessoes SET titulo = ?, atualizado_em = ? WHERE id = ?",
                    (SESSAO_PRINCIPAL_TITULO, agora, sessao_id),
                )
            else:
                conexao.execute("DELETE FROM sessoes WHERE id = ?", (sessao_id,))
            conexao.commit()
        return jsonify({"mensagem": "Conversa excluída."}), 200
    except sqlite3.Error:
        log.exception("Não foi possível excluir a sessão de chat %s.", sessao_id)
        return jsonify({"erro": "Não foi possível excluir a conversa."}), 500


SESSAO_PRINCIPAL_ID = "principal"
SESSAO_PRINCIPAL_TITULO = "Sessão principal (PC + celular)"

CLIENTES_WS = set()
CLIENTES_WS_LOCK = threading.Lock()




def rotulo_dispositivo(dados: dict) -> str:
    rotulo = dados.get("device_label") if isinstance(dados, dict) else None
    if isinstance(rotulo, str) and rotulo.strip():
        return rotulo.strip()[:20]
    return "DISPOSITIVO"



# Registra cliente WS
def registrar_cliente_ws(ws):
    info = {"desde": time.time(), "ip": None}
    try:
        if has_request_context():
            info["ip"] = request.remote_addr
            info["tipo"], info["rotulo"] = classificar_cliente(request)
    except Exception:
        pass
    with CLIENTES_WS_LOCK:
        CLIENTES_WS.add(ws)
        WS_INFO[ws] = info



# Remove cliente WS
def remover_cliente_ws(ws):
    with CLIENTES_WS_LOCK:
        CLIENTES_WS.discard(ws)
        WS_INFO.pop(ws, None)




def broadcast_ws(mensagem: dict, excluir=None):
    if mensagem.get("type") == "security_event" and mensagem.get("event",{}).get("alertAllowed") is not False:
        leitor_dia.interromper()
    payload = json.dumps(mensagem)
    with CLIENTES_WS_LOCK:
        alvos = list(CLIENTES_WS)
    for cliente in alvos:
        if cliente is excluir:
            continue
        try:
            cliente.send(payload)
        except Exception:
            remover_cliente_ws(cliente)



def dispararPainelPessoal(texto):
    from comandos.briefing_dia import pedido
    if pedido(texto):
        broadcast_ws({"type":"daily_briefing_open","read":True})
        return
    from comandos.linguagem import normalizar_comando
    texto = normalizar_comando(texto)
    normal = unicodedata.normalize("NFKD", str(texto or "").casefold())
    normal = "".join(letra for letra in normal if not unicodedata.combining(letra))
    normal = re.sub(r"\be-?mail(s?)\b", r"email\1", normal)
    normal = re.sub(r"\s+", " ", normal).strip(" .!?;:")
    slide = None
    if re.search(r"\bcheguei(?: em casa)?\b|\b(resumo do dia|mostrar tudo|me mostre tudo|painel pessoal)\b", normal):
        slide = "news"
    elif re.search(r"\b(notici\w*|g1)\b", normal) and re.search(r"\b(ler|leia|mostrar|mostre|ver|quero|ultimas|resumo)\b", normal):
        slide = "news"
    elif re.search(r"\b(agenda|compromissos)\b", normal) and re.search(r"\b(mostrar|mostre|ver|tenho|ler|leia|resumo|hoje|agenda)\b", normal):
        slide = "agenda"
    elif re.search(r"\b(minhas notas|mostre as notas|mostrar notas|ler notas|leia minhas notas)\b", normal):
        slide = "notes"
    elif re.search(r"\b(meus emails|minha caixa de entrada|emails para responder|email para responder|responder emails?|emails? que preciso responder|ler meus emails|leia meus emails)\b", normal):
        slide = "email"
    if slide:
        ler = bool(re.search(r"\b(ler|leia)\b", normal))
        broadcast_ws({"type": "briefing", "slide": slide, "read": ler, "prepare": slide == "email"})



def publicarEventoZona(evento):
    ocorrido = {"hora": datetime.now().astimezone().isoformat(timespec="seconds"), **evento}
    ocorrido["abrirTela"] = bool(getattr(config, "ABRIR_TELA_ALERTA_CAMERA", True))
    seguranca_stark.registrar_evento("zona", **ocorrido)
    if ocorrido.get("alertAllowed", True) and ocorrido.get("event") not in ("entry", "dwell"):
        broadcast_ws({"type": "security_event", "event": ocorrido})


zonasCamera.definirCallbackEvento(publicarEventoZona)



def publicarEventoSeguranca(evento):
    ocorrido = dict(evento)
    ocorrido.setdefault("abrirTela", bool(getattr(config, "ABRIR_TELA_ALERTA_CAMERA", True)))
    broadcast_ws({"type": "security_event", "event": ocorrido})


seguranca_stark.definir_callback_evento(publicarEventoSeguranca)


if Sock is not None:
    sock = Sock(app)



    @sock.route("/ws")
    def rota_ws_chat(ws):
        registrar_cliente_ws(ws)
        sessao_atual = None
        try:
            while True:
                bruto = ws.receive()
                if bruto is None:
                    break
                try:
                    dados = json.loads(bruto)
                except (TypeError, ValueError):
                    continue
                if not isinstance(dados, dict):
                    continue

                chave_taxa_ws = f"{request.remote_addr or '?'}:/ws-mensagem"
                if not consumir_limite_taxa(chave_taxa_ws, 30, 60):
                    ws.send(
                        json.dumps(
                            {
                                "type": "error",
                                "content": "limite de mensagens por minuto atingido",
                            }
                        )
                    )
                    continue

                texto = dados.get("message")
                if not isinstance(texto, str) or not texto.strip():
                    continue
                texto = texto.strip()
                if len(texto) > 4000:
                    ws.send(
                        json.dumps(
                            {
                                "type": "error",
                                "content": "comando excede o limite de 4.000 caracteres",
                            }
                        )
                    )
                    continue

                rotulo = rotulo_dispositivo(dados)
                sessao_atual = (
                    dados.get("session_id") or sessao_atual or SESSAO_PRINCIPAL_ID
                )
                criar_ou_tocar_sessao(sessao_atual)
                salvar_mensagem_sessao(sessao_atual, "user", texto)

                broadcast_ws(
                    {
                        "type": "user_message",
                        "session_id": sessao_atual,
                        "content": texto,
                        "device_label": rotulo,
                    },
                    excluir=ws,
                )
                versao_pedido = llm_local.versao_cancelamento()
                llm_local.bloquear_requisicao(False)
                texto_chat = controller.PADRAO_WAKE_WORD_PREFIXO.sub(
                    "", texto, count=1
                ).strip(" ,.!?:;-\t")
                chamada_sem_comando = (
                    bool(controller.PADRAO_WAKE_WORD_PREFIXO.match(texto))
                    and not texto_chat
                )
                encerrando_conversa = voz.frase_encerra_conversa(texto)
                if encerrando_conversa:
                    broadcast_ws({"type": "start", "session_id": sessao_atual})
                    resposta = voz.RESPOSTA_ENCERRAMENTO
                elif chamada_sem_comando:
                    broadcast_ws({"type": "start", "session_id": sessao_atual})
                    resposta = (
                        controller.resposta_saudacao_local("jarvis") or "Sim, senhor?"
                    )
                else:
                    if not COMANDO_LOCK.acquire(blocking=False):
                        broadcast_ws(
                            {
                                "type": "error",
                                "session_id": sessao_atual,
                                "content": "outro comando ainda está em processamento",
                            }
                        )
                        continue
                    broadcast_ws({"type": "start", "session_id": sessao_atual})
                    try:
                        try:
                            resposta = asyncio.run(
                                controller.processar_comando(
                                    texto_chat, permitir_acesso_codigo=False
                                )
                            )
                        except Exception:
                            log.exception("Erro ao processar comando via WebSocket.")
                            broadcast_ws(
                                {
                                    "type": "error",
                                    "session_id": sessao_atual,
                                    "content": "Erro interno ao processar o comando.",
                                }
                            )
                            continue
                    finally:
                        COMANDO_LOCK.release()

                if llm_local.versao_cancelamento() != versao_pedido:
                    broadcast_ws({"type": "done", "session_id": sessao_atual})
                    continue
                if not isinstance(resposta, str):
                    resposta = str(resposta or "")
                if encerrando_conversa:
                    resposta = voz.RESPOSTA_ENCERRAMENTO
                else:
                    resposta = voz.com_pergunta_continuidade(resposta)

                if resposta == "SHUTDOWN_SIGNAL":
                    acionar_encerramento_remoto()
                    resposta = "Encerramento solicitado."

                resposta_final = resposta or "Comando não reconhecido."
                salvar_mensagem_sessao(sessao_atual, "assistant", resposta_final)
                registrar_historico(texto, resposta_final, "ws")

                broadcast_ws(
                    {
                        "type": "chunk",
                        "content": resposta_final,
                        "session_id": sessao_atual,
                    }
                )
                broadcast_ws({"type": "done", "session_id": sessao_atual})

                if config.VOZ_ATIVA:
                    threading.Thread(
                        target=voz.falar, args=(resposta_final,), daemon=True
                    ).start()
        finally:
            remover_cliente_ws(ws)

else:
    log.warning(
        "flask_sock não está instalado — a rota /ws (chat em tempo real da "
        "nova interface) ficará indisponível. Rode: pip install flask-sock"
    )




RESUMO_VISUAL = {"state":"idle"}
RESUMO_VISUAL_TRAVA = threading.Lock()

# Entrega cartão atual a outras telas
@app.route("/interface/resumo", methods=["GET"])
def resumo_widgets():
    with RESUMO_VISUAL_TRAVA: return jsonify(dict(RESUMO_VISUAL))

# Registra partes do resumo na sessão
def publicar_resumo(evento):
    with RESUMO_VISUAL_TRAVA:
        RESUMO_VISUAL.clear()
        RESUMO_VISUAL.update(evento)
    if evento.get("state") == "reading" and evento.get("texto"):
        salvar_mensagem_sessao(SESSAO_PRINCIPAL_ID,"assistant",evento["texto"])
    broadcast_ws(evento)

# Inicia resumo falado no computador
@app.route("/briefing/ler", methods=["POST"])
def briefing_ler():
    if not ipaddress.ip_address(request.remote_addr or "0.0.0.0").is_loopback:
        return jsonify({"erro":"Leitura disponível no computador"}),403
    dados = json_objeto()
    try:
        identificador = leitor_dia.iniciar(dados.get("itens") if dados else None, publicar_resumo)
        return jsonify({"id":identificador}),202
    except ValueError as erro:
        return jsonify({"erro":str(erro)}),400
    except RuntimeError as erro:
        return jsonify({"erro":str(erro)}),409

# Cancela apenas o resumo ativo
@app.route("/briefing/parar", methods=["POST"])
def briefing_parar():
    if not ipaddress.ip_address(request.remote_addr or "0.0.0.0").is_loopback:
        return jsonify({"erro":"Ação disponível no computador"}),403
    dados = json_objeto()
    identificador = dados.get("id") if dados else None
    if not isinstance(identificador,str): return jsonify({"erro":"Resumo inválido"}),400
    return jsonify({"parado":leitor_dia.parar(identificador)})

@app.route("/voz/falar", methods=["POST"])
def voz_falar():
    dados = json_objeto()
    texto = dados.get("texto") if dados else None
    if not isinstance(texto, str) or not texto.strip() or len(texto.strip()) > 500:
        return jsonify({"erro": "texto inválido"}), 400
    if not config.VOZ_ATIVA:
        return jsonify({"erro": "voz desativada"}), 409
    sucesso = voz.falar(texto.strip())
    return jsonify({"sucesso": bool(sucesso)}), (200 if sucesso else 503)




@app.route("/voz/transcricao", methods=["POST"])
def voz_transcricao():
    dados = json_objeto()
    texto = dados.get("texto") if dados else None
    if not isinstance(texto, str) or not texto.strip() or len(texto) > 2000:
        return jsonify({"erro": "transcrição inválida"}), 400

    print(f"[OUVIDO ANDROID] {texto.strip()}", flush=True)
    log.info("Transcrição de voz do Android: %s", texto.strip())
    return jsonify({"registrado": True}), 200




@app.route("/voz/sintetizar", methods=["POST"])
def voz_sintetizar():
    dados = json_objeto()
    if dados is None:
        return jsonify({"erro": "envie um objeto JSON válido"}), 400
    texto = dados.get("texto")
    if not isinstance(texto, str) or not texto.strip():
        return jsonify({"erro": "campo 'texto' não informado"}), 400
    texto = texto.strip()
    if len(texto) > 4000:
        return jsonify({"erro": "texto excede o limite de 4.000 caracteres"}), 400

    audio_wav = voz.sintetizar_bytes(texto)
    if not audio_wav:
        return jsonify({"erro": "não foi possível sintetizar o áudio"}), 500

    resposta_http = make_response(audio_wav, 200)
    resposta_http.headers["Content-Type"] = "audio/wav"
    resposta_http.headers["Content-Length"] = str(len(audio_wav))
    return resposta_http



# Sintetiza piper painel
def sintetizarPiperPainel():
    dados = json_objeto()
    texto = dados.get("texto") if dados else None
    if not isinstance(texto, str) or not texto.strip() or len(texto.strip()) > 1200:
        return jsonify({"erro": "Texto inv?lido para leitura."}), 400
    audio = voz.sintetizarBytesPiper(texto.strip())
    if not audio:
        return jsonify({"erro": "N?o foi poss?vel gerar a voz Piper. Confira se a voz do Jarvis est? ativa."}), 503
    resposta = make_response(audio, 200)
    resposta.headers["Content-Type"] = "audio/wav"
    resposta.headers["Content-Length"] = str(len(audio))
    return resposta


app.add_url_rule("/voz/sintetizar-piper", endpoint="sintetizarPiperPainel", view_func=sintetizarPiperPainel, methods=["POST"])



@app.route("/voz/parar", methods=["POST"])
def voz_parar():
    return jsonify({"sucesso": voz.parar_fala()}), 200




@app.route("/voz/interromper", methods=["POST"])
def voz_interromper():

    config.definir_voz_ativa(False)
    voz.parar_fala()
    ESCUTA_VOZ_PAUSAR.set()
    return jsonify({"sucesso": True}), 200




@app.route("/voz/escuta/ativar", methods=["POST"])
def voz_escuta_ativar():
    config.definir_voz_ativa(True)
    ESCUTA_VOZ_ATIVAR.set()
    return jsonify({"sucesso": True}), 200




@app.route("/voz/escuta/direta", methods=["POST"])
def voz_escuta_direta():
    config.definir_voz_ativa(True)
    ESCUTA_VOZ_ATIVAR.set()
    ESCUTA_VOZ_DIRETA.set()
    return jsonify({"sucesso": True}), 200




@app.route("/voz/escuta/encerrar", methods=["POST"])
def voz_escuta_encerrar():
    ESCUTA_VOZ_ENCERRAR.set()
    return jsonify({"sucesso": True}), 200




@app.route("/voz/escuta/desligar", methods=["POST"])
def voz_escuta_desligar():

    ESCUTA_VOZ_ATIVAR.clear()
    ESCUTA_VOZ_DESLIGAR.set()
    return jsonify({"sucesso": True}), 200




# Importa contatos do arquivo

@app.get("/interface/celular")
def estado_celular_widget():
    return jsonify({k: v for k, v in resumo_celular().items() if k not in {"ip", "rotulo"}})


@app.route("/pessoal/mensagens/celular", methods=["GET", "POST"])
def mensagens_celular():
    from interface import pessoal_celular
    if request.method == "GET":
        return jsonify(pessoal_celular.listar())
    dados = json_objeto()
    if not isinstance(dados, dict):
        return jsonify({"erro": "Envie um objeto JSON"}), 400
    try:
        nova, mensagem = pessoal_celular.salvar(dados)
    except ValueError as erro:
        return jsonify({"erro": str(erro)}), 400
    if nova:
        enviar_evento_painel_local({"type": "notification", "content": "WhatsApp · " + mensagem["remetente"] + ": " + mensagem["texto"]})
    return jsonify({"sucesso": True, "nova": nova}), 201 if nova else 200



@app.route("/memoria/estado", methods=["GET"])
def memoria_estado():
    from contextlib import closing
    try:
        with memoria.TRAVA, closing(memoria.conectar()) as conexao:
            saude = conexao.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            totais = {chave: conexao.execute("SELECT COUNT(*) FROM " + tabela).fetchone()[0]
                      for chave, tabela in [("notas", "notas_hud"), ("fatos", "fatos"), ("compromissos", "compromissos")]}
        return jsonify({"pronta": saude, **totais})
    except Exception:
        log.exception("Falha na verificação de memória")
        return jsonify({"pronta": False, "erro": "Memória indisponível"}), 503



@app.route("/whatsapp/contatos/importar", methods=["POST"])
def importar_contatos_whatsapp():
    arquivo = request.files.get("arquivo")
    if arquivo is None or not (arquivo.filename or "").casefold().endswith(".vcf"):
        return jsonify({"erro": "Selecione um arquivo .vcf de contatos."}), 400
    dados = arquivo.read(config.MAX_VCF_BYTES + 1)
    if len(dados) > config.MAX_VCF_BYTES:
        return jsonify({"erro": "Arquivo muito grande."}), 413
    if b"BEGIN:VCARD" not in dados.upper() or b"END:VCARD" not in dados.upper():
        return jsonify({"erro": "O arquivo não contém contatos vCard."}), 400
    pasta = config.DATA_DIR / "contatos"
    pasta.mkdir(parents=True, exist_ok=True)
    temporario = pasta / (uuid.uuid4().hex + ".vcf")
    try:
        temporario.write_bytes(dados)
        total, mensagem = config.importar_contatos_vcf(str(temporario))
        if not total:
            return jsonify({"erro": mensagem}), 400
        temporario.replace(pasta / "contatos_whatsapp.vcf")
        return jsonify({"importados": total, "mensagem": mensagem,
                        "total": len(config.listar_contatos_whatsapp())})
    finally:
        temporario.unlink(missing_ok=True)



@app.route("/whatsapp/contatos/estado", methods=["GET"])
def contatos_whatsapp_estado():
    return jsonify({"total": len(config.listar_contatos_whatsapp())})



@app.route("/voz/escuta/estado", methods=["GET"])
def voz_escuta_estado():


    dados = dict(ESTADO_ESCUTA_PC)
    dados["falando"] = voz.EM_REPRODUCAO.is_set()
    ESTADO_ESCUTA_PC["pico"] = 0
    return jsonify(dados), 200




# Consulta agenda local e Google
@app.route("/agenda/unificada", methods=["GET"])
def agenda_unificada():
    local=memoria.listar_compromissos(100)
    erro=None
    try:remotos=google_agenda.eventos()
    except (OSError,ValueError,KeyError,RuntimeError):remotos=[];erro="Não foi possível consultar a agenda Google"
    items=sorted(local+remotos,key=lambda i:i.get("inicio",""))
    return jsonify({"compromissos":items,"google_erro":erro,"google_conectado":google_agenda.status()["conectado"]})

# Prepara conexão da agenda no PC
@app.route("/agenda/google/status", methods=["GET"])
def agenda_google_status():return jsonify(google_agenda.status())

@app.route("/agenda/google/config", methods=["POST"])
def agenda_google_config():
    try:return jsonify(google_agenda.configurar(json_objeto()))
    except (ValueError,OSError):return jsonify({"erro":"Use o JSON OAuth de aplicativo para computador"}),400

@app.route("/agenda/google/conectar", methods=["POST","DELETE"])
def agenda_google_conectar():
    try:return jsonify(google_agenda.desconectar() if request.method=="DELETE" else google_agenda.conectar())
    except (OSError,ValueError,RuntimeError):return jsonify({"erro":"Configure o cliente OAuth no PC antes de conectar"}),409

@app.route("/agenda/google/callback", methods=["GET"])
def agenda_google_callback():
    try:
        google_agenda.retorno(request.args.get("code"),request.args.get("state"))
        return Response("Google Agenda conectado. Pode fechar esta aba.",content_type="text/plain; charset=utf-8")
    except (OSError,ValueError,KeyError):return Response("Autorização não concluída. Volte ao Jarvis e tente novamente.",status=400,content_type="text/plain; charset=utf-8")

@app.route("/agenda", methods=["GET"])
def agenda_listar():
    desde = request.args.get("desde", "", type=str)[:32] or None
    ate = request.args.get("ate", "", type=str)[:32] or None
    try:
        limite = request.args.get("limite", 50, type=int)
    except (TypeError, ValueError):
        limite = 50
    return jsonify(memoria.listar_compromissos(limite, desde, ate)), 200



@app.route("/agenda", methods=["POST"])
def agenda_salvar():
    dados = json_objeto()
    if dados is None:
        return jsonify({"erro": "envie um objeto JSON valido"}), 400
    identificador = memoria.criar_compromisso(
        dados.get("titulo"),
        dados.get("inicio"),
        dados.get("descricao", ""),
        dados.get("antecedencia_minutos", 10),
    )
    if identificador is None:
        return jsonify({"erro": "titulo ou data invalidos"}), 400
    return jsonify({"sucesso": True, "id": identificador}), 201



@app.route("/agenda/<int:identificador>", methods=["DELETE"])
def agenda_remover(identificador):
    sucesso = memoria.remover_compromisso(identificador)
    return jsonify({"sucesso": sucesso}), (200 if sucesso else 404)



@app.route("/memoria/notas", methods=["GET"])
def memoria_notas_listar():
    return jsonify(memoria.listar_notas_hud()), 200




@app.route("/memoria/notas", methods=["POST"])
def memoria_notas_salvar():
    dados = json_objeto()
    if dados is None:
        return jsonify({"erro": "envie um objeto JSON válido"}), 400
    sucesso = memoria.salvar_nota_hud(
        dados.get("id"),
        dados.get("area"),
        dados.get("title"),
        dados.get("body"),
    )
    return jsonify({"sucesso": sucesso}), (200 if sucesso else 400)




@app.route("/memoria/notas/<string:id_nota>/relacionadas", methods=["GET"])
def memoria_notas_relacionadas(id_nota):
    return jsonify(memoria.listar_notas_relacionadas(id_nota, limite=2)), 200




@app.route("/memoria/notas/<string:id_nota>", methods=["DELETE"])
def memoria_notas_remover(id_nota):
    sucesso = memoria.remover_nota_hud(id_nota)
    return jsonify({"sucesso": sucesso}), (200 if sucesso else 404)



@app.route("/gmail/status", methods=["GET"])
def gmail_status():
    resposta = jsonify(gmail.status())
    resposta.headers["Cache-Control"] = "no-store, private"
    return resposta, 200



@app.route("/gmail/config", methods=["POST"])
def gmail_configurar():
    dados = json_objeto()
    if dados is None:
        return jsonify({"erro": "Informe os dados do cliente OAuth do Gmail."}), 400
    sucesso, resultado = gmail.saveConfig(dados.get("clientId"), dados.get("clientSecret"))
    return (jsonify(resultado), 200) if sucesso else (jsonify({"erro": resultado}), 400)



@app.route("/gmail/conectar", methods=["POST"])
def gmail_conectar():
    sucesso, mensagem = gmail.startAuthorization()
    return jsonify({"mensagem": mensagem}), (200 if sucesso else 409)



@app.route("/gmail/conectar", methods=["DELETE"])
def gmail_desconectar():
    return jsonify(gmail.disconnect()), 200



@app.route("/gmail/callback", methods=["GET"])
def gmail_oauth_callback():
    return resposta_gmail_oauth(), 200



@app.route("/gmail/mensagens", methods=["GET"])
def gmail_mensagens():
    try:
        limite = request.args.get("limite", 18, type=int)
        resposta = jsonify({"mensagens": gmail.listMessages(limite)})
        resposta.headers["Cache-Control"] = "no-store, private"
        return resposta, 200
    except (RuntimeError, urllib.error.URLError, TimeoutError, ValueError):
        log.exception("Falha ao carregar mensagens da caixa de entrada Gmail.")
        return jsonify({"erro": "Não foi possível carregar a caixa de entrada. Confira a conexão Gmail."}), 503



@app.route("/gmail/resposta", methods=["POST"])
def gmail_preparar_resposta():
    dados = json_objeto()
    if dados is None or not dados.get("messageId"):
        return jsonify({"erro": "Selecione uma mensagem para preparar a resposta."}), 400
    try:
        rascunho = gmail.createDraft(dados.get("messageId"), dados.get("body", ""))
        return jsonify(rascunho), 200
    except RuntimeError as erro:
        log.warning("Não foi possível preparar resposta Gmail: %s", erro)
        return jsonify({"erro": str(erro)}), (409 if "rascunho aberto" in str(erro).casefold() else 503)
    except (urllib.error.URLError, TimeoutError, ValueError):
        log.exception("Falha ao preparar resposta Gmail.")
        return jsonify({"erro": "Não foi possível preparar a resposta. Escreva o texto manualmente e tente novamente."}), 503



@app.route("/gmail/resposta", methods=["PUT"])
def gmail_atualizar_resposta():
    dados = json_objeto()
    if dados is None:
        return jsonify({"erro": "Rascunho inválido."}), 400
    try:
        rascunho = gmail.updateDraft(dados.get("id"), dados.get("body", ""))
        return jsonify(rascunho), 200
    except ValueError as erro:
        return jsonify({"erro": str(erro)}), 400



@app.route("/gmail/enviar", methods=["POST"])
def gmail_enviar_resposta():
    dados = json_objeto()
    if dados is None or not dados.get("id"):
        return jsonify({"erro": "Confirme o rascunho aberto antes de enviar."}), 400
    sucesso, mensagem = gmail.sendPending(dados.get("id"))
    return jsonify({"mensagem": mensagem}), (200 if sucesso else 409)



@app.route("/gmail/rascunho", methods=["DELETE"])
def gmail_cancelar_rascunho():
    gmail.cancelDraft()
    return jsonify({"sucesso": True}), 200


# Lê campo feed
def lerCampoFeed(item, nomes):
    for campo in list(item):
        nome = campo.tag.rsplit("}", 1)[-1].lower()
        if nome in nomes:
            if nome == "link" and campo.attrib.get("href"):
                return campo.attrib["href"].strip()
            return (campo.text or "").strip()
    return ""



def imagemCampoFeed(item):
    for campo in item.iter():
        nome = campo.tag.rsplit("}", 1)[-1].lower()
        if nome not in {"thumbnail", "content", "enclosure", "image"}:
            continue
        url = (campo.attrib.get("url") or campo.attrib.get("href") or "").strip()
        destino = urlparse(url)
        host = (destino.hostname or "").lower()
        if destino.scheme == "https" and (host.endswith(".glbimg.com") or host in {"g1.globo.com", "g1.com.br"}):
            return url
    resumo = lerCampoFeed(item, {"description", "summary", "encoded", "content"})
    imagem = re.search(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", resumo, flags=re.IGNORECASE)
    if imagem:
        destino = urlparse(html.unescape(imagem.group(1)))
        host = (destino.hostname or "").lower()
        if destino.scheme == "https" and (host.endswith(".glbimg.com") or host in {"g1.globo.com", "g1.com.br"}):
            return destino.geturl()
    return ""


# Limpa resumo noticia
def limparResumoNoticia(valor):
    texto = re.sub(r"<[^>]*>", " ", html.unescape(valor or ""))
    return re.sub(r"\s+", " ", texto).strip()[:360]


# Carrega noticias
def carregarNoticias(categoria):
    agora = time.time()
    with NOTICIAS_CACHE_LOCK:
        armazenado = NOTICIAS_CACHE.get(categoria)
        if armazenado and agora - armazenado["hora"] < 300:
            return armazenado["dados"], True
    pedido = urllib.request.Request(FEEDS_NOTICIAS[categoria], headers={"User-Agent": "Mark2/1.0 news-reader", "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})
    with urllib.request.urlopen(pedido, timeout=6) as resposta:
        host = (urlparse(resposta.geturl()).hostname or "").lower()
        if not host.endswith(".globo.com"):
            raise ValueError("Feed redirecionou para dominio nao permitido.")
        bruto = resposta.read(2_000_001)
        compactacao = (resposta.headers.get("Content-Encoding") or "").lower()
    if len(bruto) > 2_000_000:
        raise ValueError("Feed excedeu o limite permitido.")
    if compactacao == "gzip":
        with gzip.GzipFile(fileobj=io.BytesIO(bruto)) as arquivo:
            bruto = arquivo.read(2_000_001)
    if len(bruto) > 2_000_000 or b"<!doctype" in bruto.lower() or b"<!entity" in bruto.lower():
        raise ValueError("Feed excedeu o limite permitido.")
    raiz = ElementTree.fromstring(bruto)
    itens = []
    for item in raiz.iter():
        if item.tag.rsplit("}", 1)[-1].lower() not in {"item", "entry"}:
            continue
        titulo = limparResumoNoticia(lerCampoFeed(item, {"title"}))
        link = lerCampoFeed(item, {"link"})
        destino = urlparse(link)
        if not titulo or destino.scheme != "https" or (destino.hostname or "").lower() not in {"g1.globo.com", "g1.com.br"}:
            continue
        itens.append({"titulo": titulo, "resumo": limparResumoNoticia(lerCampoFeed(item, {"description", "summary", "encoded", "content"})), "imagem": imagemCampoFeed(item), "url": link, "publicada": limparResumoNoticia(lerCampoFeed(item, {"pubdate", "published", "updated", "date"})), "fonte": "G1"})
        if len(itens) >= 20:
            break
    dados = {"categoria": categoria, "atualizado": datetime.now().astimezone().isoformat(timespec="minutes"), "noticias": itens}
    with NOTICIAS_CACHE_LOCK:
        NOTICIAS_CACHE[categoria] = {"hora": agora, "dados": dados}
    return dados, False



@app.route("/noticias/g1", methods=["GET"])
def noticiasG1():
    chave = f"{request.remote_addr or '?'}:/noticias/g1"
    if not consumir_limite_taxa(chave, 30, 60):
        return jsonify({"erro": "Muitas atualizacoes em pouco tempo."}), 429
    categoria = request.args.get("categoria", "geral", type=str).lower()
    if categoria not in FEEDS_NOTICIAS:
        return jsonify({"erro": "Categoria de noticias invalida."}), 400
    try:
        dados, cache = carregarNoticias(categoria)
        dados["cache"] = cache
        return jsonify(dados), 200
    except Exception as erro:
        log.warning("Falha ao consultar RSS do G1 (%s): %s", categoria, erro)
        with NOTICIAS_CACHE_LOCK:
            armazenado = NOTICIAS_CACHE.get(categoria)
            if armazenado and time.time() - armazenado["hora"] < 86400:
                dados = dict(armazenado["dados"])
                dados["cache"] = True
                dados["desatualizado"] = True
                return jsonify(dados), 200
        return jsonify({"erro": "Noticias temporariamente indisponiveis."}), 503



@app.route("/noticias/abrir", methods=["POST"])
def noticias_abrir_no_navegador():
    dados = json_objeto()
    url = str((dados or {}).get("url", "")).strip()
    destino = urlparse(url)
    host = (destino.hostname or "").lower()
    permitido = host in {"g1.globo.com", "g1.com.br"} or host.endswith(".g1.globo.com")
    if destino.scheme != "https" or not permitido:
        return jsonify({"erro": "O endereço não pertence ao G1."}), 400
    try:
        aberto = webbrowser.open(url, new=2)
    except (OSError, webbrowser.Error):
        log.exception("Não foi possível abrir a notícia no navegador do computador.")
        aberto = False
    if not aberto:
        return jsonify({"erro": "Não foi possível abrir o navegador padrão."}), 503
    log.info("Notícia do G1 aberta no navegador do computador: %s", url)
    return jsonify({"sucesso": True}), 200


@app.route("/api/smarthome/token", methods=["POST"])
def smarthome_salvar_token():
    dados = json_objeto()
    if dados is None or "token" not in dados:
        return jsonify({"erro": "token não fornecido"}), 400

    novo_token = str(dados["token"]).strip()

    if config.definir_smartthings_token(novo_token):
        smart_home.sincronizar_token(novo_token)
        return jsonify({"sucesso": True}), 200

    return jsonify({"erro": "não foi possível salvar a configuração"}), 500



@app.route("/api/smarthome/dispositivos", methods=["GET"])
def smarthome_listar_dispositivos():

    dispositivos = smart_home.carregar_dispositivos(forcar_atualizacao=True)
    return jsonify(dispositivos), 200




@app.route("/clima", methods=["GET"])
def clima_atual():
    try:
        dados = clima.obter_clima_atual()
    except clima.ClimaIndisponivel:
        return jsonify({"erro": "clima indisponível"}), 503
    if not dados:
        return jsonify({"erro": "clima indisponível"}), 503
    try:
        previsao = clima.obter_previsao_dia(0)
        dados["maxima_dia"] = previsao.get("maxima")
        dados["minima_dia"] = previsao.get("minima")
        dados["chance_chuva_dia_pct"] = previsao.get("chance_chuva_pct")
    except (KeyError, IndexError, TypeError, ValueError):
        dados["maxima_dia"] = None
        dados["minima_dia"] = None
    return jsonify(dados), 200





























































































def disparar_chegada_automatica(origem: str = "presenca-wifi") -> bool:
    """Dispara aviso de chegada."""
    limite = float(getattr(config, "PRESENCA_COOLDOWN_S", 1800))
    for evento in reversed(listar_eventos_rotina_hoje()):
        if evento.get("tipo") != "chegada":
            continue
        try:
            idade = (
                datetime.now().astimezone() - datetime.fromisoformat(evento["hora"])
            ).total_seconds()
        except (KeyError, ValueError):
            break
        if idade < limite:
            log.info("Chegada automática ignorada: já houve chegada há %.0f s.", idade)
            return False
        break
    if not COMANDO_LOCK.acquire(timeout=8):
        log.warning("Chegada automática adiada: outro comando em processamento.")
        return False
    try:
        resposta = asyncio.run(
            controller.processar_comando("cheguei", permitir_acesso_codigo=False)
        )
    except Exception:
        log.exception("Erro ao executar a rotina de chegada automática.")
        return False
    finally:
        COMANDO_LOCK.release()
    resposta = (
        resposta
        if isinstance(resposta, str) and resposta
        else "Chegada detectada pela rede."
    )
    try:
        from comandos.automacao.central_casa import disparar as disparar_rotina_casa
        rotina_casa = disparar_rotina_casa(evento="chegada")
        if rotina_casa:
            resposta = f"{resposta} {rotina_casa}".strip()
    except Exception:
        log.exception("Falha ao iniciar a rotina de casa vinculada à chegada.")
    registrar_historico("cheguei", resposta, origem)
    return True




def fmt_idade(segundos):
    segundos = int(max(0, segundos))
    if segundos < 90:
        return f"{segundos} s"
    if segundos < 5400:
        return f"{segundos // 60} min"
    if segundos < 172800:
        return f"{segundos // 3600} h"
    return f"{segundos // 86400} d"




def checar(func):

    try:
        r = func()
        return (r[0], r[1], r[2] if len(r) > 2 else None)
    except Exception as erro:
        log.debug("Checagem de conexão falhou.", exc_info=True)
        return "bad", f"erro: {type(erro).__name__}", None



_TS_CACHE = {"em": 0.0, "dados": None}
_TS_LOCK = threading.Lock()




def tailscale_status():
    with _TS_LOCK:
        if _TS_CACHE["dados"] is not None and time.monotonic() - _TS_CACHE["em"] < 10:
            return _TS_CACHE["dados"]
    exe = https_local.caminho_tailscale()
    if not exe:
        dados = {"instalado": False, "estado": None, "peers": []}
    else:
        try:
            saida = subprocess.run(
                [exe, "status", "--json"],
                capture_output=True,
                text=True,
                timeout=8,
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            bruto = json.loads(saida.stdout)
            peers = []
            for p in (bruto.get("Peer") or {}).values():
                endereco = str(p.get("CurAddr") or "").rsplit(":", 1)[0].strip("[]")
                try:
                    privado = (
                        bool(endereco) and ipaddress.ip_address(endereco).is_private
                    )
                except ValueError:
                    privado = False
                peers.append(
                    {
                        "nome": str(p.get("HostName") or p.get("DNSName") or "?"),
                        "dns": str(p.get("DNSName") or "").rstrip(".").lower(),
                        "os": str(p.get("OS") or ""),
                        "online": bool(p.get("Online")),
                        "direto": bool(endereco),
                        "lan": privado,
                        "ips": [str(i) for i in (p.get("TailscaleIPs") or [])],
                    }
                )
            dados = {
                "instalado": True,
                "estado": bruto.get("BackendState"),
                "ip": ((bruto.get("Self") or {}).get("TailscaleIPs") or [None])[0],
                "peers": peers,
            }
        except Exception:
            dados = {"instalado": True, "estado": "erro", "peers": []}
    with _TS_LOCK:
        _TS_CACHE.update(em=time.monotonic(), dados=dados)
    return dados




def peer_celular(ts):
    alvo = str(getattr(config, "CELULAR_TAILSCALE", "") or "").strip().lower()
    for p in ts["peers"]:
        nomes = {p["nome"].lower(), p["dns"], *[i.lower() for i in p["ips"]]}
        if (
            alvo
            and alvo != "auto"
            and (alvo in nomes or any(n.startswith(alvo + ".") for n in nomes))
        ):
            return p
    for p in ts["peers"]:
        if p["os"].lower() == "android":
            return p
    return None



_ST_CACHE = {"em": 0.0, "dados": None}
_ST_LOCK = threading.Lock()




def smartthings_estado():
    if _ST_CACHE["dados"] is not None and time.monotonic() - _ST_CACHE["em"] < 30:
        return _ST_CACHE["dados"]
    if not _ST_LOCK.acquire(blocking=False):
        return _ST_CACHE["dados"] or {"token": True, "online": None, "carregando": True}
    try:
        token = smart_home.obter_token()
        if not token:
            dados = {"token": False, "online": False, "dispositivos": 0, "tv": None}
        else:
            resp = smart_home.realizar_requisicao_get("devices", token)
            itens = resp.get("items") if resp else None
            dados = {
                "token": True,
                "online": isinstance(itens, list),
                "dispositivos": len(itens) if isinstance(itens, list) else 0,
                "tv": None,
            }
            if dados["online"]:
                try:
                    id_tv = smart_home.obter_id_tv()
                    if id_tv:
                        st = smart_home.realizar_requisicao_get(
                            f"devices/{id_tv}/status"
                        )
                        valor = st["components"]["main"]["switch"]["switch"]["value"]
                        dados["tv"] = {"ligada": valor == "on"}
                    else:
                        dados["tv"] = {"ligada": None}
                except (KeyError, TypeError):
                    dados["tv"] = {"ligada": None}
        _ST_CACHE.update(em=time.monotonic(), dados=dados)
        return dados
    finally:
        _ST_LOCK.release()




def resumo_celular():
    agora = time.time()
    with CLIENTES_VISTOS_LOCK:
        itens = [dict(v) for v in CLIENTES_VISTOS.values() if v["tipo"] == "celular"]
    if not itens:
        return {
            "visto": False,
            "conectado": False,
            "visto_ha_s": None,
            "ip": None,
            "rotulo": None,
        }
    ult = max(itens, key=lambda x: x["ultimo"])
    ha = agora - ult["ultimo"]
    return {
        "visto": True,
        "conectado": ha <= JANELA_CONECTADO_S,
        "visto_ha_s": round(ha),
        "ip": ult["ip"],
        "rotulo": ult["rotulo"],
    }





def chk_servidor_local():
    if not llm_local.disponivel():
        return "bad", "servidor LM Studio não responde", "OFFLINE"
    if not llm_local.servidor_local_ativo():
        return "warn", f"{llm_local.MODELO} · DESATIVADO pelo painel/app", "DESATIVADO"
    return "ok", llm_local.MODELO, "ONLINE"




def chk_servidor_local_visao():
    if llm_local.disponivel_visao():
        return "ok", llm_local.MODELO_VISAO, "ONLINE"
    return "warn", f"{llm_local.MODELO_VISAO} offline", "OFFLINE"




def chk_memoria():
    notas = memoria.listar_notas_hud()
    return "ok", f"{len(notas)} notas / {len(memoria.obter_fatos())} fatos"




def chk_sessoes():
    return "ok", f"{len(listar_sessoes_chat())} sessões"




def chk_smarthome():
    st = smartthings_estado()
    if not st.get("token"):
        return "off", "token SmartThings não configurado (API → Token)", "OFF"
    if st.get("online") is None:
        return "warn", "consultando…", "…"
    if st["online"]:
        return "ok", f"API respondendo · {st['dispositivos']} dispositivos", "ON"
    return "bad", "API não respondeu (token inválido ou sem internet)", "OFF"




def chk_tv():
    st = smartthings_estado()
    if not st.get("online"):
        return "off", "indisponível (SmartThings OFF)", "SEM STATUS"
    tv = st.get("tv") or {}
    if tv.get("ligada") is True:
        return "ok", "TV ligada", "LIGADA"
    if tv.get("ligada") is False:
        return "off", "TV desligada (ou em standby)", "DESLIGADA"
    return "warn", "TV não encontrada no SmartThings", "?"




def chk_celular_app():
    c = resumo_celular()
    if c["conectado"]:
        return (
            "ok",
            f"{c['rotulo']} · {c['ip']} · último contato há {fmt_idade(c['visto_ha_s'])}",
            "CONECTADO",
        )
    if c["visto"]:
        return (
            "off",
            f"{c['rotulo']} · último contato há {fmt_idade(c['visto_ha_s'])}",
            "DESCONECTADO",
        )
    return (
        "off",
        "nenhum contato desde que o servidor iniciou (abra o app no celular)",
        "DESCONECTADO",
    )




def chk_celular_casa():
    if not (
        getattr(config, "CELULAR_IP_LOCAL", "")
        or getattr(config, "CELULAR_TAILSCALE", "")
    ):
        return "off", "configure celular_ip_local / celular_tailscale", "NÃO CONFIG."
    if presenca.celular_em_casa():
        return "ok", "celular na rede de casa", "EM CASA"
    return "off", "sem sinal na rede de casa", "FORA"




def chk_tailscale():
    ts = tailscale_status()
    if not ts["instalado"]:
        return "off", "Tailscale não encontrado neste PC", "OFF"
    if ts["estado"] != "Running":
        return "bad", f"estado: {ts['estado']}", "OFF"
    online = sum(1 for p in ts["peers"] if p["online"])
    cel = peer_celular(ts)
    extra = ""
    if cel:
        extra = f" · celular {'online' if cel['online'] else 'offline'}"
        if cel["online"]:
            extra += (
                " (rede local)"
                if cel["lan"]
                else (" (direto)" if cel["direto"] else " (via relay)")
            )
    return "ok", f"{ts['ip']} · {online}/{len(ts['peers'])} peers online{extra}", "ON"




def chk_presenca():
    estado = presenca.estado_atual()
    if not estado.get("ativo"):
        return "off", "monitor inativo (configure celular_ip_local)", "OFF"
    return "ok", f"celular: {estado.get('estado')}", "ATIVA"




def chk_voz():
    elevenlabs = voz.elevenlabs_configurada()
    modelo_piper = getattr(voz, "PIPER_MODELO", None)
    piper = bool(modelo_piper and Path(modelo_piper).is_file())
    if elevenlabs and piper:
        return "ok", "ElevenLabs + Piper (reserva)"
    if elevenlabs:
        return "ok", "ElevenLabs"
    if piper:
        return "ok", "Piper local"
    return "bad", "nenhum sintetizador disponível", "OFFLINE"




def chk_visao():
    if visao.captura_ao_vivo_ativa():
        return "ok", "câmera ao vivo ATIVA", "AO VIVO"
    return "ok", "pronta (câmera em espera)", "PRONTA"




def chk_clima():
    try:
        disponivel = clima.obter_clima_atual()
    except clima.ClimaIndisponivel:
        disponivel = None
    return ("ok", "online") if disponivel else ("warn", "indisponível (sem internet?)")




def chk_https():
    existe = https_local.ARQ_CERT.exists() and https_local.ARQ_CHAVE.exists()
    return (
        ("ok", f"certificado presente · porta {PORTA_HTTPS_PADRAO}")
        if existe
        else ("warn", "sem certificado (só HTTP)")
    )




def chk_websocket():
    with CLIENTES_WS_LOCK:
        n = len(CLIENTES_WS)
    return (
        ("ok", f"{n} painel(is) web conectado(s)")
        if n
        else ("warn", "nenhum painel web conectado")
    )


CHECAGENS_CONEXOES = (
    ("servidor_local", "SERVIDOR_LOCAL (TEXTO)", chk_servidor_local),
    ("servidor_local_visao", "SERVIDOR_LOCAL (VISÃO)", chk_servidor_local_visao),
    ("memoria", "MEMÓRIA", chk_memoria),
    ("sessoes", "SESSÕES", chk_sessoes),
    ("smarthome", "SMARTTHINGS", chk_smarthome),
    ("tv", "TV", chk_tv),
    ("celular_app", "CELULAR ↔ JARVIS", chk_celular_app),
    ("celular_casa", "CELULAR NO WI-FI", chk_celular_casa),
    ("tailscale", "TAILSCALE", chk_tailscale),
    ("presenca", "PRESENÇA", chk_presenca),
    ("voz", "VOZ (TTS)", chk_voz),
    ("visao", "VISÃO", chk_visao),
    ("clima", "CLIMA", chk_clima),
    ("https", "HTTPS", chk_https),
    ("websocket", "WEBSOCKET", chk_websocket),
)





def gpu_nvidia():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        saida = (
            subprocess.run(
                [
                    exe,
                    "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=4,
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            .stdout.strip()
            .splitlines()[0]
        )
        nome, uso, mu, mt, temp = [x.strip() for x in saida.split(",")]
        return {
            "nome": nome,
            "uso": float(uso),
            "vram_usada_mb": float(mu),
            "vram_total_mb": float(mt),
            "temp": float(temp),
        }
    except Exception:
        return None




def dados_pc():
    raiz = (os.environ.get("SystemDrive", "C:") + "\\") if os.name == "nt" else "/"
    mem = psutil.virtual_memory()
    d = {
        "host": platform.node(),
        "so": f"{platform.system()} {platform.release()}",
        "cpu": psutil.cpu_percent(interval=0.2),
        "nucleos": psutil.cpu_count(),
        "ram": mem.percent,
        "ram_gb": [round(mem.used / 2**30, 1), round(mem.total / 2**30, 1)],
        "uptime_s": round(time.time() - psutil.boot_time()),
        "gpu": gpu_nvidia(),
        "bateria": None,
        "disco": None,
    }
    try:
        disco = psutil.disk_usage(raiz)
        d["disco"] = {
            "pct": disco.percent,
            "livre_gb": round(disco.free / 2**30, 1),
            "unidade": raiz,
        }
    except Exception:
        pass
    try:
        bat = psutil.sensors_battery()
        if bat is not None:
            d["bateria"] = {
                "pct": round(bat.percent),
                "carregando": bool(bat.power_plugged),
            }
    except Exception:
        pass
    return d




def dados_jarvis():
    with HISTORICO_LOCK:
        interacoes = len(HISTORICO)
        ultima = HISTORICO[-1].get("hora") if HISTORICO else None
    with CLIENTES_WS_LOCK:
        ws = len(CLIENTES_WS)
    atividade = llm_local.obter_atividade()
    return {
        "uptime_s": round(time.time() - INICIO_SERVIDOR),
        "porta_http": PORTA_PADRAO,
        "porta_https": PORTA_HTTPS_PADRAO,
        "modelo": llm_local.MODELO,
        "modelo_visao": llm_local.MODELO_VISAO,
        "servidor_local_ativo": llm_local.servidor_local_ativo(),
        "llm_etapa": atividade.get("etapa"),
        "llm_gerando": atividade.get("ativo"),
        "interacoes": interacoes,
        "ultima_interacao": ultima,
        "paineis_ws": ws,
        "eventos_rotina_hoje": len(listar_eventos_rotina_hoje()),
        "presenca": presenca.estado_atual(),
    }




def lista_dispositivos():
    agora = time.time()
    lista = [
        {
            "id": "pc",
            "nome": "ESTE PC (JARVIS)",
            "estado": "ok",
            "detalhe": f"{platform.node()} · servidor ativo há {fmt_idade(agora - INICIO_SERVIDOR)}",
        }
    ]
    c = resumo_celular()
    lista.append(
        {
            "id": "celular",
            "nome": "CELULAR (APP ANDROID)",
            "estado": "ok" if c["conectado"] else "off",
            "detalhe": (
                f"{c['rotulo']} · {c['ip']} · há {fmt_idade(c['visto_ha_s'])}"
                if c["visto"]
                else "nunca conectou desde que o servidor iniciou"
            ),
            "texto": "CONECTADO" if c["conectado"] else "DESCONECTADO",
        }
    )
    with CLIENTES_VISTOS_LOCK:
        vistos = [dict(v) for v in CLIENTES_VISTOS.values() if v["tipo"] != "celular"]
    for v in sorted(vistos, key=lambda x: -x["ultimo"]):
        ha = agora - v["ultimo"]
        if ha > 900:
            continue
        lista.append(
            {
                "id": f"web:{v['ip']}",
                "nome": v["rotulo"].upper(),
                "estado": "ok" if ha <= JANELA_CONECTADO_S else "off",
                "detalhe": f"{v['ip']} · há {fmt_idade(ha)}",
                "texto": "CONECTADO" if ha <= JANELA_CONECTADO_S else "INATIVO",
            }
        )
    ts = tailscale_status()
    for p in ts["peers"]:
        lista.append(
            {
                "id": f"ts:{p['nome']}",
                "nome": f"TAILSCALE · {p['nome'].upper()}",
                "estado": "ok" if p["online"] else "off",
                "detalhe": f"{p['os'] or '?'} · "
                + (
                    "rede local"
                    if p["online"] and p["lan"]
                    else (
                        "direto"
                        if p["online"] and p["direto"]
                        else "via relay" if p["online"] else "offline"
                    )
                ),
                "texto": "ONLINE" if p["online"] else "OFFLINE",
            }
        )
    st = smartthings_estado()
    lista.append(
        {
            "id": "smartthings",
            "nome": "SMARTTHINGS",
            "estado": "ok" if st.get("online") else "off",
            "detalhe": (
                f"{st.get('dispositivos', 0)} dispositivos"
                if st.get("online")
                else "token ausente ou API offline"
            ),
            "texto": "ON" if st.get("online") else "OFF",
        }
    )
    tv = (st.get("tv") or {}).get("ligada")
    lista.append(
        {
            "id": "tv",
            "nome": "TV",
            "estado": "ok" if tv else "off",
            "detalhe": (
                "ligada"
                if tv
                else ("desligada / standby" if tv is False else "sem status")
            ),
            "texto": "LIGADA" if tv else "DESLIGADA" if tv is False else "?",
        }
    )
    return lista




@app.route("/api/conexoes", methods=["GET"])
def api_conexoes():

    inicio = time.monotonic()
    resultados = {}
    extras = {}
    pool = ThreadPoolExecutor(max_workers=len(CHECAGENS_CONEXOES) + 3)
    futuros = {
        pool.submit(checar, func): ("itens", chave, nome)
        for chave, nome, func in CHECAGENS_CONEXOES
    }
    for chave, func in (("pc", dados_pc), ("jarvis", dados_jarvis)):
        futuros[pool.submit(lambda f=func: ("ok", f(), None))] = ("extra", chave, chave)
    try:
        for futuro, (tipo, chave, nome) in futuros.items():
            restante = max(0.1, 7.0 - (time.monotonic() - inicio))
            try:
                estado, detalhe, texto = futuro.result(timeout=restante)
            except FuturesTimeout:
                estado, detalhe, texto = "bad", "tempo esgotado", None
            except Exception:
                estado, detalhe, texto = "bad", "erro", None
            if tipo == "extra":
                extras[chave] = detalhe if estado == "ok" else None
            else:
                item = {"nome": nome, "estado": estado, "detalhe": detalhe}
                if texto:
                    item["texto"] = texto
                resultados[chave] = item
    finally:
        pool.shutdown(wait=False)
    try:
        dispositivos = lista_dispositivos()
    except Exception:
        log.debug("Falha ao montar a lista de dispositivos.", exc_info=True)
        dispositivos = []
    return (
        jsonify(
            {
                "itens": resultados,
                "pc": extras.get("pc"),
                "jarvis": extras.get("jarvis"),
                "dispositivos": dispositivos,
                "celular": resumo_celular(),
                "tempo_ms": round((time.monotonic() - inicio) * 1000),
            }
        ),
        200,
    )




@app.route("/presenca/estado", methods=["GET"])
def presenca_estado():
    return jsonify(presenca.estado_atual())





@app.route("/seguranca/zonas", methods=["GET"])
def segurancaZonasObter():
    return jsonify({"zonas": zonasCamera.listarZonas()}), 200



@app.route("/seguranca/zonas", methods=["POST"])
def segurancaZonasSalvar():
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict) or not isinstance(dados.get("zonas"), list):
        return jsonify({"erro": "Envie a lista de zonas desenhadas."}), 400
    try:
        zonas = zonasCamera.salvarZonas(dados["zonas"])
    except ValueError as erro:
        return jsonify({"erro": str(erro)}), 400
    except OSError:
        log.exception("Falha ao salvar zonas de seguranca.")
        return jsonify({"erro": "Nao foi possivel salvar as zonas."}), 500
    registrar_historico("[SEGURANCA] zonas atualizadas", f"{len(zonas)} zona(s)", request.remote_addr)
    return jsonify({"zonas": zonas}), 200



@app.route("/seguranca/eventos/revisar", methods=["POST"])
def segurancaEventoRevisar():
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({"erro": "Dados de revisao invalidos."}), 400
    rating = dados.get("rating")
    if not isinstance(rating, str) or rating not in {"correta", "falso"}:
        return jsonify({"erro": "Escolha deteccao correta ou falso alerta."}), 400
    eventTime = dados.get("eventTime")
    if not isinstance(eventTime, str) or len(eventTime) > 40:
        return jsonify({"erro": "Evento de origem invalido."}), 400
    try:
        datetime.fromisoformat(eventTime)
    except ValueError:
        return jsonify({"erro": "Horario do evento invalido."}), 400
    seguranca_stark.registrar_evento(
        "revisao",
        rating=rating,
        eventTime=eventTime,
        eventType=str(dados.get("eventType", ""))[:32],
        zoneId=str(dados.get("zoneId", ""))[:48],
    )
    registrar_historico("[SEGURANCA] evento revisado", rating, request.remote_addr)
    return jsonify({"salvo": True}), 200



@app.route("/seguranca/deteccoes/hoje", methods=["GET"])
def seguranca_deteccoes_hoje():
    from datetime import timezone

    agora = datetime.now(timezone(timedelta(hours=-3)))
    inicio = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    eventos = []
    for original in seguranca_stark.eventosEntre(inicio, inicio + timedelta(days=1), limite=None):
        if original.get("tipo") != "pessoa":
            continue
        evento = dict(original)
        if evento.get("foto"):
            evento["foto"] = Path(str(evento["foto"]).replace("\\", "/")).name
        eventos.append(evento)
    eventos.sort(key=lambda evento: datetime.fromisoformat(evento["hora"]), reverse=True)
    return jsonify({"eventos": eventos}), 200


@app.get("/seguranca/eventos/historico")
def historico_capturas():
    eventos = seguranca_stark.historico_pessoas(dias=7, limite=1000)
    return jsonify({"eventos": eventos})


@app.route("/seguranca/estado", methods=["GET"])
def seguranca_estado():
    estado = seguranca_stark.estado_atual()
    camera = vigia_camera.estado_atual()
    linha = vigia_camera.carregar_linha()
    armado = bool(estado.get("armado"))
    linha_ativa = bool(
        armado and camera.get("conectada") and camera.get("camera_posicao_validada")
        and linha.get("ativa", True) and linha.get("definida")
    )
    foto = Path(camera["ultima_foto"]).name if camera.get("ultima_foto") else None
    eventos = []
    for evento in reversed(seguranca_stark.ultimos_eventos(8)):
        evento = dict(evento)
        if evento.get("foto"):
            evento["foto"] = Path(evento["foto"]).name
        eventos.append(evento)
    return jsonify({
        "ativa": armado or bool(getattr(config, "SEGURANCA_ATIVA", False)),
        "pose": visao_inteligente.estado().get("pose", {}),
        "gravacao_continua": vigia_camera.GRAVADOR_EVENTOS.status() if vigia_camera.GRAVADOR_EVENTOS is not None else {"ativo": False},
        **estado,
        "pessoas_detectadas": vigia_camera.GRAVADOR_EVENTOS.status()["pessoas_24h"] if vigia_camera.GRAVADOR_EVENTOS is not None else 0,
        "linha_ativa": linha_ativa,
        "status": "armado" if armado else "desarmado",
        "zona_topo_pct": linha.get("zona_topo_pct", 65.0),
        "zona_linha_pct": linha.get("zona_linha_pct"),
        "camera": {
            "ativo": bool(camera.get("ativo")),
            "conectada": bool(camera.get("conectada")),
            "camera_movida": bool(camera.get("camera_movida")),
            "camera_posicao_validada": bool(camera.get("camera_posicao_validada")),
            "gravando": bool(vigia_camera.GRAVADOR_EVENTOS and vigia_camera.GRAVADOR_EVENTOS.status()["ativo"]),
            "gravar_video": True,
            "pessoas": camera.get("pessoas", 0),
            "deteccoes_incertas": camera.get("deteccoes_incertas", 0),
            "noite": bool(camera.get("noite")),
            "resolucao": camera.get("resolucao"),
            "deteccao_nativa": camera.get("deteccao_nativa", "aguardando detector"),
            "movimento": bool(camera.get("movimento")),
            "ultimo_movimento": camera.get("ultimo_movimento"),
            "ptz_estado": camera.get("ptz_estado", "desativado"),
        },
        "fala": {
            "ativa": bool(getattr(config, "CAMERA_FALA_ATIVA", False)),
            "go2rtc": fala_camera.go2rtc_online() if getattr(config, "CAMERA_FALA_ATIVA", False) else False,
        },
        "ultima_foto": foto,
        "eventos": eventos,
    })



@app.route("/seguranca/onvif", methods=["GET", "POST"])
def seguranca_onvif():
    if request.method == "GET":
        camera = vigia_camera.estado_atual()
        return jsonify({
            "host": config.CAMERA_ONVIF_HOST,
            "porta": config.CAMERA_ONVIF_PORTA,
            "usuario": config.CAMERA_ONVIF_USUARIO,
            "senha_configurada": bool(config.CAMERA_ONVIF_SENHA),
            "ptz_ativo": bool(getattr(config, "VIGIA_PTZ_ATIVO", False)),
            "ptz_estado": camera.get("ptz_estado", "desativado"),
            "capacidades": vigia_camera.capacidades_ptz(),
        }), 200
    dados = json_objeto()
    if not dados:
        return jsonify({"erro": "Informe os dados ONVIF."}), 400
    host = str(dados.get("host", "")).strip()
    usuario = str(dados.get("usuario", "")).strip()
    senha = dados.get("senha", "")
    try:
        porta = int(dados.get("porta", 8899))
    except (TypeError, ValueError):
        return jsonify({"erro": "Informe uma porta ONVIF válida."}), 400
    if not host or len(host) > 253 or not re.fullmatch(r"[A-Za-z0-9.-]+", host) or ".." in host:
        return jsonify({"erro": "Informe o IP ou nome de rede da câmera."}), 400
    if not 1 <= porta <= 65535 or not usuario or len(usuario) > 128:
        return jsonify({"erro": "Confira a porta e o usuário ONVIF."}), 400
    if not isinstance(senha, str) or len(senha) > 512:
        return jsonify({"erro": "A senha ONVIF é inválida."}), 400
    if not senha:
        senha = config.CAMERA_ONVIF_SENHA
    if not senha:
        return jsonify({"erro": "Informe a senha configurada no iCSee."}), 400
    valores = (
        ("camera_onvif_host", host, "CAMERA_ONVIF_HOST"),
        ("camera_onvif_porta", porta, "CAMERA_ONVIF_PORTA"),
        ("camera_onvif_usuario", usuario, "CAMERA_ONVIF_USUARIO"),
        ("camera_onvif_senha", senha, "CAMERA_ONVIF_SENHA"),
    )
    for chave, valor, atributo in valores:
        if not config.persistir_valor(chave, valor):
            return jsonify({"erro": "Não foi possível salvar os dados da câmera."}), 500
        setattr(config, atributo, valor)
    vigia_camera.configurar_onvif()
    return jsonify({"salvo": True, "senha_configurada": True, "ptz_estado": "conectando"}), 200





@app.route("/seguranca/ptz", methods=["POST"])
def seguranca_ptz_manual():
    dados = json_objeto()
    if dados is None:
        return jsonify({"erro": "Envie o comando PTZ no formato JSON."}), 400
    comando = str(dados.get("comando", ""))
    capacidades = vigia_camera.capacidades_ptz()
    if comando not in capacidades:
        return jsonify({"erro": "Comando PTZ inválido."}), 400
    if not capacidades.get(comando):
        return jsonify({"erro": "A câmera não anunciou suporte ONVIF para este movimento."}), 409
    try:
        velocidade = float(dados.get("velocidade", 0.2))
        duracao = float(dados.get("duracao", 0.2))
    except (TypeError, ValueError):
        return jsonify({"erro": "Velocidade ou duração PTZ inválida."}), 400
    manter = dados.get("manter", False) is True and comando != "stop"
    if not 0.1 <= velocidade <= 1.0 or not 0.2 <= duracao <= 1.0:
        return jsonify({"erro": "Use velocidade de 0,1 a 1 e duração de 0,2 a 1 segundo."}), 400
    sucesso, mensagem = vigia_camera.controlar_ptz(comando, velocidade, duracao, manter=manter)
    if not sucesso:
        return jsonify({"erro": mensagem}), 502
    registrar_historico("[SEGURANÇA] PTZ manual", comando, request.remote_addr)
    return jsonify({"mensagem": mensagem, "comando": comando}), 200



@app.route("/seguranca/armar", methods=["POST"])
def seguranca_armar():
    # Um pedido explícito para armar também habilita o protocolo mestre.
    if not bool(getattr(config, "SEGURANCA_ATIVA", False)):
        sucesso, resultado = config.definirOpcao("SEGURANCA_ATIVA", True)
        if not sucesso:
            return jsonify({"erro": str(resultado)}), 500
    mensagem = seguranca_stark.armar("android" if request.headers.get("X-Mark2-Dispositivo") else "painel")
    if "desativado nas configurações" in mensagem.lower():
        return jsonify({"erro": mensagem}), 409
    registrar_historico("[SEGURANÇA] armar", mensagem, request.remote_addr)
    anunciar_seguranca(mensagem, reproduzir_no_pc=not bool(request.headers.get("X-Mark2-Dispositivo")))
    return jsonify({"mensagem": mensagem}), 200





@app.route("/seguranca/desarmar", methods=["POST"])
def seguranca_desarmar():
    mensagem = seguranca_stark.desarmar("android" if request.headers.get("X-Mark2-Dispositivo") else "painel")
    registrar_historico("[SEGURANÇA] desarmar", mensagem, request.remote_addr)
    anunciar_seguranca(mensagem, reproduzir_no_pc=not bool(request.headers.get("X-Mark2-Dispositivo")))
    return jsonify({"mensagem": mensagem}), 200




def anunciar_seguranca(mensagem, reproduzir_no_pc=True):

    if reproduzir_no_pc and config.VOZ_ATIVA and mensagem:
        threading.Thread(
            target=voz.falar,
            args=(mensagem,),
            daemon=True,
            name="mark2-aviso-seguranca",
        ).start()




@app.route("/preferencias", methods=["GET"])
def preferencias_listar():
    return jsonify({"itens": config.listarOpcoes()})




@app.route("/preferencias", methods=["POST"])
def preferencias_definir():
    dados = json_objeto()
    if not dados or "chave" not in dados or "valor" not in dados:
        return jsonify({"erro": "Informe a chave e o valor."}), 400
    sucesso, resultado = config.definirOpcao(dados["chave"], dados["valor"])
    if not sucesso:
        return jsonify({"erro": resultado}), 400
    if dados["chave"] == "SEGURANCA_ATIVA" and resultado["valor"] is False and seguranca_stark.estado_atual().get("armado"):
        mensagem = seguranca_stark.desarmar("configuracoes")
        anunciar_seguranca(mensagem)
    registrar_historico(
        "[CONFIG] alterar",
        f'{resultado["chave"]} = {resultado["valor"]}',
        request.remote_addr,
    )
    return jsonify(resultado), 200





@app.route("/seguranca/falas", methods=["GET"])
def seguranca_falas():
    return jsonify(
        {
            "falas": [
                {"id": i, "rotulo": rotulo, "texto": texto}
                for i, (rotulo, texto) in enumerate(fala_camera.predefinidas())
            ]
        }
    )





@app.route("/seguranca/falar", methods=["POST"])
def seguranca_falar():
    if not getattr(config, "CAMERA_FALA_ATIVA", False):
        return jsonify({"erro": "A fala pela câmera está desativada."}), 409

    dados = json_objeto() or {}
    indice = dados.get("predefinida")
    if isinstance(indice, int) and not isinstance(indice, bool):
        falas = fala_camera.predefinidas()
        if not 0 <= indice < len(falas):
            return jsonify({"erro": "Fala não encontrada."}), 400
        texto = falas[indice][1]
    else:
        texto = dados.get("texto")
    if not isinstance(texto, str) or not texto.strip():
        return jsonify({"erro": "Informe o texto."}), 400
    texto = " ".join(texto.split())
    if len(texto) > 300:
        return jsonify({"erro": "O texto passa de 300 caracteres."}), 400

    threading.Thread(
        target=fala_camera.falar, args=(texto,), daemon=True, name="mark2-fala-camera"
    ).start()
    registrar_historico("[SEGURANÇA] falar na câmera", texto, request.remote_addr)
    return jsonify({"mensagem": "Enviando para o alto-falante da câmera."}), 202




@app.route("/seguranca/camera/volume", methods=["GET"])
def seguranca_camera_volume_obter():
    return jsonify({"volume": round(fala_camera.volume_percentual())}), 200




@app.route("/seguranca/camera/volume", methods=["POST"])
def seguranca_camera_volume_definir():
    dados = json_objeto() or {}
    try:
        pct = fala_camera.definir_volume_percentual(dados.get("volume"))
    except (TypeError, ValueError):
        return jsonify({"erro": "Volume inválido."}), 400
    if dados.get("testar"):
        if not getattr(config, "CAMERA_FALA_ATIVA", False):
            return jsonify({"erro": "A fala pela câmera está desativada."}), 409
        threading.Thread(
            target=fala_camera.falar,
            args=("Teste de volume do alto-falante.",),
            daemon=True,
            name="mark2-fala-camera",
        ).start()
    return (
        jsonify(
            {"volume": round(pct), "mensagem": f"Volume da câmera em {round(pct)}%."}
        ),
        200,
    )





@app.route("/seguranca/linha", methods=["GET"])
def seguranca_linha_obter():
    return jsonify(vigia_camera.carregar_linha()), 200




@app.route("/seguranca/linha", methods=["POST"])
def seguranca_linha_salvar():
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        return jsonify({"erro": "dados inválidos"}), 400
    try:
        salvo = vigia_camera.salvar_linha(dados)
    except ValueError as erro:
        return jsonify({"erro": str(erro)}), 400
    return jsonify(salvo), 200





@app.route("/seguranca/aviso/audio", methods=["GET"])
def audio_aviso_seguranca():
    audio = voz.sintetizar_bytes("Protocolo Torre Stark. Pessoa detectada na area restrita.", respeitar_voz_ativa=False)
    if not audio:
        return jsonify({"erro": "Aviso sonoro indisponivel"}), 503
    return Response(audio, mimetype="audio/wav")

# Lista gravacoes android
@app.route("/seguranca/gravacoes")
def listar_gravacoes_android():
    atual = vigia_camera.gravacao_atual()
    eventos = seguranca_stark.ultimos_eventos(1000)
    arquivos = []
    for caminho in vigia_camera.PASTA_ALERTAS.glob("*.mp4"):
        if not vigia_camera._ARQUIVO_SEGURANCA_RE.fullmatch(caminho.name) or caminho == atual:
            continue
        estat = caminho.stat()
        base = caminho.stem
        try:
            quando = datetime.strptime(base.split("_")[1] + "_" + base.split("_")[2], "%Y%m%d_%H%M%S")
            hora = quando.astimezone().isoformat(timespec="seconds")
        except (IndexError, ValueError):
            quando = datetime.fromtimestamp(estat.st_mtime).astimezone()
            hora = quando.isoformat(timespec="seconds")
        evento = next((item for item in reversed(eventos)
                       if str(item.get("foto", "")).replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0] == base), {})
        classe = base.split("_", 1)[0]
        tipo = str(evento.get("tipo") or ("pessoa" if classe == "pessoa" else "movimento" if classe in {"linha", "movimento"} else "gravacao"))
        zona = str(evento.get("zoneName") or evento.get("zona") or evento.get("zone") or "")
        if tipo == "pessoa":
            titulo = "Pessoa detectada" + (f" — {zona}" if zona else "")
        elif tipo in {"linha", "movimento", "zona"}:
            titulo = "Movimento identificado" + (f" — {zona}" if zona else "")
        else:
            titulo = "Gravação de segurança" + (f" — {zona}" if zona else "")
        nome_foto = str(evento.get("foto") or "").replace("\\", "/").rsplit("/", 1)[-1]
        if not nome_foto or not (vigia_camera.PASTA_ALERTAS / nome_foto).is_file():
            candidato = caminho.with_suffix(".jpg")
            nome_foto = candidato.name if candidato.is_file() and vigia_camera._ARQUIVO_SEGURANCA_RE.fullmatch(candidato.name) else ""
        duracao = evento.get("duracao_segundos") or evento.get("duration_seconds")
        try:
            duracao = float(duracao) if duracao is not None else None
        except (TypeError, ValueError):
            duracao = None
        if not duracao:
            try:
                motor_video = vigia_camera.cv2
                if motor_video is None:
                    raise RuntimeError("OpenCV não está disponível")
                captura = motor_video.VideoCapture(str(caminho))
                fps = captura.get(motor_video.CAP_PROP_FPS)
                quadros = captura.get(motor_video.CAP_PROP_FRAME_COUNT)
                captura.release()
                duracao = round(quadros / fps, 2) if fps and quadros > 0 else None
            except Exception:
                duracao = None
        arquivos.append({
            "nome": caminho.name, "titulo": titulo, "tipo": tipo,
            "hora": str(evento.get("hora") or hora), "duracao_segundos": duracao,
            "zona": zona or None, "foto": nome_foto or None,
            "tamanho": estat.st_size,
            "url": "/seguranca/evento/arquivo/" + quote(caminho.name),
        })
    arquivos.sort(key=lambda item: item["nome"], reverse=True)
    return jsonify({"gravacoes": arquivos[:50]})


@app.route("/seguranca/gravacao/<string:nome>")
def gravacao_android(nome):
    return arquivo_evento(nome, ".mp4")


@app.route("/seguranca/evento/imagem/<string:nome>")
def imagem_evento(nome):
    return arquivo_evento(nome, ".jpg")


@app.route("/seguranca/evento/arquivo/<string:nome>")
def video_evento_arquivo(nome):
    return arquivo_evento(nome, ".webm" if nome.endswith(".webm") else ".mp4")


def arquivo_evento(nome, extensao):
    if not vigia_camera._ARQUIVO_SEGURANCA_RE.fullmatch(nome) or Path(nome).suffix.lower() != extensao:
        return jsonify({"erro": "Arquivo invalido"}), 400
    raiz = vigia_camera.PASTA_ALERTAS.resolve()
    caminho = (raiz / nome).resolve()
    if caminho.parent != raiz or not caminho.is_file():
        return jsonify({"erro": "Registro nao encontrado"}), 404
    return send_file(caminho, conditional=True)


@app.route("/seguranca/evento/video")
def video_evento():
    foto = request.args.get("foto", "")
    if not foto:
        hora = request.args.get("hora", "")
        for evento in reversed(seguranca_stark.ultimos_eventos(200)):
            if evento.get("hora") == hora and evento.get("foto"):
                foto = Path(evento["foto"]).name
                break
    if not vigia_camera._ARQUIVO_SEGURANCA_RE.fullmatch(foto) or Path(foto).suffix.lower() != ".jpg":
        return jsonify({"erro": "Evento sem foto registrada"}), 404
    nome = Path(foto).with_suffix(".mp4").name
    destino = vigia_camera.PASTA_ALERTAS / nome
    with vigia_camera.EVENTOS_VIDEO_TRAVA:
        estado_video = vigia_camera.EVENTOS_VIDEO.get(nome)
    if vigia_camera.GRAVADOR_EVENTOS is not None:
        estado_video = vigia_camera.GRAVADOR_EVENTOS.estado(nome) or estado_video
    if destino.is_file():
        ffmpeg = vigia_camera.localizar_ffmpeg()
        if not reprodutor_eventos.verificar(destino, ffmpeg):
            return jsonify({"erro": "Este arquivo foi gravado sem imagem reproduzível. Novos eventos usarão a captura corrigida."}), 404
        if request.args.get("formato") == "webm":
            compatibilidade = reprodutor_eventos.preparar(destino, ffmpeg)
            if compatibilidade == "erro":
                return jsonify({"erro": "Não foi possível preparar o vídeo para este painel."}), 404
            if compatibilidade != "pronto":
                return jsonify({"status": "compatibilidade"}), 202
            nome = destino.with_suffix(".webm").name
        return jsonify({"url": "/seguranca/evento/arquivo/" + quote(nome)}), 200
    if estado_video in ("gravando", "processando"):
        return jsonify({"status": estado_video}), 202
    return jsonify({"erro": "Falha na gravacao" if estado_video == "erro" else "Gravacao nao disponivel para este evento"}), 404


@app.route("/seguranca/hud", methods=["GET"])
def seguranca_hud():
    leve = request.args.get("leve") == "1"
    estado = vigia_camera.estado_hud(leve=leve)
    try:
        acesso_local = ipaddress.ip_address(request.remote_addr or "").is_loopback
    except ValueError:
        acesso_local = False
    if not acesso_local:
        estado["poses"] = []
    return jsonify(estado), 200



@app.route("/seguranca/ao-vivo/stream", methods=["GET"])
def seguranca_stream_ao_vivo():
    base = str(getattr(config, "GO2RTC_URL", "http://127.0.0.1:1984") or "").rstrip("/")
    servidor = urlparse(base)
    if servidor.scheme not in ("http", "https") or servidor.hostname not in ("127.0.0.1", "localhost", "::1") or servidor.username or servidor.password:
        return jsonify({"erro": "O servidor de vídeo local não está configurado."}), 503
    return jsonify({
        "duas_lentes": bool(getattr(config, "VIGIA_DUAS_LENTES", False)),
        "lente": "baixo",
        "divisao_y": float(getattr(config, "VIGIA_DIVISAO_Y", 0.5)),
    }), 200



@app.route("/seguranca/ao-vivo/webrtc", methods=["POST"])
def seguranca_webrtc():
    if request.content_length and request.content_length > 1000000:
        return jsonify({"erro": "A oferta de vídeo é grande demais."}), 413
    oferta = request.get_data(cache=False, as_text=True)
    if not oferta.startswith("v=0"):
        return jsonify({"erro": "A oferta de vídeo é inválida."}), 400
    base = str(getattr(config, "GO2RTC_URL", "http://127.0.0.1:1984") or "").rstrip("/")
    servidor = urlparse(base)
    if servidor.scheme not in ("http", "https") or servidor.hostname not in ("127.0.0.1", "localhost", "::1") or servidor.username or servidor.password:
        return jsonify({"erro": "O servidor de vídeo local não está configurado."}), 503
    fonte = urlparse(str(getattr(config, "CAMERA_A28_URL", "") or ""))
    stream = fonte.path.strip("/").split("/")[-1] or "a28"
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", stream):
        return jsonify({"erro": "O endereço do fluxo da A28 é inválido."}), 503
    requisicao = urllib.request.Request(
        f"{base}/api/webrtc?src={quote(stream, safe='')}",
        data=oferta.encode("utf-8"),
        headers={"Content-Type": "application/sdp", "Accept": "application/sdp"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(requisicao, timeout=12) as resposta:
            corpo = resposta.read(1000000)
            return Response(corpo, status=resposta.status, content_type="application/sdp")
    except (urllib.error.URLError, TimeoutError, OSError):
        return jsonify({"erro": "Não foi possível iniciar o vídeo ao vivo da A28."}), 503




@app.route("/seguranca/linha/quadro.jpg", methods=["GET"])
def seguranca_linha_quadro():
    if vigia_camera.quadro_recente(3.0) is None:
        return jsonify({"erro": "sem imagem recente da camera"}), 503
    imagem = vigia_camera.quadro_jpeg(
        mostrarIA=request.args.get("ia") == "1",
        mostrarZonas=request.args.get("zonas") == "1",
    )
    if imagem is None:
        return jsonify({"erro": "sem imagem da câmera"}), 503
    resposta = make_response(imagem)
    resposta.headers["Content-Type"] = "image/jpeg"
    resposta.headers["Cache-Control"] = "no-store"
    return resposta




@app.route("/seguranca/linha/testar", methods=["POST"])
def seguranca_linha_testar():

    vigia_camera.registrar_cruzamento("positivo")
    return jsonify({"mensagem": "Cruzamento simulado no HUD."}), 200





@app.route("/seguranca/testar", methods=["POST"])
def seguranca_testar():
    if not seguranca_stark.estado_atual()["armado"]:
        return jsonify({"erro": "Arme o protocolo antes de testar."}), 409
    quadro = vigia_camera.ultimo_quadro()
    if quadro is None or vigia_camera.cv2 is None:
        return jsonify({"erro": "A câmera A28 não está enviando imagem."}), 409
    try:
        vigia_camera.PASTA_ALERTAS.mkdir(parents=True, exist_ok=True)
        caminho = (
            vigia_camera.PASTA_ALERTAS
            / f"pessoa_teste_{datetime.now():%Y%m%d_%H%M%S}.jpg"
        )
        vigia_camera.cv2.imwrite(str(caminho), quadro)
    except Exception:
        log.exception("Falha ao salvar a foto do teste de segurança.")
        return jsonify({"erro": "Não consegui salvar a foto do teste."}), 500
    threading.Thread(
        target=seguranca_stark.ao_detectar,
        args=(str(caminho), 1),
        daemon=True,
        name="mark2-teste-seguranca",
    ).start()
    return jsonify({"mensagem": "Detecção simulada enviada."}), 202





@app.route("/logs", methods=["GET"])
def logs_listar():
    try:
        desde = int(request.args.get("desde", 0))
    except (TypeError, ValueError):
        desde = 0
    return jsonify(painel_log.listar(desde)), 200




@app.route("/logs/limpar", methods=["POST"])
def logs_limpar():
    painel_log.limpar()
    return jsonify({"sucesso": True}), 200



REGEX_LINHA_LOG = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(?:,\d+)? (\w+) ([\w.\-]+): (.*)$"
)
ORDEM_NIVEL_LOG = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}



# Lê log arquivo
def ler_log_arquivo(nivel_min="INFO", busca="", limite=300):
    pasta = config.DATA_DIR / "logs"
    atual = pasta / "mark2.log"
    arquivos = [pasta / f"mark2.log.{indice}" for indice in range(3, 0, -1)]
    arquivos.append(atual)
    linhas = []
    for arquivo in arquivos:
        try:
            linhas.extend(arquivo.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue

    minimo = ORDEM_NIVEL_LOG.get(nivel_min, 1)
    busca = busca.lower().strip()
    itens = []
    for linha in linhas:
        m = REGEX_LINHA_LOG.match(linha)
        if m:
            itens.append(
                {
                    "data": m.group(1),
                    "hora": m.group(2),
                    "nivel": m.group(3),
                    "modulo": m.group(4).replace("mark2.", "", 1),
                    "msg": m.group(5),
                }
            )
        elif itens and linha.strip():
            itens[-1]["msg"] += "\n" + linha

    saida = []
    for item in itens:
        if ORDEM_NIVEL_LOG.get(item["nivel"], 1) < minimo:
            continue
        if busca and busca not in (item["modulo"] + " " + item["msg"]).lower():
            continue
        saida.append(item)
    return saida[-limite:]




@app.route("/logs/arquivo", methods=["GET"])
def logs_arquivo():
    nivel = str(request.args.get("nivel", "INFO")).upper()
    busca = str(request.args.get("q", ""))[:80]
    try:
        limite = max(1, min(1000, int(request.args.get("limite", 300))))
    except (TypeError, ValueError):
        limite = 300
    return jsonify({"linhas": ler_log_arquivo(nivel, busca, limite)}), 200




@app.route("/rotina-historico", methods=["GET"])
def rotina_historico():
    return jsonify(listar_eventos_rotina_hoje()), 200



# Inicia servidor remoto
def iniciar_servidor_remoto(porta: int = PORTA_PADRAO, host: str | None = None):
    if not isinstance(porta, int) or isinstance(porta, bool) or not 1 <= porta <= 65535:
        raise ValueError("porta inválida")
    host_efetivo = host or "127.0.0.1"
    try:
        host_loopback = ipaddress.ip_address(host_efetivo.split("%", 1)[0]).is_loopback
    except ValueError:
        host_loopback = host_efetivo.lower() == "localhost"
    if not host_loopback:
        raise ValueError(
            "HTTP panel server must bind only to loopback; use HTTPS for remote access"
        )
    log.info(
        "Servidor remoto (HTTP) em %s:%d — redes permitidas: %s",
        host_efetivo,
        porta,
        ", ".join(str(rede) for rede in REDES_PERMITIDAS),
    )
    servir_com_threading(host_efetivo, porta)



# Inicia servidor remoto https
def iniciar_servidor_remoto_https(
    porta: int = PORTA_HTTPS_PADRAO, host: str | None = None
):
    contexto_ssl = https_local.obter_contexto_ssl()
    if not contexto_ssl:
        log.warning(
            "Sem certificado disponível: a câmera do celular NÃO vai "
            "funcionar (o app exige HTTPS na porta separada). "
            "Instale o pacote 'cryptography' (pip install cryptography) pra "
            "gerar um certificado autoassinado automaticamente, ou instale o "
            "Tailscale com HTTPS habilitado na tailnet."
        )
        return
    if not isinstance(porta, int) or isinstance(porta, bool) or not 1 <= porta <= 65535:
        raise ValueError("porta inválida")
    host_efetivo = host or "0.0.0.0"
    log.info(
        "HTTPS ativo em %s:%d — é a porta que o app Android usa "
        "(câmera e demais recursos).",
        host_efetivo,
        porta,
    )
    servir_com_threading(host_efetivo, porta, contexto_ssl)




def servir_com_threading(host, porta, ssl_context=None):
    servidor = make_server(
        host, porta, app, threaded=True, ssl_context=ssl_context
    )
    servidor.daemon_threads = True
    servidor.block_on_close = False
    with SERVIDORES_HTTP_LOCK:
        SERVIDORES_HTTP.add(servidor)
    try:
        servidor.serve_forever()
    finally:
        servidor.server_close()
        with SERVIDORES_HTTP_LOCK:
            SERVIDORES_HTTP.discard(servidor)



# Para servidores remotos
def parar_servidores_remotos():
    SERVIDORES_HTTP_PARAR.set()
    with CLIENTES_WS_LOCK:
        clientes = tuple(CLIENTES_WS)
    for cliente in clientes:
        try:
            cliente.close()
        except Exception:
            log.debug("WebSocket ja encerrado.")
    try:
        presenca.parar()
        seguranca_stark.parar()
    except Exception:
        log.exception("Falha ao interromper os serviços de câmera e presença.")
    with SERVIDORES_HTTP_LOCK:
        servidores = tuple(SERVIDORES_HTTP)
    for servidor in servidores:
        try:
            servidor.shutdown()
        except Exception:
            log.debug("Falha ao encerrar um servidor HTTP.", exc_info=True)
    limite = time.monotonic() + 2.0
    for thread in (SERVIDOR_THREAD, SERVIDOR_THREAD_HTTPS):
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, limite - time.monotonic()))




def executar_com_reinicio(funcao, *argumentos):
    while not SERVIDORES_HTTP_PARAR.is_set():
        try:
            funcao(*argumentos)
            return
        except Exception:
            if SERVIDORES_HTTP_PARAR.is_set():
                return
            log.exception(
                "O servidor remoto (%s) caiu; reiniciando em 3 s.", funcao.__name__
            )
            SERVIDORES_HTTP_PARAR.wait(3)




def ao_detectar_na_camera(caminho_foto, quantidade, **detalhes):
    seguranca_stark.ao_detectar(caminho_foto, quantidade, **detalhes)



# Inicia servidor remoto thread
def iniciar_servidor_remoto_thread(
    porta: int = PORTA_PADRAO, host: str | None = None
) -> threading.Thread:
    global SERVIDOR_THREAD, SERVIDOR_THREAD_HTTPS
    with SERVIDOR_THREAD_LOCK:
        if not any(
            thread is not None and thread.is_alive()
            for thread in (SERVIDOR_THREAD, SERVIDOR_THREAD_HTTPS)
        ):
            SERVIDORES_HTTP_PARAR.clear()
        if SERVIDOR_THREAD is None or not SERVIDOR_THREAD.is_alive():
            SERVIDOR_THREAD = threading.Thread(
                target=executar_com_reinicio,
                args=(iniciar_servidor_remoto, porta, "127.0.0.1"),
                daemon=True,
                name="mark2-servidor-remoto",
            )
            SERVIDOR_THREAD.start()
        if SERVIDOR_THREAD_HTTPS is None or not SERVIDOR_THREAD_HTTPS.is_alive():
            SERVIDOR_THREAD_HTTPS = threading.Thread(
                target=executar_com_reinicio,
                args=(iniciar_servidor_remoto_https, porta + 1, host),
                daemon=True,
                name="mark2-servidor-remoto-https",
            )
            SERVIDOR_THREAD_HTTPS.start()
        from comandos.automacao.central_casa import iniciar_agendador
        iniciar_agendador()
        presenca.iniciar(disparar_chegada_automatica)
        seguranca_stark.iniciar(callback=ao_detectar_na_camera)
        return SERVIDOR_THREAD


DB_PATH_SESSOES = config.DATA_DIR / "sessoes_chat.db"

SESSOES_LOCK = threading.Lock()



# Inicializa sessoes chat
def inicializar_sessoes_chat():
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with SESSOES_LOCK, closing(
            sqlite3.connect(DB_PATH_SESSOES, timeout=10)
        ) as conexao:
            conexao.execute(
                "CREATE TABLE IF NOT EXISTS sessoes ("
                "id TEXT PRIMARY KEY, titulo TEXT, "
                "criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL)"
            )
            conexao.execute(
                "CREATE TABLE IF NOT EXISTS mensagens ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, sessao_id TEXT NOT NULL, "
                "papel TEXT NOT NULL, conteudo TEXT NOT NULL, criado_em TEXT NOT NULL)"
            )
            conexao.execute(
                "CREATE INDEX IF NOT EXISTS idx_mensagens_sessao "
                "ON mensagens(sessao_id, id)"
            )
            conexao.commit()
    except (OSError, sqlite3.Error):
        log.exception("Não foi possível inicializar o banco de sessões de chat.")


inicializar_sessoes_chat()




def garantir_sessao_principal():
    agora = datetime.now().astimezone().isoformat()
    try:
        with SESSOES_LOCK, closing(
            sqlite3.connect(DB_PATH_SESSOES, timeout=10)
        ) as conexao:
            conexao.execute(
                "INSERT INTO sessoes (id, titulo, criado_em, atualizado_em) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
                (SESSAO_PRINCIPAL_ID, SESSAO_PRINCIPAL_TITULO, agora, agora),
            )
            conexao.commit()
    except sqlite3.Error:
        log.exception("Não foi possível preparar a sessão principal de chat.")


garantir_sessao_principal()



# Gera ID sessao
def gerar_id_sessao() -> str:
    return uuid.uuid4().hex[:16]



# Cria ou tocar sessao
def criar_ou_tocar_sessao(sessao_id: str):
    agora = datetime.now().astimezone().isoformat()
    try:
        with SESSOES_LOCK, closing(
            sqlite3.connect(DB_PATH_SESSOES, timeout=10)
        ) as conexao:
            conexao.execute(
                "INSERT INTO sessoes (id, titulo, criado_em, atualizado_em) "
                "VALUES (?, NULL, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET atualizado_em = excluded.atualizado_em",
                (sessao_id, agora, agora),
            )
            conexao.commit()
    except sqlite3.Error:
        log.exception("Não foi possível registrar a sessão de chat %s.", sessao_id)



# Salva mensagem sessao
def salvar_mensagem_sessao(sessao_id: str, papel: str, conteudo: str):
    if (
        papel not in {"user", "assistant"}
        or not isinstance(conteudo, str)
        or not conteudo.strip()
    ):
        return
    agora = datetime.now().astimezone().isoformat()
    try:
        with SESSOES_LOCK, closing(
            sqlite3.connect(DB_PATH_SESSOES, timeout=10)
        ) as conexao:
            conexao.execute(
                "INSERT INTO mensagens (sessao_id, papel, conteudo, criado_em) "
                "VALUES (?, ?, ?, ?)",
                (sessao_id, papel, conteudo[:8000], agora),
            )
            if papel == "user":
                linha = conexao.execute(
                    "SELECT titulo FROM sessoes WHERE id = ?", (sessao_id,)
                ).fetchone()
                if linha and not linha[0]:
                    titulo = conteudo.strip()[:60]
                    conexao.execute(
                        "UPDATE sessoes SET titulo = ? WHERE id = ?",
                        (titulo, sessao_id),
                    )
            conexao.execute(
                "UPDATE sessoes SET atualizado_em = ? WHERE id = ?",
                (agora, sessao_id),
            )
            conexao.commit()
    except sqlite3.Error:
        log.exception("Não foi possível salvar mensagem da sessão %s.", sessao_id)



# Lista sessoes chat
def listar_sessoes_chat(limite: int = 50) -> list:
    try:
        with SESSOES_LOCK, closing(
            sqlite3.connect(DB_PATH_SESSOES, timeout=10)
        ) as conexao:
            conexao.row_factory = sqlite3.Row
            sessoes = conexao.execute(
                "SELECT id, titulo, criado_em, atualizado_em FROM sessoes "
                "ORDER BY atualizado_em DESC LIMIT ?",
                (max(1, min(limite, 200)),),
            ).fetchall()
            resultado = []
            for sessao in sessoes:
                contagem = conexao.execute(
                    "SELECT COUNT(*) FROM mensagens WHERE sessao_id = ?",
                    (sessao["id"],),
                ).fetchone()[0]
                ultima = conexao.execute(
                    "SELECT conteudo FROM mensagens WHERE sessao_id = ? "
                    "ORDER BY id DESC LIMIT 1",
                    (sessao["id"],),
                ).fetchone()
                resultado.append(
                    {
                        "id": sessao["id"],
                        "title": sessao["titulo"],
                        "preview": (ultima[0][:80] if ultima else ""),
                        "date": (sessao["atualizado_em"] or "")[:10],
                        "message_count": contagem,
                    }
                )
            return resultado
    except sqlite3.Error:
        log.exception("Não foi possível listar as sessões de chat.")
        return []



# Lista mensagens sessao
def listar_mensagens_sessao(sessao_id: str, limite: int = 30) -> list:
    try:
        with SESSOES_LOCK, closing(
            sqlite3.connect(DB_PATH_SESSOES, timeout=10)
        ) as conexao:
            conexao.row_factory = sqlite3.Row
            linhas = conexao.execute(
                "SELECT papel, conteudo FROM mensagens WHERE sessao_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (sessao_id, max(1, min(limite, 200))),
            ).fetchall()
            return [
                {"role": linha["papel"], "content": linha["conteudo"]}
                for linha in reversed(linhas)
            ]
    except sqlite3.Error:
        log.exception("Não foi possível carregar mensagens da sessão %s.", sessao_id)
        return []


from interface import recursos_sistema
RECURSOS_TRAVA = recursos_sistema.TRAVA
RECURSOS_CACHE = recursos_sistema.CACHE

# Consulta recursos do sistema
@app.get("/interface/recursos")
def recursos_widgets():
    return jsonify(recursos_sistema.consultar(gpu_nvidia))


DESEMPENHO_UI = {}
DESEMPENHO_TRAVA = threading.Lock()

# Guarda medicao local da interface
@app.route("/interface/desempenho",methods=["GET","POST"])
def desempenho_interface():
    with DESEMPENHO_TRAVA:
        if request.method == "POST":
            dados=request.get_json(silent=True)
            if not isinstance(dados,dict): return jsonify({"erro":"Dados inválidos"}),400
            for k in ("fps","target","tab_ms","long_tasks","longest_ms"):
                v=dados.get(k)
                if v is not None and (type(v) not in (int,float) or not 0<=v<=60000): return jsonify({"erro":"Medição inválida"}),400
            DESEMPENHO_UI.update({k:dados.get(k) for k in ("fps","target","tab_ms","long_tasks","longest_ms")})
            DESEMPENHO_UI.update(renderer=str(dados.get("renderer", ""))[:240],config_open=bool(dados.get("config_open")),medido_em=time.time())
        return jsonify(DESEMPENHO_UI)


# Informa prontidao da IA local
@app.get("/interface/ia")
def ia_local_status():
    dados=llm_local.modelos_disponiveis()
    modelo=llm_local.resolver_modelo()
    python=config.BASE_DIR/".tools"/"hermes-env"/"Scripts"/"python.exe"
    agente=python.is_file() and (config.BASE_DIR/".tools"/"hermes-agent"/"run_agent.py").is_file()
    return jsonify({"servidor":dados["conectado"],"modelo":modelo,"modelo_disponivel":modelo in dados["ids"],"hermes_instalado":agente,"url":llm_local.URL_BASE,"modelos":dados["ids"]})


# Confirma acao pessoal por voz
@app.post("/pessoal/aviso")
def aviso_celular():
    dados=json_objeto() or {}
    texto=dados.get("texto")
    if not isinstance(texto,str) or not 1<=len(texto.strip())<=250:return jsonify({"erro":"Aviso inválido"}),400
    anunciar_seguranca(texto.strip())
    return jsonify({"sucesso":True})

# Limita celular ao protocolo
@app.post("/pessoal/seguranca/ativo")
def seguranca_celular_ativa():
    ativo=(json_objeto() or {}).get("ativo")
    if type(ativo) is not bool:return jsonify({"erro":"Estado inválido"}),400
    sucesso,resultado=config.definirOpcao("SEGURANCA_ATIVA",ativo)
    if not sucesso:return jsonify({"erro":resultado}),400
    if not ativo and seguranca_stark.estado_atual().get("armado"):seguranca_stark.desarmar("celular")
    mensagem="Protocolo Torre Stark "+("ativado." if ativo else "desativado.")
    # O aplicativo Android reproduz localmente a resposta; não ecoar no PC.
    return jsonify({"mensagem":mensagem})

# Consulta pessoal sem controlar PC
@app.post("/pessoal/comando")
def comando_pessoal_celular():
    acao=(json_objeto() or {}).get("acao")
    if acao=="agenda":
        itens=memoria.listar_compromissos(limite=5)
        texto="Sua agenda. "+". ".join(str(i.get("titulo","Compromisso"))+" em "+str(i.get("inicio","")) for i in itens) if itens else "Sua agenda está vazia."
    elif acao=="notas":
        itens=memoria.listar_notas_hud()[:5]
        texto="Suas notas. "+". ".join(str(i.get("title","Nota"))+". "+str(i.get("body",""))[:150] for i in itens) if itens else "Você não tem notas salvas."
    elif acao=="whatsapp":
        from interface import pessoal_celular
        itens=pessoal_celular.listar()[:5]
        texto="Avisos do celular. "+". ".join(str(i.get("remetente","Mensagem"))+". "+str(i.get("texto",""))[:150] for i in itens) if itens else "Nenhum aviso recebido do celular."
    else:return jsonify({"erro":"Comando não permitido no celular"}),400
    texto=texto[:2000]
    anunciar_seguranca(texto)
    return jsonify({"resposta":texto})

# Interrompe geracao e toda leitura
@app.post("/assistente/parar")
def parar_assistente():
    from comandos.automacao.central_casa import cancelar as cancelar_rotinas
    cancelar_rotinas()
    voz.parar_fala()
    leitor_dia.interromper()
    quantidade = llm_local.cancelar_tudo()
    return jsonify({"sucesso": True, "canceladas": quantidade})

# Mostra controles locais seguros
@app.get("/assistente/estado")
def estado_assistente():
    from comandos import hermes_agent
    return jsonify({"lm_studio": llm_local.servidor_local_ativo(), "hermes": hermes_agent.ativo(), "parada": llm_local.versao_cancelamento()})

# Alterna somente ferramentas IA
@app.post("/assistente/ativo")
def ativar_assistente():
    from comandos import hermes_agent
    dados = json_objeto() or {}
    ativo = dados.get("ativo")
    ferramenta = dados.get("ferramenta")
    if not isinstance(ativo, bool) or ferramenta not in ("lm_studio", "hermes"):
        return jsonify({"erro": "Controle inválido"}), 400
    sucesso = llm_local.definir_servidor_local_ativo(ativo) if ferramenta == "lm_studio" else hermes_agent.definir_ativo(ativo)
    if not sucesso: return jsonify({"erro": "Não foi possível salvar"}), 500
    if not ativo:
        leitor_dia.interromper()
        voz.parar_fala()
    return estado_assistente()

# Mostra estabilidade de cada janela
@app.get("/interface/janelas")
def interface_janelas():
    from interface.janela_transparente import estado_janelas
    from interface.janelas_nativas import estado_janelas as estado_nativo
    return jsonify({"janelas": estado_janelas()+estado_nativo()})


from interface.central_casa_api import api as central_casa_api
app.register_blueprint(central_casa_api)
