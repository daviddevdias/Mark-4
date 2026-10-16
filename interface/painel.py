import time
import json
import sys
import asyncio
import html
import logging
import os
import re
import threading
import queue
from pathlib import Path
from PySide6.QtCore import QThread, Signal, QTimer, Qt, QUrl, QEvent, QByteArray
from PySide6.QtGui import QColor, QTextDocument
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QLabel,
    QFrame,
    QMessageBox,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QInputDialog,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
)

import config

from comandos import wake_word, llm_local, linguagem
from comandos.controller import processar_comando
import comandos.controller as controller
from comandos.automacao import clima, presenca, rotina_saida, seguranca_stark
from . import voz
from . import servidor_remoto

log = logging.getLogger("mark2.painel")



# Para e aguardar thread
def parar_e_aguardar_thread(thread, timeout_ms=15000):
    if thread is None or not thread.isRunning():
        return True
    parar = getattr(thread, "parar", None)
    if callable(parar):
        parar()
    else:
        thread.requestInterruption()
    return thread.wait(timeout_ms)



class ThreadProcessamentoBackend(QThread):
    resposta_pronta = Signal(str)




    def __init__(self, comando: str):
        super().__init__()
        self.comando = comando




    def run(self):
        try:
            acao_musica = servidor_remoto.identificar_comando_musica(self.comando)
            if acao_musica:
                try:
                    enviado = servidor_remoto.definir_comando_midia_telefone(
                        acao_musica
                    )
                except Exception:
                    log.error(
                        "Falha ao mandar o comando de música pro celular.",
                        exc_info=True,
                    )
                    enviado = False
                resposta = (
                    servidor_remoto.RESPOSTAS_ACAO_MUSICA_TELEFONE.get(
                        acao_musica, "Prontinho."
                    )
                    if enviado
                    else "Não consegui mandar o comando pro celular agora."
                )
                if config.VOZ_ATIVA:
                    threading.Thread(target=voz.falar, args=(resposta,), daemon=True, name="mark2-resposta-voz").start()
                servidor_remoto.registrar_interacao_local(
                    self.comando, resposta, "painel-pc"
                )
                self.resposta_pronta.emit(resposta)
                return

            encerrando_conversa = voz.frase_encerra_conversa(self.comando)
            resposta = asyncio.run(processar_comando(self.comando))
            if not isinstance(resposta, str) or not resposta:
                resposta = "Comando não reconhecido."
            if resposta != "SHUTDOWN_SIGNAL" and config.VOZ_ATIVA:
                threading.Thread(target=voz.falar, args=(resposta,), daemon=True, name="mark2-resposta-voz").start()
            if resposta != "SHUTDOWN_SIGNAL":
                servidor_remoto.ESCUTA_VOZ_ATIVAR.set()
                servidor_remoto.ESCUTA_VOZ_ENCERRAR.set()
            servidor_remoto.registrar_interacao_local(
                self.comando, resposta, "painel-pc"
            )
        except Exception:
            log.error("Falha ao processar o comando do painel.", exc_info=True)
            resposta = "Ocorreu um erro ao processar o comando."
            servidor_remoto.registrar_interacao_local(
                self.comando, resposta, "painel-pc"
            )
        self.resposta_pronta.emit(resposta)



class ThreadRotinaSaida(QThread):
    resposta_pronta = Signal(str)




    def run(self):
        try:
            resposta = rotina_saida.executar_rotina_saida()
            if not isinstance(resposta, str) or not resposta:
                resposta = "Rotina de saída concluída."
            servidor_remoto.registrar_evento_rotina("saida", "painel-pc", resposta)
        except Exception:
            log.error("Falha ao executar a rotina de saída.", exc_info=True)
            resposta = "Falha ao executar a rotina de saída."
        self.resposta_pronta.emit(resposta)



class ThreadTarefas(QThread):
    tarefa_pendente = Signal(dict)




    def __init__(self, intervalo_segundos: int = 30):
        super().__init__()
        self.intervalo_segundos = intervalo_segundos
        self.ativo = True




    def run(self):
        while self.ativo and not self.isInterruptionRequested():

            for _ in range(self.intervalo_segundos):
                if not self.ativo or self.isInterruptionRequested():
                    break
                self.msleep(1000)




    def parar(self):
        self.ativo = False
        self.requestInterruption()





def contem_wake_word(texto: str) -> bool:
    return wake_word.ativado(texto)



# Remove wake word
def remover_wake_word(texto: str) -> str:
    return wake_word.remover(texto)










JANELA_CONVERSA_S = 15



JANELA_CONTINUACAO_S = 0



