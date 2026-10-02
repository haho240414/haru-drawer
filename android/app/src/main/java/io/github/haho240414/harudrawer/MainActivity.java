package io.github.haho240414.harudrawer;

import android.content.Intent;
import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    // 이미 처리한 인텐트 (같은 인텐트를 두 번 처리하지 않게)
    private Intent lastHandled;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        // 이 앱 안의 플러그인: 맥 연결·주고받기·잠금화면 (HaruPlugin.kt)
        registerPlugin(HaruPlugin.class);
        // 화면이 다시 만들어진 경우(복원 — 잠금화면 배경을 바꾸면 안드로이드 12+ 는 배경색 테마 때문에 앱 화면을 새로 만든다)·
        // 최근 앱에서 연 경우엔 처음 연결 딥링크를 다시 처리하지 않는다.
        // BridgeActivity.load() 가 super.onCreate 안에서 onNewIntent(getIntent()) 를 부르므로 super 전에 표시해 둔다.
        Intent first = getIntent();
        boolean fromHistory = first != null && (first.getFlags() & Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY) != 0;
        if (savedInstanceState != null || fromHistory) lastHandled = first;
        super.onCreate(savedInstanceState);
        handleLink(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handleLink(intent);
    }

    private void handleLink(Intent intent) {
        if (intent == null || intent == lastHandled) return;
        lastHandled = intent;
        Links.INSTANCE.handle(getApplicationContext(), intent);
    }

    @Override
    public void onResume() {
        super.onResume();
        // 앱을 열 때마다 맥 소식 받아 오기
        if (new Prefs(this).getPaired()) SyncWorker.Companion.now(this);
    }
}
