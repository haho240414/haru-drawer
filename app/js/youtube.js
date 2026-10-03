import { esc } from "./common.js";
import { Source } from "./source.js";

const topics = ["경제", "AI", "휴식", "기타"];
const guess = (name) => /휴식|음악|재즈/.test(name) ? "휴식" : /ai|인공지능/i.test(name) ? "AI" : /경제|투자/.test(name) ? "경제" : "기타";

export async function showYoutube(view, toast, runNow) {
  const state = await Source.youtube();
  const settings = await Source.settings();
  let choices = state.playlists || [];
  const last = state.last_sync;
  const browserMode = state.mode === "browser";
  view.innerHTML = `<h2 style="margin:20px 0 6px">유튜브 저장 영상</h2>
    <section class="card"><h2>저장한 관심사를 하루 보고서로</h2>
      <p class="meta">경제·AI·휴식 재생목록에서 새로 저장한 영상을 모아 정리해요. 앱에서 자세히 읽고, 잠금화면에서는 핵심을 보고, 노트북에는 같은 보고서를 파일로 남겨요.</p>
      <p class="meta">${browserMode ? "처음 확인한 목록은 기준으로만 보관해요. 다음 확인에서 새로 나타난 영상을 보고서에 넣어요. 개별 저장일은 알 수 없어 처음 발견한 날짜로 표시해요." : "처음에는 오늘 저장한 영상만 가져와요. 다음부터는 놓친 저장분을 최대 7일까지 가져와요."} 자막을 못 읽으면 제목·설명 기준이라고 표시해요.</p>
      <p>${browserMode ? (state.browser_ready ? '<span class="ok">● Chrome 기준 목록 준비됨</span>' : '<span class="muted">Chrome 기준 목록 확인 중</span>') : state.connected ? '<span class="ok">● 계정 연결됨</span>' : '<span class="muted">계정 연결 전</span>'} · ${state.enabled ? "수집 켜짐" : "수집 꺼짐"}</p>
      <p class="meta">${browserMode ? `브라우저 예약 수집: ${esc(state.browser_schedule || "예약 시각 설정 중")}<br>노트북·Chrome·Codex가 실행되고 유튜브 로그인이 유지되어야 해요.` : `자동 정리 시각: ${esc((settings.schedule || []).join(" · "))} (${esc(settings.timezone)})<br>노트북이 깨어 있고 하루서랍 상시 실행이 켜져 있어야 해요.`}</p>
      <div class="row2" ${browserMode ? 'style="display:none"' : ""}><button class="btn primary small" id="ytConnect" ${state.configured ? "" : "disabled"}>${state.connected ? "Google 계정 다시 연결" : "Google 계정 연결"}</button>
        ${state.connected ? '<button class="btn small" id="ytDisconnect">이 노트북에서 연결 해제</button>' : ""}</div>
      <div id="ytAuthLink" class="meta" style="margin-top:10px"></div>
      ${!state.configured && !browserMode ? '<p class="hint">이 개인 앱의 Google 연결 설정을 먼저 등록하면 계정 연결 버튼이 열려요. 아래 첫 연결 설정을 확인해 주세요.</p>' : ""}
    </section>
    <section class="card"><h2>보고서에 넣을 재생목록</h2>
      <p class="meta">${browserMode ? "로그인된 Chrome에서 아래 목록을 읽어요. 새 영상이 발견되면 AI 분석과 보고서 작성이 이어져요." : "직접 만든 비공개 재생목록도 읽기 전용 연결로 가져올 수 있어요."} 원래 재생목록과 영상은 수정하지 않아요.</p>
      <button class="btn small" id="ytLoad" ${browserMode ? 'style="display:none"' : ""} ${state.connected ? "" : "disabled"}>내 재생목록 불러오기</button>
      <div id="ytChoices" style="margin-top:16px"></div>
      <label class="todo" ${browserMode ? 'style="display:none"' : ""}><input type="checkbox" id="ytEnabled" ${state.enabled ? "checked" : ""} ${state.connected ? "" : "disabled"}><span>정리 시각마다 새 저장분 자동 수집</span></label>
      <div class="row2" ${browserMode ? 'style="display:none"' : ""}><button class="btn primary small" id="ytSave" ${state.connected ? "" : "disabled"}>선택 저장</button>
        <button class="btn small" id="ytRun" ${state.connected && state.enabled ? "" : "disabled"}>새 영상 가져와서 정리</button></div>
      <div id="ytMsg" class="meta" role="status" style="margin-top:12px"></div>
    </section>
    <section class="card"><h2>나중에 볼 동영상</h2>
      <p class="meta">유튜브 기본 ‘나중에 볼 동영상’은 공식 API에서 읽을 수 없어요. ${browserMode ? "로그인된 Chrome 화면에서 이 목록도 함께 읽어요." : "직접 만든 재생목록에 저장하거나, 영상에서 공유 → 하루서랍으로 보내 주세요."}</p>
      <p class="hint">${browserMode ? "전체 개수 확인에 실패하면 기존 수집 기준을 유지해요." : "브라우저에서 읽는 수집은 별도 설정이 필요해요."}</p>
    </section>
    <section class="card"><h2>최근 수집</h2><div class="meta">${last ? `${esc(last.at?.slice(0, 19).replace("T", " "))}<br>새 영상 ${last.new || 0}개 · 목록 반영 ${last.updated || 0}개${browserMode ? ` · 현재 목록 기준 ${(state.browser_baseline_count || 0).toLocaleString()}개` : ` · 예전/확인 불가 항목 ${last.skipped || 0}개`}` : "아직 수집하지 않았어요"}</div>
      ${(last?.errors || []).map(e => `<p class="bad">${esc(e.name)}: ${esc(e.message)}</p>`).join("")}</section>
    <section class="card"><details ${state.configured || browserMode ? "" : "open"}><summary>공식 API 연결 설정${browserMode ? " (선택)" : ""}</summary>
      <p class="meta">앱 연결은 브라우저의 유튜브 로그인과 별개예요. Google Cloud에서 YouTube Data API v3를 켜고, OAuth 동의 화면의 테스트 사용자에 본인 계정을 등록한 뒤, ‘데스크톱 앱’용 OAuth 클라이언트 JSON을 내려받아 등록하세요.</p>
      <a class="meta" href="https://developers.google.com/youtube/v3/guides/auth/installed-apps" target="_blank" rel="noopener">Google 공식 연결 안내 ↗</a>
      <div class="field" style="margin-top:12px"><label for="ytClient">데스크톱 앱 OAuth JSON</label><input type="file" accept=".json,application/json" id="ytClient"></div>
      ${browserMode && state.configured ? '<button class="btn small" id="ytApiConnect">Google API 계정 연결</button>' : ""}
      <p class="hint">계정 연결은 YouTube 읽기 전용 권한만 요청해요. 연결 정보는 이 노트북에만 저장돼요. Google의 테스트 모드에서는 연결이 만료되어 다시 연결해야 할 수 있어요.</p>
    </details></section>`;

  const drawChoices = () => {
    if (browserMode) {
      document.getElementById("ytChoices").innerHTML = choices.map(p => `<div class="todo"><span class="ok">✓</span><span style="flex:1">${esc(p.name)}${p.baseline?.reported_total != null ? ` · ${p.baseline.reported_total.toLocaleString()}개` : ""}</span><span class="meta">${esc(p.topic)}</span></div>`).join("");
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
