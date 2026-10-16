import logging

import hashlib

import re

import sqlite3

import threading

from contextlib import closing

from datetime import datetime

import config

log = logging.getLogger("mark2.memoria")

DB_PATH = config.DATA_DIR / "memoria_mark2.db"

TRAVA = threading.Lock()

AREAS_NOTAS_HUD = {
    "metas",
    "trabalho",
    "projetos",
    "financas",
    "aprendizado",
    "saude",
    "relacoes",
    "meta",
}


# Abre a conexão local
def conectar():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conexao = sqlite3.connect(DB_PATH, timeout=10)
    conexao.row_factory = sqlite3.Row
    return conexao


# Inicializa banco
def inicializar_banco():
    with TRAVA, closing(conectar()) as conexao:
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS mensagens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                papel TEXT NOT NULL,
                conteudo TEXT NOT NULL,
                criado_em TEXT NOT NULL
            )
            """)
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS fatos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conteudo TEXT NOT NULL UNIQUE,
                criado_em TEXT NOT NULL
            )
            """)
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS resumo (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                conteudo TEXT NOT NULL DEFAULT '',
                ate_mensagem_id INTEGER NOT NULL DEFAULT 0
            )
            """)
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS notas_hud (
                id TEXT PRIMARY KEY,
                area TEXT NOT NULL,
                titulo TEXT NOT NULL COLLATE NOCASE UNIQUE,
                conteudo TEXT NOT NULL,
                fato_conteudo TEXT NOT NULL UNIQUE,
                atualizado_em TEXT NOT NULL
            )
            """)
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS compromissos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                inicio TEXT NOT NULL,
                descricao TEXT NOT NULL DEFAULT '',
                antecedencia_minutos INTEGER NOT NULL DEFAULT 10,
                criado_em TEXT NOT NULL
            )
            """)
        conexao.execute(
            "CREATE INDEX IF NOT EXISTS idx_compromissos_inicio ON compromissos(inicio)"
        )
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS memorias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                categoria TEXT NOT NULL,
                conteudo TEXT NOT NULL,
                importancia REAL NOT NULL DEFAULT 0.5,
                confianca REAL NOT NULL DEFAULT 0.7,
                origemMensagem INTEGER,
                versao INTEGER NOT NULL DEFAULT 1,
                ativa INTEGER NOT NULL DEFAULT 1,
                motivo TEXT NOT NULL DEFAULT '',
                criadaEm TEXT NOT NULL,
                atualizadaEm TEXT NOT NULL
            )
            """)
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS historicoMemoria (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memoriaId INTEGER NOT NULL,
                conteudo TEXT NOT NULL,
                versao INTEGER NOT NULL,
                criadaEm TEXT NOT NULL
            )
            """)
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS relacoesMemoria (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                origem TEXT NOT NULL,
                tipo TEXT NOT NULL,
                destino TEXT NOT NULL,
                memoriaId INTEGER,
                criadaEm TEXT NOT NULL,
                UNIQUE(origem, tipo, destino)
            )
            """)
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS estadoOperacional (
                chave TEXT PRIMARY KEY,
                valor TEXT NOT NULL,
                confianca REAL NOT NULL DEFAULT 0.7,
                atualizadaEm TEXT NOT NULL
            )
            """)
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS projetosMemoria (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL COLLATE NOCASE UNIQUE,
                estado TEXT NOT NULL DEFAULT 'ativo',
                resumo TEXT NOT NULL DEFAULT '',
                atualizadaEm TEXT NOT NULL
            )
            """)
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS tarefasMemoria (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                projetoId INTEGER,
                titulo TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'pendente',
                atualizadaEm TEXT NOT NULL,
                UNIQUE(projetoId, titulo)
            )
            """)
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS planosMemoria (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                objetivo TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'ativo',
                criadaEm TEXT NOT NULL,
                atualizadaEm TEXT NOT NULL
            )
            """)
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS etapasPlano (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                planoId INTEGER NOT NULL,
                ordem INTEGER NOT NULL,
                descricao TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'pendente',
                atualizadaEm TEXT NOT NULL,
                UNIQUE(planoId, ordem),
                FOREIGN KEY(planoId) REFERENCES planosMemoria(id) ON DELETE CASCADE
            )
            """)
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS ajustesMemoria (
                chave TEXT PRIMARY KEY,
                valor TEXT NOT NULL
            )
            """)
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS exclusoesMemoria (
                mensagemId INTEGER PRIMARY KEY
            )
            """)
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS itensEsquecidos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                termosHash TEXT NOT NULL UNIQUE,
                criadaEm TEXT NOT NULL
            )
            """)
        conexao.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS historicoBusca USING fts5(
                conteudo, content='mensagens', content_rowid='id'
            )
            """)
        conexao.execute("""
            CREATE TRIGGER IF NOT EXISTS mensagensBuscaInsert AFTER INSERT ON mensagens BEGIN
                INSERT INTO historicoBusca(rowid, conteudo) VALUES (new.id, new.conteudo);
            END
            """)
        conexao.execute("""
            CREATE TRIGGER IF NOT EXISTS mensagensBuscaDelete AFTER DELETE ON mensagens BEGIN
                INSERT INTO historicoBusca(historicoBusca, rowid, conteudo)
                VALUES ('delete', old.id, old.conteudo);
            END
            """)
        conexao.execute("""
            CREATE TRIGGER IF NOT EXISTS mensagensBuscaUpdate AFTER UPDATE ON mensagens BEGIN
                INSERT INTO historicoBusca(historicoBusca, rowid, conteudo)
                VALUES ('delete', old.id, old.conteudo);
                INSERT INTO historicoBusca(rowid, conteudo) VALUES (new.id, new.conteudo);
            END
            """)
        indicePronto = conexao.execute(
            "SELECT valor FROM ajustesMemoria WHERE chave = 'indiceHistoricoPronto'"
        ).fetchone()
        if not indicePronto:
            conexao.execute(
                "INSERT INTO historicoBusca(historicoBusca) VALUES ('rebuild')"
            )
            conexao.execute(
                "INSERT INTO ajustesMemoria(chave, valor) VALUES ('indiceHistoricoPronto', '1')"
            )
        colunas_resumo = {
            linha["name"]
            for linha in conexao.execute("PRAGMA table_info(resumo)").fetchall()
        }
        if "ate_mensagem_id" not in colunas_resumo:
            conexao.execute(
                "ALTER TABLE resumo ADD COLUMN ate_mensagem_id INTEGER NOT NULL DEFAULT 0"
            )
        conexao.execute("PRAGMA optimize")
        conexao.commit()


inicializar_banco()


# Registra mensagem
def registrar_mensagem(papel, conteudo):
    if not isinstance(papel, str) or not papel.strip():
        return False
    if not isinstance(conteudo, str) or not conteudo.strip():
        return False
    with TRAVA, closing(conectar()) as conexao:
        conexao.execute(
            "INSERT INTO mensagens (papel, conteudo, criado_em) VALUES (?, ?, ?)",
            (papel.strip(), conteudo.strip(), datetime.now().isoformat()),
        )
        conexao.commit()
    return True


# Consulta timestamp ultima mensagem
def obter_timestamp_ultima_mensagem():

    with TRAVA, closing(conectar()) as conexao:
        linha = conexao.execute(
            "SELECT criado_em FROM mensagens ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not linha:
        return None
    try:
        return datetime.fromisoformat(linha["criado_em"])
    except (TypeError, ValueError):
        return None



def contar_mensagens_usuario():
    with TRAVA, closing(conectar()) as conexao:
        linha = conexao.execute(
            "SELECT COUNT(*) AS total FROM mensagens WHERE papel = 'user'"
        ).fetchone()
        return linha["total"] if linha else 0


# Consulta historico recente
def obter_historico_recente(limite=20, incluir_ids=False):
    if not isinstance(limite, int) or isinstance(limite, bool) or limite <= 0:
        return []
    limite = min(limite, 10_000)
    with TRAVA, closing(conectar()) as conexao:
        linhas = conexao.execute(
            "SELECT id, papel, conteudo FROM mensagens ORDER BY id DESC LIMIT ?",
            (limite,),
        ).fetchall()

    resultado = []
    for linha in reversed(linhas):
        mensagem = {"role": linha["papel"], "content": linha["conteudo"]}
        if incluir_ids:
            mensagem["id"] = linha["id"]
        resultado.append(mensagem)
    return resultado


# Consulta historico intervalo
def obter_historico_intervalo(depois_de_id, antes_de_id, limite=200):
    if not isinstance(depois_de_id, int) or not isinstance(antes_de_id, int):
        return []
    if not isinstance(limite, int) or limite <= 0 or antes_de_id <= depois_de_id:
        return []
    with TRAVA, closing(conectar()) as conexao:
        linhas = conexao.execute(
            "SELECT id, papel, conteudo FROM mensagens "
            "WHERE id > ? AND id < ? ORDER BY id ASC LIMIT ?",
            (depois_de_id, antes_de_id, min(limite, 1000)),
        ).fetchall()
    return [
        {"id": linha["id"], "role": linha["papel"], "content": linha["conteudo"]}
        for linha in linhas
    ]


# Salva fato
def salvar_fato(fato):
    if not isinstance(fato, str):
        return False
    fato = fato.strip()
    if not fato:
        return False
    try:
        with TRAVA, closing(conectar()) as conexao:
            cursor = conexao.execute(
                "INSERT OR IGNORE INTO fatos (conteudo, criado_em) VALUES (?, ?)",
                (fato, datetime.now().isoformat()),
            )
            conexao.commit()
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        log.error(f"Falha ao salvar fato: {e}")
        return False


# Consulta fatos
def obter_fatos():
    with TRAVA, closing(conectar()) as conexao:
        linhas = conexao.execute(
            "SELECT conteudo FROM fatos ORDER BY id ASC"
        ).fetchall()
    return [linha["conteudo"] for linha in linhas]


# Infere area nota
def inferir_area_nota(texto):
    texto = texto.casefold()
    if any(termo in texto for termo in ("meta", "objetivo", "futuro")):
        return "metas"
    if any(termo in texto for termo in ("trabalho", "carreira", "faculdade", "curso")):
        return "trabalho"
    if "projeto" in texto:
        return "projetos"
    if any(termo in texto for termo in ("dinheiro", "finan", "invest")):
        return "financas"
    if any(termo in texto for termo in ("aprender", "estudar", "livro")):
        return "aprendizado"
    if any(termo in texto for termo in ("saúde", "saude", "treino", "sono")):
        return "saude"
    if any(termo in texto for termo in ("família", "familia", "amigo", "namor")):
        return "relacoes"
    return "meta"



def titulo_fato(fato, id_fato):
    trecho = fato.split(":", 1)[0].strip(" []—-")
    if not trecho or len(trecho) > 42:
        palavras = re.findall(r"[\wÀ-ÿ]+", fato, flags=re.UNICODE)[:4]
        trecho = " ".join(palavras)
    return trecho[:42] or f"Memória {id_fato}"


# Sincroniza fatos com notas
def sincronizar_fatos_com_notas(conexao):
    fatos = conexao.execute(
        "SELECT id, conteudo FROM fatos "
        "WHERE conteudo NOT IN (SELECT fato_conteudo FROM notas_hud) "
        "ORDER BY id ASC"
    ).fetchall()
    for fato in fatos:
        titulo_base = titulo_fato(fato["conteudo"], fato["id"])
        titulo = titulo_base
        sufixo = 2
        while conexao.execute(
            "SELECT 1 FROM notas_hud WHERE titulo = ? COLLATE NOCASE",
            (titulo,),
        ).fetchone():
            titulo = f"{titulo_base[:36]} {sufixo}"
            sufixo += 1
        conexao.execute(
            "INSERT OR IGNORE INTO notas_hud "
            "(id, area, titulo, conteudo, fato_conteudo, atualizado_em) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                f"fato-{fato['id']}",
                inferir_area_nota(fato["conteudo"]),
                titulo,
                fato["conteudo"],
                fato["conteudo"],
                datetime.now().isoformat(),
            ),
        )


# Lista notas hud
def listar_notas_hud():
    with TRAVA, closing(conectar()) as conexao:
        sincronizar_fatos_com_notas(conexao)
        linhas = conexao.execute(
            "SELECT id, area, titulo, conteudo FROM notas_hud "
            "ORDER BY atualizado_em ASC, id ASC"
        ).fetchall()
        conexao.commit()
    return [
        {
            "id": linha["id"],
            "area": linha["area"],
            "title": linha["titulo"],
            "body": linha["conteudo"],
        }
        for linha in linhas
    ]


# Lista notas relacionadas
def listar_notas_relacionadas(id_nota, limite=2):
    if not isinstance(id_nota, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9-]{0,79}", id_nota.strip()
    ):
        return []
    if not isinstance(limite, int) or isinstance(limite, bool):
        return []
    limite = max(1, min(limite, 6))
    with TRAVA, closing(conectar()) as conexao:
        origem = conexao.execute(
            "SELECT id, area, titulo, conteudo FROM notas_hud WHERE id = ?",
            (id_nota.strip(),),
        ).fetchone()
        if origem is None:
            return []
        candidatas = conexao.execute(
            "SELECT id, area, titulo, conteudo, atualizado_em FROM notas_hud "
            "WHERE id != ? ORDER BY atualizado_em DESC, id ASC",
            (id_nota.strip(),),
        ).fetchall()


    def termos(texto):
        return {
            palavra.casefold()
            for palavra in re.findall(r"[\wÀ-ÿ]+", texto)
            if len(palavra) > 2 and palavra.casefold() not in PALAVRAS_IGNORADAS_BUSCA
        }

    termos_origem = termos(f"{origem['titulo']} {origem['conteudo']}")
    pontuadas = []
    for ordem, candidata in enumerate(candidatas):
        compartilhados = termos_origem & termos(
            f"{candidata['titulo']} {candidata['conteudo']}"
        )
        pontuacao = len(compartilhados) * 3
        if candidata["area"] == origem["area"]:
            pontuacao += 5
        pontuadas.append((pontuacao, -ordem, candidata))
    pontuadas.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [
        {
            "id": linha["id"],
            "area": linha["area"],
            "title": linha["titulo"],
            "body": linha["conteudo"],
        }
        for _, _, linha in pontuadas[:limite]
    ]


# Atualiza contexto após notas salvas
def sincronizar_contexto_privado():
    try:
        from comandos import contexto_local
        contexto_local.sincronizar(listar_notas_hud())
    except (OSError,ValueError,sqlite3.Error):log.error("Contexto privado não atualizado")

# Salva nota hud
def salvar_nota_hud(id_nota, area, titulo, conteudo):
    if not all(isinstance(valor, str) for valor in (id_nota, area, titulo, conteudo)):
        return False
    id_nota = id_nota.strip()
    area = area.strip()
    titulo = " ".join(titulo.split()).strip()
    conteudo = conteudo.strip()
    if (
        not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", id_nota)
        or area not in AREAS_NOTAS_HUD
        or not titulo
        or len(titulo) > 42
        or not conteudo
        or len(conteudo) > 1200
    ):
        return False
    fato_novo = f"{titulo}: {conteudo}"
    try:
        with TRAVA, closing(conectar()) as conexao:
            anterior = conexao.execute(
                "SELECT fato_conteudo FROM notas_hud WHERE id = ?",
                (id_nota,),
            ).fetchone()
            if anterior and anterior["fato_conteudo"] != fato_novo:
                conexao.execute(
                    "DELETE FROM fatos WHERE conteudo = ?",
                    (anterior["fato_conteudo"],),
                )
            conexao.execute(
                "INSERT INTO notas_hud "
                "(id, area, titulo, conteudo, fato_conteudo, atualizado_em) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET area = excluded.area, "
                "titulo = excluded.titulo, conteudo = excluded.conteudo, "
                "fato_conteudo = excluded.fato_conteudo, "
                "atualizado_em = excluded.atualizado_em",
                (
                    id_nota,
                    area,
                    titulo,
                    conteudo,
                    fato_novo,
                    datetime.now().isoformat(),
                ),
            )
            conexao.execute(
                "INSERT OR IGNORE INTO fatos (conteudo, criado_em) VALUES (?, ?)",
                (fato_novo, datetime.now().isoformat()),
            )
            conexao.commit()
        sincronizar_contexto_privado()
        return True
    except sqlite3.Error:
        log.error("Falha ao salvar nota da HUD.", exc_info=True)
        return False


# Remove nota hud
def remover_nota_hud(id_nota):
    if not isinstance(id_nota, str) or not re.fullmatch(
        r"[a-z0-9][a-z0-9-]{0,79}", id_nota.strip()
    ):
        return False
    try:
        with TRAVA, closing(conectar()) as conexao:
            anterior = conexao.execute(
                "SELECT fato_conteudo FROM notas_hud WHERE id = ?",
                (id_nota.strip(),),
            ).fetchone()
            if anterior is None:
                return False
            conexao.execute("DELETE FROM notas_hud WHERE id = ?", (id_nota.strip(),))
            conexao.execute(
                "DELETE FROM fatos WHERE conteudo = ?",
                (anterior["fato_conteudo"],),
            )
            conexao.commit()
        sincronizar_contexto_privado()
        return True
    except sqlite3.Error:
        log.error("Falha ao remover nota da HUD.", exc_info=True)
        return False


# Cria compromisso
def criar_compromisso(titulo, inicio, descricao="", antecedencia_minutos=10):
    if not all(isinstance(valor, str) for valor in (titulo, inicio, descricao)):
        return None
    titulo = " ".join(titulo.split()).strip()[:120]
    descricao = descricao.strip()[:1200]
    if not titulo or not inicio:
        return None
    try:
        momento = datetime.fromisoformat(inicio)
        if momento.tzinfo is not None:
            momento = momento.astimezone().replace(tzinfo=None)
        antecedencia_minutos = max(0, min(int(antecedencia_minutos), 10080))
    except (TypeError, ValueError, OverflowError):
        return None
    agora = datetime.now().isoformat(timespec="seconds")
    try:
        with TRAVA, closing(conectar()) as conexao:
            cursor = conexao.execute(
                "INSERT INTO compromissos (titulo, inicio, descricao, antecedencia_minutos, criado_em) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    titulo,
                    momento.isoformat(timespec="minutes"),
                    descricao,
                    antecedencia_minutos,
                    agora,
                ),
            )
            conexao.commit()
            return cursor.lastrowid
    except sqlite3.Error:
        log.error("Falha ao registrar compromisso.", exc_info=True)
        return None


# Lista compromissos
def listar_compromissos(limite=50, desde=None, ate=None):
    try:
        limite = max(1, min(int(limite), 200))
    except (TypeError, ValueError, OverflowError):
        limite = 50
    consulta = "SELECT id, titulo, inicio, descricao, antecedencia_minutos FROM compromissos WHERE 1=1"
    parametros = []
    if desde:
        consulta += " AND inicio >= ?"
        parametros.append(desde)
    if ate:
        consulta += " AND inicio < ?"
        parametros.append(ate)
    consulta += " ORDER BY inicio ASC LIMIT ?"
    parametros.append(limite)
    with TRAVA, closing(conectar()) as conexao:
        linhas = conexao.execute(consulta, parametros).fetchall()
    return [dict(linha) for linha in linhas]


# Remove compromisso
def remover_compromisso(identificador):
    try:
        identificador = int(identificador)
    except (TypeError, ValueError, OverflowError):
        return False
    if identificador < 1:
        return False
    with TRAVA, closing(conectar()) as conexao:
        cursor = conexao.execute(
            "DELETE FROM compromissos WHERE id = ?", (identificador,)
        )
        conexao.commit()
    return bool(cursor.rowcount)


PALAVRAS_IGNORADAS_BUSCA = {
    "o",
    "a",
    "os",
    "as",
    "um",
    "uma",
    "uns",
    "umas",
    "de",
    "da",
    "do",
    "das",
    "dos",
    "em",
    "no",
    "na",
    "nos",
    "nas",
    "para",
    "pra",
    "por",
    "com",
    "sem",
    "que",
    "e",
    "ou",
    "me",
    "te",
    "se",
    "meu",
    "minha",
    "meus",
    "minhas",
    "seu",
    "sua",
    "seus",
    "suas",
    "sobre",
    "como",
    "qual",
    "quais",
    "isso",
    "essa",
    "esse",
    "aquilo",
    "aquela",
    "aquele",
    "voce",
    "você",
    "eu",
    "ele",
    "ela",
    "eles",
    "elas",
    "fala",
    "falar",
    "diga",
    "vou",
    "vai",
    "tá",
    "ta",
    "é",
    "foi",
    "ser",
    "estou",
    "está",
}

PALAVRAS_RELACIONAMENTO_BUSCA = {
    "namorada",
    "namorado",
    "crush",
    "paquera",
    "ficante",
    "ficando",
    "fiquei",
    "relacionamento",
    "namoro",
    "casamento",
    "noiva",
    "noivo",
    "ex",
    "date",
    "encontro",
    "beijei",
    "beijou",
    "apaixonado",
    "apaixonada",
    "rolo",
    "affair",
    "peguei",
    "terminei",
    "terminou",
    "traição",
    "traiu",
    "gosto dela",
    "gosto dele",
}

PALAVRAS_ESTADO_TRISTE = {
    "triste",
    "mal",
    "chateado",
    "chateada",
    "doeu",
    "péssimo",
    "deprimido",
    "deprimida",
    "desanimado",
    "desanimada",
    "sozinho",
    "sozinha",
    "chorando",
    "chorei",
    "magoado",
    "magoada",
    "decepcionado",
    "decepcionada",
    "sofrendo",
    "cansei",
    "não aguento",
    "nao aguento",
}

PALAVRAS_ESTADO_FELIZ = {
    "feliz",
    "animado",
    "animada",
    "empolgado",
    "empolgada",
    "ótimo",
    "otimo",
    "ótima",
    "otima",
    "consegui",
    "deu certo",
    "adorei",
    "amei",
}



def contem_expressao(texto, expressao):
    return (
        re.search(rf"(?<!\w){re.escape(expressao.casefold())}(?!\w)", texto.casefold())
        is not None
    )


# Extrai nomes proprios
def extrair_nomes_proprios(texto_original):
    if not isinstance(texto_original, str):
        return set()
    nomes = set()
    palavras = texto_original.split()
    for indice, palavra in enumerate(palavras):
        limpo = palavra.strip(".,!?:;()\"'")
        if not limpo or not limpo[0].isupper():
            continue
        if indice == 0:
            continue
        if limpo.lower() in PALAVRAS_IGNORADAS_BUSCA:
            continue
        nomes.add(limpo.lower())
    return nomes


# Detecta estado emocional
def detectar_estado_emocional(texto_mensagem):
    if not isinstance(texto_mensagem, str):
        return None
    texto_lower = texto_mensagem.lower()
    if any(
        contem_expressao(texto_lower, palavra) for palavra in PALAVRAS_ESTADO_TRISTE
    ):
        return "triste"
    if any(contem_expressao(texto_lower, palavra) for palavra in PALAVRAS_ESTADO_FELIZ):
        return "feliz"
    return None


# Busca fatos relevantes
def buscar_fatos_relevantes(texto_mensagem, maximo=8):
    if not isinstance(texto_mensagem, str):
        texto_mensagem = ""
    if not isinstance(maximo, int) or isinstance(maximo, bool) or maximo <= 0:
        return []
    maximo = min(maximo, 100)
    todos_fatos = obter_fatos()
    if not todos_fatos:
        return []

    palavras = palavrasMemoria(texto_mensagem)
    if not palavras:
        return []
    pontuadas = []
    for fato in todos_fatos:
        termos = palavrasMemoria(fato)
        comum = palavras & termos
        if comum:
            pontuadas.append((len(comum) / max(1, len(palavras | termos)), fato))
    pontuadas.sort(key=lambda item: item[0], reverse=True)
    return [fato for _, fato in pontuadas[:maximo]]


# Remove fatos contendo
def remover_fatos_contendo(trecho_busca):
    if not isinstance(trecho_busca, str) or not trecho_busca.strip():
        return 0
    trecho_busca = (
        trecho_busca.strip()
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    with TRAVA, closing(conectar()) as conexao:
        cursor = conexao.execute(
            "DELETE FROM fatos WHERE conteudo LIKE ? ESCAPE '\\'",
            (f"%{trecho_busca}%",),
        )
        conexao.commit()
        return cursor.rowcount



def apagar_tudo():
    with TRAVA, closing(conectar()) as conexao:
        conexao.execute("DELETE FROM mensagens")
        conexao.execute("DELETE FROM fatos")
        conexao.execute("DELETE FROM resumo")
        conexao.execute("DELETE FROM notas_hud")
        conexao.execute("DELETE FROM memorias")
        conexao.execute("DELETE FROM historicoMemoria")
        conexao.execute("DELETE FROM relacoesMemoria")
        conexao.execute("DELETE FROM estadoOperacional")
        conexao.execute("DELETE FROM projetosMemoria")
        conexao.execute("DELETE FROM tarefasMemoria")
        conexao.execute("DELETE FROM etapasPlano")
        conexao.execute("DELETE FROM planosMemoria")
        conexao.execute("DELETE FROM exclusoesMemoria")
        conexao.execute("DELETE FROM itensEsquecidos")
        conexao.execute("INSERT INTO historicoBusca(historicoBusca) VALUES ('rebuild')")
        conexao.commit()



def apagar_conversa():
    with TRAVA, closing(conectar()) as conexao:
        conexao.execute("DELETE FROM mensagens")
        conexao.execute("DELETE FROM resumo")
        conexao.execute("DELETE FROM exclusoesMemoria")
        conexao.commit()


# Salva resumo
def salvar_resumo(texto, ate_mensagem_id=None):
    if not isinstance(texto, str) or not texto.strip():
        return False
    if ate_mensagem_id is not None and (
        not isinstance(ate_mensagem_id, int)
        or isinstance(ate_mensagem_id, bool)
        or ate_mensagem_id < 0
    ):
        return False
    with TRAVA, closing(conectar()) as conexao:
        linha = conexao.execute(
            "SELECT ate_mensagem_id FROM resumo WHERE id = 1"
        ).fetchone()
        cursor_atual = linha["ate_mensagem_id"] if linha else 0
        cursor_novo = cursor_atual if ate_mensagem_id is None else ate_mensagem_id
        conexao.execute(
            "INSERT INTO resumo (id, conteudo, ate_mensagem_id) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET conteudo = excluded.conteudo, "
            "ate_mensagem_id = excluded.ate_mensagem_id",
            (texto.strip(), cursor_novo),
        )
        conexao.commit()
    return True


# Consulta resumo atual
def obter_resumo_atual():
    return obter_estado_resumo()["conteudo"] or None


# Consulta estado resumo
def obter_estado_resumo():
    with TRAVA, closing(conectar()) as conexao:
        linha = conexao.execute(
            "SELECT conteudo, ate_mensagem_id FROM resumo WHERE id = 1"
        ).fetchone()
    if linha is None:
        return {"conteudo": "", "ate_mensagem_id": 0}
    return {
        "conteudo": linha["conteudo"] or "",
        "ate_mensagem_id": max(0, linha["ate_mensagem_id"] or 0),
    }


# Normaliza memoria
def normalizarMemoria(texto):
    import unicodedata

    base = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(letra for letra in base if not unicodedata.combining(letra))



def palavrasMemoria(texto):
    equivalencias = {
        "luz": "iluminacao",
        "luzes": "iluminacao",
        "lampada": "iluminacao",
        "lampadas": "iluminacao",
        "sensor": "sensores",
        "presenca": "sensores",
        "movimento": "sensores",
        "smartphone": "android",
        "celular": "android",
        "telefone": "android",
        "vigia": "camera",
        "cameras": "camera",
        "filmagem": "camera",
        "microfone": "voz",
        "fala": "voz",
        "audio": "voz",
        "modelo": "servidor_local",
        "qwen": "servidor_local",
    }
    return {
        equivalencias.get(palavra, palavra)
        for palavra in re.findall(r"[a-z0-9]{2,}", normalizarMemoria(texto))
        if palavra not in PALAVRAS_IGNORADAS_BUSCA
    }


# Salva memoria
def salvarMemoria(
    conteudo,
    categoria="semantica",
    importancia=0.65,
    confianca=0.75,
    origem=None,
    motivo="extraida da conversa",
):
    if not isinstance(conteudo, str):
        return False
    conteudo = " ".join(conteudo.split()).strip(" -\t\r\n")
    categorias = {
        "episodica",
        "semantica",
        "projeto",
        "preferencia",
        "decisao",
        "operacional",
    }
    if not conteudo or len(conteudo) > 2000 or categoria not in categorias:
        return False
    try:
        importancia = max(0.0, min(1.0, float(importancia)))
        confianca = max(0.0, min(1.0, float(confianca)))
    except (TypeError, ValueError):
        return False
    agora = datetime.now().isoformat()
    palavras = palavrasMemoria(conteudo)
    if not palavras:
        return False
    with TRAVA, closing(conectar()) as conexao:
        linhas = conexao.execute(
            "SELECT * FROM memorias WHERE ativa = 1 ORDER BY atualizadaEm DESC LIMIT 800"
        ).fetchall()
        melhor = None
        maior = 0.0
        projetoNovo = nomeProjetoMemoria(conteudo) if categoria == "projeto" else ""
        for linha in linhas:
            termos = palavrasMemoria(linha["conteudo"])
            semelhanca = len(palavras & termos) / max(1, len(palavras | termos))
            if (
                categoria == "projeto"
                and linha["categoria"] == categoria
                and projetoNovo
                and nomeProjetoMemoria(linha["conteudo"]) == projetoNovo
            ):
                semelhanca = max(semelhanca, 0.9)
            if semelhanca > maior:
                melhor, maior = linha, semelhanca
        corteDuplicata = 0.72
        if categoria == "preferencia" and melhor and melhor["categoria"] == categoria:
            corteDuplicata = 0.35
        if categoria == "projeto" and melhor and melhor["categoria"] == categoria:
            corteDuplicata = 0.4
        if melhor and maior >= corteDuplicata:
            mesma = normalizarMemoria(melhor["conteudo"]) == normalizarMemoria(conteudo)
            if mesma:
                texto = melhor["conteudo"]
            elif categoria == "projeto" and projetoNovo == nomeProjetoMemoria(
                melhor["conteudo"]
            ):
                texto = f"{melhor['conteudo'].rstrip('. ')}. {conteudo}"
            else:
                texto = conteudo
            if not mesma:
                conexao.execute(
                    "INSERT INTO historicoMemoria(memoriaId, conteudo, versao, criadaEm) VALUES (?, ?, ?, ?)",
                    (melhor["id"], melhor["conteudo"], melhor["versao"], agora),
                )
                if categoria == "preferencia":
                    fatosAntigos = conexao.execute(
                        "SELECT id, conteudo FROM fatos"
                    ).fetchall()
                    idsAntigos = [
                        item["id"]
                        for item in fatosAntigos
                        if normalizarMemoria(item["conteudo"])
                        == normalizarMemoria(melhor["conteudo"])
                    ]
                    if idsAntigos:
                        conexao.executemany(
                            "DELETE FROM fatos WHERE id = ?",
                            [(item,) for item in idsAntigos],
                        )
            conexao.execute(
                "UPDATE memorias SET conteudo = ?, categoria = ?, importancia = ?, confianca = ?, "
                "versao = versao + ?, atualizadaEm = ?, motivo = ? WHERE id = ?",
                (
                    texto,
                    categoria,
                    max(importancia, melhor["importancia"]),
                    confianca,
                    0 if mesma else 1,
                    agora,
                    motivo,
                    melhor["id"],
                ),
            )
            memoria_id = melhor["id"]
        else:
            cursor = conexao.execute(
                "INSERT INTO memorias (categoria, conteudo, importancia, confianca, origemMensagem, motivo, criadaEm, atualizadaEm) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    categoria,
                    conteudo,
                    importancia,
                    confianca,
                    origem,
                    motivo,
                    agora,
                    agora,
                ),
            )
            memoria_id = cursor.lastrowid
        if categoria in {"projeto", "decisao", "operacional"}:
            atualizarEstadoProjeto(conexao, conteudo, categoria, agora)
        registrarRelacoesAutomaticas(conexao, conteudo, categoria, memoria_id, agora)
        conexao.commit()
    return memoria_id


# Atualiza estado projeto
def atualizarEstadoProjeto(conexao, conteudo, categoria, agora):
    texto = conteudo.strip()
    termos = palavrasMemoria(texto)
    if categoria == "projeto" or "projeto" in termos:
        nome = nomeProjetoMemoria(texto) or texto[:60]
        conexao.execute(
            "INSERT INTO projetosMemoria(nome, resumo, atualizadaEm) VALUES (?, ?, ?) "
            "ON CONFLICT(nome) DO UPDATE SET resumo = substr(CASE WHEN instr(lower(projetosMemoria.resumo), lower(excluded.resumo)) > 0 THEN projetosMemoria.resumo ELSE projetosMemoria.resumo || ' ' || excluded.resumo END, -3000), atualizadaEm = excluded.atualizadaEm",
            (nome, texto, agora),
        )
    if categoria in {"decisao", "operacional"}:
        chave = (
            "objetivo atual"
            if any(t in termos for t in ("objetivo", "meta", "foco"))
            else "progresso recente"
        )
        conexao.execute(
            "INSERT INTO estadoOperacional(chave, valor, confianca, atualizadaEm) VALUES (?, ?, 0.75, ?) "
            "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, confianca = excluded.confianca, atualizadaEm = excluded.atualizadaEm",
            (chave, texto, agora),
        )
    palavrasPendentes = (
        "pendente",
        "preciso",
        "falta",
        "tenho que",
        "devo",
        "proximo passo",
        "lembrar de",
    )
    palavrasFechadas = (
        "conclui",
        "finalizei",
        "terminei",
        "resolvido",
        "feito",
        "concluido",
    )
    if categoria == "operacional" and any(
        palavra in normalizarMemoria(texto) for palavra in palavrasPendentes
    ):
        projeto = conexao.execute(
            "SELECT id FROM projetosMemoria WHERE estado = 'ativo' ORDER BY atualizadaEm DESC LIMIT 1"
        ).fetchone()
        projetoId = projeto["id"] if projeto else None
        existente = conexao.execute(
            "SELECT id FROM tarefasMemoria WHERE projetoId IS ? AND lower(titulo) = lower(?) AND estado = 'pendente'",
            (projetoId, texto[:300]),
        ).fetchone()
        if not existente:
            conexao.execute(
                "INSERT INTO tarefasMemoria(projetoId, titulo, estado, atualizadaEm) VALUES (?, ?, 'pendente', ?)",
                (projetoId, texto[:300], agora),
            )
    if categoria == "operacional" and any(
        palavra in normalizarMemoria(texto) for palavra in palavrasFechadas
    ):
        existentes = conexao.execute(
            "SELECT id, titulo FROM tarefasMemoria WHERE estado = 'pendente'"
        ).fetchall()
        termosNovos = palavrasMemoria(texto)
        for tarefa in existentes:
            termosTarefa = palavrasMemoria(tarefa["titulo"])
            if (
                len(termosNovos & termosTarefa)
                / max(1, len(termosNovos | termosTarefa))
                >= 0.2
            ):
                conexao.execute(
                    "UPDATE tarefasMemoria SET estado = 'concluida', atualizadaEm = ? WHERE id = ?",
                    (agora, tarefa["id"]),
                )


# Registra relacoes automaticas
def registrarRelacoesAutomaticas(conexao, conteudo, categoria, memoriaId, agora):
    entidades = {
        "iluminacao": ("luz", "luzes", "iluminacao", "lampada"),
        "sensores": ("sensor", "sensores", "presenca", "movimento"),
        "automacoes": ("automacao", "automacoes", "rotina"),
        "camera": ("camera", "cameras", "vigia"),
        "voz": ("voz", "microfone", "fala"),
        "servidor_local": ("servidor_local", "qwen", "modelo local"),
        "android": ("android", "celular", "aplicativo"),
    }
    texto = normalizarMemoria(conteudo)
    if categoria == "projeto" or "projeto" in texto:
        projeto = nomeProjetoMemoria(conteudo) or conteudo[:60]
        conexao.execute(
            "INSERT OR IGNORE INTO relacoesMemoria(origem, tipo, destino, memoriaId, criadaEm) VALUES ('JARVIS', 'projeto', ?, ?, ?)",
            (projeto, memoriaId, agora),
        )
        for entidade, variantes in entidades.items():
            if any(variante in texto for variante in variantes):
                conexao.execute(
                    "INSERT OR IGNORE INTO relacoesMemoria(origem, tipo, destino, memoriaId, criadaEm) VALUES (?, 'inclui', ?, ?, ?)",
                    (projeto, entidade, memoriaId, agora),
                )



def nomeProjetoMemoria(texto):
    achado = re.search(
        r"(?i)projeto\s+(.+?)(?:\s+(?:vai|que|para|com|inclui|envolve|controla|ajuda)\b|[,.;]|$)",
        texto,
    )
    return " ".join(achado.group(1).split()).strip()[:100] if achado else ""


# Busca memorias
def buscarMemorias(pergunta, limite=8, desde=None, ate=None, categoria=None):
    if not isinstance(pergunta, str) or not pergunta.strip():
        return []
    limite = max(1, min(int(limite), 30))
    termos = palavrasMemoria(pergunta)
    if not termos:
        return []
    with TRAVA, closing(conectar()) as conexao:
        linhas = conexao.execute(
            "SELECT * FROM memorias WHERE ativa = 1 AND (? IS NULL OR atualizadaEm >= ?) "
            "AND (? IS NULL OR atualizadaEm <= ?) AND (? IS NULL OR categoria = ?) "
            "ORDER BY atualizadaEm DESC LIMIT 1500",
            (desde, desde, ate, ate, categoria, categoria),
        ).fetchall()
    agora = datetime.now()
    pontuadas = []
    for linha in linhas:
        termosMemoria = palavrasMemoria(linha["conteudo"])
        intersecao = termos & termosMemoria
        if not intersecao:
            continue
        cobertura = len(intersecao) / max(1, len(termos))
        precisao = len(intersecao) / max(1, len(termosMemoria))
        lexical = 0.72 * cobertura + 0.28 * precisao
        try:
            idade = max(
                0.0,
                (agora - datetime.fromisoformat(linha["atualizadaEm"])).total_seconds(),
            )
        except (ValueError, TypeError):
            idade = 365 * 86400
        recencia = 1 / (1 + idade / (90 * 86400))
        score = lexical * 0.72 + linha["importancia"] * 0.18 + recencia * 0.10
        pontuadas.append((score, linha))
    pontuadas.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "id": linha["id"],
            "categoria": linha["categoria"],
            "conteudo": linha["conteudo"],
            "importancia": linha["importancia"],
            "confianca": linha["confianca"],
            "motivo": linha["motivo"],
            "criadaEm": linha["criadaEm"],
            "score": round(score, 3),
        }
        for score, linha in pontuadas[:limite]
    ]


# Consulta memorias recentes
def obterMemoriasRecentes(limite=8):
    limite = max(1, min(int(limite), 30))
    with TRAVA, closing(conectar()) as conexao:
        linhas = conexao.execute(
            "SELECT id, categoria, conteudo, importancia, confianca, motivo, criadaEm "
            "FROM memorias WHERE ativa = 1 ORDER BY atualizadaEm DESC LIMIT ?",
            (limite,),
        ).fetchall()
    return [dict(linha) for linha in linhas]


# Busca historico relacionado
def buscarHistoricoRelacionado(
    pergunta, limite=8, desde=None, ate=None, incluirEsquecidas=False
):
    if not isinstance(pergunta, str) or not pergunta.strip():
        return []
    limite = max(1, min(int(limite), 30))
    termos = sorted(palavrasMemoria(pergunta))[:12]
    if not termos:
        return []
    consulta = " OR ".join('"' + termo.replace('"', "") + '"' for termo in termos)
    try:
        with TRAVA, closing(conectar()) as conexao:
            linhas = conexao.execute(
                "SELECT m.id, m.papel, m.conteudo, m.criado_em, bm25(historicoBusca) AS peso "
                "FROM historicoBusca h JOIN mensagens m ON m.id = h.rowid "
                "WHERE historicoBusca MATCH ? AND (? IS NULL OR m.criado_em >= ?) "
                "AND (? IS NULL OR m.criado_em <= ?) "
                "AND (? = 1 OR m.id NOT IN (SELECT mensagemId FROM exclusoesMemoria)) "
                "ORDER BY peso LIMIT ?",
                (
                    consulta,
                    desde,
                    desde,
                    ate,
                    ate,
                    int(incluirEsquecidas),
                    min(limite * 5, 150),
                ),
            ).fetchall()
            esquecidas = (
                conexao.execute("SELECT termosHash FROM itensEsquecidos").fetchall()
                if not incluirEsquecidas
                else []
            )
        hashesEsquecidos = [set(linha["termosHash"].split("|")) for linha in esquecidas]
        resultado = []
        for linha in linhas:
            hashesMensagem = {
                hashlib.sha256(palavra.encode("utf-8")).hexdigest()
                for palavra in palavrasMemoria(linha["conteudo"])
            }
            if any(
                termosHash and termosHash.issubset(hashesMensagem)
                for termosHash in hashesEsquecidos
            ):
                continue
            resultado.append(
                {
                    "id": linha["id"],
                    "role": linha["papel"],
                    "content": linha["conteudo"],
                    "criadoEm": linha["criado_em"],
                }
            )
        return resultado[:limite]
    except sqlite3.Error:
        return []


# Consulta estado operacional
def obterEstadoOperacional(pergunta=""):
    with TRAVA, closing(conectar()) as conexao:
        estado = conexao.execute(
            "SELECT chave, valor, confianca, atualizadaEm FROM estadoOperacional ORDER BY atualizadaEm DESC LIMIT 30"
        ).fetchall()
        projetos = conexao.execute(
            "SELECT nome, estado, resumo, atualizadaEm FROM projetosMemoria ORDER BY atualizadaEm DESC LIMIT 20"
        ).fetchall()
        tarefas = conexao.execute(
            "SELECT p.nome AS projeto, t.titulo, t.estado FROM tarefasMemoria t LEFT JOIN projetosMemoria p ON p.id = t.projetoId ORDER BY t.atualizadaEm DESC LIMIT 30"
        ).fetchall()
        planos = conexao.execute(
            "SELECT id, objetivo, estado, atualizadaEm FROM planosMemoria ORDER BY atualizadaEm DESC LIMIT 10"
        ).fetchall()
        relacoes = conexao.execute(
            "SELECT origem, tipo, destino FROM relacoesMemoria ORDER BY criadaEm DESC LIMIT 40"
        ).fetchall()
    termos = palavrasMemoria(pergunta)
    if termos:
        relacoes = [
            item
            for item in relacoes
            if termos & palavrasMemoria(f"{item['origem']} {item['destino']}")
        ]
    return {
        "estado": [dict(item) for item in estado],
        "projetos": [dict(item) for item in projetos],
        "tarefas": [dict(item) for item in tarefas],
        "planos": [dict(item) for item in planos],
        "relacoes": [dict(item) for item in relacoes],
    }


# Salva plano
def salvarPlano(objetivo, etapas):
    if (
        not isinstance(objetivo, str)
        or not objetivo.strip()
        or not isinstance(etapas, (list, tuple))
    ):
        return None
    etapasValidas = [
        str(etapa).strip()[:500]
        for etapa in etapas
        if isinstance(etapa, str) and etapa.strip()
    ]
    if not etapasValidas:
        return None
    etapasValidas = etapasValidas[:12]
    agora = datetime.now().isoformat()
    with TRAVA, closing(conectar()) as conexao:
        cursor = conexao.execute(
            "INSERT INTO planosMemoria(objetivo, estado, criadaEm, atualizadaEm) VALUES (?, 'ativo', ?, ?)",
            (objetivo.strip()[:1000], agora, agora),
        )
        planoId = cursor.lastrowid
        conexao.executemany(
            "INSERT INTO etapasPlano(planoId, ordem, descricao, estado, atualizadaEm) VALUES (?, ?, ?, 'pendente', ?)",
            [
                (planoId, indice, etapa, agora)
                for indice, etapa in enumerate(etapasValidas, 1)
            ],
        )
        conexao.commit()
    return planoId


# Consulta planos
def obterPlanos(limite=5):
    limite = max(1, min(int(limite), 20))
    with TRAVA, closing(conectar()) as conexao:
        planos = conexao.execute(
            "SELECT id, objetivo, estado, criadaEm, atualizadaEm FROM planosMemoria ORDER BY atualizadaEm DESC LIMIT ?",
            (limite,),
        ).fetchall()
        resultado = []
        for plano in planos:
            etapas = conexao.execute(
                "SELECT ordem, descricao, estado FROM etapasPlano WHERE planoId = ? ORDER BY ordem",
                (plano["id"],),
            ).fetchall()
            resultado.append(
                {**dict(plano), "etapas": [dict(etapa) for etapa in etapas]}
            )
    return resultado



def concluirEtapaPlano(planoId, ordem):
    if (
        not isinstance(planoId, int)
        or not isinstance(ordem, int)
        or planoId < 1
        or ordem < 1
    ):
        return False
    agora = datetime.now().isoformat()
    with TRAVA, closing(conectar()) as conexao:
        cursor = conexao.execute(
            "UPDATE etapasPlano SET estado = 'concluida', atualizadaEm = ? WHERE planoId = ? AND ordem = ?",
            (agora, planoId, ordem),
        )
        if cursor.rowcount:
            pendentes = conexao.execute(
                "SELECT COUNT(*) FROM etapasPlano WHERE planoId = ? AND estado = 'pendente'",
                (planoId,),
            ).fetchone()[0]
            conexao.execute(
                "UPDATE planosMemoria SET estado = ?, atualizadaEm = ? WHERE id = ?",
                ("concluido" if not pendentes else "ativo", agora, planoId),
            )
        conexao.commit()
    return bool(cursor.rowcount)


# Registra relacao
def registrarRelacao(origem, tipo, destino, memoriaId=None):
    if not all(
        isinstance(valor, str) and valor.strip() for valor in (origem, tipo, destino)
    ):
        return False
    with TRAVA, closing(conectar()) as conexao:
        conexao.execute(
            "INSERT OR IGNORE INTO relacoesMemoria(origem, tipo, destino, memoriaId, criadaEm) VALUES (?, ?, ?, ?, ?)",
            (
                origem.strip()[:120],
                tipo.strip()[:80],
                destino.strip()[:120],
                memoriaId,
                datetime.now().isoformat(),
            ),
        )
        conexao.commit()
    return True



def esquecerMemoria(trecho):
    if not isinstance(trecho, str) or not trecho.strip():
        return 0
    termos = palavrasMemoria(trecho)
    with TRAVA, closing(conectar()) as conexao:
        linhas = conexao.execute(
            "SELECT id, conteudo FROM memorias WHERE ativa = 1"
        ).fetchall()
        ids = [
            linha["id"]
            for linha in linhas
            if termos
            and len(termos & palavrasMemoria(linha["conteudo"])) / max(1, len(termos))
            >= 0.65
        ]
        conteudos = [linha["conteudo"] for linha in linhas if linha["id"] in ids]
        projetos = {
            nomeProjetoMemoria(texto)
            for texto in conteudos
            if nomeProjetoMemoria(texto)
        }
        if ids:
            conexao.executemany(
                "DELETE FROM historicoMemoria WHERE memoriaId = ?",
                [(item,) for item in ids],
            )
            conexao.executemany(
                "DELETE FROM relacoesMemoria WHERE memoriaId = ?",
                [(item,) for item in ids],
            )
            conexao.executemany(
                "DELETE FROM memorias WHERE id = ?", [(item,) for item in ids]
            )
        fatos = conexao.execute("SELECT id, conteudo FROM fatos").fetchall()
        fatoIds = [
            item["id"]
            for item in fatos
            if termos
            and len(termos & palavrasMemoria(item["conteudo"])) / max(1, len(termos))
            >= 0.65
        ]
        conteudosFatos = [item["conteudo"] for item in fatos if item["id"] in fatoIds]
        if fatoIds:
            conexao.executemany(
                "DELETE FROM notas_hud WHERE fato_conteudo = ?",
                [(item,) for item in conteudosFatos],
            )
            conexao.executemany(
                "DELETE FROM fatos WHERE id = ?", [(item,) for item in fatoIds]
            )
        hashesApagar = sorted(
            hashlib.sha256(palavra.encode("utf-8")).hexdigest() for palavra in termos
        )
        termosHash = "|".join(hashesApagar)
        if termosHash:
            conexao.execute(
                "INSERT OR IGNORE INTO itensEsquecidos(termosHash, criadaEm) VALUES (?, ?)",
                (termosHash, datetime.now().isoformat()),
            )
        if projetos:
            marcadores = ",".join("?" for _ in projetos)
            linhasProjeto = conexao.execute(
                f"SELECT id FROM projetosMemoria WHERE nome IN ({marcadores})",
                tuple(projetos),
            ).fetchall()
            idsProjeto = [linha["id"] for linha in linhasProjeto]
            if idsProjeto:
                marcadoresProjeto = ",".join("?" for _ in idsProjeto)
                conexao.execute(
                    f"DELETE FROM tarefasMemoria WHERE projetoId IN ({marcadoresProjeto})",
                    tuple(idsProjeto),
                )
                conexao.execute(
                    f"DELETE FROM projetosMemoria WHERE id IN ({marcadoresProjeto})",
                    tuple(idsProjeto),
                )
                conexao.execute(
                    "DELETE FROM relacoesMemoria WHERE origem IN (%s) OR destino IN (%s)"
                    % (marcadores, marcadores),
                    tuple(projetos) + tuple(projetos),
                )
        planos = conexao.execute("SELECT id, objetivo FROM planosMemoria").fetchall()
        planoIds = [
            linha["id"]
            for linha in planos
            if termos
            and len(termos & palavrasMemoria(linha["objetivo"])) / max(1, len(termos))
            >= 0.65
        ]
        if planoIds:
            marcadoresPlanos = ",".join("?" for _ in planoIds)
            conexao.execute(
                f"DELETE FROM etapasPlano WHERE planoId IN ({marcadoresPlanos})",
                tuple(planoIds),
            )
            conexao.execute(
                f"DELETE FROM planosMemoria WHERE id IN ({marcadoresPlanos})",
                tuple(planoIds),
            )
        estados = conexao.execute(
            "SELECT chave, valor FROM estadoOperacional"
        ).fetchall()
        chavesEstado = [
            linha["chave"]
            for linha in estados
            if termos
            and len(termos & palavrasMemoria(linha["valor"])) / max(1, len(termos))
            >= 0.65
        ]
        if chavesEstado:
            conexao.executemany(
                "DELETE FROM estadoOperacional WHERE chave = ?",
                [(chave,) for chave in chavesEstado],
            )
        conexao.commit()
    return max(
        len(ids),
        len(fatoIds),
        len(planoIds),
        len(chavesEstado),
        len(idsProjeto) if projetos else 0,
    )


# Define ajuste memoria
def definirAjusteMemoria(chave, valor):
    if not isinstance(chave, str) or not isinstance(valor, str):
        return False
    with TRAVA, closing(conectar()) as conexao:
        conexao.execute(
            "INSERT INTO ajustesMemoria(chave, valor) VALUES (?, ?) ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
            (chave, valor),
        )
        conexao.commit()
    return True


# Consulta ajuste memoria
def obterAjusteMemoria(chave, padrao=""):
    with TRAVA, closing(conectar()) as conexao:
        linha = conexao.execute(
            "SELECT valor FROM ajustesMemoria WHERE chave = ?", (chave,)
        ).fetchone()
    return linha["valor"] if linha else padrao



def marcarMensagemSemMemoria(mensagemId):
    if (
        not isinstance(mensagemId, int)
        or isinstance(mensagemId, bool)
        or mensagemId <= 0
    ):
        return False
    with TRAVA, closing(conectar()) as conexao:
        conexao.execute(
            "INSERT OR IGNORE INTO exclusoesMemoria(mensagemId) VALUES (?)",
            (mensagemId,),
        )
        conexao.commit()
    return True


# Consulta historico para memoria
def obterHistoricoParaMemoria(limite=40):
    limite = max(2, min(int(limite), 200))
    with TRAVA, closing(conectar()) as conexao:
        linhas = conexao.execute(
            "SELECT id, papel, conteudo FROM mensagens WHERE id NOT IN (SELECT mensagemId FROM exclusoesMemoria) "
            "ORDER BY id DESC LIMIT ?",
            (limite,),
        ).fetchall()
    return [
        {"id": linha["id"], "role": linha["papel"], "content": linha["conteudo"]}
        for linha in reversed(linhas)
    ]



def exportarObsidian(pasta):
    from pathlib import Path

    raiz = Path(pasta).expanduser()
    raiz.mkdir(parents=True, exist_ok=True)
    with TRAVA, closing(conectar()) as conexao:
        memoriasAtivas = conexao.execute(
            "SELECT categoria, conteudo, confianca, atualizadaEm FROM memorias "
            "WHERE ativa = 1 ORDER BY categoria, atualizadaEm DESC LIMIT 2000"
        ).fetchall()
    estado = obterEstadoOperacional()
    (raiz / "Projetos").mkdir(exist_ok=True)
    (raiz / "Planos").mkdir(exist_ok=True)
    linhasMemoria = [
        "# Memorias",
        "",
        "Notas consolidadas. O historico bruto continua no banco local.",
        "",
    ]
    linhasMemoria.extend(
        f"- **{item['categoria']} | confianca {item['confianca']:.0%}**: {item['conteudo']} (atualizado {item['atualizadaEm'][:10]})"
        for item in memoriasAtivas
    )
    (raiz / "Memorias.md").write_text(
        "\n".join(linhasMemoria).strip() + "\n", encoding="utf-8"
    )
    linhasTarefas = ["# Tarefas", ""]
    linhasTarefas.extend(
        f"- [{'x' if item['estado'] == 'concluida' else ' '}] {item['titulo']} - {item['projeto'] or 'Sem projeto'}"
        for item in estado["tarefas"]
    )
    (raiz / "Tarefas.md").write_text(
        "\n".join(linhasTarefas).strip() + "\n", encoding="utf-8"
    )
    arquivos = ["- [[Memorias]]", "- [[Tarefas]]"]
    for projeto in estado["projetos"]:
        slug = (
            re.sub(r"[^a-z0-9-]+", "-", normalizarMemoria(projeto["nome"])).strip("-")[
                :60
            ]
            or "projeto"
        )
        destinoProjeto = raiz / "Projetos" / f"{slug}.md"
        destinoProjeto.write_text(
            f"# {projeto['nome']}\n\nEstado: {projeto['estado']}\n\n## Resumo\n\n{projeto['resumo']}\n",
            encoding="utf-8",
        )
        arquivos.append(f"- [[Projetos/{slug}|{projeto['nome']}]]")
    for plano in obterPlanos(20):
        slug = (
            re.sub(r"[^a-z0-9-]+", "-", normalizarMemoria(plano["objetivo"])).strip(
                "-"
            )[:60]
            or "plano"
        )
        destinoPlano = raiz / "Planos" / f"{plano['id']}-{slug}.md"
        linhasPlano = [
            f"# {plano['objetivo']}",
            "",
            f"Estado: {plano['estado']}",
            "",
            "## Etapas",
            "",
        ]
        linhasPlano.extend(
            f"- [{'x' if etapa['estado'] == 'concluida' else ' '}] {etapa['descricao']}"
            for etapa in plano["etapas"]
        )
        destinoPlano.write_text("\n".join(linhasPlano).strip() + "\n", encoding="utf-8")
        arquivos.append(f"- [[Planos/{plano['id']}-{slug}|{plano['objetivo']}]]")
    indice = raiz / "JARVIS.md"
    indice.write_text(
        "# Memoria do JARVIS\n\nGerado localmente. SQLite continua como fonte operacional.\n\n"
        + "\n".join(arquivos)
        + "\n",
        encoding="utf-8",
    )
    return str(indice)
