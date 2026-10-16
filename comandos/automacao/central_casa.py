"""Fontes e rotinas locais. Credenciais protegidas; execução explícita e cancelável."""
import json
import re
import threading
import time
import uuid
from datetime import datetime
from urllib.parse import urlsplit

import requests
import config
from interface import cofre_privado

TRAVA = threading.RLock()
CAMINHO = config.DATA_DIR / "central_casa.json"
ATIVAS = {}
ESTADOS = {}
AGENDADOR = None
ULTIMOS_GATILHOS = set()
ULTIMOS_DISPAROS = {}
# Integrações MCP escolhidas pelo usuário.
FONTES = {
    "google_contacts": ("Google Contatos · MCP", "mcp"),
    "samsung_health": ("Samsung Health · MCP", "mcp"),
}


def carregar():
    d = cofre_privado.ler(CAMINHO)
    fontes = d.get("fontes", {}) if isinstance(d, dict) else {}
    fontes = fontes if isinstance(fontes, dict) else {}
    fontes_ativas = {k: v for k, v in fontes.items() if k in FONTES}
    rotinas = d.get("rotinas", []) if isinstance(d, dict) else []
    rotinas = rotinas if isinstance(rotinas, list) else []
    if len(fontes_ativas) != len(fontes):
        # Migra a configuração protegida e apaga chaves de integrações removidas.
        cofre_privado.gravar(CAMINHO, {"fontes": fontes_ativas, "rotinas": rotinas})
    return {"fontes": fontes_ativas, "rotinas": rotinas}


def url_valida(url):
    p = urlsplit(url)
    if len(url)>2000 or p.scheme not in ("https", "http") or not p.hostname or p.username or p.password or p.fragment or p.query:
        raise ValueError("Use um endereço HTTP(S) válido, sem usuário e senha na URL.")
    # URLs MCP podem incluir uma chave no caminho: nunca são devolvidas pela API.
    return url.rstrip("/")


def fontes_publicas():
    with TRAVA:
        dados = carregar()["fontes"]
        fontes = [{"id": k, "nome": v[0], "tipo": v[1], "configurada": bool(dados.get(k)),
                   "estado": ESTADOS.get(k, {}).get("estado", "não verificada" if dados.get(k) else "não configurada"),
                   "verificado_em": ESTADOS.get(k, {}).get("hora"),
                   "ferramentas": ESTADOS.get(k, {}).get("ferramentas", [])}
                  for k, v in FONTES.items()]
        try:
            from comandos.automacao import smart_home
            configurada = bool(smart_home.obter_token())
        except Exception:
            configurada = False
        estado = ESTADOS.get("smartthings", {}).get("estado", "configurada · não verificada" if configurada else "não configurada")
        fontes.insert(0, {"id": "smartthings", "nome": "SmartThings", "tipo": "smartthings",
                          "configurada": configurada, "estado": estado,
                          "verificado_em": ESTADOS.get("smartthings", {}).get("hora"), "ferramentas": []})
        return fontes


def configurar(identificador, dados):
    if identificador not in FONTES: raise ValueError("Fonte inválida")
    url=url_valida(str(dados.get("url", "")))
    token=dados.get("token", "")
    if not isinstance(token,str) or len(token)>8000 or "\n" in token or "\r" in token: raise ValueError("Token inválido")
    with TRAVA:
        config_local=carregar();anterior=config_local["fontes"].get(identificador,{})
        config_local["fontes"][identificador]={"url":url,"token":token or anterior.get("token", "")}
        cofre_privado.gravar(CAMINHO,config_local);ESTADOS.pop(identificador,None)


def remover_fonte(identificador):
    with TRAVA:
        dados=carregar();dados["fontes"].pop(identificador,None);cofre_privado.gravar(CAMINHO,dados);ESTADOS.pop(identificador,None)


