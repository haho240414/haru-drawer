package io.github.haho240414.harudrawer

import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * ntfy 중계 (맥의 haru/relay.py 와 같은 규칙). up = 폰→맥, down = 맥→폰.
 * ntfy.sh: 글 메시지 4,096바이트(넘으면 첨부), 첨부 15MB·3시간, 메시지 12시간 보관.
 */
class Relay(server: String, val up: String, val down: String, private val key: String) {
    val server: String = server.trimEnd('/')

    class Incoming(val id: String, val time: Long, var obj: JSONObject, val attUrl: String?, val attExpires: Long)

    companion object {
        const val MAX_TEXT = 3800
    }

    private fun open(url: String, method: String, timeoutMs: Int = 30_000): HttpURLConnection {
        val c = URL(url).openConnection() as HttpURLConnection
        c.requestMethod = method
        c.connectTimeout = 20_000
        c.readTimeout = timeoutMs
        c.setRequestProperty("User-Agent", "haru-drawer-android/1")
        return c
    }

    private fun readAll(c: HttpURLConnection): ByteArray {
        val code = c.responseCode
        val s = if (code in 200..299) c.inputStream else (c.errorStream ?: throw IOException("HTTP $code"))
        val out = ByteArrayOutputStream()
        s.use { it.copyTo(out) }
        if (code !in 200..299) throw IOException("HTTP $code ${String(out.toByteArray()).take(120)}")
        return out.toByteArray()
    }

    /** 보내기. 결과: ntfy 메시지 id */
    fun publish(topic: String, obj0: JSONObject, attachment0: ByteArray? = null, filename: String = "h.bin"): String {
        var obj = obj0
        var attachment = attachment0
        if (attachment == null) {
            val body = Envelope.sealText(key, topic, obj)
            if (body.length <= MAX_TEXT) {
                val c = open("$server/$topic", "POST")
                c.doOutput = true
                c.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
                return JSONObject(String(readAll(c))).optString("id")
            }
            // 길면 내용 전체를 첨부로
            attachment = obj.toString().toByteArray(Charsets.UTF_8)
            obj = JSONObject().put("t", obj.optString("t")).put("big", true)
        }
        val env = Envelope.seal(key, topic, attachment)
        val head = Envelope.sealText(key, topic, obj)
        val c = open("$server/$topic", "PUT", 120_000)
        c.doOutput = true
        c.setFixedLengthStreamingMode(env.size)
        c.setRequestProperty("X-Filename", filename)
        c.setRequestProperty("X-Message", head)
        c.outputStream.use { it.write(env) }
        return JSONObject(String(readAll(c))).optString("id")
    }

    fun sendUp(obj: JSONObject, attachment: ByteArray? = null, filename: String = "h.bin") = publish(up, obj, attachment, filename)

    /** 받기. since = 유닉스 초 (0 이면 최근 12시간) */
    fun poll(topic: String, since: Long): List<Incoming> {
        val s = if (since > 0) since.toString() else "12h"
        val c = open("$server/$topic/json?poll=1&since=" + URLEncoder.encode(s, "UTF-8"), "GET")
        val text = String(readAll(c), Charsets.UTF_8)
        val out = ArrayList<Incoming>()
        for (line in text.split('\n')) {
            if (line.isBlank()) continue
            try {
                val m = JSONObject(line)
                if (m.optString("event") != "message") continue
                val obj = Envelope.openText(key, topic, m.optString("message"))
                val att = m.optJSONObject("attachment")
                out.add(Incoming(m.getString("id"), m.optLong("time"), obj, att?.optString("url"), att?.optLong("expires") ?: 0L))
            } catch (_: Exception) {
                // 남의 메시지·깨진 메시지는 무시
            }
        }
        return out
    }

    /** 첨부 받아 풀기. 만료(3시간)·없음이면 null. 긴 글 메시지(big)는 원래 내용으로 바꾸고 null. */
    fun fetchAttachment(inc: Incoming, topic: String): ByteArray? {
        val raw = inc.attUrl ?: return null
        if (inc.attExpires > 0 && inc.attExpires < System.currentTimeMillis() / 1000) return null
        // 첨부 주소는 같은 서버의 /file/… — 서버 주소를 우리가 아는 주소로 맞춘다 (에뮬레이터 10.0.2.2 등)
        val url = if (raw.contains("/file/")) "$server/file/" + raw.substringAfterLast("/file/") else raw
        val c = open(url, "GET", 120_000)
        if (c.responseCode == 404 || c.responseCode == 410) return null
        val data = Envelope.open(key, topic, readAll(c))
        if (inc.obj.optBoolean("big")) {
            inc.obj = JSONObject(String(data, Charsets.UTF_8))
            return null
        }
        return data
    }
}
