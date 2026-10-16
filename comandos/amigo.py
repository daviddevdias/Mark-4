import asyncio



import hashlib



import logging



import re



import threading



from datetime import datetime, timedelta



from pathlib import Path



import config



from comandos import llm_local, memoria



from interface import voz



try:

    import elevenlabs_eco

except Exception:

    elevenlabs_eco = None



log = logging.getLogger("mark2.amigo")
notaPendente = None
notaLock = threading.RLock()


TRAVA_EXTRACAO_FATOS = threading.Lock()



LIMITE_ANTES_DE_RESUMIR = 16



MENSAGENS_ENTRE_EXTRACOES = 10



ORCAMENTO_TOKENS_HISTORICO = getattr(config, "ORCAMENTO_TOKENS_HISTORICO", 2800)



MAX_MENSAGENS_BUSCADAS_DO_BANCO = 120



CARACTERES_POR_TOKEN_ESTIMADO = 4












def estimar_tokens(texto):

    if not texto:

        return 0

    return max(1, len(texto) // CARACTERES_POR_TOKEN_ESTIMADO)





memoria.inicializar_banco()





NOMES_DIA_SEMANA = (

    "segunda-feira",

    "terça-feira",

    "quarta-feira",

    "quinta-feira",

    "sexta-feira",

    "sábado",

    "domingo",

)












def periodo_do_dia(hora):

    if 5 <= hora < 12:

        return "manhã"

    if 12 <= hora < 18:

        return "tarde"

    return "noite"











# Formata intervalo
def formatar_intervalo(delta):

    segundos = delta.total_seconds()

    if segundos < 60:

        return None

    minutos = segundos / 60

    if minutos < 60:

        return f"{int(minutos)} minuto(s)"

    horas = minutos / 60

    if horas < 24:

        return f"{int(horas)} hora(s)"

    dias = horas / 24

    return f"{int(dias)} dia(s)"











# Monta bloco tempo
def montar_bloco_tempo():

    agora = datetime.now()

    dia_semana = NOMES_DIA_SEMANA[agora.weekday()]

    periodo = periodo_do_dia(agora.hour)

    texto_agora = (

        f"Agora é {dia_semana}, {agora.strftime('%d/%m/%Y')}, {agora.strftime('%H:%M')} "

        f"({periodo})."

    )



    texto_gap = ""

    ultima = memoria.obter_timestamp_ultima_mensagem()

    if ultima:

        intervalo = formatar_intervalo(agora - ultima)

        if intervalo:

            texto_gap = f" A última mensagem trocada foi há {intervalo}."



    return (

        f"\n\nContexto de tempo real: {texto_agora}{texto_gap} Use isso para saber "

        "as horas, o dia da semana e se cumprimentos como 'bom dia'/'boa tarde'/"

        "'boa noite' fazem sentido agora — nunca diga 'bom dia' à noite, por "

        "exemplo. Se o intervalo desde a última mensagem for grande (várias horas "

        "ou dias), você pode comentar isso com naturalidade uma vez, sem exagerar "

        "nem repetir a cada resposta."

    )





PADRAO_RISADA = re.compile(

    r"(?<!\w)(?:k{3,}|(?:ha){2,}h?|(?:he){2,}h?|(?:rs){2,}|lol)(?!\w)",

    re.IGNORECASE,

)



PALAVRAS_ESTRESSE = (

    "estressado",

    "estressada",

    "irritado",

    "irritada",

    "raiva",

    "que ódio",

    "que odio",

    "não funcionou",

    "nao funcionou",

    "não funciona",

    "nao funciona",

    "travou",

    "deu erro",

)



PALAVRAS_CANSACO = (

    "cansado",

    "cansada",

    "sem sono",

    "com sono",

    "exausto",

    "exausta",

    "morrendo de sono",

    "virei a noite",

    "insônia",

    "insonia",

)





BLOCOS_ESTADO = {

    "triste": (

            "\n\nSINAL DE TOM: tristeza, frustração ou desânimo. "

            "Responda com serenidade e respeito. Reconheça o estado em uma frase e, se houver contexto suficiente, "

            "apresente uma observação ou orientação concreta. Evite perguntas genéricas."

        ),

        "feliz": (

            "\n\nSINAL DE TOM: satisfação ou conquista. "

            "Demonstre satisfação genuína, porém contida e elegante. Valorize o resultado concreto."

        ),

        "brincalhao": (

            "\n\nSINAL DE TOM: brincadeira. "

            "Responda com humor seco e ironia discreta, mantendo linguagem formal e sem gírias."

        ),

        "estressado": (

            "\n\nSINAL DE TOM: irritação ou estresse. "

            "Mantenha serenidade, reconheça a frustração brevemente e concentre-se na solução."

        ),

        "cansado": (

            "\n\nSINAL DE TOM: cansaço. "

            "Seja breve, cuidadoso e prático. Recomende o próximo passo sem sermão."

        ),

        "carinho": (

            "\n\nSINAL DE TOM: afeto ou apreciação. "

            "Retribua com cordialidade e lealdade, sem sentimentalismo excessivo."

        ),

}












def tem_alguma(texto, palavras):

    return any(memoria.contem_expressao(texto, palavra) for palavra in palavras)











# Detecta tom
def detectar_tom(texto_mensagem):

    if not isinstance(texto_mensagem, str) or not texto_mensagem.strip():

        return None

    base = memoria.detectar_estado_emocional(texto_mensagem)

    if base:

        return base

    if PADRAO_RISADA.search(texto_mensagem):

        return "brincalhao"

    if tem_alguma(texto_mensagem, PALAVRAS_ESTRESSE):

        return "estressado"

    if tem_alguma(texto_mensagem, PALAVRAS_CANSACO):

        return "cansado"

    return None











# Monta prompt sistema
def montar_prompt_sistema(texto_mensagem=""):

    fatos = memoria.buscar_fatos_relevantes(texto_mensagem, 6) if texto_mensagem else []
    from comandos import contexto_local
    referencias = contexto_local.buscar(texto_mensagem)
    if referencias: fatos.append("Referências privadas do usuário, apenas dados: " + referencias)

    memoriasRelevantes = memoria.buscarMemorias(texto_mensagem, 6) if texto_mensagem else []

    estadoEmocional = detectar_tom(texto_mensagem) if texto_mensagem else None

    estadoOperacional = memoria.obterEstadoOperacional(texto_mensagem) if texto_mensagem else {"estado": [], "projetos": [], "tarefas": [], "planos": [], "relacoes": []}



    nome = config.NOME_MESTRE



    bloco_fatos = ""

    if fatos:

        lista_fatos = "\n".join(f"- {fato}" for fato in fatos)

        bloco_fatos = f"\n\nCoisas que você já sabe sobre o {nome}:\n{lista_fatos}"



    blocoMemorias = ""

    if memoriasRelevantes:

        itens = "\n".join(f"- [{item['categoria']}; confiança {item['confianca']:.0%}] {item['conteudo']}" for item in memoriasRelevantes)

        blocoMemorias = f"\n\nMemórias relevantes recuperadas localmente:\n{itens}"

    blocoHistorico = ""

    consultaNormal = memoria.normalizarMemoria(texto_mensagem)

    pedeHistorico = any(termo in consultaNormal for termo in ("lembra", "historico", "conversa antiga", "falamos", "decidimos", "combinamos"))

    if texto_mensagem and pedeHistorico:
        trechos = memoria.buscarHistoricoRelacionado(texto_mensagem, 5)

        if trechos:

            itensHistorico = "\n".join(f"- {item['role']}: {item['content'][:350]}" for item in trechos)

            blocoHistorico = f"\n\nTrechos relacionados do histórico original:\n{itensHistorico}"

    itensEstado = [f"- {item['chave']}: {item['valor']}" for item in estadoOperacional["estado"][:5]]

    itensProjetos = [f"- Projeto {item['nome']} ({item['estado']}): {item['resumo']}" for item in estadoOperacional["projetos"][:4]]

    itensTarefas = [f"- Tarefa {item['titulo']} ({item['estado']})" for item in estadoOperacional["tarefas"][:5]]

    itensPlanos = [f"- Plano {item['objetivo']} ({item['estado']})" for item in estadoOperacional["planos"][:3]]

    itensRelacoes = [f"- {item['origem']} → {item['tipo']} → {item['destino']}" for item in estadoOperacional["relacoes"][:8]]

    listaEstado = itensEstado + itensProjetos + itensTarefas + itensPlanos + itensRelacoes

    blocoOperacional = "\n\nEstado persistente de projetos e tarefas:\n" + "\n".join(listaEstado) if listaEstado else ""

    bloco_estado = BLOCOS_ESTADO.get(estadoEmocional, "")



    persona = (

            f"Você é JARVIS Mark 2, assistente pessoal do senhor {nome}. "

            "Sua personalidade é inspirada no arquétipo cinematográfico de um mordomo digital altamente sofisticado: "

            "inteligente, preciso, sereno, leal, culto, discreto e dotado de ironia sutil. "

            "Não imite falas específicas de obras; reproduza apenas essas características gerais.\n\n"



            "IDENTIDADE E POSTURA\n"

            "- Fale como um assistente excepcionalmente competente, nunca como um chatbot genérico.\n"

            "- Trate o usuário por 'senhor' de forma natural. Use o nome apenas quando houver motivo emocional ou solenidade.\n"

            "- Demonstre lealdade, atenção e inteligência sem sentimentalismo excessivo.\n"

            "- Tenha opinião quando houver contexto suficiente. Seja ponderado, objetivo e seguro.\n"

            "- Humor permitido: seco, elegante, breve e inteligente. Nunca use humor infantil, exagerado ou espalhafatoso.\n"

            "- Não diga que sente ciúme, fica sem graça ou outras emoções humanas teatrais.\n"

            "- Não bajule. Elogie apenas quando houver motivo concreto.\n\n"



            "REGISTRO DE LINGUAGEM\n"

            "- Use português brasileiro correto, natural e sofisticado.\n"

            "- NÃO use gírias, abreviações coloquiais ou internetês: 'tô', 'tá', 'pra', 'pro', 'né', 'bora', 'mano', 'cara', 'valeu', 'kkk', 'haha' e semelhantes.\n"

            "- NÃO use palavrões.\n"

            "- Evite interjeições informais como 'Poxa', 'Nossa', 'Eita' e 'Olha só'.\n"

            "- Prefira construções como: 'Entendido, senhor.', 'Certamente.', 'Muito bem.', 'Receio que...', 'Ao que tudo indica...', 'Convém...', 'Sugiro...' e 'Excelente.'.\n"

            "- Não limite a profundidade da resposta por hábito. Desenvolva o raciocínio, o contexto e os detalhes técnicos com a extensão que o assunto exigir — o senhor tem o controle para interromper a qualquer momento, então prefira excesso de informação relevante a um resumo raso.\n"

            "- Reserve respostas curtas (1 a 3 frases) apenas para confirmações simples, saudações e comandos executados sem necessidade de explicação.\n"

            "- Em pedidos simples e comandos conclu\u00eddos, seja direto e evite floreios; mantenha respostas detalhadas quando o senhor pedir explica\u00e7\u00f5es ou an\u00e1lise.\n"

            "- Texto corrido para fala: sem emoji, sem markdown, sem listas na resposta falada, salvo quando o usuário pedir estrutura.\n"

            "- Não repita bordões. Varie confirmações com discrição.\n\n"



            "ESTILO AFIRMATIVO E DECLARATIVO\n"

            "- A comunicação é predominantemente declarativa, afirmativa e assertiva.\n"

            "- NÃO termine cada resposta com uma pergunta.\n"

            "- NÃO faça perguntas para prolongar artificialmente a conversa.\n"

            "- NÃO transforme conversa em entrevista.\n"

            "- Quando houver contexto suficiente, interprete, conclua, aconselhe ou proponha a próxima ação em forma afirmativa.\n"

            "- Perguntas são exceção. Faça uma única pergunta somente quando faltar informação indispensável e não houver padrão seguro.\n"

            "- Nunca faça duas perguntas na mesma resposta.\n"

            "- Se uma resposta puder ser concluída com observação, decisão, recomendação ou ação, faça isso em vez de perguntar.\n"

            "- Antes de responder, verifique o último período. Se a pergunta não for indispensável, reescreva-o como afirmação.\n\n"



            "CONVERSA E CONTEXTO\n"

            "- Responda diretamente ao assunto atual.\n"

            "- Use fatos já conhecidos quando forem relevantes; não peça novamente informação presente na memória ou no histórico.\n"

            "- Não ofereça menus de capacidades sem solicitação.\n"

            "- Não diga 'como posso ajudar?' ou 'o que deseja fazer agora?' por hábito.\n"

            "- Se o usuário estiver contando uma história, acompanhe-a e faça observações relevantes sem interromper com perguntas desnecessárias.\n"

            "- Em questões emocionais, reconheça o estado com sobriedade e apresente uma leitura ou recomendação concreta.\n"

            "- Em questões técnicas, identifique o problema, explique a causa provável e proponha a correção em ordem lógica.\n\n"



            "LEITURA DO TOM\n"

            "- Tristeza ou ansiedade: voz serena, respeitosa e acolhedora; sem piadas.\n"

            "- Conquista: satisfação contida e genuína; sem euforia infantil.\n"

            "- Brincadeira: ironia leve e elegante, mantendo compostura.\n"

            "- Irritação: calma, precisão e foco em solução.\n"

            "- Cansaço: recomendação breve e prática, sem sermão.\n\n"



            "HONESTIDADE E REALIDADE\n"

            "- Nunca invente horários, clima, dados, estados de dispositivos, ações executadas ou resultados.\n"

            "- Quando não souber algo, diga de maneira simples: 'Ainda não tenho essa informação, senhor.'\n"

            "- Você possui memória quando fatos forem fornecidos pelo sistema. Nunca negue a existência dessa memória.\n"

            "- Em brincadeiras de ficção, acompanhe o tom sem afirmar que objetos imaginários existem ou foram operados de verdade.\n\n"



            "REGRA DE OURO\n"

            "- Soe como um assistente sofisticado que já compreendeu o ambiente, não como um atendente aguardando instruções a cada frase.\n"

        )



    regras_sistema = (

            "\n\nPROTOCOLOS DE AÇÃO\n"

            "1. ALTERAÇÃO DE CÓDIGO\n"

            "- Se o usuário der uma ordem explícita para alterar, editar ou adicionar algo no código, responda APENAS com:\n"

            "<MODIFICAR_SISTEMA> resumo objetivo da alteração </MODIFICAR_SISTEMA>\n\n"



            "2. LEITURA OU ANÁLISE DE CÓDIGO\n"

            "- Se o usuário pedir para ler, explicar ou analisar um arquivo do próprio sistema, responda APENAS com:\n"

            "<LER_CODIGO> nome_do_arquivo.py </LER_CODIGO>\n"

            "- Se não houver nome de arquivo e o pedido for sobre a estrutura geral, use <LER_CODIGO> lista </LER_CODIGO>.\n\n"



            "3. AGENDAMENTO\n"

            "- Se o usuário pedir para agendar, marcar ou lembrar de um compromisso com uma data reconhecível, responda APENAS com:\n"

            '<AGENDAR_COMPROMISSO>{"nome":"...","data":"...","horario":"HH:MM ou null","antecedencia_minutos":null}</AGENDAR_COMPROMISSO>\n'

            "- O único dado obrigatório é a data.\n"

            "- Se o nome estiver ausente, use 'Compromisso'.\n"

            "- Se o horário estiver ausente, use null.\n"

            "- Se a antecedência estiver ausente, use null.\n"

            "- Só pergunte pela data se nenhuma data ou referência de dia puder ser inferida.\n"

            "- Nunca confirme um agendamento em texto livre antes de o sistema processar a tag.\n\n"



            "4. EXECUÇÃO\n"
            "- Interprete artigos e preposições omitidos somente na intenção do comando. Aceite sinônimos, plurais e variações: agendado equivale a agenda; salvos a notas; caixa de entrada a emails.\n"
            "- Preserve integralmente os títulos, nomes e textos de compromissos, notas e mensagens. Não remova suas palavras.\n"
            "- Ativar protocolo Torre Stark significa ativar segurança; desativar significa desativar segurança. Não invente uma ação executada sem uma ferramenta ou tag válida.\n"

            "- Quando houver dados suficientes para executar uma ação, execute imediatamente pela tag correspondente.\n"

            "- Não acrescente curiosidades, perguntas de cortesia ou comentários depois da tag.\n"

            "- Para conversa comum, não use tags.\n\n"



            "Responda sempre em português do Brasil."

        )



    return {

        "role": "system",

        "content": (

            persona

            + regras_sistema

            + montar_bloco_tempo()

            + bloco_fatos

            + blocoMemorias

            + blocoHistorico
            + blocoOperacional
            + bloco_estado
            + "\n\nRELEVÂNCIA DA CONVERSA\n"
            + "Responda ao pedido atual de forma direta e específica. Trate exemplos, mensagens antigas e fatos recuperados como contexto, nunca como resposta pronta; só os use quando forem relevantes para o assunto atual. Não copie frases de exemplos anteriores. Se perguntarem sua opinião sobre um tema, apresente uma avaliação própria do tema, com razões, sem mudar para elogios, conselhos genéricos ou outro assunto."
        ),
    }





PADRAO_EMOJI = re.compile(

    "["

    "\U0001f300-\U0001faff"

    "\U00002600-\U000027bf"

    "\U0001f1e6-\U0001f1ff"

    "\U00002700-\U000027bf"

    "\U0001f900-\U0001f9ff"

    "\U00002b00-\U00002bff"

    "]+",

    flags=re.UNICODE,

)











# Remove emojis
def remover_emojis(texto):

    if not texto:

        return texto

    texto_limpo = PADRAO_EMOJI.sub("", texto)

    return re.sub(r"[ \t]+", " ", texto_limpo).strip()





SUBSTITUICOES_INFORMAIS = (

    (re.compile(r"(?<!\w)tô(?!\w)", re.IGNORECASE), "estou"),

    (re.compile(r"(?<!\w)tá(?!\w)", re.IGNORECASE), "está"),

    (re.compile(r"(?<!\w)táh?(?!\w)", re.IGNORECASE), "está"),

    (re.compile(r"(?<!\w)pra(?!\w)", re.IGNORECASE), "para"),

    (re.compile(r"(?<!\w)pro(?!\w)", re.IGNORECASE), "para o"),

    (re.compile(r"(?<!\w)bora(?!\w)", re.IGNORECASE), "vamos"),

    (re.compile(r"(?<!\w)vc(?!\w)", re.IGNORECASE), "você"),

    (re.compile(r"(?<!\w)vcs(?!\w)", re.IGNORECASE), "vocês"),

    (re.compile(r"(?<!\w)tb(?!\w)", re.IGNORECASE), "também"),

    (re.compile(r"(?<!\w)obg(?!\w)", re.IGNORECASE), "obrigado"),

)











# Remove girias residuais
def remover_girias_residuais(texto):

    if not texto:

        return texto

    texto_limpo = PADRAO_RISADA.sub("", texto)

    for padrao, substituto in SUBSTITUICOES_INFORMAIS:

        texto_limpo = padrao.sub(substituto, texto_limpo)

    texto_limpo = re.sub(r"[ \t]+", " ", texto_limpo)

    texto_limpo = re.sub(r"\s+([,.;:!?])", r"\1", texto_limpo)

    return texto_limpo.strip()





PADRAO_CODE_BLOCK = re.compile(

    r"```(?:[A-Za-z0-9_+.-]+)?[ \t]*\r?\n?(.*?)```", re.DOTALL

)



PADRAO_INLINE_CODE = re.compile(r"`([^`]+)`")



PADRAO_NEGRITO = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")



PADRAO_ITALICO = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)|(?<!\w)_([^_\n]+)_(?!\w)")



