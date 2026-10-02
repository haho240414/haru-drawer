"""AI 호출. 기본은 Codex CLI (이 맥의 ChatGPT 구독으로 로그인 — API 요금 없음).

함정: `codex exec -i <FILE>...` 는 뒤따르는 인자를 전부 이미지로 먹는다 → 프롬프트는 항상 stdin 으로 보낸다.
출력은 --output-schema(JSON 스키마)로 모양을 강제하고 -o 파일로 마지막 답만 받는다 (stdout 은 진행 로그).
스키마는 OpenAI 엄격 모드 규칙: 모든 객체에 additionalProperties=false, 모든 속성을 required 에.
"""
from __future__ import annotations

import base64
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests


class LLMError(RuntimeError):
    pass


class LLMQuotaError(LLMError):
    """구독 사용 한도 초과 — retry_at(유닉스 초)까지 이 백엔드를 쉬게 한다."""

    def __init__(self, msg: str, retry_at: float):
        super().__init__(msg)
        self.retry_at = retry_at


RE_RETRY = re.compile(r"try again at (\d{1,2}):(\d{2})\s*([AP]M)?", re.IGNORECASE)


def parse_retry_at(text: str, now_ts: float | None = None) -> float:
    """codex 의 'try again at 3:11 AM'(맥 현지 시각) → 유닉스 초. 못 읽으면 30분 뒤."""
    now_ts = time.time() if now_ts is None else now_ts
    m = RE_RETRY.search(text or "")
    if not m:
        return now_ts + 1800
    h, mi = int(m.group(1)), int(m.group(2))
    ap = (m.group(3) or "").upper()
    if mi > 59 or (ap and not 1 <= h <= 12) or (not ap and h > 23):
        return now_ts + 1800
    if ap == "PM" and h != 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    base = datetime.fromtimestamp(now_ts)          # 맥 현지 시각 기준 (codex 가 그렇게 찍음)
    t = base.replace(hour=h, minute=mi, second=0, microsecond=0)
    if t.timestamp() <= now_ts:
        t += timedelta(days=1)
    return t.timestamp() + 60


