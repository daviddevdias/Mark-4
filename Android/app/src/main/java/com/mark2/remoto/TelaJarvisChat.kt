package com.mark2.remoto

import android.Manifest
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Base64
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Code
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.VideoLibrary
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.util.Locale

@Composable
fun TelaJarvisChat(host: String, porta: Int, modifier: Modifier = Modifier, codigo: Boolean = false, acaoInicial: String? = null) {
    val contexto = LocalContext.current
    val prefs = remember { CofreLocal.obter(contexto) }
    val scope = rememberCoroutineScope()
    val mensagens = remember { mutableStateListOf<Pair<String, String>>() }
    val sessoes = remember { mutableStateListOf<JSONObject>() }
    var sessaoAtual by remember(host, porta) { mutableStateOf("principal") }
    var menuSessoes by remember { mutableStateOf(false) }
    var texto by remember { mutableStateOf("") }
    var enviando by remember { mutableStateOf(false) }
    var erro by remember { mutableStateOf("") }
    var reconhecendo by remember { mutableStateOf(false) }
    var modoCode by remember(codigo) { mutableStateOf(codigo) }
    fun analisarFoto(bitmap: Bitmap) {
        enviando = true
        erro = ""
        mensagens.add("user" to "[Imagem para análise]")
        scope.launch {
            try {
                val resposta = withContext(Dispatchers.IO) {
                    val reduzida = if (bitmap.width > 1600) Bitmap.createScaledBitmap(bitmap, 1600, (bitmap.height * 1600f / bitmap.width).toInt(), true) else bitmap
                    try {
                        val buffer = java.io.ByteArrayOutputStream()
                        reduzida.compress(Bitmap.CompressFormat.JPEG, 82, buffer)
                        val base64 = Base64.encodeToString(buffer.toByteArray(), Base64.NO_WRAP)
                        Mark2Api.enviarFoto(host, porta, base64, "Descreva com precisão o que aparece nesta imagem.", sessaoAtual)
                    } finally { if (reduzida !== bitmap) reduzida.recycle() }
                }
                mensagens.add("assistant" to resposta)
                VozCelular.falarResposta(host, porta, resposta) { erro = it }
            } catch (falha: Exception) { erro = falha.message ?: "Não foi possível analisar a imagem." }
            finally { enviando = false }
        }
    }
    val seletorImagem = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        if (uri != null) scope.launch {
            try {
                val bitmap = withContext(Dispatchers.IO) {
                    val limites = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                    contexto.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, limites) }
                    var escala = 1
                    while (limites.outWidth / escala > 1600 || limites.outHeight / escala > 1600) escala *= 2
                    val opcoes = BitmapFactory.Options().apply { inSampleSize = escala.coerceAtLeast(1) }
                    contexto.contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, opcoes) }
                }
                if (bitmap == null) erro = "Não foi possível abrir esta imagem." else analisarFoto(bitmap)
            } catch (falha: Exception) { erro = falha.message ?: "Falha ao abrir a imagem." }
        }
    }
    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicturePreview()) { bitmap -> if (bitmap != null) analisarFoto(bitmap) }
    val seletorVideo = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
        if (uri != null) scope.launch {
            enviando = true
            erro = ""
            mensagens.add("user" to "[Vídeo enviado para análise por quadros amostrados]")
            try {
                val bytes = withContext(Dispatchers.IO) { contexto.contentResolver.openInputStream(uri)?.use { stream -> stream.readNBytes(12 * 1024 * 1024 + 1) } ?: ByteArray(0) }
                val nome = uri.lastPathSegment?.substringAfterLast('/')?.take(100) ?: "video.mp4"
                val resposta = withContext(Dispatchers.IO) { Mark2Api.analisarVideo(host, porta, bytes, nome, sessionId = sessaoAtual) }
                mensagens.add("assistant" to resposta)
                VozCelular.falarResposta(host, porta, resposta) { erro = it }
            } catch (falha: Exception) { erro = falha.message ?: "Não foi possível analisar o vídeo." }
            finally { enviando = false }
        }
    }
    val voz = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { permitido ->
        if (permitido) {
            if (ServicoEscutaJarvis.emExecucao) {
                erro = "A escuta contínua já está usando o microfone. Desative-a nas Configurações para ditar aqui."
            } else {
                reconhecendo = true
                reconhecerFalaLocal(contexto,
                    aoConcluir = { frase -> if (!frase.isNullOrBlank()) texto = frase; reconhecendo = false },
                    aoFalhar = { mensagem -> erro = mensagem; reconhecendo = false },
                )
            }
        } else erro = "Permissão do microfone negada."
    }
    LaunchedEffect(acaoInicial) {
        when (acaoInicial) {
            "imagem" -> seletorImagem.launch("image/*")
            "video" -> seletorVideo.launch("video/*")
        }
    }
    LaunchedEffect(host, porta) {
        try {
            val lista = withContext(Dispatchers.IO) { Mark2Api.listarSessoesChat(host, porta) }
            sessoes.clear(); sessoes.addAll(lista)
            if (lista.none { it.optString("id") == sessaoAtual }) sessaoAtual = "principal"
        } catch (_: Exception) { }
    }
    LaunchedEffect(host, porta, sessaoAtual) {
        try {
            val carregadas = withContext(Dispatchers.IO) { Mark2Api.buscarMensagensSessao(host, porta, sessaoAtual) }
            mensagens.clear()
            carregadas.forEach { mensagens.add(it.optString("role") to it.optString("content")) }
            erro = ""
        } catch (falha: Exception) { erro = falha.message ?: "Não foi possível carregar a conversa do computador." }
    }
    fun enviar() {
        val original = texto.trim()
        if (original.isBlank() || enviando) return
        val pedido = if (modoCode) "JARVIS CODE. Analise este pedido de programação sem executar código:\n$original" else original
        texto = ""
        enviando = true
        erro = ""
        mensagens.add("user" to original)
        scope.launch {
            try {
                val resposta = withContext(Dispatchers.IO) {
                    Mark2Api.enviarComando(host, porta, pedido, falarNoPc = false, usarLlm = true, sessionId = sessaoAtual)
                }
                mensagens.add("assistant" to resposta)
                if (prefs.getBoolean("voz_celular", true)) {
                    VozCelular.falarResposta(host, porta, resposta) { mensagemErro -> erro = mensagemErro }
                }
            } catch (falha: Exception) { erro = falha.message ?: "Falha ao falar com o Jarvis." }
            finally { enviando = false }
        }
    }
    Column(modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
            Column { Text(if (modoCode) "JARVIS CODE" else "JARVIS AI", style = MaterialTheme.typography.titleLarge, color = MaterialTheme.colorScheme.primary); Text("Conversa sincronizada com o computador", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            Column(horizontalAlignment = Alignment.End) {
                IconButton(onClick = { modoCode = !modoCode }) { Icon(Icons.Default.Code, contentDescription = "Alternar JARVIS CODE", tint = if (modoCode) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant) }
                androidx.compose.material3.TextButton(onClick = { menuSessoes = true }) { Text("Sessão: " + (sessoes.firstOrNull { it.optString("id") == sessaoAtual }?.optString("title").orEmpty().ifBlank { sessaoAtual }.take(24)) ) }
                DropdownMenu(expanded = menuSessoes, onDismissRequest = { menuSessoes = false }) {
                    sessoes.forEach { sessao -> DropdownMenuItem(text = { Text(sessao.optString("title").ifBlank { sessao.optString("id") }.take(48)) }, onClick = { sessaoAtual = sessao.optString("id", "principal"); menuSessoes = false }) }
                }
            }
        }
        LazyColumn(Modifier.weight(1f).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(10.dp), reverseLayout = false) {
            itemsIndexed(mensagens, key = { indice, _ -> indice }) { _, item ->
                val user = item.first == "user"
                Card(Modifier.fillMaxWidth(), shape = RoundedCornerShape(16.dp), colors = CardDefaults.cardColors(containerColor = if (user) MaterialTheme.colorScheme.surfaceVariant else MaterialTheme.colorScheme.surfaceContainer)) {
                    Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                        Text(if (user) "VOCÊ" else "JARVIS", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                        val isCode = item.second.contains("```") || item.second.startsWith("    ")
                        Text(item.second, fontFamily = if (isCode) FontFamily.Monospace else FontFamily.Default, color = MaterialTheme.colorScheme.onSurface)
                    }
                }
            }
            if (enviando) item { Text("JARVIS está processando…", color = MaterialTheme.colorScheme.primary) }
        }
        if (erro.isNotBlank()) Text(erro, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(2.dp)) {
            IconButton(onClick = { seletorImagem.launch("image/*") }, enabled = !enviando) { Icon(Icons.Default.Image, contentDescription = "Analisar imagem da galeria", tint = MaterialTheme.colorScheme.primary) }
            IconButton(onClick = { camera.launch(null) }, enabled = !enviando) { Icon(Icons.Default.CameraAlt, contentDescription = "Tirar foto para análise", tint = MaterialTheme.colorScheme.primary) }
            IconButton(onClick = { seletorVideo.launch("video/*") }, enabled = !enviando) { Icon(Icons.Default.VideoLibrary, contentDescription = "Analisar vídeo", tint = MaterialTheme.colorScheme.primary) }
            IconButton(onClick = { voz.launch(Manifest.permission.RECORD_AUDIO) }, enabled = !enviando && !reconhecendo) { Icon(Icons.Default.Mic, contentDescription = if (reconhecendo) "Reconhecendo offline" else "Ditar mensagem offline", tint = if (reconhecendo) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary) }
            OutlinedTextField(value = texto, onValueChange = { texto = it }, modifier = Modifier.weight(1f), placeholder = { Text(if (modoCode) "Cole seu código ou descreva a tarefa…" else "Converse com o Jarvis…") }, maxLines = 5)
            IconButton(onClick = { enviar() }, enabled = !enviando && texto.isNotBlank()) { Icon(Icons.Default.Send, contentDescription = "Enviar", tint = MaterialTheme.colorScheme.primary) }
        }
    }
}

