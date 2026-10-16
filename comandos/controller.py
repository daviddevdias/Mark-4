import asyncio

import logging

import random

import re

import urllib.parse

import webbrowser
import uuid
from datetime import datetime, time as horaDoDia, timedelta

import config
from comandos import wake_word, linguagem, memoria

from comandos import amigo, navegador_voz, painel_log, visao, whatsapp_bot

from comandos.automacao import (
    clima,
    rotina_chegada,
    rotina_saida,
    seguranca_stark,
    smart_home,
)

from interface import gmail, voz

log = logging.getLogger("mark2.controller")





def falha(mensagem, *args):

    log.error(mensagem, *args)
    return ""


PADRAO_WAKE_WORD_PREFIXO = wake_word.PADRAO_INICIO
PADRAO_WAKE_WORD_SUFIXO = wake_word.PADRAO_FIM



def consultar_clima(funcao):
    try:
        return funcao()
    except clima.ClimaIndisponivel as erro:
        log.warning("Consulta de clima indisponível: %s", erro)
        return None

GATILHOS_PESQUISA = (
    "pesquisar",
    "pesquisa",
    "pesquise",
    "buscar",
    "busca",
    "busque",
    "procurar",
    "procura",
    "procure",
)

PADRAO_INTENCAO_PESQUISA = re.compile(
    r"^\s*(?:(?:por\s+favor|fa[çc]a|faz|pode|poderia|voc[eê]\s+pode|"
    r"eu\s+quero\s+que\s+(?:voc[eê]\s+)?|quero\s+que\s+(?:voc[eê]\s+)?|quero)\s+)*"
    r"(?:uma\s+)?"
    rf"(?P<gatilho>{'|'.join(map(re.escape, GATILHOS_PESQUISA))})\b"
    r"(?P<resto>.*)$",
    re.IGNORECASE,
)

PADRAO_PLATAFORMA_DIRETA = re.compile(
    r"^\s*(?P<plataforma>google|internet|web|youtube|yt|t[úu]bo|"
    r"wiki(?:p[eé]dia)?|wikipedia|wicca)\b\s*(?P<termo>.*)$",
    re.IGNORECASE,
)

PADRAO_PLATAFORMA_NO_TERMO = re.compile(
    r"\b(?:n[oa]|pelo|pela)\s+(?P<plataforma>google|internet|web|youtube|yt|"
    r"t[úu]bo|wiki(?:p[eé]dia)?|wikipedia|wicca)\b",
    re.IGNORECASE,
)




def nome_plataforma(valor):
    valor = valor.casefold()
    if valor in {"youtube", "yt", "túbo", "tubo"}:
        return "youtube"
    if valor.startswith("wiki") or valor == "wicca":
        return "wikipedia"
    return "google"



