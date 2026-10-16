import asyncio
import json
import logging
import threading
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import config
from comandos import whatsapp_bot
from comandos.automacao import fala_camera, presenca, vigia_camera
from interface import voz

log = logging.getLogger("mark2.seguranca_stark")

ARQ_EVENTOS = config.DATA_DIR / "seguranca_eventos.jsonl"

TRAVA = threading.Lock()
PARAR = threading.Event()
THREAD = None
threadAgenda = None
CALLBACK_EVENTO = None

ESTADO = {
    "armado": False,
    "desde": None,
    "origem": None,
    "alertas": 0,
}

alertas_recentes = []

# Consulta opção de configuração
def cfg(nome, padrao):
    return getattr(config, nome, padrao)


# Gera data no formato ISO
def agora_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


# Consulta estado atual
def estado_atual():
    with TRAVA:
        return dict(ESTADO)


# Define retorno evento
def definir_callback_evento(callback):
    global CALLBACK_EVENTO
    CALLBACK_EVENTO = callback


# Registra evento
def registrar_evento(tipo, **dados):
    evento = {"hora": agora_iso(), "tipo": tipo, **dados}
    try:
        with TRAVA:
            with open(ARQ_EVENTOS, "a", encoding="utf-8") as arquivo:
                arquivo.write(json.dumps(evento, ensure_ascii=False) + "\n")
    except OSError:
        log.error("Não foi possível gravar o evento de segurança.", exc_info=True)



def ultimos_eventos(quantidade=5):
    try:
        with open(ARQ_EVENTOS, "r", encoding="utf-8") as arquivo:
            linhas = arquivo.readlines()[-quantidade:]
        return [json.loads(linha) for linha in linhas]
    except (OSError, json.JSONDecodeError):
        return []



def eventosEntre(inicio, fim, limite=200):
    encontrados = deque(maxlen=None if limite is None else max(1, min(1000, int(limite))))
    try:
        with open(ARQ_EVENTOS, "r", encoding="utf-8") as arquivo:
            for linha in arquivo:
                try:
                    evento = json.loads(linha)
                    quando = datetime.fromisoformat(evento["hora"])
                except (ValueError, KeyError, TypeError):
                    continue
                if inicio <= quando < fim:
                    encontrados.append(evento)
    except OSError:
        return []
    return list(encontrados)



def historico_pessoas(dias=7, limite=200):
    
    corte = datetime.now().astimezone() - timedelta(days=dias)
    saida = []
    try:
        with open(ARQ_EVENTOS, "r", encoding="utf-8") as arquivo:
            for linha in arquivo:
                try:
                    evento = json.loads(linha)
                    quando = datetime.fromisoformat(evento["hora"])
                except (ValueError, KeyError, TypeError):
                    continue
                if evento.get("tipo") != "pessoa" or quando < corte:
                    continue
                foto = (
                    str(evento.get("foto") or "").replace("\\", "/").rsplit("/", 1)[-1]
                )
                saida.append(
                    {
                        "hora": evento["hora"],
                        "foto": foto,
                        "quantidade": int(evento.get("quantidade") or 1),
                        "reincidente": bool(evento.get("reincidente")),
                        "armado": bool(evento.get("armado", True)),
                        "origem": str(evento.get("origem") or "deteccao"),
                    }
                )
    except OSError:
        return []
    return saida[-limite:]



def armar(origem="manual"):
    if not cfg("SEGURANCA_ATIVA", False):
        return "Protocolo Torre Stark desativado nas configura\u00e7\u00f5es, senhor."
    with TRAVA:
        if ESTADO["armado"]:
            return "O Protocolo Torre Stark já está armado, senhor."
        ESTADO.update(armado=True, desde=agora_iso(), origem=origem, alertas=0)
        alertas_recentes.clear()
    vigia_camera.definir_defesas_armadas(True)
    vigia_camera.iniciar(callback=ao_detectar)
    registrar_evento("armado", origem=origem)
    log.info("Protocolo Torre Stark armado (%s).", origem)
    return "Protocolo Torre Stark armado, senhor."



