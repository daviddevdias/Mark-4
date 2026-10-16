(() => {
    "use strict";
    const labels={camera_live:"Câmera ao vivo",security:"Torre Stark",detections:"Últimas detecções",clock:"Relógio",weather:"Clima",agenda:"Agenda",system:"Sistema",email:"E-mails",mobile:"Notificações do celular"};
    const screenPage=document.body.classList.contains("widget-screen"),qt=["qt","native"].includes(new URLSearchParams(location.search).get("embutido"));
    let config=null,currentId=screenPage?new URLSearchParams(location.search).get("tela"):"principal",editor=null,refreshing=false,timer=null,noticeTimer=null,dragging=false,queue=Promise.resolve();
    let cameraCard=null,creating=false,undoLayout=null;
    let locked=localStorage.getItem("jarvis-layout-lock:"+currentId)==="true";
    document.body.classList.toggle("layout-locked",locked);
    const remember=()=>{undoLayout={widgets:structuredClone(selectedScreen()?.widgets||[]),revision:config?.revisao};};
    async function undo(){if(!undoLayout){notice("Nenhuma alteração para desfazer nesta janela.");return}try{await edit({acao:"layout",id:currentId,widgets:undoLayout.widgets,revisao:undoLayout.revision},false);undoLayout=null;render();notice("Layout restaurado.")}catch(e){notice(e.message)}}
    function toggleLock(){locked=!locked;localStorage.setItem("jarvis-layout-lock:"+currentId,String(locked));document.body.classList.toggle("layout-locked",locked);notice(locked?"Posições travadas. Os cards continuam funcionando.":"Posições liberadas.");closeEditor()}

    if(!screenPage){const grid=node("main","widget-grid principal-widgets");grid.id="widgetGrid";grid.setAttribute("aria-label","Elementos da tela principal");document.body.append(grid)}
    // Reabre segunda tela salva
    function secondaryScreens(){const telas=config?.telas||[];const t=telas.find(t=>t.id===config.ultima_tela)||[...telas].reverse().find(t=>t.widgets.length)||telas[telas.length-1];return t?[t]:[]}
    function selectedScreen(){return currentId==="principal"?config?.principal:config?.telas.find(t=>t.id===currentId)}
    const cache=new Map(),nodes=new Map(),transfers=new Map(),channel=typeof BroadcastChannel!=="undefined"?new BroadcastChannel("jarvis-telas"):null;
    // Cria elemento sem HTML externo
    function node(tag,cls,text){const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n}
    // Consulta API com prazo limitado
    async function api(url,data){const c=new AbortController(),timeout=setTimeout(()=>c.abort(),10000);try{const r=await fetch(url,{signal:c.signal,...(data?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)}:{})});const v=await r.json();if(!r.ok)throw new Error(v.erro||"Informação indisponível");return v}finally{clearTimeout(timeout)}}
    // Reutiliza consultas dos widgets
    function get(url,ttl=30000){let value=cache.get(url);if(!value||Date.now()-value.at>=ttl){value={at:Date.now(),promise:api(url).catch(e=>{cache.delete(url);throw e})};cache.set(url,value)}return value.promise}
    // Expira aviso fora da conversa
    function notice(text){let n=document.getElementById("screenNotice");if(!n){n=node("div","","");n.id="screenNotice";n.setAttribute("role","status");document.body.append(n)}n.textContent=text;clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>n.textContent="",3500)}
    // Salva cada alteração em sequência
    function edit(payload,track=true){
        let revisionBefore;const run=queue.then(()=>{revisionBefore=config?.revisao;document.body.dataset.layoutSave="saving";return api("/interface/telas/editar",payload)}).then(result=>{config=result.perfil;if(track&&undoLayout){if(config.revisao===revisionBefore+1)undoLayout.revision=config.revisao;else undoLayout=null;}document.body.dataset.layoutSave="saved";channel?.postMessage(config.revisao);return result});
        queue=run.catch(e=>{document.body.dataset.layoutSave="error";notice(e.message)});return run;
    }
    // Abre janela sem duplicar escuta
    async function openScreen(id){if(qt){try{await api("/interface/telas/abrir",{id})}catch(e){notice(e.message)}}else if(screenPage){location.href=id==="principal"?"/painel":"/telas?tela="+encodeURIComponent(id)}else{const win=window.open(id==="principal"?"/painel":"/telas?tela="+encodeURIComponent(id),"jarvis-"+id);if(!win)notice("Permita abrir a janela desta tela.")}}
    // Cria tela sem peças iniciais
    async function createScreen(){if(creating)return;creating=true;let win=!qt?window.open("about:blank","jarvis-segunda-tela"):null;try{const result=await edit({acao:"criar"});navigation();if(qt)await openScreen(result.id);else if(win)win.location.href="/telas?tela="+encodeURIComponent(result.id);else notice("Tela criada. Abra pelo menu Telas.")}catch(e){win?.close();notice(e.message)}finally{creating=false}}
    // Monta menu inferior esquerdo
    function navigation(){if(document.getElementById("screenBar"))return;const bar=node("nav","screen-bar");bar.id="screenBar";bar.setAttribute("aria-label",screenPage?"Organizar tela":"Menu do Jarvis");const b=node("button","screen-tab",screenPage?"Organizar":"☰");b.setAttribute("aria-label",screenPage?"Organizar elementos":"Abrir menu");b.onclick=mainMenu;bar.append(b);document.body.append(bar)}
    if (screenPage) window.openJarvisPairing = async () => { await openScreen("principal"); channel?.postMessage({ pairing: true }); };
    // Reúne navegação e ferramentas sem alterar a tela principal.
    function mainMenu() {
        closeEditor();
        editor = node("aside", "screen-palette main-menu mark3-menu");
        editor.setAttribute("aria-label", "Navegação JARVIS Mark III");
        const brand = node("div", "mark3-menu-brand");
        const brandCopy = node("div", "");
        brandCopy.append(node("strong", "", "J.A.R.V.I.S."), node("span", "", "MARK III · CONTROL CENTER"));
        const closeMenu = node("button", "mark3-menu-close", "×");
        closeMenu.type = "button";
        closeMenu.setAttribute("aria-label", "Fechar menu");
        closeMenu.onclick = closeEditor;
        brand.append(brandCopy, closeMenu);
        editor.append(brand);

        const group = (label) => {
            const section = node("section", "mark3-menu-group");
            section.append(node("h2", "", label));
            editor.append(section);
            return section;
        };
        const nav = group("CENTRAL DE CONTROLE");
        const item = (host, label, icon, action, current = false) => {
            const b = node("button", "screen-tab mark3-nav-item" + (current ? " on" : ""));
            b.type = "button";
            b.setAttribute("aria-current", current ? "page" : "false");
            const glyph = node("span", "mark3-nav-icon", icon);
            glyph.setAttribute("aria-hidden", "true");
            b.append(glyph, node("span", "", label));
            b.onclick = action;
            host.append(b);
            return b;
        };
        const go = (action) => () => { closeEditor(); action?.(); };
        item(nav, "Dashboard", "⌂", go(() => { if (screenPage) openScreen("principal"); }), !screenPage);
        item(nav, "Rotinas", "◇", go(() => window.openJarvisCasa?.("rotinas")));
        item(nav, "Torre Stark", "⬡", go(() => window.openJarvisSection?.("seg")));
        item(nav, "Dispositivos", "⌘", go(() => window.openJarvisCasa?.("aparelhos")));
        item(nav, "Pessoal", "◷", go(() => window.openJarvisSection?.("org")));
        item(nav, "Comandos", "⌁", go(() => window.openJarvisSection?.("cmd")));
        item(nav, "Configurações", "⚙", go(() => window.openJarvisSection?.("cfg")));

        const tools = group("ÁREAS E FERRAMENTAS");
        item(tools, "Meu dia", "◷", go(() => window.openDailyBriefing?.()));
        item(tools, locked ? "Destravar posições" : "Travar posições", "⠿", toggleLock);
        item(tools, "Desfazer layout", "↶", undo);
        item(tools, "Elementos", "▦", customize);
        item(tools, "Organizar", "⠿", tidy);
        item(tools, "Nova tela", "+", createScreen);

        const services = group("SERVIÇOS");
        const android = item(services, "Android · consultando", "⌁", go(() => window.openJarvisPairing?.()));
        android.classList.add("mark3-service");
        android.dataset.state = "unknown";
        let alive = true;
        const refreshAndroid = async () => {
            try {
                const response = await fetch("/interface/dashboard", { cache: "no-store" });
                if (!response.ok) throw new Error("offline");
                const data = await response.json();
                const connected = !!data.celular?.conectado;
                android.dataset.state = connected ? "on" : "off";
                android.lastElementChild.textContent = "Android · " + (connected ? "Conectado" : "Desconectado");
            } catch (_) {
                android.dataset.state = "unknown";
                android.lastElementChild.textContent = "Android · sem dados";
            }
            if (alive && editor?.isConnected)
                editor._androidTimer = setTimeout(refreshAndroid, 15000);
        };
        refreshAndroid();
        editor._cleanup = () => { alive = false; clearTimeout(editor._androidTimer); };

        document.body.append(editor);
    }
    // Fecha painel sem cobrir a tela
    function closeEditor(){editor?._cleanup?.();editor?.remove();editor=null}
    // Abre lista das telas existentes
    function screenList(){closeEditor();editor=node("aside","screen-palette");editor.append(node("strong","","Suas telas"));const close=node("button","screen-tab","Fechar");close.onclick=closeEditor;editor.append(close);if(!config.telas.length)editor.append(node("p","","Crie uma tela vazia em + Tela."));for(const t of secondaryScreens()){const row=node("div","screen-row"),b=node("button","screen-tab",t.nome),x=node("button","screen-tab screen-del","×");b.onclick=()=>openScreen(t.id);x.title="Excluir tela";x.setAttribute("aria-label","Excluir "+t.nome);let armed=null;x.onclick=async()=>{if(!armed){x.textContent="Excluir?";x.classList.add("armed");armed=setTimeout(()=>{armed=null;x.textContent="×";x.classList.remove("armed")},3000);return}clearTimeout(armed);x.disabled=true;try{await edit({acao:"remover",id:t.id});render();screenList();notice("Tela excluída.")}catch(e){notice(e.message);x.disabled=false}};row.append(b,x);editor.append(row)}document.body.append(editor)}
    // Posiciona peça pelo tamanho salvo
    function place(box,w){Object.assign(box.style,{left:w.x+"px",top:w.y+"px",width:Math.min(720,w.w)+"px",height:Math.min(560,w.h)+"px"})}
    // Amplia área para acomodar peças
    function extent(){const grid=document.getElementById("widgetGrid");if(!grid)return;grid.style.width="100%";grid.style.height="100%"}
    // Move ou redimensiona sem saltos
    function gesture(event,box,w,resize){if(locked)return;if(event.button!==0||(!resize&&event.target.closest("button,select")))return;event.preventDefault();remember();const handle=event.currentTarget,start={...w},x=event.clientX,y=event.clientY,rect=box.getBoundingClientRect(),grab={gx:x-rect.left,gy:y-rect.top};dragging=true;box.classList.add("selected");handle.setPointerCapture(event.pointerId);let frame=null,dock=null;
        const showDock=()=>{if(dock||resize||!config)return;const targets=destinations();if(!targets.length)return;dock=node("div","move-dock");dock.append(node("span","","Solte aqui para mover para:"));for(const t of targets){const d=node("div","move-dock-item",t.nome);d.dataset.id=t.id;dock.append(d)}document.body.append(dock)};
        const hover=e=>{if(!dock)return;const hit=document.elementFromPoint(e.clientX,e.clientY)?.closest(".move-dock-item");for(const d of dock.children)d.classList.toggle("on",d===hit)};
        const move=e=>{showDock();hover(e);const dx=Math.round(e.clientX-x),dy=Math.round(e.clientY-y);if(resize){w.w=Math.max(240,Math.min(720,innerWidth-w.x,start.w+dx));w.h=Math.max(140,Math.min(560,innerHeight-w.y,start.h+dy))}else{w.x=Math.max(0,Math.min(8192,innerWidth-w.w,start.x+dx));w.y=Math.max(0,Math.min(8192,innerHeight-w.h,start.y+dy))}{const g=e.altKey?null:snapTo(w,resize);guides(g)}if(!frame)frame=requestAnimationFrame(()=>{frame=null;place(box,w)})};
        const end=async e=>{const target=e&&e.type==="pointerup"&&!resize?dock?.querySelector(".move-dock-item.on")?.dataset.id:null;dock?.remove();dock=null;box.classList.remove("selected");guides(null);handle.removeEventListener("pointermove",move);handle.removeEventListener("pointerup",end);handle.removeEventListener("pointercancel",end);if(frame)cancelAnimationFrame(frame);if(target){Object.assign(w,start);place(box,w);dragging=false;extent();await moveTo(target,w);return}if(!resize&&e&&e.type==="pointerup"&&(e.clientX<0||e.clientY<0||e.clientX>innerWidth||e.clientY>innerHeight)){Object.assign(w,start);place(box,w);dragging=false;extent();handOff(w,{sx:e.screenX,sy:e.screenY,...grab});return}place(box,w);dragging=false;extent();try{await edit({acao:"peca",id:currentId,widget:{...w}})}catch(_){Object.assign(w,start);place(box,w)}};
        handle.addEventListener("pointermove",move);handle.addEventListener("pointerup",end);handle.addEventListener("pointercancel",end)}
    // Adiciona peça onde foi solta
    async function add(key,x=32,y=32){if(!labels[key]||locked){notice("Destrave as posições para adicionar elementos.");return}remember();const t=selectedScreen();if(!t){notice("Crie ou abra uma tela primeiro.");return}if(t.widgets.some(w=>w.tipo===key)){notice("Este elemento já está nesta tela.");return}try{await edit({acao:"peca",id:currentId,widget:{tipo:key,x:Math.max(0,Math.min(8192,Math.round(x))),y:Math.max(0,Math.min(8192,Math.round(y))),w:key==="mobile"?300:360,h:({mobile:220,system:320,clock:320,weather:240,security:270})[key]||280}});render()}catch(e){notice(e.message)}}
    // Desenha somente peças escolhidas
    function render(){navigation();const selected=selectedScreen();const grid=document.getElementById("widgetGrid");const wanted=new Set((selected?.widgets||[]).map(w=>w.tipo));for(const box of grid.querySelectorAll(".screen-widget")){if(wanted.has(box.dataset.tipo))continue;const content=nodes.get(box.dataset.tipo);if(content?._clock){clearInterval(content._clock);live.delete(content._clock)}if(box.dataset.tipo==="camera_live"){cameraCard?.destroy();cameraCard=null}nodes.delete(box.dataset.tipo);box.remove()}grid.querySelector(".screen-empty")?.remove();if(!selected){grid.append(node("p","screen-empty","Crie uma tela no menu inferior esquerdo."));return}if(screenPage)document.title="Jarvis · "+selected.nome;document.body.dataset.tema=selected.tema||"classico";for(const data of selected.widgets){const existing=nodes.get(data.tipo)?.closest(".screen-widget");if(existing){Object.assign(existing._widget,data);selected.widgets[selected.widgets.indexOf(data)]=existing._widget;place(existing,existing._widget);continue}const w=data;const box=node("section","screen-widget");box._widget=w;box.dataset.tipo=w.tipo;{const k=currentId+":"+w.tipo;if(!seen.has(k)){seen.add(k);box.classList.add("mac-enter");box.style.setProperty("--n",String(selected.widgets.indexOf(w)))}}place(box,w);const header=node("header","widget-heading");header.append(node("strong","",labels[w.tipo]));const remove=node("button","widget-remove","×");remove.setAttribute("aria-label","Retirar "+labels[w.tipo]);remove.onclick=async()=>{if(locked)return;remember();try{await edit({acao:"retirar",id:currentId,tipo:w.tipo});seen.delete(currentId+":"+w.tipo);render()}catch(e){notice(e.message)}};const mover=node("button","widget-remove widget-move","⇄");mover.setAttribute("aria-label","Mover "+labels[w.tipo]+" para outra tela");mover.title="Mover para outra tela";mover.onclick=()=>moveMenu(w);const sizes=node("select","widget-sizes");sizes.setAttribute("aria-label","Tamanho de "+labels[w.tipo]);
        for(const [value,label] of [["","Tamanho"],["300,240","P"],["360,300","M"],["540,420","G"]]){const option=node("option","",label);option.value=value;sizes.append(option)}
        sizes.onchange=async()=>{if(locked||!sizes.value)return;remember();const [width,height]=sizes.value.split(",").map(Number);const old={...w};w.w=Math.min(width,Math.max(240,innerWidth));w.h=height;w.x=Math.max(0,Math.min(w.x,innerWidth-w.w));place(box,w);try{await edit({acao:"peca",id:currentId,widget:{...w}})}catch(_){Object.assign(w,old);place(box,w)}sizes.value=""};header.append(sizes,mover,remove);header.onpointerdown=e=>gesture(e,box,w,false);const content=node("div","widget-content","Consultando…"),resize=node("button","widget-resize","◢");resize.setAttribute("aria-label","Redimensionar "+labels[w.tipo]);resize.onpointerdown=e=>{e.stopPropagation();gesture(e,box,w,true)};resize.onkeydown=e=>{if(locked)return;if(!["ArrowLeft","ArrowRight","ArrowUp","ArrowDown"].includes(e.key))return;e.preventDefault();remember();w.w=Math.max(240,Math.min(720,w.w+(e.key==="ArrowRight"?10:e.key==="ArrowLeft"?-10:0)));w.h=Math.max(140,Math.min(560,w.h+(e.key==="ArrowDown"?10:e.key==="ArrowUp"?-10:0)));place(box,w);edit({acao:"peca",id:currentId,widget:{...w}}).catch(()=>{})};box.append(header,content,resize);grid.append(box);nodes.set(w.tipo,content);if(w.tipo==="camera_live")cameraCard=window.createJarvisCameraCard(content)}extent();refresh()}
    // Escolhe peças e ajustes da tela
    function customize(){if(!config)return;closeEditor();editor=node("aside","screen-palette");const title=node("strong","","Elementos da tela"),close=node("button","screen-tab","Fechar");close.onclick=closeEditor;editor.append(title,close);const t=selectedScreen();if(screenPage&&t){const name=node("input");name.value=t.nome;name.maxLength=40;name.setAttribute("aria-label","Nome da tela");name.onchange=()=>edit({acao:"nome",id:currentId,nome:name.value}).then(()=>document.title="Jarvis · "+name.value).catch(()=>{});editor.append(name,node("p","editor-note","Arraste para o espaço livre. Mova pelo título e ajuste o tamanho pelo canto."))}else editor.append(node("p","editor-note","Adicione ou arraste elementos para a tela principal."));for(const [key,label] of Object.entries(labels)){const b=node("button","screen-tab palette-item",label);b.draggable=true;b.dataset.tipo=key;b.ondragstart=e=>{document.body.classList.add("widget-dragging");e.dataTransfer.effectAllowed="copy";e.dataTransfer.setData("text/plain",JSON.stringify({jarvisElement:key}))};b.onclick=()=>add(key,screenPage?Math.max(32,scrollX+32):Math.min(320,Math.max(16,innerWidth-376)),screenPage?Math.max(32,scrollY+32):120);editor.append(b)}if(screenPage&&t){const del=node("button","screen-tab","Excluir esta tela");del.onclick=async()=>{try{await edit({acao:"remover",id:currentId});closeEditor();render()}catch(e){notice(e.message)}};editor.append(del)}document.body.append(editor)}
    // Atualiza texto sem reconstruir tudo
    function lines(key,texts){const target=nodes.get(key);if(!target)return;const sig=JSON.stringify(texts);if(target.dataset.signature===sig)return;target.dataset.signature=sig;delete target.dataset.view;target.replaceChildren(...texts.map(t=>node("p","widget-line",String(t??"—"))))}
    // Desenha notícias com fonte original
    async function news(key){const politics=key==="news_politics",data=await get("/noticias/g1?categoria="+(politics?"politica":"tecnologia"),300000);let items=data.noticias||[];if(key==="news_ia")items=items.filter(n=>/intelig[eê]ncia artificial|\bia\b|openai|modelo|chatgpt|gemini|claude/i.test(n.titulo+" "+n.resumo));const target=nodes.get(key);if(!target)return;const sig=JSON.stringify(items.slice(0,3));if(target.dataset.signature===sig)return;target.dataset.signature=sig;target.replaceChildren();if(!items.length){target.append(node("p","widget-line",key==="news_ia"?"Nenhuma notícia de IA no feed de tecnologia agora.":"Nenhuma notícia disponível."));return}for(const n of items.slice(0,3)){const article=node("article","widget-news");if(n.imagem){const img=node("img");img.src=n.imagem;img.alt="";img.loading="lazy";img.onerror=()=>img.remove();article.append(img)}let parsed;try{parsed=new URL(n.url)}catch(_){}const title=node(parsed&&parsed.protocol==="https:"?"a":"strong","",n.titulo);if(title.tagName==="A"){title.href=parsed.href;title.target="_blank";title.rel="noopener noreferrer"}article.append(title);if(n.resumo)article.append(node("p","",n.resumo));target.append(article)}target.append(node("small","widget-source","Fonte: G1"+(key==="news_ia"?" · filtro de IA":"")));}
    

    
    
    function handOff(w,info){
        if(!channel){notice("Use o botão ⇄ do elemento para mover para outra tela.");return}
        const id=Math.random().toString(36).slice(2),from=currentId,tipo=w.tipo;
        const timer=setTimeout(()=>{transfers.delete(id);notice("Solte o elemento sobre outra tela do Jarvis ou use o botão ⇄.")},1500);
        transfers.set(id,{
            ok:async()=>{clearTimeout(timer);transfers.delete(id);try{await edit({acao:"retirar",id:from,tipo});seen.delete(from+":"+tipo);render()}catch(e){notice(e.message)}},
            fail:motivo=>{clearTimeout(timer);transfers.delete(id);notice(motivo||"Não foi possível mover.")}
        });
        channel.postMessage({mover:id,tipo,w:w.w,h:w.h,sx:info.sx,sy:info.sy,gx:info.gx,gy:info.gy})
    }
    
    async function receive(m){
        if(document.hidden||!config||!labels[m.tipo])return;
        const bx=(outerWidth-innerWidth)/2,cx=m.sx-(screenX+bx),cy=m.sy-(screenY+outerHeight-innerHeight-bx);
        if(cx<0||cy<0||cx>innerWidth||cy>innerHeight)return;
        const t=selectedScreen();if(!t)return;
        if(t.widgets.some(w=>w.tipo===m.tipo)){channel.postMessage({recusado:m.mover,motivo:"Este elemento já está nesta tela."});return}
        const ww=Math.max(240,Math.min(m.w,innerWidth)),hh=Math.max(140,Math.min(m.h,innerHeight));
        const x=Math.max(0,Math.min(innerWidth-ww,Math.round(cx-m.gx))),y=Math.max(0,Math.min(innerHeight-hh,Math.round(cy-m.gy)));
        try{await edit({acao:"peca",id:currentId,widget:{tipo:m.tipo,x,y,w:ww,h:hh}});render();channel.postMessage({aceito:m.mover})}
        catch(e){channel.postMessage({recusado:m.mover,motivo:e.message})}
    }
    // Telas que podem receber o elemento
    function destinations(){return[{id:"principal",nome:"Principal",widgets:config.principal.widgets},...secondaryScreens()].filter(t=>t.id!==currentId)}
    
    async function moveTo(targetId,w){
        const t=destinations().find(d=>d.id===targetId);if(!t)return false;
        if(t.widgets.some(o=>o.tipo===w.tipo)){notice("Este elemento já está em "+t.nome+".");return false}
        try{
            const n=t.widgets.length;
            await edit({acao:"peca",id:t.id,widget:{tipo:w.tipo,x:24+n*24,y:(t.id==="principal"?112:24)+n*24,w:w.w,h:w.h}});
            await edit({acao:"retirar",id:currentId,tipo:w.tipo});
            seen.delete(currentId+":"+w.tipo);closeEditor();render();notice("Movido para "+t.nome+".");return true
        }catch(e){notice(e.message);return false}
    }
    
    function moveMenu(w){
        closeEditor();editor=node("aside","screen-palette");editor.append(node("strong","","Mover "+labels[w.tipo]+" para"));
        const close=node("button","screen-tab","Fechar");close.onclick=closeEditor;editor.append(close);
        const targets=destinations();
        if(!targets.length)editor.append(node("p","","Crie outra tela em + Tela."));
        for(const t of targets){const b=node("button","screen-tab",t.nome);b.onclick=async()=>{b.disabled=true;if(!await moveTo(t.id,w))b.disabled=false};editor.append(b)}
        document.body.append(editor)
    }
    
    const SNAP=10;
    
    function snapTo(w,resize){
        const others=(selectedScreen()?.widgets||[]).filter(o=>o.tipo!==w.tipo),xs=[24],ys=[24];
        for(const o of others){xs.push(o.x,o.x+o.w);ys.push(o.y,o.y+o.h)}
        const near=(vals,lines)=>{let best=null;for(const v of vals)for(const l of lines){const d=l-v;if(Math.abs(d)<=SNAP&&(!best||Math.abs(d)<Math.abs(best.d)))best={d,line:l}}return best};
        const same=(v,key)=>others.find(o=>o[key]!==v&&Math.abs(o[key]-v)<=SNAP);
        let gx=null,gy=null;
        if(resize){
            const bx=near([w.x+w.w],xs),by=near([w.y+w.h],ys);
            if(bx){w.w+=bx.d;gx=bx.line}else{const m=same(w.w,"w");if(m)w.w=m.w}
            if(by){w.h+=by.d;gy=by.line}else{const m=same(w.h,"h");if(m)w.h=m.h}
            w.w=Math.max(240,w.w);w.h=Math.max(140,w.h)
        }else{
            const bx=near([w.x,w.x+w.w],xs),by=near([w.y,w.y+w.h],ys);
            if(bx){w.x+=bx.d;gx=bx.line}
            if(by){w.y+=by.d;gy=by.line}
            w.x=Math.max(0,w.x);w.y=Math.max(0,w.y)
        }
        return{gx,gy}
    }
    // Linhas-guia do alinhamento
    function guides(g){
        const grid=document.getElementById("widgetGrid");if(!grid)return;
        for(const [cls,pos,prop] of [["v",g?.gx,"left"],["h",g?.gy,"top"]]){
            let n=grid.querySelector(".snap-guide."+cls);
            if(pos==null){n?.remove();continue}
            if(!n){n=node("i","snap-guide "+cls);grid.append(n)}
            n.style[prop]=pos+"px"
        }
    }
    
    async function tidy(){
        if(locked){notice("Destrave as posições para organizar.");return}remember();
        const t=selectedScreen();
        if(!t||t.widgets.length<2){notice("Adicione ao menos dois elementos para organizar.");return}
        const gap=16,left=24,top=screenPage?24:112,right=(screenPage||innerWidth<=1100?innerWidth:innerWidth-420)-24;
        const items=t.widgets.map(w=>({...w})).sort((a,b)=>a.y-b.y||a.x-b.x),groups=[];
        for(const w of items){w.w=Math.max(240,Math.min(w.w,right-left));const g=groups[groups.length-1];if(g&&Math.abs(w.y-g[0].y)<=60)g.push(w);else groups.push([w])}
        let y=top;
        for(const group of groups){
            group.sort((a,b)=>a.x-b.x);
            let x=left,h=0,line=[];
            const flush=()=>{for(const w of line)w.h=h;y+=h+gap;line=[];x=left;h=0};
            for(const w of group){if(line.length&&x+w.w>right)flush();w.x=x;w.y=y;x+=w.w+gap;h=Math.max(h,w.h);line.push(w)}
            flush()
        }
        const grid=document.getElementById("widgetGrid");grid.classList.add("mac-tidy");
        for(const w of items){const box=grid.querySelector('[data-tipo="'+w.tipo+'"]');if(box)place(box,w)}
        try{for(const w of items)await edit({acao:"peca",id:currentId,widget:{tipo:w.tipo,x:w.x,y:w.y,w:w.w,h:w.h}})}catch(e){notice(e.message)}
        await new Promise(r=>setTimeout(r,650));
        grid.classList.remove("mac-tidy");render();notice("Elementos organizados.")
    }
    
    const NS="http://www.w3.org/2000/svg",CIRC=2*Math.PI*40,COLORS=["#0a84ff","#30d158","#000000","#ff453a","#bf5af2"],live=new Set(),seen=new Set();
    const plain=s=>String(s??"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase();
    // Cria elemento SVG sem HTML externo
    function sv(parent,tag,attrs={}){const n=document.createElementNS(NS,tag);for(const k in attrs)n.setAttribute(k,attrs[k]);parent.append(n);return n}
    
    function built(key,name,build){const t=nodes.get(key);if(!t)return null;if(t.dataset.view!==name){clearInterval(t._clock);t.replaceChildren();t.dataset.view=name;delete t.dataset.signature;build(t)}return t}
    
    function rows(key,items,empty){
        const t=nodes.get(key);if(!t)return;
        const sig=JSON.stringify([items,empty]);
        if(t.dataset.signature===sig&&t.dataset.view==="rows")return;
        t.dataset.signature=sig;t.dataset.view="rows";t.replaceChildren();
        const list=node("div","mac-rows");
        if(!items.length)list.append(node("p","mac-empty",empty));
        items.forEach((it,i)=>{
            const row=node("div","mac-row"+(it.avatar?" has-avatar":""));
            row.style.setProperty("--i",String(i));row.style.setProperty("--c",it.color||COLORS[i%COLORS.length]);
            if(it.avatar){const a=node("span","mac-avatar",it.avatar);let h=0;for(const c of it.title||"")h=(h*31+c.charCodeAt(0))%360;a.style.background="hsl("+h+" 55% 46%)";row.append(a)}
            else if(it.lead)row.append(node("span","mac-lead",it.lead));
            const copy=node("div","mac-copy"),title=node(it.href?"a":"strong","",it.title||"");
            if(it.href){title.href=it.href;title.target="_blank";title.rel="noopener noreferrer";title.setAttribute("aria-label","Abrir e-mail no Gmail: "+(it.title||"Sem assunto"))}
            if(it.onClick){row.classList.add("actionable-row");row.onclick=e=>{if(!e.target.closest("a,button,[role=button]"))it.onClick()};title.onclick=it.onClick;title.tabIndex=0;title.setAttribute("role","button");title.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();it.onClick()}}}
            copy.append(title);if(it.sub)copy.append(node("span","",it.sub));if(it.preview)copy.append(node("p","mail-preview",it.preview));
            row.append(copy);list.append(row)
        });
        t.append(list)
    }
    
    function clockWidget(){
        built("clock","clock",box=>{
            const wrap=node("div","mac-clock"),face=sv(wrap,"svg",{viewBox:"0 0 200 200",class:"mac-clock-face"}),date=node("div","mac-clock-date");
            for(let i=0;i<60;i++){const a=i*Math.PI/30,hr=i%5===0,r1=hr?86:90,r2=95;sv(face,"line",{x1:100+Math.sin(a)*r1,y1:100-Math.cos(a)*r1,x2:100+Math.sin(a)*r2,y2:100-Math.cos(a)*r2,class:"mac-tick"+(hr?" hr":"")})}
            for(let i=1;i<=12;i++){const a=i*Math.PI/6,n=sv(face,"text",{x:100+Math.sin(a)*70,y:100-Math.cos(a)*70,class:"mac-num"});n.textContent=String(i)}
            const hand=(cls,y1,y2)=>{const g=sv(face,"g",{class:"mac-hand-g "+cls});sv(g,"line",{x1:100,y1,x2:100,y2,class:"mac-hand "+cls});return g};
            const h=hand("h",108,58),m=hand("m",112,36),s=hand("s",118,28);
            sv(face,"circle",{cx:100,cy:100,r:4.5,class:"mac-cap"});
            const digital=node("div","clock-digital");wrap.append(digital,date);box.append(wrap);
            let turn=0,last=-1;
            const tick=()=>{if(document.hidden)return;const d=new Date(),sec=d.getSeconds();if(sec<last)turn+=360;last=sec;
                s.style.transform="rotate("+(turn+sec*6)+"deg)";
                m.style.transform="rotate("+(d.getMinutes()*6+sec*.1)+"deg)";
                h.style.transform="rotate("+((d.getHours()%12)*30+d.getMinutes()*.5)+"deg)";
                digital.textContent=d.toLocaleTimeString("pt-BR");
                date.textContent=d.toLocaleDateString("pt-BR",{weekday:"long",day:"numeric",month:"long"})};
            tick();box._clock=setInterval(tick,1000);live.add(box._clock)
        })
    }
    function cloud(g,fill){const c=sv(g,"g",{class:"mac-drift",fill});sv(c,"circle",{cx:24,cy:38,r:8});sv(c,"circle",{cx:35,cy:32,r:11});sv(c,"circle",{cx:45,cy:39,r:7});sv(c,"rect",{x:24,y:38,width:21,height:8})}
    function sun(g,cx,cy,r){const s=sv(g,"g",{class:"mac-sun",style:"transform-origin:"+cx+"px "+cy+"px"});for(let i=0;i<8;i++){const a=i*Math.PI/4;sv(s,"line",{x1:cx+Math.cos(a)*(r+4),y1:cy+Math.sin(a)*(r+4),x2:cx+Math.cos(a)*(r+9),y2:cy+Math.sin(a)*(r+9),stroke:"#ffd25e","stroke-width":3,"stroke-linecap":"round"})}sv(g,"circle",{cx,cy,r,fill:"#ffd25e"})}
    function weatherKind(desc){const t=plain(desc);return /tempest|trovoad|raio/.test(t)?"storm":/chuv|garoa|pancada|aguaceiro|chuvisco/.test(t)?"rain":/neve|granizo/.test(t)?"snow":/neblina|nevoa|fumaca|bruma/.test(t)?"fog":/parcial|poucas nuvens|algumas nuvens|variavel/.test(t)?"partly":/nubl|nuvem|nuvens|encoberto|cinza/.test(t)?"cloud":"sun"}
    
    function weatherIcon(kind,night){
        const s=document.createElementNS(NS,"svg");s.setAttribute("viewBox","0 0 64 64");
        const moon=(x,y)=>sv(s,"path",{d:"M38 14a17 17 0 1 0 12 28 14 14 0 0 1-12-28z",fill:"#f6efc4",transform:"translate("+x+" "+y+")"});
        if(kind==="sun"){night?moon(0,0):sun(s,32,32,11)}
        else if(kind==="partly"){night?moon(-6,-6):sun(s,24,24,8);cloud(s,"#fff")}
        else if(kind==="cloud")cloud(s,"#e7eef6");
        else if(kind==="rain"){cloud(s,"#cfd9e6");[28,36,44].forEach((x,i)=>sv(s,"line",{x1:x,y1:50,x2:x-2,y2:56,class:"mac-fall",style:"animation-delay:"+i*.28+"s"}))}
        else if(kind==="storm"){cloud(s,"#8896aa");sv(s,"polygon",{points:"35,42 28,53 33,53 30,63 41,50 36,50 39,42",class:"mac-flash",fill:"#ffd60a"})}
        else if(kind==="snow"){cloud(s,"#e7eef6");[28,36,44].forEach((x,i)=>sv(s,"circle",{cx:x,cy:52,r:2,class:"mac-snow",style:"animation-delay:"+i*.5+"s"}))}
        else [26,34,42].forEach((y,i)=>sv(s,"line",{x1:14+i*3,y1:y,x2:50+i*2,y2:y,stroke:"#fff","stroke-opacity":.85,"stroke-width":3.5,"stroke-linecap":"round",class:"mac-drift",style:"animation-delay:"+i*.8+"s"}));
        return s
    }
    async function weatherWidget(){
        const d=await get("/clima",300000);
        const t=built("weather","weather",box=>{
            const top=node("div","mac-wx-top"),left=node("div"),city=node("strong","mac-wx-city"),temp=node("div","mac-wx-temp"),icon=node("div","mac-wx-icon"),desc=node("span","mac-wx-desc"),range=node("span","mac-wx-range");
            left.append(city,temp);top.append(left,icon);box.append(top,desc,range);box._r={city,temp,icon,desc,range,key:""}
        });
        if(!t)return;
        window.observeJarvisAnimation?.(t);
        const r=t._r,text=d.descricao||d.condicao||"",hour=new Date().getHours(),night=hour<6||hour>=18,kind=weatherKind(text);
        const num=v=>v==null||v===""||!Number.isFinite(Number(v))?null:Math.round(Number(v));
        const cur=num(d.temperatura??d.temp),max=num(d.maxima_dia),min=num(d.minima_dia),rain=num(d.chance_chuva_dia_pct);
        r.city.textContent=d.cidade||"Clima local";r.temp.textContent=cur===null?"—":cur+"°";r.desc.textContent=text;
        r.range.textContent=[max!==null?"Máx "+max+"°":"",min!==null?"Mín "+min+"°":"",rain!==null?"Chuva "+rain+"%":""].filter(Boolean).join(" · ");
        const key=kind+night;if(r.key!==key){r.key=key;r.icon.replaceChildren(weatherIcon(kind,night))}
        t.closest(".screen-widget").dataset.clima=night?"night":["rain","storm","cloud","fog","snow"].includes(kind)?"grey":"day"
    }
    // Anel de progresso animado
    function ringSvg(color){const s=document.createElementNS(NS,"svg");s.setAttribute("viewBox","0 0 100 100");s.setAttribute("class","mac-ring-svg");sv(s,"circle",{cx:50,cy:50,r:40,class:"mac-ring-track"});const bar=sv(s,"circle",{cx:50,cy:50,r:40,class:"mac-ring-bar",stroke:color});bar.style.strokeDasharray=CIRC;bar.style.strokeDashoffset=CIRC;return{svg:s,bar}}
    function setRing(bar,p){bar.style.strokeDashoffset=CIRC*(1-Math.max(0,Math.min(100,p))/100)}
    async function systemWidget(){await window.updateJarvisResources?.(nodes.get("system"),get)}
    async function securityWidget(){
        const d=await get("/interface/seguranca",3000);
        const t=built("security","security",box=>{
            const stateRow=node("div","security-state-row"),copy=node("div","security-state-copy"),pill=node("div","mac-pill"),txt=node("span"),meta=node("p","mac-meta"),shield=node("span","security-shield"),b=node("button","mac-btn");
            pill.append(node("i"),txt);
            const icon=document.createElementNS(NS,"svg");
            icon.setAttribute("viewBox","0 0 48 48");
            icon.setAttribute("aria-hidden","true");
            sv(icon,"path",{class:"security-shield-outline",d:"M24 3 40 9v13c0 10-6.6 18-16 23C14.6 40 8 32 8 22V9l16-6Z"});
            sv(icon,"path",{class:"security-shield-check",d:"m16 24 5 5 11-12"});
            const headline=node("strong","stark-headline"),description=node("span","stark-description"),metrics=node("div","stark-metrics"),people=node("strong"),camera=node("strong"),last=node("span","stark-last");
            for(const [label,value] of [["PESSOAS AGORA",people],["CÂMERA",camera]]){const item=node("div");item.append(node("span","",label),value);metrics.append(item)}
            shield.append(icon);copy.append(pill,headline,description);stateRow.append(shield,copy);
            b.onclick=async()=>{b.disabled=true;try{const state=await api("/seguranca/estado");await api(state.armado?"/seguranca/desarmar":"/seguranca/armar",{});cache.delete("/interface/seguranca");refresh()}catch(e){notice(e.message)}finally{b.disabled=false}};
            const review=node("button","mac-btn stark-review","Revisar área monitorada");review.onclick=async()=>{if(window.openJarvisSection)window.openJarvisSection("line");else{await openScreen("principal");channel?.postMessage({section:"line"})}};
            box.append(stateRow,metrics,last,b,review);box._r={txt,meta,b,shield,headline,description,people,camera,last,review}
        });
        if(!t)return;
        window.observeJarvisAnimation?.(t);
        const r=t._r,partial=d.armado&&(!d.conectada||!d.linha_ativa);t.closest(".screen-widget").dataset.estado=partial?"warning":d.armado?"on":"off";r.review.hidden=!partial;
        r.shield.classList.toggle("is-armed",!!d.armado);
        r.txt.textContent=partial?"ATENÇÃO NECESSÁRIA":d.armado?"PROTOCOLO ATIVO":"MODO OBSERVAÇÃO";
        r.headline.textContent=partial?(d.conectada?"Proteção parcial":"Câmera sem conexão"):d.armado?"Perímetro monitorado":"Vigilância silenciosa";
        r.description.textContent=d.armado?"Alertas e proteção ativados.":"Detecção e registros sem avisos de voz.";
        r.people.textContent=String(d.pessoas??"—");r.camera.textContent=d.conectada?"Online":"Offline";
        r.camera.dataset.online=String(!!d.conectada);
        const last=new Date(d.ultima_deteccao);r.last.textContent=d.ultima_deteccao&&Number.isFinite(last.getTime())?"Último registro · "+last.toLocaleString("pt-BR",{timeZone:"America/Sao_Paulo",day:"2-digit",month:"2-digit",hour:"2-digit",minute:"2-digit"}):"Nenhuma detecção recente";
        if(partial)r.description.textContent=!d.conectada?"Sem imagem recente. Verifique a conexão da câmera.":d.camera_movida?"Câmera deslocada; linha suspensa. Revise a posição.":"Linha não validada. Revise a área de segurança.";
        r.b.dataset.armed=String(!!d.armado);
        r.meta.textContent="Pessoas presentes: "+(d.pessoas??"—");
        r.b.textContent=d.armado?"Desativar defesas":"Ativar defesas"
    }
    // Atualiza apenas widgets presentes
    async function refresh(){clearTimeout(timer);if(refreshing||document.hidden){timer=setTimeout(refresh,5000);return}refreshing=true;const tasks=[];const task=(key,fn)=>{if(nodes.has(key))tasks.push(Promise.resolve().then(fn).then(()=>{const box=nodes.get(key)?.closest(".screen-widget");box?.removeAttribute("data-stale");box?.removeAttribute("title")}).catch(()=>{const box=nodes.get(key)?.closest(".screen-widget");if(box){box.dataset.stale="true";box.title="Sem atualização recente; nova tentativa automática"}}))};
        task("clock",clockWidget);
        task("weather",weatherWidget);
        task("summary",async()=>{const d=await get("/noticias/g1?categoria=tecnologia",300000),headlines=(d.noticias||[]).slice(0,4).map(n=>n.titulo);lines("summary",headlines.length?headlines:["Nenhuma notícia de tecnologia disponível agora."]);const target=nodes.get("summary");if(target&&!target.querySelector("button")){const b=node("button","screen-tab","Abrir resumo do dia");b.onclick=async()=>{await openScreen("principal");channel?.postMessage("resumo")};target.append(b)}});
        task("detections",async()=>{
            const d=await get("/seguranca/deteccoes/hoje",5000),target=nodes.get("detections");if(!target)return;
            const items=(d.eventos||[]).filter(e=>e.foto);
            const signature=JSON.stringify(items);if(target.dataset.signature===signature)return;target.dataset.signature=signature;target.replaceChildren();
            if(!items.length){target.append(node("p","widget-line","Nenhuma foto ou gravação registrada."));return}
            const options={timeZone:"America/Sao_Paulo"},today=new Date().toLocaleDateString("pt-BR",options);
            const dated=items.map(event=>{let date=new Date(event.hora);if(!Number.isFinite(date.getTime())){const m=String(event.foto).match(/_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/);if(m)date=new Date(`${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}-03:00`)}return{event,date}}).sort((a,b)=>(b.date.getTime()||0)-(a.date.getTime()||0));
            let previous="",cluster=null,clusterStart=0,clusterCount=0;
            for(const {event,date} of dated){
                const valid=Number.isFinite(date.getTime()),day=valid?date.toLocaleDateString("pt-BR",options):"Data indisponível";
                if(day!==previous){target.append(node("h3","detection-day",(day===today?"Hoje · ":"")+day));previous=day}
                if(valid&&cluster&&Math.abs(clusterStart-date.getTime())<=60000){clusterCount++;cluster.querySelector("summary").textContent=clusterCount+" registros próximos · "+new Date(clusterStart).toLocaleTimeString("pt-BR",options)}else{cluster=node("details","detection-cluster");cluster.open=true;cluster.append(node("summary","","Registro · "+(valid?date.toLocaleTimeString("pt-BR",options):"Sem horário")));target.append(cluster);clusterStart=date.getTime();clusterCount=1}
                const row=node("article","detection-history-row"),thumb=node("button","detection-thumbnail"),img=node("img"),copy=node("div","detection-copy"),time=node("time","detection-time",valid?date.toLocaleTimeString("pt-BR",options):"Horário indisponível"),buttons=node("div","detection-actions");
                if(valid)time.dateTime=date.toISOString();img.src="/seguranca/evento/imagem/"+encodeURIComponent(event.foto);img.alt="Foto da câmera · "+day+" · "+time.textContent;img.loading="lazy";thumb.setAttribute("aria-label","Abrir foto de "+day+" às "+time.textContent);thumb.append(img);
                const open=kind=>window.openSecurityEvent?.({...event,event:"person",eventType:"person",manual:true,mediaFocus:kind});thumb.onclick=()=>open("photo");
                for(const [label,kind] of [["Foto","photo"],["Gravação","video"]]){const button=node("button","history-media-button",label);button.onclick=()=>open(kind);buttons.append(button)}
                copy.append(time,node("span","detection-caption","Câmera · "+(event.quantidade??event.persons??1)+" pessoa(s)"),buttons);row.append(thumb,copy);cluster.append(row)
            }
        });
        task("agenda",async()=>{const d=await get("/agenda?limite=20"),today=new Date().toDateString();rows("agenda",d.slice(0,5).map(a=>{const w=new Date(a.inicio),minutes=Math.ceil((w-Date.now())/60000),count=minutes>0&&minutes<1440?" · em "+(minutes<60?minutes+" min":Math.floor(minutes/60)+" h "+minutes%60+" min"):"";return{lead:w.toLocaleTimeString("pt-BR",{hour:"2-digit",minute:"2-digit"}),title:a.titulo,sub:(w.toDateString()===today?"Hoje":w.toLocaleDateString("pt-BR",{weekday:"short",day:"2-digit",month:"short"}))+count}}),"Nenhum compromisso registrado.")});
        task("email",async()=>{const status=await get("/gmail/status",60000);if(!status.conectado){lines("email",["Conecte seu Gmail na aba pessoal."]);return}const d=await get("/gmail/mensagens?limite=18",60000),messages=d.mensagens||[],attention=messages.filter(m=>m.needsReply),items=[...attention,...messages.filter(m=>!m.needsReply)].slice(0,6);rows("email",items.map(m=>{const from=String(m.from||m.fromAddress||"Remetente").replace(/<.*>/,"").replace(/"/g,"").trim()||"Remetente";return{avatar:(from.match(/[\p{L}\p{N}]/u)||["?"])[0].toUpperCase(),title:m.subject||"Sem assunto",sub:from+(Number.isFinite(new Date(m.date).getTime())?" · "+new Date(m.date).toLocaleDateString("pt-BR"):""),preview:(m.snippet||"").slice(0,160),onClick:()=>window.openJarvisEmail?.(m)}}),"Nenhum e-mail recente na caixa de entrada.")});
        for(const key of ["news_tech","news_ia","news_politics"])task(key,()=>news(key));
        task("cards",async()=>{const [notes,current]=await Promise.all([get("/memoria/notas"),get("/interface/resumo",3000)]);rows("cards",current.state==="reading"?[{title:"Jarvis está apresentando seu resumo",sub:current.texto,color:"#0a84ff"}]:notes.slice(0,4).map(n=>({title:n.title||"Nota",sub:n.body||"",color:"#ffd60a"})),"Nenhuma nota salva. Os cartões do resumo aparecem em Meu dia.")});
        task("system",systemWidget);
        task("mobile",()=>window.updateJarvisMobile?.(nodes.get("mobile"),get));
        task("security",securityWidget);
        await Promise.allSettled(tasks);refreshing=false;timer=setTimeout(refresh,document.body.classList.contains("economy-mode")?10000:5000);}

    // Atualiza perfil de outras janelas
    async function sync(){if(document.hidden||dragging)return;try{const value=await api("/interface/telas");if(!config||value.revisao!==config.revisao){const antes=JSON.stringify(selectedScreen());config=value;if(antes!==JSON.stringify(selectedScreen()))render()}}catch(_){}}
    window.openJarvisSection=window.openJarvisSection|| (async section=>{await openScreen("principal");channel?.postMessage({section})});
    window.openJarvisCasa=window.openJarvisCasa|| (async tab=>{if(!screenPage)return;await openScreen("principal");channel?.postMessage({centralCasa:tab})});
    if(channel)channel.onmessage=e=>{const m=e.data;if(m&&typeof m==="object"){if(m.section&&!screenPage)window.openJarvisSection?.(m.section);else if(m.centralCasa&&!screenPage)window.openJarvisCasa?.(m.centralCasa);else if(m.pairing&&!screenPage)window.openJarvisPairing?.();else if(m.mover)receive(m);else if(m.aceito)transfers.get(m.aceito)?.ok();else if(m.recusado)transfers.get(m.recusado)?.fail(m.motivo);return}if(m==="resumo"&&!screenPage)window.openDailyBriefing?.();else sync()};
    document.addEventListener("visibilitychange",()=>{if(!document.hidden){sync();refresh()}});
    window.addEventListener("pagehide",()=>{cameraCard?.destroy();clearTimeout(timer);channel?.close()});
    window.addEventListener("resize",extent);
    document.addEventListener("keydown",e=>{if(e.key==="Escape")closeEditor();if(e.ctrlKey&&e.key.toLowerCase()==="z"&&!e.target.closest("input,textarea,[contenteditable=true]")&&!document.querySelector("dialog[open]")&&!document.body.classList.contains("cfg")){e.preventDefault();undo()}});
    
    document.addEventListener("pointerdown",e=>{if(editor&&!editor.contains(e.target)&&!e.target.closest("#screenBar"))closeEditor()},true);
    {const grid=document.getElementById("widgetGrid");grid.ondragover=e=>{e.preventDefault();e.dataTransfer.dropEffect="copy"};grid.ondrop=e=>{e.preventDefault();document.body.classList.remove("widget-dragging");try{const data=JSON.parse(e.dataTransfer.getData("text/plain")),rect=grid.getBoundingClientRect();add(data.jarvisElement,e.clientX-rect.left,e.clientY-rect.top)}catch(_){}}}
    document.addEventListener("dragend",()=>document.body.classList.remove("widget-dragging"));
    window.personalizeJarvisScreens=customize;
    api("/interface/telas").then(value=>{config=value;render();setInterval(sync,15000)}).catch(e=>notice(e.message));
})();
