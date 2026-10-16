"""Prepara vídeos para o painel."""
import atexit
import subprocess
import threading
from pathlib import Path
from .gravacao_eventos import GravadorEventos

class ReproducaoEventos:
    # Limita conversões e memória
    def __init__(self):
        self.trava = threading.Lock()
        self.verificados = {}
        self.estados = {}
        self.convertendo = False
        self.parada = threading.Event()
        self.processo = None

    # Confirma imagem sem repetir leitura
    def verificar(self, arquivo, ffmpeg):
        arquivo = Path(arquivo).resolve()
        try:
            dados = arquivo.stat()
        except OSError:
            return False
        chave = (str(arquivo), dados.st_size, dados.st_mtime_ns)
        with self.trava:
            if chave in self.verificados:
                return self.verificados[chave]
        valido = GravadorEventos.validar_video(arquivo, ffmpeg)
        with self.trava:
            if len(self.verificados) >= 128:
                self.verificados.pop(next(iter(self.verificados)))
            self.verificados[chave] = valido
        return valido

    # Agenda formato aceito pelo painel
    def preparar(self, arquivo, ffmpeg):
        arquivo = Path(arquivo).resolve()
        destino = arquivo.with_suffix(".webm")
        if destino.is_file() and self.verificar(destino, ffmpeg):
            return "pronto"
        chave = str(arquivo)
        with self.trava:
            if self.parada.is_set():
                return "erro"
            estado = self.estados.get(chave)
            if estado == "erro":
                return estado
            if self.convertendo:
                return "processando"
            self.convertendo = True
            if len(self.estados) >= 128:
                self.estados.pop(next(iter(self.estados)))
            self.estados[chave] = "processando"
        threading.Thread(target=self.converter, args=(arquivo, ffmpeg), daemon=True,
            name="mark2-video-painel").start()
        return "processando"

    # Converte sem ocupar a inferência
    def converter(self, arquivo, ffmpeg):
        destino = arquivo.with_suffix(".webm")
        temporario = arquivo.with_suffix(".part.webm")
        estado = "erro"
        try:
            comando = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-threads", "2", "-i", str(arquivo),
                "-map", "0:v:0", "-map", "0:a:0?", "-vf", "scale=w='min(1280,iw)':h=-2",
                "-c:v", "libvpx", "-deadline", "realtime", "-cpu-used", "8", "-threads", "2",
                "-b:v", "1600k", "-c:a", "libvorbis", "-ar", "48000", "-b:a", "48k", str(temporario)]
            with self.trava:
                if self.parada.is_set():
                    return
                self.processo = subprocess.Popen(comando, stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                processo = self.processo
            processo.wait(timeout=900)
            if processo.returncode == 0 and self.verificar(temporario, ffmpeg):
                temporario.replace(destino)
                estado = "pronto"
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            with self.trava:
                if self.processo is not None and self.processo.poll() is None:
                    self.processo.kill()
                    self.processo.wait(timeout=3)
                self.processo = None
                self.estados[str(arquivo)] = estado
                self.convertendo = False
            try:
                temporario.unlink(missing_ok=True)
            except OSError:
                pass

    # Encerra a conversão ao sair
    def parar(self):
        self.parada.set()
        with self.trava:
            processo = self.processo
        if processo is not None and processo.poll() is None:
            try:
                processo.terminate()
                processo.wait(timeout=3)
            except subprocess.TimeoutExpired:
                processo.kill()
                processo.wait(timeout=3)

reprodutor_eventos = ReproducaoEventos()
atexit.register(reprodutor_eventos.parar)
