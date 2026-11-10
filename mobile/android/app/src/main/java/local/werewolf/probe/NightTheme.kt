package local.werewolf.probe

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

internal object NightPalette {
    val LightGround = Color(0xFFF2F2F2)
    val LightSurface = Color(0xFFFFFFFF)
    val LightRaised = Color(0xFFFCFCFC)
    val LightInk = Color(0xFF1C1C1C)
    val LightMuted = Color(0xFF606060)
    val LightOutline = Color(0xFF929292)
    val LightDivider = Color(0xFFE3E3E3)
    val LightAccent = Color(0xFF2A2B7B)
    val LightSelected = Color(0xFFE4E4F0)
    val LightError = Color(0xFFA52A32)
    val DarkGround = Color(0xFF121212)
    val DarkSurface = Color(0xFF30343D)
    val DarkRaised = Color(0xFF474E5B)
    val DarkInk = Color(0xFFF2F2F2)
    val DarkMuted = Color(0xFFC4C7CC)
    val DarkOutline = Color(0xFF7D8591)
    val DarkDivider = Color(0xFF4C525D)
    val DarkAccent = Color(0xFFC3C4EF)
    val DarkSelected = Color(0xFF383956)
    val DarkError = Color(0xFFF0AEB3)
}

private fun nightColors(dark: Boolean) = with(NightPalette) {
    val ground = if (dark) DarkGround else LightGround
    val surface = if (dark) DarkSurface else LightSurface
    val raised = if (dark) DarkRaised else LightRaised
    val ink = if (dark) DarkInk else LightInk
    val muted = if (dark) DarkMuted else LightMuted
    val accent = if (dark) DarkAccent else LightAccent
    val selected = if (dark) DarkSelected else LightSelected
    val error = if (dark) DarkError else LightError
    (if (dark) darkColorScheme() else lightColorScheme()).copy(
        primary = accent, onPrimary = if (dark) DarkGround else LightSurface,
        primaryContainer = selected, onPrimaryContainer = ink,
        inversePrimary = if (dark) LightAccent else DarkAccent,
        secondary = accent, onSecondary = if (dark) DarkGround else LightSurface,
        secondaryContainer = selected, onSecondaryContainer = ink,
        tertiary = muted, onTertiary = surface,
        tertiaryContainer = raised, onTertiaryContainer = ink,
        background = ground, onBackground = ink,
        surface = surface, onSurface = ink,
        surfaceVariant = raised, onSurfaceVariant = muted,
        surfaceTint = Color.Transparent,
        surfaceDim = ground, surfaceBright = raised,
        surfaceContainerLowest = ground, surfaceContainerLow = surface,
        surfaceContainer = surface, surfaceContainerHigh = raised,
        surfaceContainerHighest = raised,
        inverseSurface = if (dark) LightInk else DarkInk,
        inverseOnSurface = if (dark) LightGround else DarkGround,
        outline = if (dark) DarkOutline else LightOutline,
        outlineVariant = if (dark) DarkDivider else LightDivider,
        error = error, onError = if (dark) DarkGround else LightSurface,
        errorContainer = if (dark) Color(0xFF54252A) else Color(0xFFF7E1E3),
        onErrorContainer = ink, scrim = Color.Black,
    )
}

private fun type(size: Float, height: Float, weight: FontWeight = FontWeight.Normal, tracking: Float = 0f) =
    TextStyle(fontFamily = FontFamily.Default, fontSize = size.sp, lineHeight = height.sp,
        fontWeight = weight, letterSpacing = tracking.sp)

private val NightTypography = Typography(
    headlineLarge = type(28f, 36f, FontWeight.SemiBold, -.56f),
    headlineMedium = type(24f, 32f, FontWeight.SemiBold, -.48f),
    headlineSmall = type(24f, 32f, FontWeight.SemiBold, -.48f),
    titleLarge = type(19f, 26f, FontWeight.SemiBold, -.38f),
    titleMedium = type(17f, 24f, FontWeight.SemiBold, -.255f),
    titleSmall = type(16f, 22f, FontWeight.Medium, -.32f),
    bodyLarge = type(15.5f, 23f),
    bodyMedium = type(13f, 19f),
    bodySmall = type(12f, 18f),
    labelLarge = type(14f, 20f, FontWeight.Medium, -.28f),
    labelMedium = type(12f, 18f, FontWeight.Medium),
    labelSmall = type(11f, 16f, FontWeight.Medium),
)

@Composable internal fun NightTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = nightColors(isSystemInDarkTheme()),
        typography = NightTypography,
        shapes = Shapes(
            extraSmall = RoundedCornerShape(12.dp),
            small = RoundedCornerShape(12.dp),
            medium = RoundedCornerShape(16.dp),
            large = RoundedCornerShape(18.dp),
            extraLarge = RoundedCornerShape(26.dp),
        ),
        content = content,
    )
}
