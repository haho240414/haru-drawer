package io.github.haho240414.harudrawer

import org.json.JSONObject
import java.security.SecureRandom
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * 맥↔폰 메시지 암호화 — 맥의 haru/crypto.py 와 똑같다.
 * 봉투 = 0x01 | nonce(12) | 암호문+태그(16), AAD = 토픽 이름. 글자 메시지는 "H1:" + base64url(봉투).
 */
object Envelope {
    const val PREFIX = "H1:"
    private val rnd = SecureRandom()

    fun b64u(b: ByteArray): String = Base64.getUrlEncoder().withoutPadding().encodeToString(b)
    fun unb64u(s: String): ByteArray = Base64.getUrlDecoder().decode(s.trim().trimEnd('='))

    fun seal(keyB64: String, topic: String, plain: ByteArray): ByteArray {
        val nonce = ByteArray(12).also { rnd.nextBytes(it) }
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, SecretKeySpec(unb64u(keyB64), "AES"), GCMParameterSpec(128, nonce))
        c.updateAAD(topic.toByteArray(Charsets.UTF_8))
        return byteArrayOf(1) + nonce + c.doFinal(plain)
    }

    /** 실패하면 예외 (키가 다르거나 변조됨) */
    fun open(keyB64: String, topic: String, env: ByteArray): ByteArray {
        require(env.size >= 1 + 12 + 16 && env[0] == 1.toByte()) { "하루서랍 봉투가 아니에요" }
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.DECRYPT_MODE, SecretKeySpec(unb64u(keyB64), "AES"), GCMParameterSpec(128, env, 1, 12))
        c.updateAAD(topic.toByteArray(Charsets.UTF_8))
        return c.doFinal(env, 13, env.size - 13)
    }

    fun sealText(keyB64: String, topic: String, obj: JSONObject): String =
        PREFIX + b64u(seal(keyB64, topic, obj.toString().toByteArray(Charsets.UTF_8)))

    fun openText(keyB64: String, topic: String, text: String): JSONObject {
        require(text.startsWith(PREFIX)) { "하루서랍 메시지가 아니에요" }
        return JSONObject(String(open(keyB64, topic, unb64u(text.substring(PREFIX.length))), Charsets.UTF_8))
    }
}

/** 맥이 보여 주는 연결 코드: "HARU1." + base64url(JSON). QR 은 "haru://pair/" 를 앞에 붙이기도 한다. */
data class Pairing(val server: String, val up: String, val down: String, val key: String, val name: String) {
    companion object {
        fun parse(raw: String): Pairing {
            var code = raw.trim()
            val i = code.indexOf("HARU1.")
            require(i >= 0) { "하루서랍 연결 코드가 아니에요 (HARU1. 로 시작해야 해요)" }
            code = code.substring(i + 6).trim().trimEnd('/')
            val j = JSONObject(String(Envelope.unb64u(code), Charsets.UTF_8))
            val p = Pairing(j.getString("s").trimEnd('/'), j.getString("u"), j.getString("d"), j.getString("k"), j.optString("n", "맥"))
            require(Envelope.unb64u(p.key).size == 32) { "연결 코드의 키가 이상해요" }
            return p
        }
    }
}