def requisicao(fonte, metodo, caminho="", dados=None, cabecalhos=None):
    headers={"Accept":"application/json, text/event-stream"}
    if fonte.get("token"):headers["Authorization"]="Bearer "+fonte["token"]
    headers.update(cabecalhos or {})
    with requests.Session() as session:
        session.trust_env=False
        with session.request(metodo,fonte["url"]+caminho,headers=headers,json=dados,timeout=(4,10),allow_redirects=False,stream=True) as r:
            if r.status_code not in (200,201,202,204):raise ValueError("A fonte recusou a conexão. Confira o endereço e a credencial.")
            body=bytearray()
            for chunk in r.iter_content(16384):
                body.extend(chunk)
                if len(body)>2_000_000:raise ValueError("Resposta da fonte excedeu o limite")
            if not body:return {},dict(r.headers)
            raw=body.decode("utf-8")
            if "text/event-stream" in r.headers.get("Content-Type",""):
                mensagens=[json.loads(l[5:].strip()) for l in raw.splitlines() if l.startswith("data:") and l[5:].strip()]
                result=next((m for m in mensagens if "result" in m or "error" in m),{})
            else:result=json.loads(raw)
            return result,dict(r.headers)


def obter_fonte(nome):
    with TRAVA:fonte=carregar()["fontes"].get(nome)
    if not fonte:raise ValueError("Configure esta fonte no painel do PC")
    return fonte


