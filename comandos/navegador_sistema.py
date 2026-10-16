import ctypes
import os
import subprocess
import time
import webbrowser
from ctypes import wintypes
from pathlib import Path
from urllib.parse import quote_plus, urlparse
import psutil
import config


# Localiza janela do navegador real
def janela_navegador(executavel):
    if os.name != "nt" or not executavel:
        return None
    u = ctypes.windll.user32
    u.GetForegroundWindow.restype = wintypes.HWND
    u.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    nome = Path(executavel).name.casefold()

    def valido(hwnd):
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        try:
            processo = psutil.Process(pid.value)
            isolados = [
                str(config.DATA_DIR / n).casefold()
                for n in ("navegador_voz", "interface_browser")
            ]
            if any(
                "--user-data-dir" in arg and any(p in arg.casefold() for p in isolados)
                for arg in processo.cmdline()
            ):
                return False
            return (
                u.IsWindowVisible(hwnd)
                and u.GetWindowTextLengthW(hwnd) > 0
                and Path(processo.exe()).resolve() == Path(executavel).resolve()
            )
        except (psutil.Error, OSError):
            return False

    atual = u.GetForegroundWindow()
    if valido(atual):
        return atual
    encontrados = []
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def coletar(hwnd, _):
        if valido(hwnd):
            encontrados.append(hwnd)
        return True

    u.EnumWindows(callback(coletar), 0)
    return encontrados[0] if encontrados else None


# Envia atalho somente ao navegador
def atalho(executavel, teclas):
    hwnd = janela_navegador(executavel)
    if not hwnd:
        return False
    u = ctypes.windll.user32
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.ShowWindow(hwnd, 9)
    u.SetForegroundWindow(hwnd)
    time.sleep(0.08)
    if u.GetForegroundWindow() != hwnd:
        return False
    pressionadas = []
    try:
        for tecla in teclas:
            u.keybd_event(tecla, 0, 0, 0)
            pressionadas.append(tecla)
        return True
    finally:
        for tecla in reversed(pressionadas):
            u.keybd_event(tecla, 0, 2, 0)


# Abre site na sessao habitual
def abrir_url(url):
    return bool(webbrowser.open(url, new=2))


def executar(acao, termo, executavel):
    if acao in {"pesquisar", "youtube", "video", "abrir"}:
        texto = str(termo or "").strip()
        if not texto:
            return "Diga o que devo pesquisar."
        if acao == "abrir":
            parsed = urlparse(texto)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                return "Informe um endereço de site iniciado por https."
            url = parsed.geturl()
        else:
            url = (
                "https://www.google.com/search?q="
                if acao == "pesquisar"
                else "https://www.youtube.com/results?search_query="
            ) + quote_plus(texto)
        if not abrir_url(url):
            return "Não consegui abrir o navegador padrão do Windows."
        return (
            "Site aberto no seu navegador padrão."
            if acao == "abrir"
            else "Resultados para " + texto + " abertos no seu navegador."
        )
    if acao == "iniciar":
        hwnd = janela_navegador(executavel)
        if hwnd:
            u = ctypes.windll.user32
            u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            u.SetForegroundWindow.argtypes = [wintypes.HWND]
            u.ShowWindow(hwnd, 9)
            u.SetForegroundWindow(hwnd)
            return "Seu navegador está aberto."
        if not executavel:
            return "Não encontrei o navegador padrão do Windows."
        subprocess.Popen(
            [executavel], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        return "Navegador padrão aberto com seu perfil habitual."
    if acao == "listar":
        return "Estou usando seu navegador habitual. A listagem detalhada de abas exige uma extensão; você pode trocar por número ou dizer próxima aba."
    comandos = {
        "nova": ([17, 84], "Nova aba aberta."),
        "fechar": ([17, 87], "Aba fechada."),
        "encerrar": ([18, 115], "Janela do navegador fechada."),
        "proxima": ([17, 9], "Próxima aba selecionada."),
        "anterior": ([17, 16, 9], "Aba anterior selecionada."),
        "voltar": ([18, 37], "Voltei uma página."),
        "avancar": ([18, 39], "Avancei uma página."),
        "atualizar": ([17, 82], "Página atualizada."),
        "parar": ([27], "Carregamento interrompido."),
    }
    if acao == "selecionar":
        try:
            numero = int(termo)
        except (ValueError, TypeError):
            return "Diga um número de aba entre 1 e 9."
        if not 1 <= numero <= 9:
            return "Use abas de 1 a 8; 9 seleciona a última."
        comandos[acao] = (
            [17, 48 + numero],
            (
                "Última aba selecionada."
                if numero == 9
                else "Aba " + str(numero) + " selecionada."
            ),
        )
    if acao not in comandos:
        return "Não reconheci essa ação de navegação."
    teclas, mensagem = comandos[acao]
    return (
        mensagem
        if atalho(executavel, teclas)
        else "Não consegui focar seu navegador. Abra a janela e tente novamente."
    )
