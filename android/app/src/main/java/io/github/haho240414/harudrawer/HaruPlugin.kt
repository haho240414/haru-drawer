package io.github.haho240414.harudrawer

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.MediaStore
import android.provider.Settings
import android.util.Log
import androidx.activity.result.ActivityResult
import androidx.core.app.NotificationManagerCompat
import com.getcapacitor.JSArray
import com.getcapacitor.JSObject
import com.getcapacitor.PermissionState
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.ActivityCallback
import com.getcapacitor.annotation.CapacitorPlugin
import com.getcapacitor.annotation.Permission
import com.getcapacitor.annotation.PermissionCallback
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.time.ZonedDateTime
import java.util.concurrent.Executors

/** 웹 화면(app/js/source.js 의 PhoneSource) ↔ 네이티브 */
@CapacitorPlugin(
    name = "Haru",
    permissions = [Permission(alias = "notifications", strings = [Manifest.permission.POST_NOTIFICATIONS])],
)
class HaruPlugin : Plugin() {
    companion object {
        private const val TAG = "HaruPlugin"
        @Volatile private var instance: HaruPlugin? = null
        private val main = Handler(Looper.getMainLooper())
        val io = Executors.newSingleThreadExecutor()

        /** 네이티브에서 웹으로 알림 (앱이 열려 있을 때만) */
        fun emit(event: String, data: JSONObject = JSONObject()) {
            val p = instance ?: return
            main.post { try { p.emitEvent(event, JSObject.fromJSONObject(data)) } catch (e: Exception) { Log.w(TAG, "emit", e) } }
        }
    }

    /** notifyListeners 는 protected 라 companion 에서 부를 수 있게 감싼다 */
    fun emitEvent(event: String, data: JSObject) = notifyListeners(event, data)

    override fun load() {
        instance = this
        Lockscreen.ensureChannel(context)
        if (Prefs(context).paired) SyncWorker.schedule(context)
    }

    override fun handleOnDestroy() {
        if (instance === this) instance = null
        super.handleOnDestroy()
    }

    private fun bg(call: PluginCall, work: () -> JSONObject) {
        io.execute {
            try {
                call.resolve(JSObject.fromJSONObject(work()))
            } catch (e: Exception) {
                Log.w(TAG, "실패", e)
                call.reject(e.message ?: "실패")
            }
        }
    }

    private fun localDay(): String {
        // 맥과 같은 규칙: 새벽 4시 전은 전날
        return ZonedDateTime.now().minusHours(4).toLocalDate().toString()
    }

    @PluginMethod
    fun takeReportRoute(call: PluginCall) {
        val day = ReportLink.take()
        if (day != null) Log.i(TAG, "보고서 열기: $day")
        call.resolve(JSObject().put("day", day ?: JSONObject.NULL))
    }

    @PluginMethod
    fun getStatus(call: PluginCall) {
        val p = Prefs(context)
        val pm = context.getSystemService(PowerManager::class.java)
        val r = JSObject()
        r.put("paired", p.paired)
        r.put("macName", p.macName ?: "")
        r.put("server", p.server ?: "")
        r.put("lastHb", p.lastHb?.take(16)?.replace("T", " ") ?: "")
        r.put("macNext", p.macNext?.take(16)?.replace("T", " ") ?: "")
        r.put("macDay", p.macDay ?: "")
        r.put("outbox", Outbox.count(context))
        r.put("lastSync", p.lastSync)
        r.put("lastError", p.lastError ?: "")
        r.put("notifications", NotificationManagerCompat.from(context).areNotificationsEnabled())
        r.put("batteryOk", pm.isIgnoringBatteryOptimizations(context.packageName))
        r.put("sdk", Build.VERSION.SDK_INT)
        r.put("model", Build.MODEL ?: "")
        r.put("reportDay", Digests.days(context).firstOrNull() ?: "")
        r.put("wallpaperApplied", p.wallpaper && p.wallpaperSet && !p.appliedKey.isNullOrEmpty())
        call.resolve(r)
    }

    @PluginMethod
    fun listDigests(call: PluginCall) {
        bg(call) { JSONObject().put("days", Digests.summaries(context)).put("today", localDay()) }
    }

