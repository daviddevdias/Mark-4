"""API da central de integrações e rotinas configuradas no computador."""
import ipaddress
from flask import Blueprint, jsonify, request
from comandos.automacao import central_casa

api=Blueprint("central_casa",__name__)

@api.errorhandler(ValueError)
def invalido(erro):return jsonify({"erro":str(erro)}),400

@api.errorhandler(OSError)
def armazenamento(erro):return jsonify({"erro":"Não foi possível acessar os dados locais."}),503

@api.errorhandler(central_casa.ConflitoRotina)
def conflito(erro):return jsonify({"erro":str(erro)}),409

def objeto():
    d=request.get_json(silent=True)
    if not isinstance(d,dict):raise ValueError("Envie os dados no formato JSON.")
    return d

def local():
    if not ipaddress.ip_address((request.remote_addr or "0.0.0.0").split("%",1)[0]).is_loopback:
        raise ValueError("Configure as conexões no painel do PC.")

@api.get("/central/fontes")
def fontes():return jsonify({"fontes":central_casa.fontes_publicas()})

@api.route("/central/fontes/<nome>",methods=["POST","DELETE"])
def configurar(nome):
    local()
    if request.method=="DELETE":central_casa.remover_fonte(nome)
    else:central_casa.configurar(nome,objeto())
    return jsonify({"salvo":True})

@api.post("/central/fontes/<nome>/verificar")
def verificar(nome):local();return jsonify(central_casa.verificar_fonte(nome))

@api.get("/central/aparelhos")
def aparelhos():
    try:return jsonify({"aparelhos":central_casa.aparelhos()})
    except (ValueError,OSError):return jsonify({"aparelhos":[],"erro":"Conecte o SmartThings em Casa IA → Conexões → SmartThings para carregar os aparelhos."}),503

@api.post("/central/aparelhos/acao")
def acao():
    d=objeto();central_casa.acionar_aparelho(d.get("id"),d.get("acao"));return jsonify({"enviado":True})

@api.route("/central/rotinas",methods=["GET","POST"])
def rotinas():
    if request.method=="POST":return jsonify(central_casa.salvar_rotina(objeto()))
    return jsonify({"rotinas":central_casa.listar_rotinas()})

@api.post("/central/rotinas/disparar")
def disparar_rotina_voz():
    dados=objeto();frase=dados.get("frase");app=dados.get("app");origem=dados.get("origem","pc")
    if frase is not None and (not isinstance(frase,str) or len(frase)>120):raise ValueError("Frase inválida.")
    if app is not None and (not isinstance(app,str) or len(app)>255):raise ValueError("Aplicativo inválido.")
    if origem not in ("pc","android"):raise ValueError("Origem inválida.")
    resultado=central_casa.disparar(frase=frase.strip() if frase else None,app=app,origem=origem)
    return jsonify({"disparada":bool((resultado or {}).get("disparada")),"correspondida":bool((resultado or {}).get("correspondida")),"duplicada":bool((resultado or {}).get("duplicada")),"mensagem":(resultado or {}).get("mensagem",""),"falas":(resultado or {}).get("falas",[])})

@api.delete("/central/rotinas/<identificador>")
def remover(identificador):central_casa.remover_rotina(identificador);return jsonify({"removida":True})

@api.post("/central/rotinas/<identificador>/executar")
def executar(identificador):
    dados=objeto();simular=dados.get("simular",True);origem=dados.get("origem","pc")
    if type(simular) is not bool:raise ValueError("Escolha entre simular ou executar.")
    if origem not in ("pc","android"):raise ValueError("Origem inválida.")
    return jsonify(central_casa.executar(identificador,simular,falar_no_pc=(origem!="android")))

@api.post("/central/rotinas/cancelar")
def cancelar():central_casa.cancelar();return jsonify({"cancelamento":"solicitado"})

@api.get("/pessoal/diagnostico")
def diagnostico():
    from comandos import llm_local
    from comandos.automacao import vigia_camera, visao_inteligente
    from interface import recursos_sistema
    camera=vigia_camera.estado_atual()
    gravador=vigia_camera.GRAVADOR_EVENTOS.status() if vigia_camera.GRAVADOR_EVENTOS else {"ativo":False,"erro":"Gravador ainda não iniciado"}
    modelo=llm_local.modelos_disponiveis();pose=visao_inteligente.estado().get("pose",{})
    recursos=recursos_sistema.consultar(None)
    return jsonify({"camera":{"conectada":bool(camera.get("conectada")),"posicao_validada":bool(camera.get("camera_posicao_validada"))},"gravacao":gravador,"detector":{"status":pose.get("status"),"backend":pose.get("backend"),"inferencial_s":pose.get("inferencia_s"),"idade_s":camera.get("pessoas_ts")},"ia":{"habilitada":llm_local.servidor_local_ativo(),"conectada":modelo["conectado"],"modelo":llm_local.resolver_modelo()},"sistema":{"cpu":recursos.get("cpu"),"ram":recursos.get("ram"),"ram_disponivel_mb":recursos.get("ram_disponivel_mb"),"pressao_memoria":recursos.get("pressao_memoria")}})
