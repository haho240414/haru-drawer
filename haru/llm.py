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
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import requests


class LLMError(RuntimeError):
    pass


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
            tail = (proc.stderr or proc.stdout or "")[-600:]
            raise LLMError(f"Codex 실패 (코드 {proc.returncode}): {tail}")
        raw = op.read_text("utf-8").strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            start, end = raw.find("{"), raw.rfind("}")
            if start < 0:
                raise LLMError(f"Codex 답이 JSON 이 아니에요: {raw[:200]}")
            data = json.loads(raw[start:end + 1])
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
        data = json.loads(r.json()["message"]["content"])
    except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
        raise LLMError(f"ollama 실패: {e}")
    data["_llm"] = {"backend": "ollama", "model": model, "sec": round(time.time() - t0, 1)}
    return data


def run_json(prompt: str, schema: dict, images: list[Path] = (), settings: dict | None = None,
             effort: str | None = None, retries: int = 1) -> dict:
    s = (settings or {}).get("llm", {})
    backend = s.get("backend", "codex")
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            if backend == "codex":
                return run_codex(prompt, json.loads(json.dumps(schema)), list(images),
                                 effort=effort or s.get("effort", "low"),
                                 timeout=int(s.get("timeout", 300)), model=s.get("model"))
            if backend == "ollama":
                return run_ollama(prompt, json.loads(json.dumps(schema)), list(images),
                                  model=s.get("ollama_model", "qwen3.6:27b"), timeout=int(s.get("timeout", 300)))
            raise LLMError(f"알 수 없는 AI 백엔드: {backend}")
        except LLMError as e:
            last = e
            if attempt < retries:
                time.sleep(8)
    raise last or LLMError("AI 호출 실패")


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
