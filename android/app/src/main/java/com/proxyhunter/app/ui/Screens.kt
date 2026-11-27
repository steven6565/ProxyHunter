package com.proxyhunter.app.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

data class UiStats(
    val status: String = "OFFLINE",
    val backend: String = "OFFLINE",
    val internet: String = "OFFLINE",
    val gateway: String = "OFFLINE",
    val backendError: String = "",
    val endpoint: String = "http://127.0.0.1:8080",
    val country: String = "ALL",
    val mode: String = "per_connection",
    val discovered: Int = 0,
    val working: Int = 0,
    val uniqueIps: Int = 0,
    val healthy: Int = 0,
    val checked: Int = 0,
    val speed: Float = 0f,
    val workers: Int = 0,
    val latency: Float = 0f,
    val currentIp: String = "-",
    val active: Int = 0,
    val success: Int = 0,
    val failed: Int = 0,
    val uptime: String = "00:00:00",
    val operation: String = "idle",
    val progress: Float = 0f,
    val lastRefresh: String = "never",
    val cpu: Float? = null,
    val ram: Float? = null,
)

data class UiProxy(
    val address: String, val protocol: String, val countryCode: String,
    val country: String, val latency: Double, val healthy: Boolean,
    val lastChecked: String,
)

data class UiExport(val name: String, val count: Int, val sizeBytes: Long, val timestamp: String)

@Composable
fun HomeScreen(stats: UiStats, onAction: (String) -> Unit, onFindProxies: () -> Unit) {
    Column(modifier = Modifier.fillMaxWidth()) {
        SurfaceCard("Live status") {
            Text("Local gateway ${stats.gateway}", fontWeight = FontWeight.SemiBold,
                color = if (stats.gateway == "ONLINE") Emerald else Danger)
            Text("Internet ${stats.internet}   Backend ${stats.backend}   App ${stats.status}")
            Text("Country: ${stats.country}   Rotation: ${stats.mode}")
            Text("Operation: ${stats.operation}   Uptime: ${stats.uptime}")
            if (stats.backendError.isNotBlank()) {
                Text(stats.backendError.take(160), color = Danger, style = MaterialTheme.typography.labelMedium)
            }
            LinearProgressIndicator(progress = { stats.progress.coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
        }
        SurfaceCard("Capacity (actual verified data)") {
            Row(modifier = Modifier.fillMaxWidth()) {
                MetricTile("Discovered", stats.discovered.toString())
                MetricTile("Validated", stats.working.toString())
                MetricTile("Unique IPs", stats.uniqueIps.toString())
            }
            Row(modifier = Modifier.fillMaxWidth()) {
                MetricTile("Checked", stats.checked.toString())
                MetricTile("Speed/s", String.format("%.1f", stats.speed))
                MetricTile("Latency", "${stats.latency.toInt()} ms")
            }
            Row(modifier = Modifier.fillMaxWidth()) {
                MetricTile("Workers", stats.workers.toString(), good = false)
                MetricTile("Active", stats.active.toString(), good = false)
                MetricTile("Refresh", stats.lastRefresh, good = false)
            }
            Text("CPU ${stats.cpu?.let { "${it.toInt()}%" } ?: "n/a"} · RAM ${stats.ram?.let { "${it.toInt()}%" } ?: "n/a"}",
                style = MaterialTheme.typography.labelMedium)
        }
        SurfaceCard("Controls") {
            Row(modifier = Modifier.fillMaxWidth()) {
                Button(onClick = onFindProxies, Modifier.weight(1f).padding(end = 4.dp)) { Text("Find Proxies") }
                OutlinedButton(onClick = { onAction("check") }, Modifier.weight(1f).padding(start = 4.dp)) { Text("Check") }
            }
            Row(modifier = Modifier.fillMaxWidth().padding(top = 6.dp)) {
                OutlinedButton(onClick = { onAction("refresh") }, Modifier.weight(1f).padding(end = 4.dp)) { Text("Refresh") }
                OutlinedButton(onClick = { onAction("stop") }, Modifier.weight(1f).padding(start = 4.dp)) { Text("Stop") }
            }
        }
    }
}

@Composable
fun ProxiesScreen(proxies: List<UiProxy>, onCopy: (String) -> Unit) {
    var query by remember { mutableStateOf("") }
    var protocol by remember { mutableStateOf("all") }
    Column(Modifier.fillMaxWidth()) {
        TextField(value = query, onValueChange = { query = it }, label = { Text("Search IP / country") },
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp))
        Row(Modifier.padding(horizontal = 16.dp)) {
            listOf("all", "http", "https", "socks4", "socks5").forEach { item ->
                OutlinedButton(onClick = { protocol = item }, Modifier.padding(end = 4.dp)) { Text(item) }
            }
        }
        val filtered = proxies.filter {
            (protocol == "all" || it.protocol == protocol) &&
                (query.isBlank() || it.address.contains(query, true) || it.country.contains(query, true))
        }
        LazyColumn(Modifier.fillMaxWidth()) {
            items(filtered) { p ->
                SurfaceCard {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("${p.address}  ${flag(p.countryCode)} ${p.country}",
                                fontWeight = FontWeight.SemiBold)
                            Text("${p.protocol.uppercase()} · ${p.latency.toInt()} ms · ${p.lastChecked}",
                                style = MaterialTheme.typography.labelMedium)
                            Text(if (p.healthy) "HEALTHY" else "UNAVAILABLE",
                                color = if (p.healthy) Emerald else Danger)
                        }
                        OutlinedButton(onClick = { onCopy(p.address) }) { Text("Copy") }
                    }
                }
            }
        }
    }
}

fun flag(code: String): String {
    if (code.length != 2 || !code[0].isLetter() || !code[1].isLetter()) return ""
    // Unicode regional indicators produce the country flag without assets.
    val base = 0x1F1E6
    return String(Character.toChars(base + code[0].uppercaseChar().code - 'A'.code)) +
        String(Character.toChars(base + code[1].uppercaseChar().code - 'A'.code))
}
