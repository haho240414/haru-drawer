package io.github.haho240414.harudrawer

import android.content.Context
import android.content.SharedPreferences

/** 앱 설정·연결 정보·주고받기 상태 (SharedPreferences 하나) */
class Prefs(ctx: Context) {
    private val sp: SharedPreferences = ctx.applicationContext.getSharedPreferences("haru", Context.MODE_PRIVATE)

    private fun str(k: String) = sp.getString(k, null)
    private fun put(k: String, v: String?) = sp.edit().putString(k, v).apply()

    // ----- 맥 연결 (페어링 코드에서) -----
    var server: String? get() = str("server"); set(v) = put("server", v)
    var up: String? get() = str("up"); set(v) = put("up", v)
    var down: String? get() = str("down"); set(v) = put("down", v)
    var key: String? get() = str("key"); set(v) = put("key", v)
    var macName: String? get() = str("macName"); set(v) = put("macName", v)
    val paired: Boolean get() = !up.isNullOrEmpty() && !down.isNullOrEmpty() && !key.isNullOrEmpty() && !server.isNullOrEmpty()

    fun relay(): Relay? = if (paired) Relay(server!!, up!!, down!!, key!!) else null

    fun savePairing(p: Pairing) {
        sp.edit().putString("server", p.server).putString("up", p.up).putString("down", p.down)
            .putString("key", p.key).putString("macName", p.name)
            .putLong("downSince", 0L).putString("seen", "").putLong("helloAt", 0L).putString("helloVer", null)
            .apply()
    }

    fun clearPairing() {
        sp.edit().remove("server").remove("up").remove("down").remove("key").remove("macName")
            .remove("downSince").remove("seen").remove("lastHb").remove("macNext").remove("macDay").apply()
    }

    // ----- 잠금화면 설정 -----
    var wallpaper: Boolean get() = sp.getBoolean("wallpaper", true); set(v) = sp.edit().putBoolean("wallpaper", v).apply()
    var notify: Boolean get() = sp.getBoolean("notify", true); set(v) = sp.edit().putBoolean("notify", v).apply()
    var style: String get() = str("style") ?: "A"; set(v) = put("style", v)
    var bg: String get() = str("bg") ?: "gradient"; set(v) = put("bg", v)
    /** 같은 보고서·같은 모양이면 배경을 다시 설정하지 않으려고 기억 */
    var appliedKey: String? get() = str("appliedKey"); set(v) = put("appliedKey", v)
    /** 우리가 잠금화면 배경을 바꾼 적이 있는지 (끌 때 되돌리기) */
    var wallpaperSet: Boolean get() = sp.getBoolean("wallpaperSet", false); set(v) = sp.edit().putBoolean("wallpaperSet", v).apply()

    // ----- 주고받기 상태 -----
    var downSince: Long get() = sp.getLong("downSince", 0L); set(v) = sp.edit().putLong("downSince", v).apply()
    var seen: List<String>
        get() = (str("seen") ?: "").split(',').filter { it.isNotEmpty() }
        set(v) = put("seen", v.takeLast(300).joinToString(","))
    var lastHb: String? get() = str("lastHb"); set(v) = put("lastHb", v)
    var macNext: String? get() = str("macNext"); set(v) = put("macNext", v)
    var macDay: String? get() = str("macDay"); set(v) = put("macDay", v)
    var lastSync: Long get() = sp.getLong("lastSync", 0L); set(v) = sp.edit().putLong("lastSync", v).apply()
    var lastError: String? get() = str("lastError"); set(v) = put("lastError", v)
    var helloAt: Long get() = sp.getLong("helloAt", 0L); set(v) = sp.edit().putLong("helloAt", v).apply()
    var helloVer: String? get() = str("helloVer"); set(v) = put("helloVer", v)
    /** 첨부가 만료돼 맥에 다시 보내 달라고 한 보고서 (같은 걸 계속 조르지 않게) */
    var resendAsked: String? get() = str("resendAsked"); set(v) = put("resendAsked", v)

    // ----- 할 일 체크 (폰에서 누른 것) -----
    var todosDone: Set<String>
        get() = sp.getStringSet("todosDone", emptySet()) ?: emptySet()
        set(v) = sp.edit().putStringSet("todosDone", v.toSet()).apply()
}