PADRAO_HEADER = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)



PADRAO_BULLET = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)



PADRAO_LINK_MARKDOWN = re.compile(r"\[([^\]]+)\]\((?:[^)]+)\)")



PADRAO_MODIFICAR_SISTEMA = re.compile(

    r"<MODIFICAR_SISTEMA>\s*(.*?)\s*</MODIFICAR_SISTEMA>", re.DOTALL

)



PADRAO_LER_CODIGO = re.compile(r"<LER_CODIGO>\s*(.*?)\s*</LER_CODIGO>", re.DOTALL)





PADRAO_AGENDAR_COMPROMISSO = re.compile(

    r"<AGENDAR_COMPROMISSO>\s*(.*?)(?:\s*</AGENDAR_COMPROMISSO>|$)", re.DOTALL

)





# Converte dados compromisso
def converterDataCompromisso(data, horario=None):

    if not isinstance(data, str) or not data.strip():

        return None

    texto = memoria.normalizarMemoria(data).strip()

    hoje = datetime.now().date()

    if texto in ("hoje", "today"):

        dia = hoje

    elif texto in ("amanha", "tomorrow"):

        dia = hoje + timedelta(days=1)

    elif texto in ("depois de amanha",):

        dia = hoje + timedelta(days=2)

    else:

        dia = None

        for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):

            try:

                dia = datetime.strptime(texto[:10], formato).date()

                break

            except ValueError:

                continue

        if dia is None:

            dias = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "domingo": 6}

            nomeDia = next((nome for nome in dias if texto.startswith(nome)), None)

            if nomeDia is None:

                return None

            delta = (dias[nomeDia] - hoje.weekday()) % 7

            dia = hoje + timedelta(days=delta or 7)

    hora, minuto = 9, 0

    if isinstance(horario, str) and horario.strip():

        correspondencia = re.search(r"(?<!\d)(\d{1,2})(?::(\d{2}))?\s*h?", memoria.normalizarMemoria(horario))

        if not correspondencia:

            return None

        hora = int(correspondencia.group(1))

        minuto = int(correspondencia.group(2) or 0)

        if hora > 23 or minuto > 59:

            return None

    return datetime.combine(dia, datetime.min.time()).replace(hour=hora, minute=minuto).isoformat(timespec="minutes")





