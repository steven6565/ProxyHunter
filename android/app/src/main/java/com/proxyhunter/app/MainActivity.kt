package com.proxyhunter.app

import android.content.ClipData
import android.content.ClipboardManager
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Power
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import com.proxyhunter.app.ui.DownloadsScreen
import com.proxyhunter.app.ui.GatewayScreen
import com.proxyhunter.app.ui.HomeScreen
import com.proxyhunter.app.ui.ProxyHunterTheme
import com.proxyhunter.app.ui.ProxiesScreen
import com.proxyhunter.app.ui.UiExport
import com.proxyhunter.app.ui.UiProxy
import com.proxyhunter.app.ui.UiStats
import com.proxyhunter.app.ui.SettingsScreen

private val TABS = listOf("Home", "Proxies", "Gateway", "Downloads", "Settings")

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        ProxyService.start(this)
        setContent { ProxyHunterApp() }
    }

    @Composable
    fun ProxyHunterApp() {
        var dark by remember { mutableStateOf(true) }
        var tab by remember { mutableStateOf(0) }
        var stats by remember { mutableStateOf(UiStats()) }
        var proxies by remember { mutableStateOf<List<UiProxy>>(emptyList()) }
        var countries by remember { mutableStateOf<Map<String, Int>>(emptyMap()) }
        var history by remember { mutableStateOf<List<UiExport>>(emptyList()) }
        var message by remember { mutableStateOf("") }
        var showWorkerDialog by remember { mutableStateOf(false) }
        var selectedWorkers by remember { mutableStateOf(50) }
        var customWorkers by remember { mutableStateOf("50") }
        val scope = rememberCoroutineScope()
        val context = LocalContext.current

        fun show(result: JSONObject) {
            if (result.has("error")) {
                message = "Error: " + result.getString("error")
            } else {
                message = "Done"
            }
        }

        suspend fun refresh() = withContext(Dispatchers.IO) {
            val h = try { BridgeClient.health() } catch (ex: Exception) { JSONObject() }
            val s = try { BridgeClient.stats() } catch (ex: Exception) { JSONObject() }
            val p = try { BridgeClient.proxies() } catch (ex: Exception) { JSONObject() }
            val c = try { BridgeClient.countries() } catch (ex: Exception) { JSONObject() }
            val e = try { BridgeClient.exports("/sdcard/Download/ProxyHunter") } catch (ex: Exception) { JSONObject() }
            stats = parseStats(s, h)
            proxies = parseProxies(p)
            countries = parseCountries(c)
            history = parseExports(e)
        }

        androidx.compose.runtime.LaunchedEffect(Unit) {
            while (true) {
                refresh()
                delay(1500)
            }
        }

        fun action(name: String, params: Map<String, Any> = emptyMap()) {
            scope.launch {
                try {
                    show(withContext(Dispatchers.IO) { BridgeClient.action(name, params) })
                } catch (e: Exception) {
                    message = "Bridge error: ${e.message ?: "unknown"}"
                }
                refresh()
            }
        }

        fun copy(text: String) {
            val manager = context.getSystemService(ClipboardManager::class.java)
            manager.setPrimaryClip(ClipData.newPlainText("ProxyHunter", text))
            Toast.makeText(context, "Copied $text", Toast.LENGTH_SHORT).show()
        }

        ProxyHunterTheme(dark = dark) {
            Scaffold(
                bottomBar = {
                    NavigationBar {
                        TABS.forEachIndexed { index, label ->
                            NavigationBarItem(
                                selected = tab == index,
                                onClick = { tab = index },
                                icon = {
                                    Icon(
                                        when (index) {
                                            0 -> Icons.Filled.Home
                                            1 -> Icons.Filled.List
                                            2 -> Icons.Filled.Power
                                            3 -> Icons.Filled.Download
                                            else -> Icons.Filled.Settings
                                        }, contentDescription = label
                                    )
                                },
                                label = { Text(label) },
                            )
                        }
                    }
                }
            ) { padding ->
                Box(Modifier.fillMaxSize().padding(padding)) {
                    when (tab) {
                        0 -> HomeScreen(stats, { name -> action(name) }) { showWorkerDialog = true }
                        1 -> ProxiesScreen(proxies) { copy(it) }
                        2 -> GatewayScreen(stats, countries,
                            listOf("per_connection", "round_robin", "random", "time_based", "sticky", "lowest_latency")) { name, params ->
                            if (name == "copy_endpoint") copy(stats.endpoint) else action(name, params)
                        }
                        3 -> DownloadsScreen(history) { name, params -> action(name, params) }
                        4 -> SettingsScreen(dark) { dark = !dark }
                    }
                    if (message.isNotBlank()) {
                        Toast.makeText(context, message, Toast.LENGTH_SHORT).show()
                        message = ""
                    }
                }
            }
            if (showWorkerDialog) {
                AlertDialog(
                    onDismissRequest = { showWorkerDialog = false },
                    title = { Text("Find Proxies — workers") },
                    text = {
                        Column {
                            Text("Choose concurrency (subject to safe device limits).")
                            listOf(10, 50, 100, 200, 500, 0).forEach { option ->
                                Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                                    RadioButton(
                                        selected = selectedWorkers == option,
                                        onClick = { selectedWorkers = option },
                                    )
                                    Text(if (option == 0) "Custom" else option.toString())
                                }
                            }
                            if (selectedWorkers == 0) {
                                TextField(
                                    value = customWorkers,
                                    onValueChange = { customWorkers = it },
                                    label = { Text("Custom workers") },
                                    modifier = Modifier.fillMaxWidth(),
                                )
                            }
                        }
                    },
                    confirmButton = {
                        TextButton(onClick = {
                            val count = if (selectedWorkers == 0)
                                customWorkers.toIntOrNull() ?: 50 else selectedWorkers
                            selectedWorkers = count
                            showWorkerDialog = false
                            action("discover", mapOf("workers" to count))
                        }) { Text("Start Discovery") }
                    },
                    dismissButton = { TextButton(onClick = { showWorkerDialog = false }) { Text("Cancel") } },
                )
            }
        }
    }

    private fun parseStats(json: JSONObject, health: JSONObject): UiStats = UiStats(
        status = json.optString("status", "OFFLINE"),
        backend = health.optString("backend", if (health.optBoolean("ok", false)) "READY" else "OFFLINE"),
        internet = health.optString("internet", "OFFLINE"),
        gateway = json.optString("gateway", health.optString("gateway", "OFFLINE")),
        backendError = health.optString("error", ""),
        endpoint = json.optString("endpoint", "http://127.0.0.1:8080"),
        country = json.optString("country", "all"),
        mode = json.optString("mode", "per_connection"),
        discovered = json.optInt("discovered"),
        working = json.optInt("working"),
        uniqueIps = json.optInt("unique_ips"),
        healthy = json.optInt("healthy"),
        checked = json.optInt("checked"),
        speed = json.optDouble("speed", 0.0).toFloat(),
        workers = json.optInt("active_workers"),
        latency = json.optDouble("latency", 0.0).toFloat(),
        currentIp = json.optString("current_ip", "-"),
        active = json.optInt("active"),
        success = json.optInt("success"),
        failed = json.optInt("requests_failed"),
        uptime = json.optString("uptime", "00:00:00"),
        operation = json.optString("operation", "idle"),
        progress = json.optDouble("progress", 0.0).toFloat(),
        lastRefresh = json.optString("last_refresh", "never"),
        cpu = if (json.isNull("cpu")) null else json.optDouble("cpu").toFloat(),
        ram = if (json.isNull("ram")) null else json.optDouble("ram").toFloat(),
    )

    private fun parseProxies(json: JSONObject): List<UiProxy> {
        val array = json.optJSONArray("proxies") ?: return emptyList()
        return (0 until array.length()).map { i ->
            val o = array.getJSONObject(i)
            UiProxy(
                o.optString("address"), o.optString("protocol"), o.optString("country_code"),
                o.optString("country"), o.optDouble("response_time_ms", 0.0),
                o.optBoolean("working", true), o.optString("last_checked"),
            )
        }
    }

    private fun parseCountries(json: JSONObject): Map<String, Int> {
        val obj = json.optJSONObject("countries") ?: return emptyMap()
        val names = obj.names() ?: return emptyMap()
        return (0 until names.length()).associate { i ->
            val key = names.getString(i)
            key to obj.getInt(key)
        }
    }

    private fun parseExports(json: JSONObject): List<UiExport> {
        val array = json.optJSONArray("files") ?: return emptyList()
        return (0 until array.length()).map { i ->
            val o = array.getJSONObject(i)
            UiExport(o.optString("name"), o.optInt("count"), o.optLong("size_bytes"), o.optString("timestamp"))
        }
    }
}
