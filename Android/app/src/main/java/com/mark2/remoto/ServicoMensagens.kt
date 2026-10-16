package com.mark2.remoto

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.os.Build
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit

class ServicoMensagens : NotificationListenerService() {
    private val fila = ThreadPoolExecutor(1, 1, 30, TimeUnit.SECONDS, ArrayBlockingQueue(20), ThreadPoolExecutor.DiscardOldestPolicy()).apply { allowCoreThreadTimeOut(true) }
    private val contador = ContadorAvisos()
    @Volatile private var appsGatilhos = emptySet<String>()
    @Volatile private var cacheGatilhosEm = 0L

    // Retoma a contagem das mensagens
    override fun onCreate() {
        super.onCreate()
        val prefs = CofreLocal.obter(this)
        val vistos = runCatching { JSONArray(prefs.getString("avisos_conhecidos", "[]")) }.getOrDefault(JSONArray())
        contador.restaurar((0 until vistos.length()).map { vistos.optString(it) }, prefs.getInt("saldo_whatsapp",0), prefs.getInt("saldo_instagram",0))
    }

    // Resume novas mensagens recebidas
    @Suppress("DEPRECATION")
    override fun onNotificationPosted(aviso: StatusBarNotification?) {
        if (aviso == null || aviso.packageName == packageName) return
        if (aviso.notification.flags and (Notification.FLAG_GROUP_SUMMARY or Notification.FLAG_ONGOING_EVENT) == 0) {
            val cacheVencido = System.currentTimeMillis() - cacheGatilhosEm > 60_000
            if (cacheVencido || aviso.packageName in appsGatilhos) fila.execute {
                if (System.currentTimeMillis() - cacheGatilhosEm > 60_000) atualizarAppsGatilhos()
                if (aviso.packageName in appsGatilhos) processarGatilhoDeRotina(aviso)
            }
        }
        if (aviso.packageName !in setOf("com.whatsapp", "com.whatsapp.w4b", "com.instagram.android")) return
        val notificacao = aviso.notification
        if (notificacao.flags and (Notification.FLAG_GROUP_SUMMARY or Notification.FLAG_ONGOING_EVENT) != 0) return
        val prefs = CofreLocal.obter(this)
        val avisar = prefs.getBoolean("avisos_mensagens", true)
        val compartilhar = prefs.getBoolean("compartilhar_whatsapp", false) && aviso.packageName != "com.instagram.android"
        if (!avisar && !compartilhar) return
        val remetente = notificacao.extras.getCharSequence(Notification.EXTRA_TITLE)?.toString().orEmpty()
        val texto = (notificacao.extras.getCharSequence(Notification.EXTRA_BIG_TEXT) ?: notificacao.extras.getCharSequence(Notification.EXTRA_TEXT))?.toString().orEmpty()
        if (texto.isBlank()) return
        val mensagens = NotificationCompat.MessagingStyle.extractMessagingStyleFromNotification(notificacao)?.messages ?: emptyList()
        val recebidas = mensagens.filter { it.sender != null }
        if (mensagens.isNotEmpty() && recebidas.isEmpty()) return
        val canalDireto = notificacao.channelId?.lowercase()?.let { it.contains("direct") || it.contains("message") || it.contains("mensagen") } == true
        if (mensagens.isEmpty() && notificacao.category != null && notificacao.category != Notification.CATEGORY_MESSAGE && !canalDireto) return
        val ids = if (recebidas.isNotEmpty()) recebidas.map { hash(listOf(aviso.packageName, aviso.key, it.timestamp.toString(), it.sender.toString(), it.text.toString()).joinToString("|")) }
            else listOf(hash(listOf(aviso.packageName, aviso.key, (notificacao.`when`.takeIf { it > 0 } ?: aviso.postTime).toString(), texto).joinToString("|")))
        val app = if (aviso.packageName == "com.instagram.android") "instagram" else "whatsapp"
        val novos = ids.any { it !in contador.conhecidos }
        val lotes = contador.registrar(app, ids)
        prefs.edit().putString("avisos_conhecidos",JSONArray(contador.conhecidos.toList()).toString())
            .putInt("saldo_whatsapp",contador.whatsapp).putInt("saldo_instagram",contador.instagram).apply()
        if (avisar && lotes > 0) avisarNoCelular(app, lotes)
        if (!compartilhar || !novos || remetente.isBlank()) return
        val host = prefs.getString("host", "").orEmpty()
        if (host.isBlank()) return
        val porta = prefs.getInt("porta", 5679)
        val dados = JSONObject().put("pacote",aviso.packageName).put("id",aviso.key + ":" + aviso.postTime).put("remetente",remetente.take(120)).put("texto",texto.take(2000))
        fila.execute {
            if (prefs.getBoolean("compartilhar_whatsapp", false)) runCatching {
                Mark2Api.inicializar(applicationContext)
                Mark2Api.salvarPessoal(host,porta,"/pessoal/mensagens/celular",dados)
            }
        }
    }

