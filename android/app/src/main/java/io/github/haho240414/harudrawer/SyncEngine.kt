package io.github.haho240414.harudrawer

import android.content.Context
import android.os.Build
import android.util.Log
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequest
import androidx.work.PeriodicWorkRequest
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import org.json.JSONArray
import org.json.JSONObject
import java.time.ZonedDateTime
import java.time.temporal.ChronoUnit
import java.util.TimeZone
import java.util.concurrent.TimeUnit

/**
 * 맥과 주고받기 한 바퀴: (1) 인사(기기 화면 크기·시간대) (2) 담아 둔 것 보내기 (3) 맥 소식 받기
 * (받았다는 ack → 지우기, 첨부 만료 nack → 다시 보내기, 새 보고서 → 저장·잠금화면 적용).
 * 앱 화면의 '지금 보내기·받기'와 백그라운드 작업(SyncWorker)이 같이 쓴다.
 */
object SyncEngine {
    private const val TAG = "HaruSync"
    private const val RESEND_AFTER_SEC = 6 * 3600L

    fun nowIso(): String = ZonedDateTime.now().truncatedTo(ChronoUnit.SECONDS).toOffsetDateTime().toString()

    private fun appVersion(ctx: Context): String = try {
        ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: "?"
    } catch (_: Exception) { "?" }

    fun hello(ctx: Context, p: Prefs, r: Relay) {
        val (w, h) = Lockscreen.screenSize(ctx)
        val dm = ctx.resources.displayMetrics
        val dev = JSONObject().put("w", w).put("h", h).put("density", dm.density.toDouble())
            .put("model", Build.MODEL ?: "").put("maker", Build.MANUFACTURER ?: "").put("sdk", Build.VERSION.SDK_INT)
        r.sendUp(JSONObject().put("t", "hello").put("dev", dev).put("tz", TimeZone.getDefault().id)
            .put("app", appVersion(ctx)).put("at", nowIso()))
        p.helloAt = System.currentTimeMillis()
        p.helloVer = appVersion(ctx)
    }

    @Synchronized
    fun run(ctx: Context): JSONObject {
        val p = Prefs(ctx)
        val r = p.relay() ?: return JSONObject().put("ok", false).put("msg", "맥과 연결 전이에요")
        val res = JSONObject().put("ok", true)
        try {
            if (p.helloVer != appVersion(ctx) || System.currentTimeMillis() - p.helloAt > 24 * 3600_000L) hello(ctx, p, r)
            res.put("sent", upload(ctx, r))
            pollDown(ctx, p, r, res)
            p.lastSync = System.currentTimeMillis()
            p.lastError = null
        } catch (e: Exception) {
            Log.w(TAG, "주고받기 실패", e)
            p.lastError = e.message
            res.put("ok", false).put("msg", "맥과 주고받기 실패: ${e.message}")
        }
        return res
    }

    /** 담아 둔 것 보내기 (새것 + 보낸 지 6시간 넘었는데 맥이 못 받은 것) */
    private fun upload(ctx: Context, r: Relay): Int {
        var n = 0
        val now = System.currentTimeMillis() / 1000
        for (it in Outbox.list(ctx)) {
            if (n >= 15) break
            val state = it.optString("state")
            val due = state == "queued" || (state == "sent" && now - it.optLong("sentAt") > RESEND_AFTER_SEC)
            if (!due) continue
            val id = it.getString("id")
            val meta = JSONObject().put("t", "item").put("id", id).put("ts", it.optString("ts"))
                .put("kind", it.optString("kind")).put("text", it.optString("text"))
                .put("name", it.optString("name")).put("mime", it.optString("mime")).put("app", it.optString("app"))
            val data = Outbox.data(ctx, id)
            r.sendUp(meta, data, if (data != null) "$id.bin" else "h.bin")
            Outbox.update(ctx, id) { o -> o.put("state", "sent").put("sentAt", now).put("tries", o.optInt("tries") + 1) }
            n++
        }
        return n
    }

