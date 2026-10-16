import re




FORTES = (
    "jarvis", "jarves", "jarvi", "jarbis", "jarvez", "jervis",
    "gervis", "gerby", "gerbi", "jar vis", "james", "germes",
    "jarvys", "jarvís", "jarbas", "gerbis", "jérvis", "javis", "charvis",
    "já vis", "já vi", "ja vi", "jar vins", "jesus", "já", "ja", "jardims", "jardin", "já vi", "Chaves", "chave", "jogos de", "Jefferson",
)

CHAMADAS = ("ei", "ok", "ola", "hey")

_SEP = r"[\s,.!?;:\-]+"



def alternativas(itens):
    ordenados = sorted(itens, key=len, reverse=True)
    return "|".join(re.escape(i).replace(r"\ ", r"\s+") for i in ordenados)


_FORTES = alternativas(FORTES)
_CHAMADAS = alternativas(CHAMADAS)


PADRAO_INICIO = re.compile(
    rf"^\s*(?:(?:{_CHAMADAS}){_SEP})?(?:{_FORTES})(?!\w)[\s,.!?;:\-]*",
    re.IGNORECASE,
)


PADRAO_FIM = re.compile(
    rf"{_SEP}(?:(?:{_CHAMADAS}){_SEP})?(?:{_FORTES})[\s.!?]*$",
    re.IGNORECASE,
)



def ativado(texto) :

    return isinstance(texto, str) and PADRAO_INICIO.match(texto) is not None



def remover(texto):

    if not isinstance(texto, str):
        return ""



    while True:
        correspondencia = PADRAO_INICIO.match(texto)
        if not correspondencia:
            break
        restante = texto[correspondencia.end():]
        if restante == texto:
            break
        texto = restante
    texto = PADRAO_FIM.sub("", texto, count=1)
    return texto.strip(" ,.!?:;-")


