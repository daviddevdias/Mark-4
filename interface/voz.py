
import os
import array
import io
import re
import unicodedata
import wave
import time
import tempfile
import subprocess
import sys
import math
import struct
import logging
import threading
import json
from collections import deque
from pathlib import Path

import requests

import config
from comandos import wake_word

try:
    import pyaudio
except ImportError:
    pyaudio = None

try:
    import speech_recognition as sr
except ImportError:
    sr = None

log = logging.getLogger("mark2.voz")
reconhecedor = sr.Recognizer() if sr is not None else None
if reconhecedor is not None:
    reconhecedor.operation_timeout = 10

TAXA_AMOSTRAGEM = 16000
TAMANHO_BLOCO = 1024
SEGUNDOS_SILENCIO_PARA_PARAR = 0.6
TEMPO_MAXIMO_ESPERA_FALA = 5
try:
    LIMIAR_SILENCIO = int(getattr(config, "LIMIAR_SILENCIO_VOZ", 50))
except (TypeError, ValueError):
    LIMIAR_SILENCIO = 50
LIMIAR_SILENCIO = max(50, min(10_000, LIMIAR_SILENCIO))


class ErroMicrofone(Exception):
    pass


# Calcula rms
def calcular_rms(dados_audio: bytes) -> float:
    if not isinstance(dados_audio, (bytes, bytearray, memoryview)):
        return 0.0
    quantidade_amostras = len(dados_audio) // 2
    if quantidade_amostras == 0:
        return 0.0

    dados_validos = bytes(dados_audio[: quantidade_amostras * 2])
    amostras = struct.unpack(f"<{quantidade_amostras}h", dados_validos)
    soma_quadrados = sum(amostra * amostra for amostra in amostras)
    return math.sqrt(soma_quadrados / quantidade_amostras)


EM_REPRODUCAO = threading.Event()
TRAVA_FALA = threading.RLock()
EM_CAPTURA_FALA = threading.Event()
evento_falando = EM_REPRODUCAO
_RUIDO_CAPTURA = threading.local()


def transcrever_audio(audio):
    return reconhecedor.recognize_google(audio, language="pt-BR").strip()

# Fecha captura
def fechar_captura():
    pass


