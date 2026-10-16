package com.mark2.remoto

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.MediaPlayer
import android.media.ToneGenerator
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.text.Normalizer
import java.util.Locale
import org.json.JSONObject
import org.vosk.Model
import org.vosk.android.RecognitionListener as VoskRecognitionListener

private const val HOST_PADRAO_ESCUTA = ""
private const val PORTA_PADRAO_ESCUTA = 5679
internal const val PREF_OLLAMA_ATIVO = "ollama_ativo"
internal const val PREF_ESCUTA_CONTINUA = "escuta_continua_ativa"
enum class Autor { USUARIO, JARVIS, SISTEMA }
data class UiMessage(val autor: Autor, val texto: String, val erro: Boolean = false)

private val NOMES_JARVIS = setOf(
    "jarvis", "jarves", "jarvi", "jarbis", "jarvez", "jervis", "gervis", "gerby", "gerbi",
    "jarbas", "gerbis", "jarvys", "javis", "charvis", "germes", "james", "já vis", "já vi", "ja vi", "jar vins"
)
private const val SAUDACAO_PADRAO = "Às ordens, senhor."

object BarramentoEscutaJarvis {
    private val _mensagens = MutableSharedFlow<UiMessage>(replay = 32, extraBufferCapacity = 8)
    val mensagens = _mensagens.asSharedFlow()

    private val _ouvindo = MutableStateFlow(ServicoEscutaJarvis.emExecucao)
    val ouvindo = _ouvindo.asStateFlow()

    private val _aguardandoComando = MutableStateFlow(false)
    val aguardandoComando = _aguardandoComando.asStateFlow()

    private val _falaParcial = MutableStateFlow("")
    val falaParcial = _falaParcial.asStateFlow()

    private val _nivelMicrofone = MutableStateFlow(0)
    val nivelMicrofone = _nivelMicrofone.asStateFlow()

    
    suspend fun publicar(mensagem: UiMessage) = _mensagens.emit(mensagem)
    
    fun publicarFalaParcial(texto: String) { _falaParcial.value = texto }
    // Atualiza nivel microfone
    fun atualizarNivelMicrofone(nivel: Int) { _nivelMicrofone.value = nivel.coerceIn(0, 100) }
    
    fun marcarOuvindo(valor: Boolean) { _ouvindo.value = valor }
    
    fun marcarAguardandoComando(valor: Boolean) { _aguardandoComando.value = valor }
}

class ServicoEscutaJarvis : Service() {
    companion object {
        const val ACAO_PARAR = "com.mark2.remoto.PARAR_ESCUTA_JARVIS"
        const val ACAO_PARAR_AUDIO = "com.mark2.remoto.PARAR_AUDIO_JARVIS"
        private const val ID_CANAL = "escuta_continua_jarvis"
        private const val ID_NOTIFICACAO = 4202
        private const val TAG = "ServicoEscutaJarvis"
        private const val TIMEOUT_FALA_PADRAO_MS = 30_000L

        @Volatile
        var emExecucao: Boolean = false
            private set
    }

    private var capturaVozLocal: CapturaVozLocal? = null
    @Volatile private var carregandoModeloVoz = false
    private val handlerPrincipal = Handler(Looper.getMainLooper())
    private val escopo = CoroutineScope(Dispatchers.IO)
    private var jobEnvio: Job? = null
    private val frasesPendentes = java.util.ArrayDeque<String>()
    private lateinit var prefs: CofreLocal
    private var reinicioPendente = false
    private var pararObservacaoAudio: (() -> Unit)? = null
    private var ultimaFraseOuvidaConsole = ""
    private var ultimaFraseOuvidaConsoleEm = 0L

    @Volatile private var falandoAgora = false


    @Volatile private var comandoEmAndamento = false
    @Volatile private var chamadaSinalizadaNestaFrase = false


    private val audioManager: AudioManager by lazy { getSystemService(Context.AUDIO_SERVICE) as AudioManager }
    private var mediaPlayer: MediaPlayer? = null
    private var watchdogFala: Runnable? = null

