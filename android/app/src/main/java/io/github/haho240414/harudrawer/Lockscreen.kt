package io.github.haho240414.harudrawer

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.WallpaperManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.Shader
import android.net.Uri
import android.os.Build
import android.util.Base64
import android.util.DisplayMetrics
import android.util.Log
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File

/**
 * 잠금화면 적용: 맥이 그린 투명 카드(PNG)를 배경(기본 그라데이션 또는 내 사진) 위에 겹쳐 잠금화면 배경으로,
 * 그리고 조용한 알림으로도 보여 준다. 홈 화면 배경은 건드리지 않는다 (FLAG_LOCK 만).
 */
object Lockscreen {
    private const val TAG = "HaruLock"
    const val CHANNEL = "brief"
    const val NOTIF_ID = 2026

    fun bgFile(ctx: Context) = File(ctx.filesDir, "bg.jpg")

    /** 화면 실제 크기 (세로 기준) */
    fun screenSize(ctx: Context): Pair<Int, Int> {
        val wm = ctx.getSystemService(WindowManager::class.java)
        var w: Int
        var h: Int
        if (Build.VERSION.SDK_INT >= 30) {
            val b = wm.maximumWindowMetrics.bounds
            w = b.width(); h = b.height()
        } else {
            val dm = DisplayMetrics()
            @Suppress("DEPRECATION")
            wm.defaultDisplay.getRealMetrics(dm)
            w = dm.widthPixels; h = dm.heightPixels
        }
        if (w > h) { val t = w; w = h; h = t }
        return Pair(w, h)
    }

    private fun gradientColors(style: String) =
        if (style == "B") intArrayOf(Color.parseColor("#1c1917"), Color.parseColor("#7c2d12"))
        else intArrayOf(Color.parseColor("#0f172a"), Color.parseColor("#312e81"))

