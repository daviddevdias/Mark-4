

import shutil
import sys
import tempfile

from . import motor


# Inicia o aplicativo Jarvis
def main(argumentos):
    comando = argumentos[0] if argumentos else "status"

    if comando == "status":
        for chave, valor in motor.status().items():
            print(f"{chave:>22}: {valor}")
    elif comando == "listar":
        falas = motor.listar_falas()
        print(f"{len(falas)} fala(s) salva(s) em {motor.PASTA_CACHE}\n")
        for arquivo, texto in falas.items():
            print(f"{arquivo}\n    {texto}")
    elif comando == "testar":
        texto = " ".join(argumentos[1:]).strip() or "Sistemas online, senhor."
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as arq:
            caminho = arq.name
        ok = motor.sintetizar(texto, caminho)
        print(f"Gerou áudio com ElevenLabs: {ok} ({caminho})")
        print(f"Gasto estimado: {len(texto) * motor.cfg()['custo_por_caractere']:.0f} créditos")
    elif comando == "zerar":
        motor.zerar_contador()
        print("Contador local de gasto zerado.")
    elif comando == "limpar-cache":
        shutil.rmtree(motor.PASTA_CACHE, ignore_errors=True)
        motor.ARQ_INDICE.unlink(missing_ok=True)
        print("Cache de áudio apagado.")
    else:
        print(__doc__)


main(sys.argv[1:])
