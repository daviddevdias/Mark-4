import base64

import collections

import io
import os
import random

import logging

import threading

import time

from datetime import datetime

import config


FALHAS = {
    "tela": (
        "Senhor, não consegui estabelecer o feed da tela. Recalibrando os sensores de captura.",
        "A captura do display foi bloqueada, senhor. Reconfigurando o acesso ao monitor.",
        "Senhor, perdi o sinal do display. Reiniciando a interface de captura.",
    ),
    "camera": (
        "Senhor, o sensor óptico não respondeu. Verifique se a câmera está livre e conectada.",
        "Câmera fora de linha, senhor. Recalibrando o sensor óptico.",
        "Senhor, o feed da câmera foi interrompido. Reestabelecendo o enlace de vídeo.",
    ),
    "link": (
        "Senhor, perdi o enlace com o satélite internacional. Tentando restabelecer a conexão.",
        "Senhor, o núcleo de análise visual não respondeu. Reiniciando o canal criptografado.",
        "Conexão com a rede neural interrompida, senhor. Redirecionando o sinal.",
        "Senhor, os servidores de visão estão fora de alcance. Restabelecendo o enlace seguro.",
    ),
    "foto": (
        "Senhor, a imagem chegou corrompida. Reenvie a transmissão, por favor.",
        "Transmissão de imagem inválida, senhor. Aguardo um novo envio.",
    ),
    "ao_vivo_off": (
        "A câmera ao vivo não está em operação, senhor. Deseja que eu a ative?",
        "Nenhum feed ao vivo ativo no momento, senhor.",
    ),
    "ao_vivo_vazio": (
        "Senhor, o feed ao vivo não entregou nenhum quadro a tempo. Reinicie a captura.",
        "A transmissão ao vivo foi interrompida antes de gerar imagens, senhor.",
    ),
}




def falha(tipo, motivo=None):
    if motivo:
        log.warning("Falha (%s): %s", tipo, motivo)
    return random.choice(FALHAS[tipo])


from comandos import llm_local

log = logging.getLogger("mark2.visao")

os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp",
)

try:
    import mss
except ImportError:
    mss = None

try:
    import cv2
except ImportError:
    cv2 = None

try:
    from PIL import Image
except ImportError:
    Image = None

LARGURA_MAXIMA = 1600

QUALIDADE_JPEG = 80

TENTATIVAS_CAPTURA = 2

TEMPO_VIDA_CACHE_TELA_SEGUNDOS = 2.0

PROMPT_PADRAO_TELA = (
    "Descreva o que está na tela: quais janelas/aplicativos estão abertos, "
    "se há alguma mensagem de erro visível (cite o texto exato do erro, se "
    "houver) e, se for um documento ou código, resuma o conteúdo principal. "
    "Seja direto e objetivo."
)

PROMPT_PADRAO_CAMERA = (
    "Descreva objetivamente o que aparece nesta imagem capturada pela câmera."
)

PROMPT_PADRAO_FOTO_CELULAR = (
    "Descreva esta foto enviada pelo celular com o máximo de detalhamento "
    "possível, de forma organizada:\n"
    "1) Visão geral da cena (onde parece ser, ambiente interno/externo, "
    "iluminação, hora do dia aparente).\n"
    "2) Todos os objetos e elementos visíveis, um a um, com posição "
    "relativa (esquerda/direita/centro, perto/longe), cor, marca/modelo "
    "quando identificável, estado de conservação e quantidade.\n"
    "3) Pessoas ou animais, se houver: quantidade, roupas, postura, "
    "expressão, o que estão fazendo — sem tentar identificar quem são.\n"
    "4) Qualquer texto legível (placas, cartazes, embalagens, telas, "
    "documentos): transcreva literalmente.\n"
    "5) Detalhes que possam ser úteis mesmo que pareçam pequenos (sujeira, "
    "danos, números de série, validade, preços etc.).\n"
    "Não resuma nem seja econômico — quanto mais detalhes verificáveis na "
    "imagem, melhor."
)

MAX_TOKENS_FOTO_CELULAR = 2000

PASTA_FOTOS_RECEBIDAS = config.DATA_DIR / "fotos"

cache_tela_lock = threading.RLock()
cache_tela_base64 = None
cache_tela_hora = 0.0
cache_tela_monitor = None




