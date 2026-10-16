"""Audita comentários do projeto."""
import ast
import io
import json
import re
import tokenize
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

# Identifica explicações inválidas
def invalido(texto):
    texto = texto.strip()
    if len(texto) > 35 or any(x in texto for x in ("_", "--", "===")):
        return True
    if texto in {"Lê dados", "Grava dados"}:
        return True
    if not texto or len(texto.split()) < 2:
        return True
    if re.match(r"(?:Executa\b|Testa\b|Rotinas auxiliares|Inicializa os recursos da classe)", texto):
        return True
    if re.fullmatch(r"(?:Define|Trata|Atualiza|Carrega|Salva|Consulta) (?:estado|resultado|erro|error|dados|valor|item|itens|opção|opcao)\.?", texto):
        return True
    if "dados locais" in texto or re.search(r"\b(?:e|ou|de|do|da|dos|das|no|na|por|para|com|sem|a|o)\.?$", texto):
        return True
    return False

# Enumera fontes do projeto
def arquivos():
    resultado = [RAIZ / nome for nome in ("main.py", "config.py", "dev_watch.py")]
    for nome in ("comandos", "interface", "hud", "tests", "elevenlabs_eco", "tools", "Android"):
        for arquivo in (RAIZ / nome).rglob("*"):
            if arquivo.suffix not in {".py", ".js", ".css", ".kt", ".kts"}:
                continue
            if any(parte in {"build", ".gradle", "__pycache__"} for parte in arquivo.parts):
                continue
            resultado.append(arquivo)
    return sorted(set(resultado))

# Remove comentários Python inválidos
def python(arquivo, alterar):
    fonte = arquivo.read_text(encoding="utf-8-sig")
    arvore = ast.parse(fonte)
    linhas = fonte.splitlines(True)
    remocoes = []
    for token in tokenize.generate_tokens(io.StringIO(fonte).readline):
        if token.type != tokenize.COMMENT:
            continue
        texto = token.string[1:].strip()
        if texto.startswith(("!", "coding:", "noqa:", "type: ignore")):
            continue
        if invalido(texto):
            linha, coluna = token.start
            fim = token.end[1]
            remocoes.append((linha, coluna, fim))
    for linha, coluna, fim in reversed(remocoes):
        linhas[linha - 1] = linhas[linha - 1][:coluna] + linhas[linha - 1][fim:]
        if not linhas[linha - 1].strip(): linhas[linha - 1] = "\n"
    docs = 0
    for item in ast.walk(arvore):
        if not isinstance(item, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        texto = ast.get_docstring(item, clean=False)
        if texto is None or not invalido(texto):
            continue
        primeiro = item.body[0]
        linhas[primeiro.lineno - 1] = " " * primeiro.col_offset + ("pass\n" if len(item.body) == 1 and not isinstance(item, ast.Module) else "\n")
        for i in range(primeiro.lineno, primeiro.end_lineno): linhas[i] = "\n"
        docs += 1
    nova = "".join(linhas)
    ast.parse(nova)
    if alterar and nova != fonte: arquivo.write_text(nova, encoding="utf-8")
    return len(remocoes) + docs

# Localiza comentários Kotlin e CSS
def intervalos(fonte):
    i = 0
    while i < len(fonte):
        if fonte.startswith('"""', i):
            j = fonte.find('"""', i + 3); i = len(fonte) if j < 0 else j + 3; continue
        if fonte[i] in ('"', "'"):
            aspas = fonte[i]; i += 1
            while i < len(fonte):
                if fonte[i] == "\\": i += 2; continue
                if fonte[i] == aspas: i += 1; break
                i += 1
            continue
        if fonte.startswith("//", i):
            j = fonte.find("\n", i); j = len(fonte) if j < 0 else j
            yield i, j, fonte[i + 2:j]; i = j; continue
        if fonte.startswith("/*", i):
            j = i + 2; nivel = 1
            while j < len(fonte) and nivel:
                if fonte.startswith("/*", j): nivel += 1; j += 2
                elif fonte.startswith("*/", j): nivel -= 1; j += 2
                else: j += 1
            yield i, j, fonte[i + 2:j - 2]; i = j; continue
        i += 1

# Remove comentários sem tocar textos
def outros(arquivo, alterar):
    fonte = arquivo.read_text(encoding="utf-8-sig")
    remover = [(a, b) for a, b, texto in intervalos(fonte) if invalido(texto)]
    nova = fonte
    for a, b in reversed(remover): nova = nova[:a] + "\n" * fonte[a:b].count("\n") + nova[b:]
    if alterar and nova != fonte: arquivo.write_text(nova, encoding="utf-8")
    return len(remover)

# Salva resultado da auditoria
if __name__ == "__main__":
    import sys
    alterar = "--aplicar" in sys.argv
    resultado = {}
    for arquivo in arquivos():
        if arquivo.suffix == ".js": continue
        n = python(arquivo, alterar) if arquivo.suffix == ".py" else outros(arquivo, alterar)
        if n: resultado[str(arquivo.relative_to(RAIZ))] = n
    print(json.dumps({"total":sum(resultado.values()), "arquivos":resultado},ensure_ascii=False))
