package com.mark2.remoto

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.sp

object CoresMark2 {
    val fundo = Color(0xFF15151C)
    val fundoPainel = Color(0xFF27232F)
    val superficieElevada = Color(0xFF312A42)
    val roxo = Color(0xFF8064B5)
    val roxoLuminoso = Color(0xFFC4B5FD)
    val texto = Color(0xFFF4F3F8)
    val dim = Color(0xFFA8A6B1)
    val separador = Color(0xFF39353F)
    val verde = Color(0xFF8DB99A)
    val vermelho = Color(0xFFD98585)
    val azul = Color(0xFF3B82F6)
    val azulBrilhante = Color(0xFF60A5FA)
    val dourado = Color(0xFFF59E0B)
}

val FonteMark2 = FontFamily.Default

val TituloTopoEstilo = TextStyle(
    fontFamily = FonteMark2,
    fontSize = 11.sp,
    letterSpacing = 2.sp,
)

@Composable

fun TemaMark2(conteudo: @Composable () -> Unit) {
    val esquema = darkColorScheme(
        background = CoresMark2.fundo,
        surface = CoresMark2.fundoPainel,
        surfaceVariant = CoresMark2.superficieElevada,
        surfaceContainer = CoresMark2.superficieElevada,
        primary = CoresMark2.roxo,
        onPrimary = Color.White,
        onBackground = CoresMark2.texto,
        onSurface = CoresMark2.texto,
        secondary = CoresMark2.roxoLuminoso,
        error = CoresMark2.vermelho,
        onSurfaceVariant = CoresMark2.dim,
        outline = CoresMark2.separador,
    )
    MaterialTheme(colorScheme = esquema, content = conteudo)
}
