package com.mark2.remoto

class ContadorAvisos {
    val conhecidos = linkedSetOf<String>()
    var whatsapp = 0
    var instagram = 0

    // Conta mensagens sem duplicar
    fun registrar(app: String, ids: List<String>): Int {
        var novos = 0
        for (id in ids) {
            if (conhecidos.add(id)) novos++
            while (conhecidos.size > 256) conhecidos.remove(conhecidos.first())
        }
        val limite = if (app == "instagram") 2 else 5
        val saldo = if (app == "instagram") instagram else whatsapp
        val total = saldo + novos
        if (app == "instagram") instagram = total % limite else whatsapp = total % limite
        return total / limite
    }

    // Retoma contadores persistidos
    fun restaurar(ids: List<String>, whats: Int, insta: Int) {
        conhecidos.clear(); conhecidos.addAll(ids.takeLast(256))
        whatsapp = whats.coerceIn(0,4); instagram = insta.coerceIn(0,1)
    }
}
