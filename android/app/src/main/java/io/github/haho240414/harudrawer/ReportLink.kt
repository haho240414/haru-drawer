package io.github.haho240414.harudrawer

import java.net.URI
import java.time.LocalDate

/** 알림을 눌렀을 때 웹 화면이 준비되기 전에도 목적지를 보관한다. */
object ReportLink {
    private var pending: String? = null

    fun dayFrom(url: String): String? = try {
        val uri = URI(url)
        val day = uri.path.removePrefix("/")
        if (uri.scheme == "haru" && uri.host == "report" && uri.query == null && uri.fragment == null &&
            Regex("""\d{4}-\d{2}-\d{2}""").matches(day)) LocalDate.parse(day).toString() else null
    } catch (_: Exception) { null }

    @Synchronized fun offer(day: String) { pending = day }
    @Synchronized fun take(): String? = pending.also { pending = null }
}
