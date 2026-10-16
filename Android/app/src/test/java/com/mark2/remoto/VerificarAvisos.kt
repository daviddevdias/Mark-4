package com.mark2.remoto

object VerificarAvisos {
    // Verifica limites e duplicações
    @JvmStatic
    fun main(args: Array<String>) {
        val contador = ContadorAvisos()
        check(contador.registrar("whatsapp",listOf("w1","w2","w3","w4")) == 0)
        check(contador.registrar("whatsapp",listOf("w1","w2","w3","w4")) == 0)
        check(contador.whatsapp == 4)
        check(contador.registrar("whatsapp",listOf("w5")) == 1)
        check(contador.registrar("instagram",listOf("i1")) == 0)
        check(contador.registrar("instagram",listOf("i2")) == 1)
        check(contador.registrar("instagram",listOf("i2")) == 0)
        check(contador.registrar("whatsapp",(6..15).map { "w$it" }) == 2)
        val retomado = ContadorAvisos()
        retomado.restaurar(contador.conhecidos.toList(),contador.whatsapp,contador.instagram)
        check(retomado.registrar("whatsapp",listOf("w15")) == 0)
        retomado.registrar("whatsapp",(100..500).map { "w$it" })
        check(retomado.conhecidos.size <= 256)
        println("Avisos: limites 5 e 2, deduplicação, recuperação e memória limitada passaram.")
    }
}
