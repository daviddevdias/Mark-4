

import sys
import time
import urllib.error
import urllib.request

from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config
from comandos.automacao import fala_camera
from interface import voz



TEXTO_PADRAO = " ".join(
    ["Teste de áudio da câmera. Um, dois, três, testando."] * 3
)




def passo(texto):
    print(f"\n>> {texto}")




def main():

    passo("1) Configuração")
    ativa = getattr(config, "CAMERA_FALA_ATIVA", False)
    base = str(getattr(config, "GO2RTC_URL", "http://127.0.0.1:1984")).rstrip("/")
    stream = str(getattr(config, "GO2RTC_STREAM", "a28"))
    print(f"   CAMERA_FALA_ATIVA = {ativa}")
    print(f"   GO2RTC_URL        = {base}")
    print(f"   GO2RTC_STREAM     = {stream}")
    if not ativa:
        print("   PROBLEMA: CAMERA_FALA_ATIVA está desligado. Defina True no config.")
        return


    passo("2) go2rtc responde?")
    try:
        with urllib.request.urlopen(f"{base}/api/streams", timeout=5) as r:
            corpo = r.read().decode("utf-8", "replace")
        print(f"   OK (HTTP {r.status})")
        if f'"{stream}"' not in corpo:
            print(f"   PROBLEMA: o stream '{stream}' não existe no go2rtc.yaml.")
            return
    except Exception as erro:
        print(f"   PROBLEMA: não consegui falar com o go2rtc: {erro}")
        print("   Abra o go2rtc.exe e confira GO2RTC_URL.")
        return


    passo("3) Síntese de voz")
    try:
        texto = " ".join(sys.argv[1:]).strip() or TEXTO_PADRAO
        audio = voz.sintetizar_bytes(texto)
    except Exception as erro:
        print(f"   PROBLEMA: erro ao sintetizar: {erro!r}")
        return
    if not audio:
        print("   PROBLEMA: voz.sintetizar_bytes devolveu vazio (a síntese falhou).")
        return
    audio = fala_camera.preparar_audio(audio)  
    ganho = getattr(config, "CAMERA_FALA_GANHO", 3.0)
    print(f"   OK ({len(audio)} bytes, ganho {ganho})")


    passo("4) Arquivo de áudio")
    fala_camera.PASTA_AUDIO.mkdir(parents=True, exist_ok=True)
    caminho = fala_camera.PASTA_AUDIO / f"fala_{int(time.time() * 1000)}.wav"
    caminho.write_bytes(audio)
    print(f"   OK: {caminho}")


    passo("5) Envio ao go2rtc")
    url = fala_camera.url_api(caminho)
    print(f"   POST {url}")
    pedido = urllib.request.Request(url, method="POST")
    try:
        with urllib.request.urlopen(pedido, timeout=30) as r:
            corpo = r.read().decode("utf-8", "replace")
        print(f"   HTTP {r.status}")
        print(f"   resposta: {corpo[:300] or '(vazia)'}")
        print(
            "\nO go2rtc aceitou o envio. AGORA (nos próximos ~15 s):\n"
            "  1) ouça se a câmera fala;\n"
            f"  2) abra {base}/ e clique em 'info' ao lado de '{stream}': com a "
            "conexão de pé aparecem o produtor com remote_addr e um consumidor;\n"
            "  3) olhe a janela preta do go2rtc: erros do dvrip aparecem lá."
        )
    except urllib.error.HTTPError as erro:
        corpo = erro.read().decode("utf-8", "replace")
        print(f"   PROBLEMA: HTTP {erro.code}: {corpo[:300]}")
    except Exception as erro:
        print(f"   PROBLEMA: {erro!r}")


if __name__ == "__main__":
    main()