def escutar(callback_nivel=None, deve_parar=None, callback_texto=None) -> str:
    if pyaudio is None or sr is None or reconhecedor is None:
        log.error("Os componentes de reconhecimento de voz não estão instalados.")
        return ""
    if evento_falando.is_set():
        return ""
    try:
        interface_audio = pyaudio.PyAudio()
    except Exception as erro:
        log.exception("Não foi possível inicializar o sistema de áudio.")
        raise ErroMicrofone(
            f"Não consegui inicializar o sistema de áudio: {erro}"
        ) from erro
    stream = None
    frames = []
    falando = False
    cancelado = False
    blocos_silencio_seguidos = 0
    blocos_para_silencio = max(
        1, int(SEGUNDOS_SILENCIO_PARA_PARAR * TAXA_AMOSTRAGEM / TAMANHO_BLOCO)
    )
    inicio = time.time()

    try:
        try:
            stream = interface_audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=TAXA_AMOSTRAGEM,
                input=True,
                frames_per_buffer=TAMANHO_BLOCO,
            )
        except Exception as erro:
            log.exception(
                "Não foi possível abrir o microfone (pode estar em uso por "
                "outra instância do Mark 2, sem permissão do sistema, ou "
                "sem dispositivo padrão configurado)."
            )
            raise ErroMicrofone(f"Não consegui abrir o microfone: {erro}") from erro

        # Mede o fundo ao iniciar
        calibracao = deque()
        if not hasattr(_RUIDO_CAPTURA, "nivel"):
            calibracao.extend(stream.read(TAMANHO_BLOCO, exception_on_overflow=False) for _ in range(8))
            niveis = sorted(calcular_rms(bloco) for bloco in calibracao)
            _RUIDO_CAPTURA.nivel = niveis[1]
        ruido = _RUIDO_CAPTURA.nivel
        anteriores = deque(maxlen=8)
        while True:
            if evento_falando.is_set():
                cancelado = True
                break
            if deve_parar:
                try:
                    if deve_parar():
                        cancelado = True
                        break
                except Exception:
                    log.exception("Falha no callback de cancelamento de voz.")
                    deve_parar = None
            if not falando and (time.time() - inicio) > TEMPO_MAXIMO_ESPERA_FALA:
                break

            try:
                dados = calibracao.popleft() if calibracao else stream.read(TAMANHO_BLOCO, exception_on_overflow=False)
            except Exception:
                break

            rms = calcular_rms(dados)

            if callback_nivel:
                try:
                    callback_nivel(min(100, int((rms / 3000) * 100)))
                except Exception:
                    log.exception("Falha no callback do nível de áudio.")
                    callback_nivel = None

            limiar = max(250, LIMIAR_SILENCIO, ruido * (1.6 if falando else 2.0) + 70)
            if not falando and rms < limiar:
                ruido = ruido * .98 + rms * .02
                _RUIDO_CAPTURA.nivel = ruido
            if rms > limiar:
                if not falando:
                    frames.extend(anteriores)
                falando = True
                EM_CAPTURA_FALA.set()
                blocos_silencio_seguidos = 0
                frames.append(dados)


            elif falando:
                frames.append(dados)
                blocos_silencio_seguidos += 1
                if blocos_silencio_seguidos > blocos_para_silencio:
                    break
            else:
                anteriores.append(dados)

    except KeyboardInterrupt:
        return "sair"
    except ErroMicrofone:
        raise
    except Exception:
        log.exception("Não foi possível capturar o áudio do microfone.")
        return ""
    finally:
        EM_CAPTURA_FALA.clear()
        if stream is not None:
            try:
                stream.stop_stream()
            except Exception:
                log.exception("Falha ao parar o fluxo do microfone.")
            try:
                stream.close()
            except Exception:
                log.exception("Falha ao fechar o fluxo do microfone.")
        try:
            interface_audio.terminate()
        except Exception:
            log.exception("Falha ao encerrar o sistema de áudio.")

    if cancelado or not frames:
        return ""

    audio_bruto = b"".join(frames)
    audio_para_reconhecimento = sr.AudioData(audio_bruto, TAXA_AMOSTRAGEM, 2)

    try:
        comando = reconhecedor.recognize_google(
            audio_para_reconhecimento, language="pt-BR"
        )
        print(f"[VOCÊ]: {comando}")
        comando = comando.strip()
        if callback_texto:
            callback_texto(comando)
        return comando
    except sr.UnknownValueError:
        return ""
    except sr.RequestError:
        raise ErroMicrofone("Não foi possível conectar ao reconhecimento Google.")



RESPOSTA_ENCERRAMENTO = (
    "Entendido, senhor. Foi um prazer ajudar. Ficarei em espera até ser chamado."
)

NOMES_JARVIS = {
    "jarvis", "jarves", "jarvi", "jarbis", "jarvez", "jervis",
    "gervis", "gerby", "gerbi",
}
CHAMADAS_JARVIS = {"ei", "ok", "ola"}
FRASES_ENCERRAMENTO = {
    "so isso", "e so isso", "era so isso", "nao so isso", "nada mais",
    "isso e tudo", "por enquanto e so", "por enquanto e so isso",
    "por enquanto so isso", "nao preciso de mais nada",
    "nao precisa de mais nada", "nao obrigado", "nao obrigada", "obrigado",
    "obrigada", "obrigado por tudo", "obrigada por tudo", "valeu",
    "pode descansar", "pode parar", "descansa", "descansar",
    "encerrar conversa", "finalizar conversa",
}



# Normaliza fala
def normalizar_fala(texto):
    if not isinstance(texto, str):
        return ""
    valor = unicodedata.normalize("NFD", texto.casefold())
    valor = "".join(c for c in valor if not unicodedata.combining(c))
    valor = re.sub(r"[^a-z0-9\s]", " ", valor)
    valor = re.sub(r"\bjar\s+vis\b", "jarvis", valor)
    return re.sub(r"\s+", " ", valor).strip()



# Remove chamada Jarvis
def remover_chamada_jarvis(texto):
    partes = normalizar_fala(texto).split()
    if partes and partes[0] in CHAMADAS_JARVIS and len(partes) > 1 and partes[1] in NOMES_JARVIS:
        partes = partes[1:]
    if partes and partes[0] in NOMES_JARVIS:
        partes = partes[1:]
    if partes and partes[-1] in NOMES_JARVIS:
        partes = partes[:-1]
        if partes and partes[-1] in CHAMADAS_JARVIS:
            partes = partes[:-1]
    return " ".join(partes)




