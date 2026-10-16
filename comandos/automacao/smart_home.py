import logging

import threading

import time

import unicodedata

import requests

import config
from comandos.automacao import smartthings_auth

log = logging.getLogger("mark2.smarthome")



def falha(mensagem, *args):

    log.error(mensagem, *args)
    return ""

API_BASE = "https://api.smartthings.com/v1"

TEMPO_VIDA_CACHE_SEGUNDOS = 60

cache_id_tv = None

cache_dispositivos = None

hora_ultimo_cache = 0.0

token_cache = None

cache_lock = threading.RLock()

CANAIS_TV = dict(getattr(config, "CANAIS_TV", None) or config.obter_mapa_texto("canais_tv"))

PALAVRAS_CHAVE_TV = (
    "tv",
    "televis",
    "qled",
    "oled",
    "the frame",
    "crystal uhd",
    "smart tv",
    "4k",
    "8k",
    "tizen",
    "uhd",
)

PALAVRAS_IGNORADAS = (
    "sensor",
    "motion",
    "button",
    "lock",
    "thermostat",
    "temp",
    "vibration",
    "moisture",
    "siren",
    "dimmer",
)

# Remove acentos
def remover_acentos(texto):
    texto_normalizado = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(
        caractere
        for caractere in texto_normalizado
        if not unicodedata.combining(caractere)
    ).casefold()

# Consulta token
def obter_token():
    return smartthings_auth.obter_token_valido()

# Sincroniza token
def sincronizar_token(token):
    global cache_id_tv, cache_dispositivos, hora_ultimo_cache, token_cache

    with cache_lock:
        if token == token_cache:
            return
        cache_id_tv = None
        cache_dispositivos = None
        hora_ultimo_cache = 0.0
        token_cache = token

# Consulta cabecalhos autenticacao
def obter_cabecalhos_autenticacao(token=None):
    token_atual = obter_token() if token is None else str(token).strip()
    return {
        "Authorization": f"Bearer {token_atual}",
        "Accept": "application/json",
    }


def realizar_requisicao_get(endpoint, token=None):
    token_atual = obter_token() if token is None else str(token).strip()
    if not token_atual:
        return None

    try:
        url = f"{API_BASE}/{str(endpoint).lstrip('/')}"
        resposta = requests.get(
            url, headers=obter_cabecalhos_autenticacao(token_atual), timeout=8
        )
        if resposta.status_code == 401:
            novo_token = smartthings_auth.obter_token_valido(forcar=True)
            if novo_token and novo_token != token_atual:
                resposta = requests.get(
                    url, headers=obter_cabecalhos_autenticacao(novo_token), timeout=8
                )
        resposta.raise_for_status()
        dados = resposta.json()
        if isinstance(dados, dict):
            return dados
        log.warning("Resposta inesperada do SmartThings no GET de %s.", endpoint)
    except (requests.RequestException, ValueError, TypeError) as erro:
        log.warning("Falha no GET do SmartThings para %s: %s", endpoint, erro)
    return None


def realizar_requisicao_post(endpoint, payload, token=None):
    token_atual = obter_token() if token is None else str(token).strip()
    if not token_atual:
        return False

    try:
        url = f"{API_BASE}/{str(endpoint).lstrip('/')}"
        resposta = requests.post(
            url,
            headers=obter_cabecalhos_autenticacao(token_atual),
            json=payload,
            timeout=8,
        )
        if resposta.status_code == 401:
            novo_token = smartthings_auth.obter_token_valido(forcar=True)
            if novo_token and novo_token != token_atual:
                resposta = requests.post(
                    url,
                    headers=obter_cabecalhos_autenticacao(novo_token),
                    json=payload,
                    timeout=8,
                )
        resposta.raise_for_status()
        return True
    except requests.RequestException as erro:
        log.warning("Falha no POST do SmartThings para %s: %s", endpoint, erro)
        return False


def cache_esta_valido():
    token = obter_token()
    sincronizar_token(token)
    with cache_lock:
        return cache_dispositivos is not None and (
            time.monotonic() - hora_ultimo_cache < TEMPO_VIDA_CACHE_SEGUNDOS
        )

