

import logging
from pathlib import Path
import queue
import threading
import time

import config
from comandos.automacao.confirmacao_pessoas import ConfirmadorPessoas

try:
    import cv2  # noqa: F401 - valida a
except ImportError:
    cv2 = None

log = logging.getLogger("mark2.visao_inteligente")



CONFIANCA_MINIMA_PESSOA = 0.50
CONFIANCA_MINIMA_PONTO = 0.25
PONTOS_CORPORAIS_MINIMOS = 4

IDADE_MAXIMA_HUD_S = 1.0
# Idade máxima da pose para a decisão
# Limita a idade do quadro, incluindo
IDADE_MAXIMA_DETECCAO_PADRAO_S = 2.5
_estadoHud = {"poses": [], "poseTs": 0.0}
_TRAVA_HUD = threading.Lock()
_engine = None


class PoseWorker:
    


    def __init__(self):
        self.quadros = queue.Queue(maxsize=1)
        self.pararEvento = threading.Event()
        self.thread = None
        self.modelo = None
        self.backend = "CPU"
        self.modeloPronto = False
        self.poseErro = None
        self.resultado = []
        self.resultadoTs = 0.0
        self.resultadoSeq = 0
        self.resultadoQuadroTs = 0.0
        self.ultimaSubmissao = 0.0
        self.proximaTentativaPose = 0.0
        self.intervalo = 1.0 / max(1.0, min(60.0, float(getattr(config, "VIGIA_FPS_ALVO", 60))))
        self.ultimaInferenciaS = 0.0
        self._ultimoAvisoLento = 0.0
        self._trava = threading.RLock()
        self.confirmador = ConfirmadorPessoas()
        self._modeloCarregando = False


    def iniciar(self):
        if self.thread and self.thread.is_alive():
            return self.thread
        self.pararEvento.clear()
        self.thread = threading.Thread(
            target=self._executar,
            daemon=True,
            name="mark2-yolo11-pose",
        )
        self.thread.start()
        return self.thread


    def parar(self):
        self.pararEvento.set()
        try:
            self.quadros.put_nowait(None)
        except queue.Full:
            pass

    # Envia o quadro para inferência
    def submeter(self, quadro):
        if quadro is None or cv2 is None or not bool(getattr(config, "VIGIA_POSE_ATIVO", True)):
            return
        agora = time.monotonic()
        if agora - self.ultimaSubmissao < self.intervalo:
            return
        self.ultimaSubmissao = agora
        item = (agora, quadro.copy())
        try:
            self.quadros.put_nowait(item)
        except queue.Full:
            try:
                self.quadros.get_nowait()
            except queue.Empty:
                pass
            try:
                self.quadros.put_nowait(item)
            except queue.Full:
                pass

    # Carrega pose
    def _carregarPose(self):
        if self._modeloCarregando or time.monotonic() < self.proximaTentativaPose:
            return
        self._modeloCarregando = True
        try:
            nome = str(getattr(config, "VIGIA_MODELO_POSE", "yolo11n-pose.pt"))
            modelo = None
            onnx = Path(nome).with_suffix(".onnx")
            if onnx.is_file():
                try:
                    from comandos.automacao.pose_gpu import PoseDirectML
                    modelo = PoseDirectML(onnx)
                    self.backend = "DirectML GPU"
                except Exception as erro_gpu:
                    log.warning("DirectML indisponível; usando CPU: %s", erro_gpu)
            if modelo is None:
                from ultralytics import YOLO
                modelo = YOLO(nome)
                self.backend = "CPU"
            with self._trava:
                self.modelo = modelo
                self.modeloPronto = True
                self.poseErro = None
            log.info("Modelo YOLO11-Pose carregado em %s: %s", self.backend, nome)
        except Exception as erro:
            with self._trava:
                self.modeloPronto = False
                self.poseErro = str(erro).splitlines()[0][:220]
            self.proximaTentativaPose = time.monotonic() + 60
            log.warning("YOLO11-Pose indisponível; a câmera continua sem confirmar pessoas: %s", self.poseErro)
        finally:
            self._modeloCarregando = False

    # Infere pose
    def _inferirPose(self, quadro):
        altura, largura = quadro.shape[:2]
        resultados = self.modelo.predict(
            quadro,
            imgsz=640,
            conf=CONFIANCA_MINIMA_PESSOA,
            classes=[0],
            max_det=50,
            verbose=False,
        )
        saida = []
        if not resultados:
            return saida
        resultado = resultados[0]
        caixas = resultado.boxes
        pontos = resultado.keypoints
        if caixas is None:
            return saida
        caixasPx = (caixas.xyxy.cpu().numpy() if hasattr(caixas.xyxy, "cpu") else caixas.xyxy)
        confiancas = (caixas.conf.cpu().numpy() if hasattr(caixas.conf, "cpu") else caixas.conf) if caixas.conf is not None else [0.0] * len(caixasPx)
        pontosPx = (pontos.data.cpu().numpy() if hasattr(pontos.data, "cpu") else pontos.data) if pontos is not None and pontos.data is not None else None
        for indice, caixa in enumerate(caixasPx):
            x1, y1, x2, y2 = [float(valor) for valor in caixa[:4]]
            confianca = float(confiancas[indice])
            largura_caixa = x2 - x1
            altura_caixa = y2 - y1
            if (
                largura_caixa <= 0
                or altura_caixa <= 0
                or confianca < CONFIANCA_MINIMA_PESSOA
                or altura_caixa < largura_caixa * 0.70
                or altura_caixa / max(1, altura) < 0.08
            ):
                continue
            keypoints = []
            if pontosPx is not None and indice < len(pontosPx):
                for ponto in pontosPx[indice]:
                    x, y = float(ponto[0]), float(ponto[1])
                    pontoConf = float(ponto[2]) if len(ponto) > 2 else 1.0
                    keypoints.append([
                        round(max(0.0, min(1.0, x / largura)), 5),
                        round(max(0.0, min(1.0, y / altura)), 5),
                        round(max(0.0, min(1.0, pontoConf)), 3),
                    ])
            pontos_visiveis = sum(
                1 for ponto in keypoints if ponto[2] >= CONFIANCA_MINIMA_PONTO
            )
            if pontos_visiveis < PONTOS_CORPORAIS_MINIMOS:
                continue
            saida.append({
                "x1": round(max(0.0, x1 / largura), 5),
                "y1": round(max(0.0, y1 / altura), 5),
                "x2": round(min(1.0, x2 / largura), 5),
                "y2": round(min(1.0, y2 / altura), 5),
                "confianca": round(confianca, 3),
                "pontos_visiveis": pontos_visiveis,
                "keypoints": keypoints,
            })
        return saida


    def _executar(self):
        while not self.pararEvento.is_set():
            if not self.modeloPronto and bool(getattr(config, "VIGIA_POSE_ATIVO", True)):
                self._carregarPose()
            try:
                item = self.quadros.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                continue
            if isinstance(item, tuple) and len(item) == 2:
                quadro_ts, quadro = item
            else:
                quadro_ts, quadro = time.monotonic(), item
            if not bool(getattr(config, "VIGIA_POSE_ATIVO", True)) or not self.modeloPronto:
                continue
            try:
                inicio_inferencia = time.monotonic()
                try:
                    poses = self._inferirPose(quadro)
                except Exception:
                    if self.backend != "DirectML GPU":
                        raise
                    log.exception("Inferência GPU falhou; retomando na CPU")
                    from ultralytics import YOLO
                    self.modelo = YOLO(str(getattr(config, "VIGIA_MODELO_POSE", "yolo11n-pose.pt")))
                    self.backend = "CPU"
                    poses = self._inferirPose(quadro)
                duracao = time.monotonic() - inicio_inferencia
                self.ultimaInferenciaS = duracao
                if duracao > 0.8 and time.monotonic() - self._ultimoAvisoLento > 60:
                    self._ultimoAvisoLento = time.monotonic()
                    log.warning(
                        "Inferência de pose lenta (%.2f s por quadro); considere GPU ou imgsz menor.",
                        duracao,
                    )
            except Exception as erro:
                with self._trava:
                    self.poseErro = str(erro).splitlines()[0][:220]
                log.warning("Falha pontual na inferência de pose; a captura e o vídeo continuam ativos.", exc_info=True)
                continue
            instante = time.monotonic()
            poses = self.confirmador.atualizar(poses, quadro_ts)
            with self._trava:
                self.poseErro = None
                self.resultadoSeq += 1
                self.resultado = poses
                self.resultadoTs = instante
                self.resultadoQuadroTs = quadro_ts
            with _TRAVA_HUD:
                _estadoHud["poses"] = poses
                _estadoHud["poseTs"] = instante

    # Consulta pose
    def obterPose(self, idadeMaxima=None):
        if idadeMaxima is None:
            idadeMaxima = max(
                IDADE_MAXIMA_HUD_S,
                float(getattr(config, "VIGIA_POSE_IDADE_MAX_S", IDADE_MAXIMA_DETECCAO_PADRAO_S)),
            )
        with self._trava:
            # A fila e a inferencia tambem
            idade = time.monotonic() - self.resultadoQuadroTs if self.resultadoQuadroTs else float("inf")
            disponivel = self.modeloPronto and bool(getattr(config, "VIGIA_POSE_ATIVO", True))
            return {
                "poses": list(self.resultado) if disponivel and idade <= idadeMaxima else [],
                "idade": idade,
                "sequencia": self.resultadoSeq,
                "quadro_ts": getattr(self, "resultadoQuadroTs", 0.0),
                "pronto": disponivel and idade <= idadeMaxima,
            }


    def status(self):
        ativado = bool(getattr(config, "VIGIA_POSE_ATIVO", True))
        if not ativado:
            situacao = "desativado"
        elif self.modeloPronto:
            situacao = "ativo"
        elif self.poseErro:
            situacao = "indisponível"
        elif self.thread and self.thread.is_alive():
            situacao = "carregando"
        else:
            situacao = "parado"
        return {
            "pose": {
                "status": situacao,
                "ativo": ativado,
                "erro": self.poseErro,
                "modelo": str(getattr(config, "VIGIA_MODELO_POSE", "yolo11n-pose.pt")),
                "inferencia_s": round(self.ultimaInferenciaS, 3),
                "backend": self.backend,
            },
            "altura": {"status": "indisponível", "motivo": "sem calibração métrica validada"},
        }



