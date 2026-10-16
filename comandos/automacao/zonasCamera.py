import json
import logging
import math
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import config

log = logging.getLogger("mark2.zonasCamera")
ARQUIVO = config.DATA_DIR / "zonasCamera.json"
TEMPO_ESTADO_VENCIDO_S = 4.5
_ultimoErroLeitura = None
TRAVA = threading.RLock()
ESTADOS = {}
CALLBACK_EVENTO = None


# Define retorno evento
def definirCallbackEvento(callback):
    global CALLBACK_EVENTO
    CALLBACK_EVENTO = callback


# Normaliza ponto
def normalizarPonto(ponto):
    if not isinstance(ponto, (list, tuple)) or len(ponto) != 2:
        raise ValueError("Cada ponto precisa ter coordenadas x e y.")
    try:
        x, y = float(ponto[0]), float(ponto[1])
    except (TypeError, ValueError, OverflowError):
        raise ValueError("As coordenadas da zona precisam ser numéricas.")
    if not math.isfinite(x) or not math.isfinite(y) or not 0 <= x <= 1 or not 0 <= y <= 1:
        raise ValueError("As coordenadas precisam estar entre 0 e 1.")
    return [round(x, 5), round(y, 5)]



def areaPoligono(pontos):
    total = 0.0
    for indice, ponto in enumerate(pontos):
        proximo = pontos[(indice + 1) % len(pontos)]
        total += ponto[0] * proximo[1] - proximo[0] * ponto[1]
    return abs(total) / 2


# Normaliza zona
def normalizarZona(zona):
    if not isinstance(zona, dict):
        raise ValueError("Cada zona precisa ser um objeto.")
    nome = str(zona.get("name", "")).strip()[:48]
    if not nome:
        raise ValueError("Informe um nome para cada zona.")
    pontos = zona.get("points")
    if not isinstance(pontos, list) or not 3 <= len(pontos) <= 32:
        raise ValueError("Desenhe uma zona com 3 a 32 pontos.")
    pontos = [normalizarPonto(ponto) for ponto in pontos]
    if areaPoligono(pontos) < 0.0005:
        raise ValueError("A zona desenhada é pequena demais.")
    cor = str(zona.get("color", "#69c9ff"))
    if len(cor) != 7 or cor[0] != "#":
        raise ValueError("A cor da zona é inválida.")
    try:
        int(cor[1:], 16)
    except ValueError:
        raise ValueError("A cor da zona é inválida.")
    try:
        permanencia = int(zona.get("dwellSeconds", 20))
    except (TypeError, ValueError, OverflowError):
        permanencia = 20
    permanencia = min(3600, max(1, permanencia))
    identificador = str(zona.get("id") or uuid.uuid4().hex)
    if not identificador.isascii() or not identificador.replace("-", "").isalnum() or len(identificador) > 48:
        raise ValueError("Identificador da zona inválido.")
    ativa = zona.get("active", True)
    if not isinstance(ativa, bool):
        raise ValueError("Estado ativo da zona deve ser verdadeiro ou falso.")
    dias = zona.get("activeDays", list(range(7)))
    if not isinstance(dias, list) or any(type(dia) is not int or dia < 0 or dia > 6 for dia in dias):
        raise ValueError("Os dias ativos precisam ser números de 0 a 6.")
    dias = sorted(set(dias))
    inicio = str(zona.get("activeStart", "00:00"))
    fim = str(zona.get("activeEnd", "23:59"))
    for horario in (inicio, fim):
        try:
            datetime.strptime(horario, "%H:%M")
        except ValueError:
            raise ValueError("Os horários ativos precisam usar HH:MM.")
    try:
        intervalo = int(zona.get("cooldownSeconds", 5))
    except (TypeError, ValueError, OverflowError):
        raise ValueError("Intervalo inv\u00e1lido.")
    intervalo = min(3600, max(0, intervalo))
    tipos = zona.get("eventTypes", ["entry", "dwell", "exit"])
    permitidos = {"entry", "dwell", "exit"}
    if not isinstance(tipos, list) or any(tipo not in permitidos for tipo in tipos):
        raise ValueError("Tipos de evento da zona inválidos.")
    return {
        "id": identificador,
        "name": nome,
        "color": cor.lower(),
        "active": ativa,
        "points": pontos,
        "dwellSeconds": permanencia,
        "activeDays": dias,
        "activeStart": inicio,
        "activeEnd": fim,
        "cooldownSeconds": intervalo,
        "eventTypes": sorted(set(tipos)),
    }


# Valida zonas
def validarZonas(dados):
    if not isinstance(dados, list) or len(dados) > 24:
        raise ValueError("Envie no máximo 24 zonas.")
    zonas = [normalizarZona(zona) for zona in dados]
    ids = [zona["id"] for zona in zonas]
    if len(ids) != len(set(ids)):
        raise ValueError("Cada zona precisa ter um identificador único.")
    return zonas



def _falhaLeitura(mensagem):
    # Registra uma vez por erro: uma zona
    global _ultimoErroLeitura
    if mensagem != _ultimoErroLeitura:
        _ultimoErroLeitura = mensagem
        log.error("Zonas desativadas: %s", mensagem)
    return []


# Lista zonas
def listarZonas():
    with TRAVA:
        try:
            dados = json.loads(ARQUIVO.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, UnicodeError, json.JSONDecodeError) as erro:
            return _falhaLeitura(f"não consegui ler {ARQUIVO.name}: {erro}")
        try:
            zonas = validarZonas(dados)
        except ValueError as erro:
            return _falhaLeitura(f"zona inválida em {ARQUIVO.name}: {erro}")
        global _ultimoErroLeitura
        _ultimoErroLeitura = None
        return zonas


