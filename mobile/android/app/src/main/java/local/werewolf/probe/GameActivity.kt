package local.werewolf.probe

import android.content.res.Configuration
import android.os.Bundle
import android.os.LocaleList
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.animation.AnimatedContent
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModelProvider
import androidx.core.view.WindowCompat
import java.util.Locale
import kotlin.math.cos
import kotlin.math.sin
import kotlinx.coroutines.launch
import org.json.JSONObject

class GameActivity : ComponentActivity() {
    private lateinit var model: GameModel
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        model = ViewModelProvider(this)[GameModel::class.java]
        setContent {
            val context = LocalContext.current
            val platformConfiguration = LocalConfiguration.current
            val localized = remember(context, model.locale, platformConfiguration) {
                context.createConfigurationContext(Configuration(platformConfiguration).apply {
                    setLocales(LocaleList(Locale.forLanguageTag(model.locale)))
                    // Debug-only rendering checks affect this Activity, never device settings.
                    if (BuildConfig.DEBUG && intent.hasExtra("preview_light")) {
                        uiMode = (uiMode and Configuration.UI_MODE_NIGHT_MASK.inv()) or
                            if (intent.getBooleanExtra("preview_light", false)) Configuration.UI_MODE_NIGHT_NO else Configuration.UI_MODE_NIGHT_YES
                    }
                })
            }
            val density = LocalDensity.current
            val scale = if (BuildConfig.DEBUG) intent.getFloatExtra("preview_scale", density.fontScale).coerceIn(.8f, 2f) else density.fontScale
            CompositionLocalProvider(LocalContext provides localized,
                LocalConfiguration provides localized.resources.configuration,
                LocalResources provides localized.resources,
                LocalDensity provides Density(density.density, scale)) {
                val dark = isSystemInDarkTheme()
                SideEffect {
                    WindowCompat.getInsetsController(window, window.decorView).apply {
                        isAppearanceLightStatusBars = !dark
                        isAppearanceLightNavigationBars = !dark
                    }
                }
                NightTheme { GameApp(model) }
            }
        }
    }
    override fun onStart() { super.onStart(); if (::model.isInitialized) model.foreground(true) }
    override fun onStop() {
        if (::model.isInitialized && !isChangingConfigurations) model.foreground(false)
        super.onStop()
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable private fun GameApp(model: GameModel) {
    var actions by rememberSaveable { mutableStateOf(false) }
    var privateInfo by rememberSaveable { mutableStateOf(false) }
    var seat by remember { mutableStateOf<JSONObject?>(null) }
    val state = model.state
    val pending = state.optJSONObject("pending")
    BackHandler(model.playing && !actions && !privateInfo && seat == null) { model.leave() }
    Scaffold(topBar = {
        TopAppBar(title = { Text(stringResource(R.string.app_name), style = MaterialTheme.typography.titleSmall) },
            colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background), actions = {
            if (model.playing) TextButton(onClick = model::leave, enabled = !model.busy) {
                Text(stringResource(R.string.pause))
            }
        })
    }, bottomBar = {
        if (model.playing) Surface(color = MaterialTheme.colorScheme.surface) {
            Column(Modifier.navigationBarsPadding().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (model.failed || state.optString("status") == "error") {
                    Text(stringResource(R.string.error), color = MaterialTheme.colorScheme.error)
                    Button(onClick = { model.open(resume = true) }, enabled = !model.busy) { Text(stringResource(R.string.retry)) }
                } else if (state.optBoolean("finished")) {
                    Text(stringResource(when (state.optJSONObject("table")?.optString("winner")) {
                        "wolf" -> R.string.wolf_win; "god" -> R.string.good_win; else -> R.string.draw
                    }), style = MaterialTheme.typography.titleLarge)
                    Button(onClick = model::leave, modifier = Modifier.fillMaxWidth(), enabled = !model.busy) { Text(stringResource(R.string.home)) }
                } else if (pending != null) {
                    Button(onClick = { actions = true }, modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp), enabled = !model.busy) {
                        Text(promptTitle(pending))
                    }
                } else {
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                        Text(stringResource(R.string.waiting), style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
        }
    }) { insets ->
        AnimatedContent(model.playing, modifier = Modifier.padding(insets), label = "lobby-table") { playing ->
            if (!playing) Lobby(model) else TableScreen(model, { privateInfo = true }, { seat = it })
        }
    }
    if (actions && pending != null) {
        ModalBottomSheet(onDismissRequest = { actions = false }, containerColor = MaterialTheme.colorScheme.surface,
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
            ChoiceSheet(pending, !model.busy) { id ->
                actions = false
                model.choose(id, pending.getString("request_id"))
            }
        }
    }
    if (privateInfo) {
        val own = state.optJSONObject("private") ?: JSONObject()
        AlertDialog(onDismissRequest = { privateInfo = false }, title = { Text(stringResource(R.string.private_role)) },
            text = { SelectionContainer { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(own.optString("role_cn"), style = MaterialTheme.typography.titleLarge)
                Text(own.optString("ability"))
                if (own.optBoolean("is_wolf")) {
                    val mates = own.optJSONArray("wolfmates")
                    Text(stringResource(R.string.wolf_team, (0 until (mates?.length() ?: 0)).joinToString(", ") { mates!!.optInt(it).toString() }))
                }
                Text(stringResource(R.string.classic), style = MaterialTheme.typography.titleMedium)
                Text(stringResource(R.string.local_note))
            } } }, confirmButton = { TextButton(onClick = { privateInfo = false }) { Text(stringResource(R.string.close)) } })
    }
    seat?.let { person ->
        val pos = person.optInt("pos")
        val rows = state.optJSONArray("events").objects().filter { it.optInt("seat") == pos }
        AlertDialog(onDismissRequest = { seat = null }, title = { Text(stringResource(R.string.seat, pos, person.optString("name"))) },
            text = { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(stringResource(if (person.optBoolean("alive")) R.string.alive else R.string.dead))
                Text(stringResource(R.string.unknown_role), color = MaterialTheme.colorScheme.onSurfaceVariant)
                rows.forEach { SelectionContainer { Text(it.optString("text")) } }
            } }, confirmButton = { TextButton(onClick = { seat = null }) { Text(stringResource(R.string.close)) } })
    }
}

