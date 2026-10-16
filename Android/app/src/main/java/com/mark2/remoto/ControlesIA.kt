package com.mark2.remoto

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

// Mostra controles remotos limitados
@Composable
fun ControlesIA(host: String, porta: Int, visivel: Boolean) {
    val scope = rememberCoroutineScope()
    var lm by remember { mutableStateOf(false) }
    var hermes by remember { mutableStateOf(false) }
    var pronto by remember { mutableStateOf(false) }
    var ocupado by remember { mutableStateOf(false) }
    var erro by remember { mutableStateOf("") }
    LaunchedEffect(host, porta, visivel) {
        if (!visivel) return@LaunchedEffect
        try { val d = withContext(Dispatchers.IO) { Mark2Api.estadoIA(host, porta) }; lm = d.optBoolean("lm_studio"); hermes = d.optBoolean("hermes"); pronto = true; erro = "" }
        catch (e: Exception) { pronto = false; erro = "Conecte ao PC para controlar a IA." }
    }
    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("INTELIGÊNCIA LOCAL", style = MaterialTheme.typography.labelMedium)
        for ((key, title) in listOf("lm_studio" to "LM Studio", "hermes" to "Hermes")) {
            val ativa = if (key == "lm_studio") lm else hermes
            OutlinedButton(enabled = pronto && !ocupado, onClick = { scope.launch {
                ocupado = true
                try { val d = withContext(Dispatchers.IO) { Mark2Api.alternarIA(host, porta, key, !ativa) }; lm = d.optBoolean("lm_studio"); hermes = d.optBoolean("hermes"); erro = "" }
                catch (e: Exception) { erro = e.message ?: "Não foi possível alterar." }
                finally { ocupado = false }
            } }, modifier = Modifier.fillMaxWidth()) { Text("$title · " + if (ativa) "Ativo" else "Desativado") }
        }
        Button(onClick = {
            VozCelular.interromper()
            scope.launch { try { withContext(Dispatchers.IO) { Mark2Api.pararTudo(host, porta) }; erro = "" } catch (e: Exception) { erro = "A voz local parou. Não foi possível parar o PC." } }
        }, modifier = Modifier.fillMaxWidth(), colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.errorContainer, contentColor = MaterialTheme.colorScheme.onErrorContainer)) { Text("Parar resposta e voz") }
        if (erro.isNotBlank()) Text(erro, style = MaterialTheme.typography.bodySmall)
    }
}
