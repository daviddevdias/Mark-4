import asyncio

import logging

import re

import threading

from pathlib import Path

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

import config

log = logging.getLogger("mark2.whatsapp_bot")

DIR_SESSAO = Path(__file__).resolve().parent.parent / "sessao_whatsapp"

PADRAO_NUMERO = re.compile(r"^\d{7,15}$")

SELETOR_CAIXA_TEXTO = (
    'footer div[contenteditable="true"][role="textbox"], '
    'footer div[contenteditable="true"], '
    'div[contenteditable="true"][data-tab="10"]'
)

TRAVA_SESSAO = threading.Lock()



# Envia mensagem playwright
async def enviar_mensagem_playwright(numero, mensagem):
    if async_playwright is None:
        return "Falha ao enviar. O suporte de automação do WhatsApp não está instalado."
    if not TRAVA_SESSAO.acquire(blocking=False):
        return "Falha ao enviar. Outro envio pelo WhatsApp ainda está em andamento."
    try:
        return await realizar_envio_mensagem(numero, mensagem)
    finally:
        TRAVA_SESSAO.release()




async def realizar_envio_mensagem(numero, mensagem):
    if not isinstance(numero, str) or not isinstance(mensagem, str):
        return "Falha ao enviar. O número e a mensagem precisam ser textos válidos."

    numero = "".join(caractere for caractere in numero if caractere.isdigit())
    mensagem = mensagem.strip()
    if not PADRAO_NUMERO.fullmatch(numero):
        return "Falha ao enviar. O número precisa ter entre 7 e 15 dígitos."
    if not mensagem:
        return "Falha ao enviar. A mensagem está vazia."
    if len(mensagem) > 4096:
        return "Falha ao enviar. A mensagem excede o limite de 4.096 caracteres."

    url = f"https://web.whatsapp.com/send?phone={numero}"
    try:
        DIR_SESSAO.mkdir(parents=True, exist_ok=True)
    except OSError:
        log.error("Não foi possível preparar a sessão do WhatsApp.", exc_info=True)
        return "Falha ao enviar. Não foi possível preparar a sessão do WhatsApp."

    async with async_playwright() as p:
        browser = None

        try:
            browser = await p.chromium.launch_persistent_context(
                user_data_dir=DIR_SESSAO,
                headless=bool(getattr(config, "WHATSAPP_HEADLESS", False)),
            )
            page = browser.pages[0] if browser.pages else await browser.new_page()
            log.info("Iniciando automação do WhatsApp Web.")
            await page.goto(url, timeout=60000, wait_until="domcontentloaded")

            log.info("Aguardando carregamento da interface e caixa de texto...")
            await page.wait_for_selector(
                SELETOR_CAIXA_TEXTO, state="visible", timeout=60000
            )

            caixa_texto = page.locator(SELETOR_CAIXA_TEXTO).last
            await caixa_texto.click()

            await caixa_texto.fill(mensagem)
            conteudo_atual = await caixa_texto.inner_text()
            if not conteudo_atual.strip():
                log.error("A mensagem não foi preenchida na caixa de texto a tempo.")
                return "Falha ao enviar. O texto não carregou na caixa a tempo, tente novamente."

            await asyncio.sleep(0.5)
            await page.keyboard.press("Enter")

            log.info("Aguardando confirmação de que a mensagem foi enviada...")

            mensagem_enviada = False

            for _ in range(20):
                conteudo_apos_envio = await caixa_texto.inner_text()
                if not conteudo_apos_envio.strip():
                    mensagem_enviada = True
                    break
                await asyncio.sleep(0.5)

            if not mensagem_enviada:
                log.error(
                    "A caixa de texto continuou preenchida, o envio pode não ter sido concluído."
                )
                return (
                    "Falha ao enviar. A mensagem parece não ter sido disparada a tempo."
                )

            await asyncio.sleep(2)

            log.info("Mensagem disparada com sucesso na interface.")
            return "Mensagem enviada com sucesso pelo WhatsApp."

        except Exception as e:
            log.error(f"Erro na automação do WhatsApp: {e}")
            return "Falha ao enviar. O WhatsApp demorou a carregar, o botão mudou ou o QR Code não foi lido."

        finally:
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    log.warning(
                        "Falha ao fechar o navegador do WhatsApp.", exc_info=True
                    )