@Composable private fun Lobby(model: GameModel) {
    var role by rememberSaveable { mutableStateOf("random") }
    var character by rememberSaveable { mutableStateOf("random") }
    var replace by rememberSaveable { mutableStateOf(false) }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp), verticalArrangement = Arrangement.spacedBy(20.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(selected = model.locale == "zh-CN", onClick = { model.language("zh-CN") }, label = { Text(stringResource(R.string.language_zh)) })
            FilterChip(selected = model.locale == "en", onClick = { model.language("en") }, label = { Text(stringResource(R.string.language_en)) })
        }
        Text(stringResource(R.string.welcome), style = MaterialTheme.typography.headlineLarge)
        Text(stringResource(R.string.welcome_body), style = MaterialTheme.typography.bodyLarge)
        Text(stringResource(R.string.offline), color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.titleSmall)
        HorizontalDivider()
        Text(stringResource(R.string.classic), style = MaterialTheme.typography.titleLarge)
        Selector(stringResource(R.string.role), role, model.catalog.optJSONArray("roles").objects()) { role = it }
        Selector(stringResource(R.string.character), character, model.catalog.optJSONArray("characters").objects()) { character = it }
        model.catalog.optJSONArray("characters").objects().firstOrNull { it.optString("id") == character }?.let {
            Text(it.optString("description"), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (model.failed) Text(stringResource(R.string.error), color = MaterialTheme.colorScheme.error)
        if (model.state.optBoolean("saved")) OutlinedButton(onClick = { model.open(resume = true) }, enabled = !model.busy, modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp)) { Text(stringResource(R.string.resume)) }
        Button(onClick = { if (model.state.optBoolean("saved")) replace = true else model.open(role, character) },
            enabled = !model.busy, modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp)) {
            Text(stringResource(if (model.busy) R.string.working else R.string.start))
        }
        Text(stringResource(R.string.local_note), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(stringResource(R.string.saved), style = MaterialTheme.typography.bodySmall)
        Spacer(Modifier.height(24.dp))
    }
    if (replace) AlertDialog(onDismissRequest = { replace = false }, title = { Text(stringResource(R.string.replace)) },
        text = { Text(stringResource(R.string.replace_body)) }, confirmButton = {
            TextButton(onClick = { replace = false; model.open(role, character) }) { Text(stringResource(R.string.confirm)) }
        }, dismissButton = { TextButton(onClick = { replace = false }) { Text(stringResource(R.string.cancel)) } })
}