    // Mantém em memória apenas os pacotes que o usuário selecionou em rotinas ativas.
    private fun atualizarAppsGatilhos() {
        val prefs = CofreLocal.obter(this)
        val host = prefs.getString("host", "").orEmpty()
        if (host.isBlank()) return
        try {
            val porta = prefs.getInt("porta", 5679)
            Mark2Api.inicializar(applicationContext)
            val rotinas = Mark2Api.rotinasCasa(host, porta)
            appsGatilhos = buildSet {
                for (indice in 0 until rotinas.length()) {
                    val rotina = rotinas.optJSONObject(indice) ?: continue
                    if (!rotina.optBoolean("ativa")) continue
                    val apps = rotina.optJSONArray("apps_notificacao") ?: continue
                    for (i in 0 until apps.length()) add(apps.optString(i))
                }
            }
            cacheGatilhosEm = System.currentTimeMillis()
        } catch (erro: Exception) {
            android.util.Log.d("JarvisNotificacoes", "Não foi possível atualizar os apps selecionados: ${erro.message}")
            cacheGatilhosEm = System.currentTimeMillis()
        }
    }

    // As notificações só disparam rotinas quando o usuário seleciona explicitamente o app nelas.
    private fun processarGatilhoDeRotina(aviso: StatusBarNotification) {
        val prefs = CofreLocal.obter(this)
        val host = prefs.getString("host", "").orEmpty()
        if (host.isBlank()) return
        val porta = prefs.getInt("porta", 5679)
        val assinatura = "${aviso.key}:${aviso.postTime}"
        val chavePref = "gatilho_notificacao_${aviso.packageName}"
        if (prefs.getString(chavePref, "") == assinatura) return
        try {
            Mark2Api.inicializar(applicationContext)
            if (aviso.packageName !in appsGatilhos) return
            prefs.edit().putString(chavePref, assinatura).apply()
            val resultado = Mark2Api.dispararRotinaNotificacao(host, porta, aviso.packageName)
            if (!resultado.optBoolean("disparada")) return
            val falas = (0 until (resultado.optJSONArray("falas")?.length() ?: 0))
                .mapNotNull { resultado.optJSONArray("falas")?.optString(it) }.filter(String::isNotBlank)
            val nomeApp = runCatching { packageManager.getApplicationLabel(packageManager.getApplicationInfo(aviso.packageName, 0)).toString() }
                .getOrDefault("${aviso.packageName.substringAfterLast('.')}")
            val anuncio = (listOf("Senhor, chegou uma notificação de $nomeApp.") + falas).joinToString(" ")
            VozCelular.inicializar(applicationContext)
            VozCelular.falar(host, porta, anuncio) { erro -> android.util.Log.w("JarvisNotificacoes", erro) }
        } catch (erro: Exception) {
            android.util.Log.w("JarvisNotificacoes", "Não foi possível processar o gatilho de notificação: ${erro.message}")
        }
    }

    // Gera chave sem guardar conteúdo
    private fun hash(texto: String): String = MessageDigest.getInstance("SHA-256").digest(texto.toByteArray()).joinToString("") { "%02x".format(it) }

    // Avisa apenas nos limites pedidos
    private fun avisarNoCelular(app: String, lotes: Int) {
        if (!NotificationManagerCompat.from(this).areNotificationsEnabled()) return
        val nome = if (app == "instagram") "Instagram" else "WhatsApp"
        val quantidade = lotes * if (app == "instagram") 2 else 5
        val gestor = getSystemService(NotificationManager::class.java)
        val canal = NotificationChannel("jarvis_mensagens", "Avisos de mensagens", NotificationManager.IMPORTANCE_DEFAULT)
        canal.description = "WhatsApp: a cada 5. Instagram: a cada 2."
        gestor.createNotificationChannel(canal)
        val destino = packageManager.getLaunchIntentForPackage(if (app == "instagram") "com.instagram.android" else "com.whatsapp") ?: Intent(this, MainActivity::class.java)
        val abrir = PendingIntent.getActivity(this, if (app == "instagram") 2 else 5, destino, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val aviso = NotificationCompat.Builder(this,"jarvis_mensagens")
            .setSmallIcon(android.R.drawable.ic_dialog_email).setContentTitle("Jarvis · $nome")
            .setContentText("Senhor, chegaram $quantidade mensagens novas no $nome.")
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE).setContentIntent(abrir).setAutoCancel(true).setOnlyAlertOnce(false).build()
        try { gestor.notify(if (app == "instagram") 702 else 705, aviso) } catch (_: SecurityException) { }
    }

    // Libera recursos do serviço
    override fun onDestroy() {
        fila.shutdownNow()
        super.onDestroy()
    }
}
