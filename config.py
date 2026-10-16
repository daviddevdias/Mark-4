import copy
import json
import logging
import math
import os
import quopri
import re
import secrets
import shutil
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
    DATA_DIR = (
        Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Mark2Jarvis" / "data"
    )
else:
    BASE_DIR = Path(__file__).resolve().parent
    DATA_DIR = BASE_DIR / "data"

CONFIG_FILE = DATA_DIR / "config_mark2.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

log = logging.getLogger("mark2.config")

CONFIG_LOCK = threading.RLock()

MAC_PATTERN = re.compile("^(?:[0-9a-f]{2}:){5}[0-9a-f]{2}$")

TOKEN_REMOTO_PATTERN = re.compile("^[A-Za-z0-9._~-]{8,512}$")

MAX_CONFIG_BYTES = 5 * 1024 * 1024
MAX_VCF_BYTES = 20 * 1024 * 1024


# Carrega configuracoes
def carregar_configuracoes() -> dict:
    with CONFIG_LOCK:
        try:
            if not CONFIG_FILE.is_file():
                return {}
            if CONFIG_FILE.stat().st_size > MAX_CONFIG_BYTES:
                log.error("Arquivo de configuração excede o limite de tamanho.")
                return {}
            dados = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            log.error("Não foi possível carregar as configurações.", exc_info=True)
            return {}

    if not isinstance(dados, dict):
        log.error("O arquivo de configuração não contém um objeto JSON válido.")
        return {}
    return dados


# Salva configuracoes
def salvar_configuracoes(dados: dict) -> bool:
    if not isinstance(dados, dict):
        return False

    caminho_temporario = None
    with CONFIG_LOCK:
        try:
            copia_dados = copy.deepcopy(dados)
            conteudo = json.dumps(
                copia_dados,
                indent=4,
                ensure_ascii=False,
                allow_nan=False,
            )
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=DATA_DIR,
                prefix=f".{CONFIG_FILE.name}.",
                suffix=".tmp",
                delete=False,
            ) as arquivo_temporario:
                caminho_temporario = Path(arquivo_temporario.name)
                arquivo_temporario.write(conteudo)
                arquivo_temporario.write("\n")
                arquivo_temporario.flush()
                os.fsync(arquivo_temporario.fileno())
            os.replace(caminho_temporario, CONFIG_FILE)
            return True
        except (OSError, TypeError, ValueError):
            log.error("Não foi possível salvar as configurações.", exc_info=True)
            if caminho_temporario is not None:
                try:
                    caminho_temporario.unlink(missing_ok=True)
                except OSError:
                    pass
            return False


# Consulta texto
def obter_texto(chave: str, padrao: str, limite: int = 500) -> str:
    valor = configuracoes_locais.get(chave, padrao)
    if not isinstance(valor, str):
        return padrao
    valor = valor.strip()
    return valor[:limite] if valor else padrao


# Consulta bool
def obter_bool(chave: str, padrao: bool) -> bool:
    valor = configuracoes_locais.get(chave, padrao)
    return valor if isinstance(valor, bool) else padrao


# Consulta numero
def obter_numero(
    chave: str,
    padrao: float,
    minimo: float,
    maximo: float,
) -> float:
    valor = configuracoes_locais.get(chave, padrao)
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return padrao
    valor = float(valor)
    if not math.isfinite(valor) or not minimo <= valor <= maximo:
        return padrao
    return valor


# Consulta mapa texto
def obter_mapa_texto(chave: str) -> dict[str, str]:
    valor = configuracoes_locais.get(chave, {})
    if not isinstance(valor, dict):
        return {}
    return {
        chave_item: valor_item
        for chave_item, valor_item in valor.items()
        if isinstance(chave_item, str) and isinstance(valor_item, str)
    }


def persistir_valor(chave: str, valor) -> bool:
    with CONFIG_LOCK:
        novos_dados = copy.deepcopy(configuracoes_locais)
        novos_dados[chave] = copy.deepcopy(valor)
        if not salvar_configuracoes(novos_dados):
            return False
        configuracoes_locais.clear()
        configuracoes_locais.update(novos_dados)
        return True


configuracoes_locais = carregar_configuracoes()


NOME_MESTRE = obter_texto("nome_mestre", "", 100)

VOZ_ATIVA = obter_bool("voz_ativa", True)
VOZ_FALLBACK_PIPER = obter_bool("voz_fallback_piper", False)


VOZ_INICIAR_AUTOMATICO = obter_bool("voz_iniciar_automatico", True)


JANELA_CONTINUACAO_S = max(15, obter_numero("janela_continuacao_segundos", 15, 2, 30))

VOLUME_PADRAO = obter_numero("volume_padrao", 1.0, 0.0, 1.0)

