# YouTube 전체 음성으로 정리하기

새로 저장한 영상은 YouTube 제공 전체 자막을 먼저 확인한다. 없거나 일부만 확보되면 공개 음성 스트림을 내려받아 Apple Silicon Mac에서 MLX Whisper로 전사한다. 브라우저 쿠키나 로그인 정보를 추출하지 않는다. 제한된 영상을 열지 못하면 미완료로 남긴다.

전문이 12,000자를 넘으면 모든 구간을 10,000자 이하로 나눠 차례대로 정리하고, 각 구간의 주장·근거·수치·사례·불확실한 부분을 모아 최종 요약을 만든다. 텍스트 끝을 잘라내지 않는다. 음성 전사와 구간 정리는 캐시되며 AI 장애가 나면 완료된 구간 다음부터 재개한다. 전문이 바뀌면 이전 분석을 재사용하지 않는다.

보고서에는 상세 요약과 ‘영상 전체 구간별 정리’를 표시한다. 날짜별 노트북 보관 폴더의 `전문/`에는 시간 표시 TXT 전문과 SRT 자막을 남기고 HTML·분류 파일에서 연결한다. 폰에는 요약·구간 정리를 기존 암호화된 보고서 형식으로 보낸다. 음성 다운로드 파일은 전사 후 제거하며 전문·모델은 전용 HARU_HOME 또는 지정한 캐시에 둔다.

## 설정과 실행

기존 엔진 Python은 보존하고 별도 Apple Silicon Python 3.11 환경에 `requirements-transcription.txt`를 설치한다. FFmpeg 실행 파일은 imageio-ffmpeg 패키지에 포함된다. 설정의 `transcription`에 다음을 지정한다.

```json
{"enabled": true, "python": "/전용환경/bin/python", "model": "mlx-community/whisper-medium-mlx", "cache_directory": "/전용모델캐시", "language": null, "max_seconds": 10800, "timeout": 3600}
```

기본 전사는 선택 설치 기능이며 활성화 후에는 새 영상에 자동 적용된다. 기존 날짜를 다시 작성하려면 전용 HARU_HOME/HARU_INBOX 환경에서 `python -m haru transcribe --day YYYY-MM-DD`를 실행한다. `--id 항목ID`로 한 편만 선택하거나 `--no-publish`로 파일만 갱신할 수 있다.

다운로드 길이와 영상 길이를 비교하고 전체 음성이 아닌 경우 성공 처리하지 않는다. 실시간 영상·3시간 초과 영상은 일부만 처리하지 않고 미완료로 남긴다. 전사 또는 전문 AI 분석 실패 시 `run.ok`가 false이며 CLI도 실패 코드로 끝난다. `transcription_pending`은 다음 실행에서 재시도한다. 전체를 처리했지만 발화가 인식되지 않은 음악/무음 가능 영상은 전문을 꾸며 쓰지 않고 제목·설명 기준임을 표시한다.

## 해석의 한계

전체 **음성**을 읽는 기능이다. 화면의 표·그래프·화면에만 적힌 글을 판독하지 않는다. 자동 전사는 수치·고유명사를 잘못 인식할 수 있어 원본 영상 확인이 필요하다. 제공 자막도 제작자가 발화를 빠뜨릴 수 있다. 경제 주장·전망은 제작자의 설명으로 표현하고 사실 검증이나 개인 투자 판단을 대신하지 않는다. 휴식 영상에는 억지 할 일을 만들지 않는다.

구현 근거: [MLX Whisper 공식 안내](https://github.com/ml-explore/mlx-examples/blob/main/whisper/README.md), [yt-dlp 공식 형식 선택 안내](https://github.com/yt-dlp/yt-dlp#format-selection).