def monitores_disponiveis():
    if mss is None:
        return []
    with mss.mss() as sct:

        return list(sct.monitors)



# Lista monitores
def listar_monitores():

    monitores = monitores_disponiveis()
    if not monitores:
        return []
    return [
        {"indice": indice, "largura": m["width"], "altura": m["height"]}
        for indice, m in enumerate(monitores)
        if indice > 0 or len(monitores) == 1
    ]



# Captura tela
def capturar_tela(indice_monitor=None, regiao=None, usar_cache=False):

    global cache_tela_base64, cache_tela_hora, cache_tela_monitor

    if mss is None:
        log.error(
            "A biblioteca 'mss' não está instalada; não é possível capturar a tela."
        )
        return None
    if Image is None:
        log.error(
            "A biblioteca 'Pillow' não está instalada; não é possível processar o screenshot."
        )
        return None

    if usar_cache and regiao is None:
        with cache_tela_lock:
            cache_valido = (
                cache_tela_base64 is not None
                and cache_tela_monitor == indice_monitor
                and (time.monotonic() - cache_tela_hora)
                < TEMPO_VIDA_CACHE_TELA_SEGUNDOS
            )
            if cache_valido:
                return cache_tela_base64

    ultimo_erro = None
    for tentativa in range(TENTATIVAS_CAPTURA):
        try:
            with mss.mss() as sct:
                if regiao:
                    alvo = regiao
                elif indice_monitor is not None and indice_monitor < len(sct.monitors):
                    alvo = sct.monitors[indice_monitor]
                else:
                    alvo = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                captura = sct.grab(alvo)
            imagem = Image.frombytes("RGB", captura.size, captura.bgra, "raw", "BGRX")
            resultado = codificar_jpeg(imagem)
            if regiao is None:
                with cache_tela_lock:
                    cache_tela_base64 = resultado
                    cache_tela_hora = time.monotonic()
                    cache_tela_monitor = indice_monitor
            return resultado
        except Exception as erro:
            ultimo_erro = erro
            if tentativa + 1 < TENTATIVAS_CAPTURA:
                time.sleep(0.2)

    log.error(
        "Falha ao capturar a tela após %d tentativa(s): %s",
        TENTATIVAS_CAPTURA,
        ultimo_erro,
    )
    return None



# Captura camera
def capturar_camera():
    if cv2 is None:
        log.error("OpenCV nao esta instalado.")
        return None
    if Image is None:
        log.error("Pillow nao esta instalado.")
        return None

    try:
        from comandos.automacao import vigia_camera

        quadro = vigia_camera.quadro_recente()
        if quadro is not None:
            imagem = Image.fromarray(cv2.cvtColor(quadro, cv2.COLOR_BGR2RGB))
            return codificar_jpeg(imagem)
    except Exception:
        log.debug("Nao foi possivel reutilizar o quadro do vigia.", exc_info=True)

    url = str(getattr(config, "CAMERA_A28_URL", "") or "").strip()
    indice = int(getattr(config, "CAMERA_INDICE", 0) or 0)
    fontes = []
    if url:
        fontes.append((url, getattr(cv2, "CAP_FFMPEG", 0), "A28"))
    else:
        fontes.append((indice, None, f"camera local {indice}"))

    ultimo_erro = None
    for fonte, backend, nome in fontes:
        for tentativa in range(TENTATIVAS_CAPTURA):
            captura = None
            try:
                captura = (
                    cv2.VideoCapture(fonte, backend)
                    if backend is not None
                    else cv2.VideoCapture(fonte)
                )
                if not captura.isOpened():
                    ultimo_erro = f"Nao foi possivel abrir a fonte da camera {nome}."
                    continue
                captura.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                sucesso, quadro = False, None
                for _ in range(3):
                    sucesso, quadro = captura.read()
                    if sucesso and quadro is not None:
                        break
                if not sucesso or quadro is None:
                    ultimo_erro = f"A fonte {nome} nao retornou um quadro valido."
                    continue
                imagem = Image.fromarray(cv2.cvtColor(quadro, cv2.COLOR_BGR2RGB))
                return codificar_jpeg(imagem)
            except Exception as erro:
                ultimo_erro = erro
            finally:
                if captura is not None:
                    captura.release()
            if tentativa + 1 < TENTATIVAS_CAPTURA:
                time.sleep(0.3)

    log.error("Falha ao capturar a camera: %s", ultimo_erro)
    return None