MUSICA_CHEGADA_ATIVA = obter_bool("musica_chegada_ativa", False)

ABRIR_APPS_AO_CHEGAR = obter_bool("abrir_apps_ao_chegar", False)
FECHAR_APPS_AO_SAIR = obter_bool("fechar_apps_ao_sair", False)


PRESENCA_ATIVA = obter_bool("presenca_ativa", True)
CELULAR_IP_LOCAL = obter_texto("celular_ip_local", "", 64)
CELULAR_TAILSCALE = obter_texto("celular_tailscale", "", 200)
PRESENCA_INTERVALO_S = obter_numero("presenca_intervalo_segundos", 15, 5, 300)
PRESENCA_AUSENCIA_S = obter_numero("presenca_ausencia_segundos", 300, 30, 86400)
PRESENCA_COOLDOWN_S = obter_numero("presenca_cooldown_segundos", 1800, 60, 86400)

TICKTICK_CLIENT_ID = obter_texto("ticktick_client_id", "")
TICKTICK_CLIENT_SECRET = obter_texto("ticktick_client_secret", "")
TICKTICK_PROJECT_ID = obter_texto("ticktick_project_id", "")

MAX_CONTATOS_WHATSAPP = 100

_orcamento_configurado = configuracoes_locais.get("orcamento_tokens_historico", 6000)

if (
    isinstance(_orcamento_configurado, bool)
    or not isinstance(_orcamento_configurado, int)
    or not 256 <= _orcamento_configurado <= 1_000_000
):
    _orcamento_configurado = 6000

ORCAMENTO_TOKENS_HISTORICO = _orcamento_configurado

LLM_LOCAL_URL = obter_texto("llm_local_url", "http://localhost:1234/v1", 2048)
LLM_LOCAL_MODELO = obter_texto("llm_local_modelo", "qwen3-8b", 200)
LLM_LOCAL_QUANTIZACAO = "Q4_K_M"
LLM_VISAO_MODELO = obter_texto("llm_visao_modelo", "", 200)

CAMERA_INDICE = int(obter_numero("camera_indice", 0, 0, 10))


CAMERA_A28_URL = obter_texto("camera_a28_url", "rtsp://127.0.0.1:8554/a28", 2048)

CAMERA_FALA_GANHO = 8.0
CAMERA_FALA_ATRASO_S = obter_numero("camera_fala_atraso_s", 1.2, 0, 120)

VIGIA_ATIVO = obter_bool("vigia_ativo", True)
VIGIA_FPS_ALVO = 60
VIGIA_INTERVALO_S = obter_numero("vigia_intervalo_s", 1.5, 1, 60)
VIGIA_POSE_ATIVO = obter_bool("vigia_pose_ativo", True)
VIGIA_MODELO_POSE = obter_texto(
    "vigia_modelo_pose", str(DATA_DIR / "vigia" / "modelos" / "yolo11n-pose.pt"), 512
)
VIGIA_COOLDOWN_S = 60
VIGIA_SOMENTE_AUSENTE = obter_bool("vigia_somente_ausente", False)
VIGIA_DESCREVER = obter_bool("vigia_descrever", True)
VIGIA_RETENCAO_DIAS = int(obter_numero("vigia_retencao_dias", 7, 1, 90))
VIGIA_GRAVAR_VIDEO = obter_bool("vigia_gravar_video", True)
VIGIA_PREGRAVACAO_S = obter_numero("vigia_pregravacao_s", 5, 0, 15)
VIGIA_POSGRAVACAO_S = obter_numero("vigia_posgravacao_s", 15, 3, 120)
ABRIR_TELA_ALERTA_CAMERA = obter_bool("abrir_tela_alerta_camera", True)


VIGIA_LIMIAR_NOITE = 70
VIGIA_CONSECUTIVAS = 3


VIGIA_MOV_LIMIAR_PIX = 18
VIGIA_MOV_LIMIAR_FRAC = 0.004


ESCUTA_PAUSA_S = 0.6


CAMERA_FALA_ATIVA = obter_bool("camera_fala_ativa", True)
CAMERA_ONVIF_HOST = obter_texto("camera_onvif_host", "", 253)
CAMERA_ONVIF_PORTA = int(obter_numero("camera_onvif_porta", 8899, 1, 65535))
CAMERA_ONVIF_USUARIO = obter_texto("camera_onvif_usuario", "", 128)
CAMERA_ONVIF_SENHA = configuracoes_locais.get("camera_onvif_senha", "")
if not isinstance(CAMERA_ONVIF_SENHA, str):
    CAMERA_ONVIF_SENHA = ""
