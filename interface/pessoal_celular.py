"""Recebe mensagens pessoais."""
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
import config

# Abre a conexão local
def conectar():
    conexao = sqlite3.connect(config.DATA_DIR / "mensagens_celular.db", timeout=5)
    conexao.row_factory = sqlite3.Row
    conexao.execute("CREATE TABLE IF NOT EXISTS mensagens (id TEXT PRIMARY KEY, remetente TEXT NOT NULL, texto TEXT NOT NULL, hora TEXT NOT NULL)")
    return conexao


def salvar(dados):
    if not isinstance(dados, dict) or not isinstance(dados.get("pacote"), str) or dados["pacote"] not in {"com.whatsapp", "com.whatsapp.w4b"}:
        raise ValueError("Aplicativo não permitido")
    if not all(isinstance(dados.get(campo), str) for campo in ("remetente", "texto", "id")):
        raise ValueError("Campos da mensagem devem ser textos")
    remetente = dados["remetente"].strip()[:120]
    texto = dados["texto"].strip()[:2000]
    origem = dados["id"].strip()[:300]
    if not remetente or not texto or not origem:
        raise ValueError("Mensagem incompleta")
    identificador = hashlib.sha256(json.dumps([origem, remetente, texto], ensure_ascii=False).encode()).hexdigest()
    hora = datetime.now(timezone.utc).isoformat()
    with closing(conectar()) as conexao, conexao:
        cursor = conexao.execute("INSERT OR IGNORE INTO mensagens VALUES (?, ?, ?, ?)", (identificador, remetente, texto, hora))
        nova = cursor.rowcount > 0
        conexao.execute("DELETE FROM mensagens WHERE id NOT IN (SELECT id FROM mensagens ORDER BY hora DESC LIMIT 100)")
    return nova, {"id": identificador, "remetente": remetente, "texto": texto, "hora": hora}


def listar():
    with closing(conectar()) as conexao:
        return [dict(item) for item in conexao.execute("SELECT * FROM mensagens ORDER BY hora DESC LIMIT 30")]
