import copy
import json
import logging
import math
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp",
)

import config
from comandos import llm_local, visao
from interface import voz
from comandos.automacao import presenca, visao_inteligente, zonasCamera

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None

log = logging.getLogger("mark2.vigia_camera")


PASTA_ALERTAS = config.DATA_DIR / "vigia"
_ARQUIVO_SEGURANCA_RE = re.compile(
    r"(?:(?:pessoa|linha)_\d{8}_\d{6}_\d+\.(?:jpg|mp4|webm)|movimento_\d{8}_\d{6}_\d+\.jpg|gravacao_\d{8}_\d{6}(?:_\d{6})?(?:_(?:compat|poster))?\.(?:mp4|webm|jpg))\Z",
    re.IGNORECASE,
)

TRAVA = threading.Lock()
PARAR = threading.Event()
THREAD = None
CALLBACK = None
DEFESAS_ARMADAS = False
PTZ_CONTROLADOR = None
PTZ_TRAVA = threading.Lock()
GRAVACAO_ATUAL = None
GRAVACAO_TRAVA = threading.Lock()

quadro_atual = None
quadro_atual_hora = 0.0
ESTADO = {
    "camera_movida": False,
    "camera_posicao_validada": False,
    "ativo": False,
    "conectada": False,
    "pessoas": 0,
    "ultimo_alerta": None,
    "ultima_foto": None,
    "noite": False,
    "resolucao": None,
    "deteccao_nativa": "aguardando retangulo amarelo",
    "movimento": False,
    "ultimo_movimento": None,
    "ptz_estado": "desativado",
    "camera_ptz_movimento_desde": 0.0,
    "modo_noturno_onvif": "automatico",
}


# Consulta opção de configuração
def cfg(nome, padrao):
    return getattr(config, nome, padrao)


# Consulta lente selecionada
def lente_ativa():
    return "baixo" if cfg("VIGIA_DUAS_LENTES", False) else "unica"



def recortar_lente(quadro):

    if not cfg("VIGIA_DUAS_LENTES", False):
        return quadro
    altura = quadro.shape[0]
    corte = int(altura * float(cfg("VIGIA_DIVISAO_Y", 0.5)))
    corte = min(max(corte, 1), altura - 1)
    return quadro[corte:]



def url_mascarada(url):
    if "@" in url:
        return url.split("://", 1)[0] + "://***@" + url.rsplit("@", 1)[1]
    return url


# Limpa fotos antigas
def limpar_fotos_antigas():
    """Limpa fotos antigas."""
    try:
        dias = max(1, min(90, int(cfg("VIGIA_RETENCAO_DIAS", 7))))
    except (TypeError, ValueError, OverflowError):
        dias = 7
    limite = time.time() - dias * 86400
    removidas = 0
    try:
        if not PASTA_ALERTAS.is_dir():
            return 0
        for caminho in PASTA_ALERTAS.iterdir():
            if not caminho.is_file() or not _ARQUIVO_SEGURANCA_RE.fullmatch(
                caminho.name
            ):
                continue
            try:
                if caminho.stat().st_mtime < limite:
                    caminho.unlink()
                    removidas += 1
            except FileNotFoundError:
                continue
            except OSError:
                log.warning("Could not remove expired security photo: %s", caminho.name)
    except OSError:
        log.warning("Could not check security photo retention.", exc_info=True)
    if removidas:
        log.info(
            "Retenção de %d dia(s): %d foto(s) antiga(s) removida(s).", dias, removidas
        )
    return removidas


# Mede brilho
def medir_brilho(quadro):
    return float(cv2.cvtColor(quadro, cv2.COLOR_BGR2GRAY).mean())



def realcar_noite(quadro):
    lab = cv2.cvtColor(quadro, cv2.COLOR_BGR2LAB)
    luminancia, canal_a, canal_b = cv2.split(lab)
    media = max(1.0, float(luminancia.mean()))
    gama = (
        1.0
        if media >= 110
        else min(1.0, max(0.35, math.log(110 / 255) / math.log(media / 255)))
    )
    tabela = np.array(
        [255 * (valor / 255) ** gama for valor in range(256)], dtype=np.uint8
    )
    luminancia = cv2.LUT(luminancia, tabela)
    luminancia = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(luminancia)
    return cv2.cvtColor(cv2.merge((luminancia, canal_a, canal_b)), cv2.COLOR_LAB2BGR)



def equilibrar_brilho(quadro):
    
    alvo = float(cfg("VIGIA_FOTO_BRILHO_ALVO", 120))
    lab = cv2.cvtColor(quadro, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    media = float(l.mean())
    if media < 1 or abs(media - alvo) < 10:
        return quadro

    gama = math.log(alvo / 255) / math.log(media / 255)
    gama = min(max(gama, 0.45), 1.8)
    tabela = np.array([255 * (i / 255) ** gama for i in range(256)], dtype=np.uint8)
    l = cv2.LUT(l, tabela)

    if media < alvo * 0.8:
        l = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8)).apply(l)

    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


# Salva foto maxima
def salvar_foto_maxima(imagem, caminho):
    parametros = [cv2.IMWRITE_JPEG_QUALITY, 100]
    if hasattr(cv2, "IMWRITE_JPEG_SAMPLING_FACTOR"):
        parametros += [
            cv2.IMWRITE_JPEG_SAMPLING_FACTOR,
            cv2.IMWRITE_JPEG_SAMPLING_FACTOR_444,
        ]
    if not cv2.imwrite(str(caminho), imagem, parametros):
        cv2.imwrite(str(caminho), imagem, [cv2.IMWRITE_JPEG_QUALITY, 100])


# Lê roi
def ler_roi():
    roi = cfg("VIGIA_ROI", None)
    try:
        x1, y1, x2, y2 = (float(v) for v in roi)
    except (TypeError, ValueError):
        return None
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        log.warning("VIGIA_ROI inválido: %r (use frações 0-1).", roi)
        return None
    return x1, y1, x2, y2


# Detecta caixas camera
def detectar_caixas_camera(quadro):
    if cv2 is None or np is None or quadro is None or quadro.size == 0:
        return []
    hsv = cv2.cvtColor(quadro, cv2.COLOR_BGR2HSV)
    mascara = cv2.inRange(hsv, np.array((14, 90, 100)), np.array((42, 255, 255)))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mascara = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, kernel, iterations=2)
    contornos = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[
        -2
    ]
    altura, largura = quadro.shape[:2]
    caixas = []
    for contorno in contornos:
        x, y, w, h = cv2.boundingRect(contorno)
        if w < max(24, int(largura * 0.025)) or h < max(38, int(altura * 0.045)):
            continue
        if w > largura * 0.92 or h > altura * 0.92 or not 0.12 <= w / max(1, h) <= 2.8:
            continue
        faixa = max(2, min(8, int(min(w, h) * 0.025)))
        recorte = mascara[y : y + h, x : x + w]
        bordas = (
            float(np.count_nonzero(recorte[:faixa, :])) / max(1, w * faixa),
            float(np.count_nonzero(recorte[-faixa:, :])) / max(1, w * faixa),
            float(np.count_nonzero(recorte[:, :faixa])) / max(1, h * faixa),
            float(np.count_nonzero(recorte[:, -faixa:])) / max(1, h * faixa),
        )
        if min(bordas) < 0.22 or sum(bordas) < 1.35:
            continue
        caixa = (x, y, x + w, y + h)
        caixas.append(caixa)
    return caixas


ARQ_LINHA = config.DATA_DIR / "linha_seguranca.json"
SENTIDOS = ("ambos", "positivo", "negativo")
SENSIBILIDADES = ("baixa", "media", "alta")
# Tempo máximo sem pose válida antes
TOLERANCIA_POSE_S = 3.0

SENSIBILIDADE_MARGEM = {"alta": 0.0, "media": 0.012, "baixa": 0.03}

LINHA_PADRAO = {
    "ativa": True,
    "definida": False,
    "p1": [0.2, 0.5],
    "p2": [0.8, 0.5],
    "sentido": "ambos",
    "sensibilidade": "media",
    "cooldown_s": 5,
    "so_linha": False,
    "pausar_se_mover": True,
    "zona_topo_pct": 65.0,
    "zona_linha_pct": 65.0,
    "zona_topo_linha_pct": 65.0,
    "hud": {
        "linha": True,
        "seta": True,
        "caixas": True,
        "rotulos": True,
        "abrir_auto": True,
        "flash_s": 8,
        "espessura": 3,
        "cor_linha": "#ffd23f",
        "cor_alarme": "#ff3b3b",
    },
}

_LINHA = None
_TRAVA_LINHA = threading.Lock()



def _num(valor, padrao, minimo, maximo):
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return padrao
    if v != v:
        return padrao
    return min(max(v, minimo), maximo)



def _ponto(valor, padrao):
    try:
        x, y = (float(v) for v in valor)
    except (TypeError, ValueError):
        return list(padrao)
    if x != x or y != y:
        return list(padrao)
    return [round(min(max(x, 0.0), 1.0), 4), round(min(max(y, 0.0), 1.0), 4)]



