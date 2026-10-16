package com.mark2.remoto

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun TelaComandos(host: String, porta: Int, navegar: (String) -> Unit, modifier: Modifier = Modifier) {
    val scope = rememberCoroutineScope()
    var ocupado by remember { mutableStateOf(false) }
    var resposta by remember { mutableStateOf("") }
    LazyColumn(modifier, contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { Text("NO CELULAR", style = MaterialTheme.typography.titleMedium) }
        for (pagina in listOf("Agenda", "Notas", "WhatsApp", "Torre Stark")) item {
            OutlinedButton(onClick = { navegar(pagina) }, modifier = Modifier.fillMaxWidth()) { Text("Abrir $pagina") }
        }
        item { Text("DADOS DO SEU JARVIS", style = MaterialTheme.typography.titleMedium) }
        for ((acao, titulo) in listOf("agenda" to "Ler minha agenda", "notas" to "Ler minhas notas", "whatsapp" to "Ler avisos do WhatsApp")) item {
            Button(enabled = !ocupado, onClick = { scope.launch {
                val versao = VozCelular.versao
                ocupado = true
                try { resposta = withContext(Dispatchers.IO) { Mark2Api.comandoPessoal(host, porta, acao) }; if (versao == VozCelular.versao) VozCelular.falar(host, porta, resposta) }
                catch (erro: Exception) { resposta = erro.message ?: "Não foi possível conectar."; if (versao == VozCelular.versao) VozCelular.falar(host, porta, resposta) }
                finally { ocupado = false }
            } }, modifier = Modifier.fillMaxWidth()) { Text(titulo) }
        }
        if (ocupado) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
        if (resposta.isNotBlank()) item { Text(resposta) }
    }
}
