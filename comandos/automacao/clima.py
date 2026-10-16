import random
import logging
import threading
import time
from datetime import datetime

import requests

log = logging.getLogger("mark2.clima")


class ClimaIndisponivel(Exception):
    pass

URL_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

TEMPO_VIDA_CACHE_SEGUNDOS = 600

CIDADE_NOME = "Esteio, RS"

CIDADE_FALADA = "Esteio"

LATITUDE = -29.8577

LONGITUDE = -51.1789

FUSO_HORARIO = "America/Sao_Paulo"

DIAS_PREVISAO = 7

VARIAVEIS_ATUAIS = (
    "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,"
    "precipitation,rain,showers,weather_code,cloud_cover,pressure_msl,"
    "surface_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m"
)

VARIAVEIS_HORARIAS = (
    "temperature_2m,relative_humidity_2m,dew_point_2m,apparent_temperature,"
    "precipitation_probability,precipitation,rain,showers,weather_code,"
    "cloud_cover,visibility,wind_speed_10m,wind_direction_10m,"
    "wind_gusts_10m,uv_index"
)

VARIAVEIS_DIARIAS = (
    "weather_code,temperature_2m_max,temperature_2m_min,"
    "apparent_temperature_max,apparent_temperature_min,sunrise,sunset,"
    "daylight_duration,sunshine_duration,uv_index_max,uv_index_clear_sky_max,"
    "precipitation_sum,rain_sum,showers_sum,precipitation_hours,"
    "precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,"
    "wind_direction_10m_dominant,shortwave_radiation_sum,"
    "et0_fao_evapotranspiration"
)

cache_clima = None

hora_ultimo_cache = 0.0

cache_lock = threading.RLock()

CONDICOES_WMO = {
    0: ("☀️", "Céu limpo"),
    1: ("🌤️", "Predominantemente limpo"),
    2: ("⛅", "Parcialmente nublado"),
    3: ("☁️", "Nublado"),
    45: ("🌫️", "Neblina"),
    48: ("🌫️", "Neblina com geada"),
    51: ("🌦️", "Garoa fraca"),
    53: ("🌦️", "Garoa moderada"),
    55: ("🌦️", "Garoa forte"),
    56: ("🌧️", "Garoa congelante fraca"),
    57: ("🌧️", "Garoa congelante forte"),
    61: ("🌧️", "Chuva fraca"),
    63: ("🌧️", "Chuva moderada"),
    65: ("🌧️", "Chuva forte"),
    66: ("🌧️", "Chuva congelante fraca"),
    67: ("🌧️", "Chuva congelante forte"),
    71: ("🌨️", "Neve fraca"),
    73: ("🌨️", "Neve moderada"),
    75: ("🌨️", "Neve forte"),
    77: ("🌨️", "Grãos de neve"),
    80: ("🌦️", "Pancadas de chuva fracas"),
    81: ("🌧️", "Pancadas de chuva moderadas"),
    82: ("⛈️", "Pancadas de chuva fortes"),
    85: ("🌨️", "Pancadas de neve fracas"),
    86: ("🌨️", "Pancadas de neve fortes"),
    95: ("⛈️", "Trovoada"),
    96: ("⛈️", "Trovoada com granizo"),
    99: ("⛈️", "Trovoada com granizo forte"),
}

CODIGOS_CHUVA = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}

CODIGOS_TROVOADA = {95, 96, 99}

CODIGOS_NEVE = {71, 73, 75, 77, 85, 86}

CODIGOS_PRECIPITACAO = CODIGOS_CHUVA | CODIGOS_TROVOADA | CODIGOS_NEVE

CEU_FALADO = {
    0: "limpo",
    1: "predominantemente limpo",
    2: "parcialmente nublado",
    3: "nublado",
}

PREVISAO_FALADA = {
    1: "céu predominantemente limpo",
    2: "céu parcialmente nublado",
    3: "tempo nublado",
}

PONTOS_CARDEAIS = (
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO",
)

NOMES_DIRECAO = (
    "norte", "nor-nordeste", "nordeste", "lés-nordeste",
    "leste", "lés-sudeste", "sudeste", "su-sudeste",
    "sul", "su-sudoeste", "sudoeste", "oés-sudoeste",
    "oeste", "oés-noroeste", "noroeste", "nor-noroeste",
)

DIAS_SEMANA = (
    "segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
    "sexta-feira", "sábado", "domingo",
)

MESES = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)

