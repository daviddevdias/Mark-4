import logging
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import psutil
import config

log = logging.getLogger("mark2.video_local")

PROCESSO_GO2RTC = None
FALHAS_VIDEO = 0
PARAR_VIDEO = threading.Event()
TRAVA_VIDEO = threading.RLock()




# Localiza go2rtc
def achar_go2rtc():
    candidatos = []
    configurado = getattr(config, "GO2RTC_EXE", "")
    if configurado:
        candidatos.append(Path(str(configurado)))
    candidatos.append(config.BASE_DIR / "go2rtc" / "go2rtc.exe")
    candidatos.append(config.BASE_DIR / "go2rtc.exe")
    candidatos.append(Path(r"C:\go2rtc\go2rtc.exe"))
    for caminho in candidatos:
        if caminho.is_file():
            return caminho
    return None





def go2rtc_rodando():
    try:
        for processo in psutil.process_iter(["name"]):
            nome = processo.info.get("name") or ""
            if nome.lower() == "go2rtc.exe":
                return True
    except psutil.Error:
        pass
    return False




# Espera go2rtc
def esperar_go2rtc(limite=10.0):
    base = str(getattr(config, "GO2RTC_URL", "http://127.0.0.1:1984")).rstrip("/")
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        try:
            with urllib.request.urlopen(f"{base}/api/streams", timeout=2):
                return True
        except Exception:
            time.sleep(0.5)
    return False




# Inicia go2rtc
def iniciar_go2rtc():
    global PROCESSO_GO2RTC

    if not getattr(config, "GO2RTC_AUTOSTART", True):
        return False

    if go2rtc_rodando():
        log.info("go2rtc já está rodando.")
        return True

    exe = achar_go2rtc()
    if exe is None:
        log.warning(
            "go2rtc.exe não encontrado. Coloque na pasta do projeto (ao lado do "
            "main.py), em C:\\go2rtc, ou defina GO2RTC_EXE no config."
        )
        return False

    if not (exe.parent / "go2rtc.yaml").is_file():
        log.warning("go2rtc.yaml não encontrado em %s.", exe.parent)

    try:
        PROCESSO_GO2RTC = subprocess.Popen(
            [str(exe)],
            cwd=str(exe.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        log.exception("Não consegui abrir o go2rtc.")
        return False

    if not esperar_go2rtc():
        log.error("O go2rtc abriu mas a API não respondeu. Confira o go2rtc.yaml.")
        return False

    log.info("go2rtc iniciado (%s).", exe)
    return True




# Recupera servico de video local
def manter_go2rtc():
    global FALHAS_VIDEO
    FALHAS_VIDEO=0
    while not PARAR_VIDEO.wait(5):
        try:
            recuperar_video()
        except (OSError,subprocess.SubprocessError):
            log.exception("Falha ao recuperar servidor de vídeo; nova tentativa em 5 segundos.")



def recuperar_video():
    global FALHAS_VIDEO
    with TRAVA_VIDEO:
        if PARAR_VIDEO.is_set(): return
        if not go2rtc_rodando():
            iniciar_go2rtc();FALHAS_VIDEO=0;return
        if esperar_go2rtc(limite=1): FALHAS_VIDEO=0;return
        FALHAS_VIDEO+=1
        if FALHAS_VIDEO>=3 and PROCESSO_GO2RTC is not None and PROCESSO_GO2RTC.poll() is None:
            log.warning("Servidor de vídeo sem resposta; recuperando processo do Jarvis.")
            PROCESSO_GO2RTC.terminate()
            try: PROCESSO_GO2RTC.wait(timeout=2)
            except subprocess.TimeoutExpired: PROCESSO_GO2RTC.kill();PROCESSO_GO2RTC.wait(timeout=2)
            iniciar_go2rtc();FALHAS_VIDEO=0

# Para go2rtc
def parar_go2rtc():
    PARAR_VIDEO.set()
    with TRAVA_VIDEO:
        if PROCESSO_GO2RTC is not None and PROCESSO_GO2RTC.poll() is None:
            PROCESSO_GO2RTC.terminate()
            try:
                PROCESSO_GO2RTC.wait(timeout=2)
            except subprocess.TimeoutExpired:
                PROCESSO_GO2RTC.kill()
                PROCESSO_GO2RTC.wait(timeout=2)




def iniciar():
    PARAR_VIDEO.clear()
    iniciar_go2rtc()
    if getattr(config,"GO2RTC_AUTOSTART",True):
        threading.Thread(target=manter_go2rtc,daemon=True,name="jarvis-video-recovery").start()
