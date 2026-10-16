import base64
import email.message
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

BLOCOS = {
    "p",
    "div",
    "section",
    "article",
    "header",
    "footer",
    "table",
    "tr",
    "ul",
    "ol",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "blockquote",
}
IGNORADOS = {"head", "style", "script", "svg", "template", "noscript"}
VAZIOS = {
    "br",
    "hr",
    "img",
    "meta",
    "link",
    "input",
    "wbr",
    "source",
    "area",
    "base",
    "embed",
    "param",
    "track",
}


# Mantem paragrafos da mensagem
def normalizar(texto):
    texto = texto.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    linhas = [re.sub(r"[ \t]+", " ", linha).strip() for linha in texto.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(linhas)).strip()[:12000]


class TextoEmail(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes = []
        self.ignorados = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        oculto = "hidden" in atributos or bool(
            re.search(
                r"(?:display\s*:\s*none|visibility\s*:\s*hidden)",
                atributos.get("style") or "",
                re.I,
            )
        )
        if self.ignorados or tag in IGNORADOS or oculto:
            if tag not in VAZIOS:
                self.ignorados.append(tag)
            return
        if tag in BLOCOS or tag in {"br", "hr"}:
            self.partes.append("\n\n" if tag in BLOCOS else "\n")
        if tag == "td":
            self.partes.append(" ")
        if tag == "a":
            href = atributos.get("href") or ""
            try:
                url = urlsplit(href)
                self.links.append(
                    href if url.scheme in {"http", "https"} and url.hostname else ""
                )
            except ValueError:
                self.links.append("")

    # Descarta CSS e scripts por inteiro
    def handle_endtag(self, tag):
        if self.ignorados:
            if tag in self.ignorados:
                indice = len(self.ignorados) - 1 - self.ignorados[::-1].index(tag)
                del self.ignorados[indice:]
            return
        if tag == "a" and self.links:
            href = self.links.pop()
            if href:
                self.partes.append(" " + href + " ")
        if tag in BLOCOS:
            self.partes.append("\n\n")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VAZIOS:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if not self.ignorados:
            self.partes.append(data)


# Extrai apenas conteudo de mensagem
def extrair_payload(payload):
    plain = rich = ""
    stack = [payload]
    while stack:
        item = stack.pop()
        if not isinstance(item, dict) or item.get("filename"):
            continue
        mime = item.get("mimeType", "")
        body = item.get("body") or {}
        data = body.get("data")
        if isinstance(data, str) and mime in {"text/plain", "text/html"}:
            try:
                headers = email.message.Message()
                for header in item.get("headers") or []:
                    if str(header.get("name", "")).lower() == "content-type":
                        headers["Content-Type"] = header.get("value", "")
                charset = headers.get_content_charset() or "utf-8"
                decoded = base64.urlsafe_b64decode(
                    data + "=" * (-len(data) % 4)
                ).decode(charset, errors="replace")
            except (ValueError, UnicodeError, LookupError):
                decoded = ""
            if mime == "text/plain" and not plain:
                plain = decoded
            if mime == "text/html" and not rich:
                rich = decoded
        stack.extend(reversed(item.get("parts") or []))
    if plain:
        return normalizar(plain)
    parser = TextoEmail()
    parser.feed(rich[:500000])
    parser.close()
    return normalizar("".join(parser.partes))
