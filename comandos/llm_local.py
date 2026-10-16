import json

import logging

import math
import re

import os

import shutil

import subprocess

import threading

import contextvars

import time

from itertools import count

from pathlib import Path

from urllib.parse import urlsplit, urlunsplit

import requests

import config

log = logging.getLogger("mark2.llm_local")

URL_PADRAO = "http://localhost:1234/v1"

MODELO_PADRAO = "qwen3-8b"

MAX_MENSAGENS = 5000

MAX_CARACTERES_MENSAGENS = 2_000_000

CHAVES_RESERVADAS = {"model", "messages", "temperature", "max_tokens"}

ATIVIDADE_LOCK = threading.Lock()

ATIVIDADES = {}

SEQUENCIA_ATIVIDADE = count(1)

ATIVIDADE_VERSAO = 0

CANCELAMENTO_VERSAO = 0

ULTIMA_ETAPA = "ocioso"

ULTIMA_ATUALIZACAO = 0.0

ERRO_LOCK = threading.Lock()

ULTIMO_ERRO = None

LIMITE_CHAMADAS_PARALELAS = max(1, int(getattr(config, "LLM_LOCAL_PARALELISMO", 1)))

SEMAFORO_CHAMADAS = threading.Semaphore(LIMITE_CHAMADAS_PARALELAS)

LIMITE_CHAMADAS_VISAO = max(1, int(getattr(config, "LLM_VISAO_PARALELISMO", 1)))

SEMAFORO_VISAO = threading.Semaphore(LIMITE_CHAMADAS_VISAO)



# Registra erro
def registrar_erro(motivo):
    global ULTIMO_ERRO
    with ERRO_LOCK:
        ULTIMO_ERRO = motivo




def ultimo_erro():
    with ERRO_LOCK:
        return ULTIMO_ERRO



# Inicia atividade
def iniciar_atividade(modelo):
    global ATIVIDADE_VERSAO, ULTIMA_ETAPA, ULTIMA_ATUALIZACAO
    identificador = next(SEQUENCIA_ATIVIDADE)
    with ATIVIDADE_LOCK:
        ATIVIDADES[identificador] = {
            "modelo": modelo,
            "etapa": "gerando",
            "cancelar": threading.Event(),
            "resposta": None,
            "iniciado_em": time.time(),
        }
        ATIVIDADE_VERSAO += 1
        ULTIMA_ETAPA = "gerando"
        ULTIMA_ATUALIZACAO = time.time()
    return identificador




def finalizar_atividade(identificador, sucesso):
    global ATIVIDADE_VERSAO, ULTIMA_ETAPA, ULTIMA_ATUALIZACAO
    with ATIVIDADE_LOCK:
        ATIVIDADES.pop(identificador, None)
        ATIVIDADE_VERSAO += 1
        ULTIMA_ETAPA = (
            "gerando" if ATIVIDADES else ("concluido" if sucesso else "indisponivel")
        )
        ULTIMA_ATUALIZACAO = time.time()



# Consulta atividade
def obter_atividade():
    with ATIVIDADE_LOCK:
        modelos = sorted({item["modelo"] for item in ATIVIDADES.values()})
        return {
            "ativo": bool(ATIVIDADES),
            "operacoes": len(ATIVIDADES),
            "etapa": ULTIMA_ETAPA,
            "modelo": modelos[0] if modelos else MODELO,
            "versao": ATIVIDADE_VERSAO,
            "atualizado_em": ULTIMA_ATUALIZACAO,
        }



# Consulta evento cancelar
def obter_evento_cancelar(identificador):
    with ATIVIDADE_LOCK:
        info = ATIVIDADES.get(identificador)
        return info["cancelar"] if info else None



# Registra resposta atividade
def registrar_resposta_atividade(identificador, resposta):
    fechar = False
    with ATIVIDADE_LOCK:
        info = ATIVIDADES.get(identificador)
        if info is None or info["cancelar"].is_set():
            fechar = True
        else:
            info["resposta"] = resposta
    if fechar:
        resposta.close()
        return False
    return True



