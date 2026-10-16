package com.mark2.remoto

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.clickable
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.Code
import androidx.compose.material.icons.filled.Chat
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Notes
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.Settings as SettingsIcon
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.rememberDrawerState
import androidx.compose.material3.DrawerValue
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

private class PassoRotinaRascunho(tipoInicial: String = "falar") {
    var tipo by mutableStateOf(tipoInicial)
    var texto by mutableStateOf("")
    var segundos by mutableStateOf("5")
    var aparelhoId by mutableStateOf("")
    var acao by mutableStateOf("turn_on")
}

class MainActivity : ComponentActivity() {
    override fun onDestroy() {
        if (!isChangingConfigurations) VozCelular.fechar()
        super.onDestroy()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Mark2Api.inicializar(applicationContext)
        VozCelular.inicializar(applicationContext)
        val prefs = CofreLocal.obter(this)
        if (prefs.getBoolean("escuta_continua_ativa", false) &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            ContextCompat.startForegroundService(this, Intent(this, ServicoEscutaJarvis::class.java))
        }
        setContent { TemaMark2 { TelaPessoal() } }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TelaPessoal() {
    val contexto = LocalContext.current
    val prefs = remember { CofreLocal.obter(contexto) }
    val scope = rememberCoroutineScope()
    val lifecycle = (contexto as ComponentActivity).lifecycle
    var telaAtiva by remember { mutableStateOf(lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) }
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, _ -> telaAtiva = lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED) }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer) }
    }

    var avisos by remember { mutableStateOf(prefs.getBoolean("avisos_mensagens", true)) }
    var compartilhar by remember { mutableStateOf(prefs.getBoolean("compartilhar_whatsapp", false)) }
    var host by remember { mutableStateOf(prefs.getString("host", "") ?: "") }
    var porta by remember { mutableIntStateOf(prefs.getInt("porta", 5679)) }
    var enderecoEditado by remember { mutableStateOf(host) }
    var chaveEditada by remember { mutableStateOf("") }
    var certificadoEditado by remember { mutableStateOf("") }
    var portaEditada by remember { mutableStateOf(porta.toString()) }
    var aba by remember { mutableStateOf("Início") }
    var vozCelularAtiva by remember { mutableStateOf(prefs.getBoolean("voz_celular", true)) }
    var escutaContinua by remember { mutableStateOf(prefs.getBoolean("escuta_continua_ativa", false)) }
    var configuracao by remember { mutableStateOf(false) }
    var erroConfiguracao by remember { mutableStateOf("") }
    var criar by remember { mutableStateOf(false) }
    var erroFormulario by remember { mutableStateOf("") }
    var titulo by remember { mutableStateOf("") }
    var texto by remember { mutableStateOf("") }
    var data by remember { mutableStateOf("") }
    var hora by remember { mutableStateOf("") }
    var itens by remember { mutableStateOf(emptyList<JSONObject>()) }
    var mensagem by remember { mutableStateOf("") }
    var ocupado by remember { mutableStateOf(false) }
    var revisao by remember { mutableIntStateOf(0) }
    val drawerState = rememberDrawerState(DrawerValue.Closed)

    val pedirAvisos = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        contexto.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
    }
    fun iniciarEscutaContinuaAutorizada() {
        prefs.edit().putBoolean("escuta_continua_ativa", true).apply()
        escutaContinua = true
        ContextCompat.startForegroundService(contexto, Intent(contexto, ServicoEscutaJarvis::class.java))
    }
    val pedirNotificacoesEscuta = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        iniciarEscutaContinuaAutorizada()
    }
    val pedirMicrofone = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { permitido ->
        if (permitido) {
            if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(contexto, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                pedirNotificacoesEscuta.launch(Manifest.permission.POST_NOTIFICATIONS)
            } else iniciarEscutaContinuaAutorizada()
        } else {
            escutaContinua = false
            erroConfiguracao = "Permita o microfone para ativar a escuta local do Jarvis."
        }
    }
    fun alternarEscutaContinua(ativar: Boolean) {
        if (ativar) {
            if (ContextCompat.checkSelfPermission(contexto, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(contexto, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                    pedirNotificacoesEscuta.launch(Manifest.permission.POST_NOTIFICATIONS)
                } else iniciarEscutaContinuaAutorizada()
            } else pedirMicrofone.launch(Manifest.permission.RECORD_AUDIO)
        } else {
            prefs.edit().putBoolean("escuta_continua_ativa", false).apply()
            escutaContinua = false
            contexto.stopService(Intent(contexto, ServicoEscutaJarvis::class.java))
        }
    }
    fun ativarAvisos() {
        prefs.edit().putBoolean("avisos_mensagens", true).apply()
        avisos = true
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(contexto, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            pedirAvisos.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            contexto.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
        }
    }

    val caminho = when (aba) {
        "Agenda" -> "/agenda"
        "Notas" -> "/memoria/notas"
        "WhatsApp" -> "/pessoal/mensagens/celular"
        else -> ""
    }
    LaunchedEffect(aba, host, porta, revisao, telaAtiva) {
        if (!telaAtiva || caminho.isBlank()) return@LaunchedEffect
        ocupado = true
        itens = emptyList()
        mensagem = ""
        try {
            val resposta = Mark2Api.pessoalAsync(host, porta, caminho)
            val array = JSONArray(resposta)
            itens = (0 until array.length()).map { array.getJSONObject(it) }
            if (itens.isEmpty()) mensagem = "Nenhum item disponível."
        } catch (cancelado: CancellationException) {
            throw cancelado
        } catch (erro: Exception) {
            mensagem = erro.message ?: "Não foi possível conectar ao Jarvis."
        } finally {
            ocupado = false
        }
    }

    LaunchedEffect(host, porta, telaAtiva, aba) {
        if (!telaAtiva || aba !in setOf("JARVIS AI", "JARVIS CODE")) return@LaunchedEffect
        var parada: Int? = null
        while (true) {
            try {
                val atual = withContext(Dispatchers.IO) { Mark2Api.estadoIA(host, porta).optInt("parada") }
                if (parada != null && parada != atual) VozCelular.interromper()
                parada = atual
            } catch (cancelado: CancellationException) { throw cancelado }
            catch (_: Exception) { }
            delay(5000)
        }
    }

    val paginas = listOf(
        Triple("Início", Icons.Default.Home, "Visão geral"),
        Triple("JARVIS AI", Icons.Default.Chat, "Conversa por texto e voz"),
        Triple("JARVIS CODE", Icons.Default.Code, "Programação no chat compartilhado"),
        Triple("Torre Stark", Icons.Default.Security, "Câmera, alarme e zonas"),
        Triple("Casa IA", Icons.Default.Home, "Aparelhos e rotinas"),
        Triple("Agenda", Icons.Default.CalendarMonth, "Compromissos"),
        Triple("Notas", Icons.Default.Notes, "Notas pessoais"),
        Triple("WhatsApp", Icons.Default.Chat, "Avisos do celular"),
        Triple("Comandos", Icons.Default.Chat, "Comandos pessoais e do celular"),
    )
    ModalNavigationDrawer(
        drawerState = drawerState,
        gesturesEnabled = drawerState.isOpen,
        drawerContent = {
            ModalDrawerSheet(Modifier.verticalScroll(rememberScrollState())) {
                Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 24.dp)) {
                    Text("JARVIS", style = MaterialTheme.typography.titleLarge)
                    Text("Mark 2 · painel móvel", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                paginas.forEach { (nome, icone, descricao) ->
                    NavigationDrawerItem(
                        label = { Column { Text(nome); Text(descricao, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant) } },
                        selected = aba == nome,
                        onClick = {
                            aba = nome
                            criar = false
                            scope.launch { drawerState.close() }
                        },
                        icon = { Icon(icone, contentDescription = null) },
                        modifier = Modifier.padding(horizontal = 12.dp),
                    )
                }
                Spacer(Modifier.height(12.dp))
                NavigationDrawerItem(
                    label = { Text("Configurações") },
                    selected = false,
                    onClick = {
                        enderecoEditado = host
                        portaEditada = porta.toString()
                        chaveEditada = prefs.getString("token_remoto", "").orEmpty()
                        certificadoEditado = ""
                        erroConfiguracao = ""
                        configuracao = true
                        scope.launch { drawerState.close() }
                    },
                    icon = { Icon(Icons.Default.SettingsIcon, contentDescription = null) },
                    modifier = Modifier.padding(horizontal = 12.dp),
                )
                ControlesIA(host, porta, drawerState.isOpen)
            }
        },
    ) {
        Scaffold(
            topBar = {
                TopAppBar(
                    navigationIcon = {
                        IconButton(onClick = { scope.launch { drawerState.open() } }) {
                            Icon(Icons.Default.Menu, contentDescription = "Abrir menu")
                        }
                    },
                    title = { Text(aba) },
                    actions = {
                        IconButton(onClick = {
                            enderecoEditado = host
                            portaEditada = porta.toString()
                            chaveEditada = prefs.getString("token_remoto", "").orEmpty()
                            certificadoEditado = ""
                            erroConfiguracao = ""
                            configuracao = true
                        }) {
                            Icon(Icons.Default.SettingsIcon, contentDescription = "Configurações")
                        }
                    },
                )
            },
        ) { padding ->
            when (aba) {
                "Início" -> TelaInicio(
                    host = host,
                    porta = porta,
                    telaAtiva = telaAtiva,
                    onNavigate = { destino -> aba = destino },
                    modifier = Modifier.fillMaxSize().padding(padding),
                )
                "Comandos" -> TelaComandos(host, porta, { destino -> aba = destino }, Modifier.fillMaxSize().padding(padding))
                "JARVIS AI", "JARVIS CODE", "Analisar imagem", "Analisar gravação" -> TelaJarvisChat(
                    host, porta, Modifier.fillMaxSize().padding(padding),
                    codigo = aba == "JARVIS CODE",
                    acaoInicial = when (aba) { "Analisar imagem" -> "imagem"; "Analisar gravação" -> "video"; else -> null },
                )
                "Torre Stark" -> TelaSeguranca(host, porta, Modifier.fillMaxSize().padding(padding), telaAtiva)
                "Casa IA" -> TelaCasaIA(host, porta, telaAtiva, Modifier.fillMaxSize().padding(padding))
                else -> TelaPessoalLista(
                    aba = aba,
                    itens = itens,
                    mensagem = mensagem,
                    ocupado = ocupado,
                    compartilhar = compartilhar,
                    onCompartilhar = {
                        compartilhar = it
                        prefs.edit().putBoolean("compartilhar_whatsapp", it).apply()
                        if (it) contexto.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
                    },
                    onPermissoes = { contexto.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)) },
                    onAtualizar = { revisao++ },
                    onNovo = {
                        erroFormulario = ""
                        criar = true
                    },
                    onExcluir = { item ->
                        scope.launch {
                            ocupado = true
                            try {
                                withContext(Dispatchers.IO) {
                                    Mark2Api.removerPessoal(host, porta, "$caminho/${item.optString("id")}")
                                }
                                revisao++
                            } catch (erro: Exception) {
                                mensagem = erro.message ?: "Não foi possível excluir."
                            } finally {
                                ocupado = false
                            }
                        }
                    },
                    modifier = Modifier.fillMaxSize().padding(padding),
                )
            }
        }
    }

    if (configuracao) AlertDialog(
        onDismissRequest = { configuracao = false },
        title = { Text("Conexão e avisos") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Text("Avisos no celular")
                    Switch(checked = avisos, onCheckedChange = {
                        avisos = it
                        prefs.edit().putBoolean("avisos_mensagens", it).apply()
                        if (it) ativarAvisos()
                    })
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("Respostas por voz do Jarvis no celular")
                    Switch(checked = vozCelularAtiva, onCheckedChange = { vozCelularAtiva = it; prefs.edit().putBoolean("voz_celular", it).apply() })
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Escuta contínua offline")
                        Text(if (escutaContinua) "Microfone ativo em segundo plano · Vosk local" else "Desativada · usa o modelo local ao ativar", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Switch(checked = escutaContinua, onCheckedChange = { alternarEscutaContinua(it) })
                }
                if (avisos) TextButton(onClick = { ativarAvisos() }) { Text("Acesso às notificações") }
                OutlinedTextField(value = enderecoEditado, onValueChange = { enderecoEditado = it }, label = { Text("Endereço do PC") }, singleLine = true)
                OutlinedTextField(value = portaEditada, onValueChange = { portaEditada = it.filter(Char::isDigit) }, label = { Text("Porta HTTPS") }, singleLine = true)
                OutlinedTextField(value = chaveEditada, onValueChange = { chaveEditada = it.trim() }, label = { Text("Chave de acesso do PC") }, singleLine = true, visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation())
                OutlinedTextField(value = certificadoEditado, onValueChange = { certificadoEditado = it.replace(":", "").trim().uppercase() }, label = { Text("Certificado SHA256 do PC") }, singleLine = true)
                Text("Copie os dois dados em Configurações → Conexão segura do celular no PC.", style = MaterialTheme.typography.bodySmall)
                if (erroConfiguracao.isNotBlank()) Text(erroConfiguracao, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
            }
        },
        confirmButton = {
            TextButton(onClick = {
                val numero = portaEditada.toIntOrNull()
                if (!enderecoEditado.matches(Regex("[A-Za-z0-9.:-]{1,253}")) || numero == null || numero !in 1..65535 || !chaveEditada.matches(Regex("[A-Za-z0-9._~-]{8,512}")) || (certificadoEditado.isNotBlank() && !certificadoEditado.matches(Regex("[A-F0-9]{64}")))) {
                    erroConfiguracao = "Confira endereço, porta, chave e certificado."
                } else {
                    host = enderecoEditado.trim()
                    porta = numero
                    prefs.edit().putString("host", host).putInt("porta", numero).putString("token_remoto", chaveEditada).apply()
                    if (certificadoEditado.isNotBlank()) CofreLocal.obter(contexto, "mark2_pins").edit().putString("${host.lowercase()}:$numero", certificadoEditado).apply()
                    erroConfiguracao = ""
                    configuracao = false
                    revisao++
                }
            }) { Text("Salvar") }
        },
        dismissButton = { TextButton(onClick = { configuracao = false }) { Text("Fechar") } },
    )
    if (criar) AlertDialog(
        onDismissRequest = { criar = false },
        title = { Text(if (aba == "Agenda") "Novo compromisso" else "Nova nota") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(value = titulo, onValueChange = { titulo = it.take(120) }, label = { Text("Título") }, singleLine = true)
                if (aba == "Agenda") {
                    OutlinedTextField(value = data, onValueChange = { data = it }, label = { Text("Data: AAAA-MM-DD") }, singleLine = true)
                    OutlinedTextField(value = hora, onValueChange = { hora = it }, label = { Text("Hora: HH:MM") }, singleLine = true)
                }
                OutlinedTextField(value = texto, onValueChange = { texto = it.take(1200) }, label = { Text("Texto") })
                if (erroFormulario.isNotBlank()) Text(erroFormulario, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
            }
        },
        confirmButton = {
            TextButton(enabled = !ocupado && titulo.isNotBlank(), onClick = {
                scope.launch {
                    ocupado = true
                    try {
                        val obj = if (aba == "Agenda") {
                            JSONObject().put("titulo", titulo).put("inicio", "${data}T${hora}").put("descricao", texto)
                        } else {
                            JSONObject().put("id", java.util.UUID.randomUUID().toString()).put("area", "meta").put("title", titulo.take(42)).put("body", texto)
                        }
                        withContext(Dispatchers.IO) { Mark2Api.salvarPessoal(host, porta, caminho, obj) }
                        VozCelular.falarResposta(host, porta, "Salvo com sucesso.")
                        withContext(Dispatchers.IO) { runCatching { Mark2Api.avisar(host, porta, "Informação pessoal salva pelo celular.") } }
                        criar = false
                        erroFormulario = ""
                        titulo = ""
                        texto = ""
                        revisao++
                    } catch (erro: Exception) {
                        erroFormulario = erro.message ?: "Não foi possível salvar."
                    } finally {
                        ocupado = false
                    }
                }
            }) { Text("Salvar") }
        },
        dismissButton = { TextButton(onClick = { criar = false }) { Text("Cancelar") } },
    )
}

