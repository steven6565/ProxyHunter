package com.proxyhunter.app.ui

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

val Navy = Color(0xFF0B1220)
val Charcoal = Color(0xFF11161F)
val Surface = Color(0xFF182130)
val Emerald = Color(0xFF10B981)
val Danger = Color(0xFFEF4444)
val Muted = Color(0xFF94A3B8)

private val DarkPalette = darkColorScheme(
    primary = Emerald,
    secondary = Color(0xFF34D399),
    background = Charcoal,
    surface = Surface,
    onPrimary = Color(0xFF04150F),
    onBackground = Color(0xFFE6EDF3),
    onSurface = Color(0xFFE6EDF3),
    error = Danger,
)

private val LightPalette = lightColorScheme(
    primary = Color(0xFF059669),
    secondary = Color(0xFF10B981),
    background = Color(0xFFF4F7FA),
    surface = Color.White,
    error = Danger,
)

private val Shapes = Shapes(
    small = RoundedCornerShape(8.dp),
    medium = RoundedCornerShape(14.dp),
    large = RoundedCornerShape(20.dp),
)

private val Type = Typography(
    titleLarge = TextStyle(fontSize = 22.sp, fontWeight = FontWeight.SemiBold),
    titleMedium = TextStyle(fontSize = 17.sp, fontWeight = FontWeight.Medium),
    bodyMedium = TextStyle(fontSize = 14.sp),
    labelMedium = TextStyle(fontSize = 12.sp, color = Muted),
)

@Composable
fun ProxyHunterTheme(dark: Boolean = true, content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (dark) DarkPalette else LightPalette,
        typography = Type,
        shapes = Shapes,
        content = content,
    )
}
