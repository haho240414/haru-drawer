package io.github.haho240414.harudrawer

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import android.widget.Toast
import org.json.JSONObject

/**
 * 딥링크: haru://pair/HARU1.… (맥 QR 을 기본 카메라로 찍어도 앱이 열려 연결됨), haru://sync (바로 주고받기)
 * 점검(CI)에서도 이 길로 연결·동기화를 시킨다.
 */
object Links {
    private const val TAG = "HaruLinks"

    fun handle(ctx: Context, intent: Intent?): Boolean {
        val data = intent?.data ?: return false
        if (data.scheme != "haru") return false
        when (data.host) {
            "pair" -> {
                val code = data.toString().substringAfter("haru://pair/", "")
                HaruPlugin.io.execute {
                    try {
                        val p = Pairing.parse(code)
                        val prefs = Prefs(ctx)
                        val same = prefs.key == p.key && prefs.up == p.up && prefs.down == p.down && prefs.server == p.server
                        if (!same) prefs.savePairing(p)   // 같은 코드를 또 열면 받은 기록을 지우지 않는다
                        SyncWorker.schedule(ctx)
                        val r = SyncEngine.run(ctx)
                        Log.i(TAG, "연결: ${p.name} ${r}")
                        HaruPlugin.emit("paired", JSONObject().put("mac", p.name))
                    } catch (e: Exception) {
                        Log.w(TAG, "연결 실패", e)
                        android.os.Handler(android.os.Looper.getMainLooper()).post {
                            Toast.makeText(ctx, "연결 코드를 읽지 못했어요: ${e.message}", Toast.LENGTH_LONG).show()
                        }
                    }
                }
                return true
            }
            "sync" -> {
                HaruPlugin.io.execute {
                    val r = SyncEngine.run(ctx)
                    Log.i(TAG, "동기화: $r")
                }
                return true
            }
        }
        return false
    }
}

/** 폰을 다시 켜거나 앱을 업데이트하면 15분 주기 주고받기를 다시 건다 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (Prefs(context).paired) SyncWorker.schedule(context)
    }
}
