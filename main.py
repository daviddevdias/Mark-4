import atexit
import os

if os.name == "nt":
    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").split()
    if "--disable-direct-composition" not in flags:
        flags.append("--disable-direct-composition")
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(flags)

from comandos.automacao import video_local
from interface.painel import iniciar_aplicativo

atexit.register(video_local.parar_go2rtc)

# Inicia aplicativo e video local
def main():
    video_local.iniciar()
    iniciar_aplicativo()

if __name__ == "__main__":
    main()