# Carrega dispositivos
def carregar_dispositivos(forcar_atualizacao=False):
    global cache_id_tv, cache_dispositivos, hora_ultimo_cache

    token = obter_token()
    sincronizar_token(token)
    if not token:
        return []

    with cache_lock:
        cache_valido = cache_dispositivos is not None and (
            time.monotonic() - hora_ultimo_cache < TEMPO_VIDA_CACHE_SEGUNDOS
        )
        if cache_valido and not forcar_atualizacao:
            return list(cache_dispositivos)

    dados = realizar_requisicao_get("devices", token)
    itens = dados.get("items") if dados is not None else None
    if isinstance(itens, list):
        dispositivos = [item for item in itens if isinstance(item, dict)]
        if token != obter_token():
            sincronizar_token(obter_token())
            return carregar_dispositivos(forcar_atualizacao=True)
        with cache_lock:
            cache_dispositivos = dispositivos
            cache_id_tv = None
            hora_ultimo_cache = time.monotonic()
            return list(cache_dispositivos)

    if dados is not None:
        log.warning("Lista de dispositivos ausente na resposta do SmartThings.")
    with cache_lock:
        return list(cache_dispositivos or [])

# Envia comando dispositivo
def enviar_comando_dispositivo(id_dispositivo, comando, capacidade="switch", argumentos=None):
    if not id_dispositivo or not comando or not capacidade:
        return False

    payload = {
        "commands": [
            {
                "component": "main",
                "capability": capacidade,
                "command": comando,
                "arguments": argumentos or [],
            }
        ]
    }
    return realizar_requisicao_post(
        f"devices/{id_dispositivo}/commands",
        payload,
    )

# Consulta detalhes dispositivo
def obter_detalhes_dispositivo(id_dispositivo):
    if not id_dispositivo:
        return None
    return realizar_requisicao_get(f"devices/{id_dispositivo}")

# Consulta capacidades tv
def obter_capacidades_tv():
    id_tv = obter_id_tv() or obter_id_tv(forcar_atualizacao=True)
    if not id_tv:
        return set()
    detalhes = obter_detalhes_dispositivo(id_tv)
    if not detalhes:
        return set()
    capacidades = set()
    for componente in detalhes.get("components", []):
        if componente.get("id") != "main":
            continue
        for capacidade in componente.get("capabilities", []):
            id_capacidade = capacidade.get("id")
            if id_capacidade:
                capacidades.add(id_capacidade)
    return capacidades

MAPA_CAPACIDADES_TV = {
    "switch": "ligar/desligar",
    "tvChannel": "trocar de canal",
    "audioVolume": "volume",
    "audioMute": "mudo",
    "mediaInputSource": "trocar entrada (HDMI etc.)",
    "samsungvd.mediaInputSource": "trocar entrada (HDMI etc., variante Samsung)",
    "mediaPlayback": "play/pause/parar/avançar/retroceder",
    "mediaTrackControl": "próxima faixa/faixa anterior",
    "custom.launchapp": "abrir app instalado (Netflix, YouTube...)",
    "custom.picturemode": "modo de imagem (Padrão, Cinema, Jogos...)",
    "custom.soundmode": "modo de som",
}


def diagnosticar_tv():
    id_tv = obter_id_tv() or obter_id_tv(forcar_atualizacao=True)
    if not id_tv:
        return obter_mensagem_falha(forcar_atualizacao=False)

    capacidades = obter_capacidades_tv()
    if not capacidades:
        return falha("Não consegui ler as capacidades da TV.")

    suportado = [
        f"{nome_amigavel} ({capacidade})"
        for capacidade, nome_amigavel in MAPA_CAPACIDADES_TV.items()
        if capacidade in capacidades
    ]
    nao_suportado = [
        f"{nome_amigavel} ({capacidade})"
        for capacidade, nome_amigavel in MAPA_CAPACIDADES_TV.items()
        if capacidade not in capacidades
    ]

    partes = ["Sua TV suporta: " + (", ".join(suportado) if suportado else "nada da lista conhecida") + "."]
    if nao_suportado:
        partes.append("Não suporta (ou não anuncia): " + ", ".join(nao_suportado) + ".")
    outras = sorted(capacidades - set(MAPA_CAPACIDADES_TV))
    if outras:
        partes.append("Outras capacidades presentes, fora do escopo de TV: " + ", ".join(outras) + ".")
    return " ".join(partes)


