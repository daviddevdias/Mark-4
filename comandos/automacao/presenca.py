import ipaddress
import json
import logging
import platform
import subprocess
import threading
import time
from datetime import datetime

import config
from comandos import https_local

log = logging.getLogger("mark2.presenca")

TRAVA = threading.Lock()
THREAD = None
PARAR = threading.Event()
ESTADO = {
    "ativo": False,
    "estado": "desconhecido",
    "ultima_vista": None,
    "ultima_chegada": None,
}


def ip_valido(texto):
    try:
        return str(ipaddress.ip_address((texto or "").strip()))
    except ValueError:
        return None


def sem_janela():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def responde_ping(ip):
    alvo = ip_valido(ip)
    if not alvo:
        return False
    if platform.system() == "Windows":
        comando = ["ping", "-n", "1", "-w", "1500", alvo]
    else:
        comando = ["ping", "-c", "1", "-W", "2", alvo]
    try:
        saida = subprocess.run(
            comando,
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
            creationflags=sem_janela(),
        )
    except (OSError, subprocess.SubprocessError):
        return False

    return saida.returncode == 0 and "ttl=" in (saida.stdout or "").lower()


def tailscale_na_lan(alvo):
    alvo = (alvo or "").strip().lower()
    tailscale = https_local.caminho_tailscale()
    if not alvo or not tailscale:
        return False
    try:
        saida = subprocess.run(
            [tailscale, "status", "--json"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
            creationflags=sem_janela(),
        )
        peers = (json.loads(saida.stdout).get("Peer") or {}).values()
    except Exception:
        log.debug("Falha ao consultar o status do Tailscale.", exc_info=True)
        return False

    for peer in peers:
        nomes = {
            str(peer.get("HostName") or "").lower(),
            str(peer.get("DNSName") or "").rstrip(".").lower(),
            *[str(ip).lower() for ip in peer.get("TailscaleIPs") or []],
        }
        if alvo == "auto":
            if str(peer.get("OS") or "").lower() != "android":
                continue
        elif alvo not in nomes and not any(n.startswith(alvo + ".") for n in nomes):
            continue
        if not peer.get("Online"):
            if alvo == "auto":
                continue
            return False
        endereco = str(peer.get("CurAddr") or "").rsplit(":", 1)[0].strip("[]")
        try:
            if ipaddress.ip_address(endereco).is_private:
                return True
        except ValueError:
            pass
        if alvo != "auto":
            return False
    return False


def celular_em_casa():
    ip = getattr(config, "CELULAR_IP_LOCAL", "")
    ts = getattr(config, "CELULAR_TAILSCALE", "")
    if ip and responde_ping(ip):
        return True
    return bool(ts) and tailscale_na_lan(ts)


# Consulta estado atual
def estado_atual():
    with TRAVA:
        return dict(ESTADO)


def atualizar(**campos):
    with TRAVA:
        ESTADO.update(campos)


# Gera data no formato ISO
def agora_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


# Mantém o serviço em execução
def laco(callback):
    intervalo = float(config.PRESENCA_INTERVALO_S)
    ausencia = float(config.PRESENCA_AUSENCIA_S)
    cooldown = float(config.PRESENCA_COOLDOWN_S)

    inicio = time.monotonic()
    ultima_vista = inicio
    ultimo_disparo = None
    estado = "desconhecido"

    while not PARAR.wait(intervalo):
        try:
            visto = celular_em_casa()
        except Exception:
            log.exception("Falha inesperada ao checar a presença do celular.")
            continue
        agora = time.monotonic()

        if visto:
            ultima_vista = agora
            atualizar(ultima_vista=agora_iso())
            if estado == "ausente" and (
                ultimo_disparo is None or agora - ultimo_disparo >= cooldown
            ):
                log.info("Celular detectado em casa: acionando rotina de chegada.")
                ultimo_disparo = agora
                try:
                    callback("presenca-wifi")
                except Exception:
                    log.exception("Falha ao acionar a rotina de chegada.")
                atualizar(ultima_chegada=agora_iso())
            estado = "presente"
        elif estado != "ausente" and agora - ultima_vista >= ausencia:
            estado = "ausente"
            log.info("Celular sem sinal há %.0f s: marcado como ausente.", ausencia)
        atualizar(estado=estado)


def iniciar(callback):
    global THREAD
    if not getattr(config, "PRESENCA_ATIVA", True):
        log.info("Detecção de presença desativada em config.")
        return None
    if not (
        getattr(config, "CELULAR_IP_LOCAL", "")
        or getattr(config, "CELULAR_TAILSCALE", "")
    ):
        log.info(
            "Detecção de presença inativa: defina celular_ip_local e/ou "
            "celular_tailscale nas configurações locais."
        )
        return None
    if getattr(config, "CELULAR_IP_LOCAL", "") and not ip_valido(
        config.CELULAR_IP_LOCAL
    ):
        log.error("celular_ip_local inválido: %r", config.CELULAR_IP_LOCAL)
        return None

    with TRAVA:
        if THREAD is not None and THREAD.is_alive():
            return THREAD
        PARAR.clear()
        THREAD = threading.Thread(
            target=laco, args=(callback,), daemon=True, name="mark2-presenca"
        )
        ESTADO["ativo"] = True
        THREAD.start()
    log.info("Detecção de presença ativa.")
    return THREAD


def parar():
    PARAR.set()
    atualizar(ativo=False)
