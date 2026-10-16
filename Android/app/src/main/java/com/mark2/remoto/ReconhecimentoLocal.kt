package com.mark2.remoto

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AutomaticGainControl
import android.media.audiofx.NoiseSuppressor
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import org.vosk.android.RecognitionListener as VoskRecognitionListener
import java.io.IOException
import java.io.File
import java.io.FileOutputStream
import java.util.concurrent.Executors
import java.util.zip.ZipInputStream

private const val MODELO_ASSET_ZIP = "vosk-model-small-pt-0.3.zip"
private const val MODELO_DIRETORIO = "vosk-model-small-pt-0.3"
private const val MODELO_UUID = "mark2-vosk-pt-0.3"
private const val TAXA_AMOSTRAGEM_VOZ = 16_000

private const val TEMPO_ESPERA_FALA_MS = 5_000L
private const val TEMPO_MAXIMO_FRASE_MS = 300_000L
private const val TEMPO_FIM_FRASE_MS = 650L
private const val FATOR_ABERTURA_PORTAO = 1.7
private const val RMS_MINIMO_VOZ = 110.0
private const val TEMPO_PORTAO_ABERTO_MS = 500L
private const val RMS_ALVO_VOZ = 3200.0
private const val GANHO_MAXIMO = 16.0
private const val COEFICIENTE_PASSA_ALTA = 0.955
private val handlerVozLocal = Handler(Looper.getMainLooper())

internal object ModeloVozLocal {
    @Volatile private var modelo: Model? = null
    private var carregando = false
    private val callbacks = mutableListOf<(Model?, IOException?) -> Unit>()

    
    fun carregar(contexto: Context, callback: (Model?, IOException?) -> Unit) {
        synchronized(this) {
            modelo?.let { callback(it, null); return }
            callbacks.add(callback)
            if (carregando) return
            carregando = true
        }

        val app = contexto.applicationContext
        Executors.newSingleThreadExecutor().execute {
            try {
                val pastaRaiz = File(app.filesDir, "modelos_voz")
                val pastaModelo = File(pastaRaiz, MODELO_DIRETORIO)
                val arquivoUuid = File(pastaModelo, "uuid")
                if (!arquivoUuid.isFile || arquivoUuid.readText() != MODELO_UUID) {
                    pastaRaiz.deleteRecursively()
                    if (!pastaRaiz.mkdirs() && !pastaRaiz.isDirectory) {
                        throw IOException("Não consegui preparar o armazenamento do modelo.")
                    }
                    val raizCanonica = pastaRaiz.canonicalFile
                    ZipInputStream(app.assets.open(MODELO_ASSET_ZIP)).use { zip ->
                        val buffer = ByteArray(16 * 1024)
                        while (true) {
                            val entrada = zip.nextEntry ?: break
                            val destino = File(pastaRaiz, entrada.name).canonicalFile
                            if (!destino.path.startsWith(raizCanonica.path + File.separator)) {
                                throw IOException("Arquivo inválido dentro do modelo de voz.")
                            }
                            if (entrada.isDirectory) {
                                destino.mkdirs()
                            } else {
                                destino.parentFile?.mkdirs()
                                FileOutputStream(destino).use { saida ->
                                    while (true) {
                                        val lidos = zip.read(buffer)
                                        if (lidos < 0) break
                                        saida.write(buffer, 0, lidos)
                                    }
                                }
                            }
                            zip.closeEntry()
                        }
                    }
                }
                concluir(Model(pastaModelo.absolutePath), null)
            } catch (erro: IOException) {
                concluir(null, erro)
            } catch (erro: Exception) {
                concluir(null, IOException("Falha ao preparar o modelo offline.", erro))
            }
        }
    }

    
    private fun concluir(pronto: Model?, erro: IOException?) {
        val pendentes = synchronized(this) {
            if (pronto != null) modelo = pronto
            carregando = false
            callbacks.toList().also { callbacks.clear() }
        }
        pendentes.forEach { it(pronto, erro) }
    }
}

