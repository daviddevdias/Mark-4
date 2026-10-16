"""Salva telas e opções dos widgets."""

import copy
import json
import threading
import config

WIDGETS = {
    "camera_live",
    "agenda",
    "system",
    "security",
    "detections",
    "clock",
    "weather",
    "email",
    "mobile",
}
TRAVA = threading.RLock()


# Monta telas iniciais editáveis
def padrao():
    return {
        "versao": 2,
        "revisao": 0,
        "telas": [],
        "principal": {"id": "principal", "nome": "Principal", "widgets": []},
    }


def limpar_legado(dados):
    dados.pop("impressora", None)
    for tela in list(dados.get("telas", [])) + [dados["principal"]]:
        if isinstance(tela, dict) and isinstance(tela.get("widgets"), list):
            tela["widgets"] = [
                w
                for w in tela["widgets"]
                if isinstance(w, dict) and w.get("tipo") in WIDGETS
            ]
            for w in tela["widgets"]:
                if type(w.get("w")) is int:
                    w["w"] = min(720, max(240, w["w"]))
                if type(w.get("h")) is int:
                    w["h"] = min(560, max(140, w["h"]))


# Consulta arquivo privado das telas
def carregar():
    with TRAVA:
        try:
            dados = json.loads(
                (config.DATA_DIR / "telas_widgets.json").read_text(encoding="utf-8")
            )
            if not isinstance(dados, dict):
                return padrao()
            dados.setdefault(
                "principal", {"id": "principal", "nome": "Principal", "widgets": []}
            )
            limpar_legado(dados)
            if dados.get("versao") != 2:
                for tela in dados.get("telas", []):
                    for i, w in enumerate(tela["widgets"]):
                        w.update(
                            x=24 + (i % 3) * 380, y=24 + (i // 3) * 300, w=350, h=270
                        )
                dados["versao"] = 2
            validar_telas(dados)
            return dados
        except (OSError, ValueError, TypeError, KeyError):
            return padrao()


def publico():
    dados = carregar()
    return dados


# Confere widgets e nomes das telas
def validar_telas(dados):
    telas = dados.get("telas")
    if not isinstance(telas, list) or not 0 <= len(telas) <= 8:
        raise ValueError("Use até oito telas")
    ids = set()
    if any(t.get("id") == "principal" for t in telas if isinstance(t, dict)):
        raise ValueError("Identificador reservado")
    for tela in telas + [
        dados.get("principal", {"id": "principal", "nome": "Principal", "widgets": []})
    ]:
        if not isinstance(tela, dict):
            raise ValueError("Tela inválida")
        ident = tela.get("id")
        if (
            not isinstance(ident, str)
            or not 1 <= len(ident) <= 32
            or not ident.isascii()
            or not ident.replace("-", "").isalnum()
            or ident in ids
        ):
            raise ValueError("Identificador inválido")
        ids.add(ident)
        if (
            not isinstance(tela.get("nome"), str)
            or not 1 <= len(tela["nome"].strip()) <= 40
        ):
            raise ValueError("Nome inválido")
        if tela.get("tema", "classico") not in {"classico", "holografico"}:
            raise ValueError("Tema inválido")
        widgets = tela.get("widgets")
        if not isinstance(widgets, list) or len(widgets) > len(WIDGETS):
            raise ValueError("Lista de widgets inválida")
        vistos = set()
        for widget in widgets:
            if (
                not isinstance(widget, dict)
                or widget.get("tipo") not in WIDGETS
                or widget["tipo"] in vistos
            ):
                raise ValueError("Widget inválido")
            for campo, minimo, maximo in [
                ("x", 0, 8192),
                ("y", 0, 8192),
                ("w", 240, 720),
                ("h", 140, 560),
            ]:
                valor = widget.get(campo)
                if type(valor) is not int or not minimo <= valor <= maximo:
                    raise ValueError("Dimensão inválida")
            vistos.add(widget["tipo"])


# Persiste layout sem perder edições
def salvar(dados):
    if not isinstance(dados, dict):
        raise ValueError("Envie um objeto JSON")
    validar_telas(dados)
    with TRAVA:
        antigo = carregar()
        if (
            type(dados.get("revisao")) is not int
            or dados["revisao"] != antigo["revisao"]
        ):
            raise RuntimeError("As telas mudaram. Reabra a personalização")
        novo = {
            "versao": 2,
            "revisao": antigo["revisao"] + 1,
            "telas": [
                {
                    "id": t["id"],
                    "nome": t["nome"].strip(),
                    "tema": t.get("tema", "classico"),
                    "widgets": [
                        {k: w[k] for k in ("tipo", "x", "y", "w", "h")}
                        for w in t["widgets"]
                    ],
                }
                for t in dados["telas"]
            ],
        }
        novo["ultima_tela"] = dados.get("ultima_tela", antigo.get("ultima_tela"))
        novo["principal"] = copy.deepcopy(dados.get("principal", antigo["principal"]))
        novo["principal"]["widgets"] = [
            {k: w[k] for k in ("tipo", "x", "y", "w", "h")}
            for w in novo["principal"]["widgets"]
        ]
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        destino = config.DATA_DIR / "telas_widgets.json"
        temporario = destino.with_suffix(".tmp")
        temporario.write_text(json.dumps(novo, ensure_ascii=False), encoding="utf-8")
        temporario.replace(destino)
        return publico()


# Altera somente a peça solicitada
def alterar(dados):
    import uuid

    if not isinstance(dados, dict):
        raise ValueError("Pedido inválido")
    with TRAVA:
        perfil = carregar()
        acao = dados.get("acao")
        if acao == "criar":
            if perfil["telas"]:
                ident = perfil.get("ultima_tela")
                if not any(t["id"] == ident for t in perfil["telas"]):
                    ident = next(
                        (t["id"] for t in reversed(perfil["telas"]) if t["widgets"]),
                        perfil["telas"][-1]["id"],
                    )
                return {"perfil": perfil, "id": ident}
            ident = "tela-" + uuid.uuid4().hex[:12]
            perfil["telas"].append(
                {"id": ident, "nome": "Segunda tela", "tema": "classico", "widgets": []}
            )
        else:
            ident = dados.get("id")
            tela = (
                perfil["principal"]
                if ident == "principal"
                else next((t for t in perfil["telas"] if t["id"] == ident), None)
            )
            if ident == "principal" and acao not in {"peca", "retirar", "layout"}:
                raise ValueError("A tela principal é fixa")
            if tela is None:
                raise ValueError("Tela inexistente")
            if ident != "principal" and acao != "remover":
                perfil["ultima_tela"] = ident
            if acao == "remover":
                perfil["telas"].remove(tela)
            elif acao == "nome":
                tela["nome"] = dados.get("nome")
            elif acao == "layout":
                if dados.get("revisao") != perfil["revisao"]:
                    raise RuntimeError(
                        "O layout mudou em outra janela. Atualize antes de desfazer."
                    )
                tela["widgets"] = dados.get("widgets")
            elif acao == "peca":
                widget = dados.get("widget")
                if not isinstance(widget, dict):
                    raise ValueError("Peça inválida")
                tela["widgets"] = [
                    w for w in tela["widgets"] if w["tipo"] != widget.get("tipo")
                ] + [widget]
            elif acao == "retirar":
                tela["widgets"] = [
                    w for w in tela["widgets"] if w["tipo"] != dados.get("tipo")
                ]
            else:
                raise ValueError("Ação inválida")
        salvo = salvar(perfil)
        return {"perfil": salvo, "id": ident}
