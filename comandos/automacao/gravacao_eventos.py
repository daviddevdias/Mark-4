"""Grava buffer e recortes de eventos."""

import csv
import json
import logging
import math
import re
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

log = logging.getLogger("mark2.gravacao")


class GravadorEventos:
    # Inicializa o buffer no disco
    def __init__(self, pasta, ffmpeg, url, filtros="", antes=60, segmento=4):
        self.pasta = Path(pasta).resolve()
        self.buffer = self.pasta / "buffer"
        self.buffer.mkdir(parents=True, exist_ok=True)
        self.ffmpeg, self.url, self.filtros = ffmpeg, url, filtros
        self.antes, self.segmento = antes, segmento
        self.trava = threading.RLock()
        self.parada = threading.Event()
        self.segmentos = {}
        self.eventos = {}
        self.ativo = None
        self.presente_desde = None
        self.ultima_presenca = None
        self.processo = None
        self.fila = queue.Queue(maxsize=2)
        self.erro = None
        self.ultimo_diario = 0
        self.ultimo_espaco = 0
        self.pasta_ativa = None
        self.inicio_captura = 0
        self.ultimo_segmento = 0
        self.carregar()

    # Valida instantes do índice salvo
    @staticmethod
    def instante(valor):
        if type(valor) not in (int, float) or not math.isfinite(valor) or valor < 0:
            raise ValueError("Instante inválido")
        return float(valor)

    # Recupera apenas registros válidos
    def carregar(self):
        try:
            dados = json.loads(
                (self.buffer / "estado.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return
        if not isinstance(dados, dict):
            return
        tempos_validos = dados.get("versao_tempos") == 2
        segmentos = dados.get("segmentos", []) if tempos_validos else []
        eventos = dados.get("eventos", [])
        for item in segmentos if isinstance(segmentos, list) else []:
            try:
                if not isinstance(item, dict) or not isinstance(
                    item.get("arquivo"), str
                ):
                    continue
                caminho = (self.buffer / item["arquivo"]).resolve()
                inicio, fim = self.instante(item["inicio"]), self.instante(item["fim"])
                if (
                    inicio > fim
                    or not caminho.is_relative_to(self.buffer)
                    or caminho.suffix != ".ts"
                    or not caminho.is_file()
                ):
                    continue
                self.segmentos[str(caminho)] = {
                    "arquivo": str(caminho.relative_to(self.buffer)),
                    "inicio": inicio,
                    "fim": fim,
                }
            except (OSError, ValueError, KeyError, TypeError):
                continue
        for item in eventos if isinstance(eventos, list) else []:
            try:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("id"), str)
                    or not re.fullmatch(r"[a-f0-9]{32}", item["id"])
                ):
                    continue
                arquivos = item.get("arquivos")
                if (
                    not isinstance(arquivos, list)
                    or not arquivos
                    or not all(
                        isinstance(n, str)
                        and re.fullmatch(r"(?:pessoa|linha)_\d{8}_\d{6}_\d+\.mp4", n)
                        for n in arquivos
                    )
                ):
                    continue
                item = dict(item)
                for chave in ("inicio", "deteccao", "ultima"):
                    item[chave] = self.instante(item[chave])
                if not item["inicio"] <= item["deteccao"] <= item["ultima"]:
                    continue
                if item["estado"] not in (
                    "gravando",
                    "aguardando",
                    "processando",
                    "pronto",
                    "erro",
                ):
                    continue
                if item["estado"] in ("gravando", "aguardando", "processando"):
                    item["inicio"] = max(item["inicio"], item["deteccao"] - self.antes)
                if not tempos_validos and item["estado"] in (
                    "gravando",
                    "aguardando",
                    "processando",
                ):
                    item["fim"] = item["ultima"]
                    item["estado"] = "erro"
                if item["estado"] in ("gravando", "processando"):
                    item["fim"] = item["ultima"]
                    item["estado"] = "aguardando"
                item["fim"] = self.instante(item["fim"])
                if item["fim"] < item["ultima"]:
                    continue
                pessoas = item.get("pessoas", 1)
                if type(pessoas) is not int or not 1 <= pessoas <= 50:
                    continue
                item["pessoas"] = pessoas
                self.eventos[item["id"]] = item
            except (ValueError, KeyError, TypeError):
                continue

    # Persiste sem interromper captura
    def salvar(self):
        dados = {
            "versao_tempos": 2,
            "segmentos": list(self.segmentos.values()),
            "eventos": list(self.eventos.values()),
        }
        temporario = self.buffer / "estado.tmp"
        try:
            temporario.write_text(json.dumps(dados, allow_nan=False), encoding="utf-8")
            temporario.replace(self.buffer / "estado.json")
            if self.erro == "Falha ao salvar índice":
                self.erro = None
            return True
        except OSError:
            self.erro = "Falha ao salvar índice"
            log.warning("Não foi possível persistir o índice da câmera")
            return False
        finally:
            self.ultimo_diario = time.time()

    # Inicia gravação sem pausas
    def iniciar(self):
        self.worker = threading.Thread(
            target=self.laco, daemon=True, name="mark2-buffer-camera"
        )
        self.exportador = threading.Thread(
            target=self.exportar_fila, daemon=True, name="mark2-recortes-camera"
        )
        self.worker.start()
        self.exportador.start()
        return self

    # Guarda a última presença real
    def presenca(self, quantidade, agora=None):
        agora = time.time() if agora is None else agora
        with self.trava:
            if quantidade:
                if self.presente_desde is None:
                    self.presente_desde = agora
                self.ultima_presenca = agora
                if self.ativo:
                    self.eventos[self.ativo]["ultima"] = agora
                    item = self.eventos[self.ativo]
                    item["pessoas"] = max(
                        item.get("pessoas", 1), min(50, int(quantidade))
                    )
            elif self.ultima_presenca is not None and agora - self.ultima_presenca >= 2:
                self.fechar_presenca()

    # Fecha recorte na última presença
    def fechar_presenca(self):
        if self.ativo:
            item = self.eventos[self.ativo]
            item["fim"] = item["ultima"]
            item["estado"] = "aguardando"
            self.ativo = None
            self.salvar()
        self.presente_desde = self.ultima_presenca = None

    # Associa a foto ao vídeo futuro
    def registrar(self, foto, agora=None, quantidade=1):
        agora = time.time() if agora is None else agora
        foto = Path(foto)
        if not re.fullmatch(r"(?:pessoa|linha)_\d{8}_\d{6}_\d+\.jpg", foto.name):
            raise ValueError("Nome da foto inválido")
        nome = foto.with_suffix(".mp4").name
        with self.trava:
            if self.ativo is None:
                identificador = uuid.uuid4().hex
                deteccao = self.presente_desde or agora
                self.eventos[identificador] = {
                    "id": identificador,
                    "inicio": deteccao - self.antes,
                    "deteccao": deteccao,
                    "ultima": self.ultima_presenca or agora,
                    "fim": None,
                    "arquivos": [],
                    "estado": "gravando",
                    "pessoas": max(1, min(50, int(quantidade))),
                }
                self.ativo = identificador
            item = self.eventos[self.ativo]
            item["pessoas"] = max(
                item.get("pessoas", 1), max(1, min(50, int(quantidade)))
            )
            if nome not in item["arquivos"]:
                item["arquivos"].append(nome)
            self.salvar()
        return nome

    # Consulta o estado de um recorte
    def estado(self, nome):
        with self.trava:
            for item in self.eventos.values():
                if nome in item["arquivos"]:
                    estado = item["estado"]
                    return "processando" if estado == "aguardando" else estado
        return None

    # Informa o estado do buffer
    def status(self):
        with self.trava:
            inicio = min(
                (s["inicio"] for s in self.segmentos.values()), default=time.time()
            )
            ativo = bool(self.processo is not None and self.processo.poll() is None
                         and self.ultimo_segmento and time.time() - self.ultimo_segmento < 25)
            recentes = [
                e for e in self.eventos.values() if e["deteccao"] >= time.time() - 86400
            ]
            return {
                "ativo": ativo,
                "pre_evento_s": self.antes,
                "aparicoes_24h": len(recentes),
                "pessoas_24h": sum(e.get("pessoas", 1) for e in recentes),
                "disponivel_s": round(min(self.antes, max(0, time.time() - inicio))),
                "pendentes": sum(
                    e["estado"] in ("gravando", "aguardando", "processando")
                    for e in self.eventos.values()
                ),
                "erro": self.erro,
            }

    # Monta cópia contínua da câmera
    def comando(self, pasta):
        return [
            self.ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-rtsp_transport",
            "tcp",
            "-timeout",
            "5000000",
            "-use_wallclock_as_timestamps",
            "1",
            "-i",
            self.url,
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c:v",
            "copy",
            "-bsf:v",
            "dump_extra=freq=keyframe",
            "-c:a",
            "aac",
            "-avoid_negative_ts",
            "make_zero",
            "-threads",
            "1",
            "-f",
            "segment",
            "-segment_format",
            "mpegts",
            "-segment_time",
            str(self.segmento),
            "-reset_timestamps",
            "1",
            "-segment_list",
            str(pasta / "indice.csv"),
            "-segment_list_type",
            "csv",
            "-segment_list_size",
            "32",
            str(pasta / "quadro_%09d.ts"),
        ]

    # Lê somente segmentos finalizados
    def ler_indice(self, pasta, base):
        try:
            linhas = list(
                csv.reader(
                    (pasta / "indice.csv").read_text(encoding="utf-8").splitlines()
                )
            )
        except OSError:
            return
        with self.trava:
            for linha in linhas:
                try:
                    nome, inicio, fim = linha
                    arquivo = (pasta / Path(nome).name).resolve()
                    if (
                        not arquivo.is_relative_to(self.buffer)
                        or not arquivo.is_file()
                        or arquivo.suffix != ".ts"
                    ):
                        continue
                    self.segmentos[str(arquivo)] = {
                        "arquivo": str(arquivo.relative_to(self.buffer)),
                        "inicio": base + float(inicio),
                        "fim": base + float(fim),
                    }
                    self.ultimo_segmento = max(self.ultimo_segmento, arquivo.stat().st_mtime)
                except (ValueError, TypeError):
                    continue

    # Mantém apenas trechos necessários
    def limpar(self, agora):
        limite = agora - self.antes - self.segmento * 3
        pendentes = [
            e
            for e in self.eventos.values()
            if e["estado"] in ("gravando", "aguardando", "processando")
        ]
        for caminho, item in list(self.segmentos.items()):
            protegido = any(
                item["fim"] >= e["inicio"]
                and (e["fim"] is None or item["inicio"] <= e["fim"])
                for e in pendentes
            )
            if item["fim"] < limite and not protegido:
                alvo = Path(caminho).resolve()
                if alvo.is_relative_to(self.buffer):
                    alvo.unlink(missing_ok=True)
                self.segmentos.pop(caminho, None)
        for pasta in self.buffer.iterdir():
            # Preserve também o índice vazio: FFmpeg pode estar conectando à câmera.
            if pasta == self.pasta_ativa:
                continue
            if pasta.is_dir() and len(pasta.name) == 33 and pasta.name.startswith("s"):
                for segmento in pasta.glob("*.ts"):
                    resolvido = segmento.resolve()
                    if (
                        resolvido.is_relative_to(self.buffer)
                        and str(resolvido) not in self.segmentos
                        and segmento.stat().st_mtime < limite
                    ):
                        segmento.unlink(missing_ok=True)
            if (
                pasta.is_dir()
                and len(pasta.name) == 33
                and pasta.name.startswith("s")
                and not list(pasta.glob("*.ts"))
            ):
                if time.time() - pasta.stat().st_mtime > 60:
                    (pasta / "indice.csv").unlink(missing_ok=True)
                    try:
                        pasta.rmdir()
                    except OSError:
                        pass
        for identificador, item in list(self.eventos.items()):
            if item["estado"] in ("pronto", "erro") and agora - item["ultima"] > 86400:
                self.eventos.pop(identificador, None)

    # Agenda recortes após a saída
    def agendar(self):
        fim_disponivel = max((s["fim"] for s in self.segmentos.values()), default=0)
        for item in self.eventos.values():
            if (
                item["estado"] == "aguardando"
                and fim_disponivel < item["fim"]
                and time.time() - item["fim"] > 30
            ):
                item["estado"] = "erro"
                item["erro"] = "A câmera não entregou vídeo no período deste evento."
                log.warning("Evento %s sem segmentos de vídeo disponíveis", item["id"])
            if item["estado"] == "aguardando" and fim_disponivel >= item["fim"]:
                try:
                    self.fila.put_nowait(item["id"])
                    item["estado"] = "processando"
                except queue.Full:
                    break

    # Supervisiona o gravador contínuo
    def laco(self):
        pasta = None
        base = None
        nova_tentativa = 0
        try:
            while not self.parada.wait(0.5):
                agora = time.time()
                if (self.processo is not None and self.processo.poll() is None
                        and agora - max(self.inicio_captura, self.ultimo_segmento) > 25):
                    self.erro = "Gravador sem novos quadros; reconectando"
                    log.warning(self.erro)
                    self.fechar_processo()
                if agora - self.ultimo_espaco >= 5:
                    self.ultimo_espaco = agora
                    if shutil.disk_usage(self.buffer).free < 256 * 1024 * 1024:
                        self.erro = "Pouco espaço para gravar"
                        self.fechar_processo()
                        nova_tentativa = agora + 30
                if self.processo is None or self.processo.poll() is not None:
                    if pasta and base:
                        self.ler_indice(pasta, base)
                    if agora >= nova_tentativa:
                        if shutil.disk_usage(self.buffer).free < 256 * 1024 * 1024:
                            self.erro = "Pouco espaço para gravar"
                            nova_tentativa = agora + 30
                        else:
                            pasta = self.buffer / ("s" + uuid.uuid4().hex)
                            pasta.mkdir()
                            self.pasta_ativa = pasta
                            self.inicio_captura = agora
                            self.ultimo_segmento = 0
                            self.processo = subprocess.Popen(
                                self.comando(pasta),
                                stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                creationflags=getattr(
                                    subprocess, "CREATE_NO_WINDOW", 0
                                ),
                            )
                            self.erro = "Aguardando primeiros segmentos da câmera"
                            base = None
                            nova_tentativa = agora + 5
                if pasta:
                    primeiro = pasta / "quadro_000000000.ts"
                    if base is None and primeiro.is_file():
                        dados_arquivo = primeiro.stat()
                        base = getattr(
                            dados_arquivo, "st_birthtime", dados_arquivo.st_ctime
                        )
                    if base is not None:
                        self.ler_indice(pasta, base)
                        if self.ultimo_segmento >= self.inicio_captura:
                            self.erro = None
                with self.trava:
                    if (
                        self.ultima_presenca is not None
                        and agora - self.ultima_presenca >= 3
                    ):
                        self.fechar_presenca()
                    self.agendar()
                    self.limpar(agora)
                    if agora - self.ultimo_diario >= 5:
                        self.salvar()
        except Exception:
            log.exception("Falha no buffer da câmera")
            self.erro = "Falha no buffer da câmera"
        finally:
            self.fechar_processo()
            if pasta and base:
                self.ler_indice(pasta, base)
            with self.trava:
                self.fechar_presenca()
                self.agendar()
                self.salvar()

    # Finaliza o segmento corrente
    def fechar_processo(self):
        if self.processo is None or self.processo.poll() is not None:
            return
        try:
            self.processo.stdin.write(b"q\n")
            self.processo.stdin.flush()
            self.processo.wait(timeout=5)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            self.processo.terminate()
            try:
                self.processo.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.processo.kill()

    # Exporta vídeos fora da inferência
    def exportar_fila(self):
        while not self.parada.is_set() or not self.fila.empty():
            try:
                identificador = self.fila.get(timeout=1)
            except queue.Empty:
                continue
            self.exportar(identificador)
            self.fila.task_done()

    # Confirma imagem decodificável
    @staticmethod
    def validar_video(arquivo, ffmpeg):
        if not ffmpeg:
            return False
        comando = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-threads",
            "1",
            "-i",
            str(arquivo),
            "-map",
            "0:v:0",
            "-vf",
            "scale=2:2",
            "-threads",
            "1",
            "-frames:v",
            "1",
            "-c:v",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "pipe:1",
        ]
        try:
            resultado = subprocess.run(
                comando,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return resultado.returncode == 0 and len(resultado.stdout or b"") == 12
        except (OSError, subprocess.TimeoutExpired):
            return False

    # Prepara vídeo e painel juntos
    def exportar(self, identificador):
        lista = self.buffer / (identificador + ".txt")
        temporario = self.pasta / ("recorte_" + identificador + ".part.mp4")
        webm_temporario = self.pasta / ("recorte_" + identificador + ".part.webm")
        try:
            with self.trava:
                item = dict(self.eventos[identificador])
                segmentos = sorted(
                    (
                        dict(s)
                        for s in self.segmentos.values()
                        if s["fim"] > item["inicio"] and s["inicio"] <= item["fim"]
                    ),
                    key=lambda s: s["inicio"],
                )
            if not segmentos:
                raise RuntimeError("Não há vídeo no buffer")
            lista.write_text(
                "".join(
                    "file '"
                    + (self.buffer / s["arquivo"]).as_posix().replace("'", "'\\''")
                    + "'\n"
                    for s in segmentos
                ),
                encoding="utf-8",
            )
            inicio = max(item["inicio"], segmentos[0]["inicio"])
            duracao = max(0.1, item["fim"] - inicio)
            comando = [
                self.ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-threads",
                "2",
                "-i",
                str(lista),
                "-ss",
                str(max(0, inicio - segmentos[0]["inicio"])),
                "-t",
                str(duracao),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
            ]
            if self.filtros:
                comando += ["-vf", self.filtros]
            comando += [
                "-c:v",
                "libx264",
                "-threads",
                "2",
                "-preset",
                "ultrafast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(temporario),
            ]
            filtro_painel = ",".join(
                filter(None, [self.filtros, "scale=w='min(1280,iw)':h=-2"])
            )
            comando += [
                "-ss",
                str(max(0, inicio - segmentos[0]["inicio"])),
                "-t",
                str(duracao),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-vf",
                filtro_painel,
                "-c:v",
                "libvpx",
                "-deadline",
                "realtime",
                "-cpu-used",
                "8",
                "-threads",
                "2",
                "-b:v",
                "1600k",
                "-c:a",
                "libvorbis",
                "-ar",
                "48000",
                "-b:a",
                "48k",
                str(webm_temporario),
            ]
            resultado = subprocess.run(
                comando,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=max(120, duracao * 2),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if resultado.returncode:
                log.warning(
                    "FFmpeg encerrou recorte com código %s", resultado.returncode
                )
            if (
                not temporario.is_file()
                or temporario.stat().st_size < 1024
            ):
                raise RuntimeError("Não foi possível finalizar o vídeo")
            if not self.validar_video(temporario, self.ffmpeg):
                raise RuntimeError("Gravação sem imagem reproduzível")
            webm_valido = webm_temporario.is_file() and self.validar_video(webm_temporario, self.ffmpeg)
            destino = self.pasta / item["arquivos"][0]
            if webm_valido:
                webm_temporario.replace(destino.with_suffix(".webm"))
            temporario.replace(destino)
            for nome in item["arquivos"][1:]:
                for extensao in (".webm", ".mp4"):
                    alvo = (self.pasta / nome).with_suffix(extensao)
                    origem = destino.with_suffix(extensao)
                    if not origem.exists():
                        continue
                    if not alvo.exists():
                        try:
                            os.link(origem, alvo)
                        except OSError:
                            shutil.copyfile(origem, alvo)
            with self.trava:
                self.eventos[identificador]["estado"] = "pronto"
                self.salvar()
        except Exception:
            with self.trava:
                self.eventos[identificador]["estado"] = "erro"
                self.salvar()
            log.exception("Falha ao finalizar recorte")
        finally:
            lista.unlink(missing_ok=True)
            temporario.unlink(missing_ok=True)
            webm_temporario.unlink(missing_ok=True)

    # Solicita parada sem perder índices
    def parar(self):
        self.parada.set()
        worker = getattr(self, "worker", None)
        if worker and worker is not threading.current_thread():
            worker.join(timeout=9)
        if not worker or worker.is_alive():
            self.fechar_processo()