VIGIA_PTZ_ATIVO = obter_bool("vigia_ptz_ativo", False)
GO2RTC_URL = "http://127.0.0.1:1984"
GO2RTC_STREAM = "a28_voz"
GO2RTC_AUTOSTART = True

VIGIA_DUAS_LENTES = True
VIGIA_DIVISAO_Y = 0.5
VIGIA_LENTES_SOMAR = False

GO2RTC_EXE = str(BASE_DIR / "go2rtc" / "go2rtc.exe")

SEGURANCA_ATIVA = obter_bool("seguranca_ativa", True)
SEGURANCA_AUTO = obter_bool("seguranca_auto", True)
SEGURANCA_AGENDA_ATIVA = obter_bool("seguranca_agenda_ativa", False)
SEGURANCA_HORA_INICIO = obter_texto("seguranca_hora_inicio", "06:00", 5)
SEGURANCA_HORA_FIM = obter_texto("seguranca_hora_fim", "23:00", 5)
SEGURANCA_CONTATO_ALERTA = obter_texto("seguranca_contato_alerta", "", 120)
SEGURANCA_JANELA_ESCALADA_S = obter_numero(
    "seguranca_janela_escalada_segundos", 300, 30, 3600
)
SEGURANCA_VISAO_CHEGADA = obter_bool("seguranca_visao_chegada", True)


# Consulta token remoto
def obter_token_remoto() -> str:
    token = configuracoes_locais.get("token_remoto")
    if isinstance(token, str):
        token_limpo = token.strip()
        if token == token_limpo and TOKEN_REMOTO_PATTERN.fullmatch(token_limpo):
            return token_limpo
    token = secrets.token_urlsafe(32)
    if not persistir_valor("token_remoto", token):
        log.critical("Não foi possível persistir o token de acesso remoto.")
    return token


TOKEN_REMOTO = obter_token_remoto()

opcoesPainel = {
    "VIGIA_ATIVO": (
        "vigia_ativo",
        "bool",
        "Monitorar a camera A28",
        "Camera e seguranca",
        False,
    ),
    "VIGIA_POSE_ATIVO": (
        "vigia_pose_ativo",
        "bool",
        "Deteccao de pose YOLO11",
        "Camera e seguranca",
        False,
    ),
    "VIGIA_GRAVAR_VIDEO": (
        "vigia_gravar_video",
        "bool",
        "Salvar fotos e vídeos quando houver movimento",
        "Camera e seguranca",
        False,
    ),
    "VIGIA_RETENCAO_DIAS": (
        "vigia_retencao_dias",
        "numero",
        "Manter gravacoes por (dias)",
        "Camera e seguranca",
        False,
    ),
    "VIGIA_PREGRAVACAO_S": (
        "vigia_pregravacao_s",
        "numero",
        "Segundos antes do movimento",
        "Camera e seguranca",
        False,
    ),
    "VIGIA_POSGRAVACAO_S": (
        "vigia_posgravacao_s",
        "numero",
        "Segundos depois do movimento",
        "Camera e seguranca",
        False,
    ),
    "VIGIA_PTZ_ATIVO": (
        "vigia_ptz_ativo",
        "bool",
        "Seguir pessoa com a lente PTZ",
        "Camera e seguranca",
        False,
    ),
    "ABRIR_TELA_ALERTA_CAMERA": (
        "abrir_tela_alerta_camera",
        "bool",
        "Abrir tela do alerta automaticamente",
        "Camera e seguranca",
        False,
    ),
    "CAMERA_FALA_ATRASO_S": (
        "camera_fala_atraso_s",
        "numero",
        "Pausa antes de falar pela camera (segundos)",
        "Camera e seguranca",
        False,
    ),
    "VOZ_ATIVA": ("voz_ativa", "bool", "Voz do Jarvis", "Sistema", False),
    "VOZ_FALLBACK_PIPER": ("voz_fallback_piper", "bool", "Permitir voz Piper quando ElevenLabs falhar", "Sistema", False),
    "VOZ_INICIAR_AUTOMATICO": (
        "voz_iniciar_automatico",
        "bool",
        "Iniciar escuta com o sistema",
        "Sistema",
        False,
    ),
    "MUSICA_CHEGADA_ATIVA": (
        "musica_chegada_ativa",
        "bool",
        "Música ao chegar",
        "Rotinas",
        False,
    ),
    "ABRIR_APPS_AO_CHEGAR": (
        "abrir_apps_ao_chegar",
        "bool",
        "Abrir aplicativos ao chegar",
        "Rotinas",
        False,
    ),
    "FECHAR_APPS_AO_SAIR": (
        "fechar_apps_ao_sair",
        "bool",
        "Fechar aplicativos ao sair",
        "Rotinas",
        False,
    ),
    "PRESENCA_ATIVA": (
        "presenca_ativa",
        "bool",
        "Detectar chegada do celular",
        "Presença",
        False,
    ),
    "VIGIA_SOMENTE_AUSENTE": (
        "vigia_somente_ausente",
        "bool",
        "Ignorar câmera quando estou em casa",
        "Câmera e segurança",
        False,
    ),
    "VIGIA_DESCREVER": (
        "vigia_descrever",
        "bool",
        "Descrever pessoa detectada",
        "Câmera e segurança",
        False,
    ),
    "CAMERA_FALA_ATIVA": (
        "camera_fala_ativa",
        "bool",
        "Fala da câmera",
        "Câmera e segurança",
        False,
    ),
    "SEGURANCA_ATIVA": (
        "seguranca_ativa",
        "bool",
        "Protocolo Torre Stark",
        "Câmera e segurança",
        False,
    ),
    "SEGURANCA_AUTO": (
        "seguranca_auto",
        "bool",
        "Armar segurança automaticamente",
        "Câmera e segurança",
        False,
    ),
    "SEGURANCA_AGENDA_ATIVA": (
        "seguranca_agenda_ativa",
        "bool",
        "Armar e desarmar por horário",
        "Câmera e segurança",
        False,
    ),
    "SEGURANCA_HORA_INICIO": (
        "seguranca_hora_inicio",
        "hora",
        "Iniciar Protocolo Torre Stark",
        "Câmera e segurança",
        False,
    ),
    "SEGURANCA_HORA_FIM": (
        "seguranca_hora_fim",
        "hora",
        "Encerrar Protocolo Torre Stark",
        "Câmera e segurança",
        False,
    ),
    "JANELA_CONTINUACAO_S": (
        "janela_continuacao_segundos",
        "numero",
        "Tempo para continuar falando (segundos)",
        "Voz",
        False,
    ),
    "VOLUME_PADRAO": ("volume_padrao", "numero", "Volume do Jarvis", "Voz", False),
    "PRESENCA_INTERVALO_S": (
        "presenca_intervalo_segundos",
        "numero",
        "Intervalo de verificação (segundos)",
        "Presença",
        False,
    ),
    "PRESENCA_AUSENCIA_S": (
        "presenca_ausencia_segundos",
        "numero",
        "Tempo para considerar ausente (segundos)",
        "Presença",
        False,
    ),
    "PRESENCA_COOLDOWN_S": (
        "presenca_cooldown_segundos",
        "numero",
        "Aguardar antes de avisar novamente (segundos)",
        "Presença",
        False,
    ),
}


