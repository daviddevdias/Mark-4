(() => {
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
  const request = async (url, data, method) => {
    const response = await fetch(url, { method: method || (data ? "POST" : "GET"), headers: data ? {"Content-Type":"application/json"} : {}, body: data ? JSON.stringify(data) : undefined, cache: "no-store" });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.erro || `Falha ao acessar a central (${response.status}).`);
    return body;
  };
  const dialog = el("dialog", "casa-modal"), shell = el("section", "casa-shell");
  const header = el("header", "casa-header"), title = el("div", "casa-title"), headerActions=el("div","casa-header-actions"), back=el("button","casa-button casa-back","← Voltar"), close = el("button", "casa-button", "Fechar");
  title.append(el("strong", "", "J.A.R.V.I.S. · CONTROL CENTER"), el("span", "", "Dispositivos, integrações e rotinas"));
  back.type=close.type="button";back.hidden=true;headerActions.append(back,close);header.append(title, headerActions);
  const tabs = el("nav", "casa-tabs"), content = el("main", "casa-content"), status = el("p", "casa-status");
  shell.append(header, tabs, status, content); dialog.append(shell); document.body.append(dialog);
  close.onclick = () => dialog.close();
  let active = "fontes", routineView = "list", tabHistory = [], cache = {fontes:[], aparelhos:[], erroAparelhos:"", rotinas:[], dashboard:null, agenda:null, whatsappTotal:0};
  function mainView(){tabs.hidden=false;back.hidden=!tabHistory.length;back.onclick=tabHistory.length?()=>{active=tabHistory.pop()||"fontes";render()}:null}
  function subView(onBack){tabs.hidden=true;back.hidden=false;back.onclick=onBack}
  dialog.addEventListener("click", e => { if (e.target === dialog) dialog.close(); });
  const actions = [ ["fontes","Conexões"], ["aparelhos","Dispositivos"], ["rotinas","Rotinas"] ];
  function say(message, error=false) { status.textContent = message || ""; status.dataset.error = error ? "true" : "false"; }
  function button(label, fn, cls="") { const b=el("button", `casa-button ${cls}`,label); b.type="button"; b.onclick=fn; return b; }
  function card() { const n=el("article","casa-card"); return n; }
  function renderTabs() { mainView();tabs.replaceChildren(...actions.map(([id,label])=>{const b=button(label,()=>{if(active!==id)tabHistory.push(active);active=id;if(id==="rotinas")routineView="list";render()});b.classList.toggle("selected",active===id);return b})); }
  function section(label, description="") {
    const wrap=el("section","casa-section"), heading=el("div","casa-section-heading");
    heading.append(el("h2","",label));
    if(description) heading.append(el("p","",description));
    wrap.append(heading);
    return wrap;
  }
  function renderFontes() {
    const intro=card();
    intro.append(el("h2","","Conexões e serviços"),el("p","","Acompanhe os dispositivos e gerencie aqui as integrações do JARVIS."));
    const connectionSection=section("Estado das conexões","Situação atual do computador, celular e SmartThings."), overview=el("div","casa-device-overview");
    const phone=cache.dashboard?.celular;
    const deviceStatus=(name,state,detail)=>{const c=el("article","casa-device-status"),top=el("div","casa-device-status-top");top.append(el("strong","",name),el("span","casa-badge",state));c.append(top,el("small","",detail));overview.append(c)};
    deviceStatus("Computador",cache.dashboard?"Conectado":"Sem dados","Painel local do JARVIS");
    const phoneState=cache.dashboard?(phone?.conectado?"Conectado":"Desconectado"):"Sem dados";
    const phoneDetail=phone?.ultimo_segundos!=null?"Último contato há "+phone.ultimo_segundos+" s":"Estado informado pelo pareamento";
    deviceStatus("Android",phoneState,phoneDetail);
    const smart=cache.fontes.find(x=>x.id==="smartthings");
    deviceStatus("SmartThings",smart?.estado||(smart?.configurada?"Configurada · não verificada":"Não configurada"),"Integração da casa conectada");
    connectionSection.append(overview);

    const serviceSection=section("Serviços e integrações","Conecte ou verifique cada serviço individualmente."), grid=el("div","casa-grid");
    const agenda=card(),agendaTop=el("div","casa-card-top"),agendaCopy=el("div",""),agendaBadge=el("span","casa-badge",cache.agenda?.conectado?"Conectada":cache.agenda?.configurado?"Cliente salvo":"Não configurada");
    agendaCopy.append(el("strong","","Google Agenda"),el("small","",cache.agenda?.conectado?"Conta autorizada":cache.agenda?.configurado?"Cliente OAuth salvo neste computador":"Importe o cliente OAuth para conectar"));agendaTop.append(agendaCopy,agendaBadge);agenda.append(agendaTop);
    const agendaActions=el("div","casa-actions");agendaActions.append(button("Configurar / conectar",formAgenda),button("Atualizar estado",async()=>{try{cache.agenda=await request("/agenda/google/status");render()}catch(e){say(e.message,true)}}));
    if(cache.agenda?.conectado)agendaActions.append(button("Desconectar",async()=>{try{await request("/agenda/google/conectar",null,"DELETE");say("Google Agenda desconectado.");await load()}catch(e){say(e.message,true)}}));agenda.append(agendaActions);grid.append(agenda);
    for (const f of cache.fontes) {
      const c=card(), top=el("div","casa-card-top"), copy=el("div",""), badge=el("span","casa-badge",f.estado||"não verificada");
      copy.append(el("strong","",f.nome),el("small","",f.configurada?"Conexão salva com proteção local":"Ainda não configurada"));top.append(copy,badge);c.append(top);
      const actions=el("div","casa-actions");
      if(f.id==="smartthings"){
        actions.append(button(f.configurada?"Gerenciar conexão":"Conectar SmartThings",()=>formSmartThings()));
        actions.append(button("Verificar",async()=>{say("Verificando SmartThings…");try{const d=await request("/central/fontes/smartthings/verificar",{});say(`SmartThings conectado · ${d.ferramentas?.[0]||"pronto"}.`);await load()}catch(e){say(e.message,true)}}));
      }else{
        actions.append(button(f.configurada?"Editar conexão":"Conectar",()=>formFonte(f)),button("Verificar",async()=>{say("Verificando…");try{const d=await request(`/central/fontes/${encodeURIComponent(f.id)}/verificar`,{});say(d.ferramentas?.length?`Conectada · ${d.ferramentas.length} ferramenta(s) detectada(s).`:"Conectada.");await load()}catch(e){say(e.message,true)}}));
        if(f.configurada) actions.append(button("Desconectar",async()=>{try{await request(`/central/fontes/${encodeURIComponent(f.id)}`,null,"DELETE");say("Fonte removida.");await load()}catch(e){say(e.message,true)}}));
      }
      c.append(actions);
      if(f.ferramentas?.length){const tools=el("details","casa-tools"),sum=el("summary","",`${f.ferramentas.length} ferramentas disponíveis`),list=el("p","",f.ferramentas.join(" · "));tools.append(sum,list);c.append(tools)}
      grid.append(c);
    }
    serviceSection.append(grid);

    const personalSection=section("Recursos pessoais","Contatos e organização dos painéis do JARVIS."), personalGrid=el("div","casa-grid");
    const whatsapp=card(),whatsappTop=el("div","casa-card-top"),whatsappCopy=el("div",""),whatsappBadge=el("span","casa-badge",`${cache.whatsappTotal} contato(s)`);
    whatsappCopy.append(el("strong","","Contatos do WhatsApp"),el("small","","Importe contatos para os recursos de comunicação do JARVIS."));whatsappTop.append(whatsappCopy,whatsappBadge);whatsapp.append(whatsappTop,button("Importar contatos .VCF",formWhatsapp));personalGrid.append(whatsapp);
    const telas=card();telas.append(el("strong","","Telas e widgets"),el("p","","Organize os painéis e abra o resumo do dia."));const telasActions=el("div","casa-actions");telasActions.append(button("Personalizar telas",()=>{dialog.close();window.personalizeJarvisScreens?.()}),button("Meu dia",()=>{dialog.close();window.openDailyBriefing?.()}));telas.append(telasActions);personalGrid.append(telas);
    personalSection.append(personalGrid);
    content.replaceChildren(intro,connectionSection,serviceSection,personalSection);
  }
  function formFonte(f) {
    const form=el("form","casa-form"),name=el("h2","",`Conectar · ${f.nome}`),help=el("p","",f.id==="google_contacts"?"Informe o endereço Streamable HTTP do Google Contacts MCP e o token exigido pelo servidor. O endereço e a credencial ficam cifrados neste computador.":"Informe o endereço Streamable HTTP do Samsung Health MCP e o token exigido pelo servidor. O endereço e a credencial ficam cifrados neste computador.");
    const url=el("input");url.placeholder="https://servidor ou https://servidor-mcp";url.required=true;url.maxLength=2000;
    const token=el("input");token.type="password";token.placeholder="Token de acesso";token.autocomplete="new-password";token.maxLength=8000;
    const foot=el("div","casa-actions"),save=el("button","casa-button primary","Salvar conexão"),cancel=button("Cancelar",()=>render());save.type="submit";foot.append(save,cancel);form.append(name,help,url,token,foot);
    form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{await request(`/central/fontes/${encodeURIComponent(f.id)}`,{url:url.value.trim(),token:token.value});say("Conexão salva.");active="fontes";await load()}catch(e){say(e.message,true);save.disabled=false}};
    subView(()=>render());content.replaceChildren(form);url.focus();
  }
  function formSmartThings(){
    const form=el("form","casa-form"),name=el("h2","","Conectar · SmartThings"),help=el("p","","Cole o Personal Access Token da Samsung SmartThings. A chave é salva pelo JARVIS neste computador e não é exibida novamente.");
    const token=el("input");token.type="password";token.required=true;token.autocomplete="new-password";token.maxLength=8000;token.placeholder="Personal Access Token SmartThings";token.setAttribute("aria-label","Personal Access Token SmartThings");
    const foot=el("div","casa-actions"),save=el("button","casa-button primary","Salvar e verificar"),cancel=button("Cancelar",()=>render());save.type="submit";foot.append(save,cancel);form.append(name,help,token,foot);
    form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{await request("/api/smarthome/token",{token:token.value.trim()});token.value="";say("Chave salva. Verificando conexão…");await request("/central/fontes/smartthings/verificar",{});say("SmartThings conectado e verificado.");active="fontes";await load()}catch(err){say(err.message,true);save.disabled=false}};
    subView(()=>render());content.replaceChildren(form);token.focus();
  }
  function formAgenda(){
    const form=el("form","casa-form"),heading=el("h2","","Conectar · Google Agenda"),help=el("p","","Importe o arquivo JSON OAuth do aplicativo Google. O arquivo deve ter até 64 KB; as credenciais são protegidas localmente pelo JARVIS.");
    const file=el("input");file.type="file";file.accept=".json,application/json";file.setAttribute("aria-label","Arquivo JSON OAuth do Google Agenda");
    const foot=el("div","casa-actions"),save=button("Importar cliente",async()=>{try{const f=file.files?.[0];if(!f||f.size>64000)throw new Error("Selecione o JSON OAuth, com até 64 KB.");await request("/agenda/google/config",JSON.parse(await f.text()));file.value="";say("Cliente OAuth salvo. Agora conecte a conta.");cache.agenda=await request("/agenda/google/status")}catch(e){say(e.message,true)}}),connect=button(cache.agenda?.conectado?"Reconectar conta":"Conectar conta Google",async()=>{try{say((await request("/agenda/google/conectar",{})).mensagem||"Autorização iniciada.");cache.agenda=await request("/agenda/google/status")}catch(e){say(e.message,true)}}),cancel=button("Cancelar",()=>render());foot.append(save,connect,cancel);
    const state=el("p","casa-form-note",cache.agenda?.conectado?"Google Agenda está conectado.":cache.agenda?.configurado?"Cliente salvo · falta autorizar a conta.":"Aguardando configuração.");form.append(heading,help,file,foot,state);subView(()=>render());content.replaceChildren(form);
  }
  function formWhatsapp(){
    const form=el("form","casa-form"),heading=el("h2","","WhatsApp · importar contatos"),help=el("p","","Selecione um arquivo .VCF. Os contatos são salvos localmente no computador para os recursos de comunicação do JARVIS.");
    const file=el("input");file.type="file";file.accept=".vcf,text/vcard";file.required=true;file.setAttribute("aria-label","Arquivo de contatos VCF");
    const foot=el("div","casa-actions"),save=el("button","casa-button primary","Importar contatos"),cancel=button("Cancelar",()=>render());save.type="submit";foot.append(save,cancel);form.append(heading,help,file,foot);
    form.onsubmit=async e=>{e.preventDefault();const arquivo=file.files?.[0];if(!arquivo){say("Selecione um arquivo .VCF.",true);return}if(arquivo.size>5*1024*1024){say("O arquivo excede o limite de 5 MB.",true);return}save.disabled=true;try{const data=new FormData();data.append("arquivo",arquivo);const response=await fetch("/whatsapp/contatos/importar",{method:"POST",body:data}),result=await response.json().catch(()=>({}));if(!response.ok)throw new Error(result.erro||"Não foi possível importar os contatos.");say(`${result.mensagem} Total salvo: ${result.total}.`);cache.whatsappTotal=Number(result.total)||0;active="fontes";await load()}catch(e){say(e.message,true);save.disabled=false}};
    subView(()=>render());content.replaceChildren(form);
  }
  function renderAparelhos() {
    const intro=card(),refresh=button("Atualizar",load);intro.append(el("h2","","Dispositivos SmartThings"),el("p","","Controle individual dos aparelhos compatíveis conectados ao SmartThings."),refresh);
    const grid=el("div","casa-grid");
    for(const a of cache.aparelhos){const c=card(),top=el("div","casa-card-top"),copy=el("div",""),state=el("span",`casa-badge ${a.estado==="on"?"on":""}`,a.estado==="on"?"Ligado":"Desligado");copy.append(el("strong","",a.nome),el("small","",`${a.tipo} · ${a.id}`));top.append(copy,state);c.append(top);const b=button(a.estado==="on"?"Desligar":"Ligar",async()=>{b.disabled=true;try{await request("/central/aparelhos/acao",{id:a.id,acao:a.estado==="on"?"turn_off":"turn_on"});say(`${a.nome}: comando enviado.`);await load()}catch(e){say(e.message,true);b.disabled=false}},"primary");c.append(b);grid.append(c)}
    if(cache.erroAparelhos)grid.append(el("p","casa-empty",`Não foi possível consultar os aparelhos: ${cache.erroAparelhos}`));else if(!cache.aparelhos.length)grid.append(el("p","casa-empty","Nenhum aparelho compatível encontrado no SmartThings."));
    content.replaceChildren(intro,grid);
  }
  function dialogRotina(rotina=null) {
    const form=el("form","casa-form"),h=el("h2","",rotina?"Editar rotina":"Criar rotina"),note=el("p","","Defina o gatilho, os dias permitidos e uma sequência de ações reais. Novas rotinas começam desativadas.");
    const field=(label,placeholder,type="text")=>{const wrap=el("label","casa-field",label),i=el("input");i.placeholder=placeholder;i.type=type;wrap.append(i);return [wrap,i]};
    const [nWrap,n]=field("Nome","Ex.: Boa noite"),[descWrap,description]=field("Descrição (opcional)","O que esta rotina faz"),[pWrap,phrase]=field("Frase para ativar (opcional)","Jarvis, modo boa noite");
    const appsWrap=el("label","casa-field","Apps de notificação Android · IDs dos pacotes, separados por vírgula ou linha"),appsInput=el("textarea");
    appsInput.rows=3;appsInput.maxLength=4000;appsInput.value=(rotina?.apps_notificacao||[]).join("\n");appsWrap.append(appsInput);
    const [startWrap,start]=field("Início permitido","07:00","time"),[endWrap,end]=field("Fim permitido","22:00","time");
    n.value=rotina?.nome||"";description.value=rotina?.descricao||"";description.maxLength=500;phrase.value=rotina?.frases?.[0]||"";start.value=rotina?.inicio||"07:00";end.value=rotina?.fim||"22:00";
    const days=el("fieldset","casa-days"),legend=el("legend","","Dias permitidos");days.append(legend);const selected=[];
    for(const [i,label] of ["Seg","Ter","Qua","Qui","Sex","Sáb","Dom"].entries()){const l=el("label","casa-day",label),c=el("input");c.type="checkbox";c.checked=rotina?(rotina.dias||[]).includes(i):true;c.value=String(i);selected.push(c);l.prepend(c);days.append(l)}
    const triggerBox=el("fieldset","casa-days"),arrivalLabel=el("label","casa-day","Ao detectar chegada"),arrival=el("input"),scheduledLabel=el("label","casa-day","Executar no horário inicial"),scheduled=el("input");arrival.type=scheduled.type="checkbox";arrival.checked=rotina?.evento==="chegada";scheduled.checked=!!rotina?.agendada;arrivalLabel.prepend(arrival);scheduledLabel.prepend(scheduled);triggerBox.append(el("legend","","Gatilhos"),arrivalLabel,scheduledLabel);
    const steps=el("div","casa-step-editor"),stepHeading=el("strong","","Ações da rotina"),rows=[];
    function addStep(data=null){
      if(rows.length>=20){say("Limite de vinte ações por rotina.",true);return}
      const row=el("div","casa-step-row casa-step-card"),kind=el("select"),textInput=el("input"),apparatus=el("select"),action=el("select"),remove=button("Remover",()=>{rows.splice(rows.indexOf(entry),1);row.remove()});
      for(const [value,label] of [["falar","Falar texto"],["esperar","Esperar segundos"],["aparelho","Controlar aparelho"]]){const o=el("option","",label);o.value=value;kind.append(o)}
      textInput.placeholder="Texto que Jarvis falará";
      apparatus.append(el("option","","Escolha um aparelho"));for(const a of cache.aparelhos){const o=el("option","",`${a.nome} · ${a.id}`);o.value=a.id;apparatus.append(o)}if(data?.tipo==="aparelho"&&data.id&&!cache.aparelhos.some(a=>a.id===data.id)){const o=el("option","",data.id);o.value=data.id;apparatus.append(o)}
      for(const [value,label] of [["turn_on","Ligar"],["turn_off","Desligar"]]){const o=el("option","",label);o.value=value;action.append(o)}
      if(data){kind.value=data.tipo||"falar";textInput.value=data.tipo==="falar"?data.texto||"":data.tipo==="esperar"?String(data.segundos||""):"";apparatus.value=data.id||"";action.value=data.acao||"turn_on"}
      const extra=el("div","casa-step-extra");kind.onchange=()=>{extra.replaceChildren();if(kind.value==="falar"){textInput.type="text";textInput.placeholder="Texto que Jarvis falará";extra.append(textInput)}else if(kind.value==="esperar"){textInput.type="number";textInput.min="1";textInput.max="600";textInput.placeholder="Segundos (1–600)";extra.append(textInput)}else{extra.append(apparatus,action)}};
      const entry={row,kind,textInput,apparatus,action};rows.push(entry);row.append(kind,extra,remove);steps.append(row);kind.onchange();
    }
    const add=button("+ Adicionar ação",()=>addStep());steps.append(stepHeading,add);if(rotina?.passos?.length)rotina.passos.forEach(p=>addStep(p));else addStep();
    const actions=el("div","casa-actions"),save=el("button","casa-button primary",rotina?"Salvar alterações": "Salvar desativada"),cancel=button("Cancelar",()=>{active="rotinas";routineView="list";render()});save.type="submit";actions.append(save,cancel);form.append(h,note,nWrap,descWrap,pWrap,appsWrap,startWrap,endWrap,days,triggerBox,steps,actions);
    form.onsubmit=async e=>{e.preventDefault();if(!selected.some(x=>x.checked)){say("Escolha ao menos um dia.",true);return}if(!phrase.value.trim()&&!arrival.checked&&!scheduled.checked){say("Ative pelo menos um gatilho: frase, chegada ou horário.",true);return}
      const appsNotificacao=appsInput.value.split(/[\n,;]+/).map(app=>app.trim()).filter(Boolean);
      const passos=rows.map(row=>row.kind.value==="falar"?{tipo:"falar",texto:row.textInput.value.trim()}:row.kind.value==="esperar"?{tipo:"esperar",segundos:Number(row.textInput.value)}:{tipo:"aparelho",id:row.apparatus.value,acao:row.action.value});
      save.disabled=true;try{await request("/central/rotinas",{...(rotina||{}),nome:n.value.trim(),descricao:description.value.trim(),frases:phrase.value.trim()?[phrase.value.trim()]:[],apps_notificacao:appsNotificacao,passos,dias:selected.filter(x=>x.checked).map(x=>Number(x.value)),inicio:start.value,fim:end.value,evento:arrival.checked?"chegada":"",agendada:scheduled.checked,ativa:rotina?!!rotina.ativa:false});say(rotina?"Alterações salvas.":"Rotina salva desativada. Faça a simulação antes de ativar.");active="rotinas";await load()}catch(err){say(err.message,true);save.disabled=false}};
    subView(()=>{active="rotinas";routineView="list";render()});content.replaceChildren(form);n.focus();
  }
  function renderRotinas(){
    let importFile=document.getElementById("casa-import-rotinas");
    if(!importFile){importFile=el("input");importFile.id="casa-import-rotinas";importFile.type="file";importFile.accept="application/json,.json";importFile.hidden=true;document.body.append(importFile);importFile.onchange=async()=>{const file=importFile.files?.[0];importFile.value="";if(!file)return;if(file.size>500000){say("O arquivo excede o limite de 500 KB.",true);return}try{const parsed=JSON.parse(await file.text());const list=Array.isArray(parsed)?parsed:parsed.rotinas;if(!Array.isArray(list)||list.length!==1||!list[0]||typeof list[0]!=="object"||Array.isArray(list[0]))throw new Error("Cada arquivo precisa conter exatamente uma rotina.");for(const item of list){const {id,versao,schema_version,atualizada_em,execucao,...dados}=item||{};await request("/central/rotinas",{...dados,ativa:false})}say(list.length+" rotina(s) importada(s) desativada(s).");await load()}catch(e){say("Importação não concluída: "+e.message,true)}}}
    const intro=card(),create=button("+ Nova rotina",()=>dialogRotina(),"primary"),importBtn=button("Importar JSON",()=>importFile.click()),refresh=button("Atualizar lista",load),stop=button("■ Parar execuções",async()=>{try{await request("/central/rotinas/cancelar",{});say("Rotinas em execução canceladas.")}catch(e){say(e.message,true)}}),toolbar=el("div","casa-actions");toolbar.append(create,importBtn,refresh,stop);intro.append(el("h2","","ROTINAS"),el("p","","Automation Control Center · configure frases, gatilhos e ações reais do JARVIS."),toolbar);
    const routineTabs=el("nav","casa-routine-tabs");
    const tab=(label,view)=>{const b=button(label,()=>{routineView=view;renderRotinas()});b.classList.toggle("selected",routineView===view);b.setAttribute("aria-current",routineView===view?"page":"false");routineTabs.append(b)};
    tab("Minhas rotinas","list");
    routineTabs.append(button("Editor",()=>dialogRotina()));
    tab("Eventos de rotina · hoje","history");
    if(routineView==="history"){
      const history=card();
      const heading=el("h2","","Eventos de rotina · hoje");
      const description=el("p","","Eventos reais de chegada e saída registrados pelo JARVIS.");
      history.append(heading,description,el("p","casa-empty","Carregando eventos…"));
      content.replaceChildren(intro,routineTabs,history);
      request("/rotina-historico").then(events=>{
        history.replaceChildren(el("h2","","Eventos de rotina · hoje"),el("p","","Eventos reais de chegada e saída registrados pelo JARVIS."));
        if(!Array.isArray(events)||!events.length){history.append(el("p","casa-empty","Nenhum evento de chegada ou saída registrado hoje."));return}
        for(const event of events.slice().reverse()){
          const row=el("article","casa-history-row"),date=new Date(event.hora);
          const time=Number.isNaN(date.getTime())?"Horário indisponível":date.toLocaleString("pt-BR");
          const label=event.tipo==="chegada"?"Chegada detectada":event.tipo==="saida"?"Saída detectada":"Evento";
          row.append(el("strong","",label),el("small","",time+" · origem: "+(event.origem||"sistema")));
          if(event.mensagem)row.append(el("p","",event.mensagem));
          history.append(row);
        }
      }).catch(error=>{history.replaceChildren(el("h2","","Eventos de rotina · hoje"),el("p","casa-empty","Não foi possível consultar o histórico: "+error.message))});
      return;
    }
    const grid=el("div","casa-grid");
    for(const r of cache.rotinas){const c=card(),top=el("div","casa-card-top"),copy=el("div",""),toggle=el("input");toggle.type="checkbox";toggle.checked=!!r.ativa;toggle.setAttribute("aria-label","Ativar rotina");copy.append(el("strong","",r.nome),el("small","",[r.frases?.length?`Frase: ${r.frases.join(" · ")}`:null,r.evento==="chegada"?"Chegada":null,r.agendada?`Horário ${r.inicio}`:null].filter(Boolean).join(" · ")||`Janela ${r.inicio}–${r.fim}`));top.append(copy,toggle);c.append(top,el("p","",`${r.passos.length} ação(ões) · ${r.execucao?.estado||"pronta"}`));
      const exportar=button("Exportar JSON",()=>{const {id,versao,schema_version,atualizada_em,execucao,...dados}=r;const blob=new Blob([JSON.stringify({schema_version:1,rotinas:[{...dados,ativa:false}]},null,2)],{type:"application/json"});const url=URL.createObjectURL(blob),a=el("a");a.href=url;a.download=(r.nome||"rotina").normalize("NFKD").replace(/[^a-zA-Z0-9_-]+/g,"-").slice(0,60)+".json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}),controls=el("div","casa-actions"),edit=button("Editar",()=>dialogRotina(r)),duplicate=button("Duplicar",()=>dialogRotina({...r,id:undefined,versao:undefined,schema_version:undefined,atualizada_em:undefined,ativa:false,nome:r.nome+" (cópia)"})),sim=button("Simular",async()=>{try{const x=await request(`/central/rotinas/${r.id}/executar`,{simular:true});say(`Simulação: ${x.passos.length} passo(s), ${x.permitida_agora?"dentro":"fora"} da janela permitida. Nenhuma ação foi executada.`)}catch(e){say(e.message,true)}}),run=button("Executar",async()=>{try{const x=await request(`/central/rotinas/${r.id}/executar`,{simular:false});say(x.iniciada?`Rotina ${x.nome} iniciada.`:"Rotina iniciada.")}catch(e){say(e.message,true)}} ,"primary"),del=button("Excluir",async()=>{try{await request(`/central/rotinas/${r.id}`,null,"DELETE");say("Rotina excluída.");await load()}catch(e){say(e.message,true)}});run.disabled=!r.ativa;toggle.onchange=async()=>{try{await request("/central/rotinas",{...r,ativa:toggle.checked});say(toggle.checked?"Rotina ativada.":"Rotina desativada.");await load()}catch(e){toggle.checked=!toggle.checked;say(e.message,true)}};controls.append(edit,duplicate,exportar,sim,run,del);c.append(controls);grid.append(c)}
    if(!cache.rotinas.length)grid.append(el("p","casa-empty","Nenhuma rotina. Crie uma; ela começará desativada."));content.replaceChildren(intro,routineTabs,grid);
  }
  function render(){renderTabs();say("");if(active==="fontes")renderFontes();else if(active==="aparelhos")renderAparelhos();else renderRotinas()}
  async function load(){say("Atualizando central…");try{const [f,a,r,d,g,w]=await Promise.all([request("/central/fontes"),request("/central/aparelhos").catch(e=>({aparelhos:[],erro:e.message})),request("/central/rotinas"),request("/interface/dashboard").catch(()=>null),request("/agenda/google/status").catch(()=>null),request("/whatsapp/contatos/estado").catch(()=>({total:0}))]);cache={fontes:f.fontes||[],aparelhos:a.aparelhos||[],erroAparelhos:a.erro||"",rotinas:r.rotinas||[],dashboard:d,agenda:g,whatsappTotal:Number(w?.total)||0};render()}catch(e){say(e.message,true)}}
  window.openJarvisCasa=(tab="fontes")=>{active=actions.some(([id])=>id===tab)?tab:"fontes";tabHistory=[];routineView="list";content.scrollTop=0;dialog.scrollTop=0;dialog.showModal();load()};
})();
