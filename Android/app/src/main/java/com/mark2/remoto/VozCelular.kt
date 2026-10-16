package com.mark2.remoto

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.os.Handler
import android.os.Looper
import java.io.File

/** Reproduz somente o áudio sintetizado pelo servidor Jarvis; não usa TTS do Android. */
object VozCelular {
    @Volatile var versao = 0
        private set
    @Volatile private var contexto: Context? = null
    @Volatile private var playerRemoto: MediaPlayer? = null

    fun inicializar(ctx: Context) { contexto = ctx.applicationContext }

    fun interromper() {
        versao++
        Handler(Looper.getMainLooper()).post { liberarPlayer() }
    }

    fun falar(host: String, porta: Int, texto: String, aoErro: (String) -> Unit = {}) =
        falarResposta(host, porta, texto, aoErro)

    fun falarResposta(host: String, porta: Int, texto: String, aoErro: (String) -> Unit = {}) {
        val ctx = contexto ?: return aoErro("Áudio do Jarvis indisponível neste aparelho.")
        if (texto.isBlank() || !CofreLocal.obter(ctx).getBoolean("voz_celular", true)) return
        val versaoPedido = versao
        Thread({
            var temporario: File? = null
            try {
                val bytes = Mark2Api.sintetizarVoz(host, porta, texto.take(4000))
                require(bytes.size > 44 && bytes.copyOfRange(0, 4).decodeToString() == "RIFF") {
                    "O servidor retornou um áudio inválido. Confira a síntese de voz do Jarvis."
                }
                if (versaoPedido != versao) return@Thread
                temporario = File.createTempFile("jarvis-voz-", ".wav", ctx.cacheDir).apply { writeBytes(bytes) }
                val arquivo = requireNotNull(temporario)
                Handler(Looper.getMainLooper()).post {
                    if (versaoPedido != versao) { arquivo.delete(); return@post }
                    liberarPlayer()
                    val player = MediaPlayer()
                    playerRemoto = player
                    player.setAudioAttributes(AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ASSISTANT)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
                    player.setDataSource(arquivo.absolutePath)
                    player.setOnCompletionListener { it.release(); if (playerRemoto === it) playerRemoto = null; arquivo.delete() }
                    player.setOnErrorListener { mp, _, _ -> mp.release(); if (playerRemoto === mp) playerRemoto = null; arquivo.delete(); aoErro("Não foi possível reproduzir o áudio do Jarvis no celular."); true }
                    player.setOnPreparedListener { if (versaoPedido == versao) it.start() else { it.release(); arquivo.delete() } }
                    player.prepareAsync()
                }
            } catch (falha: Exception) {
                temporario?.delete()
                Handler(Looper.getMainLooper()).post {
                    if (versaoPedido == versao) aoErro(falha.message ?: "Não foi possível receber o áudio sintetizado pelo Jarvis.")
                }
            }
        }, "jarvis-audio-remoto").start()
    }

    private fun liberarPlayer() {
        playerRemoto?.let { atual ->
            runCatching { if (atual.isPlaying) atual.stop() }
            runCatching { atual.release() }
        }
        playerRemoto = null
    }

    fun fechar() { interromper(); contexto = null }
}
