import ctypes
import json
import os
import subprocess
from weakref import WeakValueDictionary
from ctypes import wintypes
from pathlib import Path
import psutil
import config

ABRINDO = None
JANELAS = WeakValueDictionary()
from PySide6.QtCore import QTimer

# Localiza navegador para o painel
def executavel():
    from comandos.navegador_voz import navegador
    caminho = navegador.navegadorSistema()
    if caminho and Path(caminho).name.lower() in {"brave.exe", "chrome.exe", "msedge.exe", "chromium.exe"}:
        return caminho
    for base in (os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", ""), os.environ.get("LOCALAPPDATA", "")):
        for nome in ("BraveSoftware/Brave-Browser/Application/brave.exe", "Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
            p = Path(base)/nome
            if p.is_file(): return str(p)
    return None

# Seleciona apenas janelas do Jarvis
def janelas_perfil(perfil):
    if os.name != "nt": return []
    u = ctypes.windll.user32
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    u.GetClassNameW.argtypes = [wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    u.IsWindow.argtypes = [wintypes.HWND]
    ids = set()
    alvo = str(Path(perfil).resolve()).casefold()
    for p in psutil.process_iter(["pid", "name"]):
        if (p.info["name"] or "").lower() not in {"brave.exe", "chrome.exe", "msedge.exe", "chromium.exe"}: continue
        try:
            if any(a.startswith("--user-data-dir=") and a.partition("=")[2].strip('"').casefold() == alvo for a in p.cmdline()): ids.add(p.pid)
        except psutil.Error: pass
    encontrados = []
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def coletar(hwnd, _):
        pid = wintypes.DWORD(); u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        classe=ctypes.create_unicode_buffer(128);u.GetClassNameW(hwnd,classe,128)
        if pid.value in ids and classe.value=="Chrome_WidgetWin_1" and u.GetWindowTextLengthW(hwnd)>0: encontrados.append(hwnd)
        return True
    u.EnumWindows(callback(coletar), 0)
    return encontrados

class JanelaNativa:
    # Guarda janela sem criar WebEngine
    def __init__(self, dono, ident, caminho, porta):
        self.dono = dono; self.ident = ident; self.exe = caminho; self.porta = porta
        self.perfil = config.DATA_DIR/"interface_browser"
        self.arquivo = config.DATA_DIR/("janela-"+ident+".json")
        self.hwnd = None; self.pendente = False; self.fechada = False
        self.timer = QTimer(dono); self.timer.timeout.connect(self.localizar)
        self.candidatos = set(); self.tentativas = 0
        self.aberturas=0;JANELAS[ident]=self

    # Verifica propriedade antes de agir
    def valido(self):
        if self.hwnd not in janelas_perfil(self.perfil): self.hwnd = None
        return self.hwnd is not None

    # Abre ou reaproveita a mesma tela
    def show(self):
        global ABRINDO
        if getattr(self.dono,"_encerramento_iniciado",False): return
        self.fechada=False
        if self.valido():
            u=ctypes.windll.user32;u.ShowWindow.argtypes=[wintypes.HWND,ctypes.c_int];u.ShowWindow(self.hwnd,9);self.activateWindow();return
        if self.pendente: return
        if ABRINDO is not None and ABRINDO is not self:
            QTimer.singleShot(300,lambda: self.show() if not self.fechada else None);return
        ABRINDO=self
        self.candidatos=set(janelas_perfil(self.perfil));self.pendente=True;self.tentativas=0
        self.perfil.mkdir(parents=True,exist_ok=True)
        url=f"http://127.0.0.1:{self.porta}/painel?embutido=native" if self.ident=="principal" else f"http://127.0.0.1:{self.porta}/telas?embutido=native&tela={self.ident}"
        argumentos=[self.exe,"--user-data-dir="+str(self.perfil),"--app="+url,"--no-first-run","--no-default-browser-check","--autoplay-policy=no-user-gesture-required","--window-size=1280,860"]
        try:
            subprocess.Popen(argumentos,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        except OSError:
            self.pendente=False;ABRINDO=None
            raise
        self.timer.start(250)

    # Identifica janela criada pelo app
    def localizar(self):
        global ABRINDO
        if self.fechada or getattr(self.dono,"_encerramento_iniciado",False):
            self.timer.stop();self.pendente=False
            if ABRINDO is self: ABRINDO=None
            return
        novos=set(janelas_perfil(self.perfil))-self.candidatos
        self.tentativas+=1
        if novos:
            self.hwnd=next(iter(novos));self.timer.stop();self.pendente=False;ABRINDO=None
            self.aberturas+=1
            self.restaurar();self.estilizar();self.activateWindow()
        elif self.tentativas>=60: self.timer.stop();self.pendente=False;ABRINDO=None

    # Mantem moldura escura e tela fixa
    def estilizar(self):
        if not self.valido(): return
        aplicar_icone(self.hwnd,self.ident)
        valor=ctypes.c_int(1)
        try: ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(self.hwnd),20,ctypes.byref(valor),4)
        except OSError: pass
        u=ctypes.windll.user32;u.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
        if self.ident!="principal":u.SetWindowPos(self.hwnd,wintypes.HWND(-1),0,0,0,0,0x13)

    # Reusa monitor e tamanho salvos
    def restaurar(self):
        try:
            d=json.loads(self.arquivo.read_text(encoding="utf-8"));r=d.get("retangulo")
            if not r and d.get("geometria"):
                from PySide6.QtCore import QByteArray
                from PySide6.QtWidgets import QWidget
                w=QWidget();w.restoreGeometry(QByteArray.fromBase64(d["geometria"].encode()));g=w.geometry();r=[g.x(),g.y(),g.width(),g.height()];w.deleteLater()
            if r and len(r)==4 and all(type(n) is int for n in r) and r[2]>=320 and r[3]>=240:
                u=ctypes.windll.user32;u.MoveWindow.argtypes=[wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.BOOL];u.MoveWindow(self.hwnd,*r,True)
        except (OSError,ValueError,TypeError): pass

    # Guarda posicao sem apagar perfil
    def salvar(self):
        if not self.valido(): return
        u=ctypes.windll.user32;r=wintypes.RECT();u.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
        if u.GetWindowRect(self.hwnd,ctypes.byref(r)):
            self.arquivo.write_text(json.dumps({"retangulo":[r.left,r.top,r.right-r.left,r.bottom-r.top]}),encoding="utf-8")

    # Oculta sem recarregar a pagina
    def hide(self):
        if self.valido():
            self.salvar();u=ctypes.windll.user32;u.ShowWindow.argtypes=[wintypes.HWND,ctypes.c_int];u.ShowWindow(self.hwnd,0)

    # Fecha apenas esta janela Jarvis
    def close(self):
        global ABRINDO
        if ABRINDO is self: ABRINDO=None
        self.timer.stop();self.pendente=False;self.fechada=True
        if self.valido():
            self.salvar();u=ctypes.windll.user32;u.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM];u.PostMessageW(self.hwnd,0x10,0,0)
        self.hwnd=None

    # Traz a janela selecionada
    def activateWindow(self):
        if self.valido():
            u=ctypes.windll.user32;u.SetForegroundWindow.argtypes=[wintypes.HWND];u.SetForegroundWindow(self.hwnd)

    # Reutiliza foco existente
    def raise_(self): self.activateWindow()
    # Restaura uma janela minimizada
    def showNormal(self): self.show()
    # Consulta se janela esta visivel
    def isVisible(self):
        if not self.valido(): return False
        u=ctypes.windll.user32;u.IsWindowVisible.argtypes=[wintypes.HWND];return bool(u.IsWindowVisible(self.hwnd))
    # Consulta minimizacao nativa
    def isMinimized(self):
        if not self.valido(): return False
        u=ctypes.windll.user32;u.IsIconic.argtypes=[wintypes.HWND];return bool(u.IsIconic(self.hwnd))
    # Consulta foco sem mudar janelas
    def isActiveWindow(self):
        if not self.valido(): return False
        u=ctypes.windll.user32;u.GetForegroundWindow.restype=wintypes.HWND;return u.GetForegroundWindow()==self.hwnd

# Consulta hospedagem sem pintar Qt
def estado_janelas():
    return [{"nome":j.ident,"motor":"chromium-nativo","visivel":j.isVisible(),"aberturas":j.aberturas,"pendente":j.pendente} for j in list(JANELAS.values())]

# Atualiza icone sem recarregar tela
ICONES = {}
def aplicar_icone(hwnd, ident):
    nome="jarvis" if ident=="principal" else "jarvis-tela"
    u=ctypes.windll.user32
    u.LoadImageW.argtypes=[wintypes.HINSTANCE,wintypes.LPCWSTR,wintypes.UINT,ctypes.c_int,ctypes.c_int,wintypes.UINT]
    u.LoadImageW.restype=wintypes.HANDLE
    u.SendMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
    u.SendMessageW.restype=wintypes.LPARAM
    for tipo,tamanho in [(0,16),(1,32)]:
        chave=(nome,tamanho)
        if chave not in ICONES:
            ICONES[chave]=u.LoadImageW(None,str(config.BASE_DIR/"interface/static/icons"/(nome+".ico")),1,tamanho,tamanho,0x10)
        if ICONES[chave]:u.SendMessageW(hwnd,0x80,tipo,ICONES[chave])