    @PluginMethod
    fun getDigest(call: PluginCall) {
        val day = call.getString("day") ?: ""
        bg(call) {
            val b = Digests.load(context, day) ?: return@bg JSONObject().put("digest", JSONObject.NULL)
            val d = b.optJSONObject("digest") ?: JSONObject()
            // 폰에서 체크한 할 일 반영
            val done = Prefs(context).todosDone
            d.optJSONArray("todos")?.let { a ->
                for (i in 0 until a.length()) {
                    val t = a.optJSONObject(i) ?: continue
                    if (t.optString("key") in done) t.put("done", true)
                }
            }
            d.put("version", b.optInt("ver"))
            val cards = JSONObject()
            b.optJSONObject("cards")?.let { c -> c.keys().forEach { k -> cards.put(k, "data:image/png;base64," + c.optString(k)) } }
            val thumbs = JSONObject()
            b.optJSONObject("thumbs")?.let { t -> t.keys().forEach { k -> thumbs.put(k, "data:image/jpeg;base64," + t.optString(k)) } }
            JSONObject().put("digest", d).put("cards", cards).put("thumbs", thumbs)
        }
    }

    @PluginMethod
    fun syncNow(call: PluginCall) {
        bg(call) { SyncEngine.run(context) }
    }

    @PluginMethod
    fun requestRefresh(call: PluginCall) {
        bg(call) {
            val r = SyncEngine.requestRefresh(context)
            SyncEngine.run(context)
            r
        }
    }

    @PluginMethod
    fun pair(call: PluginCall) {
        val code = call.getString("code") ?: ""
        bg(call) { doPair(code) }
    }

    fun doPair(code: String): JSONObject {
        val pairing = try { Pairing.parse(code) } catch (e: Exception) {
            return JSONObject().put("ok", false).put("msg", e.message)
        }
        val p = Prefs(context)
        val same = p.key == pairing.key && p.up == pairing.up && p.down == pairing.down && p.server == pairing.server
        if (!same) p.savePairing(pairing)
        SyncWorker.schedule(context)
        val r = SyncEngine.run(context)   // 바로 인사하고 받아 오기
        emit("paired", JSONObject().put("mac", pairing.name))
        return JSONObject().put("ok", r.optBoolean("ok")).put("msg", r.optString("msg")).put("macName", pairing.name)
    }

    @PluginMethod
    fun unpair(call: PluginCall) {
        Prefs(context).clearPairing()
        SyncWorker.cancel(context)
        call.resolve(JSObject().put("ok", true))
    }

    @PluginMethod
    fun scanQr(call: PluginCall) {
        try {
            GmsBarcodeScanning.getClient(activity).startScan()
                .addOnSuccessListener { b -> call.resolve(JSObject().put("code", b.rawValue ?: "")) }
                .addOnCanceledListener { call.resolve(JSObject().put("code", "")) }
                .addOnFailureListener { e -> call.reject("QR 스캐너를 열 수 없어요: ${e.message}") }
        } catch (e: Exception) {
            call.reject("QR 스캐너를 열 수 없어요: ${e.message}")
        }
    }

    @PluginMethod
    fun getOutbox(call: PluginCall) {
        bg(call) { JSONObject().put("items", SyncEngine.outboxJson(context)) }
    }

    @PluginMethod
    fun retryOutbox(call: PluginCall) {
        for (o in Outbox.list(context)) Outbox.update(context, o.getString("id")) { it.put("state", "queued") }
        bg(call) { SyncEngine.run(context) }
    }

    @PluginMethod
    fun getSettings(call: PluginCall) {
        val p = Prefs(context)
        call.resolve(JSObject().put("wallpaper", p.wallpaper).put("notify", p.notify).put("style", p.style)
            .put("bg", if (p.bg == "photo" && Lockscreen.bgFile(context).exists()) "photo" else "gradient"))
    }

    @PluginMethod
    fun setSettings(call: PluginCall) {
        val p = Prefs(context)
        call.getBoolean("wallpaper")?.let { p.wallpaper = it }
        call.getBoolean("notify")?.let { p.notify = it }
        call.getString("style")?.let { if (it == "A" || it == "B") p.style = it }
        call.getString("bg")?.let { if (it == "gradient" || it == "photo") p.bg = it }
        bg(call) {
            val msg = Lockscreen.apply(context)
            JSONObject().put("ok", msg == null).put("msg", msg ?: "")
        }
    }

    @PluginMethod
    fun applyLockscreen(call: PluginCall) {
        bg(call) {
            val msg = Lockscreen.apply(context, force = true)
            JSONObject().put("ok", msg == null).put("msg", msg ?: "")
        }
    }