@Composable
private fun TelaInicio(host: String, porta: Int, telaAtiva: Boolean, onNavigate: (String) -> Unit, modifier: Modifier = Modifier) {
    var estado by remember(host, porta) { mutableStateOf<Mark2Api.EstadoSeguranca?>(null) }
    var estadoIa by remember(host, porta) { mutableStateOf<JSONObject?>(null) }
    var falha by remember(host, porta) { mutableStateOf("") }
    var horaAgora by remember { mutableStateOf(java.time.LocalDateTime.now()) }
    LaunchedEffect(telaAtiva) {
        if (!telaAtiva) return@LaunchedEffect
        while (true) { horaAgora = java.time.LocalDateTime.now(); delay(60_000) }
    }
    LaunchedEffect(host, porta, telaAtiva) {
        if (!telaAtiva) return@LaunchedEffect
        while (true) {
            try {
                val resposta = withContext(Dispatchers.IO) {
                    kotlinx.coroutines.coroutineScope {
                        val seguranca = async { Mark2Api.estadoSeguranca(host, porta) }
                        val ia = async { Mark2Api.estadoIA(host, porta) }
                        Pair(seguranca.await(), ia.await())
                    }
                }
                estado = resposta.first
                estadoIa = resposta.second
                falha = ""
            } catch (cancelado: CancellationException) { throw cancelado }
            catch (erro: Exception) { falha = erro.message ?: "Jarvis indisponível."; estadoIa = null }
            delay(30_000)
        }
    }
    val horario = horaAgora.format(java.time.format.DateTimeFormatter.ofPattern("HH:mm"))
    val data = horaAgora.format(java.time.format.DateTimeFormatter.ofPattern("EEEE, d 'de' MMMM", java.util.Locale("pt", "BR")))
    LazyColumn(modifier = modifier, contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        item {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
                Row(Modifier.fillMaxWidth().padding(18.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                    Column(verticalArrangement = Arrangement.spacedBy(5.dp)) {
                        Text("Olá", style = MaterialTheme.typography.headlineSmall)
                        Text("$data · $horario", color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(if (falha.isBlank()) "● COMPUTADOR CONECTADO" else "● COMPUTADOR DESCONECTADO", style = MaterialTheme.typography.labelSmall, color = if (falha.isBlank()) CoresMark2.roxoLuminoso else MaterialTheme.colorScheme.error)
                    }
                    Text("J", style = MaterialTheme.typography.displayMedium, color = CoresMark2.roxoLuminoso)
                }
            }
        }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = CoresMark2.superficieElevada)) {
                Column(Modifier.fillMaxWidth().padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("JARVIS", style = TituloTopoEstilo, color = CoresMark2.roxoLuminoso)
                    Text("Sua central de inteligência", style = MaterialTheme.typography.titleLarge)
                    Text("Hermes · ${if (estadoIa?.optBoolean("hermes") == true) "Ativo" else if (estadoIa == null) "Desconhecido" else "Inativo"}     LM Studio · ${if (estadoIa?.optBoolean("lm_studio") == true) "Ativo" else if (estadoIa == null) "Desconhecido" else "Inativo"}", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Button(onClick = { onNavigate("JARVIS AI") }, modifier = Modifier.fillMaxWidth()) { Text("🎙  Conversar com o JARVIS") }
                }
            }
        }
        item {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
                Column(Modifier.fillMaxWidth().padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("TORRE STARK", style = TituloTopoEstilo, color = MaterialTheme.colorScheme.primary)
                    Text(when { estado == null -> "Conectando ao sistema de segurança…"; estado?.armado == true -> "Alarme armado"; estado?.ativa == true -> "Protocolo ativo · alarme desarmado"; else -> "Protocolo desligado" }, style = MaterialTheme.typography.titleMedium)
                    Text("Câmera ${if (estado?.cameraConectada == true) "conectada" else "desconectada"} · ${estado?.pessoas ?: 0} pessoa(s) agora", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    Button(onClick = { onNavigate("Torre Stark") }, modifier = Modifier.fillMaxWidth()) { Text("Abrir Torre Stark") }
                }
            }
        }
        item { Text("AÇÕES RÁPIDAS", style = TituloTopoEstilo, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        items(listOf("Analisar imagem" to "JARVIS AI", "Analisar gravação" to "JARVIS AI", "JARVIS CODE" to "JARVIS CODE", "Agenda" to "Agenda", "Notas" to "Notas", "Comandos" to "Comandos")) { (titulo, pagina) ->
            Card(modifier = Modifier.clickable { onNavigate(pagina) }, colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
                Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(titulo, style = MaterialTheme.typography.titleMedium)
                    Text("›", style = MaterialTheme.typography.titleLarge, color = MaterialTheme.colorScheme.primary)
                }
            }
        }
        if (falha.isNotBlank()) item { Text("Não foi possível consultar o computador agora.", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
    }
}

@Composable
private fun TelaPessoalLista(
    aba: String,
    itens: List<JSONObject>,
    mensagem: String,
    ocupado: Boolean,
    compartilhar: Boolean,
    onCompartilhar: (Boolean) -> Unit,
    onPermissoes: () -> Unit,
    onAtualizar: () -> Unit,
    onNovo: () -> Unit,
    onExcluir: (JSONObject) -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier.padding(horizontal = 16.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            TextButton(enabled = !ocupado, onClick = onAtualizar) { Text("Atualizar") }
            if (aba == "Agenda" || aba == "Notas") TextButton(onClick = onNovo) { Text("+ Novo") }
        }
        if (aba == "WhatsApp") {
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
                Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Compartilhe avisos com seu computador.", style = MaterialTheme.typography.bodyMedium)
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                        Text("Avisar no PC")
                        Switch(checked = compartilhar, onCheckedChange = onCompartilhar)
                    }
                    TextButton(onClick = onPermissoes) { Text("Acesso às notificações") }
                }
            }
            Spacer(Modifier.height(8.dp))
        }
        if (ocupado) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (mensagem.isNotBlank()) Text(mensagem, Modifier.padding(vertical = 12.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp), contentPadding = PaddingValues(bottom = 20.dp)) {
            items(itens) { item ->
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
                    Column(Modifier.fillMaxWidth().padding(16.dp)) {
                        Text(
                            item.optString("titulo").ifBlank { item.optString("title").ifBlank { item.optString("remetente") } },
                            style = MaterialTheme.typography.titleMedium,
                        )
                        val detalhe = when (aba) {
                            "Agenda" -> listOf(item.optString("inicio"), item.optString("descricao")).filter(String::isNotBlank).joinToString("\n")
                            "Notas" -> item.optString("body")
                            else -> item.optString("texto")
                        }
                        if (detalhe.isNotBlank()) Text(detalhe, Modifier.padding(top = 8.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                        if (aba == "Agenda" || aba == "Notas") {
                            TextButton(enabled = !ocupado, onClick = { onExcluir(item) }) { Text("Excluir") }
                        }
                    }
                }
            }
        }
    }
}