# Limpa termo pesquisa
def limpar_termo_pesquisa(termo):
    termo = re.sub(r"\s+", " ", termo).strip(" ,.!?;:")
    termo = re.sub(
        r"^(?:(?:fa[çc]a\s+uma|uma|para\s+mim|pra\s+mim|por\s+favor|"
        r"aqui|sobre|por|a\s+respeito\s+de)\b[\s,:-]*)+",
        "",
        termo,
        flags=re.IGNORECASE,
    )
    termo = re.sub(
        r"(?:\s*,?\s*(?:por\s+favor|para\s+mim|pra\s+mim))+$",
        "",
        termo,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", termo).strip(" ,.!?;:")



# Extrai intencao pesquisa
def extrair_intencao_pesquisa(comando):
    if not isinstance(comando, str):
        return None
    comando = PADRAO_WAKE_WORD_PREFIXO.sub("", comando.strip(), count=1)
    if not comando or len(comando) > 10_000:
        return None

    correspondencia_direta = PADRAO_PLATAFORMA_DIRETA.fullmatch(comando)
    if correspondencia_direta:
        termo = limpar_termo_pesquisa(correspondencia_direta.group("termo"))
        if not termo:
            return None
        return nome_plataforma(correspondencia_direta.group("plataforma")), termo

    correspondencia = PADRAO_INTENCAO_PESQUISA.fullmatch(comando)
    if not correspondencia:
        return None

    plataforma = "google"
    termo_bruto = correspondencia.group("resto")
    correspondencia_plataforma = PADRAO_PLATAFORMA_NO_TERMO.search(termo_bruto)
    if correspondencia_plataforma:
        plataforma = nome_plataforma(correspondencia_plataforma.group("plataforma"))
        termo_bruto = (
            termo_bruto[: correspondencia_plataforma.start()]
            + " "
            + termo_bruto[correspondencia_plataforma.end() :]
        )

    termo = limpar_termo_pesquisa(termo_bruto)
    return (plataforma, termo) if termo else None

PADRAO_ENVIO_MENSAGEM = re.compile(
    r"^(?:mandar|manda|mande|enviar|envia|envie)\s+"
    r"(?:uma\s+|um\s+)?"
    r"(?:mensagem|whats|whatsapp)\s+"
    r"(?:para\s+o\s+|para\s+a\s+|para\s+|pro\s+|pra\s+)"
)

PADRAO_MUSICA_CHEGADA = re.compile(
    r"^(ativar|desativar|ligar|desligar)\s+(?:a\s+)?m[uú]sica\s+d[ae]\s+chegada"
)

PADRAO_APPS_CHEGADA = re.compile(
    r"^(ativar|desativar|ligar|desligar)\s+(?:a\s+)?(?:abertura\s+de\s+aplicativos\s+na\s+chegada|aplicativos\s+ao\s+chegar)"
)

PADRAO_FECHAR_APPS_SAIDA = re.compile(
    r"^(ativar|desativar|ligar|desligar)\s+(?:o\s+)?(?:fechamento\s+de\s+aplicativos\s+na\s+sa[i\u00ed]da|fechar\s+aplicativos\s+ao\s+sair)"
)

PREFIXO_CORTESIA_ACAO = (
    r"^\s*(?:(?:por\s+favor|por\s+gentileza|fa[çc]a\s+o\s+favor\s+de|"
    r"pode|poderia)[,\s]+)?"
)

SUFIXO_ACAO = r"\s*[.!?]*\s*$"

PADRAO_TV_DESLIGAR = re.compile(
    PREFIXO_CORTESIA_ACAO + r"deslig(?:ar|a|ue)\s+(?:a\s+)?tv" + SUFIXO_ACAO
)

PADRAO_TV_LIGAR = re.compile(
    PREFIXO_CORTESIA_ACAO + r"lig(?:ar|a|ue)\s+(?:a\s+)?tv" + SUFIXO_ACAO
)

PADRAO_RESUMO_SITE = re.compile(
    r"^\s*(?:(?:fa[çc]a|gere)\s+(?:um\s+)?)?resumo\s+do\s+site"
    r"(?:\s+(?P<url>\S+))?\s*[.!?]*\s*$"
)

PADRAO_CHEGADA = re.compile(
    PREFIXO_CORTESIA_ACAO + r"cheguei(?:\s+em\s+casa)?" + SUFIXO_ACAO
)

PADRAO_CONFIRMAR_SAIDA = re.compile(
    r"^\s*(?:confirmar\s+sa[íi]da|sa[íi]da)\s*[.!]*\s*$", re.IGNORECASE
)

PADRAO_ATE_MAIS = re.compile(r"^\s*at[ée]\s+mais\s*[.!]*\s*$")

PADRAO_STATUS_CASA = re.compile(
    r"\b(?:status|relat[oó]rio)\s+d[ae]\s+(?:tv|televis[ãa]o|casa)\b"
    r"|^\s*(?:status|relat[oó]rio)\s*[.!?]*\s*$"
)

PADRAO_FALAS_APRESENTACAO_REMOVIDAS = re.compile(
    r"\bse\s+apresent(?:e|a|ar)\b"
    r"|\bapresent(?:e|a|ar)[-\s]+se\b"
    r"|\bapresent(?:e|a|ar)\s+voc[eê]\b"
    r"|\b(?:fal(?:e|a|ar)|cont(?:e|a|ar))\s+(?:um\s+pouco\s+)?(?:sobre|de)\s+voc[eê]\b"
    r"|\b(?:fa[çc]a|faz|fazer)\s+(?:uma\s+)?apresenta[çc][ãa]o\b",
    re.IGNORECASE,
)

PADRAO_FALAS_CAPACIDADES_REMOVIDAS = re.compile(
    r"\bo\s+que\s+(?:voc[eê]\s+)?(?:sabe|pode|consegue)\s+fazer\b"
    r"|\bo\s+que\s+voc[eê]\s+faz\b"
    r"|\bquais\s+(?:s[ãa]o\s+)?(?:as\s+)?suas\s+(?:fun[çc][õo]es|habilidades|capacidades|recursos)\b",
    re.IGNORECASE,
)

PADRAO_FALAS_FUTURO_REMOVIDAS = re.compile(
    r"\bo\s+que\s+voc[eê]\s+vai\s+(?:aprender|ganhar)\b"
    r"|\bseu\s+futuro\b"
    r"|\bsuas\s+(?:novidades|pr[óo]ximas\s+(?:fun[çc][õo]es|atualiza[çc][õo]es))\b",
    re.IGNORECASE,
)

PADRAO_SAIR_SISTEMA = re.compile(
    PREFIXO_CORTESIA_ACAO
    + r"(?:sair|(?:desligar|desligue|encerrar|encerre)\s+(?:o\s+)?sistema)"
    + SUFIXO_ACAO
)

PADRAO_CLIMA = re.compile(
    r"\bprevis[ãa]o\s+do\s+tempo\b"
    r"|\bcomo\s+est[áa]\s+o\s+(?:clima|tempo)\b"
    r"|\bqual\s+(?:[ée]\s+)?(?:(?:o|a)\s+)?(?:clima|previs[ãa]o)\b"
    r"|\bqual\s+(?:[ée]\s+)?o\s+tempo\s+(?:hoje|agora|l[áa]\s+fora)\b"
    r"|\bvai\s+chover\b"
    r"|^\s*(?:clima|tempo|chuva)\s*[.!?]*\s*$"
)



PADRAO_TV_VOLUME_DEFINIR = re.compile(
    PREFIXO_CORTESIA_ACAO
    + r"(?:(?:colocar|coloca|coloque)|deix(?:ar|e|a)|p[õo](?:r|e|em)|ajust(?:ar|e|a))?\s*"
    r"(?:o\s+)?volume(?:\s+da\s+tv)?\s+(?:em|para|no)\s+(?P<nivel>\d{1,3})"
    + SUFIXO_ACAO,
    re.IGNORECASE,
)

PADRAO_TV_VOLUME_SUBIR = re.compile(
    PREFIXO_CORTESIA_ACAO
    + r"(?:aument(?:ar|e|a)|sob(?:er|e)|sub(?:ir|a))\s+(?:o\s+)?volume(?:\s+da\s+tv)?"
    + SUFIXO_ACAO,
    re.IGNORECASE,
)

PADRAO_TV_VOLUME_DESCER = re.compile(
    PREFIXO_CORTESIA_ACAO
    + r"(?:abaix(?:ar|e|a)|dimin(?:uir|ua)|desc(?:er|e))\s+(?:o\s+)?volume(?:\s+da\s+tv)?"
    + SUFIXO_ACAO,
    re.IGNORECASE,
)

PADRAO_TV_MUTAR = re.compile(
    PREFIXO_CORTESIA_ACAO
    + r"(?:mut(?:ar|e|a)|silenci(?:ar|e|a))\s+(?:a\s+)?tv"
    + SUFIXO_ACAO,
    re.IGNORECASE,
)

PADRAO_TV_DESMUTAR = re.compile(
    PREFIXO_CORTESIA_ACAO
    + r"(?:desmut(?:ar|e|a)\s+(?:a\s+)?tv|tir(?:ar|e|a)\s+(?:a\s+tv\s+)?d[oa]\s+mudo)"
    + SUFIXO_ACAO,
    re.IGNORECASE,
)

PADRAO_TV_CANAL_NUMERO = re.compile(
    PREFIXO_CORTESIA_ACAO
    + r"(?:mud(?:ar|e|a)|(?:trocar|troca|troque)|(?:colocar|coloca|coloque))\s+(?:a\s+tv\s+)?(?:o\s+)?canal\s+"
    r"(?:para\s+|pra\s+)?(?P<numero>\d{1,4})" + SUFIXO_ACAO,
    re.IGNORECASE,
)

PADRAO_TV_CANAL_NOME = re.compile(
    PREFIXO_CORTESIA_ACAO
    + r"(?:mud(?:ar|e|a)|(?:trocar|troca|troque)|(?:colocar|coloca|coloque))\s+(?:a\s+tv\s+)?(?:o\s+)?canal\s+"
    r"(?:para\s+|pra\s+)?(?P<nome>\D.+)" + SUFIXO_ACAO,
    re.IGNORECASE,
)

PADRAO_TV_CANAL_SUBIR = re.compile(
    PREFIXO_CORTESIA_ACAO
    + r"(?:pr[óo]ximo\s+canal|canal\s+(?:seguinte|acima|para\s+cima))"
    + SUFIXO_ACAO,
    re.IGNORECASE,
)

PADRAO_TV_CANAL_DESCER = re.compile(
    PREFIXO_CORTESIA_ACAO + r"canal\s+(?:anterior|abaixo|para\s+baixo)" + SUFIXO_ACAO,
    re.IGNORECASE,
)

PADRAO_TV_CANAIS_SALVOS = re.compile(
    r"\bcanais\s+salvos\b|\blista\s+de\s+canais\b", re.IGNORECASE
)

PADRAO_TV_ENTRADA = re.compile(
    PREFIXO_CORTESIA_ACAO
    + r"(?:mud(?:ar|e|a)|(?:trocar|troca|troque))\s+(?:a\s+)?entrada(?:\s+da\s+tv)?\s+(?:para|pra)\s+"
    r"(?P<fonte>.+)" + SUFIXO_ACAO,
    re.IGNORECASE,
)

PADRAO_TV_ABRIR_APP = re.compile(
    PREFIXO_CORTESIA_ACAO
    + r"abr(?:ir|a|e)\s+(?:o\s+|a\s+)?(?P<app>.+?)\s+na\s+tv"
    + SUFIXO_ACAO,
    re.IGNORECASE,
)

PADRAO_TV_TOCAR = re.compile(
    PREFIXO_CORTESIA_ACAO + r"(?:tocar|toque|d[êe]\s+play)\s+na\s+tv" + SUFIXO_ACAO,
    re.IGNORECASE,
)

PADRAO_TV_PAUSAR = re.compile(
    PREFIXO_CORTESIA_ACAO + r"paus(?:ar|e|a)\s+(?:a\s+)?tv" + SUFIXO_ACAO, re.IGNORECASE
)

PADRAO_TV_PARAR_MIDIA = re.compile(
    PREFIXO_CORTESIA_ACAO
    + r"parar\s+(?:a\s+)?(?:reprodu[çc][ãa]o\s+d[ae]\s+)?tv"
    + SUFIXO_ACAO,
    re.IGNORECASE,
)

PADRAO_TV_AVANCAR = re.compile(
    PREFIXO_CORTESIA_ACAO + r"avan[çc](?:ar|e|a)\s+(?:a\s+)?tv" + SUFIXO_ACAO,
    re.IGNORECASE,
)

PADRAO_TV_RETROCEDER = re.compile(
    PREFIXO_CORTESIA_ACAO + r"retroced(?:er|a|e)\s+(?:a\s+)?tv" + SUFIXO_ACAO,
    re.IGNORECASE,
)

PADRAO_TV_MODO_IMAGEM = re.compile(
    PREFIXO_CORTESIA_ACAO
    + r"(?:mud(?:ar|e|a)|(?:colocar|coloca|coloque)|defin(?:ir|a))\s+(?:o\s+)?modo\s+de\s+imagem"
    r"(?:\s+da\s+tv)?\s+(?:para|pra|em)\s+(?P<modo>.+)" + SUFIXO_ACAO,
    re.IGNORECASE,
)



PADRAO_CLIMA_COMPLETO = re.compile(
    r"\bclima\s+completo\b|\bresumo\s+completo\s+d[oa]\s+(?:clima|tempo)\b"
    r"|\bdetalhes?\s+d[oa]\s+(?:clima|tempo)\b",
    re.IGNORECASE,
)

PADRAO_CLIMA_AMANHA = re.compile(
    r"\bprevis[ãa]o\s+(?:d[eo]\s+|pra\s+|para\s+)?amanh[ãa]\b"
    r"|\bcomo\s+(?:vai\s+estar|fica)\s+(?:o\s+)?(?:clima|tempo)\s+amanh[ãa]\b"
    r"|\b(?:clima|tempo)\s+(?:(?:de|para|pra)\s+)?amanh[ãa]\b"
    r"|\bvai\s+chover\s+amanh[ãa]\b",
    re.IGNORECASE,
)

PADRAO_CLIMA_COMPARAR = re.compile(
    r"\bcompar[ae]\s+(?:o\s+)?(?:clima|tempo)\s+de\s+amanh[ãa]\s+com\s+hoje\b"
    r"|\bamanh[ãa]\s+vai\s+ficar\s+mais\s+(?:quente|frio)\s+(?:que|do\s+que)\s+hoje\b",
    re.IGNORECASE,
)

PADRAO_CLIMA_ESTENDIDA = re.compile(
    r"\bprevis[ãa]o\s+(?:estendida|d[ao]s?\s+pr[óo]ximos\s+dias|d[ae]\s+semana)\b",
    re.IGNORECASE,
)

VERBOS_INSPECAO_VISUAL = (
    r"(?:analis(?:e|a|ar)|olh(?:e|a|ar)|verifiqu(?:e)|verific(?:a|ar))"
)

PADRAO_SEG_STATUS = re.compile(
    r"\b(?:status|relat[óo]rio|situa[cç][ãa]o)\b.*\b(?:seguran[cç]a|protocolo\s+(?:(?:torre\s+)?stark|ver[oô]nica))\b",
    re.IGNORECASE,
)

PADRAO_HISTORICO_SEGURANCA = re.compile(
    r"\b(?:(?:u|\u00fa)lt[i\u00ed]m[oa]s? eventos?|(?:u|\u00fa)lt[i\u00ed]mo movimento|quantas pessoas passaram|"
    r"algu(?:e|\u00e9)m (?:apareceu|ficou|passou|esteve) (?:no|pelo) port(?:a|\u00e3)o|"
    r"eventos? (?:de|do dia) (?:hoje|ontem)|pessoas? detectadas? (?:hoje|ontem))\b",
    re.IGNORECASE,
)

PADRAO_SEG_DESARMAR = re.compile(
    r"\b(?:desarm\w*|desativ\w*|deslig\w*)\b.*\b(?:protocolo\s+(?:(?:torre\s+)?stark|ver[oô]nica)|seguran[cç]a)\b",
    re.IGNORECASE,
)

PADRAO_SEG_ARMAR = re.compile(
    r"\b(?:arm\w*|ativ\w*|lig\w*)\b.*\b(?:protocolo\s+(?:(?:torre\s+)?stark|ver[oô]nica)|seguran[cç]a)\b",
    re.IGNORECASE,
)

PADRAO_ANALISAR_TELA = re.compile(
    PREFIXO_CORTESIA_ACAO
    + r"(?:o\s+que\s+(?:tem|h[áa])\s+na\s+(?:minha\s+)?tela|"
    + VERBOS_INSPECAO_VISUAL
    + r"\s+(?:a\s+)?(?:minha\s+)?tela|"
    r"que\s+erro\s+[ée]\s+esse)" + SUFIXO_ACAO,
    re.IGNORECASE,
)

PADRAO_ANALISAR_CAMERA = re.compile(
    PREFIXO_CORTESIA_ACAO
    + r"(?:o\s+que\s+(?:tem|h[áa])\s+na\s+c[âa]mera|"
    + VERBOS_INSPECAO_VISUAL
    + r"\s+(?:a\s+)?c[âa]mera)"
    + SUFIXO_ACAO,
    re.IGNORECASE,
)

PADRAO_CAMERA_AO_VIVO_LIGAR = re.compile(
    PREFIXO_CORTESIA_ACAO
    + r"(?:ligar|ativar|iniciar)\s+(?:a\s+)?c[âa]mera\s+ao\s+vivo"
    + SUFIXO_ACAO,
    re.IGNORECASE,
)

PADRAO_CAMERA_AO_VIVO_DESLIGAR = re.compile(
    PREFIXO_CORTESIA_ACAO
    + r"(?:desligar|desativar|parar)\s+(?:a\s+)?c[âa]mera\s+ao\s+vivo"
    + SUFIXO_ACAO,
    re.IGNORECASE,
)

PADRAO_ANALISAR_AO_VIVO = re.compile(
    PREFIXO_CORTESIA_ACAO
    + VERBOS_INSPECAO_VISUAL
    + r"(?:\s+(?:a\s+)?c(?:a|\u00e2)mera\s+ao\s+vivo|\s+(?:isso|a(?:i|\u00ed)|agora|essa\s+cena|a\s+cena))?"
    + SUFIXO_ACAO,
    re.IGNORECASE,
)



# Pesquisa web
async def pesquisar_web(comando):
    intencao = extrair_intencao_pesquisa(comando)
    if intencao is None:
        return falha("Pesquisa: não entendi o que pesquisar.")
    plataforma, termo = intencao

    query = urllib.parse.quote_plus(termo)

    if plataforma == "youtube":
        url = f"https://www.youtube.com/results?search_query={query}"
        resposta = f"Buscando por {termo} no YouTube."
    elif plataforma == "wikipedia":
        url = f"https://pt.wikipedia.org/w/index.php?search={query}"
        resposta = f"Procurando por {termo} na Wikipédia."
    else:
        url = f"https://www.google.com/search?q={query}"
        resposta = f"Pesquisando por {termo}."

    acao = "youtube" if plataforma == "youtube" else "pesquisar" if plataforma == "google" else "abrir"
    alvo = url if acao == "abrir" else termo
    return await asyncio.to_thread(navegador_voz.navegador.executar, acao, alvo)




def finalizar(resposta):
    if resposta is None or not str(resposta).strip():
        return ""
    return voz.com_pergunta_continuidade(resposta)

SAUDACOES_LOCAIS = {

       ("jarvis",): (
        "Às ordens, senhor.",
    ),
    (
        "acordado",
        "acordado?",
        "está acordado",
        "esta acordado",
        "está acordado?",
        "esta acordado?",
        "você está acordado",
        "voce esta acordado",
        "você está acordado?",
        "voce esta acordado?",
        "tá acordado",
        "ta acordado",
        "tá acordado?",
        "ta acordado?",
    ): (
        "Para o senhor sempre",
        "Em vigília, senhor. O que o senhor precisa?",
    ),
    (
        "você está aí",
        "voce esta ai",
        "você está aí?",
        "voce esta ai?",
        "está aí",
        "esta ai",
        "está aí?",
        "esta ai?",
        "tá aí",
        "ta ai",
        "tá aí?",
        "ta ai?",
        "você está me ouvindo",
        "voce esta me ouvindo",
        "você está me ouvindo?",
        "voce esta me ouvindo?",
        "está me ouvindo",
        "esta me ouvindo",
        "está me ouvindo?",
        "esta me ouvindo?",
        "você me ouve",
        "voce me ouve",
        "você me ouve?",
        "voce me ouve?",
        "consegue me ouvir",
        "consegue me ouvir?",
    ): (
        "Sempre, senhor.",
        "Alto e claro, senhor.",
    ),

    (
        "oi",
        "olá",
        "ola",
        "e ai",
        "e aí",
        "eae",
        "eai",
        "salve",
        "opa",
        "ei",
        "hey",
        "hello",
        "oi oi",
    ): (
        "Olá, Sistemas prontos.",
        "À sua disposição.",
    ),

    (
        "obrigado",
        "obrigada",
        "valeu",
        "vlw",
        "muito obrigado",
        "muito obrigada",
        "obrigadão",
        "obrigadao",
        "brigado",
    ): (
        "Sempre, senhor.",
        "Ao seu dispor.",
    ),
    (
        "bom trabalho",
        "ótimo trabalho",
        "otimo trabalho",
        "excelente trabalho",
    ): (
        "Obrigado, senhor.",
        "Agradeço. Foi uma boa colaboração.",
        "Fico honrado, senhor.",
    ),

    (
        "tchau",
        "até mais",
        "até logo",
        "falou",
        "flw",
        "tchau tchau",
        "até amanhã",
        "ate amanha",
        "ate mais",
        "ate logo",
        "fui",
        "xau",
        "adeus",
    ): (
        "Até breve, senhor.",
        "Entrando em modo de espera. Estarei aqui, senhor.",
        "Até logo, A casa fica sob a minha guarda.",
        "Volte em segurança, senhor.",
    ),
    (
        "vou dormir",
        "vou dormir agora",
        "vou deitar",
        "vou descansar",
        "vou pra cama",
        "vou para a cama",
        "estou indo dormir",
        "tô indo dormir",
        "to indo dormir",
        "hora de dormir",
    ): (
        "Descanse, senhor. Mantenho a vigília.",
        "Boa noite, Eu cuido do resto.",
        "Ativando modo noturno. Durma bem, senhor.",
        "Todos os sistemas sob controle, senhor. Bom descanso.",
    ),
    (
        "voltei",
        "já voltei",
        "ja voltei",
        "estou de volta",
        "tô de volta",
        "to de volta",
    ): (
        "Bem-vindo de volta, senhor.",
        "Bem-vindo, Tudo em ordem durante a sua ausência.",
    ),
    (
        "tenho uma ideia",
        "tive uma ideia",
        "tenho uma ideia louca",
        "tive uma ideia louca",
    ): (
        "Sou todo atenção, senhor.",
        "Estou ouvindo, Preparando as simulações.",
        "Diga, senhor. Já estou calculando as possibilidades.",
    ),
    (
        "protocolo festa",
        "protocolo de festa",
        "protocolo casa de festas",
        "protocolo casa de festa",
        "ativar protocolo festa",
        "ativar protocolo casa de festas",
    ): (
        "Protocolo Casa de Festas pronto para simulação, senhor.",
        "Em preparação, Os convidados ficam por sua conta.",
    ),

}





def resposta_saudacao_local(comando):
    for chaves, respostas in SAUDACOES_LOCAIS.items():
        if comando in chaves:
            return random.choice(respostas).format(nome=config.NOME_MESTRE)
    return None




def comando_invalido(texto):
    return not isinstance(texto, str) or not texto.strip()




def url_https_valida(url):
    if not isinstance(url, str) or not 1 <= len(url) <= 2048:
        return False
    if any(caractere.isspace() for caractere in url):
        return False
    try:
        partes = urllib.parse.urlsplit(url)
        porta = partes.port
    except ValueError:
        return False
    return bool(
        partes.scheme == "https"
        and partes.hostname
        and partes.username is None
        and partes.password is None
        and (porta is None or 1 <= porta <= 65535)
    )




def separar_contato_mensagem(
    conteudo,
    contatos,
):
    if not isinstance(conteudo, str) or not isinstance(contatos, dict):
        return None
    conteudo = conteudo.strip()
    if not conteudo:
        return None

    nomes_validos = sorted(
        (
            nome
            for nome, numero in contatos.items()
            if isinstance(nome, str)
            and nome.strip()
            and isinstance(numero, str)
            and numero.strip()
        ),
        key=len,
        reverse=True,
    )
    for nome in nomes_validos:
        partes_nome = nome.split()
        padrao_nome = r"\s+".join(re.escape(parte) for parte in partes_nome)
        correspondencia = re.match(
            rf"^{padrao_nome}(?=\s|$)",
            conteudo,
            flags=re.IGNORECASE,
        )
        if correspondencia:
            mensagem = conteudo[correspondencia.end() :].strip()
            return nome, contatos[nome], mensagem
    return None



# Processa comando interno
async def processar_comando_interno(
    comando_bruto,
    permitir_acesso_codigo=True,
):
    if comando_invalido(comando_bruto):
        return ""
    if len(comando_bruto) > 10_000:
        return falha("Comando ignorado: excede o limite de tamanho.")

    comando_original = comando_bruto.strip()
    log.info("Processando comando com %d caractere(s).", len(comando_original))

    respostaEmail = await asyncio.to_thread(gmail.voiceConfirmation, comando_original)
    if respostaEmail is not None:
        return finalizar(respostaEmail)

    comando_original = PADRAO_WAKE_WORD_PREFIXO.sub(
        "",
        comando_original,
        count=1,
    ).strip()
    comando_original = PADRAO_WAKE_WORD_SUFIXO.sub(
        "",
        comando_original,
        count=1,
    ).strip()
    if not comando_original:
        return resposta_saudacao_local("jarvis") or "Às ordens, senhor."
    comando_original = linguagem.normalizar_comando(comando_original)
    from comandos.automacao.central_casa import disparar as disparar_rotina_casa
    resposta_rotina = await asyncio.to_thread(disparar_rotina_casa, frase=comando_original)
    if resposta_rotina:
        return resposta_rotina
    if comando_original == "eai":
        return "Olá senhor, estou pronto."
    comando = comando_original.casefold()
    from .briefing_dia import pedido
    if pedido(comando):
        from datetime import datetime as data_resumo
        hora = data_resumo.now().hour
        saudacao = "Bom dia" if hora < 12 else "Boa tarde" if hora < 18 else "Boa noite"
        return saudacao + ", senhor. Vou preparar seu resumo do dia."
    if linguagem.chave(comando) in ("obrigado", "obrigada", "muito obrigado", "muito obrigada", "valeu"):
        return "Disponha, senhor."
    # Salva o texto sem alterar
    nota = re.fullmatch(r"(?:anotar|anote|criar(?: uma)? nota|crie(?: uma)? nota|salvar(?: uma)? nota)(?:\s+(?:com|sobre))?(?:\s+(.+))?", comando_original, re.IGNORECASE)
    if nota:
        texto = (nota.group(1) or "").strip()
        if not texto:
            return "O que deseja anotar, senhor?"
        if len(texto) > 1200:
            return "A nota pode ter até 1200 caracteres. Divida em duas notas, senhor."
        salvo = memoria.salvar_nota_hud("voz-" + uuid.uuid4().hex, "meta", texto[:42], texto)
        return "Nota salva, senhor." if salvo else "Não consegui salvar a nota, senhor."
    if linguagem.chave(comando) == "cancelar nota":
        return "Anotação cancelada, senhor."
    if (PADRAO_TV_CANAIS_SALVOS.search(comando) or PADRAO_TV_CANAL_NUMERO.fullmatch(comando)
            or PADRAO_TV_CANAL_NOME.fullmatch(comando) or PADRAO_TV_ENTRADA.fullmatch(comando) or PADRAO_TV_TOCAR.fullmatch(comando)
            or PADRAO_TV_PAUSAR.fullmatch(comando) or PADRAO_TV_PARAR_MIDIA.fullmatch(comando)):
        return "Esse comando de TV foi removido."
    if comando in ("o que tenho na agenda hoje", "o que tenho na agenda amanhã"):
        dia = datetime.now().date() + timedelta(days=1 if "amanhã" in comando else 0)
        itens = memoria.listar_compromissos(50, dia.isoformat(), (dia + timedelta(days=1)).isoformat())
        try:
            from interface import google_agenda
            itens += [i for i in google_agenda.eventos() if str(i["inicio"])[:10]==dia.isoformat()]
        except (OSError,ValueError,RuntimeError,KeyError):pass
        return "\n".join(f"{item['inicio'][11:16]}: {item['titulo']}" for item in itens) or "Não há compromissos para esse dia, senhor."
    if comando in ("leia minhas notas", "minhas notas"):
        notas = memoria.listar_notas_hud()
        return "\n".join(f"{nota['title']}: {nota['body']}" for nota in notas[:15]) or "Ainda não há notas salvas."


    resposta_local = resposta_saudacao_local(comando)
    if resposta_local:
        return resposta_local

    if (
        PADRAO_FALAS_APRESENTACAO_REMOVIDAS.search(comando)
        or PADRAO_FALAS_CAPACIDADES_REMOVIDAS.search(comando)
        or PADRAO_FALAS_FUTURO_REMOVIDAS.search(comando)
        or re.search(r"\bquem\s+[ée]\s+voc[eê]\b", comando)
    ):
        log.info("Pedido de apresentação ignorado.")
        return ""

    elif PADRAO_TV_DESLIGAR.fullmatch(comando):
        return finalizar(smart_home.desligar_tv())

    elif PADRAO_TV_LIGAR.fullmatch(comando):
        return finalizar(smart_home.ligar_tv())

    elif correspondencia_volume := PADRAO_TV_VOLUME_DEFINIR.fullmatch(comando):
        return finalizar(
            smart_home.definir_volume(correspondencia_volume.group("nivel"))
        )

    elif PADRAO_TV_VOLUME_SUBIR.fullmatch(comando):
        return finalizar(smart_home.volume_subir())

    elif PADRAO_TV_VOLUME_DESCER.fullmatch(comando):
        return finalizar(smart_home.volume_descer())

    elif PADRAO_TV_MUTAR.fullmatch(comando):
        return finalizar(smart_home.mutar())

    elif PADRAO_TV_DESMUTAR.fullmatch(comando):
        return finalizar(smart_home.desmutar())

    elif correspondencia_canal_num := PADRAO_TV_CANAL_NUMERO.fullmatch(comando):
        return finalizar(
            smart_home.mudar_canal_numero(correspondencia_canal_num.group("numero"))
        )

    elif PADRAO_TV_CANAL_SUBIR.fullmatch(comando):
        return finalizar(smart_home.canal_subir())

    elif PADRAO_TV_CANAL_DESCER.fullmatch(comando):
        return finalizar(smart_home.canal_descer())

    elif PADRAO_TV_CANAIS_SALVOS.search(comando):
        return finalizar(smart_home.listar_canais_salvos())

    elif correspondencia_canal_nome := PADRAO_TV_CANAL_NOME.fullmatch(comando):
        return finalizar(
            smart_home.mudar_canal_por_nome(
                correspondencia_canal_nome.group("nome").strip()
            )
        )

    elif correspondencia_entrada := PADRAO_TV_ENTRADA.fullmatch(comando):
        return finalizar(
            smart_home.mudar_fonte_entrada(
                correspondencia_entrada.group("fonte").strip()
            )
        )

    elif correspondencia_app := PADRAO_TV_ABRIR_APP.fullmatch(comando):
        return finalizar(smart_home.abrir_app(correspondencia_app.group("app").strip()))

    elif PADRAO_TV_TOCAR.fullmatch(comando):
        return finalizar(smart_home.tocar())

    elif PADRAO_TV_PAUSAR.fullmatch(comando):
        return finalizar(smart_home.pausar())

    elif PADRAO_TV_PARAR_MIDIA.fullmatch(comando):
        return finalizar(smart_home.parar_midia())

    elif PADRAO_TV_AVANCAR.fullmatch(comando):
        return finalizar(smart_home.avancar())

    elif PADRAO_TV_RETROCEDER.fullmatch(comando):
        return finalizar(smart_home.retroceder())

    elif correspondencia_modo_imagem := PADRAO_TV_MODO_IMAGEM.fullmatch(comando):
        return finalizar(
            smart_home.definir_modo_imagem(
                correspondencia_modo_imagem.group("modo").strip()
            )
        )

    elif correspondencia_site := PADRAO_RESUMO_SITE.fullmatch(comando):
        url_site = correspondencia_site.group("url")
        if not url_site or not url_https_valida(url_site):
            return falha("Resumo de site: URL HTTPS pública inválida ou ausente.")
        return falha("Resumo de site: leitura de URLs desativada (sem proteção contra rede interna).")

    elif PADRAO_HISTORICO_SEGURANCA.search(comando):
        agora = datetime.now().astimezone()
        dia = agora.date() - timedelta(days=1) if "ontem" in comando.casefold() else agora.date()
        inicio = datetime.combine(dia, horaDoDia.min, tzinfo=agora.tzinfo)
        fim = inicio + timedelta(days=1)
        eventos = seguranca_stark.eventosEntre(inicio, fim, limite=1000)
        if "ultim" in linguagem.chave(comando) and not any(dia in linguagem.chave(comando) for dia in ("hoje", "ontem")):
            eventos = seguranca_stark.ultimos_eventos(20)
        pessoas = [evento for evento in eventos if evento.get("tipo") == "pessoa" and not evento.get("reincidente")]
        if "quantas pessoas" in comando.casefold():
            quantidade = 0
            for evento in pessoas:
                try:
                    quantidade += max(1, int(evento.get("quantidade") or 1))
                except (TypeError, ValueError, OverflowError):
                    quantidade += 1
            texto = f"Foram registradas {quantidade} detecções de pessoa nesse dia. A mesma pessoa pode aparecer em mais de um registro."
        elif not eventos:
            texto = "Nao encontrei eventos de seguranca registrados nesse periodo."
        else:
            recentes = eventos[-5:]
            texto = "Ultimos eventos registrados: " + "; ".join(
                f"{evento.get('hora', '')[11:19]} {evento.get('tipo', 'evento')}"
                + (f" na zona {evento.get('zoneName')}" if evento.get("zoneName") else "")
                for evento in recentes
            )
        return finalizar(texto)

    elif PADRAO_SEG_STATUS.search(comando):
        return finalizar(seguranca_stark.relatorio())

    elif PADRAO_SEG_DESARMAR.fullmatch(comando):
        return finalizar(seguranca_stark.desarmar("comando"))

    elif PADRAO_SEG_ARMAR.fullmatch(comando):
        sucesso, resultado = config.definirOpcao("SEGURANCA_ATIVA", True)
        if not sucesso:
            return finalizar("Não consegui ativar o Protocolo Torre Stark: " + str(resultado))
        return finalizar(seguranca_stark.armar("comando"))

    elif PADRAO_ANALISAR_TELA.search(comando):
        return finalizar(await asyncio.to_thread(visao.analisar_tela))

    elif PADRAO_CAMERA_AO_VIVO_LIGAR.search(comando):
        sucesso_ao_vivo, mensagem_ao_vivo = await asyncio.to_thread(
            visao.iniciar_captura_ao_vivo
        )
        return finalizar(mensagem_ao_vivo)

    elif PADRAO_CAMERA_AO_VIVO_DESLIGAR.search(comando):
        if await asyncio.to_thread(visao.parar_captura_ao_vivo):
            return finalizar("Câmera ao vivo desligada, senhor.")
        return finalizar("A câmera ao vivo já estava desligada.")

    elif PADRAO_ANALISAR_AO_VIVO.search(comando):
        if not visao.captura_ao_vivo_ativa():
            return finalizar(await asyncio.to_thread(visao.analisar_camera))
        return finalizar(await asyncio.to_thread(visao.analisar_ao_vivo))

    elif PADRAO_ANALISAR_CAMERA.search(comando):
        return finalizar(await asyncio.to_thread(visao.analisar_camera))

    elif PADRAO_CLIMA_COMPARAR.search(comando):
        respostaClima = consultar_clima(clima.comparar_amanha_com_hoje)
        if respostaClima is None:
            return finalizar("Não consegui consultar o clima agora, senhor. Tentarei novamente mais tarde.")
        return finalizar(respostaClima)

    elif PADRAO_CLIMA_AMANHA.search(comando):
        respostaClima = consultar_clima(clima.gerar_resumo_previsao_amanha)
        if respostaClima is None:
            return finalizar("Não consegui consultar o clima agora, senhor. Tentarei novamente mais tarde.")
        return finalizar(respostaClima)

    elif PADRAO_CLIMA_ESTENDIDA.search(comando):
        linhas = consultar_clima(clima.gerar_previsao_estendida)
        if linhas is None:
            return finalizar("Não consegui consultar o clima agora, senhor. Tentarei novamente mais tarde.")
        if not linhas:
            falha("Clima: não consegui montar a previsão estendida.")
        return finalizar("\n".join(linhas))

    elif PADRAO_CLIMA_COMPLETO.search(comando):
        respostaClima = consultar_clima(clima.gerar_resumo_completo)
        if respostaClima is None:
            return finalizar("Não consegui consultar o clima agora, senhor. Tentarei novamente mais tarde.")
        return finalizar(respostaClima)

    elif PADRAO_CLIMA.search(comando):
        respostaClima = consultar_clima(clima.gerar_resumo_clima)
        if respostaClima is None:
            return finalizar("Não consegui consultar o clima agora, senhor. Tentarei novamente mais tarde.")
        return finalizar(respostaClima)

    elif PADRAO_ENVIO_MENSAGEM.match(comando):
        correspondencia_envio = PADRAO_ENVIO_MENSAGEM.match(comando)
        conteudo_bruto = comando_original[correspondencia_envio.end() :].strip()
        contato = separar_contato_mensagem(
            conteudo_bruto,
            config.listar_contatos_whatsapp(),
        )
        if contato is None:
            return falha("WhatsApp: nenhum contato salvo no início da mensagem.")
        nome_contato, numero_destino, texto_mensagem = contato
        if not texto_mensagem:
            return falha("WhatsApp: mensagem vazia. Use: mandar mensagem para [nome] [mensagem].")

        resultado_envio = await whatsapp_bot.enviar_mensagem_playwright(
            numero_destino,
            texto_mensagem,
        )
        if resultado_envio is None:
            resultado_envio = f"Mensagem enviada para {nome_contato}."
        if "sucesso" not in str(resultado_envio).lower() and not str(resultado_envio).startswith("Mensagem enviada"):
            return falha("WhatsApp (%s): %s", nome_contato, resultado_envio)
        return finalizar(resultado_envio)

    elif PADRAO_APPS_CHEGADA.match(comando):
        verbo = PADRAO_APPS_CHEGADA.match(comando).group(1)
        ativar = verbo in ("ativar", "ligar")
        if not config.definir_apps_chegada_ativos(ativar):
            return falha("Nao foi possivel salvar a abertura automatica de aplicativos.")
        estado = "ativada" if ativar else "desativada"
        return finalizar(f"Abertura de aplicativos na chegada {estado}.")

    elif PADRAO_FECHAR_APPS_SAIDA.match(comando):
        verbo = PADRAO_FECHAR_APPS_SAIDA.match(comando).group(1)
        ativar = verbo in ("ativar", "ligar")
        if not config.definir_fechar_apps_ao_sair(ativar):
            return falha("Nao foi possivel salvar o fechamento automatico de aplicativos.")
        estado = "ativado" if ativar else "desativado"
        return finalizar(f"Fechamento de aplicativos na saida {estado}.")

    elif PADRAO_MUSICA_CHEGADA.match(comando):
        verbo = PADRAO_MUSICA_CHEGADA.match(comando).group(1)
        ativar = verbo in ("ativar", "ligar")
        if not config.definir_musica_chegada_ativa(ativar):
            return falha("Não foi possível salvar a configuração da música de chegada.")

        estado = "ativada" if ativar else "desativada"
        return finalizar(f"Musica da chegada {estado}.")

    elif PADRAO_CHEGADA.fullmatch(comando):
        if config.VOZ_ATIVA:
            voz.falar(
                f"Bem-vindo de volta, {config.NOME_MESTRE}! Que bom te ver em casa. "
                "Ligando a armadura Mark 42."
            )

        return finalizar(rotina_chegada.executar_rotina_chegada())

    elif PADRAO_CONFIRMAR_SAIDA.fullmatch(comando):
        if config.VOZ_ATIVA:
            from datetime import datetime

            hora_atual = datetime.now().hour
            voz.falar(
                f"Entendido, {config.NOME_MESTRE}. Desligando o reator. "
                f"Até logo, e tenha uma excelente {amigo.periodo_do_dia(hora_atual)}!"
            )

        return finalizar(rotina_saida.executar_rotina_saida())

    elif PADRAO_STATUS_CASA.search(comando):
        return finalizar(smart_home.status_casa())

    elif PADRAO_SAIR_SISTEMA.fullmatch(comando):
        if config.VOZ_ATIVA:
            voz.falar(
                "Guardando o que aprendi hoje antes de desligar. Um instante, senhor."
            )
        fechados, falhas, pc_bloqueado = rotina_saida.executar_encerramento_sistema()
        log.info(
            "Encerramento do sistema: fechados=%s falhas=%s pc_bloqueado=%s",
            fechados,
            falhas,
            pc_bloqueado,
        )
        await amigo.consolidar_memoria_final()
        return "SHUTDOWN_SIGNAL"

    elif re.fullmatch(r"(?:fechar|feche|encerrar) (?:o )?navegador", comando):
        return finalizar(await asyncio.to_thread(navegador_voz.navegador.executar, "encerrar"))
    elif re.fullmatch(r"(?:listar|mostrar|mostre) (?:as )?abas", comando):
        return finalizar(await asyncio.to_thread(navegador_voz.navegador.executar, "listar"))
    elif alvo := re.fullmatch(r"(?:selecionar|selecione|ir para) (?:a )?aba ([1-9][0-9]*)", comando):
        return finalizar(await asyncio.to_thread(navegador_voz.navegador.executar, "selecionar", alvo.group(1)))
    elif re.fullmatch(r"(?:parar|pare) (?:o )?carregamento", comando):
        return finalizar(await asyncio.to_thread(navegador_voz.navegador.executar, "parar"))
    elif re.fullmatch(r"(?:abra|abrir|iniciar)\s+(?:o\s+)?navegador", comando):
        return finalizar(await asyncio.to_thread(navegador_voz.navegador.executar, "iniciar"))

    elif re.fullmatch(r"(?:abra|abrir)\s+(?:uma\s+)?nova\s+aba", comando):
        return finalizar(await asyncio.to_thread(navegador_voz.navegador.executar, "nova"))

    elif re.fullmatch(r"(?:feche|fechar|encerre|encerrar)\s+(?:a\s+)?aba(?:\s+do\s+navegador)?", comando):
        return finalizar(await asyncio.to_thread(navegador_voz.navegador.executar, "fechar"))

    elif re.fullmatch(r"(?:pr[oó]xima\s+aba|aba\s+seguinte)", comando):
        return finalizar(await asyncio.to_thread(navegador_voz.navegador.executar, "proxima"))

    elif re.fullmatch(r"(?:aba\s+anterior|aba\s+anteriormente)", comando):
        return finalizar(await asyncio.to_thread(navegador_voz.navegador.executar, "anterior"))

    elif re.fullmatch(r"(?:voltar|volte)\s+(?:uma\s+)?p[aá]gina(?:\s+no\s+navegador)?", comando):
        return finalizar(await asyncio.to_thread(navegador_voz.navegador.executar, "voltar"))

    elif re.fullmatch(r"(?:avan[cç]ar|avance)\s+(?:uma\s+)?p[aá]gina(?:\s+no\s+navegador)?", comando):
        return finalizar(await asyncio.to_thread(navegador_voz.navegador.executar, "avancar"))

    elif re.fullmatch(r"(?:atualizar|atualize|recarregar|recarregue)\s+(?:a\s+)?p[aá]gina", comando):
        return finalizar(await asyncio.to_thread(navegador_voz.navegador.executar, "atualizar"))

    elif correspondenciaVideo := re.fullmatch(r"(?:clique|clicar|abra|abrir|assista|assistir|toque|tocar)(?:\s+(?:no|na|o|a))?\s+(?:v[ií]deo)(?:\s+(?:chamado|com\s+o\s+t[ií]tulo))?\s+(.+)", comando):
        return finalizar(await asyncio.to_thread(navegador_voz.navegador.executar, "video", correspondenciaVideo.group(1).strip()))

    elif re.fullmatch(r"(?:pesquisar|pesquisa|pesquise|buscar|busque|procurar|procure)(?: (?:no|na|por|sobre|google|youtube))*", linguagem.chave(comando)):
        return "O que deseja pesquisar, senhor?"

    elif correspondenciaYoutube := re.fullmatch(r"(?:pesquisar|pesquise|buscar|busque|procurar|procure)\s+(?:no\s+)?youtube\s+(?:por\s+)?(.+)", comando):
        return finalizar(await asyncio.to_thread(navegador_voz.navegador.executar, "youtube", correspondenciaYoutube.group(1).strip()))

    elif correspondenciaSite := re.fullmatch(r"(?:abrir|abra|acessar|acesse)\s+(?:o\s+site\s+)?(https?://\S+)", comando):
        return finalizar(await asyncio.to_thread(navegador_voz.navegador.executar, "abrir", correspondenciaSite.group(1)))

    elif (intencaoPesquisa := extrair_intencao_pesquisa(comando_original)) is not None:
        if intencaoPesquisa[0] == "youtube":
            return finalizar(await asyncio.to_thread(navegador_voz.navegador.executar, "youtube", intencaoPesquisa[1]))
        return finalizar(await pesquisar_web(comando_original))

    return await amigo.conversar(
        comando_original,
        permitir_acesso_codigo=permitir_acesso_codigo,
    )



# Processa comando
async def processar_comando(
    comando_bruto,
    *,
    permitir_acesso_codigo=True,
):
    if not isinstance(permitir_acesso_codigo, bool):
        permitir_acesso_codigo = False
    if voz.frase_encerra_conversa(comando_bruto):
        return voz.RESPOSTA_ENCERRAMENTO
    try:
        resposta = await processar_comando_interno(
            comando_bruto,
            permitir_acesso_codigo=permitir_acesso_codigo,
        )
    except Exception:
        log.exception("Falha ao processar o comando.")
        return ""
    if resposta is None:
        return falha("Comando sem resposta (operação não concluída).")
    if not str(resposta).strip():
        return ""
    return voz.com_pergunta_continuidade(resposta)
