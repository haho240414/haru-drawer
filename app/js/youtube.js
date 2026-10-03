import { esc, icon } from "./common.js";
import { Source } from "./source.js";

const topics = ["경제", "AI", "휴식", "기타"];
const guess = (name) => /휴식|음악|재즈/.test(name) ? "휴식" : /ai|인공지능/i.test(name) ? "AI" : /경제|투자/.test(name) ? "경제" : "기타";

export async function showYoutube(view, toast, runNow) {
  const state = await Source.youtube();
  const settings = await Source.settings();
  let choices = state.playlists || [];
  const last = state.last_sync;
  const browserMode = state.mode === "browser";
  let checkedAt = "아직 확인하지 않았어요";
  if (last?.at) {
    try {
      checkedAt = new Intl.DateTimeFormat("ko-KR", { timeZone: settings.timezone || "Asia/Seoul", month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(last.at));
    } catch { checkedAt = last.at.slice(0, 16).replace("T", " "); }
  }
  view.innerHTML = `<div class="page-heading"><h1>유튜브 저장 목록</h1>
      <p>${state.enabled ? "새로 발견한 영상은 다음 보고서에 포함됩니다." : "저장한 영상을 하루 보고서로 모아 읽어보세요."}</p></div>
    <div class="youtube-status">
      <div>${browserMode ? (state.browser_ready ? '<span class="status-dot"></span><b>목록 확인 완료</b>' : '<span class="muted">목록 확인 대기</span>') : state.connected ? '<span class="status-dot"></span><b>계정 연결됨</b>' : '<span class="muted">계정 연결 전</span>'}
        ${!state.enabled ? '<span class="meta"> · 수집 꺼짐</span>' : ""}</div>
      <div class="schedule-note meta">${browserMode ? esc(state.browser_schedule || "예약 시각 설정 전") : `${esc((settings.schedule || []).join(" · "))} · ${esc(settings.timezone)}`}<br>노트북이 켜져 있어야 수집할 수 있습니다.</div>
    </div>

    <section class="card"><h2>${browserMode ? "연결한 재생목록" : "보고서에 넣을 재생목록"}</h2>
      <div class="api-actions" ${browserMode ? "hidden" : ""}>
        <div class="row2"><button class="btn primary small" id="ytConnect" ${state.configured ? "" : "disabled"}>${state.connected ? "Google 계정 다시 연결" : "Google 계정 연결"}</button>
          ${state.connected ? '<button class="btn small" id="ytDisconnect">이 노트북에서 연결 해제</button>' : ""}
          <button class="btn small" id="ytLoad" ${state.connected ? "" : "disabled"}>내 재생목록 불러오기</button></div>
        ${!state.configured ? '<p class="hint">아래 Google API 연결 설정에서 OAuth JSON을 등록하면 계정을 연결할 수 있습니다.</p>' : ""}
      </div>
      <div id="ytChoices"></div>
      <div class="api-actions" ${browserMode ? "hidden" : ""}>
        <label class="todo"><input type="checkbox" id="ytEnabled" ${state.enabled ? "checked" : ""} ${state.connected ? "" : "disabled"}><span>정리 시각마다 새 저장분 자동 수집</span></label>
        <div class="row2"><button class="btn primary small" id="ytSave" ${state.connected ? "" : "disabled"}>선택 저장</button>
          <button class="btn small" id="ytRun" ${state.connected && state.enabled ? "" : "disabled"}>새 영상 가져와서 정리</button></div>
      </div>
      <div id="ytMsg" class="meta" role="status"></div>
      <div id="ytAuthLink" class="meta auth-link"></div>
      <p class="info-note">${browserMode ? "처음 확인한 목록은 비교 기준으로 보관합니다. 이후 새로 발견한 영상만 보고서에 넣습니다." : "첫 수집에서는 오늘 저장한 영상을 가져옵니다. 이후 놓친 저장분은 최대 7일까지 확인합니다."}</p>
      <dl class="sync-facts"><div><dt>최근 확인</dt><dd>${esc(checkedAt)}</dd></div>
        <div><dt>새 영상</dt><dd>${last ? `${last.new || 0}개` : "확인 전"}</dd></div></dl>
      <p class="meta">${browserMode ? "영상의 정확한 저장일 대신 처음 발견한 날짜를 기록합니다." : "재생목록에 추가된 날짜를 기준으로 기록합니다."}</p>
      ${(last?.errors || []).map(e => `<p class="bad">${esc(e.name)}: ${esc(e.message)}</p>`).join("")}
    </section>

    <details class="youtube-details"><summary>${icon("chevron-right", "disclosure-icon")}수집 방식과 분석 범위</summary>
      <p class="meta">${browserMode ? "로그인된 Chrome에서 목록을 읽습니다. 노트북·Chrome·Codex가 실행되고 유튜브 로그인이 유지되어야 합니다." : "직접 만든 비공개 재생목록도 읽기 전용 연결로 가져올 수 있습니다. 노트북이 깨어 있고 하루서랍 상시 실행이 켜져 있어야 합니다."}</p>
      <p class="meta">새 영상이 있으면 AI 분석과 보고서 작성을 이어갑니다. 자막을 읽지 못하면 제목·설명 기준이라고 표시합니다. 원래 재생목록과 영상은 수정하지 않습니다.</p>
      <h3>나중에 볼 동영상</h3><p class="meta">유튜브 기본 ‘나중에 볼 동영상’은 공식 API에서 읽을 수 없습니다. ${browserMode ? "로그인된 Chrome 화면에서 이 목록도 함께 읽습니다. 전체 개수 확인에 실패하면 기존 수집 기준을 유지합니다." : "직접 만든 재생목록에 저장하거나, 공유 → 하루서랍으로 보내 주세요."}</p>
      ${last ? `<p class="meta">목록 반영 ${last.updated || 0}개${browserMode ? ` · 현재 목록 기준 ${(state.browser_baseline_count || 0).toLocaleString()}개` : ` · 예전/확인 불가 항목 ${last.skipped || 0}개`} · ${esc(settings.timezone)}</p>` : ""}
    </details>

    <details class="youtube-details" ${state.configured || browserMode ? "" : "open"}><summary>${icon("chevron-right", "disclosure-icon")}Google API 연결 설정${browserMode ? " · 선택" : ""}</summary>
      <p class="meta">브라우저의 유튜브 로그인과 별개의 연결입니다. Google Cloud에서 YouTube Data API v3를 켜고, OAuth 동의 화면의 테스트 사용자에 본인 계정을 등록한 뒤, ‘데스크톱 앱’용 OAuth 클라이언트 JSON을 등록하세요.</p>
      <a class="secondary-link" href="https://developers.google.com/youtube/v3/guides/auth/installed-apps" target="_blank" rel="noopener">Google 공식 연결 안내 ${icon("external-link")}</a>
      <div class="field"><label for="ytClient">데스크톱 앱 OAuth JSON</label><input type="file" accept=".json,application/json" id="ytClient"></div>
      ${browserMode && state.configured ? '<button class="btn small" id="ytApiConnect">Google API 계정 연결</button>' : ""}
      <p class="hint">YouTube 읽기 전용 권한만 요청합니다. 연결 정보는 이 노트북에 저장됩니다. Google 테스트 모드에서는 만료 후 다시 연결해야 할 수 있습니다.</p>
    </details>`;

  const drawChoices = () => {
    if (browserMode) {
      document.getElementById("ytChoices").innerHTML = choices.length ? `<table class="playlist-table"><caption class="sr-only">연결한 재생목록과 영상 수</caption>
        <thead><tr><th scope="col">재생목록</th><th scope="col">분류</th><th scope="col" class="number">영상 수</th></tr></thead><tbody>
        ${choices.map(p => `<tr><td><span class="playlist-name">${icon("square-play")}${esc(p.name)}</span></td><td>${esc(p.topic)}</td>
          <td class="number">${p.baseline?.reported_total != null ? p.baseline.reported_total.toLocaleString() : "확인 전"}</td></tr>`).join("")}</tbody></table>` : '<p class="meta">아직 연결한 재생목록이 없습니다.</p>';
      return;
    }
    document.getElementById("ytChoices").innerHTML = choices.length ? choices.map((p, i) => {
      const saved = state.playlists.find(s => s.id === p.id);
      const topic = saved?.topic || p.topic || guess(p.name);
      return `<div class="field"><label class="todo"><input type="checkbox" data-yt-pick="${i}" ${saved ? "checked" : ""}><span>${esc(p.name)}${p.count != null ? ` · ${p.count}개` : ""}</span></label>
        <select data-yt-topic="${i}" aria-label="${esc(p.name)} 보고서 주제">${topics.map(t => `<option ${topic === t ? "selected" : ""}>${t}</option>`).join("")}</select></div>`;
    }).join("") : '<p class="meta">계정을 연결하고 수집할 재생목록을 선택해 주세요.</p>';
  };
  drawChoices();
  const message = (text) => { document.getElementById("ytMsg").textContent = text; };
  document.getElementById("ytClient").onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      if (file.size > 64_000) throw new Error("OAuth JSON 파일을 확인해 주세요");
      await Source.youtubeClient(JSON.parse(await file.text()));
      toast("첫 연결 설정을 등록했어요");
      await showYoutube(view, toast, runNow);
    } catch (error) { message(error.message); }
  };
  document.getElementById("ytConnect").onclick = async () => {
    try {
      const result = await Source.youtubeConnect();
      document.getElementById("ytAuthLink").innerHTML = `<a href="${esc(result.url)}" target="_blank" rel="noopener">Google 연결 창 열기 ↗</a><br>연결 후 이 화면을 다시 열면 상태가 반영돼요.`;
      Source.openUrl(result.url);
    } catch (error) { message(error.message); }
  };
  const apiConnect = document.getElementById("ytApiConnect");
  if (apiConnect) apiConnect.onclick = document.getElementById("ytConnect").onclick;
  document.getElementById("ytLoad").onclick = async (e) => {
    e.target.disabled = true;
    message("내 재생목록을 가져오는 중…");
    try {
      choices = (await Source.youtubePlaylists()).playlists;
      drawChoices();
      message(`${choices.length}개 목록을 가져왔어요. 보고서에 넣을 목록과 주제를 선택하세요.`);
    } catch (error) { message(error.message); }
    e.target.disabled = false;
  };
  document.getElementById("ytSave").onclick = async () => {
    try {
      const selected = [...document.querySelectorAll("[data-yt-pick]:checked")].map(el => {
        const p = choices[Number(el.dataset.ytPick)];
        return { id: p.id, name: p.name, topic: document.querySelector(`[data-yt-topic="${el.dataset.ytPick}"]`).value };
      });
      await Source.youtubeSelection(selected, document.getElementById("ytEnabled").checked);
      toast("유튜브 수집 설정을 저장했어요");
      await showYoutube(view, toast, runNow);
    } catch (error) { message(error.message); }
  };
  document.getElementById("ytRun").onclick = () => runNow();
  const disconnect = document.getElementById("ytDisconnect");
  if (disconnect) disconnect.onclick = async () => {
    await Source.youtubeDisconnect();
    toast("이 노트북의 유튜브 연결 정보를 지웠어요");
    await showYoutube(view, toast, runNow);
  };
}