def dispositivo_eh_invalido(texto_dispositivo):
    texto_normalizado = remover_acentos(texto_dispositivo)
    return any(palavra in texto_normalizado for palavra in PALAVRAS_IGNORADAS)

# Calcula pontuacao tv
def calcular_pontuacao_tv(dispositivo):
    if not isinstance(dispositivo, dict):
        return 0

    campos = (
        dispositivo.get("label"),
        dispositivo.get("name"),
        dispositivo.get("deviceTypeName"),
        dispositivo.get("type"),
    )
    texto_unificado = " ".join(remover_acentos(campo) for campo in campos)
    if dispositivo_eh_invalido(texto_unificado):
        return 0
    return sum(10 for dica in PALAVRAS_CHAVE_TV if dica in texto_unificado)

# Consulta ID tv
def obter_id_tv(forcar_atualizacao=False):
    global cache_id_tv

    token = obter_token()
    sincronizar_token(token)
    if not token:
        return None

    with cache_lock:
        if cache_id_tv and not forcar_atualizacao and cache_esta_valido():
            return cache_id_tv

    id_melhor_resultado = None
    maior_pontuacao = 0
    for dispositivo in carregar_dispositivos(forcar_atualizacao):
        pontuacao_atual = calcular_pontuacao_tv(dispositivo)
        if pontuacao_atual > maior_pontuacao:
            maior_pontuacao = pontuacao_atual
            id_melhor_resultado = dispositivo.get("deviceId")

    if token == obter_token():
        with cache_lock:
            cache_id_tv = id_melhor_resultado
    return id_melhor_resultado

# Consulta mensagem falha
def obter_mensagem_falha(forcar_atualizacao=True):
    if not obter_token():
        return falha("SmartThings desconectado: token ausente ou inválido.")
    if not carregar_dispositivos(forcar_atualizacao=forcar_atualizacao):
        return falha("SmartThings: nenhum dispositivo encontrado na conta.")
    return falha("SmartThings: a televisão não foi identificada entre os dispositivos.")

# Controla tv
def controlar_tv(comando, mensagem_sucesso, capacidade="switch", argumentos=None):
    id_tv = obter_id_tv() or obter_id_tv(forcar_atualizacao=True)
    if not id_tv:
        return obter_mensagem_falha(forcar_atualizacao=False)
    if enviar_comando_dispositivo(id_tv, comando, capacidade=capacidade, argumentos=argumentos):
        log.info("Comando enviado à TV: %s (%s)", comando, capacidade)
        return mensagem_sucesso
    return falha("Falha ao enviar o comando '%s' (%s) à TV.", comando, capacidade)


def ligar_tv():
    return controlar_tv("on", "A televisão foi ligada.")


def desligar_tv():
    return controlar_tv("off", "A televisão foi desligada.")

# Consulta estado canal
def obter_status_canal():
    id_tv = obter_id_tv() or obter_id_tv(forcar_atualizacao=True)
    if not id_tv:
        return None

    dados = realizar_requisicao_get(f"devices/{id_tv}/status")
    if not dados:
        return None

    try:
        info_canal = dados["components"]["main"]["tvChannel"]
    except (KeyError, TypeError):
        return None

    numero = info_canal.get("tvChannel", {}).get("value")
    nome = info_canal.get("tvChannelName", {}).get("value")
    if numero is None and nome is None:
        return None
    return {"numero": numero, "nome": nome}


def resolver_canal_por_nome(nome_canal):
    if not nome_canal:
        return None
    chave = remover_acentos(nome_canal)
    for nome_conhecido, numero in CANAIS_TV.items():
        if remover_acentos(nome_conhecido) == chave:
            return str(numero)
    return None


