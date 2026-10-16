package com.mark2.remoto

import android.os.Build
import android.content.Context
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Call
import okhttp3.Callback
import okhttp3.Response
import java.io.IOException
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.security.MessageDigest
import java.security.SecureRandom
import java.security.cert.X509Certificate
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager

object Mark2Api {

    @Volatile private var contextoApp: android.app.Application? = null
    
    fun inicializar(context: Context) { contextoApp = context.applicationContext as? android.app.Application }
    data class Gravacao(val nome: String, val tamanho: Long, val url: String, val titulo: String = "Gravação de segurança", val hora: String = "", val duracaoSegundos: Double? = null, val zona: String? = null, val tipo: String = "", val foto: String? = null)
    data class EstadoSeguranca(val armado: Boolean, val ativa: Boolean, val cameraConectada: Boolean, val pessoas: Int, val ultimaFoto: String?, val ultimaVisita: String?, val pessoasDetectadas: Int = 0, val eventoHora: String? = null)
    data class EstadoPtz(val estado: String, val capacidades: JSONObject)

    data class HistoricoItem(
        val hora: String,
        val texto: String,
        val resposta: String,
        val origem: String,
    )

    data class Tarefa(
        val id: Int,
        val nome: String,
        val horario: String,
        val ativa: Boolean,
        val antecedencias: String,
        val conteudo: String,
    )

    data class RespostaSimples(val sucesso: Boolean, val mensagem: String)

