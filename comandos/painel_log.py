import hashlib
import logging
import threading
import time
from collections import deque
from datetime import datetime

MAX_ENTRADAS = 300
JANELA_REPETIDO_S = 60  

TRAVA = threading.Lock()
ENTRADAS = deque(maxlen=MAX_ENTRADAS)
ULTIMAS = {}  
contador = 0



def registrar(origem, mensagem, nivel="erro"):
    global contador
    origem = str(origem or "sistema").removeprefix("mark2.")
    mensagem = " ".join(str(mensagem or "").split())[:500]
    if not mensagem:
        return
    chave = hashlib.md5(f"{origem}|{mensagem}".encode("utf-8")).hexdigest()[:12]
    agora = time.monotonic()
    with TRAVA:
        contador += 1
        anterior = ULTIMAS.get(chave)
        repeticoes = 1
        if anterior is not None and agora - anterior["_t"] <= JANELA_REPETIDO_S:
            repeticoes = anterior["repeticoes"] + 1
            try:
                ENTRADAS.remove(anterior)
            except ValueError:
                pass
        entrada = {
            "id": contador,
            "chave": chave,
            "hora": datetime.now().strftime("%H:%M:%S"),
            "nivel": nivel,
            "origem": origem,
            "mensagem": mensagem,
            "repeticoes": repeticoes,
            "_t": agora,
        }
        ENTRADAS.append(entrada)
        ULTIMAS[chave] = entrada
        if len(ULTIMAS) > 4 * MAX_ENTRADAS:
            vivas = {e["chave"] for e in ENTRADAS}
            for k in [k for k in ULTIMAS if k not in vivas]:
                del ULTIMAS[k]



def listar(desde=0):
    with TRAVA:
        return [
            {k: v for k, v in e.items() if not k.startswith("_")}
            for e in ENTRADAS
            if e["id"] > desde
        ]



def limpar():
    with TRAVA:
        ENTRADAS.clear()
        ULTIMAS.clear()


class PainelHandler(logging.Handler):

    def emit(self, record):
        try:
            texto = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                erro = record.exc_info[1]
                texto += f" [{type(erro).__name__}: {erro}]"
            registrar(
                record.name,
                texto,
                "erro"
                if record.levelno >= logging.ERROR
                else "aviso"
                if record.levelno >= logging.WARNING
                else "info",
            )
        except Exception:
            self.handleError(record)


instalado = False



def instalar(nivel=logging.INFO):
    global instalado
    if instalado:
        return
    handler = PainelHandler(level=nivel)
    raiz = logging.getLogger("mark2")
    if raiz.level == logging.NOTSET or raiz.level > nivel:
        raiz.setLevel(nivel)
    raiz.addHandler(handler)
    instalado = True


instalar()