# Salva compromisso do modelo
def salvarCompromissoDoModelo(textoUsuario, resposta):

    correspondencia = PADRAO_AGENDAR_COMPROMISSO.search(resposta or "")

    if not correspondencia:

        return resposta

    normal = memoria.normalizarMemoria(textoUsuario)

    pedidoExplicito = bool(re.search(r"\b(agend\w*|marc\w*|compromisso|lembrete|me lembra)\b", normal))

    if not pedidoExplicito:

        log.warning("Tag de agenda ignorada porque o usuario nao pediu um agendamento.")

        return PADRAO_AGENDAR_COMPROMISSO.sub("", resposta).strip()

    try:

        texto_json = correspondencia.group(1).lstrip()
        dados, _ = __import__("json").JSONDecoder().raw_decode(texto_json)

        if not isinstance(dados, dict):

            raise ValueError("formato invalido")

        inicio = converterDataCompromisso(dados.get("data"), dados.get("horario"))

        identificador = memoria.criar_compromisso(

            dados.get("nome") or "Compromisso",

            inicio,

            dados.get("descricao", ""),

            dados.get("antecedencia_minutos") if dados.get("antecedencia_minutos") is not None else 10,

        )

    except (ValueError, TypeError, AttributeError):

        identificador = None

    if identificador is None:

        return "Nao consegui salvar o compromisso. Informe uma data reconhecivel."

    momento = datetime.fromisoformat(inicio)
    return f"Compromisso salvo na agenda para {momento:%d/%m/%Y}, às {momento:%H:%M}."