def frase_encerra_conversa(texto):
    normal = remover_chamada_jarvis(texto)
    if normal in ("obrigado", "obrigada", "muito obrigado", "muito obrigada", "valeu"):
        return False
    return normal in FRASES_ENCERRAMENTO




def com_pergunta_continuidade(resposta):
    if resposta == "SHUTDOWN_SIGNAL":
        return resposta
    if resposta is None:
        return "Não foi possível concluir a operação."
    texto = resposta.strip() if isinstance(resposta, str) else str(resposta).strip()
    return texto or "Operação concluída."




try:
    import elevenlabs_eco as motor

    ELEVENLABS_ECO_DISPONIVEL = True
except Exception as e:
    motor = None
    ELEVENLABS_ECO_DISPONIVEL = False
    print(f"[VOZ] Aviso: não foi possível carregar elevenlabs_eco: {e}")





BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = getattr(config, "DATA_DIR", BASE_DIR / "data")

DATA_DIR = Path(DATA_DIR)
DATA_DIR.mkdir(parents=True, exist_ok=True)

CACHE_DIR = DATA_DIR / "cache_voz"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

TEMP_DIR = DATA_DIR / "temp_voz"
TEMP_DIR.mkdir(parents=True, exist_ok=True)





VOZ_ATIVA = getattr(config, "VOZ_ATIVA", True)

VOZ_INICIAR_AUTOMATICO = getattr(config, "VOZ_INICIAR_AUTOMATICO", True)




def volume_percentual():
    return max(0, min(100, round(float(config.VOLUME_PADRAO) * 100)))



# Define volume percentual
def definir_volume_percentual(valor):
    if isinstance(valor, bool):
        raise ValueError("O volume precisa ser um número entre 0 e 100.")
    try:
        percentual = float(valor)
    except (TypeError, ValueError) as erro:
        raise ValueError("O volume precisa ser um número entre 0 e 100.") from erro
    if not 0 <= percentual <= 100:
        raise ValueError("O volume precisa estar entre 0 e 100.")
    if not config.persistir_valor("volume_padrao", percentual / 100):
        raise OSError("Não foi possível salvar o volume da voz.")
    config.VOLUME_PADRAO = percentual / 100
    return percentual



# Aplica volume temporario
def _aplicar_volume_temporario(caminho_audio):
    """Reduz diferenças de intensidade e aplica o volume escolhido ao WAV temporário."""
    volume = max(0.0, min(1.0, float(config.VOLUME_PADRAO)))
    caminho_audio = Path(caminho_audio)
    temporario = caminho_audio.with_name(caminho_audio.stem + "_volume.wav")
    try:
        with wave.open(str(caminho_audio), "rb") as origem:
            parametros = origem.getparams()
            if parametros.sampwidth != 2 or parametros.comptype != "NONE":
                return
            amostras = array.array("h")
            amostras.frombytes(origem.readframes(parametros.nframes))
        if sys.byteorder != "little":
            amostras.byteswap()
        pico = max((abs(amostra) for amostra in amostras), default=0)
        # Ignora silêncio ao medir a fala; nunca amplifica trechos baixos ou ruído.
        limiar = max(32, pico * 0.01)
        soma = 0
        quantidade = 0
        for amostra in amostras:
            if abs(amostra) >= limiar:
                soma += amostra * amostra
                quantidade += 1
        rms = math.sqrt(soma / quantidade) if quantidade else 0.0
        ganho = min(1.0, 3276.8 / rms if rms else 1.0,
                    19660.2 / pico if pico else 1.0) * volume
        for indice, amostra in enumerate(amostras):
            amostras[indice] = max(-32768, min(32767, round(amostra * ganho)))
        if sys.byteorder != "little":
            amostras.byteswap()
        with wave.open(str(temporario), "wb") as destino:
            destino.setparams(parametros)
            destino.writeframes(amostras.tobytes())
        os.replace(temporario, caminho_audio)
    except (OSError, wave.Error, OverflowError):
        print("[VOZ] Não consegui ajustar o volume do WAV temporário.")
        try:
            temporario.unlink(missing_ok=True)
        except OSError:
            pass





