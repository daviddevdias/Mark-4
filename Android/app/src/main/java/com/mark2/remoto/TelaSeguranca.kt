package com.mark2.remoto

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.app.ActivityManager
import android.content.Context
import android.net.Uri
import android.widget.VideoView
import android.widget.MediaController
import androidx.compose.foundation.Image
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowForward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File

@Composable
fun TelaSeguranca(host: String, porta: Int, modifier: Modifier = Modifier, telaAtiva: Boolean = true) {
    val contexto = LocalContext.current
    val baixaMemoria = remember(contexto) {
        (contexto.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager)?.isLowRamDevice == true
    }
    val escalaQuadro = if (baixaMemoria) 4 else 2
    val scope = rememberCoroutineScope()
    var estado by remember(host, porta) { mutableStateOf<Mark2Api.EstadoSeguranca?>(null) }
    var quadro by remember(host, porta) { mutableStateOf<Bitmap?>(null) }
    var ptz by remember(host, porta) { mutableStateOf<Mark2Api.EstadoPtz?>(null) }
    val zonas = remember(host, porta) { mutableStateListOf<JSONObject>() }
    val gravacoes = remember(host, porta) { mutableStateListOf<Mark2Api.Gravacao>() }
    var carregando by remember(host, porta) { mutableStateOf(true) }
    var operando by remember { mutableStateOf(false) }
    var erro by remember { mutableStateOf("") }
    var erroCamera by remember { mutableStateOf("") }
    var estadoZonas by remember(host, porta) { mutableStateOf("carregando") }
    var erroZonas by remember(host, porta) { mutableStateOf("") }
    var video by remember { mutableStateOf<File?>(null) }

    suspend fun atualizarEstado() {
        try {
            estado = withContext(Dispatchers.IO) { Mark2Api.estadoSeguranca(host, porta) }
            erro = ""
        } catch (falha: Exception) {
            estado = null
            erro = falha.message ?: "Não foi possível consultar a Torre Stark."
        }
    }

    suspend fun carregarPainel() {
        carregando = true
        atualizarEstado()
        val resultado = withContext(Dispatchers.IO) {
            Triple(
                runCatching { Mark2Api.listarGravacoes(host, porta) },
                runCatching { Mark2Api.listarZonasSeguranca(host, porta) },
                runCatching { Mark2Api.estadoPtz(host, porta) },
            )
        }
        resultado.first.onSuccess { gravacoes.clear(); gravacoes.addAll(it) }
            .onFailure { erro = it.message ?: "Não foi possível carregar as gravações." }
        resultado.second.onSuccess {
            zonas.clear(); zonas.addAll(it)
            estadoZonas = if (it.isEmpty()) "vazio" else "ok"
            erroZonas = ""
        }.onFailure {
            estadoZonas = if (estado == null) "offline" else "erro"
            erroZonas = it.message ?: "Falha ao consultar as zonas no computador."
        }
        resultado.third.onSuccess { ptz = it }
            .onFailure { erro = it.message ?: "Não foi possível consultar o controle da câmera." }
        carregando = false
    }

    LaunchedEffect(host, porta, telaAtiva) {
        if (!telaAtiva) return@LaunchedEffect
        carregarPainel()
        while (true) {
            delay(8000)
            atualizarEstado()
            val resultadoZonas = withContext(Dispatchers.IO) { runCatching { Mark2Api.listarZonasSeguranca(host, porta) } }
            resultadoZonas.onSuccess {
                zonas.clear(); zonas.addAll(it)
                estadoZonas = if (it.isEmpty()) "vazio" else "ok"
                erroZonas = ""
            }.onFailure {
                estadoZonas = "erro"
                erroZonas = it.message ?: "Falha ao consultar as zonas no computador."
            }
        }
    }
    LaunchedEffect(host, porta, telaAtiva) {
        if (!telaAtiva) return@LaunchedEffect
        while (true) {
            try {
                val bytes = withContext(Dispatchers.IO) { Mark2Api.baixarQuadroCamera(host, porta) }
                val opcoes = BitmapFactory.Options().apply { inSampleSize = escalaQuadro }
                quadro = BitmapFactory.decodeByteArray(bytes, 0, bytes.size, opcoes)
                erroCamera = ""
            } catch (falha: Exception) {
                erroCamera = falha.message ?: "Imagem da câmera indisponível."
            }
            delay(if (baixaMemoria) 7000 else 5000)
        }
    }
    DisposableEffect(video) {
        val arquivoAtual = video
        onDispose { arquivoAtual?.delete() }
    }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                Column {
                    Text("TORRE STARK", style = TituloTopoEstilo, color = MaterialTheme.colorScheme.primary)
                    Text("Segurança da casa", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                IconButton(onClick = { scope.launch { carregarPainel() } }, enabled = !carregando) {
                    Icon(Icons.Default.Refresh, contentDescription = "Atualizar")
                }
            }
        }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
                Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Text(if (estado?.ativa == true) "Protocolo ligado" else "Protocolo desligado", style = MaterialTheme.typography.titleMedium)
                            Text(if (estado?.armado == true) "Alarme armado" else "Alarme desarmado", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Switch(
                            checked = estado?.ativa == true,
                            enabled = estado != null && !operando,
                            onCheckedChange = { ativo ->
                                scope.launch {
                                    operando = true
                                    try {
                                        val resposta = withContext(Dispatchers.IO) { Mark2Api.definirSegurancaAtiva(host, porta, ativo) }
                                        VozCelular.falarResposta(host, porta, resposta)
                                        atualizarEstado()
                                    } catch (falha: Exception) {
                                        erro = falha.message ?: "Não foi possível atualizar a Torre Stark."
                                    } finally {
                                        operando = false
                                    }
                                }
                            },
                        )
                    }
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        InfoChip("Câmera", if (estado?.cameraConectada == true) "Conectada" else "Desconectada", estado?.cameraConectada == true, Modifier.weight(1f))
                        InfoChip("Agora", "${estado?.pessoas ?: 0} pessoa(s)", estado?.pessoas?.let { it > 0 } == true, Modifier.weight(1f))
                    }
                    Button(
                        onClick = {
                            scope.launch {
                                operando = true
                                try {
                                    val resposta = withContext(Dispatchers.IO) { Mark2Api.definirAlarme(host, porta, estado?.armado != true) }
                                    VozCelular.falarResposta(host, porta, resposta)
                                    atualizarEstado()
                                } catch (falha: Exception) {
                                    erro = falha.message ?: "Não foi possível alterar o alarme."
                                } finally {
                                    operando = false
                                }
                            }
                        },
                        enabled = estado != null && !operando,
                        modifier = Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = if (estado?.armado == true) MaterialTheme.colorScheme.errorContainer else MaterialTheme.colorScheme.primary,
                            contentColor = if (estado?.armado == true) MaterialTheme.colorScheme.onErrorContainer else MaterialTheme.colorScheme.onPrimary,
                        ),
                    ) {
                        Text(
                            when {
                                estado?.ativa != true -> "Ativar e armar Protocolo Stark"
                                estado?.armado == true -> "Desativar defesas"
                                else -> "Ativar defesas"
                            },
                        )
                    }
                    if (operando || carregando) LinearProgressIndicator(Modifier.fillMaxWidth())
                }
            }
        }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
                Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("CÂMERA", style = TituloTopoEstilo, color = MaterialTheme.colorScheme.primary)
                    if (quadro != null) {
                        Image(
                            bitmap = quadro!!.asImageBitmap(),
                            contentDescription = "Imagem recente da câmera",
                            modifier = Modifier.fillMaxWidth().height(190.dp),
                            contentScale = ContentScale.Crop,
                        )
                        Text("Imagem atualizada automaticamente", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    } else if (erroCamera.isNotBlank()) {
                        Text(erroCamera, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    } else {
                        Spacer(Modifier.height(90.dp))
                        CircularProgressIndicator(Modifier.align(Alignment.CenterHorizontally))
                    }
                    Text("Controle PTZ · ${ptz?.estado ?: "consultando"}", style = MaterialTheme.typography.titleSmall)
                    PtzControls(ptz?.capacidades) { comando, manter ->
                        scope.launch(Dispatchers.IO) {
                            try {
                                Mark2Api.moverPtz(host, porta, comando, manter)
                            } catch (falha: Exception) {
                                withContext(Dispatchers.Main) {
                                    erro = falha.message ?: "Não foi possível mover a câmera."
                                }
                            }
                        }
                    }
                }
            }
        }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
                Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("ZONAS DE MONITORAMENTO", style = TituloTopoEstilo, color = MaterialTheme.colorScheme.primary)
                    when (estadoZonas) {
                        "carregando" -> Text("Consultando zonas no computador…", color = MaterialTheme.colorScheme.onSurfaceVariant)
                        "offline" -> Text("Computador desconectado. As zonas serão atualizadas após reconectar.\n$erroZonas", color = MaterialTheme.colorScheme.error)
                        "erro" -> Text("O computador respondeu, mas houve um erro ao consultar as zonas.\n$erroZonas", color = MaterialTheme.colorScheme.error)
                        "vazio" -> Text("O computador confirmou que nenhuma zona está configurada.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    zonas.forEach { zona ->
                        val id = zona.optString("id")
                        val ativa = zona.optBoolean("active", true)
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                            Column(Modifier.weight(1f)) {
                                Text(zona.optString("name", "Zona"))
                                Text(if (ativa) "Monitoramento ativo" else "Monitoramento pausado", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            Switch(
                                checked = ativa,
                                enabled = !operando,
                                onCheckedChange = { novoEstado ->
                                    scope.launch {
                                        operando = true
                                        try {
                                            val atualizadas = zonas.map { original ->
                                                if (original.optString("id") == id) JSONObject(original.toString()).put("active", novoEstado) else JSONObject(original.toString())
                                            }
                                            withContext(Dispatchers.IO) { Mark2Api.salvarZonasSeguranca(host, porta, atualizadas) }
                                            zonas.clear()
                                            zonas.addAll(atualizadas)
                                        } catch (falha: Exception) {
                                            erro = falha.message ?: "Não foi possível atualizar a zona."
                                        } finally {
                                            operando = false
                                        }
                                    }
                                },
                            )
                        }
                    }
                }
            }
        }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
                Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("GRAVAÇÕES", style = TituloTopoEstilo, color = MaterialTheme.colorScheme.primary)
                    if (gravacoes.isEmpty()) Text("Nenhuma gravação disponível.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    gravacoes.take(8).forEach { gravacao ->
                        GravacaoCard(gravacao, host, porta, !operando) {
                            scope.launch {
                                operando = true
                                try {
                                    val arquivo = File.createTempFile("evento_", ".mp4", contexto.cacheDir)
                                    try {
                                        withContext(Dispatchers.IO) { Mark2Api.baixarGravacaoArquivo(host, porta, gravacao.nome, arquivo) }
                                    } catch (falha: Exception) { arquivo.delete(); throw falha }
                                    video = arquivo
                                } catch (falha: Exception) {
                                    erro = falha.message ?: "Não foi possível abrir a gravação."
                                } finally { operando = false }
                            }
                        }
                    }
                }
            }
        }
        if (erro.isNotBlank()) item {
            Text(erro, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
        }
    }

    video?.let { arquivo ->
        AlertDialog(
            onDismissRequest = { video = null },
            title = { Text("Reprodução do evento") },
            text = {
                AndroidView(
                    factory = { viewContext ->
                        VideoView(viewContext).apply {
                            setMediaController(MediaController(viewContext).also { it.setAnchorView(this) })
                            setOnErrorListener { _, _, _ -> erro = "Formato de vídeo não suportado neste aparelho. Tente outra gravação."; video = null; true }
                            setVideoURI(Uri.fromFile(arquivo))
                            setOnPreparedListener { it.start() }
                        }
                    },
                    onRelease = { it.stopPlayback() },
                    modifier = Modifier.fillMaxWidth().height(220.dp),
                )
            },
            confirmButton = { TextButton(onClick = { video = null }) { Text("Fechar") } },
        )
    }
}