def desarmar(origem="manual"):
    with TRAVA:
        if not ESTADO["armado"]:
            vigia_camera.definir_defesas_armadas(False)
            return "O Protocolo Torre Stark j\u00e1 estava desarmado, senhor."
        ESTADO.update(armado=False, origem=origem)
    vigia_camera.definir_defesas_armadas(False)
    registrar_evento("desarmado", origem=origem)
    log.info("Protocolo Torre Stark desarmado (%s).", origem)
    return "Protocolo Torre Stark desarmado, senhor."



def relatorio():
    estado = estado_atual()
    camera = vigia_camera.estado_atual()
    partes = [
        "Protocolo Torre Stark armado." if estado["armado"] else "Protocolo Torre Stark desarmado."
    ]
    partes.append(
        "Câmera A28 online." if camera["conectada"] else "Câmera A28 fora de linha."
    )
    eventos = [e for e in ultimos_eventos(20) if e.get("tipo") == "pessoa"]
    if eventos:
        partes.append(f"Última detecção de pessoa em {eventos[-1]['hora']}.")
    else:
        partes.append("Nenhuma pessoa detectada até agora.")
    return " ".join(partes)


# Envia WhatsApp
def enviar_whatsapp(texto):
    nome = str(cfg("SEGURANCA_CONTATO_ALERTA", "")).strip()
    if not nome:
        return False
    contatos = config.listar_contatos_whatsapp()
    chave = config.localizar_chave(contatos, nome)
    if chave is None:
        log.warning("Contato de alerta '%s' não está na agenda do WhatsApp.", nome)
        return False
    try:
        resposta = asyncio.run(
            whatsapp_bot.enviar_mensagem_playwright(contatos[chave], texto)
        )
    except Exception:
        log.exception("Falha ao enviar o alerta por WhatsApp.")
        return False
    if "sucesso" not in str(resposta).lower():
        log.error("Alerta por WhatsApp não enviado: %s", resposta)
        return False
    return True



# Registra pessoa e avisa armado
def ao_detectar(
    caminho_foto,
    quantidade,
    origem="deteccao",
    sentido=None,
    reincidente=False,
):
    with TRAVA:
        armado = ESTADO["armado"]
        reincidente = bool(reincidente)
        if armado:
            ESTADO["alertas"] += 1

    if not armado:


        registrar_evento(
            "pessoa",
            quantidade=quantidade,
            foto=caminho_foto,
            reincidente=False,
            armado=False,
            origem=origem,
            sentido=sentido,
        )
        log.info("Pessoa detectada (desarmado): foto salva na timeline.")
        return

    registrar_evento(
        "pessoa",
        quantidade=quantidade,
        foto=caminho_foto,
        reincidente=reincidente,
        armado=True,
        origem=origem,
        sentido=sentido,
    )

    if CALLBACK_EVENTO is not None:
        try:
            CALLBACK_EVENTO({
                "event": "person", "eventType": "person", "hora": agora_iso(),
                "zoneName": "Camera A28", "persons": max(1, int(quantidade or 1)),
                "foto": Path(caminho_foto).name if caminho_foto else "",
                "alertAllowed": True, "armado": True, "origem": origem,
                "abrirTela": bool(cfg("ABRIR_TELA_ALERTA_CAMERA", True)),
            })
        except Exception:
            log.exception("Falha ao publicar a deteccao no painel.")

    threading.Thread(
        target=fala_camera.falar_aviso,
        args=(reincidente,),
        daemon=True,
        name="mark2-aviso-seguranca-camera",
    ).start()

    chegada = origem == "linha" and sentido == "positivo"
    saida = origem == "linha" and sentido == "negativo"
    threading.Thread(target=voz.falar, args=("Senhor, area restrita. Pessoa detectada no portao.",), daemon=True, name="mark2-aviso-portao").start()

    if cfg("VIGIA_DESCREVER", True):
        if chegada and cfg("SEGURANCA_VISAO_CHEGADA", True):
            prompt_visao = (
                "Analise visualmente a pessoa que acabou de chegar pela entrada. "
                "Faça uma descrição objetiva de corpo inteiro em no máximo duas frases: "
                "roupa e cores visíveis, postura, ação, objetos que carrega e onde "
                "está na cena. Não tente identificar a pessoa, não estime idade, "
                "não atribua identidade e não faça reconhecimento facial."
            )
        elif saida and cfg("SEGURANCA_VISAO_CHEGADA", True):
            prompt_visao = (
                "Analise visualmente a pessoa que acabou de sair pela linha de segurança. "
                "Em no máximo duas frases, descreva corpo inteiro, roupa e cores visíveis, "
                "postura, ação, objetos que carrega e localização. Não tente identificar "
                "a pessoa nem fazer reconhecimento facial."
            )
        else:
            prompt_visao = (
                "Descreva em no máximo duas frases a pessoa que aparece nesta "
                "imagem: roupa, o que está fazendo e onde está. Não tente "
                "identificar quem é."
            )
        descricao = vigia_camera.analisar_a28(prompt_visao)
        if descricao:
            voz.falar(descricao)

    if reincidente:
        registrar_evento(
            "escalada", motivo="permanência por 10 segundos após cruzamento"
        )
        enviado = enviar_whatsapp(
            "Alerta do Protocolo Torre Stark: a pessoa permaneceu na área protegida por 10 segundos após a entrada. "
            f"Horário: {datetime.now():%H:%M}. "
            f"Foto salva em {caminho_foto}."
        )
        if not enviado:
            log.warning("Alerta de escalada não enviado por WhatsApp.")