PIPER_EXECUTAVEL = getattr(config, "PIPER_EXECUTAVEL", "piper")
PIPER_LOCAL = Path(sys.executable).resolve().parent / ("piper.exe" if os.name == "nt" else "piper")
if str(PIPER_EXECUTAVEL) == "piper" and PIPER_LOCAL.is_file():
    PIPER_EXECUTAVEL = PIPER_LOCAL
DIRETORIO_MODELOS_PIPER = Path(config.__file__).resolve().parent / "modelos_voz"



def caminhoPiper(valor):
    if not valor:
        return None
    caminho = Path(str(valor)).expanduser()
    if not caminho.is_absolute():
        caminho = Path(config.__file__).resolve().parent / caminho
    return caminho.resolve()



def localizarModeloPiper():
    configurado = caminhoPiper(getattr(config, "PIPER_MODELO", ""))
    if configurado and configurado.is_file():
        return configurado
    encontrados = sorted(DIRETORIO_MODELOS_PIPER.glob("*.onnx"))
    return encontrados[0].resolve() if encontrados else None


PIPER_MODELO = localizarModeloPiper()
PIPER_CONFIG = caminhoPiper(getattr(config, "PIPER_CONFIG", ""))
if PIPER_CONFIG is None and PIPER_MODELO is not None:
    configuracaoAutomatica = Path(str(PIPER_MODELO) + ".json")
    PIPER_CONFIG = configuracaoAutomatica if configuracaoAutomatica.is_file() else None





PLAYER_EXECUTAVEL = getattr(config, "PLAYER_EXECUTAVEL", "")






# Limpa texto
def limpar_texto(texto):
    """Limpa texto."""

    if texto is None:
        return ""

    texto = str(texto).strip()

    if not texto:
        return ""


    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()



# Remove parenteses
def remover_parenteses(texto):
    """Remove parenteses."""

    if not texto:
        return texto

    return re.sub(r"\([^)]*\)", "", texto).strip()







def elevenlabs_configurada():


    if not ELEVENLABS_ECO_DISPONIVEL:
        return False

    try:
        return bool(motor.cfg().get("ativo", False))
    except Exception as e:
        print(f"[VOZ] Erro verificando ElevenLabs: {e}")
        return False




def deve_usar_elevenlabs(texto):


    if not texto:
        return False

    if not ELEVENLABS_ECO_DISPONIVEL:
        return False

    try:
        return bool(motor.deve_falar(texto))
    except TypeError:
        try:
            return bool(motor.deve_falar())
        except Exception as e:
            print(f"[VOZ] Erro verificando ElevenLabs: {e}")
            return False

    except Exception as e:
        print(f"[VOZ] Erro verificando ElevenLabs: {e}")
        return False






# Gera áudio elevenlabs
def gerar_audio_elevenlabs(texto, caminho_saida):
    """Gera áudio elevenlabs."""

    if not ELEVENLABS_ECO_DISPONIVEL:
        return False

    texto = limpar_texto(texto)

    if not texto:
        return False

    try:
        print("[VOZ] Tentando ElevenLabs...")

        sucesso = motor.sintetizar(texto, str(caminho_saida))

        if sucesso:
            print("[VOZ] ElevenLabs OK")
            return True

        print("[VOZ] ElevenLabs falhou. Usando Piper.")
        return False

    except Exception as e:
        print(f"[VOZ] Erro ElevenLabs: {e}")
        return False