ABERTURAS = (
    "Senhor, ",
    "Se me permite, senhor, ",
    "Informo, senhor, que ",
    "Atualizando, senhor, ",
    "Conforme solicitado, senhor, ",
)



def agora():
    return datetime.now()



def abertura():
    return random.choice(ABERTURAS)



def capitalizar(texto):
    return texto[:1].upper() + texto[1:]



def unir(pecas):
    if len(pecas) == 1:
        return pecas[0]
    return ", ".join(pecas[:-1]) + ", e " + pecas[-1]



def plural(quantidade, singular, plural_):
    return f"{quantidade} {singular if quantidade == 1 else plural_}"



def graus(valor):
    n = round(valor)
    if n < 0:
        return "menos " + plural(-n, "grau", "graus")
    return plural(n, "grau", "graus")



def porcento(valor):
    return f"{round(valor)} por cento"



def milimetros(valor):
    return f"{valor:.1f}".replace(".", ",") + " milímetros"



def quilometros_hora(valor):
    return f"{round(valor)} quilômetros por hora"



def media(valores):
    return sum(valores) / len(valores)



def das(hora):
    hora = hora % 24
    if hora == 0:
        return "da meia-noite"
    if hora == 1:
        return "da 1 hora"
    return f"das {hora} horas"



def horario_falado(hora, minuto=0):
    if hora == 0:
        texto = "à meia-noite"
    elif hora == 1:
        texto = "à 1 hora"
    else:
        texto = f"às {hora} horas"
    if minuto:
        texto += " e " + plural(minuto, "minuto", "minutos")
    return texto



def horario_de_texto(texto):
    momento = datetime.fromisoformat(texto)
    return horario_falado(momento.hour, momento.minute)



