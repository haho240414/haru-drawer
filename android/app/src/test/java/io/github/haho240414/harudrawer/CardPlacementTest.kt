package io.github.haho240414.harudrawer

import org.junit.Assert.*
import org.junit.Test

class CardPlacementTest {
    @Test fun smallScreenKeepsCardInsideSelectedZoneWithoutDistortion() {
        for (position in listOf("top", "bottom")) {
            val b = CardPlacement.box(320, 640, 284, 210, position, 16)
            assertTrue(b[0] >= 16 && b[2] <= 304)
            assertTrue(b[1] >= 0 && b[3] <= 640)
            assertEquals(284.0 / 210, (b[2] - b[0]).toDouble() / (b[3] - b[1]), 0.02)
            if (position == "top") assertTrue(b[3] <= 640 * .35) else assertTrue(b[1] >= 640 * .67)
        }
    }
    @Test fun largeScreenDoesNotExpandCardPastHorizontalMargins() {
        val b = CardPlacement.box(1080, 2340, 1000, 120, "top", 54)
        assertTrue(b[0] >= 54 && b[2] <= 1026)
        assertEquals(1000.0 / 120, (b[2] - b[0]).toDouble() / (b[3] - b[1]), 0.08)
    }
}
