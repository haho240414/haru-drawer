"""독립 MLX 환경에서 실행. 음성 파일은 임시 보관하고 전문만 원자적으로 저장한다."""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(job: dict) -> None:
    os.environ["HF_HOME"] = job["cache"]
    import imageio_ffmpeg
    import mlx_whisper
    import numpy as np
    import yt_dlp

    output = Path(job["output"])
    with tempfile.TemporaryDirectory(prefix="audio-", dir=output.parent) as td:
        def duration_filter(info, *, incomplete=False):
            if info.get("is_live"):
                return "실시간 영상은 전체 음성 완료를 확인할 수 없어요"
            duration = info.get("duration")
            if duration and duration > job["max_seconds"]:
                return "영상이 전사 길이 제한을 넘었어요. 일부만 처리하지 않습니다"
            return None
        opts = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True, "format": "bestaudio",
                "outtmpl": str(Path(td) / "audio.%(ext)s"), "socket_timeout": 30,
                "retries": 2, "extractor_retries": 1, "match_filter": duration_filter,
                "max_filesize": 512 * 1024 * 1024}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(job["url"], download=True)
        if not info or info.get("id") != job["video_id"]:
            raise RuntimeError("전체 음성을 내려받지 못했어요 (로그인·제한·영상 길이 확인 필요)")
        paths = [p for p in Path(td).glob("audio.*") if p.suffix not in {".part", ".ytdl"}]
        if len(paths) != 1:
            raise RuntimeError("다운로드가 불완전해요")
        result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-v", "error", "-i", str(paths[0]),
                                 "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                                capture_output=True, check=True, timeout=600)
        audio = np.frombuffer(result.stdout, np.int16).astype(np.float32) / 32768.0
        seconds = len(audio) / 16000
        expected = info.get("duration")
        if not expected or seconds < expected - max(3, expected * .01) or seconds > job["max_seconds"]:
            raise RuntimeError("음성 길이가 영상 전체 길이와 맞지 않아요. 완료 처리하지 않습니다")
        transcript = mlx_whisper.transcribe(audio, path_or_hf_repo=job["model"], language=job.get("language"),
                                           condition_on_previous_text=False, verbose=None,
                                           hallucination_silence_threshold=2.0, word_timestamps=True)
        segments = []
        for row in transcript.get("segments", []):
            start, end, text = float(row["start"]), float(row["end"]), row["text"].strip()
            if not (math.isfinite(start) and math.isfinite(end) and 0 <= start <= end <= seconds + 2):
                raise RuntimeError("전사 시간 표시가 잘못됐어요")
            if text:
                segments.append({"start": start, "end": min(end, seconds), "text": text})
        data = {"complete": True, "video_id": job["video_id"], "model": job["model"],
                "processed_seconds": seconds, "expected_seconds": expected,
                "language": transcript.get("language"), "segments": segments, "no_speech": not bool(segments)}
        tmp = output.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        tmp.chmod(0o600)
        tmp.replace(output)


if __name__ == "__main__":
    try:
        run(json.loads(Path(sys.argv[1]).read_text("utf-8")))
    except Exception as e:
        print(f"{type(e).__name__}: {str(e)[:240]}", file=sys.stderr)
        sys.exit(1)