@Composable private fun Selector(label: String, value: String, options: List<JSONObject>, choose: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(label, style = MaterialTheme.typography.labelLarge)
        OutlinedButton(onClick = { expanded = true }, modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp),
            shape = MaterialTheme.shapes.medium,
            colors = ButtonDefaults.outlinedButtonColors(containerColor = MaterialTheme.colorScheme.surface, contentColor = MaterialTheme.colorScheme.onSurface)) {
            Text(options.firstOrNull { it.optString("id") == value }?.optString("name") ?: stringResource(R.string.random),
                modifier = Modifier.weight(1f), textAlign = TextAlign.Start)
            Icon(painterResource(R.drawable.ic_expand), contentDescription = null, modifier = Modifier.size(24.dp))
        }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }, modifier = Modifier.heightIn(max = 360.dp)) {
            DropdownMenuItem(text = { Text(stringResource(R.string.random)) }, onClick = { choose("random"); expanded = false })
            options.forEach { option -> DropdownMenuItem(text = { Text(option.optString("name")) }, onClick = { choose(option.getString("id")); expanded = false }) }
        }
    }
}

@Composable private fun TableScreen(model: GameModel, rules: () -> Unit, person: (JSONObject) -> Unit) {
    val state = model.state
    val table = state.optJSONObject("table") ?: JSONObject()
    val all = state.optJSONArray("events").objects()
    var earlier by rememberSaveable { mutableStateOf(false) }
    val rows = if (earlier) all else all.takeLast(50)
    val list = rememberLazyListState()
    val scope = rememberCoroutineScope()
    LazyColumn(state = list, modifier = Modifier.fillMaxSize(), contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item(key = "context") {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.round, table.optInt("day"), table.optInt("night")), style = MaterialTheme.typography.titleMedium)
                TextButton(onClick = rules) { Text(stringResource(R.string.rules)) }
            }
            Text(stringResource(R.string.offline), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            state.optJSONObject("private")?.let { own ->
                Surface(shape = MaterialTheme.shapes.small, color = MaterialTheme.colorScheme.secondaryContainer,
                    modifier = Modifier.padding(top = 8.dp)) {
                    Text(stringResource(R.string.private_role) + " · " + own.optInt("pos") + " · " + own.optString("role_cn"),
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp),
                        style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSecondaryContainer)
                }
            }
        }
        item(key = "table") { RoundTable(table, all.lastOrNull { it.optString("type") == "speech" }?.optInt("seat") ?: 0, person) }
        item(key = "history") {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.discussion), style = MaterialTheme.typography.titleLarge)
                TextButton(onClick = { scope.launch { list.animateScrollToItem((list.layoutInfo.totalItemsCount - 1).coerceAtLeast(0)) } }) { Text(stringResource(R.string.latest)) }
            }
            if (!earlier && all.size > 50) TextButton(onClick = { earlier = true }) { Text(stringResource(R.string.load_more, all.size - 50)) }
        }
        items(rows, key = { "event-${it.optInt("event_no")}" }) { event ->
            val private = event.optString("type") == "private"
            Column(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(when {
                    private -> stringResource(R.string.private_event)
                    event.optInt("seat") > 0 -> stringResource(R.string.seat, event.optInt("seat"), event.optString("name"))
                    else -> stringResource(R.string.host)
                }, color = if (private) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelLarge)
                SelectionContainer { Text(event.optString("text"), style = MaterialTheme.typography.bodyLarge) }
            }
        }
        item { Spacer(Modifier.height(12.dp)) }
    }
}