    private fun pollDown(ctx: Context, p: Prefs, r: Relay, res: JSONObject) {
        val since = if (p.downSince > 0) p.downSince - 180 else 0L
        val incs = r.poll(r.down, since).sortedBy { it.time }
        val seen = p.seen.toMutableList()
        var newDay: String? = null
        var received = 0
        for (inc in incs) {
            if (inc.id in seen) continue
            try {
                when (inc.obj.optString("t")) {
                    "ack" -> {
                        inc.obj.optJSONArray("ids")?.let { a -> for (i in 0 until a.length()) Outbox.remove(ctx, a.optString(i)) }
                        inc.obj.optJSONArray("nack")?.let { a ->
                            for (i in 0 until a.length()) Outbox.update(ctx, a.optString(i)) { o -> o.put("state", "queued") }
                        }
                    }
                    "hb" -> {
                        p.lastHb = inc.obj.optString("at")
                        p.macNext = inc.obj.optString("next")
                        p.macDay = inc.obj.optString("day")
                    }
                    "digest" -> {
                        val day = inc.obj.optString("day")
                        val ver = inc.obj.optInt("ver")
                        val data = r.fetchAttachment(inc, r.down)
                        if (data == null) {
                            // 3시간이 지나 첨부가 사라짐 → 맥에 다시 보내 달라고 (같은 판은 한 번만)
                            val ask = "$day:$ver"
                            if (p.resendAsked != ask) {
                                r.sendUp(JSONObject().put("t", "resend").put("day", day))
                                p.resendAsked = ask
                            }
                        } else {
                            val bundle = JSONObject(String(data, Charsets.UTF_8))
                            if (Digests.save(ctx, bundle)) {
                                newDay = day
                                received++
                            }
                        }
                    }
                }
            } catch (e: Exception) {
                Log.w(TAG, "맥 메시지 처리 실패 ${inc.obj.optString("t")}", e)
            }
            seen.add(inc.id)
        }
        p.seen = seen
        incs.maxOfOrNull { it.time }?.let { if (it > p.downSince) p.downSince = it }
        res.put("received", received)
        if (newDay != null) {
            res.put("newDigest", newDay)
            Lockscreen.apply(ctx)?.let { res.put("lockMsg", it) }
            HaruPlugin.emit("digest", JSONObject().put("day", newDay))
        }
    }

    fun requestRefresh(ctx: Context): JSONObject {
        val r = Prefs(ctx).relay() ?: return JSONObject().put("ok", false).put("msg", "맥과 연결 전이에요")
        return try {
            r.sendUp(JSONObject().put("t", "refresh").put("at", nowIso()))
            JSONObject().put("ok", true)
        } catch (e: Exception) {
            JSONObject().put("ok", false).put("msg", e.message)
        }
    }

    fun sendTodo(ctx: Context, key: String, done: Boolean) {
        val r = Prefs(ctx).relay() ?: return
        try { r.sendUp(JSONObject().put("t", "todo").put("key", key).put("done", done)) } catch (e: Exception) { Log.w(TAG, "할 일 보내기 실패", e) }
    }

    fun outboxJson(ctx: Context): JSONArray {
        val a = JSONArray()
        for (o in Outbox.list(ctx)) {
            a.put(JSONObject().put("id", o.optString("id")).put("kind", o.optString("kind")).put("ts", o.optString("ts"))
                .put("text", o.optString("text")).put("name", o.optString("name"))
                .put("state", when (o.optString("state")) { "sent" -> "보냄 (맥이 받기를 기다림)"; else -> "보낼 차례" }))
        }
        return a
    }
}

/** 백그라운드 작업: 15분마다 + 공유할 때·앱 열 때 한 번 */
class SyncWorker(ctx: Context, params: WorkerParameters) : Worker(ctx, params) {
    override fun doWork(): Result {
        if (!Prefs(applicationContext).paired) return Result.success()
        val r = SyncEngine.run(applicationContext)
        return if (r.optBoolean("ok")) Result.success() else Result.retry()
    }

    companion object {
        private val net = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

        fun schedule(ctx: Context) {
            val req = PeriodicWorkRequest.Builder(SyncWorker::class.java, 15, TimeUnit.MINUTES)
                .setConstraints(net).setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 60, TimeUnit.SECONDS).build()
            WorkManager.getInstance(ctx).enqueueUniquePeriodicWork("haru-sync", ExistingPeriodicWorkPolicy.UPDATE, req)
        }

        fun now(ctx: Context) {
            val req = OneTimeWorkRequest.Builder(SyncWorker::class.java).setConstraints(net)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS).build()
            WorkManager.getInstance(ctx).enqueueUniqueWork("haru-sync-now", ExistingWorkPolicy.REPLACE, req)
        }

        fun cancel(ctx: Context) {
            WorkManager.getInstance(ctx).cancelUniqueWork("haru-sync")
            WorkManager.getInstance(ctx).cancelUniqueWork("haru-sync-now")
        }
    }
}
