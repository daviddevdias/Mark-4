import concurrent.futures

import ctypes

import logging

import math

import platform

import subprocess

import time

import config

from comandos.automacao.rotina_chegada import processo_esta_rodando

log = logging.getLogger("mark2.rotina_saida")

PROCESSOS_ROTINA_SAIDA = {
    "Discord": "Discord.exe",
    "Spotify": "Spotify.exe",
    "Google Chrome": "chrome.exe",
    "Microsoft Edge": "msedge.exe",
    "Firefox": "firefox.exe",
    "Brave": "brave.exe",
}

PROCESSOS_ENCERRAMENTO_SISTEMA = {
    "Discord": "Discord.exe",
    "WhatsApp": "WhatsApp.exe",
    "Google Chrome": "chrome.exe",
    "Microsoft Edge": "msedge.exe",
    "Firefox": "firefox.exe",
    "Brave": "brave.exe",
}

TEMPO_ESPERA_FECHAMENTO_SUAVE = 3.0

INTERVALO_VERIFICACAO_PROCESSO = 0.2



def aguardar_processo_encerrar(nome_processo, limite_segundos):
    intervalo = max(float(INTERVALO_VERIFICACAO_PROCESSO), 0.05)
    tentativas = max(1, math.ceil(max(float(limite_segundos), 0.0) / intervalo))
    for _ in range(tentativas):
        if not processo_esta_rodando(nome_processo):
            return True
        time.sleep(intervalo)
    return not processo_esta_rodando(nome_processo)



def executar_taskkill(nome_processo):
    comando = ["taskkill", "/IM", nome_processo, "/T"]
    try:
        resultado = subprocess.run(
            comando,
            capture_output=True,
            timeout=10,
            check=False,
        )
        return resultado.returncode == 0
    except (OSError, subprocess.SubprocessError) as erro:
        log.warning("Falha ao encerrar '%s': %s", nome_processo, erro)
        return False


# Fecha processo
def fechar_processo(nome_processo):
    if not isinstance(nome_processo, str) or not nome_processo.strip():
        return False
    if not processo_esta_rodando(nome_processo):
        return False

    solicitado = executar_taskkill(nome_processo)
    if not processo_esta_rodando(nome_processo):
        return True
    if not solicitado:
        return False
    return aguardar_processo_encerrar(nome_processo, TEMPO_ESPERA_FECHAMENTO_SUAVE)


# Fecha um
def fechar_um(item):
    nome_app, nome_processo = item
    try:
        sucesso = fechar_processo(nome_processo) or not processo_esta_rodando(
            nome_processo
        )
    except Exception:
        log.exception("Falha inesperada ao fechar '%s'.", nome_app)
        sucesso = not processo_esta_rodando(nome_processo)
    return nome_app, sucesso


# Fecha processos em paralelo
def fechar_processos_em_paralelo(processos):
    ativos = [
        (nome_app, nome_processo)
        for nome_app, nome_processo in processos.items()
        if processo_esta_rodando(nome_processo)
    ]
    if not ativos:
        return [], []

    fechados = []
    falhas = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(ativos)) as executor:
        for nome_app, sucesso in executor.map(fechar_um, ativos):
            (fechados if sucesso else falhas).append(nome_app)
    return fechados, falhas



def bloquear_pc():
    sistema = platform.system()
    try:
        if sistema == "Windows":
            return bool(ctypes.windll.user32.LockWorkStation())
        if sistema == "Darwin":
            subprocess.run(["pmset", "displaysleepnow"], check=False, timeout=5)
            return True
        if sistema == "Linux":
            subprocess.run(["loginctl", "lock-session"], check=False, timeout=5)
            return True
    except (OSError, AttributeError, subprocess.SubprocessError) as erro:
        log.warning("Falha ao bloquear o PC: %s", erro)
    return False



def executar_rotina_saida():
    apps_fechados, falhas = ([], [])
    if getattr(config, "FECHAR_APPS_AO_SAIR", False):
        apps_fechados, falhas = fechar_processos_em_paralelo(PROCESSOS_ROTINA_SAIDA)
    if falhas:
        log.warning("Não consegui fechar na rotina de saída: %s", ", ".join(falhas))

    return "Rotina de saída ativada."



def executar_encerramento_sistema():
    fechados, falhas = ([], [])
    if getattr(config, "FECHAR_APPS_AO_SAIR", False):
        fechados, falhas = fechar_processos_em_paralelo(PROCESSOS_ENCERRAMENTO_SISTEMA)
    if falhas:
        log.warning("Não consegui fechar ao encerrar o sistema: %s", ", ".join(falhas))

    return fechados, falhas, False
