package com.proxyhunter.app

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/** Local JSON bridge to the embedded Python backend (Chaquopy). */
object BridgeClient {
    private const val BASE = "http://127.0.0.1:8765"

    private fun request(path: String, method: String = "GET", body: String? = null): String {
        val connection = URL(BASE + path).openConnection() as HttpURLConnection
        connection.requestMethod = method
        connection.connectTimeout = 3000
        connection.readTimeout = 180_000
        if (body != null) {
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json")
            connection.outputStream.use { it.write(body.toByteArray()) }
        }
        return connection.inputStream.bufferedReader().use { it.readText() }
    }

    fun health(): JSONObject = try {
        JSONObject(request("/health"))
    } catch (e: Exception) {
        JSONObject().put("ok", false).put("error", e.message ?: "bridge unavailable")
    }

    fun healthy(): Boolean = health().optBoolean("ok", false)

    fun action(name: String, params: Map<String, Any> = emptyMap()): JSONObject {
        val json = JSONObject()
        params.forEach { (k, v) -> json.put(k, v) }
        return JSONObject(request("/api/$name", "POST", json.toString()))
    }

    fun stats(): JSONObject = action("stats")
    fun proxies(): JSONObject = action("proxies")
    fun countries(): JSONObject = action("countries")
    fun exports(dir: String): JSONObject = action("exports", mapOf("directory" to dir))
}
