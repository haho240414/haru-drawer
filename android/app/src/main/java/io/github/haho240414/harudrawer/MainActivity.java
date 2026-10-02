package io.github.haho240414.harudrawer;

import android.content.Intent;
import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    // BridgeActivity.load() 가 onCreate 안에서 onNewIntent 를 부르기도 해서 같은 인텐트를 두 번 처리하지 않게
    private Intent lastHandled;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        // 이 앱 안의 플러그인: 맥 연결·주고받기·잠금화면 (HaruPlugin.kt)
        registerPlugin(HaruPlugin.class);
        super.onCreate(savedInstanceState);
        // 화면이 다시 만들어진 경우(복원)·최근 앱에서 연 경우엔 처음 연결 딥링크를 다시 처리하지 않는다
        boolean fromHistory = (getIntent().getFlags() & Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY) != 0;
        if (savedInstanceState == null && !fromHistory) handleLink(getIntent());
        else lastHandled = getIntent();
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