def mudar_canal_numero(numero_canal):
    numero_texto = str(numero_canal).strip()
    if not numero_texto.isdigit():
        return falha("Número de canal inválido: %r.", numero_canal)
    return controlar_tv(
        "setTvChannel",
        f"Mudei para o canal {numero_texto}.",
        capacidade="tvChannel",
        argumentos=[numero_texto],
    )


def mudar_canal_por_nome(nome_canal):
    numero = resolver_canal_por_nome(nome_canal)
    if numero:
        resultado = mudar_canal_numero(numero)
        if resultado.startswith("Mudei"):
            return f"Mudei para {nome_canal} (canal {numero})."
        return resultado

    id_tv = obter_id_tv() or obter_id_tv(forcar_atualizacao=True)
    if not id_tv:
        return obter_mensagem_falha(forcar_atualizacao=False)
    if enviar_comando_dispositivo(
        id_tv, "setTvChannelName", capacidade="tvChannel", argumentos=[nome_canal]
    ):
        return f"Tentei mudar para {nome_canal}, confira se funcionou — nem toda TV suporta busca por nome."
    return falha(
        "Canal '%s' não está nos canais salvos e a TV recusou a busca por nome. "
        "Adicione em config.CANAIS_TV.",
        nome_canal,
    )


def canal_subir():
    return controlar_tv("channelUp", "Canal +.", capacidade="tvChannel")


def canal_descer():
    return controlar_tv("channelDown", "Canal -.", capacidade="tvChannel")

# Lista canais salvos
def listar_canais_salvos():
    if not CANAIS_TV:
        return falha("Nenhum canal salvo. Configure config.CANAIS_TV com nome:número.")
    itens = ", ".join(f"{nome} ({numero})" for nome, numero in CANAIS_TV.items())
    return f"Canais salvos: {itens}."

# Consulta volume
def obter_volume():
    id_tv = obter_id_tv() or obter_id_tv(forcar_atualizacao=True)
    if not id_tv:
        return None
    dados = realizar_requisicao_get(f"devices/{id_tv}/status")
    if not dados:
        return None
    try:
        principal = dados["components"]["main"]
        volume = principal.get("audioVolume", {}).get("volume", {}).get("value")
        mudo = principal.get("audioMute", {}).get("mute", {}).get("value")
    except (KeyError, TypeError):
        return None
    if volume is None and mudo is None:
        return None
    return {"volume": volume, "mudo": mudo == "muted"}

# Define volume
def definir_volume(nivel):
    try:
        nivel = int(nivel)
    except (TypeError, ValueError):
        return falha("Nível de volume inválido: %r.", nivel)
    nivel = max(0, min(100, nivel))
    return controlar_tv(
        "setVolume", f"Volume ajustado para {nivel}.", capacidade="audioVolume", argumentos=[nivel]
    )


def volume_subir():
    return controlar_tv("volumeUp", "Volume +.", capacidade="audioVolume")


def volume_descer():
    return controlar_tv("volumeDown", "Volume -.", capacidade="audioVolume")


def mutar():
    return controlar_tv("mute", "TV no mudo.", capacidade="audioMute")


def desmutar():
    return controlar_tv("unmute", "Mudo desativado.", capacidade="audioMute")


def capacidade_entrada_disponivel():
    capacidades = obter_capacidades_tv()
    if "mediaInputSource" in capacidades:
        return "mediaInputSource"
    if "samsungvd.mediaInputSource" in capacidades:
        return "samsungvd.mediaInputSource"
    return None

# Consulta fontes entrada
def obter_fontes_entrada():
    capacidade = capacidade_entrada_disponivel()
    if not capacidade:
        return []
    id_tv = obter_id_tv() or obter_id_tv(forcar_atualizacao=True)
    if not id_tv:
        return []
    dados = realizar_requisicao_get(f"devices/{id_tv}/status")
    if not dados:
        return []
    try:
        return (
            dados["components"]["main"][capacidade]
            .get("supportedInputSources", {})
            .get("value", [])
        )
    except (KeyError, TypeError):
        return []


def mudar_fonte_entrada(nome_fonte):
    capacidade = capacidade_entrada_disponivel()
    if not capacidade:
        return falha("A TV não anuncia suporte a troca de entrada (veja diagnosticar_tv()).")
    if not nome_fonte:
        return falha("Fonte de entrada não informada (ex.: HDMI1).")
    return controlar_tv(
        "setInputSource",
        f"Entrada trocada para {nome_fonte}.",
        capacidade=capacidade,
        argumentos=[nome_fonte],
    )