def laco_presenca():
    ultimo = None
    while not PARAR.wait(10):
        atual = presenca.estado_atual().get("estado")
        if not cfg("SEGURANCA_ATIVA", False) or not cfg("SEGURANCA_AUTO", True) or cfg("SEGURANCA_AGENDA_ATIVA", False):
            ultimo = atual
            continue
        if atual == ultimo:
            continue
        ultimo = atual
        if atual == "ausente":
            armar("presenca")
        elif atual == "presente" and estado_atual()["armado"]:
            desarmar("presenca")



def dentroDaJanela(now):
    try:
        inicio = datetime.strptime(str(cfg("SEGURANCA_HORA_INICIO", "06:00")), "%H:%M").time()
        fim = datetime.strptime(str(cfg("SEGURANCA_HORA_FIM", "23:00")), "%H:%M").time()
    except ValueError:
        return False
    if inicio == fim:
        return False
    atual = now.timetz().replace(tzinfo=None)
    if inicio < fim:
        return inicio <= atual < fim
    return atual >= inicio or atual < fim



def lacoAgenda():
    armadoAgenda = False
    while not PARAR.wait(10):
        ativo = bool(cfg("SEGURANCA_ATIVA", False) and cfg("SEGURANCA_AGENDA_ATIVA", False))
        dentro = ativo and dentroDaJanela(datetime.now().astimezone())
        if dentro and not armadoAgenda:
            if not estado_atual()["armado"]:
                armar("agenda")
            voz.falar("Senhor, vou ativar o Protocolo Torre Stark.")
            armadoAgenda = True
        elif dentro and armadoAgenda and not estado_atual()["armado"]:
            armar("agenda")
            voz.falar("Senhor, o Protocolo Torre Stark foi armado novamente.")
        elif not dentro and armadoAgenda:
            if estado_atual()["armado"]:
                desarmar("agenda")
            voz.falar("Senhor, o hor\u00e1rio do Protocolo Torre Stark terminou.")
            armadoAgenda = False



def iniciar(callback=None):
    global THREAD, threadAgenda
    vigia_camera.limpar_fotos_antigas()
    thread_camera = vigia_camera.iniciar(callback=callback or ao_detectar)
    with TRAVA:
        if (
            THREAD is not None and THREAD.is_alive()
            and threadAgenda is not None and threadAgenda.is_alive()
        ):
            return THREAD
        PARAR.clear()
        if THREAD is None or not THREAD.is_alive():
            THREAD = threading.Thread(target=laco_presenca, daemon=True, name="mark2-seguranca")
            THREAD.start()
        if threadAgenda is None or not threadAgenda.is_alive():
            threadAgenda = threading.Thread(target=lacoAgenda, daemon=True, name="mark2-agenda-seguranca")
            threadAgenda.start()
    log.info("Agendamento do Protocolo Ver?nica pronto.")
    return thread_camera or THREAD



def parar():
    PARAR.set()
    vigia_camera.parar()