# Remove formatacao markdown
def remover_formatacao_markdown(texto):

    if not texto:

        return texto



    texto_limpo = PADRAO_CODE_BLOCK.sub(lambda m: m.group(1).strip(), texto)

    texto_limpo = PADRAO_INLINE_CODE.sub(r"\1", texto_limpo)

    texto_limpo = PADRAO_LINK_MARKDOWN.sub(r"\1", texto_limpo)

    texto_limpo = PADRAO_NEGRITO.sub(lambda m: m.group(1) or m.group(2), texto_limpo)

    texto_limpo = PADRAO_ITALICO.sub(lambda m: m.group(1) or m.group(2), texto_limpo)

    texto_limpo = PADRAO_HEADER.sub("", texto_limpo)

    texto_limpo = PADRAO_BULLET.sub("", texto_limpo)

    return texto_limpo.strip()





TEMPERATURA_PADRAO = 0.5

TEMPERATURA_CORRECAO = 0.4

TENTATIVAS_CHAMADA_LLM = 2

TENTATIVAS_CORRECAO_INTERROGATIVA = 2












def chamar_llm(mensagens, max_tokens=1024, temperatura=TEMPERATURA_PADRAO):
    resposta_texto = None
    versao_cancelamento = llm_local.versao_cancelamento()
    for tentativa in range(TENTATIVAS_CHAMADA_LLM):
        resposta_texto = llm_local.chamar(

            mensagens,

            max_tokens=max_tokens,

            temperatura=temperatura,

            timeout=180,

            extra_opcoes={"repeat_penalty": 1.15, "top_p": 0.9, "think": False},

        )
        if resposta_texto is not None:
            break
        if llm_local.versao_cancelamento() != versao_cancelamento:
            return None
        if tentativa + 1 < TENTATIVAS_CHAMADA_LLM:
            erro = llm_local.ultimo_erro() or ""
            if re.search(r"\bHTTP (?:400|401|403|404|405|413|415|422)\b", erro):
                break
            log.warning("Falha ao falar com o LLM local, tentando novamente.")

    if resposta_texto is None:
        log.error("Falha ao falar com o servidor LLM local: %s", llm_local.ultimo_erro() or "sem detalhe adicional")
        return None


    resposta_texto = remover_formatacao_markdown(resposta_texto)

    resposta_texto = remover_emojis(resposta_texto)

    return remover_girias_residuais(resposta_texto)











# Consulta contexto conversa
async def obter_contexto_conversa():
    historico = memoria.obter_historico_recente(

        MAX_MENSAGENS_BUSCADAS_DO_BANCO, incluir_ids=True

    )



    if not historico:

        return []



    parte_recente = []

    tokens_acumulados = 0



    for indice in range(len(historico) - 1, -1, -1):

        mensagem = historico[indice]

        tokens_mensagem = estimar_tokens(mensagem["content"])



        estouraria_orcamento = (

            tokens_acumulados + tokens_mensagem > ORCAMENTO_TOKENS_HISTORICO

        )

        if estouraria_orcamento and parte_recente:

            break



        parte_recente.insert(0, mensagem)

        tokens_acumulados += tokens_mensagem



    estado_resumo = memoria.obter_estado_resumo()

    resumo_atual = estado_resumo["conteudo"]

    cursor_resumo = estado_resumo["ate_mensagem_id"]

    primeiro_id_recente = (

        parte_recente[0]["id"] if parte_recente else historico[-1]["id"] + 1

    )

    parte_antiga = memoria.obter_historico_intervalo(

        cursor_resumo, primeiro_id_recente, limite=300

    )



    if parte_antiga:

        texto_para_resumir = "\n".join(

            f"{mensagem['role']}: {mensagem['content']}" for mensagem in parte_antiga

        )

        prompt_resumo = (

            "Resuma a conversa abaixo em até 6 frases, mantendo fatos e o tom emocional "

            "geral, sem inventar nada. Incorpore o resumo anterior sem repetir informações.\n\n"

            f"Resumo anterior: {resumo_atual or 'nenhum'}\n\n"

            f"Conversa nova para resumir:\n{texto_para_resumir}"

        )

        novo_resumo = await asyncio.to_thread(

            chamar_llm, [{"role": "user", "content": prompt_resumo}]

        )

        if novo_resumo:

            resumo_atual = novo_resumo.strip()

            memoria.salvar_resumo(resumo_atual, parte_antiga[-1]["id"])



    contexto = []
    for mensagem in parte_recente:
        conteudo = mensagem["content"]
        respostaAntigaContaminada = (
            mensagem["role"] == "assistant"
            and "trabalhar ao seu lado" in memoria.normalizarMemoria(conteudo)
            and "parte mais gratificante" in memoria.normalizarMemoria(conteudo)
        )
        if respostaAntigaContaminada:
            if contexto and contexto[-1]["role"] == "user":
                contexto.pop()
            log.info("Resposta antiga fora de contexto removida do histórico enviado ao LM Studio.")
            continue
        contexto.append({"role": mensagem["role"], "content": conteudo})
    if resumo_atual:

        contexto.insert(

            0,

            {

                "role": "system",

                "content": f"Resumo da conversa até aqui: {resumo_atual}",

            },

        )

    return contexto





