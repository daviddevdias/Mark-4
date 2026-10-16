import ctypes
import logging
import platform
import shlex
import subprocess
import time

import config

log = logging.getLogger("mark2.pc_controle")



def falha(mensagem, *args):
    log.error(mensagem, *args)
    return ""


SISTEMA = platform.system()

ATRASO_PADRAO_SEGUNDOS = 20

ATALHOS_APPS_PADRAO = {
    "navegador": "chrome",
    "chrome": "chrome",
    "bloco de notas": "notepad",
    "calculadora": "calc",
    "explorador": "explorer",
    "spotify": "spotify",
    "discord": "discord",
    "terminal": "wt",
}



def windows():
    return SISTEMA == "Windows"


VK_VOLUME_MUDO = 0xAD
VK_VOLUME_DESCER = 0xAE
VK_VOLUME_SUBIR = 0xAF
VK_MIDIA_PROXIMA = 0xB0
VK_MIDIA_ANTERIOR = 0xB1
VK_MIDIA_PLAY_PAUSA = 0xB3

KEYEVENTF_KEYUP = 0x0002



def apertar_tecla_virtual(vk_code):
    if not windows():
        return False
    try:
        ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
        time.sleep(0.03)
        ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)
        return True
    except Exception:
        log.exception("Falha ao simular a tecla virtual 0x%X.", vk_code)
        return False


ACOES_VOLUME = {
    "subir": VK_VOLUME_SUBIR,
    "aumentar": VK_VOLUME_SUBIR,
    "descer": VK_VOLUME_DESCER,
    "abaixar": VK_VOLUME_DESCER,
    "diminuir": VK_VOLUME_DESCER,
    "mudo": VK_VOLUME_MUDO,
    "silenciar": VK_VOLUME_MUDO,
}

ACOES_MIDIA = {
    "play_pausa": VK_MIDIA_PLAY_PAUSA,
    "pausar": VK_MIDIA_PLAY_PAUSA,
    "tocar": VK_MIDIA_PLAY_PAUSA,
    "proxima": VK_MIDIA_PROXIMA,
    "próxima": VK_MIDIA_PROXIMA,
    "anterior": VK_MIDIA_ANTERIOR,
}


# Controla volume
def controlar_volume(acao):
    vk_code = ACOES_VOLUME.get(str(acao or "").strip().lower())
    if vk_code is None:
        return falha("Ação de volume desconhecida: %r.", acao)
    if not windows():
        return falha("Controle de volume só está disponível no Windows.")
    if apertar_tecla_virtual(vk_code):
        return "Ok."
    return falha("Não consegui ajustar o volume.")


# Controla midia
def controlar_midia(acao):
    vk_code = ACOES_MIDIA.get(str(acao or "").strip().lower())
    if vk_code is None:
        return falha("Ação de mídia desconhecida: %r.", acao)
    if not windows():
        return falha("Controle de mídia só está disponível no Windows.")
    if apertar_tecla_virtual(vk_code):
        return "Ok."
    return falha("Não consegui controlar a mídia.")



def bloquear_tela():
    if not windows():
        return falha("Bloquear a tela só está disponível no Windows.")
    try:
        ctypes.windll.user32.LockWorkStation()
        return "Tela bloqueada."
    except Exception:
        log.exception("Falha ao bloquear a tela.")
        return falha("Não consegui bloquear a tela.")



def desligar_pc(atraso_segundos=ATRASO_PADRAO_SEGUNDOS):
    if not windows():
        return falha("Desligar remotamente só está disponível no Windows.")
    try:
        subprocess.run(
            ["shutdown", "/s", "/t", str(max(0, int(atraso_segundos)))],
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return f'Desligando o PC em {atraso_segundos} segundos. Mande "cancelar" pra abortar.'
    except Exception:
        log.exception("Falha ao agendar o desligamento.")
        return falha("Não consegui agendar o desligamento.")



def reiniciar_pc(atraso_segundos=ATRASO_PADRAO_SEGUNDOS):
    if not windows():
        return falha("Reiniciar remotamente só está disponível no Windows.")
    try:
        subprocess.run(
            ["shutdown", "/r", "/t", str(max(0, int(atraso_segundos)))],
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return f'Reiniciando o PC em {atraso_segundos} segundos. Mande "cancelar" pra abortar.'
    except Exception:
        log.exception("Falha ao agendar o reinício.")
        return falha("Não consegui agendar o reinício.")


# Cancela desligamento
def cancelar_desligamento():
    if not windows():
        return "Nada a cancelar."
    try:
        subprocess.run(
            ["shutdown", "/a"],
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return "Desligamento/reinício cancelado."
    except subprocess.CalledProcessError:
        return falha("Não havia nenhum desligamento agendado para cancelar.")
    except Exception:
        log.exception("Falha ao cancelar o desligamento.")
        return falha("Não consegui cancelar o desligamento.")



def atalhos_apps():
    atalhos = dict(ATALHOS_APPS_PADRAO)
    extras = getattr(config, "ATALHOS_APPS", None)
    if isinstance(extras, dict):
        for nome, comando in extras.items():
            if isinstance(nome, str) and comando:
                atalhos[nome.strip().lower()] = comando
    for nome, atributo in (
        ("vs code", "CAMINHO_VSCODE"),
        ("discord", "CAMINHO_DISCORD"),
    ):
        comando = getattr(config, atributo, None)
        if isinstance(comando, str) and comando.strip():
            atalhos[nome] = comando.strip()
    return atalhos


# Lista apps
def listar_apps():
    return sorted(atalhos_apps())


# Abre app
def abrir_app(nome):
    """Abre app."""
    chave = str(nome or "").strip().lower()
    comando = atalhos_apps().get(chave)
    if comando is None:
        return False, falha(
            "App '%s' desconhecido. Disponíveis: %s.", nome, ", ".join(listar_apps())
        )
    try:
        if windows():
            subprocess.Popen(
                ["cmd", "/c", "start", "", comando],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        elif isinstance(comando, (list, tuple)):
            subprocess.Popen(list(comando))
        else:
            subprocess.Popen(shlex.split(str(comando)))
        return True, f"Abrindo {chave}."
    except Exception:
        log.exception("Falha ao abrir o app %r.", nome)
        return False, falha("Não consegui abrir %s.", chave)