# Cancela atividade
def cancelar_atividade(identificador):
    resposta = None
    with ATIVIDADE_LOCK:
        info = ATIVIDADES.get(identificador)
        if info is None:
            return False
        info["cancelar"].set()
        resposta = info.get("resposta")
    if resposta is not None:
        resposta.close()
    return True



# Cancela tudo
def cancelar_tudo():
    global CANCELAMENTO_VERSAO
    with ATIVIDADE_LOCK:
        CANCELAMENTO_VERSAO += 1
        atividades = list(ATIVIDADES.values())
        for atividade in atividades:
            atividade["cancelar"].set()
        respostas = [atividade.get("resposta") for atividade in atividades]
    for resposta in respostas:
        if resposta is not None:
            try:
                resposta.close()
            except requests.RequestException:
                pass
    log.info("Cancelamento solicitado para %d chamada(s) ao LM Studio em andamento.", len(atividades))
    return len(atividades)



def versao_cancelamento():
    with ATIVIDADE_LOCK:
        return CANCELAMENTO_VERSAO


INTERVALO_BATIMENTO_SEGUNDOS = 4 * 60

BATIMENTO_LOCK = threading.Lock()

batimento_iniciado = False




def url_nativa(url_base):
    if url_base.endswith("/v1"):
        return url_base[: -len("/v1")]
    return url_base




# Mantem servidor sob demanda
def iniciar_keep_alive_automatico():
    return None


# Normaliza URL base
def normalizar_url_base(valor):
    if not isinstance(valor, str):
        return URL_PADRAO
    valor = valor.strip().rstrip("/")
    try:
        partes = urlsplit(valor)
    except ValueError:
        return URL_PADRAO
    if partes.scheme not in {"http", "https"} or not partes.netloc:
        return URL_PADRAO
    return urlunsplit((partes.scheme, partes.netloc, partes.path.rstrip("/"), "", ""))



# Normaliza modelo
def normalizar_modelo(valor):
    if not isinstance(valor, str):
        return MODELO_PADRAO
    valor = valor.strip()
    return valor[:200] if valor else MODELO_PADRAO


URL_BASE = normalizar_url_base(getattr(config, "LLM_LOCAL_URL", URL_PADRAO))

MODELO = normalizar_modelo(getattr(config, "LLM_LOCAL_MODELO", MODELO_PADRAO))

URL_BASE_VISAO = normalizar_url_base(getattr(config, "LLM_VISAO_URL", URL_BASE))

MODELO_VISAO = str(getattr(config, "LLM_VISAO_MODELO", "")).strip()[:200]

MODELOS_TRAVA = threading.RLock()
MODELOS_CACHE = {"url": "", "tempo": 0, "ids": [], "conectado": False}

# Descobre modelos sem os carregar
def modelos_disponiveis():
    with MODELOS_TRAVA:
        agora=time.monotonic()
        prazo=10 if MODELOS_CACHE["conectado"] else 1
        if MODELOS_CACHE["url"]==URL_BASE and agora-MODELOS_CACHE["tempo"]<prazo:
            return dict(MODELOS_CACHE)
        ids=[];conectado=False
        try:
            with requests.Session() as session:
                session.trust_env=False
                with session.get(URL_BASE+"/models",timeout=2) as resposta:
                    resposta.raise_for_status()
                    if len(resposta.content)<=1_000_000:
                        dados=resposta.json();conectado=True
                        ids=[m["id"] for m in dados.get("data",[]) if isinstance(m,dict) and isinstance(m.get("id"),str) and 0<len(m["id"])<=200][:100]
        except (requests.RequestException,ValueError,TypeError,AttributeError):pass
        MODELOS_CACHE.update(url=URL_BASE,tempo=time.monotonic(),ids=ids,conectado=conectado)
        return dict(MODELOS_CACHE)

# Reconhece somente Qwen compativel
def resolver_modelo():
    ids=modelos_disponiveis()["ids"]
    if MODELO in ids:return MODELO
    if MODELO!=MODELO_PADRAO:return MODELO
    candidatos=[i for i in ids if re.fullmatch(r"qwen3[-_]?8b(?:[-_.].*)?",i.rsplit("/",1)[-1].lower()) and "embedding" not in i.lower()]
    return candidatos[0] if len(candidatos)==1 else MODELO


