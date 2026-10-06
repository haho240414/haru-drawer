package io.github.haho240414.harudrawer

import kotlin.math.roundToInt

/** 투명 카드의 실제 내용만 옮길 때 글자 비율과 화면 안쪽 여백을 유지한다. */
object CardPlacement {
    fun box(w: Int, h: Int, cw: Int, ch: Int, position: String, margin: Int): IntArray {
        val top = if (position == "top") h * 0.12f else h * 0.68f
        val bottom = if (position == "top") h * 0.34f else h * 0.90f
        val scale = minOf((w - 2 * margin).coerceAtLeast(1).toFloat() / cw, (bottom - top) / ch)
        val width = (cw * scale).roundToInt().coerceAtLeast(1)
        val height = (ch * scale).roundToInt().coerceAtLeast(1)
        val x = (w - width) / 2
        val y = ((top + bottom - height) / 2).roundToInt()
        return intArrayOf(x, y, x + width, y + height)
    }
}