    @PluginMethod
    fun previewLockscreen(call: PluginCall) {
        val style = call.getString("style") ?: Prefs(context).style
        bg(call) { JSONObject().put("image", Lockscreen.previewDataUri(context, style) ?: JSONObject.NULL) }
    }

    @PluginMethod
    fun pickBackground(call: PluginCall) {
        val intent = if (Build.VERSION.SDK_INT >= 33) Intent(MediaStore.ACTION_PICK_IMAGES).setType("image/*")
        else Intent(Intent.ACTION_GET_CONTENT).setType("image/*").addCategory(Intent.CATEGORY_OPENABLE)
        startActivityForResult(call, intent, "onBackgroundPicked")
    }

    @ActivityCallback
    private fun onBackgroundPicked(call: PluginCall?, result: ActivityResult) {
        if (call == null) return
        val uri: Uri? = result.data?.data
        if (uri == null) {
            call.resolve(JSObject().put("ok", false))
            return
        }
        io.execute {
            try {
                val raw = context.contentResolver.openInputStream(uri)?.use { it.readBytes() } ?: throw IllegalStateException("사진을 열 수 없어요")
                val (w, h) = Lockscreen.screenSize(context)
                val o = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                BitmapFactory.decodeByteArray(raw, 0, raw.size, o)
                var sample = 1
                while (o.outWidth / (sample * 2) >= w && o.outHeight / (sample * 2) >= h) sample *= 2
                val bmp = BitmapFactory.decodeByteArray(raw, 0, raw.size, BitmapFactory.Options().apply { inSampleSize = sample })
                    ?: throw IllegalStateException("사진 형식을 읽을 수 없어요")
                val out = ByteArrayOutputStream()
                bmp.compress(Bitmap.CompressFormat.JPEG, 90, out)
                bmp.recycle()
                Lockscreen.bgFile(context).writeBytes(out.toByteArray())
                val p = Prefs(context)
                p.bg = "photo"
                val msg = Lockscreen.apply(context, force = true)
                call.resolve(JSObject().put("ok", true).put("msg", msg ?: ""))
            } catch (e: Exception) {
                call.reject(e.message ?: "배경 사진 저장 실패")
            }
        }
    }

    @PluginMethod
    fun setTodo(call: PluginCall) {
        val key = call.getString("key") ?: return call.reject("key 없음")
        val done = call.getBoolean("done") ?: false
        val p = Prefs(context)
        p.todosDone = if (done) p.todosDone + key else p.todosDone - key
        bg(call) {
            SyncEngine.sendTodo(context, key, done)
            if (p.notify) Digests.latest(context)?.let { Lockscreen.notify(context, it) }
            JSONObject().put("ok", true)
        }
    }

    @PluginMethod
    fun requestNotifications(call: PluginCall) {
        if (Build.VERSION.SDK_INT >= 33 && getPermissionState("notifications") != PermissionState.GRANTED) {
            requestPermissionForAlias("notifications", call, "onNotifPermission")
        } else {
            Lockscreen.ensureChannel(context)
            call.resolve(JSObject().put("granted", NotificationManagerCompat.from(context).areNotificationsEnabled()))
        }
    }

    @PermissionCallback
    private fun onNotifPermission(call: PluginCall) {
        Lockscreen.ensureChannel(context)
        val granted = getPermissionState("notifications") == PermissionState.GRANTED
        if (granted) Digests.latest(context)?.let { if (Prefs(context).notify) Lockscreen.notify(context, it) }
        call.resolve(JSObject().put("granted", granted))
    }

    @SuppressLint("BatteryLife")
    @PluginMethod
    fun openBatterySettings(call: PluginCall) {
        try {
            val i = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:" + context.packageName))
            activity.startActivity(i)
        } catch (_: Exception) {
            activity.startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }
        call.resolve()
    }

    @PluginMethod
    fun openUrl(call: PluginCall) {
        val url = call.getString("url") ?: return call.reject("url 없음")
        try {
            activity.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            call.resolve()
        } catch (e: Exception) {
            call.reject("열 수 없어요: ${e.message}")
        }
    }

    @PluginMethod
    fun debugInfo(call: PluginCall) {
        val days = JSArray()
        Digests.days(context).forEach { days.put(it) }
        call.resolve(JSObject().put("days", days).put("outbox", Outbox.count(context)).put("applied", Prefs(context).appliedKey ?: ""))
    }
}