# Lista opcoes
def listarOpcoes():
    itens = []
    limites = {
        "VOLUME_PADRAO": (0, 1),
        "JANELA_CONTINUACAO_S": (2, 30),
        "VIGIA_RETENCAO_DIAS": (1, 90),
        "VIGIA_PREGRAVACAO_S": (0, 15),
        "VIGIA_POSGRAVACAO_S": (3, 120),
        "CAMERA_FALA_ATRASO_S": (0, 120),
        "PRESENCA_INTERVALO_S": (5, 300),
        "PRESENCA_AUSENCIA_S": (30, 86400),
        "PRESENCA_COOLDOWN_S": (60, 86400),
    }
    for chave, (salva, tipo, rotulo, grupo, reinicia) in opcoesPainel.items():
        valor = globals().get(chave)
        minimo, maximo = limites.get(
            chave, (1, 86400) if tipo == "numero" else (None, None)
        )
        itens.append(
            {
                "chave": chave,
                "valor": valor,
                "tipo": tipo,
                "rotulo": rotulo,
                "grupo": grupo,
                "reinicia": reinicia,
                "minimo": minimo,
                "maximo": maximo,
                "passo": 1 if tipo == "numero" else None,
            }
        )
    return itens


def definirOpcao(chave, valor):
    if not isinstance(chave, str) or chave not in opcoesPainel:
        return False, "Esta opção não está disponível."
    salva, tipo, rotulo, grupo, reinicia = opcoesPainel[chave]
    if tipo == "bool" and not isinstance(valor, bool):
        return False, "Informe ligado ou desligado."
    if tipo == "hora":
        if not isinstance(valor, str) or not re.fullmatch(
            r"(?:[01]\d|2[0-3]):[0-5]\d", valor
        ):
            return False, "Informe um hor\u00e1rio entre 00:00 e 23:59."
    if tipo == "numero":
        limites = {
            "VOLUME_PADRAO": (0, 1),
            "JANELA_CONTINUACAO_S": (2, 30),
            "VIGIA_RETENCAO_DIAS": (1, 90),
            "VIGIA_PREGRAVACAO_S": (0, 15),
            "VIGIA_POSGRAVACAO_S": (3, 120),
            "CAMERA_FALA_ATRASO_S": (0, 120),
            "PRESENCA_INTERVALO_S": (5, 300),
            "PRESENCA_AUSENCIA_S": (30, 86400),
            "PRESENCA_COOLDOWN_S": (60, 86400),
        }
        minimo, maximo = limites.get(chave, (1, 86400))
        if (
            isinstance(valor, bool)
            or not isinstance(valor, (int, float))
            or not math.isfinite(valor)
            or not minimo <= valor <= maximo
        ):
            return False, "O valor está fora do intervalo permitido."
        valor = float(valor)
    if not persistir_valor(salva, valor):
        return False, "Não foi possível salvar a opção."
    globals()[chave] = valor
    return True, {"chave": chave, "valor": valor, "reinicia": reinicia}


