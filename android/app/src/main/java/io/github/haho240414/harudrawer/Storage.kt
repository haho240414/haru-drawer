package io.github.haho240414.harudrawer

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

/** 맥으로 보낼 것 (공유하기로 담은 것). 맥이 'ack' 하면 지운다. 파일: filesDir/outbox/<id>.json (+ .bin) */
object Outbox {
    private fun dir(ctx: Context) = File(ctx.filesDir, "outbox").apply { mkdirs() }

    @Synchronized
    fun add(ctx: Context, meta: JSONObject, data: ByteArray?): String {
        val id = meta.optString("id").ifEmpty { UUID.randomUUID().toString() }
        meta.put("id", id).put("state", "queued").put("tries", 0)
        if (data != null) {
            File(dir(ctx), "$id.bin").writeBytes(data)
            meta.put("size", data.size)
        }
        File(dir(ctx), "$id.json").writeText(meta.toString())
        return id
    }

    @Synchronized
    fun list(ctx: Context): List<JSONObject> =
        (dir(ctx).listFiles { f -> f.name.endsWith(".json") } ?: emptyArray())
            .mapNotNull { f -> try { JSONObject(f.readText()) } catch (_: Exception) { null } }
            .sortedBy { it.optString("ts") }

    fun data(ctx: Context, id: String): ByteArray? = File(dir(ctx), "$id.bin").takeIf { it.exists() }?.readBytes()

    @Synchronized
    fun update(ctx: Context, id: String, fn: (JSONObject) -> Unit) {
        val f = File(dir(ctx), "$id.json")
        if (!f.exists()) return
        val o = JSONObject(f.readText())
        fn(o)
        f.writeText(o.toString())
    }

    @Synchronized
    fun remove(ctx: Context, id: String) {
        File(dir(ctx), "$id.json").delete()
        File(dir(ctx), "$id.bin").delete()
    }

    fun count(ctx: Context) = dir(ctx).listFiles { f -> f.name.endsWith(".json") }?.size ?: 0
}

/** 맥이 보낸 하루 보고서 묶음 (보고서 + 잠금 카드 A/B + 사진 미리보기). 파일: filesDir/digests/<day>.json */
object Digests {
    private fun dir(ctx: Context) = File(ctx.filesDir, "digests").apply { mkdirs() }

    /** 저장 (같은 날 더 새 버전만). 새로 저장했으면 true */
    @Synchronized
    fun save(ctx: Context, bundle: JSONObject): Boolean {
        val day = bundle.optString("day")
        if (!Regex("""\d{4}-\d{2}-\d{2}""").matches(day)) return false
        val f = File(dir(ctx), "$day.json")
        if (f.exists()) {
            val old = try { JSONObject(f.readText()).optInt("ver") } catch (_: Exception) { -1 }
            if (old > bundle.optInt("ver")) return false
        }
        val tmp = File(dir(ctx), "$day.tmp")
        tmp.writeText(bundle.toString())
        tmp.renameTo(f)
        prune(ctx)
        return true
    }

    fun load(ctx: Context, day: String): JSONObject? =
        File(dir(ctx), "$day.json").takeIf { it.exists() }?.let { try { JSONObject(it.readText()) } catch (_: Exception) { null } }

    fun days(ctx: Context): List<String> =
        (dir(ctx).listFiles { f -> f.name.endsWith(".json") } ?: emptyArray()).map { it.name.removeSuffix(".json") }.sortedDescending()

    fun latest(ctx: Context): JSONObject? = days(ctx).firstOrNull()?.let { load(ctx, it) }

    /** 목록용 요약 (가볍게: 묶음 전체를 읽지만 필요한 것만 돌려줌) */
    fun summaries(ctx: Context): JSONArray {
        val arr = JSONArray()
        for (day in days(ctx)) {
            val b = load(ctx, day) ?: continue
            val d = b.optJSONObject("digest") ?: continue
            arr.put(JSONObject().put("day", day).put("count", d.optJSONObject("stats")?.optInt("count") ?: 0)
                .put("digest_version", b.optInt("ver")).put("generated_at", d.optString("generated_at"))
                .put("headline", d.optString("headline")))
        }
        return arr
    }

    private fun prune(ctx: Context, keep: Int = 90) {
        days(ctx).drop(keep).forEach { File(dir(ctx), "$it.json").delete() }
    }
}
