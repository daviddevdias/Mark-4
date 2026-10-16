"""Protege arquivos privados locais."""

import base64
import ctypes
import json
import os
import secrets
from pathlib import Path
import config


# Limita gravações à pasta data
def local(path):
    path = Path(path).resolve()
    if not path.is_relative_to(config.DATA_DIR.resolve()):
        raise ValueError("Arquivo fora da pasta privada")
    return path


# Cifra com a conta do Windows
def dpapi(data, abrir=False):
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    entrada = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    saida = Blob()
    if abrir:
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(entrada), None, None, None, None, 1, ctypes.byref(saida)
        )
    else:
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(entrada),
            ctypes.c_wchar_p("Jarvis Mark 2"),
            None,
            None,
            None,
            1,
            ctypes.byref(saida),
        )
    if not ok:
        raise OSError("Falha na proteção do Windows")
    try:
        return ctypes.string_at(saida.data, saida.size)
    finally:
        liberar = ctypes.windll.kernel32.LocalFree
        liberar.argtypes = [ctypes.c_void_p]
        liberar(ctypes.cast(saida.data, ctypes.c_void_p))


# Persiste JSON protegido e atômico
def gravar(path, dados):
    path = local(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(dados, ensure_ascii=False).encode("utf-8")
    if os.name == "nt":
        raw = json.dumps(
            {
                "protecao": "dpapi1",
                "conteudo": base64.b64encode(dpapi(raw)).decode("ascii"),
            }
        ).encode("utf-8")
    temp = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
    try:
        temp.write_bytes(raw)
        temp.chmod(0o600)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


# Migra segredos sem copiar arquivos
def ler(path):
    path = local(path)
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Formato privado inválido")
    if value.get("protecao") == "dpapi1":
        if os.name != "nt":
            raise OSError("Arquivo pertence ao Windows")
        return json.loads(
            dpapi(
                base64.b64decode(value["conteudo"], validate=True), abrir=True
            ).decode("utf-8")
        )
    if os.name == "nt":
        gravar(path, value)
    return value