    // Valida o certificado do servidor
    private fun trustManager(host: String, porta: Int) = object : X509TrustManager {
        // Verifica cliente trusted
        override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) { throw java.security.cert.CertificateException("Certificado de cliente não aceito") }
        // Verifica servidor trusted
        override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
            val certificado = chain?.firstOrNull() ?: throw java.security.cert.CertificateException("Certificado ausente")
            certificado.checkValidity()
            val fingerprint = MessageDigest.getInstance("SHA-256").digest(certificado.encoded).joinToString("") { "%02X".format(it) }
            val prefs = contextoApp?.let { CofreLocal.obter(it, "mark2_pins") } ?: throw java.security.cert.CertificateException("Armazenamento de confiança indisponível")
            val chave = "${host.lowercase()}:$porta"
            val salvo = prefs.getString(chave, null)
            if (salvo == null) {
                throw java.security.cert.CertificateException("Copie a impressão digital do PC nas configurações")
            } else if (!MessageDigest.isEqual(salvo.toByteArray(), fingerprint.toByteArray())) {
                throw java.security.cert.CertificateException("O certificado do Jarvis mudou. Verifique o servidor antes de reconectar.")
            }
        }
        // Consulta accepted issuers
        override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
    }

    private val clientes = linkedMapOf<String, OkHttpClient>()

    @Synchronized
    // Cria cliente
    private fun criarCliente(host: String, porta: Int, timeout: Long = 30): OkHttpClient {
        val chaveCliente = "$host:$porta:$timeout"
        clientes[chaveCliente]?.let { return it }
        val tm = trustManager(host, porta)
        val ssl = SSLContext.getInstance("TLS").apply { init(null, arrayOf<TrustManager>(tm), SecureRandom()) }
        val cliente = OkHttpClient.Builder().sslSocketFactory(ssl.socketFactory, tm)
            .hostnameVerifier { _, _ -> true }.addInterceptor(identificarDispositivo)
            .followRedirects(false).followSslRedirects(false)
            .connectTimeout(8, TimeUnit.SECONDS).readTimeout(timeout, TimeUnit.SECONDS)
            .writeTimeout(20, TimeUnit.SECONDS).callTimeout(timeout + 8, TimeUnit.SECONDS).build()
        if (clientes.size >= 4) clientes.remove(clientes.keys.first())?.connectionPool?.evictAll()
        clientes[chaveCliente] = cliente
        return cliente
    }

    /* Nome do aparelho, enviado em todo */
    private val nomeDispositivo: String = "${Build.MANUFACTURER} ${Build.MODEL}"
        .filter { it.code in 32..126 }
        .trim()
        .ifBlank { "Android" }
        .take(40)

    private val identificarDispositivo = Interceptor { cadeia ->
        cadeia.proceed(
            cadeia.request().newBuilder()
                .header("X-Mark2-Dispositivo", nomeDispositivo)
                .header("Authorization", "Bearer " + (contextoApp?.let { CofreLocal.obter(it).getString("token_remoto", "") } ?: ""))
                .build()
        )
    }

    private val jsonMediaType = "application/json; charset=utf-8".toMediaType()

    
    private fun mensagemDeErro(corpo: String, padrao: String): String {
        val texto = corpo.trim()
        if (texto.startsWith("{")) {
            try {
                val obj = JSONObject(texto)
                val msg = obj.optString("erro").ifBlank { obj.optString("mensagem") }
                if (msg.isNotBlank()) return msg
            } catch (e: Exception) {

            }
        }
        return texto.ifBlank { padrao }
    }

    
    private fun mensagemDeSucesso(corpo: String): String? {
        return try {
            JSONObject(corpo).optString("mensagem").ifBlank { null }
        } catch (e: Exception) {
            null
        }
    }

    
    private fun baseUrl(host: String, porta: Int): String {
        require(host.matches(Regex("[A-Za-z0-9.:-]{1,253}")) && porta in 1..65535) { "Endereço inválido" }
        return "https://$host:$porta"
    }

    
    private fun get(host: String, porta: Int, caminho: String): String {
        val requisicao = Request.Builder().url("${baseUrl(host, porta)}$caminho").get().build()
        criarCliente(host, porta).newCall(requisicao).execute().use { resposta ->
            val corpo = resposta.body?.string().orEmpty()
            if (!resposta.isSuccessful) {
                throw RuntimeException(mensagemDeErro(corpo, "Erro ${resposta.code} em $caminho."))
            }
            return corpo
        }
    }

    // Envia dados ao servidor
    private fun post(host: String, porta: Int, caminho: String, corpoJson: JSONObject = JSONObject()): String {
        val corpo = corpoJson.toString().toRequestBody(jsonMediaType)
        val requisicao = Request.Builder().url("${baseUrl(host, porta)}$caminho").post(corpo).build()
        criarCliente(host, porta).newCall(requisicao).execute().use { resposta ->
            val corpoResposta = resposta.body?.string().orEmpty()
            if (!resposta.isSuccessful) {
                throw RuntimeException(mensagemDeErro(corpoResposta, "Erro ${resposta.code} em $caminho."))
            }
            return corpoResposta
        }
    }

    // Cancela consulta ao sair da tela
    suspend fun pessoalAsync(host: String, porta: Int, caminho: String): String = suspendCancellableCoroutine { retorno ->
        require(caminho in setOf("/agenda", "/memoria/notas", "/memoria/estado", "/pessoal/mensagens/celular", "/noticias/g1?categoria=geral", "/gmail/mensagens"))
        val chamada = criarCliente(host,porta).newCall(Request.Builder().url("${baseUrl(host,porta)}$caminho").build())
        retorno.invokeOnCancellation { chamada.cancel() }
        chamada.enqueue(object : Callback {
            // Informa falha da consulta
            override fun onFailure(call: Call, erro: IOException) {
                if (retorno.isActive) retorno.resumeWithException(erro)
            }
            // Libera conexão após a leitura
            override fun onResponse(call: Call, resposta: Response) {
                resposta.use {
                    try {
                        val texto = it.body?.string().orEmpty()
                        if (retorno.isActive) {
                            if (it.isSuccessful) retorno.resume(texto)
                            else retorno.resumeWithException(IOException(mensagemDeErro(texto,"Erro ao consultar o Jarvis")))
                        }
                    } catch (erro: IOException) { if (retorno.isActive) retorno.resumeWithException(erro) }
                }
            }
        })
    }

    
    fun pessoal(host: String, porta: Int, caminho: String): String {
        require(caminho in setOf("/agenda", "/memoria/notas", "/memoria/estado", "/pessoal/mensagens/celular", "/noticias/g1?categoria=geral", "/gmail/mensagens"))
        return get(host, porta, caminho)
    }

    // Salva pessoal
    fun salvarPessoal(host: String, porta: Int, caminho: String, dados: JSONObject): String {
        require(caminho in setOf("/agenda", "/memoria/notas", "/pessoal/mensagens/celular"))
        return post(host, porta, caminho, dados)
    }

    // Remove pessoal
    fun removerPessoal(host: String, porta: Int, caminho: String) {
        require(caminho.matches(Regex("/agenda/[0-9]+|/memoria/notas/[a-zA-Z0-9-]+")))
        val requisicao = Request.Builder().url("${baseUrl(host, porta)}$caminho").delete().build()
        criarCliente(host, porta).newCall(requisicao).execute().use {
            if (!it.isSuccessful) throw RuntimeException("Não foi possível remover o item")
        }
    }

    // Envia comando
    fun enviarComando(host: String, porta: Int, texto: String, falarNoPc: Boolean = true, confirmarEncerramento: Boolean = false, usarLlm: Boolean = true, sessionId: String? = null): String {
        val dados = JSONObject()
            .put("texto", texto)
            .put("falar_no_pc", falarNoPc)
            .put("device", "Android")
            .put("confirmar_encerramento", confirmarEncerramento)
            .put("usar_llm", usarLlm)
        if (!sessionId.isNullOrBlank()) dados.put("session_id", sessionId)
        val corpo = dados.toString().toRequestBody(jsonMediaType)
        val requisicao = Request.Builder().url("${baseUrl(host, porta)}/comando").post(corpo).build()
        var tentativasRestantes = 2
        while (true) {
            val resultado = criarCliente(host, porta).newCall(requisicao).execute().use { resposta ->
                if (resposta.code == 429 && tentativasRestantes > 0) null
                else {
                    val corpoResposta = resposta.body?.string().orEmpty()
                    if (!resposta.isSuccessful) throw RuntimeException(mensagemDeErro(corpoResposta, "Erro ${resposta.code} ao falar com o Jarvis."))
                    corpoResposta
                }
            }
            if (resultado != null) return resultado
            tentativasRestantes--
            Thread.sleep(1500)
        }
    }

    fun listarSessoesChat(host: String, porta: Int): List<JSONObject> {
        val array = JSONArray(get(host, porta, "/api/sessions"))
        return (0 until array.length()).mapNotNull { array.optJSONObject(it) }
    }

    fun buscarMensagensSessao(host: String, porta: Int, sessionId: String = "principal"): List<JSONObject> {
        require(sessionId.matches(Regex("[A-Za-z0-9_-]{1,120}")))
        val array = JSONArray(get(host, porta, "/api/sessions/$sessionId/messages?limit=100"))
        return (0 until array.length()).mapNotNull { array.optJSONObject(it) }
    }

    // Sintetiza voz
    fun sintetizarVoz(host: String, porta: Int, texto: String): ByteArray {
        val corpo = JSONObject().put("texto", texto).toString().toRequestBody(jsonMediaType)
        val requisicao = Request.Builder().url("${baseUrl(host, porta)}/voz/sintetizar").post(corpo).build()
        criarCliente(host, porta, 90).newCall(requisicao).execute().use { resposta ->
            if (!resposta.isSuccessful) {
                val corpoErro = resposta.body?.string().orEmpty()
                throw RuntimeException(mensagemDeErro(corpoErro, "Erro ${resposta.code} ao sintetizar voz."))
            }
            return resposta.body?.bytes() ?: ByteArray(0)
        }
    }

    // Busca historico
    fun buscarHistorico(host: String, porta: Int): List<HistoricoItem> {
        val array = JSONArray(get(host, porta, "/historico"))
        val itens = mutableListOf<HistoricoItem>()
        for (i in 0 until array.length()) {
            val obj = array.getJSONObject(i)
            itens.add(
                HistoricoItem(
                    hora = obj.optString("hora"),
                    texto = obj.optString("texto"),
                    resposta = obj.optString("resposta"),
                    origem = obj.optString("origem"),
                )
            )
        }

        return itens.asReversed()
    }

    // Verifica conexão do servidor
    fun online(host: String, porta: Int): Boolean {
        return try {
            get(host, porta, "/status")
            true
        } catch (e: Exception) {
            false
        }
    }

    // Busca comandos rapidos
    fun buscarComandosRapidos(host: String, porta: Int): List<String> {
        val array = JSONArray(get(host, porta, "/comandos-rapidos"))
        return (0 until array.length()).map { array.getString(it) }
    }

    
    fun estadoServidorLocal(host: String, porta: Int): Boolean? {
        return try {
            val obj = JSONObject(get(host, porta, "/llm/estado"))
            if (obj.has("ativo")) obj.optBoolean("ativo") else null
        } catch (e: Exception) {
            null
        }
    }

    
    fun definirServidorLocalAtivo(host: String, porta: Int, ativo: Boolean): Boolean {
        val obj = JSONObject(post(host, porta, "/llm/ativo", JSONObject().put("ativo", ativo)))
        return obj.optBoolean("ativo", ativo)
    }

    // Para fala
    fun pararFala(host: String, porta: Int) {
        try { post(host, porta, "/atividade/llm/cancelar") } catch (e: Exception) {  }
        try { post(host, porta, "/voz/parar") } catch (e: Exception) {  }
    }

    // Lista tarefas
    fun listarTarefas(host: String, porta: Int): List<Tarefa> {
        val array = JSONArray(get(host, porta, "/tarefas"))
        val itens = mutableListOf<Tarefa>()
        for (i in 0 until array.length()) {
            val obj = array.getJSONObject(i)
            itens.add(
                Tarefa(
                    id = obj.optInt("id"),
                    nome = obj.optString("nome"),
                    horario = obj.optString("horario"),
                    ativa = obj.optBoolean("ativa", true),
                    antecedencias = obj.optString("antecedencias"),
                    conteudo = obj.optString("conteudo"),
                )
            )
        }
        return itens
    }

    // Cria tarefa
    fun criarTarefa(host: String, porta: Int, nome: String, horario: String): RespostaSimples {
        val corpo = JSONObject().put("nome", nome).put("horario", horario)
        val obj = JSONObject(post(host, porta, "/tarefas", corpo))
        return RespostaSimples(obj.optBoolean("sucesso", false), obj.optString("mensagem"))
    }

    // Define tarefa ativa
    fun definirTarefaAtiva(host: String, porta: Int, id: Int, ativa: Boolean) {
        post(host, porta, "/tarefas/$id/ativa", JSONObject().put("ativa", ativa))
    }

    // Remove tarefa
    fun removerTarefa(host: String, porta: Int, id: Int) {
        post(host, porta, "/tarefas/$id/remover")
    }

    // Lista apps pc
    fun listarAppsPc(host: String, porta: Int): List<String> {
        val corpo = get(host, porta, "/pc/apps")
        val nomes = mutableListOf<String>()
        val trecho = corpo.trim()
        if (trecho.startsWith("[")) {
            val array = JSONArray(trecho)
            for (i in 0 until array.length()) {
                when (val item = array.get(i)) {
                    is String -> nomes.add(item)
                    is JSONObject -> nomes.add(item.optString("nome", item.optString("app")))
                    else -> nomes.add(item.toString())
                }
            }
        } else if (trecho.startsWith("{")) {
            val obj = JSONObject(trecho)
            obj.keys().forEach { chave -> nomes.add(chave) }
        }
        return nomes
    }

    // Abre app pc
    fun abrirAppPc(host: String, porta: Int, nome: String): RespostaSimples {
        val obj = JSONObject(post(host, porta, "/pc/abrir_app", JSONObject().put("app", nome)))
        return RespostaSimples(obj.optBoolean("sucesso", false), obj.optString("mensagem"))
    }

    
    fun volumePc(host: String, porta: Int, acao: String): String? =
        mensagemDeSucesso(post(host, porta, "/pc/volume", JSONObject().put("acao", acao)))

    
    fun midiaPc(host: String, porta: Int, acao: String): String? =
        mensagemDeSucesso(post(host, porta, "/pc/midia", JSONObject().put("acao", acao)))

    
    fun bloquearPc(host: String, porta: Int): String? =
        mensagemDeSucesso(post(host, porta, "/pc/bloquear"))

    
    fun desligarPc(host: String, porta: Int): String? =
        mensagemDeSucesso(post(host, porta, "/pc/desligar", JSONObject().put("confirmar", true)))

    
    fun reiniciarPc(host: String, porta: Int): String? =
        mensagemDeSucesso(post(host, porta, "/pc/reiniciar", JSONObject().put("confirmar", true)))

    // Cancela desligamento pc
    fun cancelarDesligamentoPc(host: String, porta: Int): String? =
        mensagemDeSucesso(post(host, porta, "/pc/cancelar_desligamento"))

    
    fun aguardarComandoMidiaTelefone(host: String, porta: Int, versao: Int): Pair<Int, String?> {
        val requisicao = Request.Builder()
            .url("${baseUrl(host, porta)}/telefone/midia/aguardar?versao=$versao")
            .get()
            .build()
        criarCliente(host, porta, 40).newCall(requisicao).execute().use { resposta ->
            val corpo = resposta.body?.string().orEmpty()
            if (!resposta.isSuccessful) {
                throw RuntimeException(mensagemDeErro(corpo, "Erro ${resposta.code} ao aguardar comando de mídia."))
            }
            val obj = JSONObject(corpo)
            val versaoAtual = obj.optInt("versao", versao)
            val acao = if (obj.isNull("acao")) null else obj.optString("acao").ifBlank { null }
            return Pair(versaoAtual, acao)
        }
    }

    // Envia foto
    fun enviarFoto(host: String, porta: Int, imagemBase64: String, pergunta: String?, sessionId: String = "principal"): String {
        val corpo = JSONObject().put("imagem", imagemBase64).put("pergunta", pergunta ?: "Analise esta imagem")
            .put("session_id", sessionId).put("device", "Android").put("falar_no_pc", false)
        val obj = JSONObject(post(host, porta, "/visao/foto", corpo))
        return obj.optString("resposta")
    }

    
    fun analisarVideo(host: String, porta: Int, bytes: ByteArray, nome: String, pergunta: String = "Descreva os acontecimentos visíveis", sessionId: String = "principal"): String {
        require(bytes.isNotEmpty() && bytes.size <= 12 * 1024 * 1024) { "O vídeo precisa ter até 12 MiB." }
        val body = okhttp3.MultipartBody.Builder().setType(okhttp3.MultipartBody.FORM)
            .addFormDataPart("arquivo", nome.take(100), bytes.toRequestBody("video/*".toMediaType()))
            .addFormDataPart("pergunta", pergunta.take(500))
            .addFormDataPart("session_id", sessionId)
            .addFormDataPart("falar_no_pc", "false")
            .build()
        val req = Request.Builder().url("${baseUrl(host, porta)}/visao/video").post(body).build()
        criarCliente(host, porta, 180).newCall(req).execute().use { resposta ->
            val texto = resposta.body?.string().orEmpty()
            if (!resposta.isSuccessful) throw RuntimeException(mensagemDeErro(texto, "Falha ao analisar vídeo (HTTP ${resposta.code})."))
            return JSONObject(texto).optString("resposta")
        }
    }

    fun estadoSeguranca(host: String, porta: Int): EstadoSeguranca {
        val o = JSONObject(get(host, porta, "/seguranca/estado")); val c = o.optJSONObject("camera") ?: JSONObject()
        val eventos = o.optJSONArray("eventos") ?: JSONArray()
        val visita = (0 until eventos.length()).asSequence().mapNotNull { eventos.optJSONObject(it) }
            .firstOrNull { it.optString("origem") == "visita" }?.optString("hora")?.takeIf { it.isNotBlank() }
        val pessoa = (0 until eventos.length()).asSequence().mapNotNull { eventos.optJSONObject(it) }
            .firstOrNull { it.optString("tipo") == "pessoa" && it.optBoolean("armado") }
        return EstadoSeguranca(o.optBoolean("armado"), o.optBoolean("ativa"), c.optBoolean("conectada"), c.optInt("pessoas"), pessoa?.optString("foto")?.takeIf { it.isNotBlank() } ?: if (o.isNull("ultima_foto")) null else o.optString("ultima_foto"), visita, o.optInt("pessoas_detectadas"), pessoa?.optString("hora"))
    }
    
    fun baixarFotoEvento(host: String, porta: Int, nome: String): ByteArray {
        require(Regex("(?:(?:pessoa|linha|movimento)_\\d{8}_\\d{6}_\\d+|gravacao_\\d{8}_\\d{6}(?:_\\d{6})?(?:_(?:compat|poster))?)[.]jpg").matches(nome))
        val req = Request.Builder().url("${baseUrl(host, porta)}/seguranca/evento/imagem/$nome").get().build()
        return criarCliente(host, porta).newCall(req).execute().use { resposta ->
            if (!resposta.isSuccessful) throw RuntimeException("Foto indisponível")
            resposta.body?.bytes() ?: ByteArray(0)
        }
    }
    fun baixarQuadroCamera(host: String, porta: Int): ByteArray {
        val req = Request.Builder().url("${baseUrl(host, porta)}/seguranca/linha/quadro.jpg").get().build()
        return criarCliente(host, porta, 12).newCall(req).execute().use { resposta ->
            if (!resposta.isSuccessful) throw RuntimeException(mensagemDeErro(resposta.body?.string().orEmpty(), "Imagem da câmera indisponível."))
            resposta.body?.bytes() ?: ByteArray(0)
        }
    }
    fun listarZonasSeguranca(host: String, porta: Int): List<JSONObject> {
        val zonas = JSONObject(get(host, porta, "/seguranca/zonas")).optJSONArray("zonas") ?: JSONArray()
        return (0 until zonas.length()).mapNotNull { zonas.optJSONObject(it) }
    }
    fun salvarZonasSeguranca(host: String, porta: Int, zonas: List<JSONObject>) {
        post(host, porta, "/seguranca/zonas", JSONObject().put("zonas", JSONArray(zonas)))
    }
    fun estadoPtz(host: String, porta: Int): EstadoPtz {
        val obj = JSONObject(get(host, porta, "/seguranca/onvif"))
        return EstadoPtz(obj.optString("ptz_estado", "desconectado"), obj.optJSONObject("capacidades") ?: JSONObject())
    }
    fun moverPtz(host: String, porta: Int, comando: String, manter: Boolean = false) {
        val dados = JSONObject().put("comando", comando).put("velocidade", 0.3).put("duracao", 0.35)
        if (manter) dados.put("manter", true)
        post(host, porta, "/seguranca/ptz", dados)
    }
    // Define alarme
    fun definirAlarme(host: String, porta: Int, armar: Boolean): String = mensagemDeSucesso(post(host, porta, if (armar) "/seguranca/armar" else "/seguranca/desarmar")) ?: "Atualizado."
    // Lista gravacoes
    fun listarGravacoes(host: String, porta: Int): List<Gravacao> {
        val a = JSONObject(get(host, porta, "/seguranca/gravacoes")).optJSONArray("gravacoes") ?: return emptyList()
        return (0 until a.length()).map { i -> a.getJSONObject(i).let { item ->
            Gravacao(item.optString("nome"), item.optLong("tamanho"), item.optString("url"), item.optString("titulo", "Gravação de segurança"), item.optString("hora"), if (item.isNull("duracao_segundos")) null else item.optDouble("duracao_segundos"), item.optString("zona").takeIf { value -> value.isNotBlank() && value != "null" }, item.optString("tipo"), item.optString("foto").takeIf { value -> value.isNotBlank() && value != "null" })
        } }
    }
    
    fun baixarGravacao(host: String, porta: Int, nome: String): ByteArray {
        require(Regex("(?:(?:gravacao|pessoa|linha)_\\d{8}_\\d{6}(?:_\\d+)?)[.]mp4").matches(nome))
        val req = Request.Builder().url("${baseUrl(host, porta)}/seguranca/gravacao/$nome").get().build()
        criarCliente(host, porta).newCall(req).execute().use { r ->
            if (!r.isSuccessful) throw RuntimeException("Não foi possível abrir esta gravação (HTTP ${r.code}).")
            val corpo = r.body ?: return ByteArray(0)
            val limite = 200L * 1024 * 1024
            if (corpo.contentLength() > limite) throw RuntimeException("Gravação maior que o limite de reprodução no celular.")
            val buffer = ByteArray(64 * 1024)
            var total = 0L
            val saida = ByteArrayOutputStream()
            corpo.byteStream().use { entrada ->
                while (true) {
                    val lidos = entrada.read(buffer)
                    if (lidos < 0) break
                    total += lidos
                    if (total > limite) throw RuntimeException("Gravação maior que o limite de reprodução no celular.")
                    saida.write(buffer, 0, lidos)
                }
            }
            return saida.toByteArray()
        }
    }

    // Registra transcricao voz
    fun registrarTranscricaoVoz(host: String, porta: Int, texto: String) {
        val frase = texto.trim().take(2000)
        if (frase.isNotEmpty()) {
            post(host, porta, "/voz/transcricao", JSONObject().put("texto", frase))
        }
    }
    // Define preferencia
    fun definirPreferencia(host: String, porta: Int, chave: String, valor: Any) {
        post(host, porta, "/preferencias", JSONObject().put("chave", chave).put("valor", valor))
    }
    // Lista preferencias seguranca
    fun listarPreferenciasSeguranca(host: String, porta: Int): Triple<Boolean, Boolean, Int> {
        val itens = JSONObject(get(host, porta, "/preferencias")).optJSONArray("itens") ?: JSONArray()
        var visita = false; var gravar = true; var dias = 7
        for (i in 0 until itens.length()) {
            val item = itens.optJSONObject(i) ?: continue
            when (item.optString("chave")) {
                "VIGIA_MODO_VISITA" -> visita = item.optBoolean("valor", false)
                "VIGIA_GRAVAR_VIDEO" -> gravar = item.optBoolean("valor", true)
                "VIGIA_RETENCAO_DIAS" -> dias = item.optDouble("valor", 7.0).toInt().coerceIn(1, 90)
            }
        }
        return Triple(visita, gravar, dias)
    }

    // Baixa video sem acumular na RAM
    fun baixarGravacaoArquivo(host: String, porta: Int, nome: String, destino: java.io.File) {
        require(Regex("(?:(?:gravacao|pessoa|linha)_\\d{8}_\\d{6}(?:_\\d+)?)[.]mp4").matches(nome))
        val req = Request.Builder().url("${baseUrl(host, porta)}/seguranca/gravacao/$nome").get().build()
        criarCliente(host, porta).newCall(req).execute().use { resposta ->
            if (!resposta.isSuccessful) throw RuntimeException("Vídeo indisponível (HTTP ${resposta.code}).")
            val corpo = resposta.body ?: throw RuntimeException("Vídeo vazio.")
            if (corpo.contentType()?.type == "application" && corpo.contentType()?.subtype == "json") throw RuntimeException("A gravação ainda não está pronta.")
            val limite = 200L * 1024 * 1024
            var total = 0L
            corpo.byteStream().use { entrada -> destino.outputStream().use { saida ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val n = entrada.read(buffer); if (n < 0) break
                    total += n; if (total > limite) throw RuntimeException("Vídeo maior que 200 MB.")
                    saida.write(buffer, 0, n)
                }
            } }
            if (total == 0L) throw RuntimeException("Vídeo vazio.")
        }
    }

    // Controla somente seguranca
    fun definirSegurancaAtiva(host: String, porta: Int, ativo: Boolean): String = mensagemDeSucesso(post(host, porta, "/pessoal/seguranca/ativo", JSONObject().put("ativo", ativo))) ?: "Protocolo atualizado."

    // Confirma acao tambem no PC
    fun avisar(host: String, porta: Int, texto: String) { post(host, porta, "/pessoal/aviso", JSONObject().put("texto", texto.take(250))) }

    // Consulta comandos pessoais
    fun comandoPessoal(host: String, porta: Int, acao: String): String = JSONObject(post(host, porta, "/pessoal/comando", JSONObject().put("acao", acao))).optString("resposta", "Consulta concluída.")


    // Consulta controles da IA
    fun estadoIA(host: String, porta: Int): org.json.JSONObject = org.json.JSONObject(get(host, porta, "/assistente/estado"))

    // Alterna IA sem comandos gerais
    fun alternarIA(host: String, porta: Int, ferramenta: String, ativo: Boolean): org.json.JSONObject = org.json.JSONObject(post(host, porta, "/assistente/ativo", org.json.JSONObject().put("ferramenta", ferramenta).put("ativo", ativo)))

    // Central de casa e integrações
    fun fontesCasa(host: String, porta: Int): JSONArray = JSONObject(get(host, porta, "/central/fontes")).optJSONArray("fontes") ?: JSONArray()
    fun aparelhosCasa(host: String, porta: Int): JSONArray = JSONObject(get(host, porta, "/central/aparelhos")).optJSONArray("aparelhos") ?: JSONArray()
    fun rotinasCasa(host: String, porta: Int): JSONArray = JSONObject(get(host, porta, "/central/rotinas")).optJSONArray("rotinas") ?: JSONArray()
    fun dispararRotinaVoz(host: String, porta: Int, frase: String): JSONObject =
        JSONObject(post(host, porta, "/central/rotinas/disparar", JSONObject().put("frase", frase).put("origem", "android")))
    fun dispararRotinaNotificacao(host: String, porta: Int, pacote: String): JSONObject =
        JSONObject(post(host, porta, "/central/rotinas/disparar", JSONObject().put("app", pacote).put("origem", "android")))
    fun acionarAparelhoCasa(host: String, porta: Int, id: String, acao: String) {
        post(host, porta, "/central/aparelhos/acao", JSONObject().put("id", id).put("acao", acao))
    }
    fun salvarRotinaCasa(host: String, porta: Int, rotina: JSONObject) {
        post(host, porta, "/central/rotinas", rotina)
    }
    fun executarRotinaCasa(host: String, porta: Int, id: String, simular: Boolean): JSONObject =
        JSONObject(post(host, porta, "/central/rotinas/$id/executar", JSONObject().put("simular", simular).put("origem", "android")))
    fun cancelarRotinasCasa(host: String, porta: Int) {
        post(host, porta, "/central/rotinas/cancelar")
    }
    fun removerRotinaCasa(host: String, porta: Int, id: String) {
        require(id.matches(Regex("[a-f0-9]{32}")))
        val req = Request.Builder().url("${baseUrl(host, porta)}/central/rotinas/$id").delete().build()
        criarCliente(host, porta).newCall(req).execute().use {
            if (!it.isSuccessful) throw RuntimeException("Não foi possível excluir a rotina.")
        }
    }

    // Para toda geracao e fala
    fun pararTudo(host: String, porta: Int) { post(host, porta, "/assistente/parar") }
}
