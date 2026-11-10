package local.werewolf.probe

import android.app.Activity
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File

/** Debug test harness. Its files are isolated from the player's saved match. */
class ProbeActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val mode = intent.getStringExtra("mode") ?: "complete"
        val start = SystemClock.elapsedRealtime()
        Thread {
            try {
                if (!Python.isStarted()) Python.start(AndroidPlatform(applicationContext))
                val loaded = SystemClock.elapsedRealtime()
                val result = Python.getInstance().getModule("probe")
                    .callAttr("run", filesDir.absolutePath, mode).toString()
                File(filesDir, "result.json").writeText(result)
                Log.i("WerewolfProbe", "startup_ms=${loaded - start} total_ms=${SystemClock.elapsedRealtime() - start} result=$result")
            } catch (error: Exception) {
                Log.e("WerewolfProbe", "Probe failed", error)
                File(filesDir, "failure.txt").writeText(error.stackTraceToString())
            } finally {
                runOnUiThread { finish() }
            }
        }.start()
    }
}