# Define apps chegada ativos
def definir_apps_chegada_ativos(ativo: bool) -> bool:
    global ABRIR_APPS_AO_CHEGAR
    if not isinstance(ativo, bool) or not persistir_valor(
        "abrir_apps_ao_chegar", ativo
    ):
        return False
    ABRIR_APPS_AO_CHEGAR = ativo
    return True


# Define fechar apps ao sair
def definir_fechar_apps_ao_sair(ativo: bool) -> bool:
    global FECHAR_APPS_AO_SAIR
    if not isinstance(ativo, bool) or not persistir_valor("fechar_apps_ao_sair", ativo):
        return False
    FECHAR_APPS_AO_SAIR = ativo
    return True


# Define musica chegada ativa
def definir_musica_chegada_ativa(ativa: bool) -> bool:
    global MUSICA_CHEGADA_ATIVA
    if not isinstance(ativa, bool):
        return False
    if not persistir_valor("musica_chegada_ativa", ativa):
        return False
    MUSICA_CHEGADA_ATIVA = ativa
    return True


# Define voz ativa
def definir_voz_ativa(ativa: bool) -> bool:
    global VOZ_ATIVA
    if not isinstance(ativa, bool):
        return False
    if not persistir_valor("voz_ativa", ativa):
        return False
    VOZ_ATIVA = ativa
    return True


# Define smartthings token
def definir_smartthings_token(token: str) -> bool:
    if not isinstance(token, str):
        return False
    token = token.strip()
    if len(token) > 2048 or any(caractere.isspace() for caractere in token):
        return False
    if token.lower().startswith("code:"):
        from comandos.automacao import smartthings_auth

        return smartthings_auth.trocar_codigo(token[5:])
    return persistir_valor("smartthings_token", token)


# Consulta smartthings token
def obter_smartthings_token() -> str:
    with CONFIG_LOCK:
        token = configuracoes_locais.get("smartthings_token")
        return token.strip() if isinstance(token, str) else ""


# Lista contatos WhatsApp
def listar_contatos_whatsapp() -> dict:
    with CONFIG_LOCK:
        return obter_mapa_texto("contatos_whatsapp").copy()


# Normaliza contato
def normalizar_contato(nome: str, numero: str) -> tuple[str, str] | None:
    if not isinstance(nome, str) or not isinstance(numero, str):
        return None
    nome_normalizado = " ".join(nome.split()).strip()
    numero_normalizado = "".join(
        caractere for caractere in numero if caractere.isdigit()
    )
    if not nome_normalizado or len(nome_normalizado) > 120:
        return None
    if not 7 <= len(numero_normalizado) <= 15:
        return None
    return nome_normalizado, numero_normalizado


def localizar_chave(mapa: dict[str, str], nome: str) -> str | None:
    if nome in mapa:
        return nome
    nome_comparavel = nome.casefold()
    return next(
        (chave for chave in mapa if chave.casefold() == nome_comparavel),
        None,
    )


def adicionar_contato_whatsapp(nome: str, numero: str) -> tuple:
    contato = normalizar_contato(nome, numero)
    if contato is None:
        return False, "Informe um nome e um número válido com 7 a 15 dígitos."
    nome, numero = contato

    with CONFIG_LOCK:
        contatos = obter_mapa_texto("contatos_whatsapp")
        chave_existente = localizar_chave(contatos, nome)
        if chave_existente is None and len(contatos) >= MAX_CONTATOS_WHATSAPP:
            return False, f"Limite de {MAX_CONTATOS_WHATSAPP} contatos atingido."
        if chave_existente is not None and chave_existente != nome:
            return False, f"Aá existe um contato chamado '{chave_existente}'."
        contatos[nome] = numero
        if not persistir_valor("contatos_whatsapp", contatos):
            return False, "Não foi possível salvar o contato."
    return True, f"Contato '{nome}' salvo com sucesso."