def parse_response(raw: str, backend: str) -> dict:
    """잘못된 JSON 답도 백엔드 실패로 다뤄 보고서 생성을 계속한다."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        try:
            data = json.loads(raw[start:end + 1]) if start >= 0 and end > start else None
        except json.JSONDecodeError:
            data = None
    if not isinstance(data, dict):
        raise LLMError(f"{backend} 답이 JSON 객체가 아니에요: {raw[:120]}")
    return data


CODEX_CANDIDATES = [
    "/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex",
    "/Applications/*.app/Contents/Resources/codex-cli/bin/codex",
    "/Applications/*.app/Contents/Resources/codex",
    os.path.expanduser("~/.local/bin/codex"),
    "/opt/homebrew/bin/codex",
    "/usr/local/bin/codex",
]


def find_codex() -> str | None:
    env = os.environ.get("HARU_CODEX")
    if env and Path(env).exists():
        return env
    for pat in CODEX_CANDIDATES:
        for p in sorted(glob.glob(pat)):
            if os.access(p, os.X_OK):
                return p
    return shutil.which("codex")


def strict_schema(schema: dict) -> dict:
    """모든 객체를 엄격 모드 규칙에 맞춘다 (빠뜨리기 쉬워서 자동으로)."""
    if isinstance(schema, dict):
        if schema.get("type") == "object" and "properties" in schema:
            schema["additionalProperties"] = False
            schema["required"] = list(schema["properties"].keys())
            for v in schema["properties"].values():
                strict_schema(v)
        if schema.get("type") == "array" and "items" in schema:
            strict_schema(schema["items"])
    return schema


def run_codex(prompt: str, schema: dict, images: list[Path] = (), effort: str = "low",
              timeout: int = 300, model: str | None = None) -> dict:
    exe = find_codex()
    if not exe:
        raise LLMError("Codex CLI 를 찾지 못했어요 (ChatGPT 앱 설치·로그인 필요)")
    with tempfile.TemporaryDirectory(prefix="haru-codex-") as td:
        td = Path(td)
        work = td / "work"
        work.mkdir()
        sp, op = td / "schema.json", td / "out.json"
        sp.write_text(json.dumps(strict_schema(schema), ensure_ascii=False), "utf-8")
        cmd = [exe, "exec", "-s", "read-only", "--skip-git-repo-check", "--ephemeral", "-C", str(work),
               "-c", f'model_reasoning_effort="{effort}"', "--color", "never",
               "--output-schema", str(sp), "-o", str(op)]
        if model:
            cmd += ["-m", model]
        for img in images:
            cmd += ["-i", str(img)]
        t0 = time.time()
        try:
            proc = subprocess.run(cmd, input=prompt, text=True, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise LLMError(f"Codex 응답이 {timeout}초를 넘었어요")
        if proc.returncode != 0 or not op.exists():
            out = (proc.stderr or "") + (proc.stdout or "")
            if "usage limit" in out.lower() or "rate limit" in out.lower():
                line = next((ln for ln in out.splitlines() if "limit" in ln.lower()), "사용 한도 초과")
                raise LLMQuotaError(f"Codex 사용 한도: {line.strip()[:200]}", parse_retry_at(out))
            raise LLMError(f"Codex 실패 (코드 {proc.returncode}): {out[-600:]}")
        raw = op.read_text("utf-8").strip()
        data = parse_response(raw, "Codex")
        data["_llm"] = {"backend": "codex", "sec": round(time.time() - t0, 1), "effort": effort}
        return data


def run_ollama(prompt: str, schema: dict, images: list[Path] = (), model: str = "qwen3.6:27b",
               timeout: int = 300) -> dict:
    msg: dict = {"role": "user", "content": prompt}
    if images:
        msg["images"] = [base64.b64encode(Path(p).read_bytes()).decode() for p in images]
    t0 = time.time()
    try:
        r = requests.post("http://127.0.0.1:11434/api/chat", timeout=timeout, json={
            "model": model, "messages": [msg], "format": strict_schema(schema), "stream": False,
            "options": {"temperature": 0.2}, "think": False})
        r.raise_for_status()
        data = parse_response(r.json()["message"]["content"], "ollama")
    except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
        raise LLMError(f"ollama 실패: {e}")
    data["_llm"] = {"backend": "ollama", "model": model, "sec": round(time.time() - t0, 1)}
    return data


def _cooldown(backend: str) -> float:
    try:
        from . import store
        c = store.kv_get(f"llm_cooldown_{backend}") or {}
        return float(c.get("until", 0))
    except Exception:
        return 0.0


def _set_cooldown(backend: str, until: float, msg: str) -> None:
    try:
        from . import store
        store.kv_set(f"llm_cooldown_{backend}", {"until": until, "msg": msg})
        store.log_event("llm", f"{backend} 잠시 쉼 ({datetime.fromtimestamp(until):%H:%M}까지, 맥 시각): {msg[:120]}")
    except Exception:
        pass


def chain(settings: dict | None) -> list[str]:
    """이번에 시도할 AI 순서: 기본 → 대체(ollama). 한도로 쉬는 중인 건 뺀다."""
    s = (settings or {}).get("llm", {})
    if s.get("backend") == "fake":
        return []
    order = [s.get("backend", "codex")]
    fb = s.get("fallback", "ollama")
    if fb and fb not in order and fb != "none":
        order.append(fb)
    return [b for b in order if b != "fake" and _cooldown(b) <= time.time()]


def available(settings: dict | None) -> bool:
    return bool(chain(settings))


def run_json(prompt: str, schema: dict, images: list[Path] = (), settings: dict | None = None,
             effort: str | None = None, retries: int = 1) -> dict:
    s = (settings or {}).get("llm", {})
    order = chain(settings)
    if not order:
        raise LLMError("쓸 수 있는 AI 가 없어요 (사용 한도로 쉬는 중)")
    last: Exception | None = None
    for backend in order:
        for attempt in range(retries + 1):
            try:
                if backend == "codex":
                    return run_codex(prompt, json.loads(json.dumps(schema)), list(images),
                                     effort=effort or s.get("effort", "low"),
                                     timeout=int(s.get("timeout", 300)), model=s.get("model"))
                if backend == "ollama":
                    return run_ollama(prompt, json.loads(json.dumps(schema)), list(images),
                                      model=s.get("ollama_model", "qwen3.6:27b"),
                                      timeout=int(s.get("ollama_timeout", 1200)))
                raise LLMError(f"알 수 없는 AI 백엔드: {backend}")
            except LLMQuotaError as e:
                _set_cooldown(backend, e.retry_at, str(e))
                last = e
                break                      # 같은 백엔드 재시도 없이 다음(대체)으로
            except LLMError as e:
                last = e
                if backend != "codex" or attempt >= retries:
                    # 꺼진 로컬 모델을 묶음마다 다시 부르거나, 다음 정리에서
                    # 곧바로 같은 규칙 기반 보고서를 재생성하지 않는다.
                    _set_cooldown(backend, time.time() + max(30, int(s.get("failure_cooldown_sec", 300))), str(e))
                    break
                time.sleep(8)
    raise last or LLMError("AI 호출 실패")


def batch_size(settings: dict) -> int:
    """지금 쓸 AI 에 맞는 묶음 크기 (로컬 모델은 느려서 작게)."""
    s = settings.get("llm", {})
    order = chain(settings)
    if order and order[0] == "ollama":
        return int(s.get("ollama_batch", 3))
    return int(s.get("batch", 5))


def check(settings: dict) -> dict:
    """설정 화면용: 지금 AI 를 쓸 수 있는지."""
    backend = settings.get("llm", {}).get("backend", "codex")
    if backend == "codex":
        exe = find_codex()
        if not exe:
            return {"ok": False, "backend": backend, "msg": "Codex CLI 없음"}
        try:
            p = subprocess.run([exe, "login", "status"], capture_output=True, text=True, timeout=20)
            out = (p.stdout + p.stderr).strip()
            return {"ok": "Logged in" in out, "backend": backend, "msg": out[:120], "path": exe}
        except Exception as e:
            return {"ok": False, "backend": backend, "msg": str(e)[:120]}
    if backend == "ollama":
        try:
            r = requests.get("http://127.0.0.1:11434/api/tags", timeout=5)
            names = [m["name"] for m in r.json().get("models", [])]
            want = settings["llm"].get("ollama_model")
            return {"ok": want in names, "backend": backend, "msg": ", ".join(names[:6])}
        except Exception as e:
            return {"ok": False, "backend": backend, "msg": str(e)[:120]}
    return {"ok": backend == "fake", "backend": backend, "msg": "시험용 규칙 기반"}
