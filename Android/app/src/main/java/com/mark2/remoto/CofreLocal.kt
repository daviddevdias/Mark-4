package com.mark2.remoto

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import java.nio.charset.StandardCharsets
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

class CofreLocal private constructor(context: Context, nome: String) {
    private val appContext = context.applicationContext
    private val nomeArquivo = nome
    private val seguro = appContext.getSharedPreferences("${nome}_seguro", Context.MODE_PRIVATE)
    private val legado = appContext.getSharedPreferences(nome, Context.MODE_PRIVATE)

    // Consulta texto
    fun getString(chave: String, padrao: String?): String? = sincronizado {
        val dados = lerDados()
        if (!dados.has(chave) || dados.isNull(chave)) padrao else dados.optString(chave, "")
    }

    // Consulta número
    fun getInt(chave: String, padrao: Int): Int = sincronizado {
        lerDados().optInt(chave, padrao)
    }

    
    fun getBoolean(chave: String, padrao: Boolean): Boolean = sincronizado {
        lerDados().optBoolean(chave, padrao)
    }

    
    fun edit() = Editor()

    inner class Editor {
        private val alteracoes = linkedMapOf<String, Any?>()

        // Salva texto
        fun putString(chave: String, valor: String?): Editor = apply {
            alteracoes[chave] = valor
        }

        // Salva número
        fun putInt(chave: String, valor: Int): Editor = apply {
            alteracoes[chave] = valor
        }

        
        fun putBoolean(chave: String, valor: Boolean): Editor = apply {
            alteracoes[chave] = valor
        }

        
        fun commit(): Boolean = sincronizado {
            val dados = lerDados()
            alteracoes.forEach { (chave, valor) ->
                if (valor == null) dados.remove(chave) else dados.put(chave, valor)
            }
            gravarDados(dados)
        }

        
        fun apply() {
            commit()
        }
    }

    
    private fun lerDados(): JSONObject {
        val payload = seguro.getString(CHAVE_DADOS, null)
        if (payload != null) {
            val texto = abrir(payload)
            return JSONObject(texto)
        }
        val dados = JSONObject()
        legado.all.forEach { (chave, valor) ->
            when (valor) {
                is String, is Int, is Long, is Float, is Boolean -> dados.put(chave, valor)
                is Set<*> -> dados.put(chave, JSONArray(valor.filterIsInstance<String>()))
            }
        }
        if (dados.length() > 0 && gravarDados(dados)) {
            legado.edit().clear().commit()
        }
        return dados
    }

    
    private fun gravarDados(dados: JSONObject): Boolean {
        val payload = selar(dados.toString())
        return seguro.edit().putString(CHAVE_DADOS, payload).commit()
    }

    
    private fun selar(texto: String): String {
        val cifra = Cipher.getInstance("AES/GCM/NoPadding")
        cifra.init(Cipher.ENCRYPT_MODE, obterChave())
        val cifrado = cifra.doFinal(texto.toByteArray(StandardCharsets.UTF_8))
        val combinado = cifra.iv + cifrado
        return PREFIXO + Base64.encodeToString(combinado, Base64.NO_WRAP)
    }

    
    private fun abrir(payload: String): String {
        require(payload.startsWith(PREFIXO)) { "Formato de preferencias protegidas inválido." }
        val combinado = Base64.decode(payload.removePrefix(PREFIXO), Base64.NO_WRAP)
        require(combinado.size > TAMANHO_IV) { "Preferencias protegidas incompletas." }
        val iv = combinado.copyOfRange(0, TAMANHO_IV)
        val cifrado = combinado.copyOfRange(TAMANHO_IV, combinado.size)
        val cifra = Cipher.getInstance("AES/GCM/NoPadding")
        cifra.init(Cipher.DECRYPT_MODE, obterChave(), GCMParameterSpec(128, iv))
        return String(cifra.doFinal(cifrado), StandardCharsets.UTF_8)
    }

    // Consulta chave
    private fun obterChave(): SecretKey {
        val armazenamento = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val existente = armazenamento.getKey(ALIAS, null) as? SecretKey
        if (existente != null) return existente
        val gerador = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gerador.init(
            KeyGenParameterSpec.Builder(
                ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .build(),
        )
        return gerador.generateKey()
    }

    companion object {
        private const val ALIAS = "mark2_local_v1"
        private const val CHAVE_DADOS = "payload"
        private const val PREFIXO = "m2e1:"
        private const val TAMANHO_IV = 12
        private val trava = Any()

        
        fun obter(context: Context, nome: String = "mark2_config") =
            CofreLocal(context, nome)

        
        private inline fun <T> sincronizado(bloco: () -> T): T = synchronized(trava, bloco)
    }
}
