"""Conecta a agenda Google pessoal."""
import base64
import hashlib
import json
import secrets
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime,timedelta,timezone
import config
from interface import cofre_privado,gmail

TRAVA=threading.RLock()
PENDENTE=None
CACHE=None
REDIRECT="http://127.0.0.1:5678/agenda/google/callback"
ESCOPO="https://www.googleapis.com/auth/calendar.events.readonly"

# Localiza credenciais na pasta data
def arquivos():
    pasta=config.DATA_DIR/"google_agenda"
    return pasta/"cliente.json",pasta/"sessao.json"

# Consulta conexão sem expor segredos
def status():
    cliente,sessao=arquivos()
    try:c=cofre_privado.ler(cliente);t=cofre_privado.ler(sessao)
    except (ValueError,OSError):return {"configurado":False,"conectado":False,"erro":"Credencial local indisponível"}
    return {"configurado":bool(c.get("client_id")),"conectado":bool(t.get("refresh_token")),"somente_leitura":True,"retorno":REDIRECT}

# Importa cliente OAuth de computador
def configurar(dados):
    global CACHE
    if not isinstance(dados,dict):raise ValueError("JSON inválido")
    cliente=dados.get("installed",dados)
    if not isinstance(cliente,dict) or "web" in dados:raise ValueError("Use cliente OAuth para computador")
    ident=cliente.get("client_id","");secret=cliente.get("client_secret","")
    if not isinstance(ident,str) or not gmail.clientIdPattern.fullmatch(ident) or not isinstance(secret,str) or len(secret)>500:raise ValueError("Cliente OAuth inválido")
    path,token=arquivos()
    with TRAVA:
        antigo=cofre_privado.ler(path)
        cofre_privado.gravar(path,{"client_id":ident,"client_secret":secret})
        if antigo.get("client_id") and antigo["client_id"]!=ident:token.unlink(missing_ok=True)
        CACHE=None
    return status()

# Abre consentimento no navegador

def conectar():
    global PENDENTE
    with TRAVA:
        cliente=cofre_privado.ler(arquivos()[0])
        if not cliente.get("client_id"):raise ValueError("Importe o cliente OAuth primeiro")
        state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(64)
        PENDENTE={"state":state,"verifier":verifier,"inicio":time.monotonic()}
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    url="https://accounts.google.com/o/oauth2/v2/auth?"+urllib.parse.urlencode({"client_id":cliente["client_id"],"redirect_uri":REDIRECT,"response_type":"code","scope":ESCOPO,"access_type":"offline","prompt":"consent","state":state,"code_challenge":challenge,"code_challenge_method":"S256"})
    if not webbrowser.open(url,new=2):raise RuntimeError("Não foi possível abrir o navegador")
    return {"mensagem":"Autorize a leitura da agenda no navegador"}

# Valida retorno único com PKCE
def retorno(code,state):
    global PENDENTE
    with TRAVA:
        pendente=PENDENTE
        if not pendente or not isinstance(state,str) or not secrets.compare_digest(state,pendente["state"]) or time.monotonic()-pendente["inicio"]>600:raise ValueError("Autorização inválida ou expirada")
        PENDENTE=None
        if not isinstance(code,str) or not 1<=len(code)<=4096:raise ValueError("Código inválido")
        cliente=cofre_privado.ler(arquivos()[0])
        token=gmail.postForm("https://oauth2.googleapis.com/token",{**cliente,"code":code,"code_verifier":pendente["verifier"],"grant_type":"authorization_code","redirect_uri":REDIRECT},timeout=15)
        if not token.get("refresh_token") or not token.get("access_token"):raise ValueError("Consentimento não concluído")
        cofre_privado.gravar(arquivos()[1],{"refresh_token":token["refresh_token"],"access_token":token["access_token"],"expires_at":time.time()+int(token.get("expires_in",3600))})
    return status()

# Renova acesso sob trava única
def acesso():
    with TRAVA:
        token=cofre_privado.ler(arquivos()[1])
        if not token.get("refresh_token"):raise RuntimeError("Google Agenda não conectado")
        if float(token.get("expires_at",0))-time.time()>60:return token["access_token"]
        cliente=cofre_privado.ler(arquivos()[0])
        resposta=gmail.postForm("https://oauth2.googleapis.com/token",{**cliente,"refresh_token":token["refresh_token"],"grant_type":"refresh_token"},timeout=15)
        token.update(access_token=resposta["access_token"],expires_at=time.time()+int(resposta.get("expires_in",3600)))
        cofre_privado.gravar(arquivos()[1],token)
        return token["access_token"]

# Consulta compromissos sem alterar

def eventos():
    global CACHE
    with TRAVA:
        if CACHE and time.monotonic()-CACHE[0]<60:return list(CACHE[1])
        if not status()["conectado"]:return []
        inicio=datetime.now().astimezone().replace(hour=0,minute=0,second=0,microsecond=0)
        query=urllib.parse.urlencode({"timeMin":inicio.isoformat(),"timeMax":(inicio+timedelta(days=7)).isoformat(),"singleEvents":"true","orderBy":"startTime","maxResults":100})
        req=urllib.request.Request("https://www.googleapis.com/calendar/v3/calendars/primary/events?"+query,headers={"Authorization":"Bearer "+acesso(),"Accept":"application/json"})
        with urllib.request.urlopen(req,timeout=12) as resp:
            raw=resp.read(2000001)
            if len(raw)>2000000:raise ValueError("Resposta muito grande")
            dados=json.loads(raw)
        itens=[]
        for event in dados.get("items",[]):
            if event.get("status")=="cancelled":continue
            start=event.get("start",{});data=start.get("dateTime") or start.get("date")
            if not data:continue
            itens.append({"id":"google:"+str(event.get("id","")),"titulo":str(event.get("summary","Compromisso"))[:300],"inicio":data,"dia_inteiro":bool(start.get("date")),"descricao":str(event.get("description",""))[:2000],"origem":"google"})
        CACHE=(time.monotonic(),itens)
        return list(itens)

# Remove apenas a sessão da agenda
def desconectar():
    global CACHE,PENDENTE
    with TRAVA:
        arquivos()[1].unlink(missing_ok=True);CACHE=None;PENDENTE=None
    return status()