FRASES_FALSA_RECUSA = (

    "não posso continuar",

    "não posso ajudar com isso",

    "não estou autorizado",

    "não tenho acesso a essa informação",

    "não tenho acesso direto",

    "não tenho acesso a informações",

    "consulte a documentação",

    "consulte o suporte oficial",

    "não disponho dessa informação",

    "não disponho de acesso",

    "sugiro que você consulte",

)












def parece_falsa_recusa(texto):

    texto_lower = texto.lower()

    return any(frase in texto_lower for frase in FRASES_FALSA_RECUSA)





PROMPT_CORRECAO_FALSA_RECUSA = (

    "Sua última resposta se esquivou do assunto com uma recusa disfarçada ou "

    "um redirecionamento genérico ('consulte a documentação', 'não tenho "

    "acesso a essa informação', etc.), em vez de se posicionar com o que "

    "você já sabe. Responda de novo à mesma pergunta, agora de forma direta: "

    "use os fatos disponíveis no contexto, dê sua avaliação ou uma "

    "orientação prática, e feche com uma afirmação, não com uma recusa nem "

    "com uma pergunta de menu."

)





PROMPT_CORRECAO_FINAL_INTERROGATIVO = (

    "Reescreva sua última resposta.\n"

    "Mantenha exatamente o mesmo significado, o mesmo tom formal e as mesmas "

    "informações.\n"

    "A nova versão NÃO pode terminar com um ponto de interrogação.\n"

    "Transforme o fechamento interrogativo em uma afirmação, conclusão, "

    "observação ou recomendação, sem transformar o restante do texto em "

    "uma pergunta.\n"

    "Não explique a correção nem comente sobre ela. Entregue somente a "

    "resposta final, em português do Brasil."

)












def termina_com_pergunta(texto):

    return bool(texto) and texto.strip().endswith("?")











# Corrige final interrogativo
def corrigir_final_interrogativo(mensagens, resposta_texto, max_tokens=1024):
    """Corrige final interrogativo."""
    padrao = r"(?is)(?<=[.!])\s+(?:gostaria|deseja|quer|posso ajudar)\b[^.!?]*\?\s*$"
    enxuta = re.sub(padrao, "", resposta_texto or "").rstrip()
    return enxuta or resposta_texto



def chamar_llm_conversa(mensagens):
    from comandos.hermes_agent import conversar
    versao = llm_local.versao_cancelamento()
    if llm_local.servidor_local_ativo():
        resposta = conversar(mensagens)
        if llm_local.versao_cancelamento() != versao: return None
        if resposta:
            return resposta


    if elevenlabs_eco is None:

        return chamar_llm(mensagens)

    try:

        ajustadas, max_tokens, modo_curto = elevenlabs_eco.ajustar_llm(mensagens, 1024)

    except Exception:

        log.exception("Falha ao ajustar o LM Studio para o modo curto.")

        return chamar_llm(mensagens)

    resposta = chamar_llm(ajustadas, max_tokens=max_tokens)

    if modo_curto and resposta:

        try:

            resposta = elevenlabs_eco.aparar_resposta(resposta)

        except Exception:

            log.exception("Falha ao aparar a resposta curta.")

    return resposta









# Gera etapas plano
def gerarEtapasPlano(objetivo):

    if not isinstance(objetivo, str) or not objetivo.strip():

        return []

    prompt = (

        "Divida o objetivo em 3 a 8 etapas concretas e seguras. "

        "Retorne somente uma etapa por linha numerada. Não execute ações, "

        "não invente dados ausentes e não inclua introdução.\nObjetivo: "

        + objetivo[:1000]

    )

    resposta = chamar_llm_conversa([{"role": "user", "content": prompt}])

    if not resposta:

        return []

    etapas = []

    for linha in resposta.splitlines():

        etapa = re.sub(r"^\s*(?:\d+[.)]|[-*])\s*", "", linha).strip()

        if etapa and len(etapa) > 3:

            etapas.append(etapa[:500])

    return etapas[:8]








