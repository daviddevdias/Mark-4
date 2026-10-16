"""Valida a interface com dados sintéticos e servidor isolado."""
import argparse
import copy
import io
import re
import threading
from pathlib import Path
from flask import Flask, Response, jsonify, request, send_from_directory
from werkzeug.serving import make_server
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
app=Flask(__name__,static_folder=str(ROOT/"interface/static"))
photo=io.BytesIO();Image.new("RGB",(640,360),"#20607c").save(photo,format="JPEG")
attempts=0
widgets=[{"tipo":kind,"x":24+i%3*380,"y":24+i//3*310,"w":360,"h":290} for i,kind in enumerate(["camera_live","security","system","email","agenda","mobile"])]
profile={"versao":2,"revisao":0,"principal":{"id":"principal","nome":"Principal","widgets":[]},"telas":[{"id":"test","nome":"Teste","widgets":widgets}],"ultima_tela":"test"}
resource={"cpu":32,"ram":93,"ram_disponivel_mb":512,"pressao_memoria":"alta","historico":[{"hora":1000+i*5,"cpu":i*7,"ram":85+i} for i in range(8)],"gpu":None,"processos":[{"nome":"Busy","cpu":45,"ram_mb":240},{"nome":"Heavy","cpu":1,"ram_mb":1900}],"processos_memoria":[{"nome":"Heavy","cpu":1,"ram_mb":1900},{"nome":"Busy","cpu":45,"ram_mb":240}],"jarvis_mb":900,"disco":20,"atualizado_em":1791932400,"componentes":[{"nome":"Serviço Jarvis","ram_mb":400},{"nome":"brave.exe","ram_mb":500}],"camera":True,"gmail":True,"celular":{"conectado":False}}
security={"ativa":True,"armado":True,"linha_ativa":False,"camera":{"conectada":True,"camera_movida":True,"ativo":True,"pessoas":0},"eventos":[],"fala":{}}
central_sources=[{"id":"smartthings","nome":"SmartThings","tipo":"smartthings","configurada":True,"estado":"conectada","ferramentas":[]},{"id":"google_contacts","nome":"Google Contatos · MCP","tipo":"mcp","configurada":False,"estado":"não configurada","ferramentas":[]},{"id":"samsung_health","nome":"Samsung Health · MCP","tipo":"mcp","configurada":False,"estado":"não configurada","ferramentas":[]}]
central_devices=[{"id":"light.sala","nome":"Luz da sala","estado":"off","tipo":"light"}]
central_routines=[]
message={"id":"synthetic","subject":"Mensagem de teste","from":"Equipe","date":"2026-10-14T10:00:00-03:00","snippet":"Prévia curta e legível","body":"Texto com detalhes.\n\nhttps://www.linkedin.com/jobs/view/123/?token="+"a"*900+"\n\n<style>.secret{color:red}</style>"}
@app.route('/<path:path>',methods=['GET','POST','DELETE'])
def handler(path):
    global attempts,profile,central_routines
    if path in {"painel","telas"}:
        html=(ROOT/("jarvis.html" if path=="painel" else "telas.html")).read_text(encoding="utf-8")
        html=re.sub(r'<script src="https://cdn[^>]+></script>|<script src="/hud/core3d[^>]+></script>',"",html)
        return html
    if path=="central/fontes":return {"fontes":central_sources}
    if path=="central/aparelhos":return {"aparelhos":central_devices}
    if path=="central/rotinas":
        if request.method=="POST":
            routine=dict(request.json,id="a"*32,execucao={});central_routines=[routine];return routine
        return {"rotinas":central_routines}
    if path.startswith("central/rotinas/") and path.endswith("/executar"):return {"simulacao":True,"passos":[{}],"permitida_agora":True}
    if path=="central/rotinas/cancelar":return {"cancelamento":"solicitado"}
    if path=="central/aparelhos/acao":return {"enviado":True}
    if path=="interface/telas":return profile
    if path=="interface/telas/editar":
        d=request.json;target=profile['principal'] if d['id']=='principal' else profile['telas'][0]
        if d['acao']=='layout':
            if d['revisao']!=profile['revisao']:return {"erro":"Conflito"},409
            target['widgets']=d['widgets']
        elif d['acao']=='peca':target['widgets']=[w for w in target['widgets'] if w['tipo']!=d['widget']['tipo']]+[d['widget']]
        profile['revisao']+=1;return {"perfil":profile}
    if path=='interface/seguranca':return {"armado":True,"conectada":True,"camera_movida":True,"linha_ativa":False,"pessoas":0}
    if path=='seguranca/estado':return security
    if path=='seguranca/ao-vivo/stream':return {},503
    if path=='seguranca/linha/quadro.jpg':
        attempts+=1
        if attempts<=2:return {},503
        return Response(photo.getvalue(),mimetype='image/jpeg')
    if path in {'interface/recursos','interface/dashboard'}:return resource
    if path=='interface/celular':return {"conectado":False}
    if path=='pessoal/mensagens/celular':return []
    if path=='gmail/status':return {"conectado":True,"configurado":True}
    if path=='gmail/mensagens':return {"mensagens":[message]}
    if path=='interface/ia':return {"servidor":True,"modelo":"qwen3-8b","modelo_disponivel":True,"hermes_instalado":True,"url":"http://localhost:1235/v1"}
    if path=='preferencias':return {"itens":[]}
    if path=='api/endereco':return {"ips":[],"porta":5678}
    if path=='noticias/g1':return {"noticias":[]}
    if path in {'agenda','memoria/notas','historico','api/smarthome/dispositivos'}:return []
    if path=='seguranca/falas':return {"frases":[]}
    if path=='seguranca/onvif':return {"ptz_estado":"Sem teste"}
    if path=='interface/desempenho':return {"sucesso":True}
    return {}


def main(canal=None):
    server=make_server('127.0.0.1',5685,app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start()
    output=ROOT/'data'/'manutencao'/'validacao_interface';output.mkdir(parents=True,exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True, **({"channel":canal} if canal else {}))
            page=browser.new_page(viewport={"width":1366,"height":900});errors=[];page.on('pageerror',lambda e:(errors.append(str(e)),print('PAGE ERROR:',str(e),flush=True)))
            page.goto('http://127.0.0.1:5685/telas?tela=test')
            page.wait_for_selector('.camera-preview',timeout=20000)
            assert attempts>=3
            assert page.locator('.stark-headline').inner_text()=='Proteção parcial'
            assert page.get_by_text('Celular desconectado · exibindo avisos salvos').is_visible()
            page.locator('[data-tipo="email"] [role=button]').click()
            assert 'token=' not in page.locator('.mail-body').inner_text()
            assert page.locator('.mail-body style').count()==0
            page.get_by_role('button',name='Criar lembrete',exact=True).click()
            assert page.locator('.mail-reminder').is_visible()
            page.locator('.mail-reminder input').fill('2099-10-15T14:30')
            with page.expect_request('**/agenda') as sent:page.get_by_role('button',name='Salvar lembrete',exact=True).click()
            assert sent.value.post_data_json['titulo']=='Responder: Mensagem de teste'
            with page.expect_request('**/memoria/notas') as saved:page.get_by_role('button',name='Salvar como nota',exact=True).click()
            assert saved.value.post_data_json['area']=='trabalho'
            page.get_by_role('button',name='Fechar',exact=True).click()
            size=page.locator('[data-tipo="security"] .widget-sizes');size.select_option('540,420');page.wait_for_function('document.body.dataset.layoutSave==="saved"')
            assert page.locator('[data-tipo="security"]').bounding_box()['width']==540
            page.keyboard.press('Control+z');page.wait_for_function('document.querySelector("[data-tipo=security]").style.width==="360px"')
            page.get_by_role('button',name='Organizar elementos',exact=True).click();page.get_by_role('button',name='Travar posições',exact=True).click()
            assert page.locator('body').evaluate('e=>e.classList.contains("layout-locked")')
            page.screenshot(path=str(output/'cards.png'))
            page.keyboard.press('Control+k');page.get_by_role('searchbox').fill('saúde');page.keyboard.press('Enter')
            page.wait_for_selector('.resource-pressure[data-level=alta]')
            assert page.locator('.jarvis-dashboard .resource-chart polyline').count()==2
            assert 'Heavy' in page.locator('.jarvis-dashboard .resource-processes:not([hidden])').inner_text().splitlines()[0]
            assert page.locator('.jarvis-dashboard').evaluate('(e)=>Math.abs(e.getBoundingClientRect().left-(innerWidth-e.clientWidth)/2)<5')
            with page.expect_download() as download:page.get_by_role('button',name='Exportar diagnóstico').click()
            exported=Path(download.value.path()).read_text(encoding='utf-8')
            assert 'Mensagem de teste' not in exported and 'historico' in exported
            page.screenshot(path=str(output/'dashboard.png'))
            page.keyboard.press('Escape');page.wait_for_selector('.jarvis-dashboard',state='detached')
            page.goto('http://127.0.0.1:5685/painel?embutido=native')
            page.evaluate('openJarvisSection("cfg")')
            page.wait_for_selector('.settings-search input')
            page.locator('.settings-search input').fill('gmail')
            assert page.locator('#gmailGroup').is_visible()
            assert not page.locator('#connectionGroup').is_visible()
            page.get_by_role('button',name='Limpar busca').click()
            page.get_by_text('Aparência e desempenho',exact=True).click();page.locator('.economy-control input').check()
            assert page.locator('body').evaluate('e=>e.classList.contains("economy-mode")')
            page.screenshot(path=str(output/'settings.png'))
            page.evaluate('openJarvisSection("seg")');page.wait_for_selector('#liveFrame',state='attached') if page.locator('#liveFrame').count() else None
            page.wait_for_selector('.camera-preview',timeout=15000)
            assert page.locator('.camera-tools').count()==1
            page.evaluate('openJarvisSection("ctl")');page.wait_for_timeout(1200)
            assert page.locator('.camera-tools').count()==0
            page.evaluate('window.openJarvisCasa()')
            page.wait_for_selector('.casa-modal[open]')
            page.get_by_role('button',name='Dispositivos',exact=True).click()
            assert page.get_by_text('Luz da sala',exact=True).is_visible()
            with page.expect_request('**/central/aparelhos/acao'):
                page.get_by_role('button',name='Ligar',exact=True).click()
            page.get_by_role('button',name='Rotinas',exact=True).click()
            page.get_by_role('button',name='+ Nova rotina').click()
            page.get_by_label('Nome').fill('Rotina teste')
            page.get_by_label('Frase para ativar (opcional)').fill('Jarvis ligar luz')
            page.locator('.casa-step-row input').fill('Olá, senhor.')
            with page.expect_request('**/central/rotinas') as rotina_salva:
                page.get_by_role('button',name='Salvar desativada').click()
            assert rotina_salva.value.post_data_json['ativa'] is False
            assert rotina_salva.value.post_data_json['frases']==['Jarvis ligar luz']
            page.get_by_text('Rotina teste',exact=True).wait_for(timeout=5000)
            page.keyboard.press('Escape')
            page.evaluate('openJarvisEmail('+__import__('json').dumps(message)+')')
            page.set_viewport_size({"width":375,"height":720})
            assert page.locator('.jarvis-card-dialog').evaluate('(e)=>e.getBoundingClientRect().right<=innerWidth')
            assert page.get_by_role('button',name='Gerar resposta',exact=True).bounding_box()['y']<720
            page.screenshot(path=str(output/'email-mobile.png'))
            assert not errors,errors
            print('PASS: camera recovery, security, mobile, email, sizes, undo, lock, quick search, dashboard, settings, economy, player cleanup, mobile layout')
            browser.close()
    finally:server.shutdown()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--canal',choices=('chrome','msedge'),help='Usa navegador ja instalado, sem baixar Chromium adicional')
    main(parser.parse_args().canal)

