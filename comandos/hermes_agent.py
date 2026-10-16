import json
import os
import subprocess
import time
import config
from comandos import llm_local

# Consulta permissao do agente
def ativo():
    return config.obter_bool("hermes_ativo", True)

# Alterna agente sem fechar LM
def definir_ativo(valor):
    if not isinstance(valor, bool): return False
    salvo = config.persistir_valor("hermes_ativo", valor)
    if salvo and not valor: llm_local.cancelar_tudo()
    return salvo

# Coordena conversa local
def conversar(mensagens, max_tokens=1024):
    python = config.BASE_DIR / ".tools" / "hermes-env" / "Scripts" / "python.exe"
    runner = config.BASE_DIR / "tools" / "hermes_runner.py"
    if not ativo() or not llm_local.servidor_local_ativo() or not python.is_file() or not llm_local.disponivel():
        return None
    ambiente = {k: v for k, v in os.environ.items()
        if not any(x in k.upper() for x in ("API_KEY", "ACCESS_TOKEN", "SECRET"))}
    ambiente.update(HERMES_HOME=str(config.DATA_DIR / "hermes"), PYTHONUTF8="1")
    pedido = {"mensagens": mensagens, "max_tokens": max_tokens,
        "url": llm_local.URL_BASE, "modelo": llm_local.resolver_modelo()}
    atividade = llm_local.iniciar_atividade(llm_local.MODELO)
    cancelar = llm_local.obter_evento_cancelar(atividade)
    sucesso = False
    processo = None
    try:
        with llm_local.SEMAFORO_CHAMADAS:
            if cancelar.is_set():
                return None
            processo = subprocess.Popen([str(python), str(runner)], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                env=ambiente, cwd=str(config.BASE_DIR),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            limite = time.monotonic() + 135
            entrada = json.dumps(pedido)
            while True:
                if cancelar.is_set() or time.monotonic() >= limite:
                    processo.kill()
                    processo.communicate()
                    return None
                try:
                    saida, _ = processo.communicate(input=entrada, timeout=0.25)
                    break
                except subprocess.TimeoutExpired:
                    entrada = None
            sucesso = processo.returncode == 0
    except (OSError, ValueError):
        return None
    finally:
        if processo and processo.poll() is None:
            processo.kill()
            processo.communicate()
        llm_local.finalizar_atividade(atividade, sucesso)
    for linha in reversed(saida.splitlines()):
        if linha.startswith("MARK2_RESULT="):
            return llm_local.limpar_resposta(json.loads(linha[13:]).get("resposta", ""))
    return None