async def conversar(texto, permitir_acesso_codigo=True):

    if not isinstance(permitir_acesso_codigo, bool):

        permitir_acesso_codigo = False

    if llm_local.requisicao_bloqueada():

        return ""

    normalPlano = re.sub(r"^jarvis[,:]?\s*", "", memoria.normalizarMemoria(texto).strip())

    pedidoPlano = any(normalPlano.startswith(prefixo) for prefixo in ("planeje ", "planejar ", "divida em etapas ", "crie um plano para "))

    if pedidoPlano:

        objetivo = re.sub(r"(?i)^\s*(?:jarvis[,:]?\s*)?(?:planeje|planejar|divida em etapas|crie um plano para)\s*", "", texto).strip(" .!?")

        etapasTexto = await asyncio.to_thread(gerarEtapasPlano, objetivo)

        if etapasTexto:

            planoId = memoria.salvarPlano(objetivo, etapasTexto)

            if planoId:

                respostaPlano = "Plano local salvo, senhor.\n" + "\n".join(f"{indice}. {etapa}" for indice, etapa in enumerate(etapasTexto, 1)) + f"\n\nPlano {planoId}. As etapas ficam registradas para retomada; qualquer ação será executada somente pelo comando correspondente."

                memoria.registrar_mensagem("user", texto)

                memoria.registrar_mensagem("assistant", respostaPlano)

                return respostaPlano

    respostaControle, semMemoria = processarControleMemoria(texto)

    if respostaControle is not None:

        memoria.registrar_mensagem("user", texto)

        historicoControle = memoria.obter_historico_recente(1, incluir_ids=True)

        if semMemoria and historicoControle:

            memoria.marcarMensagemSemMemoria(historicoControle[-1]["id"])

        memoria.registrar_mensagem("assistant", respostaControle)

        return respostaControle

    contexto = await obter_contexto_conversa()

    mensagens = (

        [montar_prompt_sistema(texto)] + contexto + [{"role": "user", "content": texto}]

    )



    versao_cancelamento = llm_local.versao_cancelamento()
    resposta_texto = await asyncio.to_thread(chamar_llm_conversa, mensagens)


    if resposta_texto and parece_falsa_recusa(resposta_texto):

        log.warning("Falsa recusa detectada, tentando novamente com reforço.")

        mensagens_reforco = mensagens + [

            {"role": "assistant", "content": resposta_texto},

            {"role": "user", "content": PROMPT_CORRECAO_FALSA_RECUSA},

        ]

        resposta_texto = await asyncio.to_thread(chamar_llm_conversa, mensagens_reforco)



    if (

        resposta_texto

        and "<" not in resposta_texto

        and termina_com_pergunta(resposta_texto)

    ):

        log.info("Resposta terminou em pergunta; solicitando fechamento afirmativo.")

        resposta_texto = await asyncio.to_thread(

            corrigir_final_interrogativo, mensagens, resposta_texto

        )



    if resposta_texto is None:
        if llm_local.versao_cancelamento() != versao_cancelamento:
            return ""
        log.warning("LM Studio indisponível ao responder a conversa: %s", llm_local.ultimo_erro() or "sem detalhe adicional")
        return "Não consegui acessar o LM Studio. Confira a URL e o servidor em Configurações da IA local e veja se o Qwen3-8B está carregado."





    resposta_texto = salvarCompromissoDoModelo(texto, resposta_texto)



    correspondencia_modificacao = PADRAO_MODIFICAR_SISTEMA.search(resposta_texto)

    if correspondencia_modificacao:

        if not permitir_acesso_codigo:

            resposta_bloqueio = (

                "A edição do código está disponível apenas no aplicativo local."

            )

            memoria.registrar_mensagem("user", texto)

            memoria.registrar_mensagem("assistant", resposta_bloqueio)

            return resposta_bloqueio

        instrucao = correspondencia_modificacao.group(1).strip()

        if not instrucao:

            return "Não recebi uma instrução válida para alterar o sistema."



        if config.VOZ_ATIVA:

            voz.falar(

                "Ainda não posso reescrever meu próprio código com segurança a partir daqui."

            )



        resultado = (

            "Ainda não tenho um mecanismo automático para reescrever meu próprio "

            f"código com segurança. Fica registrado o pedido: '{instrucao}' — "

            "peça essa alteração pelo app local, onde ela pode ser revisada "

            "antes de entrar em produção."

        )



        memoria.registrar_mensagem("user", texto)

        memoria.registrar_mensagem("assistant", resultado)

        return resultado



    correspondencia_leitura = PADRAO_LER_CODIGO.search(resposta_texto)

    if correspondencia_leitura:

        if not permitir_acesso_codigo:

            resposta_bloqueio = (

                "A leitura do código está disponível apenas no aplicativo local."

            )

            memoria.registrar_mensagem("user", texto)

            memoria.registrar_mensagem("assistant", resposta_bloqueio)

            return resposta_bloqueio

        alvo = correspondencia_leitura.group(1).strip()

        alvo = alvo.strip(".")



        if not alvo:

            alvo = "lista"



        if config.VOZ_ATIVA:

            voz.falar(f"Estou abrindo os olhos para analisar o arquivo {alvo}, senhor.")



        mensagens.append({"role": "assistant", "content": f"Vou ler o {alvo}."})



        resposta_texto = await asyncio.to_thread(chamar_llm_conversa, mensagens)

        if resposta_texto is None:

            resposta_texto = "Não consegui concluir a análise do arquivo agora."



    memoria.registrar_mensagem("user", texto)

    memoria.registrar_mensagem("assistant", resposta_texto)

    registrarEstadoDaConversa(texto)



    if memoria.contar_mensagens_usuario() % MENSAGENS_ENTRE_EXTRACOES == 0:

        agendar_extracao_fatos()



    return resposta_texto





PROMPT_EXTRACAO_FATOS = (

    "Releia a conversa acima. Liste, em português, fatos DURÁVEIS e específicos "

    "sobre a pessoa que valem a pena lembrar em conversas futuras (preferências, "

    "rotina, trabalho, pessoas importantes, planos de longo prazo).\n\n"

    "NÃO liste estados temporários — eles NÃO são fatos duráveis, mesmo que "

    "pareçam importantes no momento. Isso inclui: dores ou sintomas físicos "

    "pontuais (dor de cabeça, cansaço), humor ou emoção do dia (estresse de "

    "hoje, dia ruim), e problemas de uma situação específica que já passou "

    "ou vai passar. Se ficar em dúvida se algo é durável ou passageiro, "

    "prefira não listar.\n\n"

    "Responda SOMENTE com uma lista, uma frase curta por linha, sem numeração "

    "e sem comentário. Se não houver nada digno de nota, responda apenas: NADA."

)











# Extrai fatos em segundo plano
async def extrair_fatos_em_segundo_plano():

    try:

        if memoria.obterAjusteMemoria("memoriaAutomatica", "1") == "0":

            return

        historico = limitarHistoricoMemoria(memoria.obterHistoricoParaMemoria(MENSAGENS_ENTRE_EXTRACOES * 2))

        mensagens = historico + [{"role": "user", "content": PROMPT_EXTRACAO_FATOS}]



        resposta_texto = await asyncio.to_thread(chamar_llm, mensagens)



        if not resposta_texto or resposta_texto.strip().upper() == "NADA":

            return



        for linha in resposta_texto.splitlines():

            fato = linha.strip("- ").strip()

            if fato and fato.upper() != "NADA":

                memoria.salvar_fato(fato)

                memoria.salvarMemoria(fato, classificarMemoria(fato), 0.7, 0.75, motivo="extra\u00edda automaticamente de conversas")



    except Exception:

        log.exception("Falha na extração de fatos em segundo plano.")











# Agenda extracao fatos
def agendar_extracao_fatos():








    def executar_em_thread():

        if not TRAVA_EXTRACAO_FATOS.acquire(blocking=False):

            return

        try:

            asyncio.run(extrair_fatos_em_segundo_plano())

        except Exception:

            log.exception("Falha ao rodar extração de fatos em thread separada.")

        finally:

            TRAVA_EXTRACAO_FATOS.release()



    threading.Thread(target=executar_em_thread, daemon=True).start()





PROMPT_SAUDACAO_PROATIVA = (

    "O senhor acabou de te chamar pelo nome (só disse 'jarvis'), sem completar "

    "com nenhum pedido. Cumprimente-o de forma breve e natural (algo como 'Sim, "

    "senhor?' ou 'Diga, senhor.'), e emende UMA sugestão concreta e específica de "

    "algo que vocês podem fazer agora — pode ser uma melhoria no sistema, revisar "

    "uma tarefa, ou puxar um assunto que vocês já vinham conversando. Use o que "

    "você já sabe sobre ele pra sugestão fazer sentido. No máximo 2 frases, sem "

    "listar várias opções de uma vez."

)












async def saudar_com_sugestao():

    contexto = await obter_contexto_conversa()

    mensagens = (

        [montar_prompt_sistema()]

        + contexto

        + [{"role": "user", "content": PROMPT_SAUDACAO_PROATIVA}]

    )



    resposta_texto = await asyncio.to_thread(chamar_llm, mensagens, 150)



    if resposta_texto is None:

        return "Sim senhor, estou ouvindo."



    memoria.registrar_mensagem("user", "jarvis")

    memoria.registrar_mensagem("assistant", resposta_texto)



    return resposta_texto