class ThreadEscutaVoz(QThread):
    resposta_pronta = Signal(str, str)
    nivel_atualizado = Signal(int)
    encerrar_sistema = Signal()




    def __init__(self):
        super().__init__()
        self.ativo = True
        self.parada_fila = threading.Event()
        self.janela_ate = 0.0
        self.nota_ate = 0.0
        self.pausado = False




    def falar_resposta(self, resposta):
        concluido = threading.Event()

        def executar():
            try:
                voz.falar(resposta, deve_parar=lambda: not self.ativo)
            finally:
                concluido.set()
        threading.Thread(target=executar, daemon=True, name="mark2-fala-escuta").start()
        while self.ativo and not self.isInterruptionRequested():
            if concluido.wait(0.1):
                break


    @property
    def aguardando_jarvis(self):
        return True



    @aguardando_jarvis.setter
    def aguardando_jarvis(self, valor):
        self.janela_ate = 0.0


    # Abre janela
    def abrir_janela(self, segundos):
        self.janela_ate = 0.0




    def _publicar(self, **campos):
        try:
            servidor_remoto.ESTADO_ESCUTA_PC.update(campos)
        except Exception:
            pass


    # Emite nivel
    def _emitir_nivel(self, valor):
        self._publicar(
            nivel=valor,
            pico=max(servidor_remoto.ESTADO_ESCUTA_PC.get("pico", 0), valor),
            ocupado=False,
            pausado=self.pausado,
            janela=not self.aguardando_jarvis,
        )
        self.nivel_atualizado.emit(valor)



    def _sinalizar_escuta(self):
        self.abrir_janela(0)
        self._publicar(ativo=True, erro="", ocupado=False, nivel=0,
                       pausado=self.pausado, janela=False)
        resposta = "Às ordens, senhor."
        if config.VOZ_ATIVA:
            self.falar_resposta(resposta)
        servidor_remoto.registrar_interacao_local("Jarvis", resposta, "voz-pc", usuario_registrado=True)
        self.resposta_pronta.emit("Mark 2", resposta)




    # Emite texto
    def _emitir_texto(self, texto):
        self._publicar(texto_ouvido=texto, transcricao_parcial=True,
                       transcricao_ts=time.time())


    def run(self):
        self.fila_comandos = queue.Queue(maxsize=8)
        self.worker_comandos = threading.Thread(target=self._processar_fila, daemon=True, name="mark2-comandos-voz")
        self.worker_comandos.start()
        self._publicar(ativo=True, erro="", ocupado=False, dono=id(self))
        try:
            while self.ativo and not self.isInterruptionRequested():
                if voz.EM_REPRODUCAO.is_set():
                    voz.fechar_captura()
                    self.msleep(40)
                    continue
                try:
                    comando = voz.escutar(callback_nivel=self._emitir_nivel, callback_texto=self._emitir_texto,
                        deve_parar=lambda: not self.ativo or self.isInterruptionRequested() or voz.EM_REPRODUCAO.is_set())
                    if not comando:
                        continue
                    self._publicar(erro="")
                    self._aceitar_transcricao(comando)
                except voz.ErroMicrofone as erro:
                    self._publicar(erro=str(erro))
                    self.msleep(1000)
        finally:
            self.ativo = False
            self.parada_fila.set()
            self.worker_comandos.join(timeout=2)
            voz.fechar_captura()
            self._publicar(ativo=False, nivel=0, ocupado=False)


    def _aceitar_transcricao(self, comando):
        if not comando or not self.ativo:
            return
        servidor_remoto.registrar_fala_ouvida(comando)
        texto_nota = comando
        limpa = remover_wake_word(comando)
        if self.nota_ate > time.monotonic():
            self.nota_ate = 0
            if linguagem.chave(limpa) != "cancelar nota" and not linguagem.comando_direto(limpa):
                texto_nota = "anotar " + limpa
        if re.fullmatch(r"(?:anotar|anote|criar(?: uma)? nota|crie(?: uma)? nota|salvar(?: uma)? nota)", limpa, re.IGNORECASE):
            self.nota_ate = time.monotonic() + 90
        aceito = texto_nota != comando or contem_wake_word(comando) or linguagem.comando_direto(comando) or linguagem.chave(comando) in ("eai", "e ai", "oi", "ola", "alo", "cheguei em casa")
        self._publicar(texto_ouvido=comando, transcricao_parcial=False,
                       transcricao_ts=time.time(), comando_reconhecido=aceito)
        if aceito:
            try:
                self.fila_comandos.put_nowait((texto_nota, llm_local.versao_cancelamento()))
            except queue.Full:
                self.resposta_pronta.emit("Sistema", "Fila de comandos cheia; tente novamente.")

    # Processa fila
    def _processar_fila(self):
        while self.ativo and not self.parada_fila.is_set():
            try:
                comando, versao_pedido = self.fila_comandos.get(timeout=.1)
                if llm_local.versao_cancelamento() != versao_pedido: continue
                if self.pausado:
                    config.definir_voz_ativa(True)
                    self.pausado = False
                llm_local.bloquear_requisicao(not linguagem.autoriza_ia_voz(comando))
                comando = remover_wake_word(comando)
                if not comando:
                    self._sinalizar_escuta()
                    continue

                self._publicar(ocupado=True, nivel=0)
                print(f"[ENVIADO]: {comando}")
                self.resposta_pronta.emit("Você", comando)

                acao_musica = servidor_remoto.identificar_comando_musica(comando)
                if acao_musica:
                    try:
                        enviado = servidor_remoto.definir_comando_midia_telefone(
                            acao_musica
                        )
                    except Exception:
                        log.error(
                            "Falha ao mandar o comando de música pro celular.",
                            exc_info=True,
                        )
                        enviado = False
                    resposta = (
                        servidor_remoto.RESPOSTAS_ACAO_MUSICA_TELEFONE.get(
                            acao_musica, "Prontinho."
                        )
                        if enviado
                        else "Não consegui mandar o comando pro celular agora."
                    )
                    self.resposta_pronta.emit("Mark 2", resposta)
                    servidor_remoto.registrar_interacao_local(comando, resposta, "voz-pc", usuario_registrado=True)
                    if config.VOZ_ATIVA and self.ativo:
                        self.falar_resposta(resposta)
                    self.abrir_janela(0)
                    continue

                encerrando_conversa = voz.frase_encerra_conversa(comando)

                resposta = (
                    voz.RESPOSTA_ENCERRAMENTO
                    if encerrando_conversa
                    else asyncio.run(controller.processar_comando(comando))
                )
                if llm_local.versao_cancelamento() != versao_pedido: continue
                if not isinstance(resposta, str) or not resposta:
                    resposta = "Comando não reconhecido."
                if encerrando_conversa:
                    resposta = voz.RESPOSTA_ENCERRAMENTO
                else:
                    resposta = voz.com_pergunta_continuidade(resposta)
                if not self.ativo or self.isInterruptionRequested():
                    break
                servidor_remoto.registrar_interacao_local(comando, resposta, "voz-pc", usuario_registrado=True)
                if resposta != "SHUTDOWN_SIGNAL":
                    self.resposta_pronta.emit("Mark 2", resposta)
                    if config.VOZ_ATIVA:
                        self.falar_resposta(resposta)
                    if encerrando_conversa:
                        self.aguardando_jarvis = True
                    else:
                        self.abrir_janela(0)
                else:
                    self.resposta_pronta.emit("Sistema", "Encerrando sistema.")
                    self.aguardando_jarvis = True
                if resposta == "SHUTDOWN_SIGNAL":
                    self.ativo = False
                    self.encerrar_sistema.emit()
            except queue.Empty:
                continue
            except Exception:
                log.exception("Falha no comando de voz")
                self._publicar(ocupado=False)
        self._publicar(ocupado=False)


    def parar(self):
        self.ativo = False
        self.parada_fila.set()
        self.requestInterruption()