def tocar():
    return controlar_tv("play", "Reproduzindo.", capacidade="mediaPlayback")


def pausar():
    return controlar_tv("pause", "Pausado.", capacidade="mediaPlayback")

# Para midia
def parar_midia():
    return controlar_tv("stop", "Parado.", capacidade="mediaPlayback")


def avancar():
    return controlar_tv("fastForward", "Avançando.", capacidade="mediaPlayback")


def retroceder():
    return controlar_tv("rewind", "Retrocedendo.", capacidade="mediaPlayback")

APPS_TV_PADRAO = {
    "netflix": "3201907018807",
    "youtube": "111299001912",
    "prime video": "3201512006785",
    "disney+": "3201901017640",
    "spotify": "3201606009684",
}

APPS_TV = {**APPS_TV_PADRAO, **dict(getattr(config, "APPS_TV", None) or config.obter_mapa_texto("apps_tv"))}

# Abre app
def abrir_app(nome_app):
    if "custom.launchapp" not in obter_capacidades_tv():
        return falha("A TV não anuncia suporte a abrir apps (veja diagnosticar_tv()).")
    chave = remover_acentos(nome_app)
    app_id = next(
        (valor for nome, valor in APPS_TV.items() if remover_acentos(nome) == chave),
        None,
    )
    if not app_id:
        return falha(
            "App '%s' desconhecido na TV. Adicione o appId em config.APPS_TV.",
            nome_app,
        )
    return controlar_tv(
        "launchApp", f"Abrindo {nome_app}.", capacidade="custom.launchapp", argumentos=[app_id]
    )

# Consulta modos imagem
def obter_modos_imagem():
    if "custom.picturemode" not in obter_capacidades_tv():
        return []
    id_tv = obter_id_tv() or obter_id_tv(forcar_atualizacao=True)
    if not id_tv:
        return []
    dados = realizar_requisicao_get(f"devices/{id_tv}/status")
    if not dados:
        return []
    try:
        return (
            dados["components"]["main"]["custom.picturemode"]
            .get("supportedPictureModes", {})
            .get("value", [])
        )
    except (KeyError, TypeError):
        return []

# Define modo imagem
def definir_modo_imagem(modo):
    if "custom.picturemode" not in obter_capacidades_tv():
        return falha("A TV não anuncia suporte a troca de modo de imagem.")
    return controlar_tv(
        "setPictureMode",
        f"Modo de imagem definido para {modo}.",
        capacidade="custom.picturemode",
        argumentos=[modo],
    )


def status_casa():
    id_tv = obter_id_tv() or obter_id_tv(forcar_atualizacao=True)
    if not id_tv:
        return obter_mensagem_falha(forcar_atualizacao=False)

    dados_tv = realizar_requisicao_get(f"devices/{id_tv}/status")
    if not dados_tv:
        return falha("Sem resposta dos servidores da Samsung (status da TV).")

    try:
        estado_atual = dados_tv["components"]["main"]["switch"]["switch"]["value"]
    except (KeyError, TypeError):
        return falha("Status da TV indisponível: resposta sem o campo 'switch'.")

    if estado_atual == "on":
        partes = ["A televisão está ligada no momento."]
        status_canal = obter_status_canal()
        if status_canal:
            if status_canal.get("nome"):
                partes.append(f"No canal {status_canal.get('numero')} ({status_canal['nome']}).")
            elif status_canal.get("numero") is not None:
                partes.append(f"No canal {status_canal.get('numero')}.")
        status_volume = obter_volume()
        if status_volume and status_volume.get("volume") is not None:
            sufixo_mudo = " (no mudo)" if status_volume.get("mudo") else ""
            partes.append(f"Volume em {status_volume['volume']}{sufixo_mudo}.")
        return " ".join(partes)
    if estado_atual == "off":
        return "A televisão está desligada no momento."
    return falha("Status da TV desconhecido: %r.", estado_atual)