KEEP_ALIVE_TEXTO = getattr(config, "LLM_LOCAL_KEEP_ALIVE", 1800)

KEEP_ALIVE_VISAO = getattr(config, "LLM_VISAO_KEEP_ALIVE", 300)

SERVIDOR_LOCAL_LOCK = threading.RLock()
SERVIDOR_LOCAL_UNLOAD_LOCK = threading.Lock()
SERVIDOR_LOCAL_ATIVO = config.obter_bool("servidor_local_ativo", True)


BLOQUEIO_NESTA_REQUISICAO = contextvars.ContextVar("mark2_llm_bloqueado", default=False)




def bloquear_requisicao(bloqueado):
    BLOQUEIO_NESTA_REQUISICAO.set(bool(bloqueado))




def requisicao_bloqueada():
    return BLOQUEIO_NESTA_REQUISICAO.get()




def servidor_local_ativo():
    if BLOQUEIO_NESTA_REQUISICAO.get():
        return False
    with SERVIDOR_LOCAL_LOCK:
        return SERVIDOR_LOCAL_ATIVO




# Libera modelos locais
def descarregar_modelos_servidor_local():
    return None



def definir_servidor_local_ativo(ativo):
    global SERVIDOR_LOCAL_ATIVO
    if not isinstance(ativo, bool):
        return False
    with SERVIDOR_LOCAL_LOCK:
        if not config.persistir_valor("servidor_local_ativo", ativo):
            return False
        SERVIDOR_LOCAL_ATIVO = ativo
    if not ativo:
        cancelar_tudo()
        threading.Thread(target=descarregar_modelos_servidor_local, daemon=True).start()
    return True



def parar_servidor_servidor_local():
    sucesso = definir_servidor_local_ativo(False)
    return {"sucesso": sucesso, "mensagem": "IA pausada no Jarvis. O LM Studio permanece disponível."}


# Valida máximo tokens
def validar_max_tokens(valor):
    if isinstance(valor, bool) or not isinstance(valor, int):
        return None
    return valor if 1 <= valor <= 131_072 else None



# Valida numero
def validar_numero(valor, minimo, maximo):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return None
    valor = float(valor)
    return valor if math.isfinite(valor) and minimo <= valor <= maximo else None



# Valida mensagens
def validar_mensagens(mensagens):
    if not isinstance(mensagens, (list, tuple)):
        return None
    if not mensagens or len(mensagens) > MAX_MENSAGENS:
        return None

    mensagens_validadas = []
    total_caracteres = 0
    for mensagem in mensagens:
        if not isinstance(mensagem, dict):
            return None
        papel = mensagem.get("role")
        conteudo = mensagem.get("content")
        if papel not in {"system", "user", "assistant", "tool"}:
            return None
        if not isinstance(conteudo, str):
            return None
        total_caracteres += len(conteudo)
        if total_caracteres > MAX_CARACTERES_MENSAGENS:
            return None
        mensagem_validada = dict(mensagem)
        mensagem_validada["role"] = papel
        mensagem_validada["content"] = conteudo
        mensagens_validadas.append(mensagem_validada)
    return mensagens_validadas



# Extrai conteudo
def extrair_conteudo(resposta_json):
    if not isinstance(resposta_json, dict):
        return None
    escolhas = resposta_json.get("choices")
    if not isinstance(escolhas, list) or not escolhas:
        return None
    primeira_escolha = escolhas[0]
    if not isinstance(primeira_escolha, dict):
        return None
    mensagem = primeira_escolha.get("message")
    if not isinstance(mensagem, dict):
        return None
    conteudo = mensagem.get("content")
    if isinstance(conteudo, str):
        conteudo = conteudo.strip()
        return conteudo or None
    if not isinstance(conteudo, list):
        return None

    partes = []
    for bloco in conteudo:
        if not isinstance(bloco, dict):
            continue
        texto = bloco.get("text")
        if isinstance(texto, str) and texto:
            partes.append(texto)
    conteudo_unido = "".join(partes).strip()
    return conteudo_unido or None