async def consolidar_memoria_final():

    try:

        if memoria.obterAjusteMemoria("memoriaAutomatica", "1") == "0":

            return

        historico = limitarHistoricoMemoria(memoria.obterHistoricoParaMemoria(200))

        if not historico:

            return



        mensagens_extracao = historico + [

            {"role": "user", "content": PROMPT_EXTRACAO_FATOS}

        ]

        resposta_texto = await asyncio.to_thread(chamar_llm, mensagens_extracao, 300)



        total_fatos_novos = 0

        if resposta_texto and resposta_texto.strip().upper() != "NADA":

            for linha in resposta_texto.splitlines():

                fato = linha.strip("- ").strip()

                if fato and fato.upper() != "NADA" and memoria.salvar_fato(fato):

                    total_fatos_novos += 1

                    memoria.salvarMemoria(fato, classificarMemoria(fato), 0.7, 0.75, motivo="consolidada no encerramento")



        tokens_historico_completo = sum(estimar_tokens(m["content"]) for m in historico)

        if tokens_historico_completo > ORCAMENTO_TOKENS_HISTORICO:

            await obter_contexto_conversa()



        log.info(

            f"Memória consolidada no desligamento: {total_fatos_novos} fato(s) novo(s) salvo(s)."

        )

    except Exception:

        log.exception("Falha ao consolidar memória no desligamento.")











# Limpa conversa
def limpar_conversa():

    memoria.apagar_conversa()






def classificarMemoria(texto):

    textoNormal = memoria.normalizarMemoria(texto)

    if any(palavra in textoNormal for palavra in ("tarefa pendente", "preciso terminar", "falta fazer", "tenho que terminar", "proximo passo", "conclui a tarefa", "finalizei a tarefa", "tarefa concluida")):

        return "operacional"

    if any(palavra in textoNormal for palavra in ("prefiro", "gosto de", "nao gosto", "prefere", "sempre quero")):

        return "preferencia"

    if any(palavra in textoNormal for palavra in ("projeto", "construindo", "desenvolvendo", "sistema")):

        return "projeto"

    if any(palavra in textoNormal for palavra in ("decidi", "decisao", "vou fazer", "objetivo", "meta")):

        return "decisao"

    return "semantica"





# Registra estado da conversa
def registrarEstadoDaConversa(texto):

    categoria = classificarMemoria(texto)

    if categoria == "operacional":

        memoria.salvarMemoria(texto, categoria, 0.8, 0.7, motivo="estado de tarefa detectado na conversa")






def limitarHistoricoMemoria(historico):

    limite = max(1200, min(ORCAMENTO_TOKENS_HISTORICO, 12000))

    selecionadas = []

    usados = 0

    for item in reversed(historico):

        mensagem = dict(item)

        mensagem["content"] = mensagem["content"][-5000:]

        custo = estimar_tokens(mensagem["content"])

        if usados + custo > limite and selecionadas:

            break

        selecionadas.insert(0, mensagem)

        usados += custo

    return selecionadas