# Remove contato WhatsApp
def remover_contato_whatsapp(nome: str) -> tuple:
    if not isinstance(nome, str) or not nome.strip():
        return False, "Informe o nome do contato."

    with CONFIG_LOCK:
        contatos = obter_mapa_texto("contatos_whatsapp")
        chave = localizar_chave(contatos, " ".join(nome.split()))
        if chave is None:
            return False, f"Contato '{nome.strip()}' não encontrado."
        del contatos[chave]
        if not persistir_valor("contatos_whatsapp", contatos):
            return False, "Não foi possível remover o contato."
    return True, f"Contato '{chave}' removido com sucesso."


def renomear_contato_whatsapp(nome_atual: str, novo_nome: str, numero: str) -> tuple:
    contato = normalizar_contato(novo_nome, numero)
    if contato is None or not isinstance(nome_atual, str):
        return False, "Informe um nome e um número válido com 7 a 15 dígitos."
    novo_nome, numero = contato

    with CONFIG_LOCK:
        contatos = obter_mapa_texto("contatos_whatsapp")
        chave_atual = localizar_chave(contatos, " ".join(nome_atual.split()))
        if chave_atual is None:
            return False, f"Contato '{nome_atual.strip()}' não encontrado."
        chave_destino = localizar_chave(contatos, novo_nome)
        if chave_destino is not None and chave_destino != chave_atual:
            return False, f"Aá existe um contato chamado '{chave_destino}'."
        del contatos[chave_atual]
        contatos[novo_nome] = numero
        if not persistir_valor("contatos_whatsapp", contatos):
            return False, "Não foi possível salvar a alteração."
    return True, f"Contato '{chave_atual}' renomeado para '{novo_nome}'."


def decodificar_valor_vcard(valor: str, metadados: str) -> str:
    if "ENCODING=QUOTED-PRINTABLE" in metadados.upper():
        try:
            dados_decodificados = quopri.decodestring(valor)
            correspondencia_charset = re.search(
                '(?:^|;)CHARSET=(?:\\"([^\\"]+)\\"|([^;:]+))',
                metadados,
                flags=re.IGNORECASE,
            )
            charset = ""
            if correspondencia_charset:
                charset = (
                    (
                        correspondencia_charset.group(1)
                        or correspondencia_charset.group(2)
                        or ""
                    )
                    .strip()
                    .casefold()
                    .replace("_", "-")
                )
            aliases_charset = {
                "utf8": "utf-8",
                "utf-8": "utf-8",
                "iso-8859-1": "latin-1",
                "iso8859-1": "latin-1",
                "latin1": "latin-1",
                "latin-1": "latin-1",
                "windows-1252": "cp1252",
                "cp1252": "cp1252",
                "us-ascii": "ascii",
                "ascii": "ascii",
            }
            codificacoes = [
                aliases_charset.get(charset),
                "utf-8",
                "cp1252",
                "latin-1",
            ]
            for codificacao in dict.fromkeys(
                item for item in codificacoes if item is not None
            ):
                try:
                    valor = dados_decodificados.decode(codificacao)
                    break
                except UnicodeDecodeError:
                    continue
        except (UnicodeError, ValueError):
            pass
    return (
        valor.replace("\\n", " ")
        .replace("\\N", " ")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
        .strip()
    )


