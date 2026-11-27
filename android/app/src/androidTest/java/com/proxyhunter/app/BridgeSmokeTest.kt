package com.proxyhunter.app

import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Before
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Runs on a real Android device/emulator against the packaged APK. */
@RunWith(AndroidJUnit4::class)
class BridgeSmokeTest {

    @Before
    fun launchApp() {
        // MainActivity starts ProxyService, which boots the embedded backend.
        ActivityScenario.launch(MainActivity::class.java)
    }

    private fun waitUntil(timeoutMs: Long, predicate: () -> Boolean): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (predicate()) return true
            Thread.sleep(2000)
        }
        return false
    }

    @Test
    fun bridgeReadyDiscoveryValidationAndExport() {
        assertTrue("bridge never became ready", BridgeClient.waitForBridge(90_000))
        val health = BridgeClient.health()
        assertEquals("3.1.1", health.optString("version"))
        assertEquals("READY", health.optString("backend"))

        val start = BridgeClient.action("discover", mapOf("workers" to 10))
        assertTrue("discover did not start: $start", start.optBoolean("started"))
        assertTrue(
            "no proxies discovered",
            waitUntil(180_000) { BridgeClient.stats().optInt("discovered") > 0 }
        )
        val discovered = BridgeClient.stats().optInt("discovered")

        val check = BridgeClient.action("check", mapOf("limit" to 5))
        assertTrue("check did not start: $check", check.optBoolean("started"))
        assertTrue(
            "no proxies checked",
            waitUntil(180_000) { BridgeClient.stats().optInt("checked") > 0 }
        )

        val exported = BridgeClient.action(
            "export",
            mapOf("kind" to "all", "formats" to listOf("txt", "csv", "json")),
        )
        val files = exported.optJSONArray("files")
        assertTrue("export failed: $exported", (files?.length() ?: 0) >= 3)
        assertEquals("discovered=$discovered checked=${BridgeClient.stats().optInt("checked")}", true, discovered > 0)
    }
}
