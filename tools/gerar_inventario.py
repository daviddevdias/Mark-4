"""Gera documentação local sem ler dados pessoais."""
import argparse
import ast
from datetime import datetime
from pathlib import Path
import re

BASE = Path(__file__).resolve().parents[1]
SECOES = [
    ("Inicialização e janelas", "Inicializa serviços, abre as janelas nativas e conserva a posição das telas.", ["main.py", "interface/painel.py", "interface/janelas_nativas.py"]),
    ("Tela principal", "Núcleo animado, horário, sessão de conversa, microfone, menu e botão de interromper.", ["jarvis.html", "hud/core3d.js", "interface/static/js/cornerPanel.js"]),
    ("Segunda tela e cards", "Câmera, Torre Stark, detecções, relógio, clima, agenda, sistema, e-mails e notificações. Layout editável e salvo localmente.", ["telas.html", "interface/telas_widgets.py", "interface/static/js/telasWidgets.js", "interface/static/js/cardEnhancements.js"]),
    ("Configurações e dashboard", "Controles, segurança, pessoal, comandos, registros e integrações. Métricas reais do computador e processos.", ["interface/static/js/jarvis.js", "interface/static/js/workspaceShell.js", "interface/static/js/experience.js", "interface/recursos_sistema.py"]),
    ("Câmera e segurança", "Conexão de vídeo, recuperação, lentes, linha monitorada, detecção, pose e gravações de eventos.", ["interface/static/js/cameraPlayer.js", "interface/static/js/cameraCard.js", "comandos/automacao/video_local.py", "comandos/automacao/vigia_camera.py", "comandos/automacao/seguranca_stark.py", "comandos/automacao/gravacao_eventos.py", "comandos/automacao/reproducao_eventos.py"]),
    ("Voz e comandos", "Escuta, ativação por chamada ao Jarvis, execução de comandos e síntese de fala.", ["interface/voz.py", "comandos/wake_word.py", "comandos/controller.py", "comandos/linguagem.py"]),
    ("Inteligência artificial local", "Integração com LM Studio e Hermes, geração de respostas e cancelamento.", ["comandos/llm_local.py", "comandos/hermes_agent.py", "comandos/amigo.py"]),
    ("E-mail, agenda e memória", "Consulta de mensagens, leitura segura do conteúdo, rascunhos, compromissos, notas e resumo do dia.", ["interface/gmail.py", "interface/email_conteudo.py", "interface/google_agenda.py", "comandos/memoria.py", "comandos/briefing_dia.py", "interface/static/js/personalHologram.js"]),
    ("Celular e acesso remoto", "API autenticada, conexão HTTPS, pareamento, avisos do Android e comandos remotos.", ["interface/servidor_remoto.py", "interface/pessoal_celular.py", "interface/cofre_privado.py", "comandos/https_local.py"]),
    ("Casa, computador e navegador", "Controles de dispositivos, TV, aplicativos, navegador e automações de presença.", ["comandos/automacao/smart_home.py", "comandos/pc_controle.py", "comandos/navegador_sistema.py", "comandos/navegador_voz.py", "comandos/automacao/presenca.py"]),
]

def analisar(caminho):
    texto = caminho.read_text(encoding="utf-8-sig")
    funcoes, rotas = [], []
    if caminho.suffix == ".py":
        arvore = ast.parse(texto)
        for item in ast.walk(arvore):
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcoes.append((item.name, item.lineno))
                for dec in item.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr in {"route", "get", "post", "delete", "put", "patch"} and dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                        metodos = dec.func.attr.upper() if dec.func.attr != "route" else "GET"
                        for keyword in dec.keywords:
                            if keyword.arg == "methods":
                                try: metodos = ", ".join(ast.literal_eval(keyword.value))
                                except (ValueError, TypeError): pass
                        rotas.append((metodos, dec.args[0].value, item.name, item.lineno))
    elif caminho.suffix == ".js":
        funcoes = [(m.group(1), texto[:m.start()].count("\n")+1) for m in re.finditer(r"(?:async\s+)?function\s+(\w+)\s*\(", texto)]
    return len(texto.splitlines()), funcoes, rotas

def gerar(destino):
    linhas = ["# Inventário do Jarvis", "", "Gerado em " + datetime.now().astimezone().isoformat(timespec="seconds"), "", "Este inventário combina um mapa explicativo com símbolos e rotas encontrados no código. Não comprova que todas as integrações estejam conectadas. Não lê data/, credenciais, logs, e-mails, certificados nem valores de configuração.", ""]
    catalogados=set(); rotas=[]; erros=[]
    for titulo, descricao, arquivos in SECOES:
        linhas.extend(["## " + titulo, "", descricao, ""])
        for arquivo in arquivos:
            caminho=BASE/arquivo
            if not caminho.is_file(): continue
            catalogados.add(arquivo)
            try: quantidade, funcoes, endpoints=analisar(caminho)
            except (OSError, UnicodeError, SyntaxError) as erro:
                erros.append(arquivo + ": " + type(erro).__name__); continue
            rotas.extend(endpoints)
            linhas.extend(["### " + arquivo, "", str(quantidade)+" linhas.", ""])
            if funcoes:
                linhas.extend(["Funções: " + "; ".join(nome + " (linha " + str(numero) + ")" for nome,numero in funcoes) + ".", ""])
    linhas.extend(["## Rotas da API", "", "Métodos, caminhos e funções responsáveis. O acesso continua sujeito às regras de autenticação do servidor.", ""])
    for metodo, rota, funcao, numero in sorted(set(rotas)):
        linhas.append(f"- `{metodo} {rota}` — `{funcao}`, linha {numero}.")
    linhas.extend(["", "## Demais arquivos de implementação", ""])
    for pasta in ["comandos", "interface", "hud", "Android/app/src"]:
        raiz=BASE/pasta
        if not raiz.exists(): continue
        for arquivo in sorted(raiz.rglob("*")):
            if arquivo.suffix not in {".py", ".js", ".css", ".kt", ".xml"} or any(parte in {"data", "build", "__pycache__", ".gradle"} for parte in arquivo.parts): continue
            relativo=arquivo.relative_to(BASE).as_posix()
            if relativo not in catalogados: linhas.append("- " + relativo)
    linhas.extend(["", "## Testes disponíveis", ""])
    for arquivo in sorted((BASE/"tests").glob("test_*.py")): linhas.append("- " + arquivo.relative_to(BASE).as_posix())
    linhas.extend(["", "## Como atualizar", "", "Execute `gerar_texto_jarvis.bat` na raiz ou `python tools/gerar_inventario.py --saida docs/INVENTARIO_JARVIS.md`. Para texto simples, escolha um destino terminado em .txt. O conteúdo usa marcações legíveis nos dois formatos.", "", "## Manutenção", "", "Consulte MANUTENCAO.md e docs/MELHORIAS_2026-10-14.md. O inventário não altera o funcionamento do Jarvis.", ""])
    if erros: linhas.extend(["## Arquivos não analisados", "", *erros])
    destino.parent.mkdir(parents=True,exist_ok=True)
    destino.write_text("\n".join(linhas),encoding="utf-8")
    return len(rotas)

if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saida",type=Path,default=BASE/"docs"/"INVENTARIO_JARVIS.md")
    args=parser.parse_args()
    destino=args.saida.resolve()
    rotas=gerar(destino)
    print(f"Documento criado: {destino} ({rotas} rotas catalogadas)")