def verificar_fonte(nome):
    if nome == "smartthings":
        from comandos.automacao import smart_home
        token = smart_home.obter_token()
        if not token:
            with TRAVA: ESTADOS["smartthings"] = {"estado": "não configurada", "hora": time.time()}
            raise ValueError("Configure o token SmartThings em Casa IA → Conexões → SmartThings.")
        resposta = smart_home.realizar_requisicao_get("devices", token)
        itens = resposta.get("items") if isinstance(resposta, dict) else None
        if not isinstance(itens, list):
            with TRAVA: ESTADOS["smartthings"] = {"estado": "falha de conexão", "hora": time.time()}
            raise ValueError("O SmartThings não respondeu. Confira o token e a conexão.")
        with TRAVA: ESTADOS["smartthings"] = {"estado": "conectada", "hora": time.time(), "ferramentas": [f"{len(itens)} dispositivos"]}
        return {"sucesso": True, "ferramentas": [f"{len(itens)} dispositivos"]}
    if nome not in FONTES:raise ValueError("Fonte inválida")
    fonte=obter_fonte(nome)
    try:
        result,headers=requisicao(fonte,"POST",dados={"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"Jarvis Mark 2","version":"2"}}})
        if result.get("error") or "result" not in result:raise ValueError("A fonte não respondeu à inicialização MCP")
        session_id=next((v for k,v in headers.items() if k.lower()=="mcp-session-id"),None)
        session_headers={"MCP-Protocol-Version":result["result"].get("protocolVersion","2025-03-26")}
        if session_id:session_headers["Mcp-Session-Id"]=session_id
        try:
            requisicao(fonte,"POST",dados={"jsonrpc":"2.0","method":"notifications/initialized"},cabecalhos=session_headers)
            response,_=requisicao(fonte,"POST",dados={"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}},cabecalhos=session_headers)
            if response.get("error"):raise ValueError("A fonte não permitiu listar ferramentas")
            tools=[str(t.get("name",""))[:120] for t in response.get("result",{}).get("tools",[])[:100]]
        finally:
            if session_id:
                try:requisicao(fonte,"DELETE",cabecalhos=session_headers)
                except (ValueError,requests.RequestException):pass
        with TRAVA:ESTADOS[nome]={"estado":"conectada","hora":time.time(),"ferramentas":tools}
        return {"sucesso":True,"ferramentas":tools}
    except (requests.RequestException,ValueError,KeyError,TypeError):
        with TRAVA:ESTADOS[nome]={"estado":"falha de conexão","hora":time.time()}
        raise ValueError("Não foi possível verificar a fonte. Confira o servidor e as credenciais.") from None


def aparelhos():
    from comandos.automacao import smart_home
    saida=[]
    for d in smart_home.carregar_dispositivos()[:200]:
        identificador=str(d.get("deviceId", ""))
        main=(d.get("components") or {}).get("main") or {}
        capacidades={str(c.get("id", "")) for c in main.get("capabilities", []) if isinstance(c,dict)}
        if not identificador or "switch" not in capacidades:continue
        estado=((main.get("switch") or {}).get("switch") or {}).get("value", "unknown")
        saida.append({"id":"smartthings:"+identificador,"nome":str(d.get("label") or d.get("name") or identificador)[:150],"estado":str(estado)[:40],"tipo":"SmartThings"})
    return saida


def acionar_aparelho(entity, acao):
    if not isinstance(entity,str) or not re.fullmatch(r"smartthings:[A-Za-z0-9-]{1,160}",entity) or acao not in ("turn_on","turn_off"):
        raise ValueError("Escolha um aparelho SmartThings compatível e uma ação válida")
    from comandos.automacao import smart_home
    if not smart_home.enviar_comando_dispositivo(entity.removeprefix("smartthings:"), "on" if acao=="turn_on" else "off"):
        raise ValueError("O SmartThings não confirmou o comando do aparelho.")


def validar_rotina(d):
    if not isinstance(d,dict):raise ValueError("Rotina inválida")
    nome=d.get("nome","");descricao=d.get("descricao","");frases=d.get("frases",[]);apps=d.get("apps_notificacao",[]);passos=d.get("passos",[]);dias=d.get("dias",list(range(7)))
    if not isinstance(nome,str) or not 1<=len(nome.strip())<=80:raise ValueError("Dê um nome à rotina")
    if not isinstance(descricao,str) or len(descricao)>500:raise ValueError("Descrição inválida; use até 500 caracteres")
    if not isinstance(frases,list) or len(frases)>10 or any(not isinstance(f,str) or not 1<=len(f.strip())<=120 for f in frases):raise ValueError("Frases inválidas")
    if not isinstance(apps,list) or len(apps)>30 or any(not isinstance(app,str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+",app) for app in apps):raise ValueError("Aplicativos de notificação inválidos")
    if not isinstance(dias,list) or not dias or any(type(x) is not int or x not in range(7) for x in dias):raise ValueError("Dias inválidos")
    inicio=d.get("inicio","00:00");fim=d.get("fim","23:59")
    for h in (inicio,fim):
        if not isinstance(h,str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d",h):raise ValueError("Horário inválido")
    evento=d.get("evento","")
    if evento not in ("","chegada"):raise ValueError("Gatilho não disponível; reconhecimento facial ainda não configurado")
    agendada=d.get("agendada",False)
    if type(agendada) is not bool:raise ValueError("Estado do agendamento inválido")
    if not isinstance(passos,list) or not 1<=len(passos)<=20:raise ValueError("Use de 1 a 20 passos")
    limpos=[];espera=0
    for p in passos:
        if not isinstance(p,dict):raise ValueError("Passo inválido")
        tipo=p.get("tipo")
        if tipo=="falar":
            texto=p.get("texto","")
            if not isinstance(texto,str) or not 1<=len(texto.strip())<=500:raise ValueError("Texto de fala inválido")
            limpos.append({"tipo":tipo,"texto":texto.strip()})
        elif tipo=="esperar":
            segundos=p.get("segundos")
            if type(segundos) is not int or not 1<=segundos<=600:raise ValueError("Espera deve ser de 1 a 600 segundos")
            espera+=segundos;limpos.append({"tipo":tipo,"segundos":segundos})
        elif tipo=="aparelho":
            entity=p.get("id","");acao=p.get("acao","")
            if not isinstance(entity,str) or not re.fullmatch(r"smartthings:[A-Za-z0-9-]{1,160}",entity) or acao not in ("turn_on","turn_off"):raise ValueError("Aparelho ou ação inválidos")
            limpos.append({"tipo":tipo,"id":entity,"acao":acao})
        else:raise ValueError("Tipo de passo inválido")
    if espera>1800:raise ValueError("A soma das esperas deve ser de até 30 minutos")
    ativo=d.get("ativa",False)
    if type(ativo) is not bool:raise ValueError("Estado inválido")
    return {"nome":nome.strip(),"descricao":descricao.strip(),"frases":[f.strip() for f in frases],"apps_notificacao":sorted(set(apps)),"passos":limpos,"dias":sorted(set(dias)),"inicio":inicio,"fim":fim,"evento":evento,"agendada":agendada,"ativa":ativo}


class ConflitoRotina(ValueError):
    """A rotina mudou desde a última leitura do cliente."""


def salvar_rotina(dados):
    nova=validar_rotina(dados);identificador=dados.get("id") or uuid.uuid4().hex
    if not isinstance(identificador,str) or not re.fullmatch(r"[a-f0-9]{32}",identificador):raise ValueError("Identificador inválido")
    nova["id"]=identificador
    with TRAVA:
        d=carregar();existente=next((r for r in d["rotinas"] if r["id"]==identificador),None)
        if existente:
            versao_atual=int(existente.get("versao",1))
            versao_recebida=dados.get("versao")
            if versao_recebida is not None and (type(versao_recebida) is not int or versao_recebida!=versao_atual):
                raise ConflitoRotina("Esta rotina mudou em outro dispositivo. Atualize a lista antes de salvar.")
            nova["versao"]=versao_atual+1
        else:
            nova["versao"]=1
        nova["schema_version"]=1
        nova["atualizada_em"]=datetime.now().astimezone().isoformat(timespec="seconds")
        resto=[r for r in d["rotinas"] if r["id"]!=identificador]
        if len(resto)>=100:raise ValueError("Limite de 100 rotinas")
        d["rotinas"]=resto+[nova];cofre_privado.gravar(CAMINHO,d)
    return nova


def listar_rotinas():
    with TRAVA:
        return [dict(r,schema_version=r.get("schema_version",1),versao=r.get("versao",1),atualizada_em=r.get("atualizada_em"),execucao=ESTADOS.get(r["id"],{})) for r in carregar()["rotinas"]]


def remover_rotina(identificador):
    with TRAVA:
        if identificador in ATIVAS:ATIVAS[identificador].set()
        d=carregar();d["rotinas"]=[r for r in d["rotinas"] if r["id"]!=identificador];cofre_privado.gravar(CAMINHO,d)


def na_janela(r,agora=None):
    agora=agora or datetime.now();h=agora.strftime("%H:%M")
    if agora.weekday() not in r["dias"]:return False
    return r["inicio"]<=h<=r["fim"] if r["inicio"]<=r["fim"] else h>=r["inicio"] or h<=r["fim"]


def executar(identificador,simular=True, falar_no_pc=True):
    with TRAVA:
        r=next((r for r in carregar()["rotinas"] if r["id"]==identificador),None)
        if not r:raise ValueError("Rotina não encontrada")
        if simular:return {"simulacao":True,"nome":r["nome"],"passos":r["passos"],"permitida_agora":na_janela(r)}
        if not r["ativa"] or not na_janela(r):raise ValueError("Rotina desativada ou fora do horário permitido")
        if identificador in ATIVAS or len(ATIVAS)>=2:raise ValueError("Já existe uma rotina em execução; aguarde")
        cancel=threading.Event();ATIVAS[identificador]=cancel;ESTADOS[identificador]={"estado":"executando","passo":0,"hora":time.time()}
    def rodar():
        from interface import voz
        try:
            for i,p in enumerate(r["passos"]):
                if cancel.is_set():break
                with TRAVA:ESTADOS[identificador]["passo"]=i+1
                if p["tipo"]=="esperar":cancel.wait(p["segundos"])
                elif p["tipo"]=="falar":
                    if falar_no_pc:voz.falar(p["texto"],deve_parar=cancel.is_set)
                else:acionar_aparelho(p["id"],p["acao"])
            estado="cancelada" if cancel.is_set() else "concluída"
        except Exception:estado="falha · confira a conexão do aparelho"
        finally:
            with TRAVA:ESTADOS[identificador].update(estado=estado,hora=time.time());ATIVAS.pop(identificador,None)
    threading.Thread(target=rodar,daemon=True,name="jarvis-rotina-casa").start()
    falas=[p["texto"] for p in r["passos"] if p.get("tipo")=="falar"] if not falar_no_pc else []
    return {"iniciada":True,"nome":r["nome"],"falas":falas}


def _verificar_agendamentos():
    """Dispara uma rotina uma vez por minuto no horário configurado."""
    global ULTIMOS_GATILHOS
    agora = datetime.now()
    chave_minuto = agora.strftime("%Y-%m-%d %H:%M")
    dia = agora.strftime("%Y-%m-%d")
    ULTIMOS_GATILHOS = {k for k in ULTIMOS_GATILHOS if k.partition(":")[2].startswith(dia)}
    for rotina in listar_rotinas():
        chave = f"{rotina['id']}:{chave_minuto}"
        if rotina.get("ativa") and rotina.get("agendada", False) and rotina.get("inicio") == agora.strftime("%H:%M") and chave not in ULTIMOS_GATILHOS:
            ULTIMOS_GATILHOS.add(chave)
            try:
                executar(rotina["id"], False)
            except ValueError:
                pass


def iniciar_agendador():
    """Inicia o agendador local idempotente, sem executar rotinas desativadas."""
    global AGENDADOR
    with TRAVA:
        if AGENDADOR and AGENDADOR.is_alive():
            return AGENDADOR
        def ciclo():
            while True:
                try:
                    _verificar_agendamentos()
                except Exception:
                    import logging
                    logging.getLogger("mark2.rotinas_casa").exception("Falha ao conferir rotinas agendadas")
                time.sleep(max(1, 60 - datetime.now().second))
        AGENDADOR = threading.Thread(target=ciclo, daemon=True, name="jarvis-agendador-casa")
        AGENDADOR.start()
        return AGENDADOR


def cancelar():
    with TRAVA:
        for cancel in ATIVAS.values():cancel.set()


def disparar(frase=None,evento=None,app=None,origem="pc"):
    """Executa a primeira rotina elegível e retorna falas para o dispositivo de origem."""
    from comandos.linguagem import chave
    agora=time.monotonic()
    with TRAVA:
        for identificador,hora in list(ULTIMOS_DISPAROS.items()):
            if agora-hora>300:ULTIMOS_DISPAROS.pop(identificador,None)
    for r in listar_rotinas():
        frase_ok=bool(frase and chave(frase) in {chave(f) for f in r.get("frases",[])})
        evento_ok=bool(evento and evento==r.get("evento"))
        app_ok=bool(app and app in r.get("apps_notificacao",[]))
        if r["ativa"] and na_janela(r) and (frase_ok or evento_ok or app_ok):
            with TRAVA:
                if agora-ULTIMOS_DISPAROS.get(r["id"],0)<3:
                    return {"disparada":False,"correspondida":True,"duplicada":True,"mensagem":"Este gatilho acabou de ser processado.","rotina":r["nome"],"falas":[]}
                ULTIMOS_DISPAROS[r["id"]]=agora
            try:
                executar(r["id"],False,falar_no_pc=(origem!="android"))
                falas=[p["texto"] for p in r.get("passos",[]) if p.get("tipo")=="falar"]
                return {"disparada":True,"correspondida":True,"duplicada":False,"mensagem":"Rotina "+r["nome"]+" iniciada.","rotina":r["nome"],"falas":falas}
            except ValueError as e:
                with TRAVA:ULTIMOS_DISPAROS.pop(r["id"],None)
                return {"disparada":False,"correspondida":True,"duplicada":False,"mensagem":str(e),"rotina":r["nome"],"falas":[]}
    return None
