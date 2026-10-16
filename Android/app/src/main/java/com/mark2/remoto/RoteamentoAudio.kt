package com.mark2.remoto

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioDeviceCallback
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.os.Build
import android.os.Handler
import android.util.Log

/* Entrada de áudio escolhida. [tipo] */



class RotaEntrada(val tipo: Int, val dispositivo: AudioDeviceInfo?) {
    val bluetooth: Boolean
        get() = tipo == AudioDeviceInfo.TYPE_BLUETOOTH_SCO ||
                (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S && tipo == AudioDeviceInfo.TYPE_BLE_HEADSET)
}





object RoteamentoAudio {
    private const val TAG = "RoteamentoAudio"
    private const val ESPERA_SCO_LEGADO_MS = 1_500L
    private const val ESPERA_TROCA_MS = 600L

    @Volatile private var rotaBluetoothAtiva = false

    
    private fun gerenciador(contexto: Context) =
        contexto.applicationContext.getSystemService(Context.AUDIO_SERVICE) as AudioManager

    
    private fun temPermissaoBluetooth(contexto: Context): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.S ||
                contexto.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED

    
    private fun bluetoothConectado(am: AudioManager, tipo: Int): Boolean =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            am.availableCommunicationDevices.any { it.type == tipo }
        } else {
            am.getDevices(AudioManager.GET_DEVICES_OUTPUTS).any { it.type == tipo }
        }

    /* Fone com microfone, na ordem: P2 > */




    
    fun entradaPreferida(contexto: Context): RotaEntrada? {
        val am = gerenciador(contexto)
        val entradas = am.getDevices(AudioManager.GET_DEVICES_INPUTS)
        for (tipo in listOf(AudioDeviceInfo.TYPE_WIRED_HEADSET, AudioDeviceInfo.TYPE_USB_HEADSET)) {
            entradas.firstOrNull { it.type == tipo }?.let { return RotaEntrada(tipo, it) }
        }
        return null
    }

    /* Microfone embutido do celular */
    
    fun microfoneDoCelular(contexto: Context): AudioDeviceInfo? =
        gerenciador(contexto).getDevices(AudioManager.GET_DEVICES_INPUTS)
            .firstOrNull { it.type == AudioDeviceInfo.TYPE_BUILTIN_MIC }

    
    
    fun saidaPreferida(contexto: Context, rota: RotaEntrada?): AudioDeviceInfo? {
        val saidas = gerenciador(contexto).getDevices(AudioManager.GET_DEVICES_OUTPUTS)
        if (rota != null) saidas.firstOrNull { it.type == rota.tipo }?.let { return it }
        val tipos = mutableListOf(
            AudioDeviceInfo.TYPE_WIRED_HEADSET,
            AudioDeviceInfo.TYPE_WIRED_HEADPHONES,
            AudioDeviceInfo.TYPE_USB_HEADSET,
        )
        if (temPermissaoBluetooth(contexto)) tipos.add(AudioDeviceInfo.TYPE_BLUETOOTH_A2DP)
        for (tipo in tipos) saidas.firstOrNull { it.type == tipo }?.let { return it }
        return null
    }

    /* Prepara a rota da entrada */



    
    fun ativarEntrada(contexto: Context, rota: RotaEntrada?, handler: Handler, aoPronto: () -> Unit) {
        if (rota == null || !rota.bluetooth) {
            liberarEntrada(contexto)
            aoPronto()
            return
        }
        val am = gerenciador(contexto)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val destino = am.availableCommunicationDevices.firstOrNull { it.type == rota.tipo }
            val ok = destino != null && am.setCommunicationDevice(destino)
            if (!ok) Log.w(TAG, "Não consegui rotear a voz pro fone Bluetooth.")
            rotaBluetoothAtiva = ok
            aoPronto()
        } else {
            @Suppress("DEPRECATION")
            am.startBluetoothSco()
            @Suppress("DEPRECATION")
            am.isBluetoothScoOn = true
            rotaBluetoothAtiva = true
            handler.postDelayed({ aoPronto() }, ESPERA_SCO_LEGADO_MS)
        }
    }

    
    fun liberarEntrada(contexto: Context) {
        if (!rotaBluetoothAtiva) return
        rotaBluetoothAtiva = false
        val am = gerenciador(contexto)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            am.clearCommunicationDevice()
        } else {
            @Suppress("DEPRECATION")
            am.isBluetoothScoOn = false
            @Suppress("DEPRECATION")
            am.stopBluetoothSco()
        }
    }

    /* Avisa quando o fone é */



    
    fun observar(contexto: Context, handler: Handler, aoMudar: () -> Unit): () -> Unit {
        val am = gerenciador(contexto)
        var anterior = entradaPreferida(contexto)?.tipo ?: -1
        val verificar = Runnable {
            val atual = entradaPreferida(contexto)?.tipo ?: -1
            if (atual != anterior) {
                anterior = atual
                aoMudar()
            }
        }
        val callback = object : AudioDeviceCallback() {
            // Trata áudio devices added
            override fun onAudioDevicesAdded(addedDevices: Array<out AudioDeviceInfo>?) = agendar()
            // Trata áudio devices removed
            override fun onAudioDevicesRemoved(removedDevices: Array<out AudioDeviceInfo>?) = agendar()
            
            private fun agendar() {
                handler.removeCallbacks(verificar)
                handler.postDelayed(verificar, ESPERA_TROCA_MS)
            }
        }
        am.registerAudioDeviceCallback(callback, handler)
        return {
            handler.removeCallbacks(verificar)
            am.unregisterAudioDeviceCallback(callback)
        }
    }
}