    // Inicializa a tela do aplicativo
    override fun onCreate() {
        super.onCreate()
        prefs = CofreLocal.obter(this)
        criarCanalNotificacao()
    }

    // Trata start comando
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACAO_PARAR_AUDIO) {
            pararAudioAtual()
            return if (emExecucao) START_STICKY else START_NOT_STICKY
        }
        if (intent?.action == ACAO_PARAR) {
            pararServico()
            return START_NOT_STICKY
        }
        if (!prefs.getBoolean(PREF_ESCUTA_CONTINUA, false) ||
            checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (emExecucao) return START_STICKY
        startForeground(ID_NOTIFICACAO, construirNotificacao())
        emExecucao = true
        pararObservacaoAudio = RoteamentoAudio.observar(this, handlerPrincipal) { aoMudarRotaAudio() }
        BarramentoEscutaJarvis.marcarOuvindo(true)
        BarramentoEscutaJarvis.publicarFalaParcial("")
        escopo.launch {
            BarramentoEscutaJarvis.publicar(
                UiMessage(Autor.SISTEMA, "Microfone ativo. Diga Jarvis e seu pedido; navegação aceita comandos diretos.")
            )
        }
        handlerPrincipal.post { iniciarReconhecedor() }
        escopo.launch {
            while (emExecucao) {
                atualizarCacheFrasesRotina()
                kotlinx.coroutines.delay(60_000)
            }
        }
        return START_STICKY
    }

    // Libera recursos do serviço
    override fun onDestroy() {
        emExecucao = false
        BarramentoEscutaJarvis.marcarOuvindo(false)
        BarramentoEscutaJarvis.marcarAguardandoComando(false)
        BarramentoEscutaJarvis.publicarFalaParcial("")
        BarramentoEscutaJarvis.atualizarNivelMicrofone(0)
        handlerPrincipal.removeCallbacksAndMessages(null)
        pararObservacaoAudio?.invoke()
        pararObservacaoAudio = null
        encerrarCapturaVoz()
        RoteamentoAudio.liberarEntrada(this)
        jobEnvio?.cancel()
        escopo.cancel()
        mediaPlayer?.release()
        mediaPlayer = null
        super.onDestroy()
    }

    // Trata bind
    override fun onBind(intent: Intent?): IBinder? = null

    // Para servico
    private fun pararServico() {
        emExecucao = false
        CofreLocal.obter(this)
            .edit().putBoolean(PREF_ESCUTA_CONTINUA, false).apply()
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    // Para áudio atual
    private fun pararAudioAtual() {
        jobEnvio?.cancel()
        jobEnvio = null
        comandoEmAndamento = false
        BarramentoEscutaJarvis.marcarAguardandoComando(false)
        falandoAgora = false
        mediaPlayer?.let {
            try { it.stop() } catch (_: Exception) {}
            it.release()
        }
        mediaPlayer = null
        cancelarWatchdogFala()
        if (emExecucao) iniciarReconhecedor()
    }

    
    private fun atributosFala(): AudioAttributes = AudioAttributes.Builder()
        .setUsage(AudioAttributes.USAGE_ASSISTANT)
        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
        .build()

    // Inicia watchdog fala
    private fun iniciarWatchdogFala(timeoutMs: Long = TIMEOUT_FALA_PADRAO_MS) {
        watchdogFala?.let { handlerPrincipal.removeCallbacks(it) }
        val runnavel = Runnable {
            if (falandoAgora) {
                Log.w(TAG, "Watchdog: fala travada, retomando escuta.")
                falandoAgora = false
                mediaPlayer?.release()
                mediaPlayer = null
                iniciarReconhecedor()
            }
        }
        watchdogFala = runnavel
        handlerPrincipal.postDelayed(runnavel, timeoutMs)
    }

    // Cancela watchdog fala
    private fun cancelarWatchdogFala() {
        watchdogFala?.let { handlerPrincipal.removeCallbacks(it) }
        watchdogFala = null
    }

    // Avisa comando captado
    private fun avisarComandoCaptado() {
        try {
            val gerador = ToneGenerator(AudioManager.STREAM_MUSIC, 70)
            gerador.startTone(ToneGenerator.TONE_PROP_BEEP, 120)
            handlerPrincipal.postDelayed({ gerador.release() }, 200)
        } catch (e: Exception) {
            Log.w(TAG, "Falha ao tocar o bipe de confirmação: ${e.message}")
        }
        try {
            val vibrador = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                (getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager).defaultVibrator
            } else {
                @Suppress("DEPRECATION")
                getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
            }
            vibrador.vibrate(VibrationEffect.createOneShot(80, VibrationEffect.DEFAULT_AMPLITUDE))
        } catch (e: Exception) {
            Log.w(TAG, "Falha ao vibrar a confirmação: ${e.message}")
        }
    }

    // Inicia reconhecedor
    private fun iniciarReconhecedor() {
        if (!emExecucao || falandoAgora) {
            return
        }
        capturaVozLocal?.let {
            it.pausar(false)
            return
        }
        if (carregandoModeloVoz) return
        carregandoModeloVoz = true
        ModeloVozLocal.carregar(this) { modelo, erro ->
            if (!emExecucao) {
                carregandoModeloVoz = false
                return@carregar
            }
            if (modelo == null) {
                carregandoModeloVoz = false
                Log.e(TAG, "Falha ao carregar modelo offline: ${erro?.message}", erro)
                escopo.launch {
                    BarramentoEscutaJarvis.publicar(
                        UiMessage(
                            autor = Autor.SISTEMA,
                            texto = "Não consegui carregar o reconhecimento de voz offline: ${erro?.message ?: "erro desconhecido"}.",
                            erro = true,
                        )
                    )
                }
                reagendarReconhecedor(4000)
                return@carregar
            }
            val rota = RoteamentoAudio.entradaPreferida(this)
            RoteamentoAudio.ativarEntrada(this, rota, handlerPrincipal) {
                carregandoModeloVoz = false
                if (emExecucao && capturaVozLocal == null) abrirCaptura(modelo, rota)
            }
        }
    }

    // Abre captura
    private fun abrirCaptura(modelo: Model, rota: RotaEntrada?) {
        try {
            val captura = CapturaVozLocal.criar(modelo, this, rota)
            capturaVozLocal = captura
            captura.iniciar(
                ouvinte = ouvinteVozLocal,
                aoNivelMicrofone = BarramentoEscutaJarvis::atualizarNivelMicrofone,
            )
        } catch (falha: Exception) {
            Log.e(TAG, "Falha ao abrir o microfone", falha)
            encerrarCapturaVoz()
            escopo.launch {
                BarramentoEscutaJarvis.publicar(
                    UiMessage(Autor.SISTEMA, "Não consegui abrir o microfone: ${falha.message}", erro = true)
                )
            }
            reagendarReconhecedor(3000)
        }
    }

    /* Fone conectado/desconectado: reabre */
    
    private fun aoMudarRotaAudio() {
        if (!emExecucao) return
        val usandoFone = RoteamentoAudio.entradaPreferida(this) != null
        Log.i(TAG, "Rota de áudio mudou; microfone do ${if (usandoFone) "fone" else "celular"}.")
        escopo.launch {
            BarramentoEscutaJarvis.publicar(
                UiMessage(Autor.SISTEMA, if (usandoFone) "Microfone: fone de ouvido." else "Microfone: celular.")
            )
        }
        encerrarCapturaVoz()
        iniciarReconhecedor()
    }

    private val ouvinteVozLocal = object : VoskRecognitionListener {
        
        private fun tratarResultado(hypothesis: String?) {
            val frase = try { JSONObject(hypothesis.orEmpty()).optString("text") } catch (_: Exception) { "" }
            if (frase.isNotBlank()) {
                val agora = System.currentTimeMillis()
                if (frase == ultimaFraseOuvidaConsole && agora - ultimaFraseOuvidaConsoleEm < 700) return
                ultimaFraseOuvidaConsole = frase
                ultimaFraseOuvidaConsoleEm = agora
                Log.i(TAG, "[OUVIDO] $frase")
                val host = prefs.getString("host", HOST_PADRAO_ESCUTA) ?: HOST_PADRAO_ESCUTA
                val porta = prefs.getInt("porta", PORTA_PADRAO_ESCUTA)
                escopo.launch {
                    try {
                        Mark2Api.registrarTranscricaoVoz(host, porta, frase)
                    } catch (erro: Exception) {
                        Log.d(TAG, "Transcrição não enviada ao console do PC: ${erro.message}")
                    }
                }
                BarramentoEscutaJarvis.publicarFalaParcial("")
                escopo.launch { BarramentoEscutaJarvis.publicar(UiMessage(Autor.SISTEMA, "Ouvi: $frase")) }
                processarFraseOuvida(frase)
            }
        }
        
        override fun onResult(hypothesis: String?) = tratarResultado(hypothesis)
        // Trata final resultado
        override fun onFinalResult(hypothesis: String?) = tratarResultado(hypothesis)
        // Trata partial resultado
        override fun onPartialResult(hypothesis: String?) {
            val parcial = try { JSONObject(hypothesis.orEmpty()).optString("partial") } catch (_: Exception) { "" }
            if (!chamadaSinalizadaNestaFrase && !comandoEmAndamento && extrairComandoAposChamada(parcial) != null) {
                chamadaSinalizadaNestaFrase = true
                escopo.launch {
                    BarramentoEscutaJarvis.publicar(
                        UiMessage(Autor.SISTEMA, "Jarvis detectado; ouvindo o restante do comando…")
                    )
                }
            }
            BarramentoEscutaJarvis.publicarFalaParcial(parcial)
        }
        // Trata timeout
        override fun onTimeout() { chamadaSinalizadaNestaFrase = false }
        
        override fun onError(exception: Exception?) {
            chamadaSinalizadaNestaFrase = false
            Log.e(TAG, "Falha no reconhecedor local", exception)
            handlerPrincipal.post {
                if (emExecucao && capturaVozLocal != null) {
                    encerrarCapturaVoz()
                    reagendarReconhecedor(1500)
                }
            }
        }
    }

    // Reagenda reconhecedor
    private fun reagendarReconhecedor(atrasoMs: Long = 250) {
        if (!emExecucao || reinicioPendente) return
        reinicioPendente = true
        handlerPrincipal.postDelayed({
            reinicioPendente = false
            iniciarReconhecedor()
        }, atrasoMs)
    }

    // Encerra captura voz
    private fun encerrarCapturaVoz() {
        capturaVozLocal?.encerrar()
        capturaVozLocal = null
    }

    // Confere primeiro se a frase é um gatilho de rotina e, se for, mantém toda a fala no celular.
    private fun processarFraseOuvida(fraseOriginal: String) {
        val chamadaJaSinalizada = chamadaSinalizadaNestaFrase
        chamadaSinalizadaNestaFrase = false
        if (comandoEmAndamento) {
            if (extrairComandoAposChamada(fraseOriginal) != null && frasesPendentes.size < 8) frasesPendentes.addLast(fraseOriginal)
            return
        }
        if (!ehFraseGatilhoRotina(fraseOriginal)) {
            processarComandoReconhecido(fraseOriginal, chamadaJaSinalizada)
            return
        }
        jobEnvio?.cancel()
        comandoEmAndamento = true
        BarramentoEscutaJarvis.marcarAguardandoComando(true)
        jobEnvio = escopo.launch {
            var rotinaDisparada = false
            try {
                val host = prefs.getString("host", HOST_PADRAO_ESCUTA) ?: HOST_PADRAO_ESCUTA
                val porta = prefs.getInt("porta", PORTA_PADRAO_ESCUTA)
                val resultado = withContext(Dispatchers.IO) { Mark2Api.dispararRotinaVoz(host, porta, fraseOriginal) }
                if (resultado.optBoolean("correspondida")) rotinaDisparada = true
                if (resultado.optBoolean("disparada")) {
                    val fala = (0 until (resultado.optJSONArray("falas")?.length() ?: 0))
                        .mapNotNull { resultado.optJSONArray("falas")?.optString(it) }
                        .filter(String::isNotBlank).joinToString(". ")
                    BarramentoEscutaJarvis.publicar(UiMessage(Autor.SISTEMA, resultado.optString("mensagem", "Rotina iniciada.")))
                    if (fala.isNotBlank()) falarResposta(fala)
                }
            } catch (e: Exception) {
                if (e is CancellationException) return@launch
                Log.i(TAG, "Sem rotina correspondente ou serviço de rotinas indisponível: ${e.message}")
            } finally {
                comandoEmAndamento = false
                BarramentoEscutaJarvis.marcarAguardandoComando(false)
                if (!rotinaDisparada) handlerPrincipal.post { processarComandoReconhecido(fraseOriginal, chamadaJaSinalizada) }
                else handlerPrincipal.post { if (frasesPendentes.isNotEmpty() && emExecucao) processarFraseOuvida(frasesPendentes.removeFirst()) }
            }
        }
    }

    private suspend fun atualizarCacheFrasesRotina() {
        val host = prefs.getString("host", HOST_PADRAO_ESCUTA) ?: HOST_PADRAO_ESCUTA
        val porta = prefs.getInt("porta", PORTA_PADRAO_ESCUTA)
        try {
            val rotinas = Mark2Api.rotinasCasa(host, porta)
            val frases = org.json.JSONArray()
            for (indice in 0 until rotinas.length()) {
                val rotina = rotinas.optJSONObject(indice) ?: continue
                if (!rotina.optBoolean("ativa")) continue
                val itens = rotina.optJSONArray("frases") ?: continue
                for (i in 0 until itens.length()) frases.put(itens.optString(i))
            }
            prefs.edit().putString("frases_rotinas_ativas", frases.toString()).apply()
        } catch (erro: Exception) {
            Log.d(TAG, "Não foi possível atualizar os gatilhos de rotina: ${erro.message}")
        }
    }

    private fun ehFraseGatilhoRotina(frase: String): Boolean {
        val frases = runCatching { org.json.JSONArray(prefs.getString("frases_rotinas_ativas", "[]")) }.getOrNull() ?: return false
        val reconhecida = normalizarFala(frase)
        return (0 until frases.length()).any { normalizarFala(frases.optString(it)) == reconhecida }
    }

    private fun processarComandoReconhecido(fraseOriginal: String, chamadaJaSinalizada: Boolean) {
        if (!emExecucao) return
        if (comandoEmAndamento) {
            if (extrairComandoAposChamada(fraseOriginal) != null && frasesPendentes.size < 8) frasesPendentes.addLast(fraseOriginal)
            return
        }
        val comando = extrairComandoAposChamada(fraseOriginal) ?: return
        Log.i(TAG, "Chamada detectada em \"$fraseOriginal\" -> comando: \"$comando\"")
        if (comando.isBlank()) {
            escopo.launch { BarramentoEscutaJarvis.publicar(UiMessage(Autor.JARVIS, SAUDACAO_PADRAO)); falarResposta(SAUDACAO_PADRAO) }
            return
        }
        if (!chamadaJaSinalizada) avisarComandoCaptado()
        enviarComando(comando)
    }

    private val padraoEncerrarSistema = Regex("^(por favor |por gentileza |pode |poderia )?(sair|(desligar|desligue|encerrar|encerre) (o )?sistema)$")

    // Envia comando
    private fun enviarComando(comando: String) {
        if (padraoEncerrarSistema.matches(normalizarFala(comando))) {
            escopo.launch {
                BarramentoEscutaJarvis.publicar(UiMessage(Autor.SISTEMA, "Encerrar o sistema só pelo botão de desligar do aplicativo."))
            }
            return
        }
        jobEnvio?.cancel()
        comandoEmAndamento = true
        BarramentoEscutaJarvis.marcarAguardandoComando(true)
        jobEnvio = escopo.launch {
            BarramentoEscutaJarvis.publicar(UiMessage(Autor.USUARIO, comando))
            val host = prefs.getString("host", HOST_PADRAO_ESCUTA) ?: HOST_PADRAO_ESCUTA
            val porta = prefs.getInt("porta", PORTA_PADRAO_ESCUTA)
            try {
                val resposta = Mark2Api.enviarComando(host, porta, comando, falarNoPc = false, usarLlm = prefs.getBoolean(PREF_OLLAMA_ATIVO, true))
                if (resposta.isNotBlank()) {
                    BarramentoEscutaJarvis.publicar(UiMessage(Autor.JARVIS, resposta))
                    falarResposta(resposta)
                } else if (!prefs.getBoolean(PREF_OLLAMA_ATIVO, true)) {
                    BarramentoEscutaJarvis.publicar(UiMessage(Autor.SISTEMA, "Ollama desativado neste celular. Toque no ícone de robô para ativar."))
                }
            } catch (e: Exception) {
                if (e is CancellationException) return@launch
                val mensagemErro = e.message ?: "Falha ao falar com o Jarvis."
                BarramentoEscutaJarvis.publicar(UiMessage(Autor.SISTEMA, mensagemErro, erro = true))

            } finally {
                comandoEmAndamento = false
                BarramentoEscutaJarvis.marcarAguardandoComando(false)
                handlerPrincipal.post { if (frasesPendentes.isNotEmpty() && emExecucao) processarFraseOuvida(frasesPendentes.removeFirst()) }
            }
        }
    }

    
    private suspend fun falarResposta(texto: String) {
        if (texto.isBlank()) return
        val bytes = try {
            val host = prefs.getString("host", HOST_PADRAO_ESCUTA) ?: HOST_PADRAO_ESCUTA
            val porta = prefs.getInt("porta", PORTA_PADRAO_ESCUTA)
            Mark2Api.sintetizarVoz(host, porta, texto)
        } catch (e: Exception) {
            Log.w(TAG, "Falha ao receber áudio sintetizado do Jarvis: ${e.message}")
            escopo.launch { BarramentoEscutaJarvis.publicar(UiMessage(Autor.SISTEMA, "Não foi possível receber a voz configurada pelo Jarvis.", erro = true)) }
            null
        }
        handlerPrincipal.post {
            if (!emExecucao) return@post
            if (bytes != null && bytes.size > 44 && bytes.copyOfRange(0, 4).decodeToString() == "RIFF") {
                tocarAudioDoServidor(bytes)
            } else {
                iniciandoEscutaAposFalhaAudio()
            }
        }
    }

    private fun iniciandoEscutaAposFalhaAudio() {
        falandoAgora = false
        cancelarWatchdogFala()
        iniciarReconhecedor()
    }

    private fun tocarAudioDoServidor(bytes: ByteArray) {
        try {
            val arquivoTemp = File.createTempFile("jarvis_fala_", ".wav", cacheDir)
            arquivoTemp.writeBytes(bytes)
            falandoAgora = true
            capturaVozLocal?.pausar(true)
            iniciarWatchdogFala(TIMEOUT_FALA_PADRAO_MS)
            mediaPlayer?.release()
            val player = MediaPlayer()
            mediaPlayer = player
            player.setOnCompletionListener {
                if (mediaPlayer === it) mediaPlayer = null
                it.release()
                arquivoTemp.delete()
                falandoAgora = false
                cancelarWatchdogFala()
                iniciarReconhecedor()
            }
            player.setOnErrorListener { mp, _, _ ->
                if (mediaPlayer === mp) mediaPlayer = null
                mp.release()
                arquivoTemp.delete()
                iniciandoEscutaAposFalhaAudio()
                true
            }
            player.setOnPreparedListener { preparado ->
                if (!emExecucao || mediaPlayer !== preparado) {
                    preparado.release()
                    arquivoTemp.delete()
                    return@setOnPreparedListener
                }
                if (preparado.duration > 0) iniciarWatchdogFala(preparado.duration.toLong() + 6000L)
                preparado.start()
            }
            player.setAudioAttributes(AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ASSISTANT)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                player.setPreferredDevice(RoteamentoAudio.saidaPreferida(this, RoteamentoAudio.entradaPreferida(this)))
            }
            player.setDataSource(arquivoTemp.absolutePath)
            player.prepareAsync()
        } catch (e: Exception) {
            Log.w(TAG, "Falha ao reproduzir áudio sintetizado do Jarvis: ${e.message}")
            iniciandoEscutaAposFalhaAudio()
        }
    }

    // Cria canal notificacao
    private fun criarCanalNotificacao() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val gerenciador = getSystemService(NotificationManager::class.java)
            val canal = NotificationChannel(
                ID_CANAL,
                "Escuta contínua do Jarvis",
                NotificationManager.IMPORTANCE_LOW,
            )
            canal.description = "Mantém o microfone pronto pra ouvir \"jarvis\" sem precisar apertar nada."
            gerenciador.createNotificationChannel(canal)
        }
    }

    
    private fun construirNotificacao(): Notification {
        val intentParar = Intent(this, ServicoEscutaJarvis::class.java).apply { action = ACAO_PARAR }
        val pendingParar = PendingIntent.getService(
            this, 0, intentParar,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, ID_CANAL)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        return builder
            .setContentTitle("Jarvis")
            .setContentText("Ouvindo por \"jarvis\"... diga o comando quando quiser.")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setOngoing(true)
            .addAction(Notification.Action.Builder(null, "Parar de ouvir", pendingParar).build())
            .build()
    }
}

