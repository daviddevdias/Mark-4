import io
import json
import logging
import random
import threading
import time
import urllib.parse
import urllib.request
import wave
from array import array

import config
from interface import voz

log = logging.getLogger("mark2.fala_camera")

PASTA_AUDIO = config.DATA_DIR / "fala_camera"

TRAVA = threading.Lock()

cache_go2rtc = {"hora": -100.0, "ok": False}

FALAS_AVISO = (
    "Aten\u00e7\u00e3o. \u00c1rea restrita. As defesas est\u00e3o armadas. Afaste-se e identifique-se.",
    "Aten\u00e7\u00e3o. Esta entrada \u00e9 uma \u00e1rea restrita monitorada. Por favor, afaste-se.",
)

FALAS_REINCIDENTE = (
    "\u00c1rea restrita. Sua presen\u00e7a continua sendo detectada. Afaste-se imediatamente.",
    "\u00c1rea restrita. A ocorr\u00eancia est\u00e1 sendo registrada. Afaste-se, por favor.",
)

FALAS_PREDEFINIDAS = {
    "Indisponível": "O senhor {nome} não está disponível no momento.",
    "Deixe recado": "O senhor {nome} não está disponível. Se desejar, deixe seu recado após o sinal.",
    "Aguarde": "Por favor, aguarde. Sua solicitação está sendo processada.",
    "Identifique-se": "Por segurança, informe seu nome e o motivo da visita.",
    "Encomenda": "Encomenda detectada. Por favor, deixe-a no local indicado. Obrigado.",
    "Área monitorada": "Atenção. Esta residência encontra-se sob monitoramento por vídeo. Identifique-se.",
    "Obrigado": "Obrigado pela visita. Tenha um excelente dia.",
    "Saudação": "Bom dia. Em que posso ajudá-lo?",
    "Quem é": "Por favor, informe seu nome e o motivo da visita.",
    "Entrada": "A entrada está sendo monitorada. Aguarde instruções.",
    "Aguarde identificação": "Um momento, por favor. Sua identificação está sendo verificada.",
    "Encerrar": "Agradeço pela colaboração. Tenha um bom dia.",
}


# Consulta opção de configuração
def cfg(nome, padrao):
    return getattr(config, nome, padrao)



def url_api(caminho):
    base = str(cfg("GO2RTC_URL", "http://127.0.0.1:1984")).rstrip("/")
    stream = str(cfg("GO2RTC_STREAM", "a28_voz"))
    origem = f"ffmpeg:{caminho.as_posix()}#audio=pcma#input=file"
    return (
        f"{base}/api/streams?dst={urllib.parse.quote(stream, safe='')}"
        f"&src={urllib.parse.quote(origem, safe=':/')}"
    )


# Prepara áudio
def preparar_audio(audio):
    ganho = float(cfg("CAMERA_FALA_GANHO", 3.0))
    if ganho <= 1.0:
        return audio
    try:
        import numpy as np

        with wave.open(io.BytesIO(audio), "rb") as entrada:
            canais = entrada.getnchannels()
            largura = entrada.getsampwidth()
            taxa = entrada.getframerate()
            bruto = entrada.readframes(entrada.getnframes())
        if largura != 2:
            return audio

        amostras = np.frombuffer(bruto, dtype="<i2").astype(np.float32) / 32768.0
        pico = float(np.max(np.abs(amostras))) if amostras.size else 0.0
        if pico <= 0.0:
            return audio

        amostras = amostras / pico
        amostras = np.tanh(ganho * amostras) / np.tanh(ganho)
        saida_i16 = (amostras * 0.98 * 32767.0).astype("<i2")

        saida = io.BytesIO()
        with wave.open(saida, "wb") as arquivo:
            arquivo.setnchannels(canais)
            arquivo.setsampwidth(2)
            arquivo.setframerate(taxa)
            arquivo.writeframes(saida_i16.tobytes())
        return saida.getvalue()
    except Exception:
        log.warning(
            "Não consegui amplificar o áudio; usando o original.", exc_info=True
        )
        return audio


ARQ_VOLUME = config.DATA_DIR / "volume_camera.json"
VOLUME_MINIMO_PCT = 5.0
_volume = {"pct": None}



