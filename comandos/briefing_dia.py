"""Coordena o resumo falado do dia."""

import threading
import textwrap
import queue
import uuid
from .linguagem import chave
from . import wake_word

PEDIDOS = {
    "bom dia",
    "boa tarde",
    "boa noite",
    "resumo do dia",
    "resumo da manha",
    "meu resumo",
    "briefing",
    "briefing do dia",
}


# Reconhece pedido completo do resumo
def pedido(texto):
    normal = chave(texto)
    nomes = {chave(nome) for nome in wake_word.FORTES} | {"javes"}
    if normal in PEDIDOS:
        return True
    return any(
        normal == f"{saudacao} {nome}"
        for saudacao in PEDIDOS
        for nome in nomes
    )



class LeitorDia:
    # Inicializa controle da leitura
    def __init__(self):
        self.trava = threading.Lock()
        self.ativo = None

    # Valida e inicia leitura local
    def iniciar(self, itens, publicar):
        from interface import voz

        if not isinstance(itens, list) or not 1 <= len(itens) <= 8:
            raise ValueError("Resumo inválido")
        for item in itens:
            if (
                not isinstance(item, dict)
                or item.get("key")
                not in {"weather", "agenda", "email", "news", "news_tech", "news_ia", "news_politics", "notes"}
                or not isinstance(item.get("texto"), str)
                or not 1 <= len(item["texto"].strip()) <= 3000
            ):
                raise ValueError("Parte do resumo inválida")
        if not voz.VOZ_ATIVA:
            raise RuntimeError("A voz do Jarvis está desativada")
        atual = {"id": uuid.uuid4().hex, "parada": threading.Event(), "falando": False}
        with self.trava:
            if self.ativo is not None:
                raise RuntimeError("Já há um resumo sendo lido")
            self.ativo = atual
        threading.Thread(
            target=self.executar,
            args=(atual, [dict(i) for i in itens], publicar),
            daemon=True,
            name="mark2-resumo-dia",
        ).start()
        return atual["id"]

    # Sincroniza cartões com a fala
    def executar(self, atual, itens, publicar):
        from interface import voz
        falhou = False
        preparados=queue.Queue(maxsize=2)
        partes=[textwrap.wrap(item["texto"],width=170,break_long_words=False,break_on_hyphens=False) for item in itens]
        encerrado=threading.Event()
        # Antecipa os proximos audios
        def preparar():
            for grupo in partes:
                for texto in grupo:
                    if encerrado.is_set() or atual["parada"].is_set(): return
                    try: audio=voz.sintetizar_bytes(texto)
                    except Exception: audio=None
                    while not encerrado.is_set() and not atual["parada"].is_set():
                        try: preparados.put(audio,timeout=.2);break
                        except queue.Full: continue
                    else: return
        threading.Thread(target=preparar,daemon=True,name="mark2-prefetch-voz").start()
        try:
            for indice,item in enumerate(itens):
                while not atual["parada"].is_set():
                    if voz.TRAVA_FALA.acquire(timeout=.2): break
                else: break
                try:
                    if atual["parada"].is_set(): break
                    with self.trava: atual["falando"] = True
                    publicou=False
                    sucesso = True
                    for parte in partes[indice]:
                        while not atual["parada"].is_set():
                            try: audio=preparados.get(timeout=.2);break
                            except queue.Empty: continue
                        else: sucesso=False;break
                        if not publicou:
                            publicar({"type":"daily_briefing","id":atual["id"],"key":item["key"],"state":"reading","texto":item["texto"]})
                            publicou=True
                        try:
                            tocou=bool(audio) and voz.falar(parte,deve_parar=atual["parada"].is_set,audio_preparado=audio,manter_reproducao=True)
                        except Exception:
                            tocou=False
                        if not tocou: sucesso=False
                    with self.trava: atual["falando"] = False
                    if not sucesso:
                        falhou = not atual["parada"].is_set()
                        publicar({"type":"daily_briefing","id":atual["id"],"key":item["key"],"state":"unavailable"})
                        if atual["parada"].is_set(): break
                finally:
                    voz.EM_REPRODUCAO.clear()
                    voz.TRAVA_FALA.release()
        except Exception:
            falhou = True
        finally:
            encerrado.set()
            with self.trava:
                atual["falando"] = False
                if self.ativo is atual: self.ativo = None
            publicar({"type":"daily_briefing","id":atual["id"],"state":"done","cancelled":atual["parada"].is_set(),"failed":falhou})

    # Para somente a própria leitura
    def parar(self, identificador):
        from interface import voz
        with self.trava:
            atual = self.ativo
            if atual is None or atual["id"] != identificador: return False
            atual["parada"].set()
            if atual["falando"]: voz.parar_fala()
        return True


    # Cancela resumo por alerta urgente
    def interromper(self):
        with self.trava:
            ident = self.ativo["id"] if self.ativo else None
        return self.parar(ident) if ident else False

leitor_dia = LeitorDia()