// Normaliza fala
private fun normalizarFala(texto: String): String {
    val semAcentos = Normalizer.normalize(texto.lowercase(Locale("pt", "BR")), Normalizer.Form.NFD)
        .replace(Regex("\\p{Mn}+"), "")
    return semAcentos.replace(Regex("[^a-z0-9\\s]"), " ").replace(Regex("\\s+"), " ").trim()
}


private fun estimarDuracaoFalaMs(texto: String): Long {
    val palavras = texto.trim().split(Regex("\\s+")).filter { it.isNotBlank() }.size.coerceAtLeast(1)
    return (palavras * 400L + 4000L).coerceIn(6000L, 60_000L)
}

// Extrai comando apos chamada
private fun extrairComandoAposChamada(fraseOriginal: String): String? {
    val nomes = NOMES_JARVIS.joinToString("|") { Regex.escape(it) }
    val chamada = Regex("^\\s*(?:(?:ei|ok|ola|olá|hey)[ ,]+)?(?:$nomes|jar\\s+vis)(?!\\w)[ ,.!?:;-]*", RegexOption.IGNORE_CASE).find(fraseOriginal)
    if (chamada != null) return fraseOriginal.substring(chamada.range.last + 1).trim()
    val normal = normalizarFala(fraseOriginal)
    if (normal in setOf("eai", "e ai", "oi", "ola", "alo")) return "eai"
    if (normal == "cheguei em casa") return fraseOriginal
    val direto = Regex("(?:abrir|abra|iniciar) (?:o )?navegador|(?:abrir|abra) (?:uma )?nova aba|(?:fechar|feche|encerrar|encerre) (?:a )?aba(?: do navegador)?|(?:proxima|anterior) aba|aba (?:anterior|seguinte)|(?:voltar|volte|avancar|avance|atualizar|atualize|recarregar|recarregue) (?:(?:uma|a) )?pagina(?: no navegador)?")
    return if (direto.matches(normal)) fraseOriginal else null
}

