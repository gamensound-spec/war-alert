# PLAN: 시장 스트레스 지표 (환율·코스피) — '참고' 등급

## 배경·원칙
- 한국 전쟁 위험에 대한 시장 반응(원화 약세, 코스피 하락)을 4번째 지표로 추가한다.
- 대리 지표이고 평소에도 변동이 크다. **경보를 만들지 않는다.** 판정은 `normal | watch(주의) | muted(보류)`만 쓰고
  `alerts`는 항상 빈 배열이다(전체 [경보] 제목에 영향 주지 않음). 사이트·메일에 "참고 지표, 신뢰도 낮음" 명시.
- 데이터 소스: Yahoo Finance chart API (비공식·키 불필요, 약관 회색지대). 환율 `KRW=X`, 코스피 `^KS11`.
  `https://query1.finance.yahoo.com/v8/finance/chart/<심볼>?range=6mo&interval=1d`, User-Agent 필요.
  실패해도 전체를 멈추지 않는다(아래). Stooq 등 봇 차단 사이트는 쓰지 않고 우회하지 않는다.
- 비밀값 없음. 새 환경변수 없음.

## 범위 (수정 가능 파일)
- `market_monitor.py` (신규): 수집·계산·`data/market.json` 출력, `run()` → `(alerts, lines)` (기존 모듈과 같은 시그니처)
- `tests/test_market_monitor.py` (신규): 합성 응답으로 파싱·z-score·판정·실패 처리 테스트
- `daily_report.py`: parts에 ("시장 스트레스", market_monitor.run) 추가 (한 줄)
- `mail_report.py`: 04 섹션 추가. `render`·`build`에 market 인자 연결, 판정 배너에는 영향 주지 않음
- `index.html`: 섹션 하나 추가(요약 카드 2개 + 간단 SVG 라인 차트 1개 또는 카드만). 외부 라이브러리 금지,
  외부 문자열 escape, 모바일(≤560px) 유지. `hero()`의 경보 집계에는 포함하지 않는다.
- CLAUDE.md는 건드리지 말 것(Claude가 갱신). 호텔 위험도 로직(`hotelRisk`/`hotel_risk`)·워크플로 수정 금지.

## 명세
1. 각 심볼 일별 종가를 받아 최근 90거래일 보관. 지표:
   - 환율: 일별 변화율(%)의 20일 변화 / 직전 60일 일간 변화율 표준편차로 robust z (중앙값·MAD 방식, news_monitor.robust_z와 동일)
   - 코스피: 일간 수익률의 같은 z (하락이 위험이므로 부호를 반전해 "스트레스 z"로 통일)
   - 기준선 표본이 30거래일 미만이면 muted(판단 보류).
2. 판정: 두 지표 중 스트레스 z가 하나라도 ≥ 2.0 → watch(주의), 둘 다 ≥ 2.0 → watch + "동시 악화" 문구. 그 외 normal.
   경보(alert)는 만들지 않는다. 임계값은 상수로 두고 `config`에 출력.
3. `data/market.json`: `generated_at`(KST ISO), `source`("yahoo-chart-unofficial"), `config`, `status`
   (normal|watch|muted), `alerts: []`, `watch: [문구]`, `latest`(심볼별 최근 종가·전일 대비 %·z), `series`(날짜별 종가).
4. 실패 처리: 한 심볼 실패 시 다른 심볼은 계속하고 실패 심볼은 `error` 필드. 두 심볼 모두 실패하면 RuntimeError로 올려
   daily_report가 [점검]으로 처리(기존 패턴). 직전 market.json이 있으면 덮어쓰기 전에 보존하고 실패 시 유지.
   429/비 JSON 응답은 15·30초 재시도 후 포기. 휴장일(최신 일자가 3일 넘게 뒤처짐)은 사이트에 '데이터 지연' 표시.
5. 사이트/메일 문구에 출처(Yahoo Finance, 비공식 API)와 "대리 지표 · 신뢰도 낮음 · 경보 없음"을 표시.

## 수용 기준
- `python -m pytest tests/` 전체 통과 (기존 29개 + 신규).
- `python -c "import market_monitor"` 및 `python market_monitor.py` 실제 실행으로 `data/market.json` 생성
  (네트워크 가능 시 실제 응답으로, 불가 시 RESULT에 사유 기록). 실행 결과(최근 종가·z·판정)를 RESULT에 그대로 기록.
- 메일 미리보기: `python -c "import mail_report; ..."`로 04 섹션 포함 HTML 생성 확인 (market.json 없을 때도 깨지지 않을 것).
- 사이트: `python -m http.server`로 열었을 때 market 섹션이 렌더되고 market.json이 없어도 빈 상태 메시지 표시.
  브라우저 확인이 불가하면 미검증으로 RESULT에 명시.
- **금지**: `daily_report.py` 실행(SerpApi·메일 발송), 커밋·푸시, 비밀값 기재.

## 보고
- RESULT.md: 변경 파일, 실제 실행한 명령과 출력 원문, 미검증 범위.
- 검수(Claude): diff 읽기, pytest·실행 직접 확인, 사이트 렌더 확인, REVIEW.md 작성.