# Gera áudio piper
def gerar_audio_piper(texto, caminho_saida):
    texto = limpar_texto(texto)
    if not texto:
        return False
    if PIPER_MODELO is None or not PIPER_MODELO.is_file():
        print("[VOZ] Modelo Piper n?o encontrado em:", DIRETORIO_MODELOS_PIPER)
        return False
    entradaTemp = None
    destino = Path(caminho_saida)
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.unlink(missing_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".txt", dir=str(destino.parent), delete=False) as entrada:
            entrada.write(texto)
            entradaTemp = Path(entrada.name)
        comando = [str(PIPER_EXECUTAVEL), "--model", str(PIPER_MODELO)]
        if PIPER_CONFIG and PIPER_CONFIG.is_file():
            comando.extend(["--config", str(PIPER_CONFIG)])
        comando.extend(["--input_file", str(entradaTemp), "--output_file", str(destino)])
        print("[VOZ] Gerando ?udio com Piper...")
        processo = subprocess.run(comando, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=60, check=False)
        if processo.returncode != 0:
            print("[VOZ] Erro Piper:", processo.stderr)
            return False
        if not destino.is_file() or destino.stat().st_size == 0:
            print("[VOZ] Piper n?o retornou ?udio.")
            return False
        print("[VOZ] Piper OK")
        return True
    except subprocess.TimeoutExpired:
        print("[VOZ] Piper demorou demais.")
        return False
    except FileNotFoundError:
        print("[VOZ] Piper ou modelo n?o encontrado:", PIPER_EXECUTAVEL)
        return False
    except Exception as erro:
        print(f"[VOZ] Erro Piper: {erro}")
        return False
    finally:
        if entradaTemp is not None:
            entradaTemp.unlink(missing_ok=True)