def codificar_jpeg(imagem, largura_maxima=LARGURA_MAXIMA, qualidade=QUALIDADE_JPEG):
    if imagem.width > largura_maxima:
        proporcao = largura_maxima / imagem.width
        nova_altura = max(1, int(imagem.height * proporcao))
        imagem = imagem.resize((largura_maxima, nova_altura))
    buffer = io.BytesIO()
    imagem.convert("RGB").save(buffer, format="JPEG", quality=qualidade)
    return base64.b64encode(buffer.getvalue()).decode("ascii")



def mensagem_falha_servidor_local():
    if not llm_local.servidor_local_ativo():
        return "O LM Studio esta desativado."
    erro = llm_local.ultimo_erro()
    if not erro:
        return "O Qwen Vision nao retornou"
    texto = str(erro).lower()
    if "404" in texto or ("model" in texto and ("not found" in texto or "nao encontrado" in texto)):
        return "O modelo Qwen Vision nao esta disponivel no LM Studio"
    if any(chave in texto for chave in ("connection", "conectar", "refused", "timed out", "timeout")):
        return "Nao foi possivel conectar ao LM Studio"
    return "O LM Studio falhou ao analisar a imagem"



def analisar_tela(pergunta=None, indice_monitor=None, regiao=None, usar_cache=False):
    imagem_base64 = capturar_tela(
        indice_monitor=indice_monitor, regiao=regiao, usar_cache=usar_cache
    )
    if imagem_base64 is None:
        return falha("tela")

    resultado = llm_local.chamar_visao(pergunta or PROMPT_PADRAO_TELA, imagem_base64)
    if resultado is None:
        return mensagem_falha_servidor_local()
    return resultado



# Salva foto recebida
def salvar_foto_recebida(imagem_base64, prefixo="foto"):

    if not llm_local.imagem_valida(imagem_base64):
        return None
    try:
        PASTA_FOTOS_RECEBIDAS.mkdir(parents=True, exist_ok=True)
        nome = f"{prefixo}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
        caminho = PASTA_FOTOS_RECEBIDAS / nome
        caminho.write_bytes(base64.b64decode(imagem_base64, validate=True))
        return caminho
    except Exception:
        log.error("Falha ao salvar a foto recebida.", exc_info=True)
        return None




def analisar_foto_recebida(imagem_base64, pergunta=None, salvar=True):

    if not llm_local.imagem_valida(imagem_base64):
        return falha("foto"), None

    caminho_salvo = salvar_foto_recebida(imagem_base64) if salvar else None

    resultado = llm_local.chamar_visao(
        pergunta or PROMPT_PADRAO_FOTO_CELULAR,
        imagem_base64,
        max_tokens=MAX_TOKENS_FOTO_CELULAR,
    )
    if resultado is None:
        return falha("link", llm_local.ultimo_erro()), caminho_salvo
    return resultado, caminho_salvo




def analisar_camera(pergunta=None):

    imagem_base64 = capturar_camera()
    if imagem_base64 is None:
        return falha("camera")

    resultado = llm_local.chamar_visao(pergunta or PROMPT_PADRAO_CAMERA, imagem_base64)
    if resultado is None:
        return mensagem_falha_servidor_local()
    return resultado


FPS_CAPTURA_AO_VIVO = float(getattr(config, "CAMERA_AO_VIVO_FPS", 2) or 2)

DURACAO_BUFFER_AO_VIVO_SEGUNDOS = float(
    getattr(config, "CAMERA_AO_VIVO_DURACAO_SEGUNDOS", 12) or 12
)

MAX_QUADROS_BUFFER_AO_VIVO = max(
    2, int(FPS_CAPTURA_AO_VIVO * DURACAO_BUFFER_AO_VIVO_SEGUNDOS)
)

MAX_QUADROS_ENVIADOS_ANALISE_AO_VIVO = max(
    1, int(getattr(config, "CAMERA_AO_VIVO_MAX_QUADROS_ANALISE", 6) or 6)
)

LARGURA_MAXIMA_AO_VIVO = 960

QUALIDADE_JPEG_AO_VIVO = 70

MAX_TOKENS_AO_VIVO = 1400

