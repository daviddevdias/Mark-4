import logging

import subprocess

import webbrowser

import psutil

import config

log = logging.getLogger("mark2.rotina_chegada")

APPS_ROTINA_CHEGADA = {
    "VS Code": {
        "processo": "Code.exe",
        "comando": getattr(config, "CAMINHO_VSCODE", None),
    },
    "Discord": {
        "processo": "Discord.exe",
        "comando": getattr(config, "CAMINHO_DISCORD", None),
    },

}


def processo_esta_rodando(nome_processo):
    if not isinstance(nome_processo, str) or not nome_processo.strip():
        return False

    nome_procurado = nome_processo.casefold()
    try:
        processos = psutil.process_iter(["name"])
        for processo in processos:
            try:
                nome_atual = processo.info.get("name")
            except (psutil.Error, KeyError, TypeError):
                continue
            if nome_atual and str(nome_atual).casefold() == nome_procurado:
                return True
    except psutil.Error as erro:
        log.warning("Falha ao consultar os processos em execução: %s", erro)
    return False


def navegador_esta_aberto():
    navegadores = ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe")
    return any(processo_esta_rodando(nome) for nome in navegadores)

# Abre playlist spotify
def abrir_playlist_spotify():
    playlist = getattr(config, "SPOTIFY_PLAYLIST_CHEGADA", "")
    if not isinstance(playlist, str) or not playlist.strip():
        return False
    try:
        return bool(webbrowser.open(playlist.strip()))
    except (OSError, webbrowser.Error) as erro:
        log.warning("Falha ao abrir a playlist do Spotify: %s", erro)
        return False

# Abre YouTube chegada
def abrir_youtube_chegada():
    link = getattr(config, "LINK_YOUTUBE_CHEGADA", "")
    if not isinstance(link, str) or not link.strip():
        return False
    try:
        return bool(webbrowser.open(link.strip()))
    except (OSError, webbrowser.Error) as erro:
        log.warning("Falha ao abrir o link do YouTube: %s", erro)
        return False


def comando_valido(comando):
    if isinstance(comando, str):
        return bool(comando.strip())
    if isinstance(comando, (list, tuple)):
        return bool(comando) and all(isinstance(item, str) and item for item in comando)
    return False


def executar_rotina_chegada():
    acoes_realizadas = []
    falhas = []

    if getattr(config, "ABRIR_APPS_AO_CHEGAR", False):
        for nome_app, info in APPS_ROTINA_CHEGADA.items():
            nome_processo = info.get("processo")
            comando = info.get("comando")
            if processo_esta_rodando(nome_processo):
                continue
            if not comando_valido(comando):
                log.warning("Comando de abertura de '%s' não configurado.", nome_app)
                falhas.append(nome_app)
                continue
            try:
                subprocess.Popen(comando)
                acoes_realizadas.append(nome_app)
            except (OSError, ValueError, subprocess.SubprocessError) as erro:
                log.warning("Falha ao abrir '%s': %s", nome_app, erro)
                falhas.append(nome_app)

    if getattr(config, "MUSICA_CHEGADA_ATIVA", False):
        playlist_configurada = bool(
            str(getattr(config, "SPOTIFY_PLAYLIST_CHEGADA", "") or "").strip()
        )
        youtube_configurado = bool(
            str(getattr(config, "LINK_YOUTUBE_CHEGADA", "") or "").strip()
        )
        if abrir_playlist_spotify():
            if "Spotify" not in acoes_realizadas:
                acoes_realizadas.append("Spotify")
            if "Spotify" in falhas:
                falhas.remove("Spotify")
        elif playlist_configurada:
            falhas.append("playlist do Spotify")
        if abrir_youtube_chegada():
            acoes_realizadas.append("YouTube")
        elif youtube_configurado:
            falhas.append("YouTube")

    if falhas:
        log.error("Rotina de chegada: não consegui abrir: %s.", ", ".join(falhas))
    if acoes_realizadas:
        return "Chegada registrada, senhor. Ambiente pronto."
    if falhas:
        return ""
    return "Chegada registrada, senhor."