def volume_percentual():
    
    if _volume["pct"] is None:
        pct = None
        try:
            pct = float(json.loads(ARQ_VOLUME.read_text(encoding="utf-8"))["pct"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if pct is None:
            pct = 100.0
        _volume["pct"] = min(max(pct, VOLUME_MINIMO_PCT), 100.0)
    return _volume["pct"]


# Define volume percentual
def definir_volume_percentual(valor):
    pct = min(max(float(valor), VOLUME_MINIMO_PCT), 100.0)
    _volume["pct"] = pct
    try:
        ARQ_VOLUME.parent.mkdir(parents=True, exist_ok=True)
        ARQ_VOLUME.write_text(json.dumps({"pct": pct}), encoding="utf-8")
    except OSError:
        log.warning("Não consegui gravar o volume da câmera.", exc_info=True)
    return pct


# Aplica volume
def aplicar_volume(audio):

    ganho = (volume_percentual() / 100.0) ** 2
    if ganho >= 0.999:
        return audio
    try:
        with wave.open(io.BytesIO(audio), "rb") as entrada:
            canais = entrada.getnchannels()
            largura = entrada.getsampwidth()
            taxa = entrada.getframerate()
            bruto = entrada.readframes(entrada.getnframes())
        if largura != 2:
            return audio
        bruto = bruto[: len(bruto) - (len(bruto) % 2)]
        amostras = array("h")
        amostras.frombytes(bruto)
        escalado = array("h", (int(a * ganho) for a in amostras))
        saida = io.BytesIO()
        with wave.open(saida, "wb") as arquivo:
            arquivo.setnchannels(canais)
            arquivo.setsampwidth(2)
            arquivo.setframerate(taxa)
            arquivo.writeframes(escalado.tobytes())
        return saida.getvalue()
    except Exception:
        log.warning("Não consegui ajustar o volume do áudio da câmera.", exc_info=True)
        return audio



def adicionar_silencio(audio):
    inicio = max(0.0, float(cfg("CAMERA_FALA_ATRASO_S", 1.2)))
    fim = 0.6
    try:
        with wave.open(io.BytesIO(audio), "rb") as entrada:
            canais = entrada.getnchannels()
            largura = entrada.getsampwidth()
            taxa = entrada.getframerate()
            bruto = entrada.readframes(entrada.getnframes())
        tamanho_quadro = canais * largura
        antes = b"\x00" * (int(taxa * inicio) * tamanho_quadro)
        depois = b"\x00" * (int(taxa * fim) * tamanho_quadro)
        saida = io.BytesIO()
        with wave.open(saida, "wb") as arquivo:
            arquivo.setnchannels(canais)
            arquivo.setsampwidth(largura)
            arquivo.setframerate(taxa)
            arquivo.writeframes(antes + bruto + depois)
        return saida.getvalue()
    except Exception:
        log.warning("Não consegui adicionar silêncio ao áudio.", exc_info=True)
        return audio



def go2rtc_online():
    agora = time.monotonic()
    if agora - cache_go2rtc["hora"] < 15:
        return cache_go2rtc["ok"]
    base = str(cfg("GO2RTC_URL", "http://127.0.0.1:1984")).rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/api/streams", timeout=1.5):
            ok = True
    except Exception:
        ok = False
    cache_go2rtc.update(hora=agora, ok=ok)
    return ok


# Limpa antigos
def limpar_antigos():
    limite = time.time() - 600
    try:
        for arquivo in PASTA_AUDIO.glob("fala_*.wav"):
            if arquivo.stat().st_mtime < limite:
                arquivo.unlink(missing_ok=True)
    except OSError:
        log.debug("Falha ao limpar os áudios antigos.", exc_info=True)



def falar(texto):
    if not cfg("CAMERA_FALA_ATIVA", False):
        log.info("Fala não enviada: o alto-falante da câmera está desativado.")
        return False
    if not TRAVA.acquire(timeout=30):
        log.error("A fala da câmera foi descartada após esperar 30 segundos pelo alto-falante.")
        return False
    try:
        audio = voz.sintetizar_bytes(texto, respeitar_voz_ativa=False)
        if not audio:
            log.error("A síntese não gerou áudio para o alto-falante da câmera A28.")
            return False
        audio = preparar_audio(audio)
        audio = aplicar_volume(audio)
        audio = adicionar_silencio(audio)

        PASTA_AUDIO.mkdir(parents=True, exist_ok=True)
        limpar_antigos()
        caminho = PASTA_AUDIO / f"fala_{int(time.time() * 1000)}.wav"
        caminho.write_bytes(audio)

        pedido = urllib.request.Request(url_api(caminho), method="POST")
        with urllib.request.urlopen(pedido, timeout=30) as resposta:
            log.info(
                "Go2rtc aceitou a fala da câmera A28 (HTTP %s, canal %s).",
                resposta.status,
                cfg("GO2RTC_STREAM", "a28_voz"),
            )
        return True
    except Exception:
        log.warning("Não consegui falar pela câmera A28.", exc_info=True)
        return False
    finally:
        TRAVA.release()



def predefinidas():
    base = config.obter_mapa_texto("camera_falas") or FALAS_PREDEFINIDAS
    nome = str(cfg("NOME_MESTRE", "")).strip() or "proprietário"
    falas = []
    for rotulo, texto in base.items():
        rotulo = " ".join(str(rotulo).split())[:30]
        texto = " ".join(str(texto).replace("{nome}", nome).split())[:300]
        if rotulo and texto:
            falas.append((rotulo, texto))
    return falas[:12]



def falar_aviso(reincidente=False):
    return falar(random.choice(FALAS_REINCIDENTE if reincidente else FALAS_AVISO))