PROMPT_PADRAO_AO_VIVO = (
    "Estas imagens são quadros tirados em sequência, nos últimos segundos, "
    "por uma câmera que ficou gravando ao vivo. Descreva a cena com o "
    "máximo de detalhe possível, como se estivesse vendo tudo ao vivo:\n"
    "1) Ambiente e contexto geral (onde parece ser, iluminação, hora do "
    "dia aparente).\n"
    "2) Pessoas ou animais: quantidade, o que estão fazendo, postura, "
    "expressão, roupas — descreva sem tentar identificar quem são.\n"
    "3) Objetos relevantes e qualquer mudança perceptível entre um quadro "
    "e outro (algo se moveu, apareceu, sumiu, mudou de posição).\n"
    "4) Qualquer texto legível nos quadros: transcreva literalmente.\n"
    "5) Qualquer coisa que pareça fora do comum ou que mereça atenção.\n"
    "Seja detalhado e preciso; não invente nada que não esteja visível nas "
    "imagens."
)

captura_ao_vivo_lock = threading.RLock()
captura_ao_vivo_thread = None
captura_ao_vivo_parar = threading.Event()
captura_ao_vivo_pronta = threading.Event()
captura_ao_vivo_buffer = collections.deque(maxlen=MAX_QUADROS_BUFFER_AO_VIVO)
captura_ao_vivo_ativa_flag = False



# Captura ao vivo ativa
def captura_ao_vivo_ativa():
    with captura_ao_vivo_lock:
        return captura_ao_vivo_ativa_flag




def loop_captura_ao_vivo(fonte_camera):
    global captura_ao_vivo_ativa_flag

    captura = None
    erros_seguidos = 0
    try:
        intervalo = 1.0 / FPS_CAPTURA_AO_VIVO if FPS_CAPTURA_AO_VIVO > 0 else 0.5
        while not captura_ao_vivo_parar.is_set():
            quadro = None
            try:
                from comandos.automacao import vigia_camera

                quadro = vigia_camera.quadro_recente(max_idade=3.0)
            except Exception:
                log.debug("Quadro compartilhado do vigia indisponivel.", exc_info=True)

            if quadro is not None:
                if captura is not None:
                    captura.release()
                    captura = None
                erros_seguidos = 0
            else:
                if captura is None:
                    backend = getattr(cv2, "CAP_FFMPEG", 0) if isinstance(fonte_camera, str) else None
                    captura = (
                        cv2.VideoCapture(fonte_camera, backend)
                        if backend is not None
                        else cv2.VideoCapture(fonte_camera)
                    )
                    if not captura.isOpened():
                        log.error("Nao foi possivel abrir a fonte da camera ao vivo: %s", "A28 RTSP" if isinstance(fonte_camera, str) else fonte_camera)
                        captura.release()
                        captura = None
                        captura_ao_vivo_parar.wait(1.0)
                        continue
                    captura.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                sucesso, quadro = captura.read()
                if not sucesso or quadro is None:
                    erros_seguidos += 1
                    if erros_seguidos >= 10:
                        log.warning("Feed da camera perdeu 10 quadros; reconectando.")
                        captura.release()
                        captura = None
                        erros_seguidos = 0
                        captura_ao_vivo_parar.wait(0.5)
                    else:
                        captura_ao_vivo_parar.wait(0.1)
                    continue
                erros_seguidos = 0

            try:
                imagem = Image.fromarray(cv2.cvtColor(quadro, cv2.COLOR_BGR2RGB))
                codificado = codificar_jpeg(
                    imagem,
                    largura_maxima=LARGURA_MAXIMA_AO_VIVO,
                    qualidade=QUALIDADE_JPEG_AO_VIVO,
                )
                with captura_ao_vivo_lock:
                    captura_ao_vivo_buffer.append((time.monotonic(), codificado))
                    if not captura_ao_vivo_ativa_flag:
                        captura_ao_vivo_ativa_flag = True
                        captura_ao_vivo_pronta.set()
            except Exception:
                log.debug("Falha ao processar quadro ao vivo.", exc_info=True)
            captura_ao_vivo_parar.wait(intervalo)
    except Exception:
        log.error("Falha na captura da camera ao vivo.", exc_info=True)
    finally:
        if captura is not None:
            captura.release()
        with captura_ao_vivo_lock:
            captura_ao_vivo_ativa_flag = False
        captura_ao_vivo_pronta.set()
        log.info("Captura da camera ao vivo encerrada.")


