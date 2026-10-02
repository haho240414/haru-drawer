package io.github.haho240414.harudrawer

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** 맥(파이썬 haru/crypto.py)이 만든 봉투를 폰이 똑같이 여는지 — 시험 벡터는 파이썬으로 만든 실제 값 */
class EnvelopeTest {
    private val key = "W1Jjqz3f823ZQVXpEBTAlEHyzdHP0qbawb2iYb_yJK8"
    private val topic = "haru-testvectortopic0000001"

    @Test
    fun opensPythonEnvelope() {
        val env = Envelope.unb64u("Ac76uuRVU-BeoFksaNgHSNJcgMMO3UGzqU0XTGQH-qxxi4bJc7UdlY0kONFJwITtUB8loUY")
        assertEquals("안녕 하루서랍 🗂", String(Envelope.open(key, topic, env), Charsets.UTF_8))
    }

    @Test
    fun opensPythonText() {
        val o = Envelope.openText(key, topic,
            "H1:AZ5c3inMXC1pnblYfI_vO8GJx3sgwXdFkJWMevI8Nmrf_u7Z0s2Ta6bXt4WMquAkjaY7YsepweQuduIa0uad33dlNwQWRQ")
        assertEquals("digest", o.getString("t"))
        assertEquals("2026-10-01", o.getString("day"))
        assertEquals(3, o.getInt("ver"))
    }

    @Test
    fun roundTripAndTamper() {
        val env = Envelope.seal(key, topic, "hello".toByteArray())
        assertEquals("hello", String(Envelope.open(key, topic, env)))
        var failed = false
        try { Envelope.open(key, "other-topic", env) } catch (_: Exception) { failed = true }
        assertTrue("다른 토픽에서는 열리면 안 됨", failed)
        val bad = env.copyOf().also { it[it.size - 1] = (it[it.size - 1].toInt() xor 1).toByte() }
        failed = false
        try { Envelope.open(key, topic, bad) } catch (_: Exception) { failed = true }
        assertTrue("변조되면 열리면 안 됨", failed)
        val t = Envelope.sealText(key, topic, JSONObject().put("t", "item").put("text", "가나다"))
        assertEquals("가나다", Envelope.openText(key, topic, t).getString("text"))
    }

    @Test
    fun parsesPairingCodeAndDeepLink() {
        val code = "HARU1.eyJ2IjoxLCJzIjoiaHR0cHM6Ly9udGZ5LnNoIiwidSI6ImhhcnUtdXAxMjMiLCJkIjoiaGFydS1kb3duNDU2IiwiayI6IlcxSmpxejNmODIzWlFWWHBFQlRBbEVIeXpkSFAwcWJhd2IyaVliX3lKSzgiLCJuIjoiXHViOWU1XHViZDgxIn0"
        for (raw in listOf(code, "haru://pair/$code", "  $code\n")) {
            val p = Pairing.parse(raw)
            assertEquals("https://ntfy.sh", p.server)
            assertEquals("haru-up123", p.up)
            assertEquals("haru-down456", p.down)
            assertEquals(key, p.key)
            assertEquals("맥북", p.name)
        }
    }
}
