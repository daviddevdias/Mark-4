
import json
import logging
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

import config

log = logging.getLogger("mark2.smartthings_auth")

TOKEN_URL = "https://api.smartthings.com/oauth/token"
AUTHORIZE_URL = "https://api.smartthings.com/oauth/authorize"
REDIRECT_PADRAO = "https://httpbin.org/get"
ESCOPOS = "r:devices:* w:devices:* x:devices:*"
MARGEM_SEGUNDOS = 300  


ARQUIVO_TOKENS = Path(config.DATA_DIR) / "smartthings_oauth.json"

_lock = threading.RLock()



# Consulta opção de configuração
def _cfg(nome, padrao=""):
    
    valor = os.environ.get(nome.upper())
    if not valor:
        valor = config.carregar_configuracoes().get(nome.lower())
    return valor.strip() if isinstance(valor, str) and valor.strip() else padrao




def _ler_tokens():
    try:
        dados = json.loads(ARQUIVO_TOKENS.read_text(encoding="utf-8"))
        return dados if isinstance(dados, dict) else {}
    except (OSError, ValueError):
        return {}




def _salvar_tokens(dados):
    temporario = ARQUIVO_TOKENS.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, indent=2), encoding="utf-8")
    try:
        os.chmod(temporario, 0o600)
    except OSError:
        pass
    os.replace(temporario, ARQUIVO_TOKENS)  




def _chamar_endpoint_token(dados_form):
    client_id = _cfg("smartthings_client_id")
    client_secret = _cfg("smartthings_client_secret")
    if not client_id or not client_secret:
        raise RuntimeError(
            "Defina smartthings_client_id e smartthings_client_secret "
            "no config_mark2.json."
        )
    resposta = requests.post(
        TOKEN_URL,
        auth=(client_id, client_secret),
        data={"client_id": client_id, **dados_form},
        headers={"Accept": "application/json"},
        timeout=15,
    )
    if resposta.status_code >= 400:
        raise RuntimeError(f"HTTP {resposta.status_code}: {resposta.text[:300]}")
    return resposta.json()




def _guardar_resposta(resposta, tokens_antigos=None):
    antigos = tokens_antigos or {}
    novo = {
        "access_token": resposta["access_token"],

        "refresh_token": resposta.get("refresh_token") or antigos.get("refresh_token"),
        "expires_at": time.time() + int(resposta.get("expires_in", 86399)),
    }
    _salvar_tokens(novo)
    return novo




def renovar_token():
    
    with _lock:
        tokens = _ler_tokens()
        refresh = tokens.get("refresh_token")
        if not refresh:
            log.error("Sem refresh token salvo. Rode: python smartthings_auth.py setup")
            return None
        try:
            resposta = _chamar_endpoint_token(
                {"grant_type": "refresh_token", "refresh_token": refresh}
            )
            novo = _guardar_resposta(resposta, tokens)
            log.info("Token do SmartThings renovado.")
            return novo["access_token"]
        except (RuntimeError, requests.RequestException, KeyError, ValueError) as erro:
            log.error(
                "Falha ao renovar o token do SmartThings (%s). Se persistir, "
                "rode novamente: python smartthings_auth.py setup",
                erro,
            )
            return None




def oauth_configurado():
    return bool(_ler_tokens().get("refresh_token"))




def obter_token_valido(forcar=False):
    
    with _lock:
        tokens = _ler_tokens()
        if not tokens.get("refresh_token"):
            return config.obter_smartthings_token()

        ainda_vale = tokens.get("expires_at", 0) - MARGEM_SEGUNDOS > time.time()
        if ainda_vale and not forcar:
            return tokens["access_token"]
        return renovar_token() or (tokens["access_token"] if ainda_vale else None)




def trocar_codigo(codigo):
    
    codigo = str(codigo or "").strip()
    if not codigo:
        return False
    redirect = _cfg("smartthings_redirect_uri", REDIRECT_PADRAO)
    try:
        with _lock:
            resposta = _chamar_endpoint_token(
                {
                    "grant_type": "authorization_code",
                    "code": codigo,
                    "redirect_uri": redirect,
                }
            )
            _guardar_resposta(resposta)
        log.info("Autorização OAuth do SmartThings concluída.")
        return True
    except (RuntimeError, requests.RequestException, KeyError, ValueError) as erro:
        log.error("Falha ao trocar o code do SmartThings: %s", erro)
        return False




def montar_url_autorizacao():
    client_id = _cfg("smartthings_client_id")
    if not client_id:
        return None
    return AUTHORIZE_URL + "?" + urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": _cfg("smartthings_redirect_uri", REDIRECT_PADRAO),
            "scope": ESCOPOS,
        }
    )




def configurar():
    
    url = montar_url_autorizacao()
    if not url:
        print(
            "Defina smartthings_client_id e smartthings_client_secret no "
            f"{config.CONFIG_FILE} antes."
        )
        return
    print("1) Abra este link, faça login na Samsung e autorize:\n")
    print(url)
    print(
        "\n2) Você será redirecionado para a redirect_uri. Copie o valor do "
        "parâmetro 'code' da URL (ele expira rápido!)."
    )
    codigo = input("\nCole o code aqui: ").strip()
    if trocar_codigo(codigo):
        print(f"Pronto! Tokens salvos em {ARQUIVO_TOKENS}")
    else:
        print("Falhou. Gere um code novo e tente de novo (veja o log acima).")


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        configurar()
    elif len(sys.argv) > 1 and sys.argv[1] == "refresh":
        print("OK" if renovar_token() else "Falhou")
    else:
        print("Uso: python smartthings_auth.py [setup|refresh]")