# Inicia captura ao vivo
def iniciar_captura_ao_vivo(indice_camera=None):

    global captura_ao_vivo_thread

    if cv2 is None:
        return (
            False,
            "Senhor, o módulo de visão computacional não está instalado.",
        )
    if Image is None:
        return (
            False,
            "Senhor, falta o módulo de processamento de imagem.",
        )

    with captura_ao_vivo_lock:
        if captura_ao_vivo_ativa_flag:
            return False, "A camera ao vivo ja esta em operacao, senhor."
        captura_ao_vivo_buffer.clear()
        captura_ao_vivo_parar.clear()
        captura_ao_vivo_pronta.clear()
        fonte_camera = str(getattr(config, "CAMERA_A28_URL", "") or "").strip()
        if not fonte_camera:
            fonte_camera = int(
                indice_camera
                if indice_camera is not None
                else getattr(config, "CAMERA_INDICE", 0) or 0
            )
        captura_ao_vivo_thread = threading.Thread(
            target=loop_captura_ao_vivo, args=(fonte_camera,), daemon=True
        )
        captura_ao_vivo_thread.start()

    captura_ao_vivo_pronta.wait(timeout=8)
    if not captura_ao_vivo_ativa():
        parar_captura_ao_vivo()
        return (
            False,
            "Senhor, nao consegui abrir o feed da camera A28.",
        )

    return (
        True,
        "Câmera ao vivo ativada, senhor."
    )



# Para captura ao vivo
def parar_captura_ao_vivo():
    global captura_ao_vivo_thread

    with captura_ao_vivo_lock:
        estava_ativa = captura_ao_vivo_ativa_flag
        thread = captura_ao_vivo_thread
        captura_ao_vivo_parar.set()

    if thread is not None:
        thread.join(timeout=5)

    with captura_ao_vivo_lock:
        captura_ao_vivo_buffer.clear()
        captura_ao_vivo_thread = None

    return estava_ativa



# Seleciona quadros ao vivo
def selecionar_quadros_ao_vivo(maximo):
    with captura_ao_vivo_lock:
        quadros = list(captura_ao_vivo_buffer)

    if not quadros:
        return []
    if len(quadros) <= maximo:
        return [codificado for _, codificado in quadros]

    passo = len(quadros) / maximo
    indices = sorted({int(indice * passo) for indice in range(maximo)})
    if indices[-1] != len(quadros) - 1:
        indices[-1] = len(quadros) - 1
    return [quadros[indice][1] for indice in indices]




def ultimo_quadro_ao_vivo_jpeg(max_idade=3.0):
    with captura_ao_vivo_lock:
        if not captura_ao_vivo_ativa_flag or not captura_ao_vivo_buffer:
            return None
        hora, imagem = captura_ao_vivo_buffer[-1]
    if time.monotonic() - hora > max_idade:
        return None
    try:
        return base64.b64decode(imagem, validate=True)
    except (TypeError, ValueError):
        log.warning("Quadro ao vivo invalido descartado.")
        return None



# Salva quadros ao vivo
def salvar_quadros_ao_vivo(quadros_base64):
    caminhos = []
    try:
        PASTA_FOTOS_RECEBIDAS.mkdir(parents=True, exist_ok=True)
        carimbo = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        for indice, quadro in enumerate(quadros_base64):
            nome = f"ao_vivo_{carimbo}_{indice:02d}.jpg"
            caminho = PASTA_FOTOS_RECEBIDAS / nome
            caminho.write_bytes(base64.b64decode(quadro, validate=True))
            caminhos.append(caminho)
    except Exception:
        log.error("Falha ao salvar os quadros da captura ao vivo.", exc_info=True)
    return caminhos




def analisar_ao_vivo(pergunta=None, salvar=True):
    if not captura_ao_vivo_ativa():
        return falha("ao_vivo_off")

    quadros = selecionar_quadros_ao_vivo(MAX_QUADROS_ENVIADOS_ANALISE_AO_VIVO)

    if not quadros:
        return falha("ao_vivo_vazio")

    if salvar:
        salvar_quadros_ao_vivo(quadros)

    resultado = llm_local.chamar_visao_multiplas(
        pergunta or PROMPT_PADRAO_AO_VIVO, quadros, max_tokens=MAX_TOKENS_AO_VIVO
    )
    if resultado is None:
        return mensagem_falha_servidor_local()
    return resultado
