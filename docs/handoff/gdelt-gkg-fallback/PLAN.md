# PLAN: GDELT DOC API 대체 수집 경로 (GKG 원본 파일)

## 배경
- GDELT DOC API 색인이 2026-10-25경부터 멈춤. Actions에서는 11-06부터 429가 풀리지 않아
  `news_monitor`가 실패하고 메일 제목이 [점검]이 됨. `data/news.json`은 11-05 이후 갱신 없음(latest 10-24).
- 원본 15분 파일(`https://data.gdeltproject.org/gdeltv2/lastupdate.txt`, 301 → https)은 정상 갱신.
- 현재 지표: 하루 전체 기사 중 관련 기사 비율(만 건당), 직전 28일 중앙값·MAD robust z.

## 목표
DOC API가 실패하면(429/빈 데이터/지연) 원본 GKG 파일에서 같은 지표를 직접 계산해 `data/news.json`을 갱신한다.

## 범위 (수정 가능 파일)
- `news_monitor.py` — 폴백 호출 연결
- `gdelt_gkg.py` (신규) — GKG 수집·집계
- `tests/test_gdelt_gkg.py` (신규) — 합성 데이터 테스트
- `.github/workflows/hotel.yml`·`index.html`·`mail_report.py`·`daily_report.py`는 수정 금지.
  news.json 스키마(`series[].date/count/total/share/tone/partial`, `latest`, `articles`)는 그대로 유지.

## 명세
1. 대상일의 15분 파일 목록은 `http://data.gdeltproject.org/gdeltv2/masterfilelist.txt`(또는 날짜 규칙 URL
   `https://data.gdeltproject.org/gdeltv2/YYYYMMDDHHMMSS.gkg.csv.zip`)에서 얻는다. 리다이렉트 따라감.
2. 하루 96개 파일을 스트리밍으로 읽어 파일을 저장하지 않고 집계만 한다(저장소에 원본 커밋 금지).
   - total = 그날 GKG 레코드 수
   - count = 관련 레코드 수. 관련 = 영어 기준 V2Themes/제목·URL에 "north korea" 또는 "korean peninsula"가
     있고 전쟁 키워드(war, missile, attack, invasion, evacuation, troops)가 함께 있는 레코드.
     실제 GKG 컬럼 기준(V2Themes, V2Tone, DocumentIdentifier)은 구현자가 확인해 RESULT에 명시.
   - tone = 관련 레코드 V2Tone 첫 값 평균
3. 증분 집계: `data/news_gkg_daily.csv`(date,count,total,tone)에 하루씩 누적. 매 실행마다 누락일만 채운다
   (최대 3일/회, 시간 초과 방지). 기준선 28일이 차려면 최초 백필이 필요하므로 `--backfill N` 옵션 제공.
   기존 DOC API series(10-27까지)는 기준선 초반 구간으로 쓰되 두 출처 값이 섞이므로 `source` 필드로 구분.
4. `news_monitor.fetch()`는 DOC 실패 또는 마지막 온전한 날이 오늘보다 3일 넘게 뒤처지면 GKG 경로로 폴백.
   news.json에 `source: "gdelt-doc" | "gdelt-gkg"` 추가. articles는 GKG 관련 레코드 URL 중 상위 12개
   (제목 없으면 도메인+URL).
5. 네트워크 실패는 예외를 삼키지 말고 기존처럼 RuntimeError로 올려 daily_report가 [점검] 처리하게 한다.
6. 비밀값·SerpApi 호출 없음. 우회가 필요한 차단 사이트 접근 금지.

## 수용 기준
- `python -m pytest tests/` 통과(네트워크 없이 합성 GKG 샘플로 파싱·집계·폴백 분기 검증).
- `python -c "import news_monitor"` 및 기존 `evaluate()` 동작 불변(기존 입력으로 동일 결과).
- 로컬에서 `python gdelt_gkg.py --backfill 2`로 실제 2일 집계가 되는지 실행 결과를 RESULT에 그대로 기록
  (소요 시간, 다운로드 용량 포함). 28일 전체 백필은 하지 말고 예상 소요만 보고.
- `daily_report.py` 실행 금지.

## 검증/보고
- RESULT.md: 변경 파일, 실제 실행한 명령과 출력, 미검증 범위(예: Actions 환경 시간/용량).
- 검수(Claude): diff 읽기, pytest·tsc류 직접 실행, REVIEW.md 작성.