@Composable
private fun GravacaoCard(item: Mark2Api.Gravacao, host: String, porta: Int, enabled: Boolean, onPlay: () -> Unit) {
    var miniatura by remember(item.nome, host, porta) { mutableStateOf<Bitmap?>(null) }
    LaunchedEffect(item.foto, host, porta) {
        val foto = item.foto ?: return@LaunchedEffect
        miniatura = withContext(Dispatchers.IO) {
            runCatching {
                val bytes = Mark2Api.baixarFotoEvento(host, porta, foto)
                BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
            }.getOrNull()
        }
    }
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Row(Modifier.fillMaxWidth().padding(10.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            if (miniatura != null) Image(miniatura!!.asImageBitmap(), "Foto real do evento", Modifier.size(76.dp), contentScale = ContentScale.Crop)
            else Spacer(Modifier.size(76.dp))
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text(item.titulo, style = MaterialTheme.typography.titleSmall)
                val dataHora = runCatching { java.time.Instant.parse(item.hora).atZone(java.time.ZoneId.systemDefault()).format(java.time.format.DateTimeFormatter.ofPattern("dd/MM/yyyy · HH:mm:ss")) }.getOrDefault(item.hora)
                if (dataHora.isNotBlank()) Text(dataHora, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                item.duracaoSegundos?.let { segundos -> Text("Duração: %02d:%02d".format(segundos.toInt() / 60, segundos.toInt() % 60), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                item.zona?.let { Text("Zona: $it", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            }
            TextButton(enabled = enabled, onClick = onPlay) { Text("▶") }
        }
    }
}

@Composable
private fun InfoChip(label: String, value: String, positive: Boolean, modifier: Modifier = Modifier) {
    Card(modifier, shape = RoundedCornerShape(14.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Column(Modifier.fillMaxWidth().padding(10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(value, style = MaterialTheme.typography.labelMedium, color = if (positive) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface)
        }
    }
}

@Composable
private fun PtzControls(capacidades: JSONObject?, executar: (String, Boolean) -> Unit) {
    val habilitado = capacidades != null
    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
        PtzButton(Icons.Default.ArrowUpward, "Mover para cima", "up", habilitado && capacidades!!.optBoolean("up"), executar)
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
            PtzButton(Icons.Default.ArrowBack, "Mover para esquerda", "left", habilitado && capacidades!!.optBoolean("left"), executar)
            PtzButton(Icons.Default.Stop, "Parar câmera", "stop", habilitado && capacidades!!.optBoolean("stop"), executar)
            PtzButton(Icons.Default.ArrowForward, "Mover para direita", "right", habilitado && capacidades!!.optBoolean("right"), executar)
        }
        PtzButton(Icons.Default.ArrowDownward, "Mover para baixo", "down", habilitado && capacidades!!.optBoolean("down"), executar)
    }
}

@Composable
private fun PtzButton(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    description: String,
    command: String,
    enabled: Boolean,
    executar: (String, Boolean) -> Unit,
) {
    val gesto = Modifier.pointerInput(command, enabled) {
        detectTapGestures(onPress = {
            if (!enabled) return@detectTapGestures
            executar(command, command != "stop")
            tryAwaitRelease()
            if (command != "stop") executar("stop", false)
        })
    }
    OutlinedButton(onClick = {}, enabled = enabled, modifier = Modifier.size(48.dp).then(gesto), contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)) {
        Icon(icon, contentDescription = description)
    }
}