private class TratamentoVoz {
    private var xAnterior = 0.0
    private var yAnterior = 0.0
    private var piso = 100.0
    private var ganho = 1.0
    private var ultimaVozMs = 0L

    
    fun processar(buffer: ByteArray, tamanho: Int, musicaAtiva: Boolean, agoraMs: Long): Boolean {
        val amostras = tamanho / 2
        if (amostras == 0) return false
        val filtrado = DoubleArray(amostras)
        var soma = 0.0
        for (i in 0 until amostras) {
            val baixo = buffer[2 * i].toInt() and 0xff
            val alto = buffer[2 * i + 1].toInt()
            val x = ((alto shl 8) or baixo).toDouble()
            val y = COEFICIENTE_PASSA_ALTA * (yAnterior + x - xAnterior)
            xAnterior = x
            yAnterior = y
            filtrado[i] = y
            soma += y * y
        }
        val rms = kotlin.math.sqrt(soma / amostras)
        val limiar = maxOf(piso * FATOR_ABERTURA_PORTAO, RMS_MINIMO_VOZ)
        val vozDetectada = rms >= limiar
        if (vozDetectada) ultimaVozMs = agoraMs
        val aberto = agoraMs - ultimaVozMs <= TEMPO_PORTAO_ABERTO_MS
        if (rms < piso) {
            piso = piso * 0.9 + rms * 0.1
        } else {
            val taxa = when {
                musicaAtiva -> 0.01
                !aberto -> 0.03
                else -> 0.002
            }
            piso += (rms - piso) * taxa
        }
        if (piso < 30.0) piso = 30.0
        if (vozDetectada) {
            val desejado = (RMS_ALVO_VOZ / maxOf(rms, 1.0)).coerceIn(1.0, GANHO_MAXIMO)
            val taxaGanho = if (desejado < ganho) 0.3 else 0.1
            ganho += (desejado - ganho) * taxaGanho
        }
        for (i in 0 until amostras) {
            val amostra = (filtrado[i] * ganho).toInt().coerceIn(-32768, 32767)
            buffer[2 * i] = (amostra and 0xff).toByte()
            buffer[2 * i + 1] = ((amostra shr 8) and 0xff).toByte()
        }
        return aberto
    }
}