def duracao_falada(segundos):
    horas = int(segundos // 3600)
    minutos = int((segundos % 3600) // 60)
    return plural(horas, "hora", "horas") + " e " + plural(minutos, "minuto", "minutos")



def indice_cardeal(graus_vento):
    return round(graus_vento / 22.5) % 16



def graus_para_direcao_cardeal(graus_vento):
    return PONTOS_CARDEAIS[indice_cardeal(graus_vento)]



def direcao_falada(graus_vento):
    return NOMES_DIRECAO[indice_cardeal(graus_vento)]



def forca_vento(kmh):
    if kmh < 20:
        return "uma brisa leve"
    if kmh < 40:
        return "vento moderado"
    if kmh < 60:
        return "vento forte"
    if kmh < 90:
        return "vento muito forte"
    return "ventania"



def nivel_uv(indice):
    if indice < 3:
        return "baixo"
    if indice < 6:
        return "moderado"
    if indice < 8:
        return "alto"
    if indice < 11:
        return "muito alto"
    return "extremo"



def qualidade_umidade(umidade):
    if umidade < 30:
        return "ar seco"
    if umidade < 60:
        return "ar confortável"
    if umidade < 85:
        return "ar úmido"
    return "ar saturado"



def visibilidade_falada(metros):
    km = metros / 1000
    if km >= 10:
        return "visibilidade ampla, acima de 10 quilômetros"
    return f"visibilidade de {km:.1f} quilômetros".replace(".", ",").replace(",0 ", " ")


# Consulta dados openmeteo
def obter_dados_openmeteo(forcar_atualizacao=False):
    global cache_clima, hora_ultimo_cache
    with cache_lock:
        if (
            not forcar_atualizacao
            and cache_clima is not None
            and time.monotonic() - hora_ultimo_cache < TEMPO_VIDA_CACHE_SEGUNDOS
        ):
            return cache_clima
        try:
            resposta = requests.get(
                URL_OPEN_METEO,
                params={
                    "latitude": LATITUDE,
                    "longitude": LONGITUDE,
                    "current": VARIAVEIS_ATUAIS,
                    "hourly": VARIAVEIS_HORARIAS,
                    "daily": VARIAVEIS_DIARIAS,
                    "timezone": FUSO_HORARIO,
                    "forecast_days": DIAS_PREVISAO,
                },
                timeout=8,
            )
            resposta.raise_for_status()
            dados = resposta.json()
            if not isinstance(dados, dict) or not all(
                isinstance(dados.get(chave), dict)
                for chave in ("current", "hourly", "daily")
            ):
                raise ClimaIndisponivel("A resposta do serviço de clima é inválida.")
        except requests.RequestException as erro:
            if cache_clima is not None:
                log.warning("Open-Meteo indisponível; usando os últimos dados em cache: %s", erro)
                return cache_clima
            log.warning("Open-Meteo indisponível e sem dados em cache: %s", erro)
            raise ClimaIndisponivel("Não foi possível consultar o serviço de clima.") from erro
        cache_clima = dados
        hora_ultimo_cache = time.monotonic()
        return cache_clima



def indice_hora(dados, momento):
    return dados["hourly"]["time"].index(momento.strftime("%Y-%m-%dT%H:00"))



def hora_de(horario, posicao):
    return int(horario["time"][posicao][11:13])



def indices_do_dia(indice_dia):
    return range(indice_dia * 24, indice_dia * 24 + 24)



def serie_do_dia(dados, chave, indice_dia):
    inicio = indice_dia * 24
    return dados["hourly"][chave][inicio : inicio + 24]



def hora_do_extremo(dados, indice_dia, maior):
    serie = serie_do_dia(dados, "temperature_2m", indice_dia)
    alvo = max(serie) if maior else min(serie)
    return serie.index(alvo)



def chovendo_na_hora(horario, posicao):
    return (
        horario["precipitation"][posicao] >= 0.1
        or horario["weather_code"][posicao] in CODIGOS_PRECIPITACAO
    )


# Consulta clima atual
def obter_clima_atual(forcar_atualizacao=False):
    dados = obter_dados_openmeteo(forcar_atualizacao)
    atual = dados["current"]
    horario = dados["hourly"]
    posicao = indice_hora(dados, agora())
    codigo = atual["weather_code"]
    icone, descricao = CONDICOES_WMO[codigo]
    vento = atual["wind_speed_10m"]
    rajada = atual["wind_gusts_10m"]
    return {
        "temperatura": atual["temperature_2m"],
        "sensacao_termica": atual["apparent_temperature"],
        "umidade_pct": atual["relative_humidity_2m"],
        "pressao_hpa": atual["surface_pressure"],
        "pressao_nivel_mar_hpa": atual["pressure_msl"],
        "precipitacao_mm": atual["precipitation"],
        "chuva_mm": atual["rain"],
        "pancadas_mm": atual["showers"],
        "nuvens_pct": atual["cloud_cover"],
        "eh_dia": bool(atual["is_day"]),
        "vento_kmh": f"{vento:.1f} km/h",
        "rajada_kmh": f"{rajada:.1f} km/h",
        "vento_graus": atual["wind_direction_10m"],
        "vento_direcao": graus_para_direcao_cardeal(atual["wind_direction_10m"]),
        "ponto_orvalho": horario["dew_point_2m"][posicao],
        "visibilidade_m": horario["visibility"][posicao],
        "uv_indice": horario["uv_index"][posicao],
        "probabilidade_chuva_pct": horario["precipitation_probability"][posicao],
        "codigo": codigo,
        "descricao": descricao,
        "icone": icone,
        "cidade": CIDADE_NOME,
        "atualizado_em": atual["time"],
    }


# Consulta previsao dia
def obter_previsao_dia(indice_dia, forcar_atualizacao=False):
    dados = obter_dados_openmeteo(forcar_atualizacao)
    diario = dados["daily"]
    codigo = diario["weather_code"][indice_dia]
    icone, descricao = CONDICOES_WMO[codigo]


    def valor(chave):
        return diario[chave][indice_dia]

    return {
        "data": valor("time"),
        "codigo": codigo,
        "icone": icone,
        "descricao": descricao,
        "maxima": valor("temperature_2m_max"),
        "minima": valor("temperature_2m_min"),
        "sensacao_maxima": valor("apparent_temperature_max"),
        "sensacao_minima": valor("apparent_temperature_min"),
        "chance_chuva_pct": valor("precipitation_probability_max"),
        "chuva_mm": valor("precipitation_sum"),
        "chuva_liquida_mm": valor("rain_sum"),
        "pancadas_mm": valor("showers_sum"),
        "horas_chuva": valor("precipitation_hours"),
        "vento_max_kmh": valor("wind_speed_10m_max"),
        "rajada_max_kmh": valor("wind_gusts_10m_max"),
        "vento_dominante_graus": valor("wind_direction_10m_dominant"),
        "vento_dominante": graus_para_direcao_cardeal(
            valor("wind_direction_10m_dominant")
        ),
        "uv_max": valor("uv_index_max"),
        "uv_max_ceu_limpo": valor("uv_index_clear_sky_max"),
        "nascer_sol": valor("sunrise"),
        "por_sol": valor("sunset"),
        "duracao_dia_s": valor("daylight_duration"),
        "duracao_sol_s": valor("sunshine_duration"),
        "radiacao_mj": valor("shortwave_radiation_sum"),
        "evapotranspiracao_mm": valor("et0_fao_evapotranspiration"),
    }



def estado_falado(codigo):
    descricao = CONDICOES_WMO[codigo][1].lower()
    if codigo in CEU_FALADO:
        return f"o céu está {CEU_FALADO[codigo]} em {CIDADE_FALADA}"
    if codigo in CODIGOS_NEVE:
        return f"está nevando em {CIDADE_FALADA}, {descricao}"
    if codigo in CODIGOS_CHUVA:
        return f"está chovendo em {CIDADE_FALADA}, {descricao}"
    return f"há {descricao} em {CIDADE_FALADA}"



def previsao_falada(codigo):
    if codigo in PREVISAO_FALADA:
        return f"a previsão é de {PREVISAO_FALADA[codigo]}"
    return f"a previsão é de {CONDICOES_WMO[codigo][1].lower()}"



def frase_chuva_hoje(dados, chovendo_agora):
    horario = dados["hourly"]
    posicao = indice_hora(dados, agora())
    fim = min(len(horario["time"]), posicao + 24)
    if chovendo_agora:
        for j in range(posicao + 1, fim):
            if not chovendo_na_hora(horario, j):
                return f"a chuva deve cessar por volta {das(hora_de(horario, j))}{' de amanhã' if j >= 24 else ''}"
        return "a chuva deve persistir pelas próximas 24 horas"
    for j in range(posicao + 1, fim):
        if chovendo_na_hora(horario, j):
            return f"há previsão de chuva a partir {das(hora_de(horario, j))}{' de amanhã' if j >= 24 else ''}"
    return "não há previsão de chuva nas próximas 24 horas"



def conselho(chuva, trovoada, maxima, minima, uv, rajada):
    sugestoes = []
    if trovoada:
        sugestoes.append(
            random.choice(
                (
                    "sugiro evitar áreas abertas durante as tempestades",
                    "com trovoadas à vista, recomendo desconectar os aparelhos mais sensíveis",
                )
            )
        )
    if chuva:
        sugestoes.append(
            random.choice(
                (
                    "recomendo levar um guarda-chuva",
                    "um guarda-chuva seria uma escolha prudente",
                    "é aconselhável não sair sem um guarda-chuva",
                )
            )
        )
    if maxima >= 33:
        sugestoes.append("convém manter a hidratação em dia")
    if uv >= 8:
        sugestoes.append("o protetor solar é indispensável")
    if minima <= 8:
        sugestoes.append("um agasalho será bem-vindo")
    if rajada >= 60:
        sugestoes.append("convém recolher objetos soltos")
    if not sugestoes:
        return capitalizar(
            random.choice(
                (
                    "o tempo está do nosso lado",
                    "não vejo objeções meteorológicas ao seu dia",
                    "as condições são favoráveis, nada que exija precauções especiais",
                )
            )
            + ", senhor."
        )
    return capitalizar(" e ".join(sugestoes[:2])) + ", senhor."


# Gera resumo clima
def gerar_resumo_clima():
    dados = obter_dados_openmeteo()
    momento = agora()
    atual = dados["current"]
    hoje = obter_previsao_dia(0)
    chovendo = atual["weather_code"] in CODIGOS_PRECIPITACAO
    topo = (
        f"{abertura()}{estado_falado(atual['weather_code'])}, "
        f"{horario_falado(momento.hour, momento.minute)}, "
        f"a temperatura é de {graus(atual['temperature_2m'])}, "
        f"a mínima de hoje é de {graus(hoje['minima'])}, "
        f"e a máxima, de {graus(hoje['maxima'])}."
    )
    return f"{topo} {capitalizar(frase_chuva_hoje(dados, chovendo))}, senhor."


# Gera resumo completo
def gerar_resumo_completo():
    dados = obter_dados_openmeteo()
    momento = agora()
    posicao = indice_hora(dados, momento)
    atual = dados["current"]
    horario = dados["hourly"]
    hoje = obter_previsao_dia(0)
    codigo = atual["weather_code"]
    chovendo = codigo in CODIGOS_PRECIPITACAO

    topo = (
        f"{abertura()}{estado_falado(codigo)}, "
        f"{horario_falado(momento.hour, momento.minute)}, "
        f"a temperatura é de {graus(atual['temperature_2m'])}, "
        f"com sensação térmica de {graus(atual['apparent_temperature'])}, "
        f"a mínima de hoje é de {graus(hoje['minima'])}, "
        f"e a máxima, de {graus(hoje['maxima'])}."
    )

    hora_maxima = hora_do_extremo(dados, 0, True)
    if hora_maxima > momento.hour:
        topo += f" A máxima deve ocorrer por volta {das(hora_maxima)}."

    chuva = []
    if atual["precipitation"] > 0:
        chuva.append(
            f"já foram registrados {milimetros(atual['precipitation'])} na última hora"
        )
    chuva.append(frase_chuva_hoje(dados, chovendo))
    proximas = horario["precipitation_probability"][posicao + 1 : posicao + 7]
    chuva.append(
        f"a probabilidade de chuva nas próximas 6 horas é de {porcento(max(proximas))}"
    )
    restante = sum(horario["precipitation"][posicao + 1 : 24])
    if restante >= 0.1:
        chuva.append(
            f"devem acumular mais {milimetros(restante)} até o fim do dia"
        )
    if hoje["chuva_mm"] >= 0.1:
        chuva.append(
            f"o total do dia chega a {milimetros(hoje['chuva_mm'])}, "
            f"distribuídos em {plural(round(hoje['horas_chuva']), 'hora', 'horas')} de precipitação"
        )

    atmosfera = [
        f"a umidade relativa é de {porcento(atual['relative_humidity_2m'])}, {qualidade_umidade(atual['relative_humidity_2m'])}",
        f"o ponto de orvalho é de {graus(horario['dew_point_2m'][posicao])}",
        f"a pressão é de {round(atual['surface_pressure'])} hectopascais na superfície, e {round(atual['pressure_msl'])} ao nível do mar",
        f"a cobertura de nuvens é de {porcento(atual['cloud_cover'])}",
        visibilidade_falada(horario["visibility"][posicao]),
    ]

    velocidade = atual["wind_speed_10m"]
    if velocidade < 6:
        vento = [f"o vento está calmo, a {quilometros_hora(velocidade)}"]
    else:
        vento = [
            f"{forca_vento(velocidade)} de {direcao_falada(atual['wind_direction_10m'])}, a {quilometros_hora(velocidade)}"
        ]
    vento.append(f"com rajadas de até {quilometros_hora(atual['wind_gusts_10m'])}")
    vento.append(
        f"a máxima do dia é de {quilometros_hora(hoje['vento_max_kmh'])}, com rajadas de até {quilometros_hora(hoje['rajada_max_kmh'])}, predominantemente de {direcao_falada(hoje['vento_dominante_graus'])}"
    )

    nascer = datetime.fromisoformat(hoje["nascer_sol"])
    por = datetime.fromisoformat(hoje["por_sol"])
    sol = []
    if momento < nascer:
        sol.append(
            f"o sol nasce {horario_falado(nascer.hour, nascer.minute)}, e se põe {horario_falado(por.hour, por.minute)}"
        )
    elif momento < por:
        sol.append(f"o sol se põe {horario_falado(por.hour, por.minute)}")
    else:
        sol.append(f"o sol se pôs {horario_falado(por.hour, por.minute)}")
    sol.append(
        f"o dia tem {duracao_falada(hoje['duracao_dia_s'])} de luz solar, com cerca de {duracao_falada(hoje['duracao_sol_s'])} de sol efetivo"
    )
    sol.append(
        f"o índice ultravioleta máximo é de {round(hoje['uv_max'])}, considerado {nivel_uv(hoje['uv_max'])}"
    )
    if atual["is_day"]:
        sol.append(
            f"neste momento, ele está em {round(horario['uv_index'][posicao])}"
        )

    final = conselho(
        chovendo or hoje["chance_chuva_pct"] >= 60,
        codigo in CODIGOS_TROVOADA,
        hoje["maxima"],
        hoje["minima"],
        hoje["uv_max"],
        hoje["rajada_max_kmh"],
    )

    return " ".join(
        (
            topo,
            f"Quanto à precipitação, {unir(chuva)}.",
            f"No que diz respeito à atmosfera, {unir(atmosfera)}.",
            f"Sobre o vento, {unir(vento)}.",
            f"Quanto ao sol, {unir(sol)}.",
            final,
        )
    )



def diferenca_graus(antigo, novo, rotulo):
    delta = round(novo - antigo)
    if delta == 0:
        return f"a {rotulo} será praticamente igual à de hoje, em {graus(novo)}"
    sentido = "mais quente" if delta > 0 else "mais fria"
    return f"a {rotulo} será {plural(abs(delta), 'grau', 'graus')} {sentido}, em {graus(novo)}"



def diferencas(indice_antigo, indice_novo):
    antigo = obter_previsao_dia(indice_antigo)
    novo = obter_previsao_dia(indice_novo)
    pecas = [
        diferenca_graus(antigo["maxima"], novo["maxima"], "máxima"),
        diferenca_graus(antigo["minima"], novo["minima"], "mínima"),
    ]

    delta_chance = novo["chance_chuva_pct"] - antigo["chance_chuva_pct"]
    if abs(delta_chance) < 10:
        pecas.append(
            f"a chance de chuva é parecida com a de hoje, em {porcento(novo['chance_chuva_pct'])}"
        )
    elif delta_chance > 0:
        pecas.append(
            f"a chance de chuva sobe de {round(antigo['chance_chuva_pct'])} para {porcento(novo['chance_chuva_pct'])}"
        )
    else:
        pecas.append(
            f"a chance de chuva cai de {round(antigo['chance_chuva_pct'])} para {porcento(novo['chance_chuva_pct'])}"
        )

    delta_volume = novo["chuva_mm"] - antigo["chuva_mm"]
    if abs(delta_volume) >= 1:
        verbo = "aumenta" if delta_volume > 0 else "diminui"
        pecas.append(
            f"o volume de chuva {verbo} de {milimetros(antigo['chuva_mm'])} para {milimetros(novo['chuva_mm'])}"
        )

    delta_rajada = novo["rajada_max_kmh"] - antigo["rajada_max_kmh"]
    if abs(delta_rajada) >= 10:
        verbo = "sobem" if delta_rajada > 0 else "caem"
        pecas.append(
            f"as rajadas máximas {verbo} de {round(antigo['rajada_max_kmh'])} para {quilometros_hora(novo['rajada_max_kmh'])}"
        )

    delta_uv = novo["uv_max"] - antigo["uv_max"]
    if abs(delta_uv) >= 2:
        verbo = "sobe" if delta_uv > 0 else "cai"
        pecas.append(
            f"o índice ultravioleta {verbo} de {round(antigo['uv_max'])} para {round(novo['uv_max'])}"
        )

    delta_sol = round((novo["duracao_sol_s"] - antigo["duracao_sol_s"]) / 3600)
    if abs(delta_sol) >= 1:
        sentido = "a mais" if delta_sol > 0 else "a menos"
        pecas.append(
            f"teremos cerca de {plural(abs(delta_sol), 'hora', 'horas')} {sentido} de sol efetivo"
        )
    return pecas


# Gera resumo previsao amanha
def gerar_resumo_previsao_amanha():
    amanha = obter_previsao_dia(1)
    chuva = f"chance de chuva de {porcento(amanha['chance_chuva_pct'])}"
    if amanha["chuva_mm"] >= 0.1:
        chuva += f", com cerca de {milimetros(amanha['chuva_mm'])} previstos"
    else:
        chuva += ", sem acumulado significativo previsto"
    return (
        f"{abertura()}amanh\u00e3 em {CIDADE_FALADA}, {previsao_falada(amanha['codigo'])}, "
        f"com m\u00ednima de {graus(amanha['minima'])} e m\u00e1xima de {graus(amanha['maxima'])}. "
        f"{chuva.capitalize()}."
    )



def comparar_amanha_com_hoje():
    return f"{abertura()}em comparação com hoje, {unir(diferencas(0, 1))}."


# Gera previsao estendida
def gerar_previsao_estendida(dias=6):
    dias = min(dias, DIAS_PREVISAO - 1)
    linhas = []
    for indice in range(1, dias + 1):
        previsao = obter_previsao_dia(indice)
        data = datetime.fromisoformat(previsao["data"])
        linhas.append(
            f"{capitalizar(DIAS_SEMANA[data.weekday()])}, {data.day} de {MESES[data.month - 1]}, "
            f"{previsao['descricao'].lower()}, "
            f"mínima de {graus(previsao['minima'])}, "
            f"máxima de {graus(previsao['maxima'])}, "
            f"{porcento(previsao['chance_chuva_pct'])} de chance de chuva, "
            f"e vento de até {quilometros_hora(previsao['vento_max_kmh'])}."
        )
    return linhas