# Salva zonas
def salvarZonas(dados):
    zonas = validarZonas(dados)
    ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    temporario = None
    with TRAVA:
        try:
            fd, temporario = tempfile.mkstemp(prefix="zonas-", suffix=".tmp", dir=ARQUIVO.parent)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as arquivo:
                json.dump(zonas, arquivo, ensure_ascii=False, separators=(",", ":"))
                arquivo.flush()
                os.fsync(arquivo.fileno())
            os.replace(temporario, ARQUIVO)
            ESTADOS.clear()
            return zonas
        except OSError:
            if temporario:
                try:
                    os.unlink(temporario)
                except OSError:
                    pass
            raise



def pontoDentro(ponto, vertices):
    x, y = ponto
    dentro = False
    anterior = len(vertices) - 1
    for indice, atual in enumerate(vertices):
        ax, ay = atual
        bx, by = vertices[anterior]
        cruza = (ay > y) != (by > y)
        if cruza and x < (bx - ax) * (y - ay) / ((by - ay) or 1e-12) + ax:
            dentro = not dentro
        anterior = indice
    return dentro



def agendaAtiva(zona, momento):
    dia = momento.weekday()
    if dia not in zona["activeDays"]:
        if zona["activeStart"] <= zona["activeEnd"]:
            return False
        diaAnterior = (dia - 1) % 7
        if momento.strftime("%H:%M") > zona["activeEnd"] or diaAnterior not in zona["activeDays"]:
            return False
    horario = momento.strftime("%H:%M")
    inicio = zona["activeStart"]
    fim = zona["activeEnd"]
    if inicio <= fim:
        return dia in zona["activeDays"] and inicio <= horario <= fim
    return (dia in zona["activeDays"] and horario >= inicio) or ((dia - 1) % 7 in zona["activeDays"] and horario <= fim)



def avaliarZonas(caixas, largura, altura, agora=None):
    if largura <= 0 or altura <= 0:
        return []
    instante = time.monotonic() if agora is None else float(agora)
    momento = datetime.now()
    zonas = listarZonas()
    ativos = {zona["id"]: zona for zona in zonas if zona["active"]}
    pontos = [((caixa[0] + caixa[2]) / (2 * largura), caixa[3] / altura) for caixa in caixas]
    eventos = []
    with TRAVA:
        for identificador in list(ESTADOS):
            if identificador not in ativos:
                del ESTADOS[identificador]
        for identificador, zona in ativos.items():
            contagem = sum(pontoDentro(ponto, zona["points"]) for ponto in pontos)
            estado = ESTADOS.setdefault(identificador, {"present": False, "since": 0.0, "dwellSent": False, "candidateCount": 0, "lastSeen": 0.0, "missingCount": 0, "lastAlert": 0.0})
            evento = None
            if estado["present"] and instante - estado["lastSeen"] > TEMPO_ESTADO_VENCIDO_S:
                # Ocupação sem atualização recente
                estado.update(present=False, dwellSent=False, candidateCount=0, missingCount=0)
            if contagem:
                if instante - estado["lastSeen"] > 4.5:
                    estado["candidateCount"] = 0
                estado["candidateCount"] += 1
                estado["lastSeen"] = instante
                estado["missingCount"] = 0
            else:
                estado["candidateCount"] = 0
                estado["missingCount"] += 1
            confirmado = estado["candidateCount"] >= max(3, int(getattr(config, "VIGIA_CONSECUTIVAS", 3)))
            if contagem and confirmado and not estado["present"]:
                estado.update(present=True, since=instante, dwellSent=False)
                evento = {"event": "entry", "persons": contagem}
            elif contagem and estado["present"] and not estado["dwellSent"] and instante - estado["since"] >= zona["dwellSeconds"]:
                estado["dwellSent"] = True
                evento = {"event": "dwell", "persons": contagem, "duration": int(instante - estado["since"])}
            elif not contagem and estado["present"] and estado["missingCount"] >= 2:
                estado.update(present=False, dwellSent=False)
                evento = {"event": "exit", "persons": 0, "duration": int(instante - estado["since"])}
            if evento:
                intervalo = zona["cooldownSeconds"]
                alertaLiberado = agendaAtiva(zona, momento) and evento["event"] in zona["eventTypes"] and not (estado["lastAlert"] > 0 and instante - estado["lastAlert"] < intervalo)
                if alertaLiberado:
                    estado["lastAlert"] = instante
                eventos.append({**evento, "zoneId": identificador, "zoneName": zona["name"], "color": zona["color"], "alertAllowed": alertaLiberado})
    callback = CALLBACK_EVENTO
    if callback:
        for evento in eventos:
            try:
                callback(evento)
            except Exception:
                # Uma notificação do painel não pode
                pass
    return eventos



def estadoOcupacao(agora=None):
    
    instante = time.monotonic() if agora is None else float(agora)
    momento = datetime.now()
    zonas = {zona["id"]: zona for zona in listarZonas() if zona["active"]}
    saida = []
    with TRAVA:
        for identificador, estado in ESTADOS.items():
            zona = zonas.get(identificador)
            if (
                not zona
                or not estado.get("present")
                or instante - float(estado.get("lastSeen", 0.0)) > 4.5
                or not agendaAtiva(zona, momento)
                or "dwell" not in zona["eventTypes"]
            ):
                continue
            idade = max(0.0, instante - float(estado.get("since", instante)))
            saida.append({
                "zoneId": identificador,
                "zoneName": zona["name"],
                "duration": idade,
                "persons": 1,
                "color": zona["color"],
            })
    return saida