class CapturaVozLocal private constructor(
    private val audio: AudioRecord,
    private val reconhecedor: Recognizer,
    private val efeitos: List<android.media.audiofx.AudioEffect>,
    private val gerenciadorAudio: AudioManager?,
) {
    @Volatile private var ativo = false
    @Volatile private var pausado = false
    private var threadCaptura: Thread? = null

    
    fun iniciar(
        ouvinte: VoskRecognitionListener,
        esperaMaximaMs: Long? = null,
        aoNivelMicrofone: ((Int) -> Unit)? = null,
    ) {
        if (ativo) return
        ativo = true
        threadCaptura = Thread({
            try {
                audio.startRecording()

                val buffer = ByteArray(maxOf(2_048, AudioRecord.getMinBufferSize(
                    TAXA_AMOSTRAGEM_VOZ,
                    AudioFormat.CHANNEL_IN_MONO,
                    AudioFormat.ENCODING_PCM_16BIT,
                )))
                val inicio = SystemClock.elapsedRealtime()
                var inicioFalaMs = 0L
                var ultimaAtualizacaoNivelMs = 0L
                var estavaPausado = false
                val tratamento = TratamentoVoz()
                val silencio = ByteArray(buffer.size)
                val pendente = ByteArray(buffer.size)
                var pendenteTamanho = buffer.size
                var pendenteAberto = false
                while (ativo) {
                    val lidos = audio.read(buffer, 0, buffer.size)
                    if (lidos <= 0) throw IOException("A gravação do microfone foi interrompida.")
                    val agora = SystemClock.elapsedRealtime()
                    if (pausado) {
                        if (!estavaPausado) reconhecedor.reset()
                        estavaPausado = true
                        pendenteAberto = false
                        inicioFalaMs = 0L
                        aoNivelMicrofone?.invoke(0)
                        continue
                    }
                    estavaPausado = false
                    if (aoNivelMicrofone != null && agora - ultimaAtualizacaoNivelMs >= 250L) {
                        aoNivelMicrofone(calcularNivel(buffer, lidos))
                        ultimaAtualizacaoNivelMs = agora
                    }
                    val abertoAgora = tratamento.processar(buffer, lidos, gerenciadorAudio?.isMusicActive == true, agora)
                    val paraEnviar = if (pendenteAberto || abertoAgora) pendente.copyOf(pendenteTamanho) else silencio
                    val tamanhoEnviar = pendenteTamanho
                    System.arraycopy(buffer, 0, pendente, 0, lidos)
                    pendenteTamanho = lidos
                    pendenteAberto = abertoAgora
                    if (reconhecedor.acceptWaveForm(paraEnviar, tamanhoEnviar)) {
                        val resultado = reconhecedor.result
                        if (JSONObject(resultado).optString("text").isNotBlank()) {
                            handlerVozLocal.post { ouvinte.onResult(resultado) }
                        }
                        inicioFalaMs = 0L
                    } else {
                        val parcial = reconhecedor.partialResult
                        if (JSONObject(parcial).optString("partial").isNotBlank()) {
                            if (inicioFalaMs == 0L) inicioFalaMs = SystemClock.elapsedRealtime()
                            handlerVozLocal.post { ouvinte.onPartialResult(parcial) }
                        }
                    }
                    if (inicioFalaMs != 0L && agora - inicioFalaMs >= TEMPO_MAXIMO_FRASE_MS) {
                        val final = reconhecedor.finalResult
                        handlerVozLocal.post {
                            if (JSONObject(final).optString("text").isNotBlank()) {
                                ouvinte.onFinalResult(final)
                            } else {
                                ouvinte.onTimeout()
                            }
                        }
                        if (esperaMaximaMs != null) break
                        reconhecedor.reset()
                        inicioFalaMs = 0L
                    } else if (
                        esperaMaximaMs != null && inicioFalaMs == 0L &&
                        agora - inicio >= esperaMaximaMs
                    ) {
                        handlerVozLocal.post { ouvinte.onTimeout() }
                        break
                    }
                }
            } catch (erro: Exception) {
                if (ativo) handlerVozLocal.post { ouvinte.onError(erro) }
            }
        }, "jarvis-microfone-local").apply { start() }
    }

    // Calcula rms
    private fun calcularRms(buffer: ByteArray, tamanho: Int): Double {
        var somaQuadrados = 0.0
        var amostras = 0
        var indice = 0
        while (indice + 1 < tamanho) {
            val semSinal = (buffer[indice].toInt() and 0xff) or
                    ((buffer[indice + 1].toInt() and 0xff) shl 8)
            val amostra = if (semSinal > 32767) semSinal - 65536 else semSinal
            somaQuadrados += amostra.toDouble() * amostra
            amostras++
            indice += 2
        }
        if (amostras == 0) return 0.0
        return kotlin.math.sqrt(somaQuadrados / amostras)
    }

    // Calcula nivel
    private fun calcularNivel(buffer: ByteArray, tamanho: Int): Int =
        ((calcularRms(buffer, tamanho) / 3000.0) * 100.0).toInt().coerceIn(0, 100)

    
    fun pausar(pausar: Boolean) { pausado = pausar }

    
    fun encerrar() {
        ativo = false
        try { if (audio.recordingState == AudioRecord.RECORDSTATE_RECORDING) audio.stop() } catch (_: Exception) {}
        try { threadCaptura?.join(1000) } catch (_: InterruptedException) { Thread.currentThread().interrupt() }
        try { audio.release() } catch (_: Exception) {}
        try { reconhecedor.close() } catch (_: Exception) {}
        efeitos.forEach { try { it.release() } catch (_: Exception) {} }
    }

    companion object {
        @SuppressLint("MissingPermission")
        
        fun criar(modelo: Model, contexto: Context? = null, rota: RotaEntrada? = null): CapturaVozLocal {
            val formato = AudioFormat.Builder()
                .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                .setSampleRate(TAXA_AMOSTRAGEM_VOZ)
                .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                .build()
            val minimo = AudioRecord.getMinBufferSize(
                TAXA_AMOSTRAGEM_VOZ,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
            )
            if (minimo <= 0) throw IOException("O microfone do celular não está disponível.")

            
            fun gravador(fonte: Int) = AudioRecord.Builder()
                .setAudioSource(fonte)
                .setAudioFormat(formato)
                .setBufferSizeInBytes(maxOf(minimo, TAXA_AMOSTRAGEM_VOZ / 5 * 2))
                .build()

            var audioPronto: AudioRecord? = null
            // Nunca VOICE COMMUNICATION: com fone
            val fontes = listOf(MediaRecorder.AudioSource.VOICE_RECOGNITION, MediaRecorder.AudioSource.MIC)
            // Sem fone P2/USB, fixa o microfone
            val dispositivoEntrada = rota?.dispositivo
                ?: contexto?.let { RoteamentoAudio.microfoneDoCelular(it) }
            for (fonte in fontes) {
                val candidato = try { gravador(fonte) } catch (_: Exception) { null } ?: continue
                if (candidato.state == AudioRecord.STATE_INITIALIZED) {
                    dispositivoEntrada?.let {
                        if (!candidato.setPreferredDevice(it)) Log.w("CapturaVozLocal", "Não consegui fixar o microfone.")
                    }
                    audioPronto = candidato
                    break
                }
                candidato.release()
            }
            val gerenciadorAudio = contexto?.applicationContext?.getSystemService(Context.AUDIO_SERVICE) as? AudioManager
            return construir(modelo, audioPronto ?: throw IOException("Não consegui abrir o microfone do celular."), gerenciadorAudio)
        }

        
        private fun construir(modelo: Model, audio: AudioRecord, gerenciadorAudio: AudioManager?): CapturaVozLocal {
            val recognizer = Recognizer(modelo, TAXA_AMOSTRAGEM_VOZ.toFloat())
            try {

                recognizer.setEndpointerDelays(
                    TEMPO_ESPERA_FALA_MS / 1000f,
                    TEMPO_FIM_FRASE_MS / 1000f,
                    TEMPO_MAXIMO_FRASE_MS / 1000f,
                )
                val efeitos = mutableListOf<android.media.audiofx.AudioEffect>()
                
                fun ativarEfeito(criar: () -> android.media.audiofx.AudioEffect?) {
                    try { criar()?.also { it.enabled = true; efeitos.add(it) } }
                    catch (_: Exception) {  }
                }
                if (NoiseSuppressor.isAvailable()) ativarEfeito { NoiseSuppressor.create(audio.audioSessionId) }
                if (AutomaticGainControl.isAvailable()) ativarEfeito { AutomaticGainControl.create(audio.audioSessionId) }
                return CapturaVozLocal(audio, recognizer, efeitos, gerenciadorAudio)
            } catch (erro: Exception) {
                recognizer.close()
                audio.release()
                throw erro
            }
        }
    }
}