# Extrai delta stream
def extrair_delta_stream(pedaco):
    if not isinstance(pedaco, dict):
        return ""
    escolhas = pedaco.get("choices")
    if not isinstance(escolhas, list) or not escolhas:
        return ""
    primeira = escolhas[0]
    if not isinstance(primeira, dict):
        return ""
    delta = primeira.get("delta")
    if not isinstance(delta, dict):
        return ""
    texto = delta.get("content")
    return texto if isinstance(texto, str) else ""




def enviar_para_servidor_local(corpo, timeout, url_base=None, evento_cancelar=None, ao_receber_resposta=None):
    if not servidor_local_ativo():
        registrar_erro("O servidor de LLM local está desativado no painel.")
        return None
    url_base = url_base or URL_BASE
    corpo_stream = dict(corpo)
    corpo_stream["stream"] = True
    resposta = None

    try:
        resposta = requests.post(
            f"{url_base}/chat/completions", json=corpo_stream, timeout=timeout, stream=True
        )

        if ao_receber_resposta is not None and not ao_receber_resposta(resposta):
            resposta.close()
            return None
        if evento_cancelar is not None and evento_cancelar.is_set():
            resposta.close()
            return None

        resposta.encoding = 'utf-8'

        resposta.raise_for_status()
    except requests.exceptions.Timeout as erro:
        if resposta is not None:
            resposta.close()
        log.error("Timeout ao chamar o LLM local em %s: %s", url_base, erro)
        registrar_erro(
            f"O servidor de LLM local não respondeu em {timeout:.0f}s (timeout). Ele pode "
            "estar sobrecarregado, recarregando o modelo, ou a máquina não "
            "aguenta o modelo configurado."
        )
        return None
    except requests.exceptions.ConnectionError as erro:
        if resposta is not None:
            resposta.close()
        log.error("Falha ao conectar ao LLM local em %s: %s", url_base, erro)
        registrar_erro(
            f"Não foi possível conectar ao servidor de LLM local em {url_base}. "
            "Verifique se o serviço está rodando e se o endereço configurado está correto."
        )
        return None
    except requests.RequestException as erro:
        if evento_cancelar is not None and evento_cancelar.is_set():
            if resposta is not None:
                resposta.close()
            return None
        resposta_erro = getattr(erro, "response", None) or resposta
        status = getattr(resposta_erro, "status_code", None)
        if status is None:
            log.error("Falha ao conectar ao LLM local em %s: %s", url_base, erro)
            registrar_erro(f"Falha de rede ao falar com o servidor de LLM local: {erro}")
        else:
            detalhe = ""
            try:
                corpo_erro = resposta_erro.json()
                if isinstance(corpo_erro, dict):
                    detalhe = corpo_erro.get("error") or corpo_erro.get("message") or ""
            except (ValueError, AttributeError):
                pass
            detalhe = str(detalhe).strip()[:500]
            sufixo = f" Detalhe: {detalhe}" if detalhe else ""
            log.error("O LLM local respondeu com HTTP %s: %s%s", status, erro, sufixo)
            registrar_erro(f"O servidor de LLM local respondeu com erro HTTP {status}.{sufixo}")
        if resposta is not None:
            resposta.close()
        return None

    partes = []
    cancelado = False
    try:
        for linha_bytes in resposta.iter_lines(decode_unicode=False):
            if evento_cancelar is not None and evento_cancelar.is_set():
                cancelado = True
                break

            if not linha_bytes:
                continue

            try:
                linha = linha_bytes.decode("utf-8", errors="strict").strip()
            except UnicodeDecodeError:

                log.warning("Chunk UTF-8 inválido recebido do LM Studio.")
                continue

            if not linha.startswith("data:"):
                continue

            dado = linha[5:].strip()
            if not dado or dado == "[DONE]":
                continue

            try:
                pedaco = json.loads(dado)
            except (TypeError, ValueError):
                log.debug("Chunk SSE JSON inválido ignorado.")
                continue

            partes.append(extrair_delta_stream(pedaco))
    except Exception as erro:
        log.error("Falha ao ler a resposta em streaming do LM Studio: %s", erro)
        if evento_cancelar is not None and evento_cancelar.is_set():
            return None
        registrar_erro(f"A conexão com o LM Studio caiu no meio da resposta: {erro}")
        return None
    finally:
        resposta.close()

    if cancelado:
        return None

    conteudo = limpar_resposta("".join(partes))
    if not conteudo:
        log.error("O LLM local devolveu uma resposta sem conteúdo utilizável.")
        registrar_erro(
            "O LM Studio respondeu, mas sem conteúdo utilizável (resposta vazia)."
        )
        return None

    registrar_erro(None)
    return conteudo