@Composable private fun RoundTable(table: JSONObject, speaker: Int, onSeat: (JSONObject) -> Unit) {
    val seats = table.optJSONArray("seats").objects()
    BoxWithConstraints(Modifier.fillMaxWidth().heightIn(min = 320.dp), contentAlignment = Alignment.Center) {
        val size = maxWidth.coerceAtMost(400.dp)
        Box(Modifier.size(size), contentAlignment = Alignment.Center) {
            Surface(Modifier.size(size * .58f), shape = CircleShape, color = MaterialTheme.colorScheme.surfaceContainer) {
                Column(Modifier.padding(30.dp), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(stringResource(R.string.host), style = MaterialTheme.typography.titleMedium)
                    Text(phaseLabel(table.optString("phase")), style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center)
                }
            }
            seats.forEach { seat ->
                val pos = seat.optInt("pos")
                val theta = (pos - 1) * Math.PI / 6 - Math.PI / 2
                val radius = size / 2 - 30.dp
                val desc = stringResource(R.string.seat, pos, seat.optString("name")) + ", " + stringResource(if (seat.optBoolean("alive")) R.string.alive else R.string.dead) +
                    if (seat.optBoolean("is_player")) ", " + stringResource(R.string.you) else ""
                Column(Modifier.offset(x = radius * cos(theta).toFloat(), y = radius * sin(theta).toFloat())
                    .width(56.dp).semantics(mergeDescendants = true) { contentDescription = desc }
                    .clip(MaterialTheme.shapes.small).clickable { onSeat(seat) }.padding(vertical = 4.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Surface(shape = CircleShape, color = if (pos == speaker) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface,
                        border = BorderStroke(if (seat.optBoolean("is_player")) 2.dp else 1.dp,
                            if (seat.optBoolean("is_player")) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outline), modifier = Modifier.size(48.dp)) {
                        Box(contentAlignment = Alignment.Center) {
                            Text(pos.toString(), style = MaterialTheme.typography.labelLarge,
                                color = if (seat.optBoolean("alive")) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                    Text(if (seat.optBoolean("is_player")) stringResource(R.string.you) else if (!seat.optBoolean("alive")) stringResource(R.string.dead) else seat.optString("name"),
                        style = MaterialTheme.typography.labelSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        }
    }
}

@Composable private fun actionTitle(kind: String): String = stringResource(when (kind) {
    "ready" -> R.string.ready; "night" -> R.string.night; "speech" -> R.string.speech
    "table_answer" -> R.string.table_answer; "table_reply" -> R.string.table_reply
    "election_up" -> R.string.election_up; "election_withdraw" -> R.string.election_withdraw
    "vote" -> R.string.vote; "day_skill" -> R.string.day_skill; else -> R.string.choose
})

@Composable private fun phaseLabel(phase: String): String = stringResource(when (phase) {
    "night", "dawn" -> R.string.phase_night; "day" -> R.string.phase_day
    "election" -> R.string.phase_election; "vote" -> R.string.phase_vote; else -> R.string.phase_prep
})

@Composable private fun promptTitle(pending: JSONObject): String {
    val data = pending.optJSONObject("data") ?: JSONObject()
    return when {
        pending.optString("kind") == "night" && data.optString("role").isNotBlank() -> data.getString("role")
        pending.optString("kind") == "vote" -> stringResource(if (data.optBoolean("sheriff")) R.string.vote_sheriff else R.string.vote_exile)
        data.optBoolean("last_words") -> stringResource(R.string.last_words)
        data.optBoolean("final_reply") -> stringResource(R.string.final_reply)
        else -> actionTitle(pending.optString("kind"))
    }
}

@Composable private fun ChoiceSheet(pending: JSONObject, enabled: Boolean, choose: (String) -> Unit) {
    val choices = pending.optJSONArray("choices").objects()
    var more by remember(pending.optString("request_id")) { mutableStateOf(false) }
    var approach by remember(pending.optString("request_id")) { mutableStateOf<String?>(null) }
    val approaches = listOf("pressure", "protect", "probe", "reveal", "discuss", "hold")
        .filter { goal -> choices.any { it.optString("approach") == goal } }
    val hasSuggestions = choices.any { it.optBoolean("suggested") }
    val visible = if (approach != null) choices.filter { it.optString("approach") == approach }
        else if (!more && hasSuggestions) choices.filter { it.optBoolean("suggested") } else choices
    LazyColumn(Modifier.fillMaxWidth().fillMaxHeight(.8f), contentPadding = PaddingValues(24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Text(promptTitle(pending), style = MaterialTheme.typography.headlineSmall)
            val data = pending.optJSONObject("data") ?: JSONObject()
            for (key in listOf("phase", "desc")) {
                val text = data.optString(key)
                if (text.isNotBlank()) Text(text, style = MaterialTheme.typography.bodyLarge)
            }
            val from = data.optString("from")
            if (from.isNotEmpty()) Text(from, color = MaterialTheme.colorScheme.primary)
            data.optJSONArray("questions").objects().forEach { question ->
                if (question.optString("text").isNotBlank()) {
                    Text(question.optString("from") + ": " + question.optString("text"), style = MaterialTheme.typography.bodyLarge)
                }
            }
        }
        if (approaches.isNotEmpty()) {
            item {
                Text(stringResource(R.string.strategy_prompt), style = MaterialTheme.typography.titleMedium)
                Text(stringResource(R.string.strategy_note), style = MaterialTheme.typography.bodyMedium)
            }
            item {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    approaches.chunked(2).forEach { pair ->
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            pair.forEach { goal ->
                                FilterChip(selected = approach == goal, onClick = { approach = if (approach == goal) null else goal },
                                    modifier = Modifier.weight(1f).heightIn(min = 48.dp),
                                    label = { Text(approachLabel(goal)) })
                            }
                        }
                    }
                }
            }
            if (approach != null) item {
                Text(visible.firstOrNull()?.optString("consequence").orEmpty(), style = MaterialTheme.typography.bodyMedium)
            }
        }
        if (approach == null && hasSuggestions && !more) item {
            Text(stringResource(R.string.suggested), style = MaterialTheme.typography.titleSmall)
        }
        items(visible, key = { it.getString("id") }) { option ->
            OutlinedButton(onClick = { choose(option.getString("id")) }, enabled = enabled,
                modifier = Modifier.fillMaxWidth().heightIn(min = 52.dp), shape = MaterialTheme.shapes.medium,
                colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.onSurface),
                contentPadding = PaddingValues(16.dp)) {
                Text(option.getString("label"), modifier = Modifier.fillMaxWidth(), style = MaterialTheme.typography.bodyLarge)
            }
        }
        if (approach == null && hasSuggestions && !more) item { TextButton(onClick = { more = true }) { Text(stringResource(R.string.all_choices)) } }
    }
}

@Composable private fun approachLabel(goal: String): String = stringResource(when (goal) {
    "pressure" -> R.string.approach_pressure; "protect" -> R.string.approach_protect
    "probe" -> R.string.approach_probe; "reveal" -> R.string.approach_reveal
    "discuss" -> R.string.approach_discuss; else -> R.string.approach_hold
})