def iniciar():
    global _engine
    if _engine is None:
        _engine = PoseWorker()
    _engine.iniciar()
    return _engine



def parar():
    if _engine is not None:
        _engine.parar()


# Envia o quadro para inferência
def submeter(quadro):
    if _engine is not None:
        _engine.submeter(quadro)


# Consulta pose
def obterPose(idadeMaxima=None):
    if _engine is None:
        return {"poses": [], "idade": None, "pronto": False}
    return _engine.obterPose(idadeMaxima)



def estado():
    if _engine is None:
        ativo = bool(getattr(config, "VIGIA_POSE_ATIVO", True))
        return {
            "pose": {"status": "parado" if ativo else "desativado", "ativo": ativo, "erro": None},
            "altura": {"status": "indisponível", "motivo": "sem calibração métrica validada"},
        }
    return _engine.status()


# Normaliza pose
def normalizarPose(deteccoes, largura, altura):
    saida = []
    for item in deteccoes or []:
        if not isinstance(item, dict):
            continue
        pontos = []
        for ponto in item.get("keypoints", []):
            if not isinstance(ponto, (list, tuple)) or len(ponto) < 2:
                continue
            x, y = float(ponto[0]), float(ponto[1])
            confianca = float(ponto[2]) if len(ponto) > 2 else 1.0
            if not all(map(lambda valor: valor == valor and abs(valor) != float("inf"), (x, y, confianca))):
                continue
            pontos.append([
                min(1.0, max(0.0, x)),
                min(1.0, max(0.0, y)),
                min(1.0, max(0.0, confianca)),
            ])
        if len(pontos) >= 17:
            saida.append({"keypoints": pontos[:17], "id": item.get("id")})
    return saida



def posesHud():
    with _TRAVA_HUD:
        if time.monotonic() - _estadoHud["poseTs"] > IDADE_MAXIMA_HUD_S:
            return []
        return list(_estadoHud["poses"])


__all__ = ["estado", "iniciar", "normalizarPose", "obterPose", "parar", "posesHud", "submeter"]