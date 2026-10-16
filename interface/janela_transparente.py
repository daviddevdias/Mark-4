import config
import logging
import threading
import time
import uuid

from PySide6.QtCore import Qt, QEvent, QObject
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QSizeGrip


class BarraJanela(QWidget):
    # Mantem controles da janela
    def __init__(self, janela):
        super().__init__(janela)
        self.janela = janela
        self.setFixedHeight(30)
        self.setStyleSheet("BarraJanela{background:rgba(23,33,43,245)} QLabel{color:#c9dcea;background:transparent;font-size:11px} QPushButton{color:#d5e6ed;background:transparent;border:0;border-radius:0} QPushButton:hover{background:#344959}")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        titulo = QLabel(janela.windowTitle(), self)
        titulo.setAttribute(Qt.WA_TransparentForMouseEvents)
        layout.addWidget(titulo)
        layout.addStretch()
        for nome, rotulo, acao in (("Minimizar", "−", janela.showMinimized), ("Maximizar ou restaurar", "□", self.alternar), ("Fechar", "×", janela.close)):
            botao = QPushButton(rotulo, self)
            botao.setAccessibleName(nome)
            botao.setToolTip(nome)
            botao.setFixedSize(42, 30)
            botao.clicked.connect(acao)
            layout.addWidget(botao)

    # Alterna tamanho sem outra janela
    def alternar(self):
        self.janela.showNormal() if self.janela.isMaximized() else self.janela.showMaximized()

    # Move pelo cabecalho nativo
    def mousePressEvent(self, evento):
        if evento.button() == Qt.LeftButton and self.janela.windowHandle():
            self.janela.windowHandle().startSystemMove()
        super().mousePressEvent(evento)

    # Maximiza com duplo clique
    def mouseDoubleClickEvent(self, evento):
        if evento.button() == Qt.LeftButton: self.alternar()
        super().mouseDoubleClickEvent(evento)


class AjusteCanto(QObject):
    # Guarda controle de tamanho
    def __init__(self, janela):
        super().__init__(janela)
        self.janela = janela
        self.canto = QSizeGrip(janela)
        self.canto.setFixedSize(16, 16)
        janela.installEventFilter(self)

    # Ajusta canto sem redesenhar HUD
    def eventFilter(self, objeto, evento):
        if evento.type() in (QEvent.Resize, QEvent.Show, QEvent.WindowStateChange):
            self.canto.move(self.janela.width()-16, self.janela.height()-16)
            self.canto.setVisible(not self.janela.isMaximized())
            self.canto.raise_()
        return False


# Compoe vidro mantendo texto opaco
def preparar_janela(janela, web):
    janela.setWindowFlag(Qt.FramelessWindowHint, True)
    janela.setAttribute(Qt.WA_TranslucentBackground, False)
    janela.setAutoFillBackground(True)
    janela.setStyleSheet("QMainWindow{background:#0c1016}")
    janela.setWindowOpacity(.90 if config.obter_bool("interface_transparente", False) else 1.0)
    web.setAttribute(Qt.WA_TranslucentBackground, False)
    web.setAutoFillBackground(True)
    web.setStyleSheet("background:#0c1016")
    web.page().setBackgroundColor(QColor("#0c1016"))
    janela.setMenuWidget(BarraJanela(janela))
    janela.canto_transparente = AjusteCanto(janela)
    acompanhar_janela(janela, web)


ESTADOS = {}
TRAVA_ESTADOS = threading.Lock()
log = logging.getLogger("mark2.interface")

# Consulta sem tocar em widgets Qt
def estado_janelas():
    with TRAVA_ESTADOS: return [dict(v) for v in ESTADOS.values()]

# Registra cargas e falhas reais
def acompanhar_janela(janela, web):
    chave = uuid.uuid4().hex
    with TRAVA_ESTADOS:
        ESTADOS[chave] = {"nome": janela.windowTitle(), "cargas": 0, "falhas": 0, "opacidade": janela.windowOpacity(), "ultima_carga": None}

    # Conta navegacoes completas
    def carregando():
        with TRAVA_ESTADOS:
            estado = ESTADOS.get(chave)
            if not estado: return
            estado["cargas"] += 1
            estado["ultima_carga"] = time.time()
            numero = estado["cargas"]
        log.info("Janela %s: carregamento %d", janela.windowTitle(), numero)

    # Registra queda do renderizador
    def falhou(status, codigo):
        with TRAVA_ESTADOS:
            if chave in ESTADOS: ESTADOS[chave]["falhas"] += 1
        log.error("Renderizador %s: %s, codigo %s", janela.windowTitle(), status, codigo)

    # Retira estado ao fechar Qt
    def remover(*_):
        with TRAVA_ESTADOS: ESTADOS.pop(chave, None)

    web.loadStarted.connect(carregando)
    web.page().renderProcessTerminated.connect(falhou)
    janela.destroyed.connect(remover)
