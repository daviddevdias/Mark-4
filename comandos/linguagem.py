import re
import unicodedata


def chave(texto):
    texto = unicodedata.normalize("NFD", str(texto).casefold())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", texto)).strip()

# Normaliza comando
def normalizar_comando(texto):
    normal = chave(texto)
    if re.match(r"^(?:agendar|agende|marcar|marque|lembrar|lembre|anote|anotar|criar|crie|salvar|salve|mandar|enviar|envie|responder)\b", normal):
        return texto
    normal = re.sub(r"^(?:por favor|por gentileza|pode|poderia)\s+", "", normal)
    if re.fullmatch(r"(?:fecha|feche|fechar|encerra|encerre|encerrar) (?:(?:a|essa|esta) )?aba(?: (?:do )?navegador)?", normal):
        return "fechar aba"
    if normal in ("abrir aba", "abra aba", "abrir uma aba", "abra uma aba"):
        return "abrir nova aba"
    if normal == "anterior aba":
        return "aba anterior"
    normal = re.sub(r"\b(?:torre estarque|torre estark|torre starque)\b", "torre stark", normal)
    protocolo = r"(?:(?:o|a) )?(?:protocolo )?(?:torre stark|torre|stark|veronica|seguranca|defesas)"
    if re.fullmatch(r"(?:ativar|ative|ligar|ligue|armar|arme) " + protocolo, normal):
        return "ativar protocolo torre stark"
    if re.fullmatch(r"(?:desativar|desative|desligar|desligue|desarmar|desarme) " + protocolo, normal):
        return "desativar protocolo torre stark"
    if re.fullmatch(r"(?:abrir|abra|ligar|ligue|ativar|ative) (?:(?:a|o) )?camera(?: ao vivo)?", normal):
        return "ligar camera ao vivo"
    if re.fullmatch(r"(?:fechar|feche|desligar|desligue|desativar|desative) (?:(?:a|o) )?camera(?: ao vivo)?", normal):
        return "desligar camera ao vivo"
    if re.fullmatch(r"(?:o que |que |quais )?(?:tenho|tem|ha)(?: na)? (?:agenda|agendado|agendados|compromissos)(?: (?:para |de )?(hoje|amanha))?", normal):
        return "o que tenho na agenda " + ("amanhã" if "amanha" in normal else "hoje")
    if re.fullmatch(r"(?:leia|ler|mostre|mostrar|ver|listar|liste) (?:(?:as|os|minhas|meus|minha|meu) )?(?:notas?|salvos?|anotacoes|anotacao|lembretes?)", normal):
        return "leia minhas notas" if normal.startswith(("leia", "ler")) else "minhas notas"
    if re.fullmatch(r"(?:leia|ler|mostre|mostrar|ver|listar|liste) (?:(?:as|os|minhas|meus|minha|meu|a) )?(?:e ?mails?|caixa de entrada)", normal):
        return "leia meus emails" if normal.startswith(("leia", "ler")) else "meus emails"
    if normal in ("quantas deteccoes de pessoas hoje", "quantas pessoas detectadas hoje"):
        return "quantas pessoas passaram hoje"
    if normal in ("eai", "e ai", "oi", "ola", "alo"):
        return "eai"
    return texto


def navegacao_direta(texto):
    normal = chave(normalizar_comando(texto))
    return bool(re.fullmatch(r"(?:abrir|abra|iniciar) (?:o )?navegador|(?:abrir|abra) (?:uma )?nova aba|(?:fechar|feche|encerrar|encerre) (?:a )?aba(?: (?:do )?navegador)?|(?:proxima|anterior) aba|aba (?:anterior|seguinte)|(?:voltar|volte|avancar|avance|atualizar|atualize|recarregar|recarregue) (?:(?:uma|a) )?pagina(?: no navegador)?", normal))


def comando_direto(texto):
    normal = chave(texto)
    from .briefing_dia import pedido
    return (pedido(texto) or navegacao_direta(texto)
        or bool(re.fullmatch(r"(?:fechar|feche|encerrar) (?:o )?navegador|(?:listar|mostrar|mostre) (?:as )?abas|(?:selecionar|selecione|ir para) (?:a )?aba [1-9][0-9]*|(?:parar|pare) (?:o )?carregamento", normal))
        or bool(re.match(r"^(?:pesquisar|pesquisa|pesquise|buscar|busque|procurar|procure)\b", normal))
        or normal in ("obrigado", "obrigada", "muito obrigado", "muito obrigada", "valeu", "cancelar nota")
        or normalizar_comando(texto) in (
        "ativar protocolo torre stark", "desativar protocolo torre stark"))

# Autoriza IA so em pergunta chamada
def autoriza_ia_voz(texto):
    from . import wake_word
    if not isinstance(texto, str) or not re.match(r"^\s*(?:(?:ei|ok|ola|hey)[ ,]+)?(?:jarvis|jervis|jérvis|jarves|jarbis|jarvys|jarvi|jarvez|javis|charvis)(?!\w)", texto, re.IGNORECASE): return False
    normal = chave(wake_word.remover(texto))
    return bool(re.match(r"^(?:como|o que|oque|qual|quais|quem|quando|onde|por que|porque|quanto|quantos|explique|explica|me explique|me explica|me ajude|me ajuda|pode|voce pode|preciso de ajuda)\b", normal))