def importar_contatos_vcf(caminho_arquivo: str) -> tuple:
    if not isinstance(caminho_arquivo, (str, os.PathLike)):
        return 0, "Não foi possível ler o arquivo .vcf."

    try:
        caminho = Path(caminho_arquivo)
        if not caminho.is_file() or caminho.stat().st_size > MAX_VCF_BYTES:
            return 0, "O arquivo .vcf não existe ou excede o limite de 20 MB."
        dados = caminho.read_bytes()
        try:
            conteudo = dados.decode("utf-8-sig")
        except UnicodeDecodeError:
            conteudo = dados.decode("cp1252")
    except (OSError, UnicodeError):
        return 0, "Não foi possível ler o arquivo .vcf."

    linhas_desdobradas = []
    for linha in conteudo.splitlines():
        if linha.startswith((" ", "\t")) and linhas_desdobradas:
            linhas_desdobradas[-1] += linha[1:]
        else:
            linhas_desdobradas.append(linha)

    contatos_importados = []
    nome_encontrado = None
    numero_encontrado = None
    dentro_vcard = False
    total_ignorados = 0

    for linha in linhas_desdobradas:
        linha_limpa = linha.strip()
        if linha_limpa.upper() == "BEGIN:VCARD":
            dentro_vcard = True
            nome_encontrado = None
            numero_encontrado = None
            continue
        if linha_limpa.upper() == "END:VCARD":
            if dentro_vcard:
                contato = normalizar_contato(
                    nome_encontrado or "",
                    numero_encontrado or "",
                )
                if contato is None:
                    total_ignorados += 1
                else:
                    contatos_importados.append(contato)
            dentro_vcard = False
            continue
        if not dentro_vcard or ":" not in linha_limpa:
            continue

        metadados, valor = linha_limpa.split(":", 1)
        propriedade = metadados.split(";", 1)[0].split(".")[-1].upper()
        valor = decodificar_valor_vcard(valor, metadados)
        if propriedade == "FN" and not nome_encontrado:
            nome_encontrado = valor
        elif propriedade == "TEL" and not numero_encontrado:
            numero_encontrado = valor

    if not contatos_importados:
        return 0, f"0 contato(s) importado(s), {total_ignorados} ignorado(s)."

    total_importados = 0
    with CONFIG_LOCK:
        contatos = obter_mapa_texto("contatos_whatsapp")
        for nome, numero in contatos_importados:
            chave_existente = localizar_chave(contatos, nome)
            if chave_existente is None and len(contatos) >= MAX_CONTATOS_WHATSAPP:
                total_ignorados += 1
                continue
            if chave_existente is not None and chave_existente != nome:
                nome = chave_existente
            contatos[nome] = numero
            total_importados += 1
        if total_importados and not persistir_valor("contatos_whatsapp", contatos):
            return 0, "Não foi possível salvar os contatos importados."

    return (
        total_importados,
        f"{total_importados} contato(s) importado(s), {total_ignorados} ignorado(s).",
    )


def expandir_item_comando(item: str) -> str:
    return os.path.expandvars(os.path.expanduser(item.strip()))


def comando_configurado(chave: str) -> list[str] | None:
    valor = configuracoes_locais.get(chave)
    if isinstance(valor, str) and valor.strip():
        return [expandir_item_comando(valor)]
    if (
        isinstance(valor, (list, tuple))
        and valor
        and all(isinstance(item, str) and item.strip() for item in valor)
    ):
        return [expandir_item_comando(item) for item in valor]
    return None


def primeiro_executavel(candidatos: list[Path | None], nomes_path: tuple[str, ...]):
    for candidato in candidatos:
        if candidato is not None and candidato.is_file():
            return str(candidato)
    for nome in nomes_path:
        encontrado = shutil.which(nome)
        if encontrado:
            return encontrado
    return None


def descobrir_vscode() -> list[str] | None:
    configurado = comando_configurado("caminho_vscode")
    if configurado:
        return configurado
    local_app_data = os.environ.get("LOCALAPPDATA")
    program_files = os.environ.get("ProgramFiles")
    program_files_x86 = os.environ.get("ProgramFiles(x86)")
    executavel = primeiro_executavel(
        [
            (
                Path(local_app_data) / "Programs" / "Microsoft VS Code" / "Code.exe"
                if local_app_data
                else None
            ),
            (
                Path(program_files) / "Microsoft VS Code" / "Code.exe"
                if program_files
                else None
            ),
            (
                Path(program_files_x86) / "Microsoft VS Code" / "Code.exe"
                if program_files_x86
                else None
            ),
        ],
        ("code", "Code.exe"),
    )
    return [executavel] if executavel else None


def descobrir_discord() -> list[str] | None:
    configurado = comando_configurado("caminho_discord")
    if configurado:
        return configurado
    local_app_data = os.environ.get("LOCALAPPDATA")
    atualizador = (
        Path(local_app_data) / "Discord" / "Update.exe" if local_app_data else None
    )
    if atualizador is not None and atualizador.is_file():
        return [str(atualizador), "processStart", "Discord.exe"]
    executavel = primeiro_executavel([], ("Discord.exe", "discord"))
    return [executavel] if executavel else None


def descobrir_spotify() -> list[str] | None:
    configurado = comando_configurado("caminho_spotify")
    if configurado:
        return configurado
    app_data = os.environ.get("APPDATA")
    local_app_data = os.environ.get("LOCALAPPDATA")
    executavel = primeiro_executavel(
        [
            Path(app_data) / "Spotify" / "Spotify.exe" if app_data else None,
            (
                Path(local_app_data) / "Microsoft" / "WindowsApps" / "Spotify.exe"
                if local_app_data
                else None
            ),
        ],
        ("Spotify.exe", "spotify"),
    )
    return [executavel] if executavel else None


CAMINHO_VSCODE = descobrir_vscode()

CAMINHO_DISCORD = descobrir_discord()

CAMINHO_SPOTIFY = descobrir_spotify()

LATITUDE = obter_numero("latitude", -29.85, -90.0, 90.0)
LONGITUDE = obter_numero("longitude", -51.18, -180.0, 180.0)

