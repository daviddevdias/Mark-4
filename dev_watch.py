from __future__ import annotations

import os
import py_compile
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INTERVALO_S = 0.75
ESTABILIDADE_S = 1.0
EXCLUIR = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    "data",
    "build",
    "dist",
    "Android",
    "logs",
    "sessao_whatsapp",
}
EXTENSOES_PYTHON = {".py"}
EXTENSOES_INTERFACE = {".html", ".css", ".js", ".mjs"}


def arquivos_monitorados() -> dict[Path, tuple[int, int]]:
    resultado: dict[Path, tuple[int, int]] = {}
    for raiz, pastas, nomes in os.walk(ROOT):
        pastas[:] = [
            pasta
            for pasta in pastas
            if pasta not in EXCLUIR and not pasta.startswith(".")
        ]
        diretorio = Path(raiz)
        for nome in nomes:
            caminho = diretorio / nome
            if caminho.suffix.lower() not in EXTENSOES_PYTHON | EXTENSOES_INTERFACE:
                continue
            try:
                info = caminho.stat()
                resultado[caminho] = (info.st_mtime_ns, info.st_size)
            except OSError:
                continue
    return resultado


def arquivos_alterados(
    antes: dict[Path, tuple[int, int]], depois: dict[Path, tuple[int, int]]
) -> set[Path]:
    return {
        caminho
        for caminho in antes.keys() | depois.keys()
        if antes.get(caminho) != depois.get(caminho)
    }


# Grava marcador
def gravar_marcador(caminho: Path, conteudo: str) -> None:
    temporario = caminho.with_name(caminho.name + ".tmp")
    temporario.write_text(conteudo, encoding="ascii")
    os.replace(temporario, caminho)


# Inicia Jarvis
def iniciar_jarvis(ambiente: dict[str, str]) -> subprocess.Popen:
    opcoes = {"cwd": ROOT, "env": ambiente}
    if os.name == "nt":
        opcoes["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen([sys.executable, "-u", "main.py"], **opcoes)


def compilar_alterados(arquivos: set[Path]) -> bool:
    validos = True
    for caminho in sorted(arquivos):
        if caminho.suffix.lower() not in EXTENSOES_PYTHON:
            continue
        if not caminho.is_file():
            continue
        try:
            py_compile.compile(str(caminho), doraise=True)
            try:
                exibicao = caminho.relative_to(ROOT)
            except ValueError:
                exibicao = caminho
            print(f"[Auto Restart] Sintaxe v\u00e1lida: {exibicao}", flush=True)
        except (OSError, py_compile.PyCompileError):
            validos = False
            traceback.print_exc()
    return validos


# Inicia o aplicativo Jarvis
def main() -> int:
    identificador = uuid.uuid4().hex
    temporario = Path(tempfile.gettempdir())
    pedido = temporario / f"jarvis-mark2-reload-{identificador}.request"
    versao_assets = temporario / f"jarvis-mark2-assets-{identificador}.token"
    gravar_marcador(versao_assets, str(time.time_ns()))
    ambiente = os.environ.copy()
    ambiente.update(
        {
            "JARVIS_DEV_RELOAD": "1",
            "JARVIS_DEV_RELOAD_REQUEST": str(pedido),
            "JARVIS_DEV_ASSET_TOKEN_FILE": str(versao_assets),
        }
    )
    print(
        "Modo desenvolvimento ativo: Live Reload da interface e Auto Restart controlado do Python.",
        flush=True,
    )
    print(
        "Hot Reload de m\u00f3dulos Python n\u00e3o \u00e9 usado: c\u00e2mera, YOLO e threads mant\u00eam estado e conex\u00f5es em execu\u00e7\u00e3o.",
        flush=True,
    )
    print(
        "Para produ\u00e7\u00e3o, inicie com python main.py. Este monitor \u00e9 opt-in.",
        flush=True,
    )
    processo = iniciar_jarvis(ambiente)
    estado_anterior = arquivos_monitorados()
    alterados_pendentes: set[Path] = set()
    instante_alteracao = 0.0
    reinicio_solicitado = False
    try:
        while True:
            codigo = processo.poll()
            if codigo is not None:
                if reinicio_solicitado:
                    print(
                        "[Auto Restart] Encerramento seguro conclu\u00eddo; iniciando o Jarvis novamente.",
                        flush=True,
                    )
                    processo = iniciar_jarvis(ambiente)
                    reinicio_solicitado = False
                    continue
                print(
                    f"Jarvis encerrou com c\u00f3digo {codigo}; monitor encerrado para evitar rein\u00edcio em la\u00e7o.",
                    flush=True,
                )
                return codigo
            atual = arquivos_monitorados()
            mudancas = arquivos_alterados(estado_anterior, atual)
            if mudancas:
                estado_anterior = atual
                alterados_pendentes.update(mudancas)
                instante_alteracao = time.monotonic()
            elif (
                alterados_pendentes
                and time.monotonic() - instante_alteracao >= ESTABILIDADE_S
            ):
                pendentes = set(alterados_pendentes)
                alterados_pendentes.clear()
                arquivos_ui = [
                    p for p in pendentes if p.suffix.lower() in EXTENSOES_INTERFACE
                ]
                if arquivos_ui:
                    gravar_marcador(versao_assets, str(time.time_ns()))
                    print(
                        "[Live Reload] Interface atualizada; o navegador local vai recarregar a p\u00e1gina.",
                        flush=True,
                    )
                alteracoes_python = {
                    p for p in pendentes if p.suffix.lower() in EXTENSOES_PYTHON
                }
                if alteracoes_python:
                    if compilar_alterados(alteracoes_python):
                        gravar_marcador(pedido, "restart")
                        reinicio_solicitado = True
                        print(
                            "[Auto Restart] Aguardando encerramento limpo de c\u00e2mera, PTZ e servidores.",
                            flush=True,
                        )
                    else:
                        print(
                            "[Auto Restart] Sintaxe inv\u00e1lida; o processo atual continua e novas altera\u00e7\u00f5es ser\u00e3o monitoradas.",
                            flush=True,
                        )
            time.sleep(INTERVALO_S)
    except KeyboardInterrupt:
        if processo.poll() is None:
            gravar_marcador(pedido, "stop")
            print(
                "Pedido de encerramento enviado; aguardando a c\u00e2mera e os servidores fecharem.",
                flush=True,
            )
            while processo.poll() is None:
                time.sleep(0.25)
        return 0
    finally:
        pedido.unlink(missing_ok=True)
        versao_assets.unlink(missing_ok=True)
        versao_assets.with_name(versao_assets.name + ".tmp").unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