class DialogConfiguracoes(QDialog):




    def __init__(self, janela_principal):
        super().__init__(janela_principal)
        self.janela_principal = janela_principal
        self.setWindowTitle("Mark 2 - Configurações")
        self.resize(480, 550)
        self.setStyleSheet(janela_principal.styleSheet())
        self.construir_elementos_interface()
        self.carregar_token_salvo()
        self.carregar_contatos_salvos()




    def construir_elementos_interface(self):
        layout_principal = QVBoxLayout(self)
        layout_principal.setContentsMargins(20, 20, 20, 20)
        layout_principal.setSpacing(15)

        layout_principal.addLayout(self.criar_secao_api())
        layout_principal.addWidget(self.criar_linha_separadora())
        layout_principal.addLayout(self.criar_secao_acesso_remoto())
        layout_principal.addWidget(self.criar_linha_separadora())
        layout_principal.addLayout(self.criar_secao_contatos())



    # Cria secao API
    def criar_secao_api(self) -> QHBoxLayout:
        layout_api = QHBoxLayout()
        label_api = QLabel("SmartThings Token:")

        self.input_token = QLineEdit()
        self.input_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_token.setPlaceholderText("Cole sua chave de API aqui...")

        botao_salvar_token = QPushButton("Salvar")
        botao_salvar_token.clicked.connect(self.salvar_token)

        layout_api.addWidget(label_api)
        layout_api.addWidget(self.input_token)
        layout_api.addWidget(botao_salvar_token)
        return layout_api



    # Cria linha separadora
    def criar_linha_separadora(self) -> QFrame:
        linha = QFrame()
        linha.setFrameShape(QFrame.Shape.HLine)
        linha.setStyleSheet("background-color: #30363d;")
        return linha



    # Cria secao acesso remoto
    def criar_secao_acesso_remoto(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        label = QLabel("Token do painel remoto:")
        self.input_token_remoto = QLineEdit()
        self.input_token_remoto.setReadOnly(True)
        self.input_token_remoto.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_token_remoto.setText(config.TOKEN_REMOTO)
        botao_copiar = QPushButton("Copiar")
        botao_copiar.clicked.connect(self.copiar_token_remoto)
        layout.addWidget(label)
        layout.addWidget(self.input_token_remoto)
        layout.addWidget(botao_copiar)
        return layout




    def copiar_token_remoto(self):
        QApplication.clipboard().setText(config.TOKEN_REMOTO)
        QMessageBox.information(
            self, "Token copiado", "Token do painel remoto copiado."
        )



    # Carrega token salvo
    def carregar_token_salvo(self):
        token_salvo = config.configuracoes_locais.get("smartthings_token", "")
        if token_salvo:
            self.input_token.setText(token_salvo)
            self.janela_principal.adicionar_log(
                "Sistema", "Token do SmartThings carregado com sucesso."
            )



    # Salva token
    def salvar_token(self):
        novo_token = self.input_token.text().strip()

        if config.definir_smartthings_token(novo_token):
            QMessageBox.information(
                self, "Sucesso", "Token salvo nas configurações locais."
            )
            self.janela_principal.adicionar_log(
                "Sistema", "Chave de API do SmartThings atualizada."
            )
        else:
            QMessageBox.warning(
                self, "Erro", "Não foi possível salvar o arquivo de configuração."
            )



    # Cria secao contatos
    def criar_secao_contatos(self) -> QVBoxLayout:
        layout_contatos = QVBoxLayout()

        label_contatos = QLabel(
            f"Contatos do WhatsApp (máx. {config.MAX_CONTATOS_WHATSAPP}):"
        )
        layout_contatos.addWidget(label_contatos)

        self.lista_contatos = QListWidget()
        layout_contatos.addWidget(self.lista_contatos)

        layout_inputs_contato = QHBoxLayout()

        self.input_nome_contato = QLineEdit()
        self.input_nome_contato.setPlaceholderText("Nome do contato...")

        self.input_numero_contato = QLineEdit()
        self.input_numero_contato.setPlaceholderText("Número (com DDI e DDD)...")

        botao_adicionar_contato = QPushButton("Adicionar")
        botao_adicionar_contato.clicked.connect(self.adicionar_contato)

        botao_remover_contato = QPushButton("Remover")
        botao_remover_contato.clicked.connect(self.remover_contato_selecionado)

        botao_editar_contato = QPushButton("Editar")
        botao_editar_contato.clicked.connect(self.editar_nome_contato)

        layout_inputs_contato.addWidget(self.input_nome_contato)
        layout_inputs_contato.addWidget(self.input_numero_contato)
        layout_inputs_contato.addWidget(botao_adicionar_contato)
        layout_inputs_contato.addWidget(botao_remover_contato)
        layout_inputs_contato.addWidget(botao_editar_contato)

        layout_contatos.addLayout(layout_inputs_contato)

        botao_importar_contatos = QPushButton("Importar contatos (.vcf)")
        botao_importar_contatos.clicked.connect(self.importar_contatos)
        layout_contatos.addWidget(botao_importar_contatos)

        return layout_contatos



    # Carrega contatos salvos
    def carregar_contatos_salvos(self):
        self.lista_contatos.clear()
        contatos_salvos = config.listar_contatos_whatsapp()
        for nome_contato, numero_contato in contatos_salvos.items():
            item = QListWidgetItem(f"{nome_contato} - {numero_contato}")
            item.setData(1000, nome_contato)
            item.setData(1001, numero_contato)
            self.lista_contatos.addItem(item)




    def adicionar_contato(self):
        nome_contato = self.input_nome_contato.text().strip()
        numero_contato = self.input_numero_contato.text().strip()

        if not nome_contato or not numero_contato:
            QMessageBox.warning(self, "Erro", "Preencha o nome e o número do contato.")
            return

        sucesso, mensagem = config.adicionar_contato_whatsapp(
            nome_contato, numero_contato
        )

        if sucesso:
            self.input_nome_contato.clear()
            self.input_numero_contato.clear()
            self.carregar_contatos_salvos()
            self.janela_principal.adicionar_log("Sistema", mensagem)
        else:
            QMessageBox.warning(self, "Erro", mensagem)



    # Remove contato selecionado
    def remover_contato_selecionado(self):
        item_selecionado = self.lista_contatos.currentItem()

        if not item_selecionado:
            QMessageBox.warning(self, "Erro", "Selecione um contato para remover.")
            return

        nome_contato = item_selecionado.data(1000)
        sucesso, mensagem = config.remover_contato_whatsapp(nome_contato)

        if sucesso:
            self.carregar_contatos_salvos()
            self.janela_principal.adicionar_log("Sistema", mensagem)
        else:
            QMessageBox.warning(self, "Erro", mensagem)




    def editar_nome_contato(self):
        item_selecionado = self.lista_contatos.currentItem()

        if not item_selecionado:
            QMessageBox.warning(self, "Erro", "Selecione um contato para editar.")
            return

        nome_atual = item_selecionado.data(1000)
        numero_atual = item_selecionado.data(1001)

        novo_nome, confirmado = QInputDialog.getText(
            self, "Editar nome do contato", "Novo nome:", QLineEdit.Normal, nome_atual
        )

        if not confirmado or not novo_nome.strip():
            return

        sucesso, mensagem = config.renomear_contato_whatsapp(
            nome_atual, novo_nome.strip(), numero_atual
        )

        if sucesso:
            self.carregar_contatos_salvos()
            self.janela_principal.adicionar_log("Sistema", mensagem)
        else:
            QMessageBox.warning(self, "Erro", mensagem)




    def importar_contatos(self):
        caminho_arquivo, _ = QFileDialog.getOpenFileName(
            self, "Selecionar arquivo de contatos", "", "vCard (*.vcf)"
        )

        if not caminho_arquivo:
            return

        total_importados, mensagem = config.importar_contatos_vcf(caminho_arquivo)

        self.carregar_contatos_salvos()
        self.janela_principal.adicionar_log("Sistema", mensagem)
        QMessageBox.information(self, "Importação concluída", mensagem)



class DialogDocumentoTarefa(QDialog):




    def __init__(self, janela_principal, tarefa: dict, iniciar_em_edicao: bool = False):
        super().__init__(janela_principal)
        self.janela_principal = janela_principal
        self.id_tarefa = tarefa["id"]
        self.nome_tarefa = tarefa["nome"]
        self.conteudo_atual = tarefa["conteudo"] or ""
        self.modo_edicao = False

        self.setWindowTitle(f"Mark 2 - Documento: {self.nome_tarefa}")
        self.resize(720, 680)
        self.setMinimumSize(560, 480)
        self.setStyleSheet(janela_principal.styleSheet())
        self.construir_elementos_interface()

        if iniciar_em_edicao:
            self.alternar_modo()




    def construir_elementos_interface(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        cabecalho = QFrame()
        cabecalho.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
            " stop:0 #1f6feb, stop:1 #8957e5);"
            " border-top-left-radius: 10px; border-top-right-radius: 10px;"
        )
        layout_cabecalho = QVBoxLayout(cabecalho)
        layout_cabecalho.setContentsMargins(22, 16, 22, 16)
        layout_cabecalho.setSpacing(2)

        label_titulo = QLabel(f"📄  {self.nome_tarefa}")
        label_titulo.setTextFormat(Qt.TextFormat.PlainText)
        label_titulo.setStyleSheet(
            "color: #ffffff; font-size: 19px; font-weight: bold; background: transparent;"
        )
        label_subtitulo = QLabel("DOCUMENTO ANEXADO · MARK 2")
        label_subtitulo.setStyleSheet(
            "color: #dce4ff; font-weight: bold; font-size: 10px; "
            "letter-spacing: 1px; background: transparent;"
        )

        layout_cabecalho.addWidget(label_subtitulo)
        layout_cabecalho.addWidget(label_titulo)
        layout.addWidget(cabecalho)

        corpo = QWidget()
        layout_corpo = QVBoxLayout(corpo)
        layout_corpo.setContentsMargins(22, 20, 22, 20)
        layout_corpo.setSpacing(14)

        self.texto = QTextEdit()
        self.texto.setReadOnly(True)
        self.texto.setStyleSheet(
            "QTextEdit { background-color: #0d1117; border: 1px solid #21262d; "
            "border-radius: 8px; padding: 14px; font-size: 14px; }"
        )
        self.exibir_modo_visualizacao()
        layout_corpo.addWidget(self.texto, stretch=1)

        layout_botoes = QHBoxLayout()

        self.botao_alternar = QPushButton("✎  Editar Documento")
        self.botao_alternar.setStyleSheet(
            "QPushButton { background-color: #6e40c9; }"
            "QPushButton:hover { background-color: #8957e5; }"
        )
        self.botao_alternar.clicked.connect(self.alternar_modo)

        botao_fechar = QPushButton("Fechar")
        botao_fechar.setStyleSheet(
            "QPushButton { background-color: #30363d; }"
            "QPushButton:hover { background-color: #3a4048; }"
        )
        botao_fechar.clicked.connect(self.close)

        layout_botoes.addWidget(self.botao_alternar)
        layout_botoes.addStretch()
        layout_botoes.addWidget(botao_fechar)
        layout_corpo.addLayout(layout_botoes)

        layout.addWidget(corpo)



    # Exibe modo visualizacao
    def exibir_modo_visualizacao(self):
        if self.conteudo_atual.strip():
            self.texto.document().setMarkdown(
                self.conteudo_atual,
                QTextDocument.MarkdownFeature.MarkdownNoHTML,
            )
        else:
            self.texto.setPlainText(
                "Nenhum documento adicionado ainda.\n\n"
                'Clique em "Editar Documento" pra escrever um cardápio, checklist '
                "ou qualquer anotação relacionada a essa tarefa. Formatação em "
                "Markdown é suportada: use ## pra títulos, - pra listas e "
                "**negrito** pra destacar."
            )



class JanelaPainelControle(QMainWindow):



    sinal_encerrar_remoto = Signal()




    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mark 2 - Painel de Controle")
        self.resize(600, 500)
        self.worker_voz = None
        self.worker = None
        self.worker_saida = None
        self.worker_clima = None
        self.worker_tarefas = None
        self.encerramento_pendente = False
        self.aplicar_estilos_visuais()
        self.construir_elementos_interface()
        self.iniciar_monitoramento_clima()
        self.iniciar_monitoramento_tarefas()
        self.sinal_encerrar_remoto.connect(self.solicitar_encerramento)
        servidor_remoto.registrar_callback_encerramento(self.sinal_encerrar_remoto.emit)



    # Inicia monitoramento tarefas
    def iniciar_monitoramento_tarefas(self):
        self.worker_tarefas = ThreadTarefas()
        self.worker_tarefas.tarefa_pendente.connect(self.alertar_tarefa_pendente)
        self.worker_tarefas.start()




    def alertar_tarefa_pendente(self, aviso: dict):
        nome = aviso["nome"]

        if aviso["tipo"] == "antecedencia":
            mensagem = (
                f"Senhor {config.NOME_MESTRE}, faltam {aviso['minutos']} minutos "
                f"para '{nome}', às {aviso['horario']}."
            )
        else:
            mensagem = f"Senhor {config.NOME_MESTRE}, chegou a hora de: {nome}."
            if aviso.get("tem_documento"):
                mensagem += " Tem um documento anexado — abra em Tarefas pra consultar."

        self.adicionar_log("📌 Tarefa", mensagem)
        self.mostrar_notificacao_toast(f"📌 {nome}", mensagem)

        if config.VOZ_ATIVA:
            voz.falar(mensagem)



    # Mostra notificacao toast
    def mostrar_notificacao_toast(self, titulo: str, mensagem: str):
        titulo_seguro = html.escape(str(titulo))
        mensagem_segura = html.escape(str(mensagem)).replace("\n", "<br>")
        self.label_toast.setText(f"<b>{titulo_seguro}</b><br>{mensagem_segura}")
        self.label_toast.adjustSize()

        margem = 20
        x = self.width() - self.label_toast.width() - margem
        self.label_toast.move(max(margem, x), margem + 40)
        self.label_toast.raise_()
        self.label_toast.show()

        QTimer.singleShot(8000, self.label_toast.hide)



    # Inicia monitoramento clima
    def iniciar_monitoramento_clima(self):
        self.worker_clima.clima_atualizado.connect(self.atualizar_label_clima)
        self.worker_clima.start()



    # Atualiza label clima
    def atualizar_label_clima(self, dados: dict):
        temperatura = dados.get("temperatura")
        if not isinstance(temperatura, (int, float)) or isinstance(temperatura, bool):
            self.label_clima.setText("Clima indisponível")
            return
        icone = dados.get("icone", "🌡️")
        descricao = dados.get("descricao", "")
        self.label_clima.setText(f"{icone} {temperatura:.0f}°C · {descricao}")



    # Aplica estilos visuais
    def aplicar_estilos_visuais(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #0d1117; }
            QDialog { background-color: #0d1117; }
            QLabel { color: #c9d1e0; font-family: Segoe UI; font-weight: bold; }
            QLabel#titulo { font-size: 20px; color: #ffffff; }
            QFrame#cartao { background-color: #10151d; border: 1px solid #21262d; border-radius: 10px; }
            QTextEdit { background-color: #161b22; color: #c9d1e0; border: 1px solid #30363d; border-radius: 6px; padding: 10px; font-size: 14px;}
            QLineEdit { background-color: #0a0e14; color: #ffffff; border: 1px solid #30363d; border-radius: 6px; padding: 8px; font-size: 14px;}
            QLineEdit:focus { border: 1px solid #58a6ff; }
            QListWidget { background-color: #161b22; color: #c9d1e0; border: 1px solid #30363d; border-radius: 6px; padding: 6px; font-size: 14px;}
            QProgressBar { background-color: #161b22; border: 1px solid #30363d; border-radius: 6px; text-align: center; }
            QProgressBar::chunk { background-color: #58a6ff; border-radius: 6px; }
            QPushButton { background-color: #238636; color: #ffffff; font-weight: bold; border-radius: 6px; padding: 8px 16px; }
            QPushButton:hover { background-color: #2ea043; }
            QTableWidget {
                background-color: #10151d;
                alternate-background-color: #161b22;
                color: #c9d1e0;
                border: 1px solid #21262d;
                border-radius: 8px;
                gridline-color: #21262d;
                font-size: 13px;
                font-weight: normal;
                selection-background-color: #1f6feb;
                selection-color: #ffffff;
            }
            QTableWidget::item { padding: 8px; border: none; }
            QTableCornerButton::section { background-color: #161b22; border: none; }
            QHeaderView::section {
                background-color: #161b22;
                color: #58a6ff;
                font-weight: bold;
                font-size: 12px;
                padding: 8px;
                border: none;
                border-bottom: 2px solid #30363d;
            }
            QScrollBar:vertical { background: #10151d; width: 10px; margin: 0; }
            QScrollBar::handle:vertical { background: #30363d; border-radius: 5px; min-height: 24px; }
            QScrollBar::handle:vertical:hover { background: #3a4048; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)



    # Cria cartao
    def criar_cartao(self, layout_interno) -> QFrame:
        cartao = QFrame()
        cartao.setObjectName("cartao")
        cartao.setLayout(layout_interno)
        layout_interno.setContentsMargins(14, 12, 14, 12)
        return cartao




    def construir_elementos_interface(self):
        widget_central = QWidget()
        layout_principal = QVBoxLayout(widget_central)
        layout_principal.setContentsMargins(22, 18, 22, 18)
        layout_principal.setSpacing(16)

        layout_principal.addLayout(self.criar_secao_topo())
        layout_principal.addWidget(self.criar_cartao(self.criar_secao_voz()))

        layout_label_log = QHBoxLayout()
        label_log = QLabel("Terminal de Comunicação:")
        botao_limpar_log = QPushButton("Limpar")
        botao_limpar_log.setStyleSheet(
            "QPushButton { background-color: #30363d; padding: 4px 10px; }"
            "QPushButton:hover { background-color: #3a4048; }"
        )
        botao_limpar_log.clicked.connect(lambda: self.display_log.clear())
        layout_label_log.addWidget(label_log)
        layout_label_log.addStretch()
        layout_label_log.addWidget(botao_limpar_log)
        layout_principal.addLayout(layout_label_log)

        self.display_log = QTextEdit()
        self.display_log.setReadOnly(True)
        layout_principal.addWidget(self.display_log, stretch=1)

        layout_principal.addLayout(self.criar_secao_comando())
        self.setCentralWidget(widget_central)

        self.label_toast = QLabel(self)
        self.label_toast.setWordWrap(True)
        self.label_toast.setMaximumWidth(320)
        self.label_toast.setStyleSheet(
            "QLabel { background-color: #1f6feb; color: #ffffff; "
            "border-radius: 10px; padding: 12px 16px; font-weight: normal; }"
        )
        self.label_toast.hide()



    # Cria secao topo
    def criar_secao_topo(self) -> QHBoxLayout:
        layout_topo = QHBoxLayout()
        label_titulo = QLabel("Mark 2")
        label_titulo.setObjectName("titulo")

        self.label_status = QLabel("● Pronto")
        self.label_status.setStyleSheet("color: #3fb950; font-weight: normal;")

        self.label_clima = QLabel("Carregando clima...")
        self.label_clima.setStyleSheet("color: #8b949e; font-weight: normal;")

        self.botao_saida = QPushButton("Saída")
        self.botao_saida.setStyleSheet(
            "QPushButton { background-color: #8b3a3a; }"
            "QPushButton:hover { background-color: #a94442; }"
        )
        self.botao_saida.clicked.connect(self.confirmar_saida)

        self.botao_musica = QPushButton()
        self.botao_musica.setStyleSheet(
            "QPushButton { background-color: #6e40c9; }"
            "QPushButton:hover { background-color: #8957e5; }"
        )
        self.botao_musica.clicked.connect(self.alternar_musica_chegada)
        self.atualizar_texto_botao_musica()

        botao_tarefas = QPushButton("Tarefas")
        botao_tarefas.setStyleSheet(
            "QPushButton { background-color: #9e6a03; }"
            "QPushButton:hover { background-color: #bb8009; }"
        )
        botao_tarefas.clicked.connect(self.abrir_tarefas)

        botao_configuracoes = QPushButton("Configurações")
        botao_configuracoes.clicked.connect(self.abrir_configuracoes)

        layout_topo.addWidget(label_titulo)
        layout_topo.addWidget(self.label_status)
        layout_topo.addWidget(self.label_clima)
        layout_topo.addStretch()
        layout_topo.addWidget(self.botao_saida)
        layout_topo.addWidget(self.botao_musica)
        layout_topo.addWidget(botao_tarefas)
        layout_topo.addWidget(botao_configuracoes)
        return layout_topo



    # Atualiza texto botao musica
    def atualizar_texto_botao_musica(self):
        if config.MUSICA_CHEGADA_ATIVA:
            self.botao_musica.setText("🎵 Música: Ativada")
        else:
            self.botao_musica.setText("🎵 Música: Desativada")



    # Alterna musica chegada
    def alternar_musica_chegada(self):
        nova_situacao = not config.MUSICA_CHEGADA_ATIVA
        if not config.definir_musica_chegada_ativa(nova_situacao):
            QMessageBox.warning(
                self, "Erro", "Não foi possível salvar a configuração no disco."
            )
            return
        self.atualizar_texto_botao_musica()



    # Abre configuracoes
    def abrir_configuracoes(self):
        DialogConfiguracoes(self).exec()




    def confirmar_saida(self):
        if self.worker_saida is not None and self.worker_saida.isRunning():
            return
        resposta = QMessageBox.question(
            self,
            "Confirmar saída",
            "Isso vai fechar VS Code, Discord, Spotify e os navegadores abertos. Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return

        self.definir_status("Executando rotina de saída...", "#d29922")
        self.adicionar_log("Você", "até mais")

        self.worker_saida = ThreadRotinaSaida()
        self.worker_saida.resposta_pronta.connect(self.receber_resposta_saida)
        self.worker_saida.finished.connect(self.finalizar_thread_saida)
        self.botao_saida.setEnabled(False)
        self.worker_saida.start()



    # Recebe resposta saida
    def receber_resposta_saida(self, resposta: str):
        self.adicionar_log("Mark 2", resposta)
        self.definir_status("Pronto", "#3fb950")




    def finalizar_thread_saida(self):
        self.worker_saida = None
        self.botao_saida.setEnabled(True)




    def definir_status(self, texto: str, cor_hex: str):
        self.label_status.setText(f"● {texto}")
        self.label_status.setStyleSheet(f"color: {cor_hex}; font-weight: normal;")



    # Cria secao voz
    def criar_secao_voz(self) -> QHBoxLayout:
        layout_voz = QHBoxLayout()
        label_voz = QLabel("Sistema de Voz:")
        self.botao_voz = QPushButton("Ativar Voz")
        self.botao_voz.clicked.connect(self.alternar_sistema_voz)

        self.medidor_nivel_audio = QProgressBar()
        self.medidor_nivel_audio.setRange(0, 100)
        self.medidor_nivel_audio.setTextVisible(False)
        self.medidor_nivel_audio.setFixedWidth(150)
        self.medidor_nivel_audio.setVisible(False)

        layout_voz.addWidget(label_voz)
        layout_voz.addWidget(self.botao_voz)
        layout_voz.addWidget(self.medidor_nivel_audio)
        return layout_voz



    # Alterna sistema voz
    def alternar_sistema_voz(self):
        if self.worker_voz is None:
            config.definir_voz_ativa(True)
            self.worker_voz = ThreadEscutaVoz()
            self.worker_voz.resposta_pronta.connect(self.adicionar_log)
            self.worker_voz.nivel_atualizado.connect(self.medidor_nivel_audio.setValue)
            self.worker_voz.encerrar_sistema.connect(self.solicitar_encerramento)
            self.worker_voz.finished.connect(self.finalizar_thread_voz)
            self.worker_voz.start()

            self.medidor_nivel_audio.setVisible(True)
            self.botao_voz.setText("Desativar Voz")
            self.adicionar_log("Sistema", "Sistema de voz ativado.")
        else:
            self.worker_voz.parar()
            self.esconder_medidor_nivel_audio()
            self.botao_voz.setText("Ativar Voz")
            self.adicionar_log("Sistema", "Sistema de voz desativado.")




    def esconder_medidor_nivel_audio(self):
        self.medidor_nivel_audio.setVisible(False)
        self.medidor_nivel_audio.setValue(0)




    def finalizar_thread_voz(self):
        self.worker_voz = None
        self.esconder_medidor_nivel_audio()
        self.botao_voz.setText("Ativar Voz")
        if self.encerramento_pendente:
            QTimer.singleShot(0, self.close)




    def solicitar_encerramento(self):
        self.encerramento_pendente = True
        if self.worker_voz is None or not self.worker_voz.isRunning():
            self.close()



    # Cria secao comando
    def criar_secao_comando(self) -> QHBoxLayout:
        layout_comando = QHBoxLayout()
        self.input_comando = QLineEdit()
        self.input_comando.setPlaceholderText("Digite um comando para o Mark 2...")
        self.input_comando.returnPressed.connect(self.enviar_comando)

        self.botao_enviar = QPushButton("Enviar")
        self.botao_enviar.clicked.connect(self.enviar_comando)

        layout_comando.addWidget(self.input_comando)
        layout_comando.addWidget(self.botao_enviar)
        return layout_comando



    # Envia comando
    def enviar_comando(self):
        if self.worker is not None and self.worker.isRunning():
            return
        texto_comando = self.input_comando.text().strip()
        if not texto_comando:
            return

        self.input_comando.clear()
        self.adicionar_log("Você", texto_comando)
        self.definir_status("Processando...", "#d29922")
        self.input_comando.setEnabled(False)
        self.botao_enviar.setEnabled(False)

        self.worker = ThreadProcessamentoBackend(texto_comando)
        self.worker.resposta_pronta.connect(self.receber_resposta_backend)
        self.worker.finished.connect(self.finalizar_processamento_backend)
        self.worker.start()




    def adicionar_log(self, autor: str, mensagem: str):
        autor_seguro = html.escape(str(autor))
        mensagem_segura = html.escape(str(mensagem or "")).replace("\n", "<br>")
        self.display_log.append(f"<b>[{autor_seguro}]:</b> {mensagem_segura}")
        scrollbar = self.display_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())



    # Recebe resposta backend
    def receber_resposta_backend(self, resposta):
        if resposta == "SHUTDOWN_SIGNAL":
            self.adicionar_log("Sistema", "encerrando sistema")
            self.encerramento_pendente = True
        else:
            self.adicionar_log("mark 2", resposta)
            self.definir_status("Pronto", "#3fb950")




    def finalizar_processamento_backend(self):
        self.worker = None
        self.input_comando.setEnabled(True)
        self.botao_enviar.setEnabled(True)
        self.input_comando.setFocus()
        if self.encerramento_pendente:
            QTimer.singleShot(0, self.close)



    # Fecha evento
    def closeEvent(self, evento_fechar):
        voz.parar_fala()
        for thread in (
            self.worker_voz,
            self.worker,
            self.worker_saida,
            self.worker_tarefas,
        ):
            if not parar_e_aguardar_thread(thread):
                evento_fechar.ignore()
                return

        servidor_remoto.parar_servidores_remotos()
        evento_fechar.accept()



class JanelaHUDJarvis(QMainWindow):

    sinal_encerrar_remoto = Signal()
    sinal_finalizar_encerramento = Signal()
    sinal_abrir_tela = Signal(str)




    def __init__(self):
        super().__init__()
        self.sinal_encerrar_remoto.connect(self.close)
        self.sinal_finalizar_encerramento.connect(self.finalizar_encerramento)
        servidor_remoto.registrar_callback_encerramento(self.sinal_encerrar_remoto.emit)
        self.telas_adicionais = {}
        self.sinal_abrir_tela.connect(self.abrir_tela_adicional)
        servidor_remoto.registrar_abertura_tela(self.sinal_abrir_tela.emit)
        self.setWindowTitle("Jarvis · Mark 2")
        self.resize(1280, 860)
        self._tentativas_carga = 0
        self._encerramento_iniciado = False
        self._encerramento_concluido = False
        self._thread_encerramento = None
        self.worker_voz = None
        self.web = QWebEngineView(self)
        from .janela_transparente import preparar_janela
        preparar_janela(self, self.web)
        for atributo in ("WebGLEnabled", "Accelerated2dCanvasEnabled", "ScrollAnimatorEnabled"):
            self.web.settings().setAttribute(getattr(self.web.settings().WebAttribute, atributo), True)

        self.web.settings().setAttribute(
            self.web.settings().WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self.web.settings().setAttribute(
            self.web.settings().WebAttribute.JavascriptEnabled, True
        )

        self.setCentralWidget(self.web)
        self.web.page().featurePermissionRequested.connect(self.conceder_permissao)
        self.web.loadFinished.connect(self.carga_finalizada)

        self.worker_tarefas = ThreadTarefas()
        self.worker_tarefas.tarefa_pendente.connect(self.alertar_tarefa)
        self.worker_tarefas.start()

        self.timer_voz = QTimer(self)
        self.timer_voz.timeout.connect(self.sincronizar_escuta_voz)
        self.timer_voz.start(150)



        if getattr(config, "VOZ_INICIAR_AUTOMATICO", True):
            config.definir_voz_ativa(True)
            servidor_remoto.ESCUTA_VOZ_ATIVAR.set()

        QTimer.singleShot(350, self.carregar_hud)



    # Abre tela sem outra escuta de voz
    def abrir_tela_adicional(self, identificador):
        if self._encerramento_iniciado: return
        for chave, tela in self.telas_adicionais.items():
            if chave != identificador: tela.hide()
        if identificador == "principal":
            if self.isMinimized(): self.showNormal()
            else: self.show()
            self.raise_()
            self.activateWindow()
            return
        janela = self.telas_adicionais.get(identificador)
        if janela is None:
            janela = JanelaWidgets(self, identificador)
            self.telas_adicionais[identificador] = janela
        if janela.isVisible() and not janela.isMinimized():
            if not janela.isActiveWindow():
                janela.raise_()
                janela.activateWindow()
            return
        if janela.isMinimized(): janela.showNormal()
        else: janela.show()
        janela.raise_()
        janela.activateWindow()

    # Pausa a interface minimizada
    def changeEvent(self, evento):
        super().changeEvent(evento)
        if evento.type() == QEvent.Type.WindowStateChange and hasattr(self, "web"):
            self.web.page().setVisible(not self.isMinimized() and self.isVisible())

    # Suspende a interface oculta
    def hideEvent(self, evento):
        if hasattr(self, "web"):
            self.web.page().setVisible(False)
        super().hideEvent(evento)

    # Retoma a interface visível
    def showEvent(self, evento):
        super().showEvent(evento)
        if hasattr(self, "web"):
            self.web.page().setVisible(not self.isMinimized())

    # Carrega hud
    def carregar_hud(self):
        self._tentativas_carga += 1
        self.web.load(
            QUrl(f"http://127.0.0.1:{servidor_remoto.PORTA_PADRAO}/painel?embutido=qt")
        )



    # Trata o carregamento do painel
    def carga_finalizada(self, sucesso):
        if sucesso:
            QTimer.singleShot(10000, self.medir_nucleo)
        elif self._tentativas_carga < 10:
            QTimer.singleShot(500, self.carregar_hud)

    # Mede núcleo uma vez por carga
    def medir_nucleo(self):
        # Salva somente métricas visuais
        def receber(resultado):
            try:
                dados = json.loads(resultado or "{}")
                if dados.get("width"):
                    (config.DATA_DIR / "desempenho_nucleo.json").write_text(json.dumps(dados), encoding="utf8")
            except (ValueError, OSError):
                log.debug("Métricas do núcleo indisponíveis")
        try:
            if os.environ.get("JARVIS_TESTE_MOUSE") == "1" and not getattr(self, "_mouse_medido", False):
                self._mouse_medido = True
                self.web.page().runJavaScript("""(()=>{
                    const box=document.getElementById('center').getBoundingClientRect();
                    const cx=box.left+box.width/2, cy=box.top+box.height/2-innerHeight*0.06;
                    const radius=Math.min(innerHeight*0.22,innerWidth*0.2),start=performance.now();
                    let last=start,samples=[];
                    function mover(now){
                        const angle=(now-start)*0.004;
                        window.dispatchEvent(new MouseEvent('mousemove',{clientX:cx+Math.cos(angle)*radius,clientY:cy+Math.sin(angle)*radius}));
                        if(now-last>1000){samples.push({...window.jarvisAnimationStats});last=now}
                        if(now-start<6000)requestAnimationFrame(mover);
                        else{window.dispatchEvent(new MouseEvent('mouseout'));window.jarvisMouseBenchmark={samples}}
                    }
                    requestAnimationFrame(mover);
                })()""")
                QTimer.singleShot(7000, self.medir_mouse)
            self.web.page().runJavaScript("JSON.stringify({...window.jarvisAnimationStats,visible:!document.hidden})", receber)
        except RuntimeError:
            pass




    # Salva teste opcional do cursor
    def medir_mouse(self):
        # Registra FPS durante movimento
        def receber(resultado):
            try:
                dados = json.loads(resultado or "{}")
                (config.DATA_DIR / "desempenho_mouse.json").write_text(json.dumps(dados), encoding="utf8")
            except (ValueError, OSError):
                pass
        try:
            self.web.page().runJavaScript("JSON.stringify(window.jarvisMouseBenchmark || {})", receber)
        except RuntimeError:
            pass

    def conceder_permissao(self, origem, recurso):
        permitido = recurso == QWebEnginePage.MediaAudioCapture
        politica = (
            QWebEnginePage.PermissionGrantedByUser
            if permitido
            else QWebEnginePage.PermissionDeniedByUser
        )
        self.web.page().setFeaturePermission(origem, recurso, politica)



    # Sincroniza escuta voz
    def sincronizar_escuta_voz(self):
        if servidor_remoto.ESCUTA_VOZ_DESLIGAR.is_set():
            servidor_remoto.ESCUTA_VOZ_DESLIGAR.clear()
            servidor_remoto.ESCUTA_VOZ_ATIVAR.clear()
            servidor_remoto.ESCUTA_VOZ_PAUSAR.clear()
            servidor_remoto.ESCUTA_VOZ_DIRETA.clear()
            servidor_remoto.ESCUTA_VOZ_ENCERRAR.clear()
            if self.worker_voz is not None and self.worker_voz.isRunning():
                self.worker_voz.parar()
            return
        if servidor_remoto.ESCUTA_VOZ_PAUSAR.is_set():
            servidor_remoto.ESCUTA_VOZ_PAUSAR.clear()
            servidor_remoto.ESCUTA_VOZ_ATIVAR.clear()
            servidor_remoto.ESCUTA_VOZ_DIRETA.clear()
            servidor_remoto.ESCUTA_VOZ_ENCERRAR.clear()
            if self.worker_voz is not None and self.worker_voz.isRunning():
                self.worker_voz.pausado = True
                self.worker_voz.aguardando_jarvis = True
            else:
                self.worker_voz = ThreadEscutaVoz()
                self.worker_voz.pausado = True
                self.worker_voz.encerrar_sistema.connect(self.close)
                self.worker_voz.start()
            return
        if servidor_remoto.ESCUTA_VOZ_ATIVAR.is_set():
            servidor_remoto.ESCUTA_VOZ_ATIVAR.clear()
            if (
                self.worker_voz is None
                or not self.worker_voz.isRunning()
                or not self.worker_voz.ativo
            ):
                self.worker_voz = ThreadEscutaVoz()
                self.worker_voz.encerrar_sistema.connect(self.close)
                self.worker_voz.start()
            else:
                self.worker_voz.pausado = False
        if servidor_remoto.ESCUTA_VOZ_DIRETA.is_set():
            servidor_remoto.ESCUTA_VOZ_DIRETA.clear()
            if self.worker_voz is not None:
                self.worker_voz.pausado = False
                self.worker_voz.aguardando_jarvis = False
        if servidor_remoto.ESCUTA_VOZ_ENCERRAR.is_set():
            servidor_remoto.ESCUTA_VOZ_ENCERRAR.clear()
            if self.worker_voz is not None:
                self.worker_voz.aguardando_jarvis = True




    def alertar_tarefa(self, aviso: dict):
        nome = aviso.get("nome", "Tarefa")
        if aviso.get("tipo") == "antecedencia":
            mensagem = (
                f"Senhor {config.NOME_MESTRE}, faltam {aviso.get('minutos')} minutos "
                f"para '{nome}', às {aviso.get('horario')}."
            )
        else:
            mensagem = f"Senhor {config.NOME_MESTRE}, chegou a hora de: {nome}."
            if aviso.get("tem_documento"):
                mensagem += " Há um documento anexado na tarefa."
        servidor_remoto.registrar_interacao_local(
            "[Alerta de Tarefa]", mensagem, "monitor-tarefas"
        )
        if config.VOZ_ATIVA:
            voz.falar(mensagem)



    # Fecha evento
    def closeEvent(self, evento_fechar):
        if self._encerramento_concluido:
            evento_fechar.accept()
            return
        evento_fechar.ignore()
        if self._encerramento_iniciado:
            return

        self._encerramento_iniciado = True
        servidor_remoto.registrar_abertura_tela(None)
        servidor_remoto.leitor_dia.interromper()
        for janela in self.telas_adicionais.values(): janela.close()
        self.timer_voz.stop()
        self.hide()
        voz.parar_fala()

        threads = [
            self.worker_voz,
            getattr(self, "worker_tarefas", None),
            getattr(self, "worker_caverna", None),
        ]
        for thread in threads:
            if thread is None or not thread.isRunning():
                continue
            parar = getattr(thread, "parar", None)
            if callable(parar):
                parar()
            else:
                thread.requestInterruption()

        presenca.parar()
        seguranca_stark.parar()
        self._thread_encerramento = threading.Thread(
            target=self.encerrar_em_segundo_plano,
            args=(threads,),
            daemon=True,
            name="mark2-encerramento",
        )
        self._thread_encerramento.start()


    # Encerra em segundo plano
    def encerrar_em_segundo_plano(self, threads):
        try:
            llm_local.cancelar_tudo()
            servidor_remoto.parar_servidores_remotos()
            for thread in threads:
                while thread is not None and thread.isRunning():
                    thread.wait(100)
        except Exception:
            log.exception("Falha durante o encerramento do Jarvis.")
        finally:
            self.sinal_finalizar_encerramento.emit()



    def finalizar_encerramento(self):
        self._encerramento_concluido = True
        self.close()
        aplicativo = QApplication.instance()
        if aplicativo is not None:
            aplicativo.quit()




# Configura registro de falhas
def configurar_registro_de_falhas():
    import faulthandler
    import threading
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    from logging.handlers import RotatingFileHandler

    pasta = config.DATA_DIR / "logs"
    pasta.mkdir(parents=True, exist_ok=True)
    manipulador = RotatingFileHandler(
        pasta / "mark2.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    manipulador.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    raiz = logging.getLogger()
    raiz.addHandler(manipulador)
    if raiz.level == logging.NOTSET or raiz.level > logging.INFO:
        raiz.setLevel(logging.INFO)

    arquivo_falhas = open(pasta / "falhas_nativas.log", "a", encoding="utf-8")
    faulthandler.enable(file=arquivo_falhas, all_threads=True)


    # Registra excecao
    def registrar_excecao(tipo, valor, rastro):
        if isinstance(valor, KeyboardInterrupt):
            return
        logging.getLogger("mark2.falha").critical(
            "Exceção não tratada", exc_info=(tipo, valor, rastro)
        )

    sys.excepthook = registrar_excecao
    threading.excepthook = lambda args: registrar_excecao(
        args.exc_type, args.exc_value, args.exc_traceback
    )
    logging.getLogger("mark2.falha").info("Registro de falhas em %s", pasta)



# Inicia aplicativo
def iniciar_aplicativo():
    configurar_registro_de_falhas()

    servidor_remoto.iniciar_servidor_remoto_thread()
    seguranca_stark.iniciar()

    app = QApplication(sys.argv)

    fonte = app.font()
    fonte.setPointSize(10)
    app.setFont(fonte)

    from .janelas_nativas import executavel
    caminho = executavel() if os.name == "nt" and config.obter_bool("interface_browser_nativa", False) else None
    if caminho:
        app.setQuitOnLastWindowClosed(False)
        janela = ServicoHUDNativo(caminho)
    else: janela = JanelaHUDJarvis()
    janela.show()

    marcador_dev = os.environ.get("JARVIS_DEV_RELOAD_REQUEST", "")
    if os.environ.get("JARVIS_DEV_RELOAD") == "1" and marcador_dev:
        timer_recarregamento_dev = QTimer(app)

        # Verifica pedido recarregamento dev
        def verificar_pedido_recarregamento_dev():
            try:
                caminho = Path(marcador_dev)
                if not caminho.is_file():
                    return
                acao = caminho.read_text(encoding="ascii").strip()
                caminho.unlink(missing_ok=True)
                if acao in {"restart", "stop"}:
                    log.warning("Pedido de %s do Jarvis recebido pelo monitor de desenvolvimento.",
                                "rein\u00edcio controlado" if acao == "restart" else "encerramento")
                    timer_recarregamento_dev.stop()
                    janela.close()
            except OSError:
                log.exception("N\u00e3o foi poss\u00edvel processar o pedido do monitor de desenvolvimento.")

        timer_recarregamento_dev.timeout.connect(verificar_pedido_recarregamento_dev)
        timer_recarregamento_dev.start(500)

    sys.exit(app.exec())


class JanelaWidgets(QMainWindow):
    # Cria tela independente do painel
    def __init__(self, pai, identificador):
        super().__init__()
        self.dono = pai
        self.setWindowFlag(Qt.Window, True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setWindowTitle("Jarvis · Tela adicional")
        self.resize(1100, 800)
        self.identificador = identificador
        self.geometria_arquivo = config.DATA_DIR / ("janela-" + identificador + ".json")
        try:
            geo = json.loads(self.geometria_arquivo.read_text(encoding="utf-8"))
            self.restoreGeometry(QByteArray.fromBase64(geo["geometria"].encode("ascii")))
        except (OSError, ValueError, KeyError, TypeError): pass
        self.web = QWebEngineView(self)
        from .janela_transparente import preparar_janela
        preparar_janela(self, self.web)
        for atributo in ("WebGLEnabled", "Accelerated2dCanvasEnabled", "ScrollAnimatorEnabled"):
            self.web.settings().setAttribute(getattr(self.web.settings().WebAttribute, atributo), True)
        self.setCentralWidget(self.web)
        self.web.load(QUrl(f"http://127.0.0.1:{servidor_remoto.PORTA_PADRAO}/telas?embutido=qt&tela={identificador}"))

    # Guarda monitor e tamanho da janela
    def closeEvent(self, evento):
        try:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            self.geometria_arquivo.write_text(json.dumps({"geometria":bytes(self.saveGeometry().toBase64()).decode("ascii")}), encoding="utf-8")
        except OSError: log.exception("Não foi possível guardar a posição da tela")
        super().closeEvent(evento)


    # Pausa página minimizada
    def changeEvent(self, evento):
        super().changeEvent(evento)
        if evento.type() == QEvent.Type.WindowStateChange and hasattr(self,"web"):
            self.web.page().setVisible(not self.isMinimized() and self.isVisible())

    # Suspende página fora da vista
    def hideEvent(self, evento):
        if hasattr(self,"web"): self.web.page().setVisible(False)
        super().hideEvent(evento)

    # Retoma widgets visíveis
    def showEvent(self, evento):
        super().showEvent(evento)
        self.web.page().setVisible(not self.isMinimized())


class ServicoHUDNativo(JanelaHUDJarvis):
    # Inicia servicos sem pintar Qt
    def __init__(self, caminho):
        QMainWindow.__init__(self)
        from .janelas_nativas import JanelaNativa
        self.caminho_nativo=caminho
        self._encerramento_iniciado=False;self._encerramento_concluido=False;self._thread_encerramento=None
        self.worker_voz=None;self.telas_adicionais={}
        self.principal_nativa=JanelaNativa(self,"principal",caminho,servidor_remoto.PORTA_PADRAO)
        self.sinal_encerrar_remoto.connect(self.close);self.sinal_finalizar_encerramento.connect(self.finalizar_encerramento)
        servidor_remoto.registrar_callback_encerramento(self.sinal_encerrar_remoto.emit)
        self.sinal_abrir_tela.connect(self.abrir_tela_adicional);servidor_remoto.registrar_abertura_tela(self.sinal_abrir_tela.emit)
        self.worker_tarefas=ThreadTarefas();self.worker_tarefas.tarefa_pendente.connect(self.alertar_tarefa);self.worker_tarefas.start()
        self.timer_voz=QTimer(self);self.timer_voz.timeout.connect(self.sincronizar_escuta_voz);self.timer_voz.start(150)
        self.timer_janela=QTimer(self);self.timer_janela.timeout.connect(self.verificar_janela_nativa);self.timer_janela.start(5000)
        if getattr(config,"VOZ_INICIAR_AUTOMATICO",True):
            config.definir_voz_ativa(True);servidor_remoto.ESCUTA_VOZ_ATIVAR.set()

    # Guarda geometria e acompanha fechar
    def verificar_janela_nativa(self):
        if self._encerramento_iniciado: return
        if self.principal_nativa.aberturas and not self.principal_nativa.valido():
            self.close();return
        for janela in [self.principal_nativa,*self.telas_adicionais.values()]:
            try: janela.salvar()
            except OSError: log.exception("Não foi possível guardar posição da janela")

    # Mostra app sem janela Qt visivel
    def show(self): self.principal_nativa.show()
    # Oculta somente a tela principal
    def hide(self): self.principal_nativa.hide()
    # Fecha mantendo encerramento seguro
    def close(self):
        from PySide6.QtGui import QCloseEvent
        if self._encerramento_concluido: self.principal_nativa.close();return True
        self.timer_janela.stop();self.closeEvent(QCloseEvent());return True

    # Reabre telas com o mesmo perfil
    def abrir_tela_adicional(self, ident):
        from .janelas_nativas import JanelaNativa
        if self._encerramento_iniciado:return
        if ident=="principal":self.principal_nativa.show();return
        for key,janela in self.telas_adicionais.items():
            if key!=ident:janela.hide()
        janela=self.telas_adicionais.get(ident)
        if janela is None:
            janela=JanelaNativa(self,ident,self.caminho_nativo,servidor_remoto.PORTA_PADRAO);self.telas_adicionais[ident]=janela
        janela.show()
