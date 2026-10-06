package io.github.haho240414.harudrawer

import org.junit.Assert.*
import org.junit.Test

class ReportLinkTest {
    @Test fun routesOnlyValidReportDates() {
        assertEquals("2026-10-05", ReportLink.dayFrom("haru://report/2026-10-05"))
        assertEquals("2024-02-29", ReportLink.dayFrom("haru://report/2024-02-29"))
        for (url in listOf("haru://report/2026-02-29", "haru://report/../../secret", "haru://pair/2026-10-05",
            "https://report/2026-10-05", "haru://report/2026-10-05?x=1", "haru://report/2026-10-05#settings")) {
            assertNull(url, ReportLink.dayFrom(url))
        }
    }
    @Test fun keepsColdLaunchAndConsumesOnce() {
        ReportLink.take()
        ReportLink.offer("2026-10-04")
        ReportLink.offer("2026-10-05")
        assertEquals("2026-10-05", ReportLink.take())
        assertNull(ReportLink.take())
    }
}
