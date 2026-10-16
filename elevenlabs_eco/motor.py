

import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
import unicodedata
import wave
from pathlib import Path

import requests
import config
from interface import cofre_privado

log = logging.getLogger("mark2.elevenlabs_eco")

PASTA = Path(__file__).resolve().parent
ARQ_CONFIG = config.DATA_DIR / "elevenlabs" / "configuracao.json"
PASTA_DADOS = config.DATA_DIR / "elevenlabs"
ARQ_USO = PASTA_DADOS / "uso.json"
ARQ_INDICE = PASTA_DADOS / "indice.json"
PASTA_CACHE = PASTA_DADOS / "cache"

TAXA_AMOSTRAGEM = 24000
URL_TTS = "https://api.elevenlabs.io/v1/text-to-speech/{voz}"
URL_ASSINATURA = "https://api.elevenlabs.io/v1/user/subscription"

PADRAO = {
    "ativo": True,
    "api_key": "",
    "voice_id": "",
    "modelo": "eleven_flash_v2_5",
    "creditos_totais": 40000,
    "reserva_creditos": 1500,
    "custo_por_caractere": 0.5,
    "intervalo_sync_segundos": 1800,
    "limite_caracteres_por_fala": 200,
    "texto_longo": "piper",
    "remover_parenteses": True,
    "usar_cache": True,
    "limite_cache_mb": 0,
    "economizar_servidor_local": True,
    "max_tokens_servidor_local": 160,
    "palavras_pedem_detalhe": ["detalh", "explique", "explica", "resum", "completo"],
    "instrucao_brevidade": (
        "MODO ECONOMIA DE VOZ: responda em no máximo 2 frases curtas, com até "
        "{limite} caracteres no total. Vá direto ao ponto, sem introdução, sem "
        "listas e sem perguntas de cortesia. Só detalhe se o usuário pedir."
    ),
}

_TRAVA = threading.RLock()
_cfg_cache = None
_cfg_mtime = None
_uso_cache = None
_bloqueado_ate = 0.0
_ultima_sync = 0.0
_saldo_api = None

_URL = re.compile(r"https?://\S+")
_TAG = re.compile(r"<[^>]*>")
_EMOJI = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff\U00002b00-\U00002bff]"
)
_MARKDOWN = re.compile(r"[*_`#>~|]+")
_PARENTESES = re.compile(r"\([^)]*\)")
_FIM_DE_FRASE = re.compile(r"(?<=[.!?…])\s+")


# Consulta opção de configuração
def cfg():
    
    global _cfg_cache, _cfg_mtime
    with _TRAVA:
        try:
            mtime = ARQ_CONFIG.stat().st_mtime
        except OSError:
            return dict(PADRAO, ativo=False)
        if _cfg_cache is None or mtime != _cfg_mtime:
            dados = {}
            try:
                dados = cofre_privado.ler(ARQ_CONFIG)
            except (OSError, ValueError):
                log.error("configuracao.json ilegível; ElevenLabs desativado.")
                dados = {"ativo": False}
            if not isinstance(dados, dict):
                dados = {"ativo": False}
            _cfg_cache = {**PADRAO, **dados}
            _cfg_mtime = mtime
        resultado = dict(_cfg_cache)

    # A chave também pode vir de variável
    resultado["api_key"] = (
        os.environ.get("ELEVENLABS_API_KEY") or resultado.get("api_key") or ""
    ).strip()
    resultado["voice_id"] = (
        os.environ.get("ELEVENLABS_VOICE_ID") or resultado.get("voice_id") or ""
    ).strip()
    return resultado



def _credenciais_ok(c):
    chave, voz = c["api_key"], c["voice_id"]
    if not chave or not voz:
        return False
    return not (chave.startswith("SUA_") or voz.startswith("SEU_"))



def _disponivel(c):
    return bool(c["ativo"]) and _credenciais_ok(c) and time.time() >= _bloqueado_ate