SPOTIFY_PLAYLIST_CHEGADA = obter_texto(
    "spotify_playlist_chegada", "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M", 2048
)

LINK_YOUTUBE_CHEGADA = obter_texto(
    "link_youtube_chegada",
    "https://www.youtube.com/watch?v=pAgnJDJN4VA&list=RDjNo3zmhXE9Y&index=2",
    2048,
)


# Lista dispositivos confiaveis
def listar_dispositivos_confiaveis() -> dict:
    with CONFIG_LOCK:
        dispositivos = obter_mapa_texto("dispositivos_confiaveis")
        return {
            mac.strip().lower().replace("-", ":"): nome
            for mac, nome in dispositivos.items()
            if MAC_PATTERN.fullmatch(mac.strip().lower().replace("-", ":"))
            and nome.strip()
        }


# Registra dispositivo confiavel
def registrar_dispositivo_confiavel(mac: str, nome: str) -> tuple:
    if not isinstance(mac, str) or not isinstance(nome, str):
        return False, "MAC e nome são obrigatórios."
    mac = mac.strip().lower().replace("-", ":")
    nome = " ".join(nome.split()).strip()
    if not MAC_PATTERN.fullmatch(mac):
        return False, "Informe um endereço MAC válido."
    if not nome or len(nome) > 120:
        return False, "Informe um nome válido para o dispositivo."

    with CONFIG_LOCK:
        dispositivos = listar_dispositivos_confiaveis()
        dispositivos[mac] = nome
        if not persistir_valor("dispositivos_confiaveis", dispositivos):
            return False, "Não foi possível salvar o dispositivo."

        ignorados = listar_dispositivos_ignorados()
        if mac in ignorados:
            ignorados.pop(mac)
            persistir_valor("dispositivos_ignorados", ignorados)
    return True, f"Dispositivo '{nome}' registrado como confiável."


# Remove dispositivo confiavel
def remover_dispositivo_confiavel(mac: str) -> tuple:
    if not isinstance(mac, str):
        return False, "Informe um endereço MAC válido."
    mac = mac.strip().lower().replace("-", ":")
    if not MAC_PATTERN.fullmatch(mac):
        return False, "Informe um endereço MAC válido."

    with CONFIG_LOCK:
        dispositivos = listar_dispositivos_confiaveis()
        if mac not in dispositivos:
            return False, "Dispositivo não encontrado na lista de confiáveis."
        nome = dispositivos.pop(mac)
        if not persistir_valor("dispositivos_confiaveis", dispositivos):
            return False, "Não foi possível salvar a alteração."
    return True, f"'{nome}' removido da lista de dispositivos confiáveis."


# Lista dispositivos ignorados
def listar_dispositivos_ignorados() -> dict:
    with CONFIG_LOCK:
        dispositivos = obter_mapa_texto("dispositivos_ignorados")
        return {
            mac.strip().lower().replace("-", ":"): data
            for mac, data in dispositivos.items()
            if MAC_PATTERN.fullmatch(mac.strip().lower().replace("-", ":"))
        }


def ignorar_dispositivo(mac: str, nome: str = "") -> tuple:
    if not isinstance(mac, str):
        return False, "Informe um endereço MAC válido."
    mac = mac.strip().lower().replace("-", ":")
    if not MAC_PATTERN.fullmatch(mac):
        return False, "Informe um endereço MAC válido."
    nome = " ".join(nome.split()).strip()[:120] if isinstance(nome, str) else ""

    with CONFIG_LOCK:
        dispositivos = listar_dispositivos_ignorados()
        dispositivos[mac] = json.dumps(
            {"nome": nome, "desde": datetime.now().isoformat(timespec="seconds")},
            ensure_ascii=False,
        )
        if not persistir_valor("dispositivos_ignorados", dispositivos):
            return False, "Não foi possível salvar o dispositivo."
    return True, "Dispositivo ignorado. Ele não vai mais aparecer nem gerar avisos."


# Remove dispositivo ignorado
def remover_dispositivo_ignorado(mac: str) -> tuple:
    if not isinstance(mac, str):
        return False, "Informe um endereço MAC válido."
    mac = mac.strip().lower().replace("-", ":")
    if not MAC_PATTERN.fullmatch(mac):
        return False, "Informe um endereço MAC válido."

    with CONFIG_LOCK:
        dispositivos = listar_dispositivos_ignorados()
        if mac not in dispositivos:
            return False, "Dispositivo não encontrado na lista de ignorados."
        dispositivos.pop(mac)
        if not persistir_valor("dispositivos_ignorados", dispositivos):
            return False, "Não foi possível salvar a alteração."
    return True, "Dispositivo removido da lista de ignorados."