# Corrige mojibake
def corrigir_mojibake(texto):
    if not isinstance(texto, str) or not texto:
        return texto

    marcadores = ("Ã", "Â", "â€", "â€™", "â€œ", "â€\x9d", "�")
    if not any(marcador in texto for marcador in marcadores):
        return texto

    try:
        candidato = texto.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return texto

    antes = sum(texto.count(m) for m in marcadores)
    depois = sum(candidato.count(m) for m in marcadores)

    return candidato if depois < antes else texto



# Limpa resposta
def limpar_resposta(texto):
    """Limpa resposta."""
    if not isinstance(texto, str):
        return texto

    texto = corrigir_mojibake(texto)
    texto = texto.replace("\x00", "")
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.S)
    return texto.strip()




def chamar(
    mensagens,
    max_tokens=1024,
    temperatura=0.4,
    timeout=180,
    extra_opcoes=None,
):
    registrar_erro(None)
    mensagens_validadas = validar_mensagens(mensagens)
    if mensagens_validadas is None:
        log.error("A lista de mensagens enviada ao LLM é inválida ou grande demais.")
        registrar_erro("A mensagem enviada ao servidor de LLM local é inválida ou excede o limite.")
        return None

    max_tokens = validar_max_tokens(max_tokens)
    if max_tokens is None:
        log.error("max_tokens inválido ou fora do limite permitido.")
        registrar_erro("A quantidade de tokens solicitada está fora do limite permitido.")
        return None

    temperatura = validar_numero(temperatura, 0.0, 2.0)
    if temperatura is None:
        log.error("Temperatura inválida ou fora do limite permitido.")
        registrar_erro("A temperatura solicitada está fora do limite permitido.")
        return None

    timeout = validar_numero(timeout, 0.1, 900)
    if timeout is None:
        log.error("Timeout inválido ou fora do limite permitido.")
        registrar_erro("O tempo limite da chamada ao LLM é inválido.")
        return None

    if extra_opcoes is not None and not isinstance(extra_opcoes, dict):
        log.error("As opções extras do LLM precisam ser um dicionário.")
        registrar_erro("As opções extras enviadas ao LLM local são inválidas.")
        return None

    corpo = {
        "model": resolver_modelo(),
        "messages": mensagens_validadas,
        "temperature": temperatura,
        "max_tokens": max_tokens,

    }
    if extra_opcoes:
        for chave, valor in extra_opcoes.items():
            if isinstance(chave, str) and chave not in CHAVES_RESERVADAS:
                corpo[chave] = valor

    try:
        json.dumps(corpo, allow_nan=False)
    except (TypeError, ValueError):
        log.error("As opções enviadas ao LLM não são serializáveis.")
        registrar_erro("As opções enviadas ao servidor de LLM local não são serializáveis.")
        return None


    atividade_id = iniciar_atividade(MODELO)
    evento_cancelar = obter_evento_cancelar(atividade_id)
    ao_receber_resposta = lambda resposta: registrar_resposta_atividade(atividade_id, resposta)
    sucesso = False
    with SEMAFORO_CHAMADAS:
        try:
            conteudo = enviar_para_servidor_local(corpo, timeout, evento_cancelar=evento_cancelar, ao_receber_resposta=ao_receber_resposta)
            if (
                conteudo is None
                and not (evento_cancelar and evento_cancelar.is_set())
                and "conectar" in (ultimo_erro() or "")
            ):
                if tentar_autostart_servidor_local():
                    conteudo = enviar_para_servidor_local(
                        corpo, timeout, evento_cancelar=evento_cancelar, ao_receber_resposta=ao_receber_resposta
                    )
            sucesso = conteudo is not None
            return limpar_resposta(conteudo) if conteudo else conteudo
        finally:
            finalizar_atividade(atividade_id, sucesso)