def _uso():
    global _uso_cache
    with _TRAVA:
        if _uso_cache is None:
            try:
                _uso_cache = json.loads(ARQ_USO.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _uso_cache = {}
            for chave, padrao in (
                ("gasto", 0.0),
                ("chamadas", 0),
                ("cache_hits", 0),
                ("caracteres", 0),
            ):
                _uso_cache.setdefault(chave, padrao)
        return _uso_cache


# Salva uso
def _salvar_uso():
    with _TRAVA:
        try:
            PASTA_DADOS.mkdir(parents=True, exist_ok=True)
            temporario = ARQ_USO.with_suffix(".tmp")
            temporario.write_text(json.dumps(_uso(), indent=2), encoding="utf-8")
            os.replace(temporario, ARQ_USO)
        except OSError:
            log.warning("Não consegui salvar o contador de uso.", exc_info=True)



def zerar_contador():
    with _TRAVA:
        _uso().update(gasto=0.0, chamadas=0, cache_hits=0, caracteres=0)
        _salvar_uso()



def _saldo_conta(c, sincronizar):
    
    global _ultima_sync, _saldo_api
    agora = time.time()
    if sincronizar and agora - _ultima_sync >= float(c["intervalo_sync_segundos"]):
        _ultima_sync = agora
        try:
            resposta = requests.get(
                URL_ASSINATURA, headers={"xi-api-key": c["api_key"]}, timeout=5
            )
            resposta.raise_for_status()
            dados = resposta.json()
            _saldo_api = float(dados["character_limit"]) - float(
                dados["character_count"]
            )
        except Exception:
            log.debug("Não consegui consultar o saldo da ElevenLabs.", exc_info=True)
    return _saldo_api



def _restante(c, sincronizar=True):
    
    local = float(c["creditos_totais"]) - float(_uso()["gasto"])
    conta = _saldo_conta(c, sincronizar)
    restante = local if conta is None else min(local, conta)
    return restante - float(c["reserva_creditos"])


# Prepara texto
def preparar_texto(texto, c=None):
    c = c or cfg()
    if not isinstance(texto, str):
        return ""
    texto = _URL.sub("", texto)
    texto = _TAG.sub("", texto)
    texto = _EMOJI.sub("", texto)
    texto = _MARKDOWN.sub("", texto)
    if c["remover_parenteses"]:
        texto = _PARENTESES.sub("", texto)
    return re.sub(r"\s+", " ", texto).strip()



def _cortar_frases(texto, limite):
    
    escolhido = ""
    for frase in _FIM_DE_FRASE.split(texto):
        candidato = f"{escolhido} {frase}".strip()
        if len(candidato) > limite:
            break
        escolhido = candidato
    return escolhido



def _texto_para_voz(texto, c):
    
    limpo = preparar_texto(texto, c)
    if not limpo:
        return ""
    limite = int(c["limite_caracteres_por_fala"])
    if len(limpo) <= limite:
        return limpo
    if str(c["texto_longo"]).lower() == "cortar":
        return _cortar_frases(limpo, limite)
    return ""



def _slug(texto):
    base = _normalizar(texto)
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
    return base[:60] or "fala"



def _arquivo_cache(texto, c=None):
    
    codigo = hashlib.sha1(texto.encode("utf-8")).hexdigest()[:10]
    return PASTA_CACHE / f"{_slug(texto)}__{codigo}.wav"



def _indice():
    try:
        dados = json.loads(ARQ_INDICE.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}


# Registra no indice
def _registrar_no_indice(texto, arquivo):
    """Registra no indice."""
    with _TRAVA:
        try:
            indice = _indice()
            indice[arquivo.name] = {
                "texto": texto,
                "criado": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            PASTA_DADOS.mkdir(parents=True, exist_ok=True)
            temporario = ARQ_INDICE.with_suffix(".tmp")
            temporario.write_text(
                json.dumps(indice, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            os.replace(temporario, ARQ_INDICE)
        except OSError:
            log.debug("Não consegui atualizar o índice do cache.", exc_info=True)


# Lista falas
def listar_falas():
    return {nome: dados.get("texto", "") for nome, dados in _indice().items()}



def deve_falar(texto):
    
    try:
        c = cfg()
        if not c["ativo"]:
            return False
        falar = _texto_para_voz(texto, c)
        if not falar:
            return False
        if c["usar_cache"] and _arquivo_cache(falar).is_file():
            return True  
        if not _disponivel(c):
            return False
        return len(falar) * float(c["custo_por_caractere"]) <= _restante(c, False)
    except Exception:
        log.exception("Falha ao decidir se usa o ElevenLabs.")
        return False



def _bloquear(segundos, motivo):
    global _bloqueado_ate
    _bloqueado_ate = time.time() + segundos
    log.warning("ElevenLabs em pausa por %.0f s: %s", segundos, motivo)



def _requisitar(texto, c):
    try:
        resposta = requests.post(
            URL_TTS.format(voz=c["voice_id"]),
            headers={
                "xi-api-key": c["api_key"],
                "Content-Type": "application/json",
                "Accept": "audio/pcm",
            },
            params={"output_format": f"pcm_{TAXA_AMOSTRAGEM}"},
            json={
                "text": texto,
                "model_id": c["modelo"],
                "voice_settings": {"speed": 0.95},
            },
            timeout=20,
        )
    except requests.RequestException:
        _bloquear(60, "sem conexão com a ElevenLabs")
        return None

    if resposta.status_code == 200 and resposta.content:
        return resposta.content

    corpo = (resposta.text or "")[:300]
    if "quota_exceeded" in corpo:
        _bloquear(1800, "créditos esgotados")
    elif resposta.status_code in (401, 403):
        _bloquear(86400, "chave de API ou voice_id recusados")
    elif resposta.status_code == 429:
        _bloquear(120, "limite de requisições")
    else:
        _bloquear(60, f"HTTP {resposta.status_code}")
    return None


# Grava wav
def _gravar_wav(caminho, pcm):
    with wave.open(str(caminho), "wb") as arquivo:
        arquivo.setnchannels(1)
        arquivo.setsampwidth(2)
        arquivo.setframerate(TAXA_AMOSTRAGEM)
        arquivo.writeframes(pcm)



def _podar_cache(c):
    
    if float(c["limite_cache_mb"]) <= 0:
        return
    limite = float(c["limite_cache_mb"]) * 1024 * 1024
    try:
        arquivos = sorted(PASTA_CACHE.glob("*.wav"), key=lambda a: a.stat().st_mtime)
        total = sum(a.stat().st_size for a in arquivos)
        while arquivos and total > limite:
            antigo = arquivos.pop(0)
            total -= antigo.stat().st_size
            antigo.unlink(missing_ok=True)
    except OSError:
        pass



def sintetizar(texto, caminho_wav):
    
    try:
        c = cfg()
        if not c["ativo"]:
            return False
        falar = _texto_para_voz(texto, c)
        if not falar:
            return False

        arquivo_cache = _arquivo_cache(falar)
        if c["usar_cache"] and arquivo_cache.is_file():
            shutil.copyfile(arquivo_cache, caminho_wav)
            with _TRAVA:
                _uso()["cache_hits"] += 1
                _salvar_uso()
            return True

        if not _disponivel(c):
            return False

        custo = len(falar) * float(c["custo_por_caractere"])
        if custo > _restante(c, True):
            log.info("Orçamento do ElevenLabs esgotado; usando o Piper.")
            return False

        pcm = _requisitar(falar, c)
        if not pcm:
            return False
        _gravar_wav(caminho_wav, pcm)

        if c["usar_cache"]:
            try:
                PASTA_CACHE.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(caminho_wav, arquivo_cache)
                _registrar_no_indice(falar, arquivo_cache)
                _podar_cache(c)
            except OSError:
                log.debug("Não consegui gravar no cache.", exc_info=True)

        with _TRAVA:
            uso = _uso()
            uso["gasto"] += custo
            uso["chamadas"] += 1
            uso["caracteres"] += len(falar)
            _salvar_uso()
        return True
    except Exception:
        log.exception("Falha no ElevenLabs; usando o Piper.")
        return False



def _normalizar(texto):
    texto = unicodedata.normalize("NFD", str(texto).casefold())
    return "".join(ch for ch in texto if not unicodedata.combining(ch))



def _pede_detalhe(mensagens, c):
    for mensagem in reversed(mensagens):
        if mensagem.get("role") == "user":
            conteudo = _normalizar(mensagem.get("content", ""))
            return any(_normalizar(p) in conteudo for p in c["palavras_pedem_detalhe"])
    return False



def ajustar_llm(mensagens, max_tokens):
    
    try:
        c = cfg()
        if not (c["economizar_servidor_local"] and _disponivel(c)):
            return mensagens, max_tokens, False
        if _restante(c, False) <= 0 or _pede_detalhe(mensagens, c):
            return mensagens, max_tokens, False

        instrucao = str(c["instrucao_brevidade"]).replace(
            "{limite}", str(int(c["limite_caracteres_por_fala"]))
        )
        novas = [dict(m) for m in mensagens]
        for mensagem in novas:
            if mensagem.get("role") == "system":
                mensagem["content"] = f"{mensagem['content']}\n\n{instrucao}"
                break
        else:
            novas.insert(0, {"role": "system", "content": instrucao})
        return novas, min(int(max_tokens), int(c["max_tokens_servidor_local"])), True
    except Exception:
        log.exception("Falha ao ajustar o LM Studio; seguindo sem modo curto.")
        return mensagens, max_tokens, False



def aparar_resposta(resposta):
    
    if not isinstance(resposta, str) or "<" in resposta:
        return resposta
    texto = resposta.rstrip()
    if texto.endswith((".", "!", "?", "…", '"', "”", ")")):
        return resposta
    fim = max(texto.rfind(marca) for marca in (". ", "! ", "? "))
    if fim >= 20:
        return texto[: fim + 1]
    return resposta



def status():
    c = cfg()
    uso = _uso()
    total = float(c["creditos_totais"])
    gasto = float(uso["gasto"])
    return {
        "ativo": c["ativo"],
        "credenciais_ok": _credenciais_ok(c),
        "modelo": c["modelo"],
        "creditos_gastos": round(gasto),
        "creditos_restantes": round(total - gasto),
        "falas_pagas": uso["chamadas"],
        "falas_do_cache": uso["cache_hits"],
        "falas_salvas": (
            len(list(PASTA_CACHE.glob("*.wav"))) if PASTA_CACHE.is_dir() else 0
        ),
        "caracteres_enviados": uso["caracteres"],
        "limite_por_fala": c["limite_caracteres_por_fala"],
        "servidor_local_modo_curto": c["economizar_servidor_local"],
    }