def tocar_audio(caminho_audio):


    caminho_audio = Path(caminho_audio)

    if not caminho_audio.exists():
        print("[VOZ] Arquivo de áudio não existe.")
        return False

    try:
        if os.name == "nt":
            import winsound

            winsound.PlaySound(str(caminho_audio), winsound.SND_FILENAME)

            return True


        if PLAYER_EXECUTAVEL:
            subprocess.run(
                [PLAYER_EXECUTAVEL, str(caminho_audio)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            return True

        players = ["paplay", "aplay"]

        for player in players:
            try:
                subprocess.run(
                    [player, str(caminho_audio)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                return True

            except FileNotFoundError:
                continue

        print("[VOZ] Nenhum player de áudio encontrado.")
        return False

    except Exception as e:
        print(f"[VOZ] Erro reproduzindo áudio: {e}")



# Para fala
VERSAO_PARADA = 0

def parar_fala():
    """Para fala."""
    global VERSAO_PARADA
    VERSAO_PARADA += 1
    if os.name != "nt":
        return False
    try:
        import winsound

        winsound.PlaySound(None, 0)
        return True
    except Exception as erro:
        print(f"[VOZ] Não consegui interromper o áudio: {erro}")
        return False




def sinal_escuta():

    if os.name != "nt":
        return False
    try:
        import winsound

        winsound.Beep(880, 120)
        return True
    except Exception:
        return False







# Serializa falas sem sobreposição
def falar(texto, deve_parar=None, audio_preparado=None, manter_reproducao=False):
    versao = VERSAO_PARADA
    callback = deve_parar
    deve_parar = lambda: versao != VERSAO_PARADA or bool(callback and callback())
    with TRAVA_FALA:
        if deve_parar(): return False
        if audio_preparado is None and not manter_reproducao: return _falar_serial(texto, deve_parar)
        return _falar_serial(texto, deve_parar, audio_preparado, manter_reproducao)

# Reproduz a fala com cancelamento
def _falar_serial(texto, deve_parar=None, audio_preparado=None, manter_reproducao=False):

    if not VOZ_ATIVA:
        print("[VOZ] Voz desativada.")
        return False

    texto = limpar_texto(texto)

    if not texto:
        return False

    print(f"[JARVIS] {texto}")



    try:

        cfg = motor.cfg()

        if cfg.get("remover_parenteses", True):
            texto_limpo = remover_parenteses(texto)
        else:
            texto_limpo = texto

    except Exception:
        texto_limpo = texto

    if not texto_limpo:
        return False



    nome_temp = f"voz_{int(time.time() * 1000)}.wav"

    caminho_temp = TEMP_DIR / nome_temp

    sucesso = False
    if audio_preparado is not None:
        if not isinstance(audio_preparado,bytes) or not audio_preparado: return False
        caminho_temp.write_bytes(audio_preparado)
        sucesso=True
    else:
        if elevenlabs_configurada():
            sucesso = gerar_audio_elevenlabs(texto_limpo, caminho_temp)
        if not sucesso and getattr(config, "VOZ_FALLBACK_PIPER", False):
            sucesso = gerar_audio_piper(texto_limpo, caminho_temp)

    if not sucesso:

        print("[VOZ] ERRO: nenhum sistema de voz funcionou.")

        return False

    if deve_parar and deve_parar():
        caminho_temp.unlink(missing_ok=True)
        return False
    if audio_preparado is None: _aplicar_volume_temporario(caminho_temp)

    limite_captura = time.monotonic() + 1.2
    while not EM_REPRODUCAO.is_set() and EM_CAPTURA_FALA.is_set() and time.monotonic() < limite_captura:
        if deve_parar and deve_parar():
            caminho_temp.unlink(missing_ok=True)
            return False
        time.sleep(.03)
    EM_REPRODUCAO.set()
    try:
        return bool(tocar_audio(caminho_temp))
    finally:
        if not manter_reproducao: EM_REPRODUCAO.clear()
        caminho_temp.unlink(missing_ok=True)






# Sintetiza bytes
def sintetizar_bytes(texto, respeitar_voz_ativa=True):

    if respeitar_voz_ativa and not VOZ_ATIVA:
        return None

    texto = limpar_texto(texto)

    if not texto:
        return None



    try:

        cfg = motor.cfg()

        if cfg.get("remover_parenteses", True):
            texto_limpo = remover_parenteses(texto)
        else:
            texto_limpo = texto

    except Exception:

        texto_limpo = texto

    if not texto_limpo:
        return None



    nome_temp = f"bytes_{time.time_ns()}.wav"

    caminho_temp = TEMP_DIR / nome_temp

    sucesso = False



    if elevenlabs_configurada():
        sucesso = gerar_audio_elevenlabs(texto_limpo, caminho_temp)

    if not sucesso and getattr(config, "VOZ_FALLBACK_PIPER", False):
        sucesso = gerar_audio_piper(texto_limpo, caminho_temp)

    if not sucesso:
        return None



    _aplicar_volume_temporario(caminho_temp)

    try:

        with open(caminho_temp, "rb") as arquivo:

            dados = arquivo.read()

        return dados

    except Exception as e:

        print(f"[VOZ] Erro lendo áudio: {e}")

        return None

    finally:



        try:

            if caminho_temp.exists():
                caminho_temp.unlink()

        except Exception:
            pass






# Sintetiza bytes piper
def sintetizarBytesPiper(texto):
    if not VOZ_ATIVA:
        return None
    texto = limpar_texto(texto)
    if not texto:
        return None
    caminho = TEMP_DIR / f"resumoPiper_{time.time_ns()}.wav"
    try:
        if not gerar_audio_piper(texto, caminho):
            return None
        _aplicar_volume_temporario(caminho)
        return caminho.read_bytes()
    except OSError:
        print("[VOZ] Falha ao preparar fala Piper para o painel.")
        return None
    finally:
        try:
            caminho.unlink(missing_ok=True)
        except OSError:
            pass



def testar_elevenlabs():


    print()
    print("=" * 60)
    print(" TESTE ELEVENLABS")
    print("=" * 60)

    if not ELEVENLABS_ECO_DISPONIVEL:

        print("[TESTE] elevenlabs_eco não está disponível.")

        return False

    try:

        configurado = elevenlabs_configurada()

        print(f"[TESTE] ElevenLabs configurado: {configurado}")

    except Exception as e:

        print(f"[TESTE] Erro verificando configuração: {e}")

    texto = "Teste de áudio do Jarvis."

    caminho = TEMP_DIR / "teste_elevenlabs.wav"

    sucesso = gerar_audio_elevenlabs(texto, caminho)

    if sucesso:

        print("[TESTE] Áudio ElevenLabs gerado com sucesso.")

        print(f"[TESTE] Arquivo: {caminho}")

        tocar_audio(caminho)

        return True

    print("[TESTE] Falha ao gerar áudio.")

    return False







def testar_voz():




    print()
    print("=" * 60)
    print(" TESTE DO SISTEMA DE VOZ")
    print("=" * 60)

    print(f"[TESTE] Voz ativa: {VOZ_ATIVA}")

    print(f"[TESTE] ElevenLabs Eco: " f"{ELEVENLABS_ECO_DISPONIVEL}")

    if ELEVENLABS_ECO_DISPONIVEL:

        try:

            print(f"[TESTE] ElevenLabs configurado: " f"{elevenlabs_configurada()}")

        except Exception as e:

            print(f"[TESTE] Erro: {e}")

    falar("Teste do sistema de voz do Jarvis.")





if __name__ == "__main__":

    testar_voz()