    private fun decodeScaled(file: File, w: Int, h: Int): Bitmap? {
        val o = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.path, o)
        if (o.outWidth <= 0) return null
        var sample = 1
        while (o.outWidth / (sample * 2) >= w && o.outHeight / (sample * 2) >= h) sample *= 2
        return BitmapFactory.decodeFile(file.path, BitmapFactory.Options().apply { inSampleSize = sample })
    }

    /** 배경 + 카드 → 잠금화면 한 장 */
    fun compose(ctx: Context, bundle: JSONObject, style: String, bgMode: String, w0: Int = 0, h0: Int = 0): Bitmap {
        val (sw, sh) = screenSize(ctx)
        val w = if (w0 > 0) w0 else sw
        val h = if (h0 > 0) h0 else sh
        val out = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888)
        val c = Canvas(out)
        val paint = Paint(Paint.ANTI_ALIAS_FLAG or Paint.FILTER_BITMAP_FLAG)
        val photo = if (bgMode == "photo" && bgFile(ctx).exists()) decodeScaled(bgFile(ctx), w, h) else null
        if (photo != null) {
            // 가운데 기준으로 꽉 채우기
            val scale = maxOf(w.toFloat() / photo.width, h.toFloat() / photo.height)
            val sw2 = (w / scale).toInt(); val sh2 = (h / scale).toInt()
            val sx = (photo.width - sw2) / 2; val sy = (photo.height - sh2) / 2
            c.drawBitmap(photo, Rect(sx, sy, sx + sw2, sy + sh2), Rect(0, 0, w, h), paint)
            // 글씨가 잘 보이게 아래쪽을 살짝 어둡게
            val scrim = Paint().apply {
                shader = LinearGradient(0f, h * 0.35f, 0f, h.toFloat(), Color.TRANSPARENT, Color.argb(130, 0, 0, 0), Shader.TileMode.CLAMP)
            }
            c.drawRect(0f, 0f, w.toFloat(), h.toFloat(), scrim)
            photo.recycle()
        } else {
            val cols = gradientColors(style)
            val g = Paint().apply { shader = LinearGradient(0f, 0f, 0f, h.toFloat(), cols[0], cols[1], Shader.TileMode.CLAMP) }
            c.drawRect(0f, 0f, w.toFloat(), h.toFloat(), g)
        }
        val card = cardBitmap(bundle, style)
        if (card != null) {
            val position = Prefs(ctx).cardPosition
            if (position == "middle") {
                c.drawBitmap(card, Rect(0, 0, card.width, card.height), Rect(0, 0, w, h), paint)
            } else {
                val content = visibleBounds(card)
                val margin = (w * 0.05f).toInt()
                val box = CardPlacement.box(w, h, content.width(), content.height(), position, margin)
                c.drawBitmap(card, content, Rect(box[0], box[1], box[2], box[3]), paint)
            }
            card.recycle()
        }
        return out
    }

    private fun visibleBounds(bitmap: Bitmap): Rect {
        val row = IntArray(bitmap.width)
        var left = bitmap.width; var right = 0; var top = bitmap.height; var bottom = 0
        for (y in 0 until bitmap.height) {
            bitmap.getPixels(row, 0, bitmap.width, 0, y, bitmap.width, 1)
            for (x in row.indices) if ((row[x] ushr 24) >= 32) {
                left = minOf(left, x); right = maxOf(right, x + 1)
                top = minOf(top, y); bottom = maxOf(bottom, y + 1)
            }
        }
        return if (left < right && top < bottom) Rect(left, top, right, bottom)
            else Rect(0, 0, bitmap.width, bitmap.height)
    }

    fun cardBitmap(bundle: JSONObject, style: String): Bitmap? {
        val cards = bundle.optJSONObject("cards") ?: return null
        val b64 = cards.optString(style).ifEmpty { cards.optString("A") }
        if (b64.isEmpty()) return null
        val bytes = Base64.decode(b64, Base64.DEFAULT)
        return BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
    }

    /** 가장 최근 보고서로 잠금화면·알림 갱신. 문제가 있으면 사람이 읽을 메시지, 없으면 null */
    fun apply(ctx: Context, force: Boolean = false): String? {
        val p = Prefs(ctx)
        val bundle = Digests.latest(ctx) ?: return "아직 맥에서 받은 정리가 없어요"
        if (p.notify) notify(ctx, bundle) else NotificationManagerCompat.from(ctx).cancel(NOTIF_ID)
        val wm = WallpaperManager.getInstance(ctx)
        if (p.wallpaper) {
            val stamp = if (p.bg == "photo") bgFile(ctx).lastModified() else 0L
            val key = "${bundle.optString("day")}:${bundle.optInt("ver")}:${p.style}:${p.bg}:$stamp:${p.cardPosition}"
            if (force || key != p.appliedKey) {
                return try {
                    val bmp = compose(ctx, bundle, p.style, p.bg)
                    wm.setBitmap(bmp, null, true, WallpaperManager.FLAG_LOCK)
                    bmp.recycle()
                    p.appliedKey = key
                    p.wallpaperSet = true
                    Log.i(TAG, "잠금화면 배경 적용 $key")
                    null
                } catch (e: Exception) {
                    Log.w(TAG, "배경 적용 실패", e)
                    "잠금화면 배경을 바꾸지 못했어요: ${e.message}"
                }
            }
        } else if (p.wallpaperSet) {
            try { wm.clear(WallpaperManager.FLAG_LOCK) } catch (e: Exception) { Log.w(TAG, "배경 되돌리기 실패", e) }
            p.wallpaperSet = false
            p.appliedKey = null
        }
        return null
    }

    fun ensureChannel(ctx: Context) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CHANNEL) == null) {
            val ch = NotificationChannel(CHANNEL, "하루 정리", NotificationManager.IMPORTANCE_DEFAULT).apply {
                description = "잠금화면에 오늘 모은 것 요약 (소리·진동 없음)"
                setSound(null, null)
                enableVibration(false)
                setShowBadge(false)
                lockscreenVisibility = android.app.Notification.VISIBILITY_PUBLIC
            }
            nm.createNotificationChannel(ch)
        }
    }

    fun notify(ctx: Context, bundle: JSONObject) {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        ensureChannel(ctx)
        val d = bundle.optJSONObject("digest") ?: return
        val lock = d.optJSONObject("lock")
        val count = d.optJSONObject("stats")?.optInt("count") ?: 0
        val title = lock?.optString("title").takeUnless { it.isNullOrEmpty() } ?: d.optString("headline")
        val lines = ArrayList<String>()
        val quick = d.optJSONArray("quick_summary")
        val arr = if (quick != null && quick.length() > 0) quick else lock?.optJSONArray("lines")
        if (arr != null) for (i in 0 until minOf(3, arr.length())) arr.optString(i).takeIf { it.isNotEmpty() }?.let { lines.add("${i + 1}. $it") }
        val open0 = Intent(Intent.ACTION_VIEW, Uri.parse("haru://report/${bundle.optString("day")}"), ctx, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        val pi = PendingIntent.getActivity(ctx, 0, open0, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val n = NotificationCompat.Builder(ctx, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_haru)
            .setContentTitle("하루서랍 · ${d.optString("label")} · ${count}개 자료")
            .setContentText(lines.firstOrNull() ?: title)
            .setStyle(NotificationCompat.BigTextStyle().bigText(lines.joinToString("\n").ifEmpty { title })
                .setSummaryText("눌러서 상세 브리핑 읽기"))
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setShowWhen(true)
            .setContentIntent(pi)
            .addAction(R.drawable.ic_stat_haru, "보고서 읽기", pi)
            .setColor(Color.parseColor("#795c41"))
            .build()
        try {
            NotificationManagerCompat.from(ctx).notify(NOTIF_ID, n)
        } catch (e: SecurityException) {
            Log.w(TAG, "알림 권한 없음", e)
        }
    }

    /** 앱 미리보기용 작은 JPEG (data URI) */
    fun previewDataUri(ctx: Context, style: String): String? {
        val bundle = Digests.latest(ctx) ?: return null
        val p = Prefs(ctx)
        val (w, h) = screenSize(ctx)
        val pw = 360
        val ph = (h.toFloat() / w * pw).toInt()
        val bmp = compose(ctx, bundle, style, p.bg, pw, ph)
        val out = ByteArrayOutputStream()
        bmp.compress(Bitmap.CompressFormat.JPEG, 85, out)
        bmp.recycle()
        return "data:image/jpeg;base64," + Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
    }
}