def _cor(valor, padrao):
    if isinstance(valor, str) and re.fullmatch("#[0-9a-fA-F]{6}", valor):
        return valor
    return padrao


# Normaliza linha
def _normalizar_linha(dados, base):
    saida = copy.deepcopy(base)
    if not isinstance(dados, dict):
        return saida
    saida["ativa"] = bool(dados.get("ativa", saida["ativa"]))
    saida["definida"] = bool(dados.get("definida", saida["definida"]))
    saida["p1"] = _ponto(dados.get("p1"), saida["p1"])
    saida["p2"] = _ponto(dados.get("p2"), saida["p2"])
    if (
        math.hypot(saida["p2"][0] - saida["p1"][0], saida["p2"][1] - saida["p1"][1])
        < 0.02
    ):
        saida["definida"] = False
    if dados.get("sentido") in SENTIDOS:
        saida["sentido"] = dados["sentido"]
    if dados.get("sensibilidade") in SENSIBILIDADES:
        saida["sensibilidade"] = dados["sensibilidade"]
    saida["cooldown_s"] = _num(dados.get("cooldown_s"), saida["cooldown_s"], 0, 600)
    saida["so_linha"] = bool(dados.get("so_linha", saida["so_linha"]))
    saida["pausar_se_mover"] = bool(
        dados.get("pausar_se_mover", saida["pausar_se_mover"])
    )
    saida["zona_topo_pct"] = round(
        _num(dados.get("zona_topo_pct"), saida["zona_topo_pct"], 0, 95), 1
    )
    saida["zona_topo_linha_pct"] = round(
        _num(dados.get("zona_topo_linha_pct"), saida["zona_topo_linha_pct"], 0, 95), 1
    )
    saida["zona_linha_pct"] = round(
        _num(dados.get("zona_linha_pct"), saida["zona_topo_pct"], 0, 95), 1
    )

    hud_novo = dados.get("hud") if isinstance(dados.get("hud"), dict) else {}
    hud = saida["hud"]
    for chave in ("linha", "seta", "caixas", "rotulos", "abrir_auto"):
        hud[chave] = bool(hud_novo.get(chave, hud[chave]))
    hud["flash_s"] = _num(hud_novo.get("flash_s"), hud["flash_s"], 1, 60)
    hud["espessura"] = int(_num(hud_novo.get("espessura"), hud["espessura"], 1, 10))
    hud["cor_linha"] = _cor(hud_novo.get("cor_linha"), hud["cor_linha"])
    hud["cor_alarme"] = _cor(hud_novo.get("cor_alarme"), hud["cor_alarme"])

    saida["ativa"] = bool(saida["definida"])
    saida["zona_topo_linha_pct"] = saida["zona_topo_pct"]
    saida["zona_linha_pct"] = saida["zona_topo_pct"]
    saida["so_linha"] = False
    return saida



