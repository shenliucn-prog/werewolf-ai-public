package local.werewolf.probe

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File
import java.util.concurrent.Executors
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

fun JSONArray?.objects(): List<JSONObject> = if (this == null) emptyList() else
    (0 until length()).mapNotNull { optJSONObject(it) }

/** One serial command channel, independent of Activity recreation. */
class GameModel(application: Application) : AndroidViewModel(application) {
    private val io = Executors.newSingleThreadExecutor().asCoroutineDispatcher()
    private val prefs = application.getSharedPreferences("mobile-ui", 0)
    private val directory = File(application.filesDir, "play").absolutePath
    var locale by mutableStateOf(prefs.getString("locale", "zh-CN") ?: "zh-CN")
        private set
    var state by mutableStateOf(JSONObject())
        private set
    var catalog by mutableStateOf(JSONObject())
        private set
    var playing by mutableStateOf(false)
        private set
    var busy by mutableStateOf(true)
        private set
    var failed by mutableStateOf(false)
        private set
    private var foreground = false

    init {
        viewModelScope.launch {
            try {
                catalog = call("catalog", JSONObject().put("locale", locale))
                state = call("poll")
            } catch (_: Exception) { failed = true }
            busy = false
            while (true) {
                if (foreground && !busy) {
                    try { state = call("poll") } catch (_: Exception) { failed = true }
                }
                delay(300)
            }
        }
    }

    private suspend fun call(operation: String, args: JSONObject = JSONObject()): JSONObject = withContext(io) {
        if (!Python.isStarted()) Python.start(AndroidPlatform(getApplication()))
        JSONObject(Python.getInstance().getModule("mobile")
            .callAttr("command", directory, operation, args.toString()).toString())
    }

    fun language(value: String) {
        if (playing || busy) return
        locale = value
        prefs.edit().putString("locale", value).apply()
        viewModelScope.launch { catalog = call("catalog", JSONObject().put("locale", value)) }
    }

    fun open(role: String = "random", character: String = "random", resume: Boolean = false) {
        if (busy) return
        busy = true
        failed = false
        viewModelScope.launch {
            try {
                state = call(if (resume) "resume" else "start", JSONObject()
                    .put("role", role).put("character", character).put("locale", locale).put("replace", true))
                locale = state.optString("locale", locale)
                playing = true
                if (!foreground) state = call("pause")
            } catch (_: Exception) { failed = true }
            busy = false
        }
    }

    fun choose(id: String, requestId: String) {
        if (busy) return
        busy = true
        viewModelScope.launch {
            try {
                val accepted = call("choose", JSONObject().put("choice_id", id).put("request_id", requestId))
                state = call("poll")
                if (!accepted.optBoolean("accepted")) failed = true
            } catch (_: Exception) { failed = true }
            busy = false
        }
    }

    fun leave() {
        if (busy) return
        busy = true
        viewModelScope.launch {
            try {
                state = call("pause")
                playing = false
            } catch (_: Exception) { failed = true }
            busy = false
        }
    }

    fun foreground(value: Boolean) {
        if (foreground == value) return
        foreground = value
        if (!playing) return
        busy = true
        viewModelScope.launch {
            try {
                state = call(if (value) "resume" else "pause")
            } catch (_: Exception) { failed = true }
            busy = false
        }
    }
}