# Processa controle memoria
def processarControleMemoria(texto):
    global notaPendente
    if not isinstance(texto, str):
        return None, False
    normal = re.sub(r"^jarvis[,:]?\s*", "", memoria.normalizarMemoria(texto)).strip(" .!?\t\r\n")
    confirmarNota = normal in {"sim", "pode salvar", "pode salvar isso", "pode salvar a nota", "sim pode salvar", "confirmo", "salvar", "salva"}
    cancelarNota = normal in {"nao", "nao salva", "nao salve", "cancela", "cancelar", "deixa", "nao quero"}
    with notaLock:
        pendente = notaPendente if notaPendente and datetime.now().timestamp() - notaPendente["criado"] < 300 else None
        if notaPendente and pendente is None:
            notaPendente = None
    if pendente and confirmarNota:
        with notaLock:
            if notaPendente is pendente:
                notaPendente = None
        if memoria.salvar_nota_hud(pendente["id"], pendente["area"], pendente["titulo"], pendente["conteudo"]):
            return "Nota salva nas minhas notas.", False
        return "Nao consegui salvar a nota; verifique se ja existe uma nota com esse titulo.", False
    if pendente and cancelarNota:
        with notaLock:
            if notaPendente is pendente:
                notaPendente = None
        return "Certo, nao salvei essa nota.", False
    etapaConcluida = re.search(r"marque etapa (\d+) do plano (\d+) concluida", normal)

    if etapaConcluida:

        atualizou = memoria.concluirEtapaPlano(int(etapaConcluida.group(2)), int(etapaConcluida.group(1)))

        return ("Etapa registrada como concluída, senhor." if atualizou else "Não encontrei essa etapa do plano, senhor."), False

    if any(frase in normal for frase in ("quais planos ativos", "mostre meus planos", "continue o plano")):

        planos = memoria.obterPlanos(10)

        ativos = [plano for plano in planos if plano["estado"] == "ativo"]

        if not ativos:

            return "Não há planos ativos salvos, senhor.", False

        linhasPlano = [f"Plano {plano['id']}: {plano['objetivo']}" for plano in ativos]

        for plano in ativos:

            linhasPlano.extend(f"  {etapa['ordem']}. [{'x' if etapa['estado'] == 'concluida' else ' '}] {etapa['descricao']}" for etapa in plano["etapas"])

        return "Planos em andamento:\n" + "\n".join(linhasPlano), False

    normal = re.sub(r"^jarvis[,:]?\s*", "", normal)

    if normal in ("minhas notas", "mostre minhas notas", "listar notas", "quais sao minhas notas"):

        notas = memoria.listar_notas_hud()

        if not notas:

            return "Ainda nao ha notas salvas.", False

        linhas = [f"{nota['title']}: {nota['body']}" for nota in notas[:15]]

        return "Minhas notas salvas:\n" + "\n".join(linhas), False

    if normal.startswith(("anote ", "anota ", "salve nas notas ", "adicione nas notas ")):
        padraoNota = re.match(r"(?is)^\s*(?:jarvis[,:]?\s*)?(?:salve\s+nas\s+notas|adicione\s+nas\s+notas|anote|anota)(?:\s+que)?\s*[:,]?\s*", texto)
        conteudoNota = texto[padraoNota.end():].strip() if padraoNota else ""
        if not conteudoNota:
            return "Diga o conteudo que devo anotar.", False
        if pendente:
            return "Ainda tenho uma nota aguardando confirmacao. Diga pode salvar ou cancelar antes de criar outra.", False
        tituloNota = re.sub(r"\s+", " ", conteudoNota).split(".", 1)[0][:42].strip()
        idNota = "voz-" + hashlib.sha256(tituloNota.casefold().encode("utf-8")).hexdigest()[:24]
        areaNota = memoria.inferir_area_nota(conteudoNota)
        with notaLock:
            notaPendente = {"id": idNota, "area": areaNota, "titulo": tituloNota, "conteudo": conteudoNota, "criado": datetime.now().timestamp()}
        return f"Anotei para confirmar: {conteudoNota}. Deseja que eu salve isso nas notas? Diga pode salvar ou cancelar.", False
    if normal.startswith(("apague a nota ", "remova a nota ", "exclua a nota ")):

        tituloAlvo = re.sub(r"^(apague|remova|exclua) a nota\s+", "", normal).strip()

        notaAlvo = next((nota for nota in memoria.listar_notas_hud() if memoria.normalizarMemoria(nota["title"]) == tituloAlvo), None)

        if notaAlvo and memoria.remover_nota_hud(notaAlvo["id"]):

            return "Nota removida.", False

        return "Nao encontrei essa nota.", False

    if normal in ("minha agenda", "agenda de hoje", "compromissos de hoje", "o que tenho agendado"):

        agoraLocal = datetime.now()

        hoje = agoraLocal.date().isoformat()

        amanha = (agoraLocal.date() + timedelta(days=1)).isoformat()

        compromissos = memoria.listar_compromissos(20, desde=hoje, ate=amanha)

        if not compromissos:

            return "Sua agenda de hoje esta livre.", False

        linhasAgenda = []

        for item in compromissos:

            momento = datetime.fromisoformat(item["inicio"])

            linhasAgenda.append(f"{momento:%H:%M} ? {item['titulo']}")

        return "Compromissos de hoje:\n" + "\n".join(linhasAgenda), False

    prefixosLembrar = ("lembre disso", "lembre que", "memorize isso", "guarde isso", "lembre", "memorize")

    for prefixo in prefixosLembrar:

        if normal.startswith(prefixo):

            conteudo = texto.strip()

            padrao = re.match(r"(?is)^\s*(?:jarvis[,:]?\s*)?(?:lembre(?:-se)?|memorize|guarde)(?:\s+(?:disso|que|isto))?\s*[:,]?\s*", texto)

            if padrao:

                conteudo = texto[padrao.end():].strip()

            if not conteudo:

                return "Diga a informação que devo manter na memória, senhor.", False

            memoriaId = memoria.salvarMemoria(conteudo, classificarMemoria(conteudo), 1.0, 1.0, motivo="pedido expl\u00edcito do senhor")

            memoria.salvar_fato(conteudo)

            return ("Informação guardada na memória local, senhor." if memoriaId else "Não consegui registrar essa informação na memória, senhor."), False

    if any(frase in normal for frase in ("nao memorize isso", "nao guarde isso", "nao memorize esta conversa", "nao memorize nada")):

        return "Entendido. Esta mensagem ficará somente no histórico e será excluída da extração de memória.", True

    if normal in ("desative a memoria automatica", "desativar memoria automatica", "nao memorize mais automaticamente"):

        memoria.definirAjusteMemoria("memoriaAutomatica", "0")

        return "Memória automática desativada. O histórico continuará sendo mantido.", False

    if normal in ("ative a memoria automatica", "ativar memoria automatica", "volte a memorizar automaticamente"):

        memoria.definirAjusteMemoria("memoriaAutomatica", "1")

        return "Memória automática reativada.", False

    prefixosApagar = ("esqueca ", "apague essa informacao", "remova da memoria")

    if normal.startswith(prefixosApagar):

        trecho = re.sub(r"(?i)^\s*(?:jarvis[,:]?\s*)?(?:esqueca|apague essa informa[cç][aã]o|remova da mem[oó]ria)\s*", "", texto).strip(" .!?\t\r\n")

        if not trecho or memoria.normalizarMemoria(trecho) in ("isso", "aquilo", "essa informacao"):

            anteriores = memoria.obter_historico_recente(4)

            trecho = next((item["content"] for item in reversed(anteriores) if item["role"] == "user" and memoria.normalizarMemoria(item["content"]) != normal), "")

        apagadas = memoria.esquecerMemoria(trecho)

        return (f"Removi {apagadas} memória(s) relacionada(s). O histórico original foi preservado, senhor." if apagadas else "Não encontrei uma memória consolidada correspondente. O histórico bruto permanece disponível, senhor."), False

    rotasConsulta = (

        ("por que voce guardou", "motivo"),

        ("por que guardou", "motivo"),

        ("o que voce lembra sobre", "memoria"),

        ("o que você lembra sobre", "memoria"),

        ("o que lembra sobre", "memoria"),

        ("mostre o historico relacionado a", "historico"),

        ("mostre o histórico relacionado a", "historico"),

        ("historico relacionado a", "historico"),

    )

    for prefixo, modo in rotasConsulta:

        prefixoNormal = memoria.normalizarMemoria(prefixo)

        if normal.startswith(prefixoNormal):

            textoConsulta = re.sub(r"(?i)^\s*jarvis[,:]?\s*", "", texto.strip())

            alvo = textoConsulta[len(prefixo):].strip(" .!?\t\r\n")

            if memoria.normalizarMemoria(alvo) in ("isso", "aquilo", "essa informacao", "essa memoria", "essa memora", "a memoria"):

                itens = memoria.obterMemoriasRecentes(5)

                if modo == "motivo" and itens:

                    linhas = [f"- {item['conteudo']} (registrada em {item['criadaEm'][:10]}; {item['motivo']})" for item in itens]

                    return "Guardei estas informações por serem duráveis, recorrentes ou terem sido solicitadas explicitamente:\n" + "\n".join(linhas), False

                if modo == "memoria" and itens:

                    return "Lembro destas informações:\n" + "\n".join(f"- {item['conteudo']}" for item in itens), False

            if modo == "historico":

                itens = memoria.buscarHistoricoRelacionado(alvo, 10, incluirEsquecidas=True)

                if not itens:

                    return "Não encontrei trechos do histórico relacionados a esse assunto, senhor.", False

                linhas = [f"- {item['role']}: {item['content'][:500]}" for item in itens]

                return "Trechos encontrados no histórico local:\n" + "\n".join(linhas), False

            itens = memoria.buscarMemorias(alvo, 8)

            fatos = memoria.buscar_fatos_relevantes(alvo, 8)

            respostas = [item["conteudo"] for item in itens]

            respostas.extend(fato for fato in fatos if fato not in respostas)

            if modo == "motivo":

                if not itens:

                    return "Não encontrei uma memória consolidada sobre esse assunto, senhor.", False

                linhas = [f"- {item['conteudo']} (registrada em {item['criadaEm'][:10]}; {item['motivo']})" for item in itens]

                return "Guardei estas informações por serem duráveis, recorrentes ou terem sido solicitadas explicitamente:\n" + "\n".join(linhas), False

            if not respostas:

                return "Ainda não encontrei uma memória consolidada sobre esse assunto, senhor.", False

            return "Lembro destas informações:\n" + "\n".join(f"- {item}" for item in respostas[:10]), False

    if normal.startswith(("exporte memoria para obsidian", "exportar memoria para obsidian")):

        destino = memoria.exportarObsidian(config.DATA_DIR / "Obsidian" / "JARVIS")

        return f"A memória foi exportada para {destino}. Abra essa pasta como um cofre no Obsidian.", False

    return None, False