// Reconhece fala local
fun reconhecerFalaLocal(
    contexto: Context,
    aoConcluir: (String?) -> Unit,
    aoFalhar: (String) -> Unit,
) {
    ModeloVozLocal.carregar(contexto) { modelo, erro ->
        if (modelo == null) {
            aoFalhar("Não consegui preparar o reconhecimento offline: ${erro?.message ?: "erro desconhecido"}")
            return@carregar
        }

        val rota = RoteamentoAudio.entradaPreferida(contexto)
        
        fun liberarRota() {
            if (!ServicoEscutaJarvis.emExecucao) RoteamentoAudio.liberarEntrada(contexto)
        }
        RoteamentoAudio.ativarEntrada(contexto, rota, handlerVozLocal) {
            val captura = try { CapturaVozLocal.criar(modelo, contexto, rota) }
            catch (falha: Exception) {
                liberarRota()
                aoFalhar(falha.message ?: "Não consegui abrir o microfone.")
                return@ativarEntrada
            }
            var finalizado = false
            
            fun terminar(texto: String?, mensagemErro: String? = null) {
                if (finalizado) return
                finalizado = true
                captura.encerrar()
                liberarRota()
                if (mensagemErro == null) aoConcluir(texto) else aoFalhar(mensagemErro)
            }

            captura.iniciar(object : VoskRecognitionListener {
                
                override fun onResult(hypothesis: String?) {
                    val texto = try { JSONObject(hypothesis.orEmpty()).optString("text") } catch (_: Exception) { "" }
                    if (texto.isNotBlank()) terminar(texto)
                }
                // Trata final resultado
                override fun onFinalResult(hypothesis: String?) {
                    val texto = try { JSONObject(hypothesis.orEmpty()).optString("text") } catch (_: Exception) { "" }
                    terminar(texto.ifBlank { null }, if (texto.isBlank()) "Não entendi a fala." else null)
                }
                // Trata partial resultado
                override fun onPartialResult(hypothesis: String?) {}
                
                override fun onError(exception: Exception?) {
                    terminar(null, exception?.message ?: "Falha no reconhecimento offline.")
                }
                // Trata timeout
                override fun onTimeout() { terminar(null, "Não ouvi uma frase antes do tempo limite.") }
            }, TEMPO_ESPERA_FALA_MS + TEMPO_MAXIMO_FRASE_MS)
        }
    }
}