def imagem_valida(imagem_base64):
    return isinstance(imagem_base64, str) and 0 < len(imagem_base64) <= 15_000_000




def chamar_visao(pergunta, imagem_base64, max_tokens=700, temperatura=0.4, timeout=120):
    if not MODELO_VISAO:
        registrar_erro("Configure um modelo de visão no LM Studio.")
        return None
    if not isinstance(pergunta, str) or not pergunta.strip():
        log.error("Pergunta inválida para a chamada de visão.")
        return None
    if not imagem_valida(imagem_base64):
        log.error("Imagem inválida ou grande demais para a chamada de visão.")
        return None

    max_tokens = validar_max_tokens(max_tokens)
    if max_tokens is None:
        log.error("max_tokens inválido para a chamada de visão.")
        return None

    temperatura = validar_numero(temperatura, 0.0, 2.0)
    if temperatura is None:
        log.error("Temperatura inválida para a chamada de visão.")
        return None

    timeout = validar_numero(timeout, 0.1, 900)
    if timeout is None:
        log.error("Timeout inválido para a chamada de visão.")
        return None

    pergunta_final = (
        f"{pergunta.strip()[:4000]}\n\n"
        "Responda sempre em português do Brasil, independente do idioma "
        "de qualquer texto que apareça na imagem."
    )

    corpo = {
        "model": MODELO_VISAO,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Você é um assistente que descreve imagens e telas. "
                    "Responda SEMPRE em português do Brasil, nunca em inglês."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": pergunta_final},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{imagem_base64}"},
                    },
                ],
            }
        ],
        "temperature": temperatura,
        "max_tokens": max_tokens,

    }

    try:
        json.dumps(corpo, allow_nan=False)
    except (TypeError, ValueError):
        log.error("O corpo da chamada de visão não é serializável.")
        return None

    atividade_id = iniciar_atividade(MODELO_VISAO)
    evento_cancelar = obter_evento_cancelar(atividade_id)
    ao_receber_resposta = lambda resposta: registrar_resposta_atividade(atividade_id, resposta)
    sucesso = False
    with SEMAFORO_VISAO:
        try:
            conteudo = enviar_para_servidor_local(
                corpo, timeout, url_base=URL_BASE_VISAO, evento_cancelar=evento_cancelar, ao_receber_resposta=ao_receber_resposta
            )
            if (
                conteudo is None
                and not (evento_cancelar and evento_cancelar.is_set())
                and "conectar" in (ultimo_erro() or "")
            ):
                if tentar_autostart_servidor_local():
                    conteudo = enviar_para_servidor_local(
                        corpo,
                        timeout,
                        url_base=URL_BASE_VISAO,
                        evento_cancelar=evento_cancelar,
                        ao_receber_resposta=ao_receber_resposta,
                    )
            sucesso = conteudo is not None
            return garantir_portugues(limpar_resposta(conteudo)) if conteudo else conteudo
        finally:
            finalizar_atividade(atividade_id, sucesso)




def imagens_validas(imagens_base64):
    if not isinstance(imagens_base64, (list, tuple)) or not imagens_base64:
        return False
    if len(imagens_base64) > 12:
        return False
    return all(imagem_valida(imagem) for imagem in imagens_base64)