def linha_atual():
    
    global _LINHA
    with _TRAVA_LINHA:
        if _LINHA is None:
            try:
                dados = json.loads(ARQ_LINHA.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                dados = {}
            _LINHA = _normalizar_linha(dados, LINHA_PADRAO)
        return _LINHA


# Carrega linha
def carregar_linha():
    return copy.deepcopy(linha_atual())


# Salva linha
def salvar_linha(dados):
    global _LINHA
    if not isinstance(dados, dict):
        raise ValueError("dados inválidos")
    antigo = linha_atual()
    novo = _normalizar_linha(dados, antigo)
    novo["ativa"] = bool(novo["definida"])
    novo["zona_topo_pct"] = _num(
        dados.get("zona_topo_pct"), antigo["zona_topo_pct"], 0, 95
    )
    novo["zona_topo_linha_pct"] = novo["zona_topo_pct"]
    novo["zona_linha_pct"] = novo["zona_topo_pct"]
    novo["so_linha"] = False
    novo["hud"]["caixas"] = True
    if novo["definida"] and (
        novo["p1"] != antigo["p1"]
        or novo["p2"] != antigo["p2"]
        or _referencia() is None
    ):
        definir_referencia(ultimo_quadro())
    try:
        ARQ_LINHA.parent.mkdir(parents=True, exist_ok=True)
        tmp = ARQ_LINHA.with_suffix(".tmp")
        tmp.write_text(json.dumps(novo, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(ARQ_LINHA)
    except OSError:
        log.error("Não consegui gravar a linha de segurança.", exc_info=True)
        raise ValueError("Não consegui salvar a linha no disco.")
    with _TRAVA_LINHA:
        _LINHA = novo
    return copy.deepcopy(novo)


ARQ_REFERENCIA = config.DATA_DIR / "linha_referencia.png"
_REF = {"gray": None, "carregada": False}
_JANELA = {}



def _cinza_pequeno(quadro):
    altura, largura = quadro.shape[:2]
    escala = 320.0 / largura
    pequeno = cv2.resize(
        quadro, (320, max(8, int(altura * escala))), interpolation=cv2.INTER_AREA
    )
    return cv2.cvtColor(pequeno, cv2.COLOR_BGR2GRAY).astype(np.float32)


# Define referencia
def definir_referencia(quadro):
    if cv2 is None or quadro is None:
        return False
    temporario = ARQ_REFERENCIA.with_name(ARQ_REFERENCIA.stem + ".tmp.png")
    try:
        ARQ_REFERENCIA.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(temporario), quadro):
            raise OSError("OpenCV recusou a gravação da referência da linha.")
        temporario.replace(ARQ_REFERENCIA)
        _REF["gray"] = _cinza_pequeno(quadro)
        _REF["carregada"] = True
        return True
    except Exception:
        try:
            temporario.unlink(missing_ok=True)
        except OSError:
            pass
        log.warning(
            "Não consegui gravar a imagem de referência da linha.", exc_info=True
        )
        return False






def _referencia():
    if not _REF["carregada"]:
        _REF["carregada"] = True
        try:
            img = cv2.imread(str(ARQ_REFERENCIA))
            if img is not None:
                _REF["gray"] = _cinza_pequeno(img)
        except Exception:
            pass
    return _REF["gray"]



def referencia_disponivel():
    
    return cv2 is not None and _referencia() is not None



def camera_deslocada(quadro):
    
    ref = _referencia()
    if ref is None or cv2 is None:
        return None, 0.0, 0.0
    atual = _cinza_pequeno(quadro)
    if atual.shape != ref.shape:
        return False, 0.0, 0.0
    janela = _JANELA.get(atual.shape)
    if janela is None:
        janela = _JANELA[atual.shape] = cv2.createHanningWindow(
            (atual.shape[1], atual.shape[0]), cv2.CV_32F
        )
    (dx, dy), resposta = cv2.phaseCorrelate(ref, atual, janela)
    if resposta < 0.05:
        return None, dx, dy
    tol = float(cfg("VIGIA_LINHA_TOL_MOVER", 0.02)) * atual.shape[1]
    return math.hypot(dx, dy) > tol, dx, dy


class Rastreador:
    


    def __init__(self):
        self.trilhas = {}
        self.proximo_id = 1
        self.ultimo_instante = None


    @staticmethod
    def _geometria(linha, largura, altura, diagonal):
        if not linha:
            return None
        ax, ay = linha["p1"][0] * largura, linha["p1"][1] * altura
        bx, by = linha["p2"][0] * largura, linha["p2"][1] * altura
        comp = math.hypot(bx - ax, by - ay)
        if comp < 5:
            return None
        return {
            "a": (ax, ay),
            "comp": comp,
            "ux": (bx - ax) / comp,
            "uy": (by - ay) / comp,
            "margem": SENSIBILIDADE_MARGEM.get(linha.get("sensibilidade"), 0.012)
            * diagonal,
            "sentido": linha.get("sentido", "ambos"),
        }


    @staticmethod
    def _dist(ponto, g):

        return g["ux"] * (ponto[1] - g["a"][1]) - g["uy"] * (ponto[0] - g["a"][0])


    def _checar(self, trilha, pe, g):
        d = self._dist(pe, g)
        if abs(d) <= g["margem"]:
            return None
        lado = 1 if d > 0 else -1
        if trilha["lado"] == 0:
            trilha.update(lado=lado, pe_lado=pe)
            return None

        sentido = None
        if lado != trilha["lado"]:
            antes = trilha["pe_lado"]
            d0 = self._dist(antes, g)
            k = d0 / (d0 - d)
            xx = antes[0] + k * (pe[0] - antes[0])
            yy = antes[1] + k * (pe[1] - antes[1])
            tau = (xx - g["a"][0]) * g["ux"] + (yy - g["a"][1]) * g["uy"]
            tol = 0.10 * g["comp"]
            candidato = "positivo" if lado > 0 else "negativo"
            nome = "Sentido 1" if candidato == "positivo" else "Sentido 2"
            if not (-tol <= tau <= g["comp"] + tol):
                log.info(
                    "Linha: pessoa trocou de lado, mas fora do trecho desenhado (%s).",
                    nome,
                )
            elif g["sentido"] not in ("ambos", candidato):
                log.info(
                    "Linha: cruzamento no %s IGNORADO porque a linha está configurada "
                    "para outro sentido. Troque o sentido ou use 'Ambos'.",
                    nome,
                )
            else:
                sentido = candidato
        trilha.update(lado=lado, pe_lado=pe)
        return sentido


    def atualizar(self, caixas, agora, largura, altura, linha=None):
        ttl = float(cfg("VIGIA_TRILHA_TTL_S", 4.0))
        for tid in [t for t, v in self.trilhas.items() if agora - v["visto"] > ttl]:
            del self.trilhas[tid]

        diagonal = math.hypot(largura, altura) or 1.0
        limite = 0.30 * diagonal
        pes = [((c[0] + c[2]) / 2.0, float(c[3])) for c in caixas]

        pares = sorted(
            (math.hypot(pes[i][0] - t["pe"][0], pes[i][1] - t["pe"][1]), i, tid)
            for i in range(len(pes))
            for tid, t in self.trilhas.items()
        )
        casados, usados = {}, set()
        for dist, i, tid in pares:
            if dist > limite:
                break
            if i in casados or tid in usados:
                continue
            casados[i] = tid
            usados.add(tid)

        geometria = self._geometria(linha, largura, altura, diagonal)
        cruzamentos = []
        for i, pe in enumerate(pes):
            tid = casados.get(i)
            if tid is None:
                tid = self.proximo_id
                self.proximo_id += 1
                self.trilhas[tid] = {"lado": 0, "pe_lado": pe}
            trilha = self.trilhas[tid]
            trilha.update(pe=pe, visto=agora, caixa=caixas[i])
            if geometria is not None:
                sentido = self._checar(trilha, pe, geometria)
                if sentido:

                    trilha["permanencia_inicio"] = agora
                    trilha["reincidente_emitido"] = False
                    trilha["sentido_cruzado"] = sentido
                    trilha["lado_cruzamento"] = trilha["lado"]
                    trilha["ultima_presenca"] = agora
                    cruzamentos.append(sentido)
                elif trilha.get("permanencia_inicio") is not None:

                    trilha["ultima_presenca"] = agora
        self.ultimo_instante = agora
        return cruzamentos

    # Verifica reincidentes
    def verificar_reincidentes(self, agora, permanencia_s=10.0, perda_s=1.5):
        """Verifica reincidentes."""
        eventos = []
        ttl = float(cfg("VIGIA_TRILHA_TTL_S", 4.0))

        for tid, trilha in self.trilhas.items():
            inicio = trilha.get("permanencia_inicio")
            if inicio is None:
                continue
            if trilha.get("reincidente_emitido", False):
                continue

            ultima = trilha.get("ultima_presenca", trilha.get("visto", agora))

            if agora - ultima > perda_s:
                trilha["permanencia_inicio"] = None
                trilha["reincidente_emitido"] = False
                continue

            if agora - trilha.get("visto", agora) > ttl:
                trilha["permanencia_inicio"] = None
                trilha["reincidente_emitido"] = False
                continue

            if trilha.get("lado") != trilha.get("lado_cruzamento"):

                trilha["permanencia_inicio"] = None
                trilha["reincidente_emitido"] = False
                continue

            if agora - inicio < permanencia_s:
                continue

            trilha["reincidente_emitido"] = True
            eventos.append((tid, trilha.get("sentido_cruzado")))

        return eventos


    def diagnostico(self, linha, largura, altura):
        
        diagonal = math.hypot(largura, altura) or 1.0
        g = self._geometria(linha, largura, altura, diagonal)
        if g is None:
            return 0.0, []
        itens = [
            (tid, round(self._dist(t["pe"], g)), t["lado"])
            for tid, t in self.trilhas.items()
            if t["visto"] == self.ultimo_instante
        ]
        return g["margem"], itens


    def visiveis(self):
        return [
            (tid, t["caixa"])
            for tid, t in self.trilhas.items()
            if t["visto"] == self.ultimo_instante
        ]


HUD = {"caixas": [], "poses": [], "ts": 0.0}
CRUZAMENTO = {"id": 0, "ts": 0.0, "hora": None, "sentido": None}



# Seleciona pessoas fora do corte
def indices_area_monitorada(caixas, altura, linha, armado):
    corte = _num(linha.get("zona_topo_pct"), 65, 0, 95) if armado else 0
    limite = altura * corte / 100
    return [i for i, caixa in enumerate(caixas) if caixa[3] >= limite]


def publicar_hud(visiveis, largura, altura, poses=None, idade=0):

    def fracao(valor, total):
        return round(min(max(valor / total, 0.0), 1.0), 4)

    caixas = [
        {
            "id": tid,
            "x1": fracao(caixa[0], largura),
            "y1": fracao(caixa[1], altura),
            "x2": fracao(caixa[2], largura),
            "y2": fracao(caixa[3], altura),
        }
        for tid, caixa in visiveis
    ]
    posesHud = []
    for pose in poses or []:
        pose = dict(pose)
        caixaPose = (
            pose.get("x1", 0),
            pose.get("y1", 0),
            pose.get("x2", 0),
            pose.get("y2", 0),
        )
        centroX = (caixaPose[0] + caixaPose[2]) / 2
        centroY = (caixaPose[1] + caixaPose[3]) / 2
        correspondencias = []
        for caixa in caixas:
            dentro = (
                caixa["x1"] <= centroX <= caixa["x2"]
                and caixa["y1"] <= centroY <= caixa["y2"]
            )
            if dentro:
                area = max(0, caixa["x2"] - caixa["x1"]) * max(
                    0, caixa["y2"] - caixa["y1"]
                )
                correspondencias.append((area, caixa["id"]))
        if correspondencias:
            pose["id"] = min(correspondencias)[1]
        posesHud.append(pose)
    with TRAVA:
        HUD["caixas"] = caixas
        HUD["poses"] = posesHud
        HUD["ts"] = time.time() - max(0, idade)


# Registra cruzamento
def registrar_cruzamento(sentido):
    with TRAVA:
        CRUZAMENTO["id"] += 1
        CRUZAMENTO["ts"] = time.time()
        CRUZAMENTO["hora"] = datetime.now().astimezone().isoformat(timespec="seconds")
        CRUZAMENTO["sentido"] = sentido
    log.info("Linha de segurança cruzada (%s).", sentido)



def estado_hud(leve=False):
    linha = linha_atual()
    estado_camera = estado_atual()
    with TRAVA:
        cruz = dict(CRUZAMENTO)
        caixas = list(HUD["caixas"])
        poses = list(HUD["poses"])
        ts = HUD["ts"]
        conectada = ESTADO["conectada"]
        deteccao_nativa = ESTADO.get("deteccao_nativa", "aguardando detector")
        pessoas = int(estado_camera.get("pessoas", 0) or 0)
        movimento = bool(ESTADO.get("movimento", False))
    cruzamento = None
    if cruz["id"]:
        cruzamento = {
            "id": cruz["id"],
            "hora": cruz["hora"],
            "sentido": cruz["sentido"],
            "idade_s": round(time.time() - cruz["ts"], 1),
        }
    armado = bool(DEFESAS_ARMADAS)
    posicao_ok = bool(estado_camera.get("camera_posicao_validada"))
    referencia_ok = referencia_disponivel()
    linha_ativa = bool(
        armado
        and posicao_ok
        and referencia_ok
        and linha.get("ativa", True)
        and linha.get("definida")
    )
    zona_topo_pct = float(linha.get("zona_topo_pct", 65)) if armado else 0.0
    saida = {
        "ativa": linha["ativa"],
        "linha_ativa": linha_ativa,
        "armado": armado,
        "protocolo_ativo": armado or bool(cfg("SEGURANCA_ATIVA", False)),
        "modo_camera": "fixa" if posicao_ok else "aguardando",
        "zona_topo_pct": zona_topo_pct,
        "referencia_disponivel": referencia_ok,
        "abrir_auto": bool(linha["hud"]["abrir_auto"]),
        "cruzamento": cruzamento,
        "camera_movida": bool(estado_camera.get("camera_movida")),
        "camera_posicao_validada": posicao_ok,
        "deteccao_nativa": deteccao_nativa,
        "pessoas": pessoas,
        "movimento": movimento,
        "poses": poses if time.time() - ts < 1.8 else [],
        "idade_deteccao_s": round(max(0, time.time() - ts), 3) if ts else None,
        "altura": {
            "status": "indisponivel",
            "motivo": "sem calibracao metrica validada",
        },
    }
    if not leve:
        saida["conectada"] = conectada
        saida["caixas"] = caixas if time.time() - ts < 1.8 else []
    return saida




def estado_camera_movida():
    with TRAVA:
        return ESTADO.get("camera_movida", False)


# Consulta estado atual
def estado_atual():
    with TRAVA:
        estado = dict(ESTADO)
    if not estado.get("conectada") or time.monotonic() - float(estado.get("pessoas_ts") or 0) > 1.0:
        estado["pessoas"] = 0
    return estado


# Define defesas armadas
def definir_defesas_armadas(armadas):
    """Define defesas armadas."""
    global DEFESAS_ARMADAS
    DEFESAS_ARMADAS = bool(armadas)



def atualizar(**campos):
    with TRAVA:
        ESTADO.update(campos)


class ControladorONVIF:

    def __init__(self, host, porta, usuario, senha):
        self.host = host
        self.porta = porta
        self.usuario = usuario
        self.senha = senha
        self.comandos_manual = queue.Queue(maxsize=1)
        self.faixas_velocidade = {}
        self.trava_noturno = threading.Lock()
        self.modo_noturno_pendente = None
        self.parar_evento = threading.Event()
        self.thread = threading.Thread(
            target=self.executar, daemon=True, name="mark2-onvif-ptz"
        )
        self.thread.start()


    def enviar(self, noite=None):
        if noite is not None:
            with self.trava_noturno:
                self.modo_noturno_pendente = noite


    def encerrar(self):
        self.parar_evento.set()


    def comando_manual(self, comando, velocidade=0.2, duracao=0.2, timeout=3.0, manter=False):
        if comando not in {
            "left", "right", "up", "down", "zoom_in", "zoom_out", "stop",
        }:
            return False, "Comando PTZ invalido."
        atualizar(
            camera_posicao_validada=False,
            camera_movida=True,
            camera_ptz_movimento_desde=time.monotonic(),
        )
        tarefa = {
            "comando": comando,
            "velocidade": max(0.1, min(1.0, float(velocidade))),
            "duracao": max(0.2, min(1.0, float(duracao))),
            "manter": bool(manter),
            "concluido": threading.Event(),
        }
        # Descarta movimentos antigos: o comando mais recente sempre vence.
        if comando == "stop":
            while True:
                try:
                    antigo = self.comandos_manual.get_nowait()
                    antigo.update(ok=False, mensagem="Comando PTZ substituido.")
                    antigo["concluido"].set()
                except queue.Empty:
                    break
        else:
            while True:
                try:
                    antigo = self.comandos_manual.get_nowait()
                    antigo.update(ok=False, mensagem="Comando PTZ substituido.")
                    antigo["concluido"].set()
                except queue.Empty:
                    break
        self.comandos_manual.put_nowait(tarefa)
        if not tarefa["concluido"].wait(timeout):
            return False, "A camera nao confirmou o comando PTZ a tempo."
        return bool(tarefa.get("ok")), str(
            tarefa.get("mensagem", "Comando PTZ concluido.")
        )


    @staticmethod
    def _velocidade_faixa(faixa, sentido, intensidade):
        if not faixa:
            return None
        minimo, maximo = faixa
        if sentido > 0 and maximo > 0:
            return maximo * intensidade
        if sentido < 0 and minimo < 0:
            return minimo * intensidade
        return None


    def _executar_manual(self, servico_ptz, perfil, tarefa):
        comando = tarefa["comando"]
        if comando == "stop":
            servico_ptz.Stop(
                {"ProfileToken": perfil.token, "PanTilt": True, "Zoom": True}
            )
            tarefa.update(
                ok=True, mensagem="Camera parada; comando confirmado pela ONVIF."
            )
            return
        intensidade = tarefa["velocidade"]
        eixos = {
            "left": ("x", -1), "right": ("x", 1),
            "down": ("y", -1), "up": ("y", 1),
            "zoom_out": ("zoom", -1), "zoom_in": ("zoom", 1),
        }
        eixo, sentido = eixos[comando]
        valor = self._velocidade_faixa(
            self.faixas_velocidade.get(eixo), sentido, intensidade
        )
        if valor is None:
            tarefa.update(
                ok=False,
                mensagem="A camera nao anunciou suporte ONVIF para este movimento.",
            )
            return
        movimento = {}
        if eixo in ("x", "y"):
            movimento["PanTilt"] = {
                "x": valor if eixo == "x" else 0.0,
                "y": valor if eixo == "y" else 0.0,
            }
        else:
            movimento["Zoom"] = {"x": valor}
        argumento = {
            "ProfileToken": perfil.token,
            "Velocity": movimento,
            "Timeout": "PT30S" if tarefa.get("manter") else f"PT{tarefa['duracao']:.1f}S",
        }
        movimento_iniciado = False
        try:
            servico_ptz.ContinuousMove(argumento)
            movimento_iniciado = True
            if not tarefa.get("manter"):
                time.sleep(tarefa["duracao"])
        finally:
            if movimento_iniciado and not tarefa.get("manter"):
                servico_ptz.Stop(
                    {"ProfileToken": perfil.token, "PanTilt": True, "Zoom": True}
                )
        tarefa.update(
            ok=True,
            mensagem=("Movimento PTZ iniciado." if tarefa.get("manter") else "Toque PTZ concluido; camera parada pela ONVIF."),
        )


    def executar(self):
        servico_ptz = None
        servico_imagem = None
        perfil = None
        origem = None
        ultimo_modo = None
        try:
            from onvif import ONVIFCamera
            from zeep.transports import Transport

            transporte = Transport(timeout=5, operation_timeout=5)
            transporte.session.trust_env = False
            camera = ONVIFCamera(
                self.host, self.porta, self.usuario, self.senha,
                transport=transporte,
            )
            media = camera.create_media_service()
            perfis = list(media.GetProfiles())
            perfil = next(
                (item for item in perfis if getattr(item, "PTZConfiguration", None)),
                None,
            )
            if perfil is not None:
                servico_ptz = camera.create_ptz_service()
                try:
                    config_ptz = getattr(perfil, "PTZConfiguration", None)
                    options = servico_ptz.GetConfigurationOptions(
                        {"ConfigurationToken": getattr(config_ptz, "token", None)}
                    )
                    spaces = getattr(options, "Spaces", None)
                    pan_tilt = getattr(spaces, "ContinuousPanTiltVelocitySpace", []) or []
                    zoom = getattr(spaces, "ContinuousZoomVelocitySpace", []) or []
                    if pan_tilt:
                        faixa_x = getattr(pan_tilt[0], "XRange", None)
                        faixa_y = getattr(pan_tilt[0], "YRange", None)
                        if faixa_x:
                            self.faixas_velocidade["x"] = (
                                float(faixa_x.Min), float(faixa_x.Max)
                            )
                        if faixa_y:
                            self.faixas_velocidade["y"] = (
                                float(faixa_y.Min), float(faixa_y.Max)
                            )
                    if zoom:
                        faixa_z = getattr(zoom[0], "XRange", None)
                        if faixa_z:
                            self.faixas_velocidade["zoom"] = (
                                float(faixa_z.Min), float(faixa_z.Max)
                            )
                except Exception:
                    log.info(
                        "A camera nao informou faixas de velocidade ONVIF para o PTZ."
                    )
            try:
                servico_imagem = camera.create_imaging_service()
                configuracao_video = (
                    getattr(perfil, "VideoSourceConfiguration", None)
                    if perfil else None
                )
                origem = getattr(configuracao_video, "SourceToken", None)
                if not origem:
                    fontes = list(media.GetVideoSources())
                    origem = getattr(fontes[0], "token", None) if fontes else None
            except Exception:
                servico_imagem = None
            atualizar(
                ptz_estado=(
                    "conectado" if servico_ptz is not None
                    else "ONVIF conectado, PTZ indisponivel"
                )
            )
            while not self.parar_evento.is_set():
                try:
                    tarefa = self.comandos_manual.get_nowait()
                except queue.Empty:
                    tarefa = None
                if tarefa is not None:
                    try:
                        if servico_ptz is None or perfil is None:
                            tarefa.update(
                                ok=False,
                                mensagem="A camera nao confirmou um perfil PTZ ONVIF.",
                            )
                        else:
                            self._executar_manual(servico_ptz, perfil, tarefa)
                    except Exception as erro:
                        tarefa.update(
                            ok=False,
                            mensagem="A camera recusou o comando PTZ: "
                            + str(erro).splitlines()[0][:120],
                        )
                    finally:
                        tarefa["concluido"].set()
                with self.trava_noturno:
                    noite = self.modo_noturno_pendente
                    self.modo_noturno_pendente = None
                if (
                    noite is not None and noite != ultimo_modo
                    and servico_imagem is not None and origem
                ):
                    try:
                        configuracao = servico_imagem.GetImagingSettings(
                            {"VideoSourceToken": origem}
                        )
                        configuracao.IrCutFilter = "OFF" if noite else "AUTO"
                        servico_imagem.SetImagingSettings({
                            "VideoSourceToken": origem,
                            "ImagingSettings": configuracao,
                            "ForcePersistence": True,
                        })
                        ultimo_modo = noite
                        atualizar(modo_noturno_onvif=(
                            "infravermelho" if noite else "automatico"
                        ))
                    except Exception:
                        servico_imagem = None
                        atualizar(modo_noturno_onvif="indispon?vel")
                self.parar_evento.wait(0.1)
        except Exception as erro:
            mensagem = str(erro).splitlines()[0][:140]
            atualizar(
                ptz_estado="falha na conex?o ONVIF",
                camera_posicao_validada=False,
                camera_movida=True,
                camera_ptz_movimento_desde=time.monotonic(),
            )
            log.warning(
                "N?o foi poss?vel inicializar o controle ONVIF da c?mera: %s", mensagem
            )
            while True:
                try:
                    tarefa = self.comandos_manual.get_nowait()
                except queue.Empty:
                    break
                tarefa.update(
                    ok=False,
                    mensagem="A camera nao confirmou a conexao ONVIF.",
                )
                tarefa["concluido"].set()
        finally:
            if servico_ptz is not None and perfil is not None:
                try:
                    servico_ptz.Stop(
                        {"ProfileToken": perfil.token, "PanTilt": True, "Zoom": True}
                    )
                except Exception:
                    pass



# Configura onvif
def configurar_onvif():
    global PTZ_CONTROLADOR
    with PTZ_TRAVA:
        anterior = PTZ_CONTROLADOR
        PTZ_CONTROLADOR = None
        if anterior is not None:
            anterior.encerrar()
        host = str(cfg("CAMERA_ONVIF_HOST", "")).strip()
        senha = str(cfg("CAMERA_ONVIF_SENHA", ""))
        usuario = str(cfg("CAMERA_ONVIF_USUARIO", "")).strip()
        porta = int(cfg("CAMERA_ONVIF_PORTA", 8899))
        if not host or not usuario or not senha:
            atualizar(ptz_estado="configure host, usuário e senha")
            return False
        atualizar(ptz_estado="conectando")
        PTZ_CONTROLADOR = ControladorONVIF(host, porta, usuario, senha)
        return True


# Envia modo noturno
def enviar_modo_noturno(noite):
    controlador = PTZ_CONTROLADOR
    if controlador is not None:
        controlador.enviar(noite=noite)




def capacidades_ptz():
    controlador = PTZ_CONTROLADOR
    faixas = controlador.faixas_velocidade if controlador is not None else {}
    return {
        "stop": controlador is not None
        and estado_atual().get("ptz_estado") == "conectado",
        "left": bool(
            ControladorONVIF._velocidade_faixa(faixas.get("x"), -1, 0.5) is not None
        ),
        "right": bool(
            ControladorONVIF._velocidade_faixa(faixas.get("x"), 1, 0.5) is not None
        ),
        "up": bool(
            ControladorONVIF._velocidade_faixa(faixas.get("y"), 1, 0.5) is not None
        ),
        "down": bool(
            ControladorONVIF._velocidade_faixa(faixas.get("y"), -1, 0.5) is not None
        ),
        "zoom_in": bool(
            ControladorONVIF._velocidade_faixa(faixas.get("zoom"), 1, 0.5) is not None
        ),
        "zoom_out": bool(
            ControladorONVIF._velocidade_faixa(faixas.get("zoom"), -1, 0.5) is not None
        ),
    }


# Controla PTZ
def controlar_ptz(comando, velocidade=0.35, duracao=0.5, manter=False):
    controlador = PTZ_CONTROLADOR
    if controlador is None:
        return False, "Salve as credenciais ONVIF antes de comandar a câmera."
    return controlador.comando_manual(comando, velocidade, duracao, manter=manter)



def ultimo_quadro():
    with TRAVA:
        return None if quadro_atual is None else quadro_atual.copy()



def quadro_recente(max_idade=3.0):
    with TRAVA:
        if quadro_atual is None or time.monotonic() - quadro_atual_hora > max_idade:
            return None
        return quadro_atual.copy()


# Guarda quadro
def guardar_quadro(quadro):
    global quadro_atual, quadro_atual_hora
    with TRAVA:
        quadro_atual = quadro
        quadro_atual_hora = time.monotonic()
    altura, largura = quadro.shape[:2]
    atualizar(resolucao=f"{largura} x {altura}")



def quadro_base64(quadro):
    imagem = visao.Image.fromarray(cv2.cvtColor(quadro, cv2.COLOR_BGR2RGB))
    return visao.codificar_jpeg(imagem)



def quadro_jpeg(largura_max=960, qualidade=80, mostrarIA=False, mostrarZonas=False):
    
    quadro = ultimo_quadro()
    if quadro is None or cv2 is None:
        return None
    altura, largura = quadro.shape[:2]
    if largura > largura_max:
        quadro = cv2.resize(
            quadro,
            (largura_max, int(altura * largura_max / largura)),
            interpolation=cv2.INTER_AREA,
        )
    try:
        quadro = equilibrar_brilho(quadro)
    except Exception:
        pass
    if (mostrarIA or mostrarZonas) and np is not None:
        altura, largura = quadro.shape[:2]
        estado = estado_hud()
        if mostrarIA:
            for caixa in estado.get("caixas", []):
                x1 = int(caixa["x1"] * largura)
                y1 = int(caixa["y1"] * altura)
                x2 = int(caixa["x2"] * largura)
                y2 = int(caixa["y2"] * altura)
                cv2.rectangle(quadro, (x1, y1), (x2, y2), (0, 220, 255), 2)
        if mostrarZonas:
            for zona in zonasCamera.listarZonas():
                if not zona["active"]:
                    continue
                pontos = [
                    (int(x * largura), int(y * altura)) for x, y in zona["points"]
                ]
                poligono = np.array(pontos, dtype=np.int32).reshape((-1, 1, 2))
                cv2.polylines(quadro, [poligono], True, (255, 190, 70), 2, cv2.LINE_AA)
                cv2.putText(
                    quadro,
                    zona["name"],
                    pontos[0],
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (255, 210, 110),
                    2,
                    cv2.LINE_AA,
                )
    ok, buf = cv2.imencode(".jpg", quadro, [cv2.IMWRITE_JPEG_QUALITY, qualidade])
    return buf.tobytes() if ok else None



def analisar_a28(pergunta=None):
    quadro = ultimo_quadro()
    if quadro is None:
        return "Senhor, a câmera A28 não está transmitindo no momento."
    if medir_brilho(quadro) <= float(cfg("VIGIA_LIMIAR_NOITE", 70)):
        quadro = realcar_noite(quadro)
    resultado = llm_local.chamar_visao(
        pergunta or visao.PROMPT_PADRAO_CAMERA, quadro_base64(quadro)
    )
    if resultado is None:
        return visao.falha("link", llm_local.ultimo_erro())
    return resultado


# Salva foto e dispara aviso armado
def alertar(
    quadro,
    caixas,
    quantidade,
    origem="deteccao",
    sentido=None,
    reincidente=False,
):
    try:

        foto = equilibrar_brilho(quadro)
        if cfg("VIGIA_FOTO_CAIXAS", False):
            for x1, y1, x2, y2 in caixas:
                cv2.rectangle(foto, (x1, y1), (x2, y2), (0, 255, 0), 2)

        PASTA_ALERTAS.mkdir(parents=True, exist_ok=True)
        prefixo = "linha" if origem == "linha" else "pessoa"
        caminho = PASTA_ALERTAS / f"{prefixo}_{datetime.now():%Y%m%d_%H%M%S_%f}.jpg"
        salvar_foto_maxima(foto, caminho)
        gravar_evento(caminho, quantidade)
        limpar_fotos_antigas()
        atualizar(
            ultimo_alerta=datetime.now().astimezone().isoformat(timespec="seconds"),
            ultima_foto=str(caminho),
        )

        n = quantidade
        if CALLBACK is not None:
            CALLBACK(
                str(caminho),
                n,
                origem=origem,
                sentido=sentido,
                reincidente=reincidente,
            )
            return

        if not DEFESAS_ARMADAS:
            return
        if origem == "linha":
            voz.falar("Senhor, a linha de segurança foi cruzada.")
        else:
            voz.falar(
                "Senhor, detectei uma pessoa no campo da câmera A28."
                if n == 1
                else f"Senhor, detectei {n} pessoas no campo da câmera A28."
            )
        if cfg("VIGIA_DESCREVER", True):
            descricao = llm_local.chamar_visao(
                "Descreva em no máximo duas frases a pessoa que aparece nesta "
                "imagem: roupa, o que está fazendo e onde está. Não tente "
                "identificar quem é.",
                quadro_base64(foto),
                max_tokens=200,
            )
            if descricao:
                voz.falar(descricao)
    except Exception:
        log.exception("Falha ao processar o alerta de pessoa.")


# Mede movimento
def medir_movimento(quadro, anterior, limiar_pix, limiar_frac):
    altura, largura = quadro.shape[:2]
    pequeno = cv2.resize(
        quadro,
        (160, max(8, int(altura * 160 / largura))),
        interpolation=cv2.INTER_AREA,
    )
    cinza = cv2.GaussianBlur(cv2.cvtColor(pequeno, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    if anterior is None or anterior.shape != cinza.shape:
        return cinza, True
    fracao = float((cv2.absdiff(cinza, anterior) > limiar_pix).mean())
    return cinza, fracao >= limiar_frac


# Abre camera
def abrir_camera(url):
    captura = cv2.VideoCapture(url, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
    if captura.isOpened():
        captura.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return captura
    captura.release()
    return None



def localizar_ffmpeg():
    candidatos = [
        getattr(config, "FFMPEG_EXE", ""),
        str(config.BASE_DIR / "go2rtc" / "ffmpeg.exe"),
        shutil.which("ffmpeg"),
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ]
    go2rtc = Path(str(getattr(config, "GO2RTC_EXE", "") or ""))
    arquivo_config = go2rtc.parent / "go2rtc.yaml" if str(go2rtc) else None
    if arquivo_config and arquivo_config.is_file():
        try:
            dentro_ffmpeg = False
            for linha in arquivo_config.read_text(encoding="utf-8-sig").splitlines():
                if re.match(r"^ffmpeg\s*:", linha):
                    dentro_ffmpeg = True
                    continue
                if dentro_ffmpeg and linha and not linha[0].isspace():
                    break
                if dentro_ffmpeg:
                    encontrado = re.match(r'\s+bin:\s*["\']?(.*?)["\']?\s*$', linha)
                    if encontrado:
                        candidatos.insert(0, encontrado.group(1))
                        break
        except OSError:
            pass
    for candidato in candidatos:
        if not candidato:
            continue
        caminho = shutil.which(str(candidato)) or str(candidato)
        if Path(caminho).is_file():
            return caminho
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return None


# Grava clipe da deteccao
EVENTOS_VIDEO = {}
EVENTOS_VIDEO_TRAVA = threading.Lock()

GRAVADOR_EVENTOS = None

# Inicia o buffer contínuo no disco
def iniciar_buffer_eventos():
    global GRAVADOR_EVENTOS
    with EVENTOS_VIDEO_TRAVA:
        if GRAVADOR_EVENTOS is not None and not GRAVADOR_EVENTOS.parada.is_set():
            return GRAVADOR_EVENTOS
        from comandos.automacao.gravacao_eventos import GravadorEventos
        filtros = ""
        if cfg("VIGIA_DUAS_LENTES", False):
            divisao = max(.05, min(.95, float(cfg("VIGIA_DIVISAO_Y", .5))))
            filtros = f"crop=iw:trunc(ih*{1-divisao}/2)*2:0:trunc(ih*{divisao}/2)*2"
        GRAVADOR_EVENTOS = GravadorEventos(PASTA_ALERTAS, localizar_ffmpeg(),
            str(cfg("CAMERA_A28_URL", "")).strip(), filtros=filtros).iniciar()
        return GRAVADOR_EVENTOS

# Associa a foto ao recorte futuro
def gravar_evento(caminho_foto, quantidade=1):
    return iniciar_buffer_eventos().registrar(caminho_foto, quantidade=quantidade)



def gravacao_atual():
    with GRAVACAO_TRAVA:
        return GRAVACAO_ATUAL


# Prepara vídeo sem reter quadro HD
def preparar_quadro_gravacao(quadro):
    altura, largura = quadro.shape[:2]
    escala = min(1.0, 640 / max(1, largura))
    tamanho = (max(2, int(largura * escala) // 2 * 2), max(2, int(altura * escala) // 2 * 2))
    if (largura, altura) == tamanho:
        return quadro.copy()
    return cv2.resize(quadro, tamanho, interpolation=cv2.INTER_AREA)


# Inicia gravacao video
def iniciar_gravacao_video(caminho, tamanho, quadros_previos):
    global GRAVACAO_ATUAL
    ffmpeg = localizar_ffmpeg()
    url = str(cfg("CAMERA_A28_URL", "")).strip()
    if not ffmpeg or not url:
        raise RuntimeError("FFmpeg ou fluxo da câmera indisponível.")
    largura, altura = tamanho
    anteriores = [quadro for _, quadro in quadros_previos]
    atraso_audio = len(anteriores) / 5.0
    argumentos = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-thread_queue_size",
        "256",
        "-f",
        "rawvideo",
        "-pixel_format",
        "bgr24",
        "-video_size",
        f"{largura}x{altura}",
        "-framerate",
        "5",
        "-i",
        "pipe:0",
        "-itsoffset",
        f"{atraso_audio:.3f}",
        "-rtsp_transport",
        "tcp",
        "-thread_queue_size",
        "256",
        "-i",
        url,
        "-map",
        "0:v:0",
        "-map",
        "1:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "24",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "5",
        "-g",
        "25",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-ar",
        "16000",
        "-shortest",
        "-movflags",
        "+faststart",
        str(caminho),
    ]
    processo = subprocess.Popen(
        argumentos,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    with GRAVACAO_TRAVA:
        GRAVACAO_ATUAL = caminho
    try:
        for quadro in anteriores:
            reduzido = (
                cv2.resize(quadro, tamanho, interpolation=cv2.INTER_AREA)
                if (quadro.shape[1], quadro.shape[0]) != tamanho
                else quadro
            )
            processo.stdin.write(reduzido.tobytes())
    except (BrokenPipeError, OSError):
        fechar_gravacao_video(processo)
        raise RuntimeError("FFmpeg encerrou antes de iniciar a gravação.")
    return processo


# Escreve gravacao video
def escrever_gravacao_video(processo, quadro, tamanho):
    if processo is None or processo.poll() is not None or processo.stdin is None:
        return False
    reduzido = (
        cv2.resize(quadro, tamanho, interpolation=cv2.INTER_AREA)
        if (quadro.shape[1], quadro.shape[0]) != tamanho
        else quadro
    )
    try:
        processo.stdin.write(reduzido.tobytes())
        return True
    except (BrokenPipeError, OSError):
        return False


# Fecha gravacao video
def fechar_gravacao_video(processo):
    global GRAVACAO_ATUAL
    if processo is None:
        return
    caminho = gravacao_atual()
    try:
        if processo.stdin and not processo.stdin.closed:
            processo.stdin.close()
        processo.wait(timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        try:
            processo.terminate()
            processo.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            processo.kill()
            processo.wait(timeout=3)
    finally:
        with GRAVACAO_TRAVA:
            if GRAVACAO_ATUAL == caminho:
                GRAVACAO_ATUAL = None
        if caminho and Path(caminho).is_file():
            try:
                if Path(caminho).stat().st_size < 32768:
                    Path(caminho).unlink(missing_ok=True)
            except OSError:
                pass


# Monitora area protegida


# Mantém o serviço em execução
def laco():
    url = str(cfg("CAMERA_A28_URL", "")).strip()
    intervalo = 1.0 / max(1.0, min(60.0, float(cfg("VIGIA_FPS_ALVO", 60))))
    intervalo_linha = float(cfg("VIGIA_LINHA_INTERVALO_S", 0.4))
    limiar_noite = float(cfg("VIGIA_LIMIAR_NOITE", 70))
    cooldown = float(cfg("VIGIA_COOLDOWN_S", 60))
    so_ausente = bool(cfg("VIGIA_SOMENTE_AUSENTE", False))
    consecutivas_min = max(3, int(cfg("VIGIA_CONSECUTIVAS", 3)))
    sumiu_apos = 10.0
    mov_pix = float(cfg("VIGIA_MOV_LIMIAR_PIX", 18))
    mov_frac = float(cfg("VIGIA_MOV_LIMIAR_FRAC", 0.004))
    gravador = None
    inicio_gravacao = 0.0
    proxima_gravacao = 0.0
    proxima_tentativa_gravacao = 0.0
    pessoa_confirmada_ate = 0.0
    quadros_pregrava = deque(maxlen=max(1, int(cfg("VIGIA_PREGRAVACAO_S", 5) * 5)))
    movimento_ate = 0.0
    movimento_consecutivo = 0
    proxima_amostra_movimento = 0.0
    ultima_foto_movimento = -1e9
    posicao_estavel_desde = None
    modo_noite_enviado = None
    ultimo_quadro_pregravado = None
    cinza_mov_anterior = None
    tamanho = None

    rastreador = Rastreador()
    captura = None
    falhas = 0
    proxima_analise = 0.0
    consecutivas = 0
    ultima_pose_pronta = 0.0
    ultima_sequencia_pose = None
    contexto_deteccao_anterior = None
    pessoa_no_quadro = False
    ultima_vez_visto = 0.0
    ultimo_alerta = -cooldown
    quantidade_alertada = 0
    ultimo_alerta_linha = -1e9
    armado_anterior = False
    ultimo_aviso_posicao = -float("inf")

    while not PARAR.is_set():
        if captura is None:
            captura = abrir_camera(url)
            if captura is None:
                posicao_estavel_desde = None
                atualizar(
                    conectada=False, camera_posicao_validada=False,
                    pessoas=0,
                )
                movimento_consecutivo = 0
                consecutivas = 0
                rastreador.trilhas.clear()
                quadros_pregrava.clear()
                falhas += 1
                log.warning("Sem conexão com a A28 (%s).", url_mascarada(url))
                PARAR.wait(min(15, 3 * falhas))
                continue
            falhas = 0
            atualizar(conectada=True)
            log.info("Conectado à câmera A28.")

        if not captura.grab():
            captura.release()
            captura = None
            cinza_mov_anterior = None
            movimento_consecutivo = 0
            consecutivas = 0
            rastreador.trilhas.clear()
            quadros_pregrava.clear()
            if gravador is not None:
                fechar_gravacao_video(gravador)
                gravador = None
            posicao_estavel_desde = None
            atualizar(
                conectada=False, camera_posicao_validada=False,
                pessoas=0, )
            log.warning("Stream da A28 caiu; reconectando.")
            continue

        agora = time.monotonic()
        if agora >= movimento_ate and estado_atual().get("movimento"):
            atualizar(movimento=False)
        if gravador is not None and gravador.poll() is not None:
            fechar_gravacao_video(gravador)
            gravador = None
            proxima_tentativa_gravacao = agora + 30
            log.warning(
                "A gravação da A28 foi encerrada pelo FFmpeg; nova tentativa em 30 segundos."
            )
        # Buffer substitui vídeo de movimento
        gravar_video = False
        if not gravar_video:
            quadros_pregrava.clear()
        armado_agora = bool(DEFESAS_ARMADAS)
        if armado_agora and not armado_anterior:
            pessoa_no_quadro = False
            ultima_vez_visto = 0.0
            ultimo_alerta = -cooldown
            consecutivas = 0
            rastreador.trilhas.clear()
        armado_anterior = armado_agora
        # Mantém observação silenciosa
        detectar_ativo = True
        analisar_agora = detectar_ativo and agora >= proxima_analise
        amostrar_movimento = gravar_video and agora >= proxima_amostra_movimento
        mexeu = False
        if (not gravar_video or agora >= movimento_ate) and gravador is not None:
            fechar_gravacao_video(gravador)
            gravador = None
            tamanho = None
            atualizar(movimento=False)
            limpar_fotos_antigas()
        if analisar_agora:
            linha = linha_atual()
            linha_ativa = bool(
                linha.get("ativa", True)
                and linha["definida"]
                and DEFESAS_ARMADAS
                and estado_atual().get("camera_posicao_validada", False)
            )
            proxima_analise = agora + (
                min(intervalo, intervalo_linha) if DEFESAS_ARMADAS else intervalo
            )
        if not analisar_agora and not amostrar_movimento and gravador is None:
            PARAR.wait(min(0.01, intervalo))
            continue
        ok, quadro = captura.retrieve()
        if not ok or quadro is None:
            if time.monotonic() - quadro_atual_hora > 2.0:
                atualizar(
                    camera_posicao_validada=False,
                )
            continue
        quadro = recortar_lente(quadro)
        guardar_quadro(quadro)
        linha = linha_atual()
        posicao_validada = False
        camera_movida = False
        mdx = mdy = 0.0
        movimento_ptz_desde = float(
            estado_atual().get("camera_ptz_movimento_desde") or 0.0
        )
        if movimento_ptz_desde and agora - movimento_ptz_desde < 3.0:
            camera_movida = True
            posicao_estavel_desde = None
        else:
            try:
                resultado_movimento, mdx, mdy = camera_deslocada(quadro)
                if resultado_movimento is None:
                    posicao_estavel_desde = None
                elif resultado_movimento:
                    camera_movida = True
                    posicao_estavel_desde = None
                else:
                    if posicao_estavel_desde is None:
                        posicao_estavel_desde = agora
                    posicao_validada = agora - posicao_estavel_desde >= 3.0
            except Exception:
                posicao_estavel_desde = None
                camera_movida = True
        estado_anterior = estado_atual()
        if (
            estado_anterior.get("camera_movida") != camera_movida
            or estado_anterior.get("camera_posicao_validada") != posicao_validada
        ):
            atualizar(
                camera_movida=camera_movida,
                camera_posicao_validada=posicao_validada,
            )
            if camera_movida and agora-ultimo_aviso_posicao>=60:
                ultimo_aviso_posicao=agora
                log.warning(
                    "A28 fora da posicao fixa validada ou em movimento; linha suspensa."
                )
            elif posicao_validada:
                log.info("Posição da A28 estável; linha liberada.")
        linha_ativa = bool(
            linha.get("ativa", True)
            and linha.get("definida")
            and DEFESAS_ARMADAS
            and posicao_validada
        )
        atualizar(camera_posicao_validada=posicao_validada, camera_movida=camera_movida)
        contexto_deteccao = (DEFESAS_ARMADAS, posicao_validada)
        if contexto_deteccao != contexto_deteccao_anterior:
            contexto_deteccao_anterior = contexto_deteccao
            consecutivas = 0
            ultima_pose_pronta = 0.0
            rastreador.trilhas.clear()
        if detectar_ativo:
            visao_inteligente.submeter(quadro)
        evento_movimento = False
        brilho = medir_brilho(quadro)
        if amostrar_movimento:
            proxima_amostra_movimento = agora + 0.2
            cinza_mov, mexeu = medir_movimento(
                quadro, cinza_mov_anterior, mov_pix, mov_frac
            )
            brilho = float(cinza_mov.mean())
            if cinza_mov_anterior is None:
                mexeu = False
            cinza_mov_anterior = cinza_mov
            quadros_pregrava.append((agora, preparar_quadro_gravacao(quadro)))
            movimento_consecutivo = movimento_consecutivo + 1 if mexeu else 0
            if movimento_consecutivo >= 2:
                evento_movimento = True
                movimento_ate = agora + float(cfg("VIGIA_POSGRAVACAO_S", 15))
                atualizar(
                    movimento=True,
                    ultimo_movimento=datetime.now()
                    .astimezone()
                    .isoformat(timespec="seconds"),
                )
                if agora - ultima_foto_movimento >= 4:
                    try:
                        PASTA_ALERTAS.mkdir(parents=True, exist_ok=True)
                        nome_foto = f"movimento_{datetime.now():%Y%m%d_%H%M%S_%f}.jpg"
                        caminho_foto = PASTA_ALERTAS / nome_foto
                        salvar_foto_maxima(
                            equilibrar_brilho(quadro.copy()), caminho_foto
                        )
                        atualizar(ultima_foto=str(caminho_foto))
                        ultima_foto_movimento = agora
                    except Exception:
                        log.warning(
                            "Nao foi possivel salvar a foto de movimento da A28.",
                            exc_info=True,
                        )
                if (
                    gravador is None or agora - inicio_gravacao >= 300
                ) and agora >= proxima_tentativa_gravacao:
                    try:
                        if gravador is not None:
                            fechar_gravacao_video(gravador)
                            gravador = None
                        PASTA_ALERTAS.mkdir(parents=True, exist_ok=True)
                        altura, largura = quadro.shape[:2]
                        escala = min(1.0, 640 / max(1, largura))
                        tamanho = (
                            max(2, int(largura * escala) // 2 * 2),
                            max(2, int(altura * escala) // 2 * 2),
                        )
                        nome_video = f"gravacao_{datetime.now():%Y%m%d_%H%M%S_%f}.mp4"
                        caminho_video = PASTA_ALERTAS / nome_video
                        try:
                            gravador = iniciar_gravacao_video(
                                caminho_video, tamanho, list(quadros_pregrava)
                            )
                        except Exception:
                            gravador = None
                            caminho_video.unlink(missing_ok=True)
                            proxima_tentativa_gravacao = agora + 30
                            log.warning(
                                "Nao foi possivel iniciar a gravacao H.264 com audio da A28.",
                                exc_info=True,
                            )
                        else:
                            inicio_gravacao = agora
                            proxima_tentativa_gravacao = 0.0
                            ultimo_quadro_pregravado = agora
                            limpar_fotos_antigas()
                    except Exception:
                        log.warning(
                            "Nao foi possivel preparar a gravacao de movimento da A28.",
                            exc_info=True,
                        )
        gravar_agora = gravar_video and gravador is not None and agora < movimento_ate
        if gravar_agora and amostrar_movimento and ultimo_quadro_pregravado != agora:
            if not escrever_gravacao_video(gravador, quadro, tamanho):
                fechar_gravacao_video(gravador)
                gravador = None
                proxima_tentativa_gravacao = agora + 30
                log.warning(
                    "A gravação H.264 da A28 foi interrompida; nova tentativa em 30 segundos."
                )
            ultimo_quadro_pregravado = agora
        if not detectar_ativo and evento_movimento and agora >= proxima_analise:
            analisar_agora = True
            linha = linha_atual()
            linha_ativa = False
            proxima_analise = agora + intervalo
        modo_noite_atual = brilho <= limiar_noite
        if modo_noite_enviado != modo_noite_atual:
            modo_noite_enviado = modo_noite_atual
            enviar_modo_noturno(modo_noite_enviado)

        if not analisar_agora:
            continue
        if so_ausente and not DEFESAS_ARMADAS and presenca.estado_atual().get("estado") != "ausente":
            consecutivas = 0
            pessoa_no_quadro = False
            atualizar(pessoas=0)
            continue

        noite = brilho <= limiar_noite
        atualizar(noite=noite)
        if analisar_agora:
            resultado_pose = visao_inteligente.obterPose()
            pose_pronta = bool(resultado_pose.get("pronto"))
            if pose_pronta:
                quadro_pose_ts = float(resultado_pose.get("quadro_ts") or 0.0)
                movimento_ptz_desde = float(
                    estado_atual().get("camera_ptz_movimento_desde") or 0.0
                )
                pose_pronta = bool(quadro_pose_ts > 0 and quadro_pose_ts >= movimento_ptz_desde)
            poses_candidatas = list(resultado_pose.get("poses", [])) if pose_pronta else []
            if pose_pronta:
                resultado_pose = dict(resultado_pose, poses=[p for p in poses_candidatas if p.get("confirmada", True)])
                altura_pose, largura_pose = quadro.shape[:2]
                caixas = [
                    [
                        int(pose["x1"] * largura_pose),
                        int(pose["y1"] * altura_pose),
                        int(pose["x2"] * largura_pose),
                        int(pose["y2"] * altura_pose),
                    ]
                    for pose in resultado_pose.get("poses", [])
                ]
                fonte_deteccao = "YOLO11-Pose"
                sequencia_pose = resultado_pose.get("sequencia")
                quadro_pose_novo = (
                    sequencia_pose is None or sequencia_pose != ultima_sequencia_pose
                )
                if sequencia_pose is not None:
                    ultima_sequencia_pose = sequencia_pose
            else:
                caixas = detectar_caixas_camera(quadro)
                fonte_deteccao = "detector nativo da camera"
                quadro_pose_novo = True
            zona_topo_pct = (
                float(linha.get("zona_topo_pct", 65)) if DEFESAS_ARMADAS else 0.0
            )
            total_caixas = len(caixas)
            indices = indices_area_monitorada(caixas, quadro.shape[0], linha, DEFESAS_ARMADAS)
            caixas = [caixas[i] for i in indices]
            poses_monitoradas = [resultado_pose["poses"][i] for i in indices] if pose_pronta else []
            descartadas_topo = total_caixas - len(caixas)
            caixas_presentes = list(caixas)
            quantidade = len(caixas_presentes)
            if pose_pronta and quadro_pose_novo and GRAVADOR_EVENTOS is not None:
                GRAVADOR_EVENTOS.presenca(quantidade)
            if pose_pronta:
                ultima_pose_pronta = agora
                if not caixas:
                    consecutivas = 0
                elif quadro_pose_novo:
                    consecutivas += 1
            elif agora - ultima_pose_pronta > TOLERANCIA_POSE_S:
                # Uma pose atrasada isolada não apaga
                consecutivas = 0
            if caixas:
                ultima_vez_visto = agora
            atualizar(
                pessoas=quantidade if pose_pronta else 0,
                pessoas_ts=float(resultado_pose.get("quadro_ts") or 0.0) if pose_pronta else 0.0,
                deteccoes_incertas=sum(not p.get("confirmada", True) for p in poses_candidatas) if pose_pronta else quantidade,
                deteccao_nativa=(
                    f"{quantidade} pessoa(s) confirmada(s) por {fonte_deteccao}"
                    if caixas_presentes and pose_pronta
                    else (
                        f"{quantidade} retangulo(s) nativo(s), sem confirmacao de pessoa pela IA"
                        if caixas
                        else (
                            f"{descartadas_topo} pessoa(s) acima do corte de {zona_topo_pct:.0f}% da imagem"
                            if descartadas_topo
                            else f"{fonte_deteccao} aguardando pessoa"
                        )
                    )
                ),
            )
            altura_q, largura_q = quadro.shape[:2]
            pausada = bool(DEFESAS_ARMADAS and not linha_ativa)

            if pose_pronta and quadro_pose_novo and DEFESAS_ARMADAS and linha_ativa:
                # Avalia também sem caixas: é assim
                # e fica livre para a próxima entrada
                eventos_zona = zonasCamera.avaliarZonas(
                    caixas, largura_q, altura_q, agora
                )
                for evento_zona in eventos_zona:
                    if (
                        evento_zona.get("alertAllowed")
                        and evento_zona.get("event") in ("entry", "dwell")
                        and consecutivas >= consecutivas_min
                    ):
                        pessoa_no_quadro = True
                        quantidade_alertada = quantidade
                        ultimo_alerta = agora
                        threading.Thread(
                            target=alertar,
                            args=(
                                quadro.copy(),
                                caixas,
                                int(evento_zona.get("persons") or 1),
                            ),
                            kwargs={
                                "origem": "zona",
                                "reincidente": evento_zona.get("event") == "dwell",
                            },
                            daemon=True,
                            name="mark2-vigia-zona",
                        ).start()
            cruzamentos = rastreador.atualizar(
                caixas_presentes if pose_pronta else [],
                agora,
                largura_q,
                altura_q,
                linha if (pose_pronta and linha_ativa and not pausada) else None,
            )
            publicar_hud(
                [item for item in rastreador.visiveis() if indices_area_monitorada([item[1]], altura_q, linha, DEFESAS_ARMADAS)] if pose_pronta else [],
                largura_q,
                altura_q,
                poses_candidatas,
                max(0, time.monotonic() - float(resultado_pose.get("quadro_ts") or time.monotonic())),
            )
            if (
                pose_pronta
                and cruzamentos
                and consecutivas >= consecutivas_min
                and agora - ultimo_alerta_linha >= float(linha.get("cooldown_s", 5))
            ):
                ultimo_alerta_linha = agora
                sentido = cruzamentos[0]
                registrar_cruzamento(sentido)
                pessoa_no_quadro = True
                quantidade_alertada = quantidade
                ultimo_alerta = agora
                threading.Thread(
                    target=alertar,
                    args=(quadro.copy(), caixas, quantidade),
                    kwargs={
                        "origem": "linha",
                        "sentido": sentido,
                        "reincidente": False,
                    },
                    daemon=True,
                    name="mark2-vigia-linha",
                ).start()
            if (
                pose_pronta
                and caixas
                and consecutivas >= consecutivas_min
                and detectar_ativo
                and (not pessoa_no_quadro or quantidade > quantidade_alertada
                     or (GRAVADOR_EVENTOS is not None and GRAVADOR_EVENTOS.ativo is None))
                and agora - ultimo_alerta >= (2 if GRAVADOR_EVENTOS is not None and GRAVADOR_EVENTOS.ativo is None else 5)
            ):
                pessoa_no_quadro = True
                quantidade_alertada = quantidade
                ultimo_alerta = agora
                threading.Thread(
                    target=alertar,
                    args=(quadro.copy(), caixas, quantidade),
                    kwargs={"origem": "vigia"},
                    daemon=True,
                    name="mark2-vigia-alerta",
                ).start()
                quantidade_alertada = quantidade
            if not caixas:
                if pessoa_no_quadro and agora - ultima_vez_visto >= sumiu_apos:
                    pessoa_no_quadro = False
    if captura is not None:
        captura.release()
    if gravador is not None:
        fechar_gravacao_video(gravador)
    limpar_fotos_antigas()
    atualizar(ativo=False, conectada=False)



def iniciar(callback=None):
    global THREAD, CALLBACK
    CALLBACK = callback
    if cv2 is None or visao.Image is None:
        log.error("Instale: pip install opencv-python pillow numpy")
        return None
    if not (
        cfg("VIGIA_ATIVO", False) or cfg("VIGIA_GRAVAR_VIDEO", True) or DEFESAS_ARMADAS
    ):
        log.info("Vigia da câmera A28 desativado em config.")
        return None
    if not str(cfg("CAMERA_A28_URL", "")).strip():
        log.info("Vigia inativo: defina camera_a28_url nas configurações locais.")
        return None

    limpar_fotos_antigas()
    visao_inteligente.iniciar()
    iniciar_buffer_eventos()
    if (
        cfg("CAMERA_ONVIF_HOST", "")
        and cfg("CAMERA_ONVIF_USUARIO", "")
        and cfg("CAMERA_ONVIF_SENHA", "")
    ):
        configurar_onvif()
    with TRAVA:
        if THREAD is not None and THREAD.is_alive():
            return THREAD
        PARAR.clear()
        THREAD = threading.Thread(target=laco, daemon=True, name="mark2-vigia")
        ESTADO["ativo"] = True
        THREAD.start()
    log.info("Vigia da câmera A28 ativo.")
    return THREAD



def parar():
    PARAR.set()
    if GRAVADOR_EVENTOS is not None:
        GRAVADOR_EVENTOS.parar()
    visao_inteligente.parar()