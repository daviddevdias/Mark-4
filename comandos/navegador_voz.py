import asyncio
import concurrent.futures
import logging
import os
import queue
import re
import threading
import unicodedata
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import config

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

log = logging.getLogger("mark2.navegador_voz")


class NavegadorVoz:

    def __init__(self):
        self.trava = threading.RLock()
        self.fila = queue.Queue()
        self.pronto = threading.Event()
        self.thread = None
        self.falha = None
        self.paginaAtiva = None

    def executar(self, acao, termo=""):
        if config.obter_texto("navegador_modo", "sistema", 30) == "sistema":
            from comandos import navegador_sistema

            with self.trava:
                return navegador_sistema.executar(acao, termo, self.navegadorSistema())
        if async_playwright is None:
            return "A navegação por voz precisa do Playwright e do navegador Chromium instalados."
        if acao in {"fechar", "encerrar", "listar"} and (
            self.thread is None or not self.thread.is_alive()
        ):
            return "Não há navegador aberto pelo Jarvis."
        with self.trava:
            if self.thread is None or not self.thread.is_alive():
                self.pronto.clear()
                self.falha = None
                self.thread = threading.Thread(
                    target=self.iniciar, daemon=True, name="mark2-navegador-voz"
                )
                self.thread.start()
        if not self.pronto.wait(45):
            return "O navegador controlado não respondeu ao iniciar."
        if self.falha:
            return self.falha
        retorno = concurrent.futures.Future()
        self.fila.put((acao, termo, retorno))
        try:
            resultado = retorno.result(timeout=45)
            if acao == "encerrar":
                self.thread.join(timeout=5)
            return resultado
        except concurrent.futures.TimeoutError:
            return "O navegador demorou demais para concluir. Tente novamente."

    def iniciar(self):
        asyncio.run(self.servir())

    # Atende ações do navegador
    async def servir(self):
        playwright = None
        contexto = None
        try:
            playwright = await async_playwright().start()
            perfil = Path(config.DATA_DIR) / "navegador_voz"
            perfil.mkdir(parents=True, exist_ok=True)
            opcoes = {
                "user_data_dir": str(perfil),
                "headless": False,
                "no_viewport": True,
                "chromium_sandbox": True,
                "ignore_default_args": ["--enable-automation"],
                "args": ["--no-first-run", "--no-default-browser-check"],
            }
            navegador = self.navegadorSistema()
            if navegador:
                opcoes["executable_path"] = navegador
            contexto = await playwright.chromium.launch_persistent_context(**opcoes)
            if not contexto.pages:
                await contexto.new_page()
            self.paginaAtiva = contexto.pages[0]
            contexto.on("page", self.marcarPagina)
            contexto.on("close", self.aoFecharContexto)
            self.pronto.set()
            while True:
                acao, termo, retorno = await asyncio.to_thread(self.fila.get)
                try:
                    resultado = await self.aplicar(contexto, acao, termo)
                    retorno.set_result(resultado)
                    if acao == "encerrar":
                        break
                except Exception:
                    log.exception("Falha ao executar ação de navegação por voz.")
                    retorno.set_result(
                        "A página não conseguiu executar essa ação. Tente descrever o alvo com mais precisão."
                    )
        except Exception:
            self.falha = "Não consegui abrir o navegador controlado. Verifique se Chromium, Brave, Chrome ou Edge estão instalados."
            log.exception("Falha ao iniciar o navegador controlado.")
            self.pronto.set()
        finally:
            if contexto is not None:
                contexto.remove_listener("close", self.aoFecharContexto)
            self.paginaAtiva = None
            while not self.fila.empty():
                try:
                    _, _, pendente = self.fila.get_nowait()
                    if not pendente.done():
                        pendente.set_result("Navegador fechado.")
                except queue.Empty:
                    break
            if contexto is not None:
                try:
                    await contexto.close()
                except Exception:
                    log.debug("Falha ao fechar a janela controlada.", exc_info=True)
            if playwright is not None:
                try:
                    await playwright.stop()
                except Exception:
                    pass

    # Encerra fila ao fechar a janela
    def aoFecharContexto(self, *_):
        self.fila.put(("encerrar", "", concurrent.futures.Future()))

    # Localiza o navegador do Windows
    def navegadorSistema(self):
        if os.name != "nt":
            return None
        import winreg

        try:
            chave = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, chave) as entrada:
                progid, _ = winreg.QueryValueEx(entrada, "ProgId")
            with winreg.OpenKey(
                winreg.HKEY_CLASSES_ROOT, str(progid) + r"\shell\open\command"
            ) as entrada:
                comando, _ = winreg.QueryValueEx(entrada, None)
            candidato = re.match(
                r'^\s*(?:"([^"]+\.exe)"|(.+?\.exe))(?:\s|$)',
                str(comando),
                re.IGNORECASE,
            )
            if candidato:
                caminho = os.path.expandvars(candidato.group(1) or candidato.group(2))
                if Path(caminho).is_file():
                    log.info("Navegador padrão selecionado: %s", Path(caminho).name)
                    return caminho
        except OSError:
            pass
        for nome, pasta in (
            ("brave.exe", "BraveSoftware/Brave-Browser/Application"),
            ("msedge.exe", "Microsoft/Edge/Application"),
            ("chrome.exe", "Google/Chrome/Application"),
        ):
            for raiz in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(
                        raiz,
                        rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{nome}",
                    ) as entrada:
                        caminho, _ = winreg.QueryValueEx(entrada, None)
                    if Path(str(caminho).strip('"')).is_file():
                        return str(caminho).strip('"')
                except OSError:
                    continue
            for base in (
                os.environ.get("PROGRAMFILES"),
                os.environ.get("PROGRAMFILES(X86)"),
                os.environ.get("LOCALAPPDATA"),
            ):
                if base and (Path(base) / pasta / nome).is_file():
                    return str(Path(base) / pasta / nome)
        return None

    # Consulta aba ativa do navegador
    def paginaAtual(self, contexto):
        paginas = contexto.pages
        if not paginas:
            return None
        if self.paginaAtiva in paginas:
            return self.paginaAtiva
        self.paginaAtiva = paginas[-1]
        return self.paginaAtiva

    # Marca a aba ativa do navegador
    def marcarPagina(self, pagina):
        self.paginaAtiva = pagina

    async def aplicar(self, contexto, acao, termo):
        paginas = contexto.pages
        pagina = self.paginaAtual(contexto)
        if acao == "encerrar":
            return "Navegador fechado."
        if acao == "listar":
            if not paginas:
                return "Não há abas abertas."
            titulos = [
                f"{i + 1}: {await p.title() or 'Nova aba'}"
                for i, p in enumerate(paginas)
            ]
            return "Abas abertas: " + "; ".join(titulos)
        if acao == "selecionar":
            indice = int(termo) - 1
            if not 0 <= indice < len(paginas):
                return "Essa aba não existe. Diga listar abas para consultar."
            self.paginaAtiva = paginas[indice]
            await self.paginaAtiva.bring_to_front()
            return "Aba " + str(indice + 1) + " selecionada."
        if pagina is None and acao not in {"fechar", "nova"}:
            pagina = await contexto.new_page()
            self.paginaAtiva = pagina
        if acao == "parar":
            await pagina.evaluate("window.stop()")
            return "Carregamento interrompido."
        if acao == "iniciar":
            if pagina is None:
                pagina = await contexto.new_page()
                self.paginaAtiva = pagina
            if pagina.url == "about:blank":
                await pagina.goto("chrome://newtab")
            await pagina.bring_to_front()
            return "Navegador controlado aberto. Diga o que deseja pesquisar ou qual aba quer usar."
        if acao == "nova":
            pagina = await contexto.new_page()
            self.paginaAtiva = pagina
            await pagina.goto("chrome://newtab")
            await pagina.bring_to_front()
            return "Nova aba aberta."
        if acao == "fechar":
            if pagina is None:
                return "Não há aba aberta no navegador controlado."
            await pagina.close()
            self.paginaAtiva = contexto.pages[-1] if contexto.pages else None
            if self.paginaAtiva is not None:
                await self.paginaAtiva.bring_to_front()
            return "Aba fechada."
        if acao in {"proxima", "anterior"}:
            if not paginas:
                await contexto.new_page()
                return "Nova aba aberta."
            atual = paginas.index(pagina)
            destino = (atual + (1 if acao == "proxima" else -1)) % len(paginas)
            self.paginaAtiva = paginas[destino]
            await self.paginaAtiva.bring_to_front()
            return "Aba " + str(destino + 1) + " de " + str(len(paginas)) + "."
        if acao == "voltar":
            await pagina.go_back(wait_until="domcontentloaded", timeout=15000)
            return "Voltei uma página."
        if acao == "avancar":
            await pagina.go_forward(wait_until="domcontentloaded", timeout=15000)
            return "Avancei uma página."
        if acao == "atualizar":
            await pagina.reload(wait_until="domcontentloaded", timeout=20000)
            return "Página atualizada."
        if acao in {"pesquisar", "youtube"}:
            busca = str(termo or "").strip()
            if not busca:
                return "Diga o que devo pesquisar."
            destino = (
                "https://www.youtube.com/results?search_query=" + quote_plus(busca)
                if acao == "youtube"
                else "https://www.google.com/search?q=" + quote_plus(busca)
            )
            await pagina.goto(destino, wait_until="domcontentloaded", timeout=25000)
            await pagina.bring_to_front()
            return "Resultados para " + busca + " abertos no navegador controlado."
        if acao == "abrir":
            destino = urlparse(str(termo or "").strip())
            if (
                destino.scheme not in {"http", "https"}
                or not destino.hostname
                or destino.username
                or destino.password
            ):
                return "Informe um endereço de site iniciado por https."
            await pagina.goto(
                destino.geturl(), wait_until="domcontentloaded", timeout=25000
            )
            await pagina.bring_to_front()
            return "Site aberto no navegador controlado."
        if acao == "video":
            busca = str(termo or "").strip()
            if not busca:
                return "Diga o nome do vídeo que devo procurar."
            atual = urlparse(pagina.url)
            if (atual.hostname or "").lower() not in {
                "youtube.com",
                "www.youtube.com",
                "m.youtube.com",
            } or "/results" not in atual.path:
                await pagina.goto(
                    "https://www.youtube.com/results?search_query=" + quote_plus(busca),
                    wait_until="domcontentloaded",
                    timeout=25000,
                )
            await pagina.wait_for_load_state("domcontentloaded", timeout=15000)
            links = pagina.get_by_role(
                "link", name=re.compile(re.escape(busca), re.IGNORECASE)
            )
            total = await links.count()
            candidatos = {}
            for indice in range(min(total, 30)):
                link = links.nth(indice)
                url = await link.get_attribute("href")
                nome = re.sub(r"\s+", " ", (await link.inner_text()).strip())
                if url and "/watch" in url and nome:
                    candidatos[url.split("&", 1)[0]] = (nome, link)
            if not candidatos:
                return "Não encontrei um vídeo com esse nome. Diga parte do título que aparece nos resultados."
            normalBusca = self.normalizar(busca)
            exatos = {
                url: item
                for url, item in candidatos.items()
                if self.normalizar(item[0]) == normalBusca
            }
            possiveis = exatos or candidatos
            if len(possiveis) > 1:
                titulos = list(
                    dict.fromkeys(item[0] for item in list(possiveis.values())[:4])
                )
                return (
                    "Encontrei mais de um vídeo. Diga o título completo: "
                    + "; ".join(titulos)
                )
            titulo, link = next(iter(possiveis.values()))
            await link.click(timeout=12000)
            return "Abri o vídeo: " + titulo
        return "Não reconheci essa ação de navegação."

    @staticmethod
    def normalizar(texto):
        valor = unicodedata.normalize("NFKD", str(texto or "").casefold())
        return "".join(
            letra for letra in valor if not unicodedata.combining(letra)
        ).strip()


navegador = NavegadorVoz()
