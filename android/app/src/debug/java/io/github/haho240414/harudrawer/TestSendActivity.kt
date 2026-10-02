package io.github.haho240414.harudrawer

import android.app.Activity
import android.content.ClipData
import android.content.Intent
import android.os.Bundle
import android.util.Log
import androidx.core.content.FileProvider
import java.io.File

/**
 * 점검용(디버그 빌드에만): cache/<file> 을 실제 앱이 공유하듯 FileProvider 주소 + 읽기 권한으로 ShareActivity 에 보낸다.
 * adb 셸은 갤러리·다운로드 파일의 읽기 권한을 남의 앱에 넘겨줄 수 없어서(SecurityException) 이 길로 시험한다.
 *   am start -n <pkg>/.TestSendActivity --es file share/x.png --es mime image/png
 */
class TestSendActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        try {
            val f = File(cacheDir, intent.getStringExtra("file") ?: "")
            val mime = intent.getStringExtra("mime") ?: "application/octet-stream"
            val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", f)
            val send = Intent(Intent.ACTION_SEND).setType(mime).setClass(this, ShareActivity::class.java)
                .putExtra(Intent.EXTRA_STREAM, uri)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            send.clipData = ClipData.newRawUri("", uri)
            intent.getStringExtra("text")?.let { send.putExtra(Intent.EXTRA_TEXT, it) }
            startActivity(send)
            Log.i("HaruTestSend", "보냄 $uri ($mime, ${f.length()}B)")
        } catch (e: Exception) {
            Log.w("HaruTestSend", "실패", e)
        }
        finish()
    }
}
