package io.github.haho240414.harudrawer

import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import android.util.Log
import android.widget.Toast
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.zip.ZipInputStream

/**
 * 다른 앱의 '공유하기 → 하루서랍'. 화면 없이 담기만 하고 바로 닫힌다.
 * 링크·글 / 사진(긴 변 2048 JPEG 로 줄임) / 파일 / 카톡 대화 내보내기(.txt·.csv·.zip) 를 받는다.
 */
class ShareActivity : Activity() {
    companion object {
        private const val TAG = "HaruShare"
        private const val MAX_BYTES = 14 * 1024 * 1024   // ntfy.sh 첨부 한도 15MB 안쪽
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val n = try { handle(intent) } catch (e: Exception) { Log.w(TAG, "공유 받기 실패", e); -1 }
        val msg = when {
            n > 1 -> "하루서랍에 ${n}개 담았어요"
            n == 1 -> "하루서랍에 담았어요"
            n == -2 -> "파일이 너무 커요 (14MB 까지)"
            else -> "담지 못했어요"
        }
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
        if (n > 0) {
            if (Prefs(this).paired) SyncWorker.now(this)
            HaruPlugin.emit("shared", JSONObject().put("count", n))
        }
        finish()
    }

    @Suppress("DEPRECATION")
    private fun streamsOf(intent: Intent): List<Uri> = when (intent.action) {
        Intent.ACTION_SEND -> listOfNotNull(
            if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
            else intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM))
        Intent.ACTION_SEND_MULTIPLE ->
            (if (Build.VERSION.SDK_INT >= 33) intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java)
            else intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM)) ?: emptyList()
        else -> emptyList()
    }

    private fun handle(intent: Intent): Int {
        if (intent.action != Intent.ACTION_SEND && intent.action != Intent.ACTION_SEND_MULTIPLE) return 0
        val text = intent.getStringExtra(Intent.EXTRA_TEXT)?.trim().orEmpty()
        val subject = intent.getStringExtra(Intent.EXTRA_SUBJECT)?.trim().orEmpty()
        val note = when {
            subject.isNotEmpty() && text.isNotEmpty() && !text.contains(subject) -> "$subject\n$text"
            text.isNotEmpty() -> text
            else -> subject
        }
        val from = (if (Build.VERSION.SDK_INT >= 22) referrer?.host else null) ?: ""
        val streams = streamsOf(intent)
        if (streams.isEmpty()) {
            if (note.isEmpty()) return 0
            add("text", note, null, null, null, from)
            return 1
        }
        var n = 0
        for (uri in streams) {
            val r = addStream(uri, intent.type, if (streams.size == 1) note else "", from)
            if (r < 0) return r
            n += r
        }
        return n
    }

    private fun add(kind: String, text: String, name: String?, mime: String?, data: ByteArray?, from: String) {
        val meta = JSONObject().put("ts", SyncEngine.nowIso()).put("kind", kind).put("text", text)
            .put("name", name ?: "").put("mime", mime ?: "").put("app", from)
        Outbox.add(this, meta, data)
    }

    private fun nameOf(uri: Uri): String? = try {
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst()) c.getString(0) else null
        }
    } catch (_: Exception) { null } ?: uri.lastPathSegment?.substringAfterLast('/')

    private fun addStream(uri: Uri, type: String?, note: String, from: String): Int {
        val mime = contentResolver.getType(uri) ?: type ?: "application/octet-stream"
        val name = nameOf(uri) ?: "shared"
        val raw = contentResolver.openInputStream(uri)?.use { input ->
            val out = ByteArrayOutputStream()
            val buf = ByteArray(64 * 1024)
            var total = 0
            while (true) {
                val k = input.read(buf)
                if (k < 0) break
                total += k
                if (total > MAX_BYTES * 3) return -2   // 사진은 줄이면 작아지지만 너무 큰 건 거른다
                out.write(buf, 0, k)
            }
            out.toByteArray()
        } ?: return 0
        if (mime.startsWith("image/") && !mime.contains("gif")) {
            val jpg = shrinkImage(raw)
            if (jpg != null) {
                add("image", note, name.substringBeforeLast('.') + ".jpg", "image/jpeg", jpg, from)
                return 1
            }
        }
        if (raw.size > MAX_BYTES) return -2
        val kind = when {
            looksLikeKakaoExport(name, mime, raw) -> "export"
            mime.startsWith("image/") -> "image"
            mime.startsWith("video/") -> "video"
            mime.startsWith("audio/") -> "audio"
            mime.startsWith("text/plain") && raw.size < 20_000 && note.isEmpty() -> {
                // 짧은 글 파일은 글로
                add("text", String(raw, Charsets.UTF_8).trim(), name, mime, null, from)
                return 1
            }
            else -> "file"
        }
        add(kind, note, name, mime, raw, from)
        return 1
    }

    private fun shrinkImage(raw: ByteArray): ByteArray? {
        val o = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(raw, 0, raw.size, o)
        if (o.outWidth <= 0) return null
        var sample = 1
        while (maxOf(o.outWidth, o.outHeight) / (sample * 2) >= 2048) sample *= 2
        val bmp = BitmapFactory.decodeByteArray(raw, 0, raw.size, BitmapFactory.Options().apply { inSampleSize = sample }) ?: return null
        val scale = 2048f / maxOf(bmp.width, bmp.height)
        val fit = if (scale < 1f) Bitmap.createScaledBitmap(bmp, (bmp.width * scale).toInt(), (bmp.height * scale).toInt(), true) else bmp
        val out = ByteArrayOutputStream()
        fit.compress(Bitmap.CompressFormat.JPEG, 88, out)
        if (fit !== bmp) fit.recycle()
        bmp.recycle()
        return out.toByteArray()
    }

    /** 카톡 '대화 내용 내보내기' 파일인지 (txt·csv 앞부분 또는 zip 안의 txt) */
    private fun looksLikeKakaoExport(name: String, mime: String, raw: ByteArray): Boolean {
        fun isChat(head: String) = head.contains("카카오톡 대화") || head.contains("Date,User,Message") ||
            head.contains("저장한 날짜") || head.contains("Date Saved")
        val lower = name.lowercase()
        if (raw.size >= 2 && raw[0] == 'P'.code.toByte() && raw[1] == 'K'.code.toByte()) {
            try {
                ZipInputStream(raw.inputStream()).use { z ->
                    while (true) {
                        val e = z.nextEntry ?: break
                        val n = e.name.lowercase()
                        if (n.endsWith(".txt") || n.endsWith(".csv")) {
                            val head = ByteArray(4000)
                            val k = z.read(head)
                            if (k > 0 && isChat(String(head, 0, k, Charsets.UTF_8))) return true
                        }
                    }
                }
            } catch (_: Exception) { }
            return false
        }
        if (mime.startsWith("text/") || lower.endsWith(".txt") || lower.endsWith(".csv")) {
            val head = String(raw, 0, minOf(raw.size, 4000), Charsets.UTF_8)
            return isChat(head) || lower.startsWith("kakaotalk") || lower.startsWith("talk_")
        }
        return false
    }
}
