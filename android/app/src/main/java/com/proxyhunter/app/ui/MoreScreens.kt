package com.proxyhunter.app.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun GatewayScreen(stats: UiStats, countries: Map<String, Int>, modes: List<String>,
                  onAction: (String, Map<String, Any>) -> Unit) {
    var selected by remember { mutableStateOf("") }
    var mode by remember { mutableStateOf(stats.mode) }
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }

    Column(Modifier.fillMaxWidth()) {
        SurfaceCard("Gateway") {
            Text("${stats.status} · ${stats.endpoint}", color = if (stats.status == "ONLINE") Emerald else Danger)
            Text("Country: ${stats.country}   Mode: ${stats.mode}")
            Text("Eligible: ${stats.healthy}   Unique IPs: ${stats.uniqueIps}")
            Text("Active: ${stats.active}   OK: ${stats.success}   Failed: ${stats.failed}")
            Text("Current upstream: ${stats.currentIp}")
            Row(Modifier.padding(top = 8.dp)) {
                Button(onClick = { onAction("gateway_start", emptyMap()) }, Modifier.padding(end = 6.dp)) { Text("Start") }
                OutlinedButton(onClick = { onAction("gateway_stop", emptyMap()) }, Modifier.padding(end = 6.dp)) { Text("Stop") }
                OutlinedButton(onClick = { onAction("copy_endpoint", emptyMap()) }) { Text("Copy endpoint") }
            }
        }
        SurfaceCard("Country selection") {
            LazyColumn(Modifier.fillMaxWidth().padding(top = 6.dp)) {
                items(countries.entries.toList()) { (code, count) ->
                    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                        Text("${flag(code)} $code  ($count validated)", Modifier.weight(1f))
                        OutlinedButton(onClick = { selected = code }) { Text("Select") }
                    }
                }
            }
            Text("Selected: ${if (selected.isBlank()) "All" else selected}")
            Row {
                OutlinedButton(onClick = { selected = "" }) { Text("All countries") }
                Button(onClick = { onAction("gateway_countries", mapOf("countries" to selected.ifBlank { "all" })) }) {
                    Text("Apply")
                }
            }
        }
        SurfaceCard("Rotation") {
            modes.forEach { item ->
                OutlinedButton(onClick = { mode = item; onAction("gateway_mode", mapOf("mode" to item)) },
                    Modifier.padding(end = 4.dp)) { Text(item) }
            }
            Text("Active: $mode", style = MaterialTheme.typography.labelMedium)
        }
        SurfaceCard("Authentication (localhost needs none)") {
            TextField(value = username, onValueChange = { username = it }, label = { Text("Username") },
                modifier = Modifier.fillMaxWidth())
            TextField(value = password, onValueChange = { password = it }, label = { Text("Password") },
                modifier = Modifier.fillMaxWidth())
            Button(onClick = {
                onAction("gateway_auth", mapOf("username" to username, "password" to password))
            }) { Text("Save credentials (PBKDF2)") }
        }
    }
}

@Composable
fun DownloadsScreen(history: List<UiExport>, onAction: (String, Map<String, Any>) -> Unit) {
    Column(Modifier.fillMaxWidth()) {
        SurfaceCard("Export working proxies") {
            Row {
                Button(onClick = { onAction("export", mapOf("kind" to "all", "formats" to listOf("txt", "csv", "json"))) }) {
                    Text("Export all")
                }
                OutlinedButton(onClick = { onAction("export", mapOf("kind" to "protocol", "value" to "socks5")) }) {
                    Text("SOCKS5")
                }
            }
            Text("Files are written to Download/ProxyHunter/", style = MaterialTheme.typography.labelMedium)
        }
        SurfaceCard("Export history") {
            LazyColumn(Modifier.fillMaxWidth()) {
                items(history) { item ->
                    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                        Text("${item.name} · ${item.count} proxies · ${item.sizeBytes} bytes")
                        Text(item.timestamp, style = MaterialTheme.typography.labelMedium)
                    }
                }
            }
        }
    }
}

@Composable
fun SettingsScreen(dark: Boolean, onToggleTheme: () -> Unit) {
    Column(Modifier.fillMaxWidth()) {
        SurfaceCard("Appearance") {
            Button(onClick = onToggleTheme) { Text(if (dark) "Switch to light theme" else "Switch to dark theme") }
        }
        SurfaceCard("About") {
            Text("ProxyHunter v3.0 — Desktop & Mobile Edition")
            Text("Free public proxies are untrusted. Never send passwords, payment data or confidential information through them.")
            Text("Localhost gateway is the secure default. Remote access requires authentication, TLS and access controls.")
        }
    }
}