def chamar_visao_multiplas(
    pergunta, imagens_base64, max_tokens=1200, temperatura=0.4, timeout=180
):
    if not isinstance(pergunta, str) or not pergunta.strip():
        log.error("Pergunta inválida para a chamada de visão com múltiplas imagens.")
        return None
    if not imagens_validas(imagens_base64):
        log.error(
            "Lista de imagens inválida, vazia ou grande demais para a chamada de visão."
        )
        return None

    max_tokens = validar_max_tokens(max_tokens)
    if max_tokens is None:
        log.error("max_tokens inválido para a chamada de visão com múltiplas imagens.")
        return None

    temperatura = validar_numero(temperatura, 0.0, 2.0)
    if temperatura is None:
        log.error("Temperatura inválida para a chamada de visão com múltiplas imagens.")
        return None

    timeout = validar_numero(timeout, 0.1, 900)
    if timeout is None:
        log.error("Timeout inválido para a chamada de visão com múltiplas imagens.")
        return None

    pergunta_final = (
        f"{pergunta.strip()[:4000]}\n\n"
        "Responda sempre em português do Brasil, independente do idioma "
        "de qualquer texto que apareça nas imagens."
    )

    conteudo = [{"type": "text", "text": pergunta_final}]
    for imagem in imagens_base64:
        conteudo.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{imagem}"},
            }
        )

    corpo = {
        "model": MODELO_VISAO,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Você é um assistente que descreve cenas a partir de uma "
                    "sequência de quadros tirados em sequência por uma câmera "
                    "ao vivo. Responda SEMPRE em português do Brasil, nunca "
                    "em inglês."
                ),
            },
            {"role": "user", "content": conteudo},
        ],
        "temperature": temperatura,
        "max_tokens": max_tokens,

    }

    try:
        json.dumps(corpo, allow_nan=False)
    except (TypeError, ValueError):
        log.error(
            "O corpo da chamada de visão com múltiplas imagens não é serializável."
        )
        return None

    atividade_id = iniciar_atividade(MODELO_VISAO)
    evento_cancelar = obter_evento_cancelar(atividade_id)
    ao_receber_resposta = lambda resposta: registrar_resposta_atividade(atividade_id, resposta)
    sucesso = False
    with SEMAFORO_VISAO:
        try:
            conteudo_resposta = enviar_para_servidor_local(
                corpo, timeout, url_base=URL_BASE_VISAO, evento_cancelar=evento_cancelar, ao_receber_resposta=ao_receber_resposta
            )
            if (
                conteudo_resposta is None
                and not (evento_cancelar and evento_cancelar.is_set())
                and "conectar" in (ultimo_erro() or "")
            ):
                if tentar_autostart_servidor_local():
                    conteudo_resposta = enviar_para_servidor_local(
                        corpo,
                        timeout,
                        url_base=URL_BASE_VISAO,
                        evento_cancelar=evento_cancelar,
                        ao_receber_resposta=ao_receber_resposta,
                    )
            sucesso = conteudo_resposta is not None
            return (
                garantir_portugues(limpar_resposta(conteudo_resposta))
                if conteudo_resposta
                else conteudo_resposta
            )
        finally:
            finalizar_atividade(atividade_id, sucesso)




def garantir_portugues(texto):
    mensagens = [
        {
            "role": "system",
            "content": (
                "Você recebe uma descrição de imagem que pode estar em "
                "inglês ou português. Se já estiver em português do "
                "Brasil, devolva o texto exatamente como está, sem "
                "nenhuma alteração. Se estiver em inglês (ou outro "
                "idioma), traduza para português do Brasil natural, "
                "preservando todo o conteúdo e o sentido. Responda "
                "apenas com o texto final, sem comentários adicionais."
            ),
        },
        {"role": "user", "content": texto[:4000]},
    ]
    traduzido = chamar(mensagens, max_tokens=800, temperatura=0.2, timeout=60)
    return traduzido if traduzido else texto


ULTIMA_TENTATIVA_AUTOSTART = 0.0

AUTOSTART_LOCK = threading.Lock()

COOLDOWN_AUTOSTART_SEGUNDOS = 30




# Usa servidor ja configurado
def tentar_autostart_servidor_local():
    return False


def disponivel():
    try:
        resposta = requests.get(f"{URL_BASE}/models", timeout=3)
        resposta.raise_for_status()
        return True
    except requests.RequestException:
        return False




def disponivel_visao():
    if not MODELO_VISAO:
        return False
    try:
        resposta = requests.get(f"{URL_BASE_VISAO}/models", timeout=3)
        resposta.raise_for_status()
        return True
    except requests.RequestException:
        return False