@Composable
private fun TelaCasaIA(host: String, porta: Int, telaAtiva: Boolean, modifier: Modifier = Modifier) {
    val contexto = LocalContext.current
    val scope = rememberCoroutineScope()
    var fontes by remember(host, porta) { mutableStateOf(emptyList<JSONObject>()) }
    var aparelhos by remember(host, porta) { mutableStateOf(emptyList<JSONObject>()) }
    var rotinas by remember(host, porta) { mutableStateOf(emptyList<JSONObject>()) }
    var ocupado by remember { mutableStateOf(false) }
    var mensagem by remember { mutableStateOf("") }
    var criar by remember { mutableStateOf(false) }
    var abaCasa by remember { mutableStateOf("conexoes") }
    var rotinaEditando by remember { mutableStateOf<JSONObject?>(null) }
    var seletorApps by remember { mutableStateOf(false) }
    var filtroApps by remember { mutableStateOf("") }
    val appsNotificacao = remember { mutableStateListOf<String>() }
    var appsInstalados by remember { mutableStateOf(emptyList<Pair<String, String>>()) }
    LaunchedEffect(contexto) {
        appsInstalados = withContext(Dispatchers.IO) {
            @Suppress("DEPRECATION")
            val instalados = contexto.packageManager.getInstalledApplications(0)
            instalados.map { app -> app.packageName to app.loadLabel(contexto.packageManager).toString() }
                .filter { it.first != contexto.packageName }
                .distinctBy { it.first }.sortedBy { it.second.lowercase() }
        }
    }
    var nome by remember { mutableStateOf("") }
    var frase by remember { mutableStateOf("") }
    var inicio by remember { mutableStateOf("07:00") }
    var fim by remember { mutableStateOf("23:00") }
    val passosRascunho = remember { mutableStateListOf(PassoRotinaRascunho()) }
    val diasSelecionados = remember { mutableStateListOf(0, 1, 2, 3, 4, 5, 6) }
    var horarioAtivo by remember { mutableStateOf(false) }
    var chegadaAtiva by remember { mutableStateOf(false) }
    var simulacao by remember { mutableStateOf("") }
    var revisao by remember { mutableIntStateOf(0) }

    suspend fun atualizar() {
        ocupado = true
        try {
            val resultado = withContext(Dispatchers.IO) {
                Triple(
                    runCatching { Mark2Api.fontesCasa(host, porta) },
                    runCatching { Mark2Api.aparelhosCasa(host, porta) },
                    runCatching { Mark2Api.rotinasCasa(host, porta) },
                )
            }
            resultado.first.onSuccess { fontes = (0 until it.length()).mapNotNull(it::optJSONObject) }
            resultado.second.onSuccess { aparelhos = (0 until it.length()).mapNotNull(it::optJSONObject) }
            resultado.third.onSuccess {
                rotinas = (0 until it.length()).mapNotNull(it::optJSONObject)
                val frasesAtivas = JSONArray()
                rotinas.filter { rotina -> rotina.optBoolean("ativa") }.forEach { rotina ->
                    val frases = rotina.optJSONArray("frases") ?: return@forEach
                    for (i in 0 until frases.length()) frasesAtivas.put(frases.optString(i))
                }
                CofreLocal.obter(contexto).edit().putString("frases_rotinas_ativas", frasesAtivas.toString()).apply()
            }
            mensagem = resultado.second.exceptionOrNull()?.message ?: if (aparelhos.isEmpty()) "Nenhum aparelho SmartThings disponível. Confira a conexão na aba Conexões do painel do PC." else ""
        } catch (cancelado: CancellationException) { throw cancelado }
        catch (erro: Exception) { mensagem = erro.message ?: "Não foi possível carregar a central de casa." }
        finally { ocupado = false }
    }

    LaunchedEffect(host, porta, telaAtiva, revisao) {
        if (!telaAtiva) return@LaunchedEffect
        atualizar()
    }
    LaunchedEffect(host, porta, telaAtiva) {
        if (!telaAtiva) return@LaunchedEffect
        while (true) { delay(30_000); atualizar() }
    }

    Column(modifier.padding(horizontal = 16.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Column {
                Text("CASA INTELIGENTE", style = MaterialTheme.typography.titleLarge)
                Text("Aparelhos e rotinas conectados ao Jarvis", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            TextButton(enabled = !ocupado, onClick = { revisao++ }) { Text("Atualizar") }
        }
        if (ocupado) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (mensagem.isNotBlank()) Text(mensagem, Modifier.padding(vertical = 12.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("conexoes" to "Conexões", "aparelhos" to "Aparelhos", "rotinas" to "Rotinas").forEach { (id, titulo) ->
                if (abaCasa == id) Button(onClick = { abaCasa = id }) { Text(titulo) }
                else androidx.compose.material3.OutlinedButton(onClick = { abaCasa = id }) { Text(titulo) }
            }
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp), contentPadding = PaddingValues(bottom = 24.dp)) {
            if (abaCasa == "conexoes") {
            item {
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
                    Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                        Column {
                            Text("Fontes", style = MaterialTheme.typography.titleMedium)
                            Text("Credenciais guardadas no PC", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Text("${fontes.count { it.optBoolean("configurada") }} / ${fontes.size}", color = MaterialTheme.colorScheme.primary)
                    }
                }
            }
            items(fontes, key = { "fonte-" + it.optString("id") }) { fonte ->
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
                    Row(Modifier.fillMaxWidth().padding(14.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(fonte.optString("nome"), style = MaterialTheme.typography.titleSmall)
                            Text(if (fonte.optBoolean("configurada")) fonte.optString("estado") else "Configure no painel do PC", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Text(if (fonte.optBoolean("configurada")) "●" else "○", color = if (fonte.optBoolean("configurada")) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            }
            if (abaCasa == "aparelhos") {
            item {
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
                    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                            Text("Aparelhos SmartThings", style = MaterialTheme.typography.titleMedium)
                            Text("${aparelhos.size} conectados", color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.labelMedium)
                        }
                        Text("Luzes, tomadas e ventiladores", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            items(aparelhos, key = { it.optString("id") }) { aparelho ->
                val id = aparelho.optString("id")
                val ligado = aparelho.optString("estado") == "on"
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
                    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(aparelho.optString("nome", id), style = MaterialTheme.typography.titleSmall)
                            Text("${aparelho.optString("tipo").replaceFirstChar { it.uppercase() }} · ${if (ligado) "Ligado" else "Desligado"}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Switch(checked = ligado, enabled = !ocupado, onCheckedChange = { novo ->
                            scope.launch {
                                ocupado = true
                                try {
                                    withContext(Dispatchers.IO) { Mark2Api.acionarAparelhoCasa(host, porta, id, if (novo) "turn_on" else "turn_off") }
                                    delay(500)
                                    atualizar()
                                } catch (erro: Exception) { mensagem = erro.message ?: "Falha ao controlar o aparelho." }
                                finally { ocupado = false }
                            }
                        })
                    }
                }
            }
            }
            if (abaCasa == "rotinas") {
            item {
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
                    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                            Column {
                                Text("Minhas rotinas", style = MaterialTheme.typography.titleMedium)
                                Text("Frase de voz ou horário", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            Button(onClick = { rotinaEditando = null; appsNotificacao.clear(); nome = ""; frase = ""; inicio = "07:00"; fim = "23:00"; passosRascunho.clear(); passosRascunho.add(PassoRotinaRascunho()); diasSelecionados.clear(); diasSelecionados.addAll(0..6); horarioAtivo = false; chegadaAtiva = false; criar = true }) { Text("+ Nova") }
                        }
                    }
                }
            }
            if (rotinas.isEmpty()) item { Text("Crie uma rotina no Jarvis para automatizar falas e horários.", Modifier.padding(8.dp), color = MaterialTheme.colorScheme.onSurfaceVariant) }
            items(rotinas, key = { it.optString("id") }) { rotina ->
                val id = rotina.optString("id")
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainer)) {
                    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(rotina.optString("nome"), style = MaterialTheme.typography.titleSmall)
                                val frases = rotina.optJSONArray("frases")
                                val gatilhos = buildList {
                                if (frases != null && frases.length() > 0) add("Frase: ${frases.optString(0)}")
                                if (rotina.optString("evento") == "chegada") add("Chegada")
                                if ((rotina.optJSONArray("apps_notificacao")?.length() ?: 0) > 0) add("Notificações ${(rotina.optJSONArray("apps_notificacao")?.length() ?: 0)} app(s)")
                                if (rotina.optBoolean("agendada")) add("Horário ${rotina.optString("inicio")}")
                            }.joinToString(" · ").ifBlank { "Manual · janela ${rotina.optString("inicio")}–${rotina.optString("fim")}" }
                            Text(gatilhos, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            Switch(checked = rotina.optBoolean("ativa"), onCheckedChange = { ativa ->
                                val copia = JSONObject(rotina.toString()).put("ativa", ativa)
                                scope.launch {
                                    ocupado = true
                                    try { withContext(Dispatchers.IO) { Mark2Api.salvarRotinaCasa(host, porta, copia) }; revisao++ }
                                    catch (erro: Exception) { mensagem = erro.message ?: "Não foi possível alterar a rotina." }
                                    finally { ocupado = false }
                                }
                            })
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            TextButton(enabled = !ocupado, onClick = {
                                rotinaEditando = JSONObject(rotina.toString())
                                nome = rotina.optString("nome")
                                frase = rotina.optJSONArray("frases")?.optString(0).orEmpty()
                                appsNotificacao.clear(); rotina.optJSONArray("apps_notificacao")?.let { a -> for (i in 0 until a.length()) appsNotificacao.add(a.optString(i)) }
                                inicio = rotina.optString("inicio", "07:00"); fim = rotina.optString("fim", "23:00")
                                horarioAtivo = rotina.optBoolean("agendada"); chegadaAtiva = rotina.optString("evento") == "chegada"
                                diasSelecionados.clear(); rotina.optJSONArray("dias")?.let { a -> for (i in 0 until a.length()) diasSelecionados.add(a.optInt(i)) }
                                passosRascunho.clear()
                                rotina.optJSONArray("passos")?.let { a -> for (i in 0 until a.length()) a.optJSONObject(i)?.let { p ->
                                    passosRascunho.add(PassoRotinaRascunho(p.optString("tipo", "falar")).apply { texto = p.optString("texto"); segundos = p.optInt("segundos", 5).toString(); aparelhoId = p.optString("id"); acao = p.optString("acao", "turn_on") })
                                } }
                                if (passosRascunho.isEmpty()) passosRascunho.add(PassoRotinaRascunho())
                                criar = true
                            }) { Text("Editar") }
                            TextButton(enabled = !ocupado, onClick = {
                                scope.launch {
                                    try {
                                        val r = withContext(Dispatchers.IO) { Mark2Api.executarRotinaCasa(host, porta, id, true) }
                                        simulacao = "Simulação: ${r.optJSONArray("passos")?.length() ?: 0} passo(s); ${if (r.optBoolean("permitida_agora")) "dentro do horário" else "fora do horário"}. Nenhuma ação foi executada."
                                    } catch (erro: Exception) { mensagem = erro.message ?: "Não foi possível simular." }
                                }
                            }) { Text("Simular") }
                            TextButton(enabled = !ocupado && rotina.optBoolean("ativa"), onClick = {
                                scope.launch {
                                    ocupado = true
                                    try {
                                        val r = withContext(Dispatchers.IO) { Mark2Api.executarRotinaCasa(host, porta, id, false) }
                                        mensagem = if (r.optBoolean("iniciada")) "Rotina ${r.optString("nome")} iniciada." else "Rotina iniciada."
                                        val fala = (0 until (r.optJSONArray("falas")?.length() ?: 0)).mapNotNull { r.optJSONArray("falas")?.optString(it) }.filter(String::isNotBlank).joinToString(". ")
                                        if (fala.isNotBlank()) VozCelular.falarResposta(host, porta, fala)
                                        revisao++
                                    } catch (erro: Exception) { mensagem = erro.message ?: "Não foi possível executar." }
                                    finally { ocupado = false }
                                }
                            }) { Text("Executar") }
                            TextButton(enabled = !ocupado, onClick = {
                                scope.launch {
                                    try { withContext(Dispatchers.IO) { Mark2Api.removerRotinaCasa(host, porta, id) }; revisao++ }
                                    catch (erro: Exception) { mensagem = erro.message ?: "Não foi possível excluir." }
                                }
                            }) { Text("Excluir") }
                        }
                    }
                }
            }
            item {
                TextButton(enabled = !ocupado, onClick = {
                    scope.launch {
                        try { withContext(Dispatchers.IO) { Mark2Api.cancelarRotinasCasa(host, porta) }; mensagem = "Rotinas em execução interrompidas."; VozCelular.interromper() }
                        catch (erro: Exception) { mensagem = erro.message ?: "Não foi possível interromper." }
                    }
                }) { Text("■ Parar todas as rotinas") }
            }
            if (simulacao.isNotBlank()) item { Text(simulacao, color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.bodySmall) }
            }
        }
    }

    if (criar) AlertDialog(
        onDismissRequest = { criar = false; seletorApps = false },
        title = { Text(if (rotinaEditando == null) "Nova rotina" else "Editar rotina") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (seletorApps) {
                    Text("Escolha quais apps podem ativar esta rotina. O conteúdo das notificações não é enviado ao computador.", style = MaterialTheme.typography.bodySmall)
                    TextButton(onClick = { seletorApps = false; filtroApps = "" }) { Text("← Voltar à rotina") }
                    OutlinedTextField(filtroApps, { filtroApps = it.take(80) }, label = { Text("Buscar aplicativo") }, singleLine = true)
                    val visiveis = appsInstalados.filter { filtroApps.isBlank() || it.second.contains(filtroApps, ignoreCase = true) || it.first.contains(filtroApps, ignoreCase = true) }
                    if (visiveis.isEmpty()) Text("Nenhum aplicativo encontrado.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                    visiveis.forEach { (pacote, rotulo) ->
                        Row(Modifier.fillMaxWidth().clickable { if (pacote in appsNotificacao) appsNotificacao.remove(pacote) else if (appsNotificacao.size < 30) appsNotificacao.add(pacote) }, verticalAlignment = Alignment.CenterVertically) {
                            androidx.compose.material3.Checkbox(checked = pacote in appsNotificacao, onCheckedChange = { marcado -> if (marcado && appsNotificacao.size < 30) appsNotificacao.add(pacote) else appsNotificacao.remove(pacote) })
                            Text(rotulo, style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                    if (appsNotificacao.size >= 30) Text("Limite de 30 aplicativos por rotina.", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
                } else {
                Text("Escolha a frase que ativa a rotina e organize as ações abaixo. A rotina nova começa desativada.", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(nome, { nome = it.take(80) }, label = { Text("Nome") }, singleLine = true)
                OutlinedTextField(frase, { frase = it.take(120) }, label = { Text("Frase que ativa esta rotina") }, placeholder = { Text("Ex.: Olá Jarvis, ligar luzes") }, singleLine = true)
                OutlinedTextField(inicio, { inicio = it.take(5) }, label = { Text("Início permitido · HH:MM") }, singleLine = true)
                OutlinedTextField(fim, { fim = it.take(5) }, label = { Text("Fim permitido · HH:MM") }, singleLine = true)
                Text("Aplicativos que ativam esta rotina", style = MaterialTheme.typography.titleSmall)
                Text(if (appsNotificacao.isEmpty()) "Nenhum app selecionado" else "${appsNotificacao.size} aplicativo(s) selecionado(s) · o Jarvis anuncia no celular", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                TextButton(onClick = { seletorApps = true }) { Text("Escolher aplicativos") }
                Text("Dias ativos", style = MaterialTheme.typography.titleSmall)
                Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    listOf("S", "T", "Q", "Q", "S", "S", "D").forEachIndexed { dia, rotulo ->
                        TextButton(onClick = { if (dia in diasSelecionados) diasSelecionados.remove(dia) else diasSelecionados.add(dia) }) {
                            Text(rotulo, color = if (dia in diasSelecionados) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                }
                Text("Passos da rotina", style = MaterialTheme.typography.titleSmall)
                passosRascunho.forEachIndexed { indice, passo ->
                    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
                        Column(Modifier.fillMaxWidth().padding(10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                                listOf("falar" to "Falar", "esperar" to "Esperar", "aparelho" to "Aparelho").forEach { (tipo, titulo) ->
                                    TextButton(onClick = { passo.tipo = tipo }) { Text(if (passo.tipo == tipo) "• " else titulo) }
                                }
                                if (passosRascunho.size > 1) TextButton(onClick = { passosRascunho.removeAt(indice) }) { Text("Remover") }
                            }
                            when (passo.tipo) {
                                "falar" -> OutlinedTextField(passo.texto, { passo.texto = it.take(500) }, label = { Text("Texto que o Jarvis falará") })
                                "esperar" -> OutlinedTextField(passo.segundos, { passo.segundos = it.filter(Char::isDigit).take(3) }, label = { Text("Esperar em segundos · 1 a 600") }, singleLine = true)
                                "aparelho" -> {
                                    Text("Aparelho SmartThings", style = MaterialTheme.typography.bodySmall)
                                    if (aparelhos.isEmpty()) Text("Nenhum aparelho carregado. Conecte o SmartThings no PC.", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
                                    aparelhos.forEach { aparelho ->
                                        val id = aparelho.optString("id")
                                        TextButton(onClick = { passo.aparelhoId = id }) { Text(" · ") }
                                    }
                                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                        TextButton(onClick = { passo.acao = "turn_on" }) { Text(if (passo.acao == "turn_on") "• Ligar" else "Ligar") }
                                        TextButton(onClick = { passo.acao = "turn_off" }) { Text(if (passo.acao == "turn_off") "• Desligar" else "Desligar") }
                                    }
                                }
                            }
                        }
                    }
                }
                TextButton(enabled = passosRascunho.size < 20, onClick = { passosRascunho.add(PassoRotinaRascunho()) }) { Text("+ Adicionar passo (/20)") }
                }
            }
        },
        confirmButton = {
            TextButton(enabled = !seletorApps && nome.isNotBlank() && frase.isNotBlank() && diasSelecionados.isNotEmpty() && passosRascunho.isNotEmpty() && inicio.matches(Regex("(?:[01]\\d|2[0-3]):[0-5]\\d")) && fim.matches(Regex("(?:[01]\\d|2[0-3]):[0-5]\\d")) && passosRascunho.all { passo -> when (passo.tipo) { "falar" -> passo.texto.isNotBlank(); "esperar" -> (passo.segundos.toIntOrNull() ?: 0) in 1..600; "aparelho" -> passo.aparelhoId.isNotBlank() && aparelhos.any { it.optString("id") == passo.aparelhoId }; else -> false } }, onClick = {
                val passos = JSONArray()
                passosRascunho.forEach { passo ->
                    passos.put(when (passo.tipo) {
                        "falar" -> JSONObject().put("tipo", "falar").put("texto", passo.texto.trim())
                        "esperar" -> JSONObject().put("tipo", "esperar").put("segundos", passo.segundos.toInt())
                        else -> JSONObject().put("tipo", "aparelho").put("id", passo.aparelhoId).put("acao", passo.acao)
                    })
                }
                val frases = JSONArray().also { if (frase.isNotBlank()) it.put(frase.trim()) }
                val apps = JSONArray().also { lista -> appsNotificacao.distinct().forEach(lista::put) }
                val rotina = (rotinaEditando?.let { JSONObject(it.toString()) } ?: JSONObject())
                    .put("nome", nome.trim()).put("frases", frases).put("apps_notificacao", apps).put("passos", passos)
                    .put("dias", JSONArray(diasSelecionados.sorted())).put("inicio", inicio).put("fim", fim).put("evento", if (chegadaAtiva) "chegada" else "").put("agendada", horarioAtivo)
                if (rotinaEditando == null) rotina.put("ativa", false)
                scope.launch {
                    ocupado = true
                    try { withContext(Dispatchers.IO) { Mark2Api.salvarRotinaCasa(host, porta, rotina) }; criar = false; rotinaEditando = null; revisao++ }
                    catch (erro: Exception) { mensagem = erro.message ?: "Não foi possível criar a rotina." }
                    finally { ocupado = false }
                }
            }) { Text(if (rotinaEditando == null) "Salvar desativada" else "Salvar alterações") }
        },
        dismissButton = { TextButton(onClick = { criar = false }) { Text("Cancelar") } },
    )
}


