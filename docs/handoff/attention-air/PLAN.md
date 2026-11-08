# PLAN: 대중 관심도(05) + 항공 교통(06) 참고 지표

## 원칙 (market-stress와 동일)
- 둘 다 **대리 지표·신뢰도 낮음·경보 없음**. 판정은 `normal | watch | muted`만, `alerts`는 항상 `[]`.
  전체 [경보] 제목·사이트 hero 경보 집계에 영향 주지 않는다. 사이트·메일에 출처와 "참고 지표 · 신뢰도 낮음 · 경보 없음" 표시.
- 키·비밀값·새 환경변수 없음. 자동 접속을 막는 사이트 우회 금지. 실패 패턴은 market_monitor.py를 따른다
  (소스 하나 실패 → 해당 카드만 '수집 실패', 전부 실패 → RuntimeError로 [점검], 직전 JSON은 실패 시 보존, 원자적 쓰기).
- z-score 단위 주의: **같은 단위끼리만 비교**한다(market에서 20일 누적을 일간 분포와 비교해 √20배 부풀려졌던 결함 재발 금지).
  기준선은 `news_monitor.robust_z`(median/MAD*1.4826) 재사용.
- 참고 구현: `/Users/dex/war-alert/market_monitor.py`, `tests/test_market_monitor.py`, mail_report의 04 섹션, index.html의 sec-market.

## A. attention_monitor.py → `data/attention.json` (05 대중 관심도)
소스 두 개, 각각 독립 실패 처리.
1. **Wikimedia Pageviews API** (공식·키 불필요, UA에 연락처 없는 일반 이름 사용 예: "war-alert/1.0"):
   `https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/<제목>/daily/<YYYYMMDD>/<YYYYMMDD>`
   제목: `North_Korea`, `Korean_War`, `Korean_Demilitarized_Zone`, `Kim_Jong_Un`. 최근 60일 일별 조회수.
   - 지표: 4개 문서 합산 일 조회수. 최신 확정일(보통 어제) 값을 직전 28일 중앙값·MAD로 robust z (같은 단위: 일 조회수 vs 일 조회수).
   - 표본 14일 미만·MAD 0이면 muted. z ≥ 2.0 → watch.
   - 404(데이터 없음)는 해당 문서 건너뛰되 4개 모두 없으면 소스 실패.
2. **Google Trends 한국 일간 인기 검색어 RSS** `https://trends.google.com/trending/rss?geo=KR` (오늘 목록만 제공):
   - 항목 title과 뉴스 제목에서 키워드(전쟁, 북한, 미사일, 핵, 계엄 제외, 대피, 비상식량, 징집, 참전) 포함 건수를 센다.
   - 하루 1회 스냅샷을 `data/attention_trends.csv`(date,keyword_hits,items)에 누적. 14일 미만이면 muted(판단 보류),
     이후 hits의 직전 28일 robust z, 단 MAD 0(대부분 0건)이면 "평소 0건 대비 N건"처럼 건수만 표시하고 watch는 hits ≥ 3일 때만.
   - RSS에 이미 오늘 목록이 있으므로 같은 날 중복 실행 시 같은 date 행을 덮어쓴다.
- `attention.json`: generated_at, source 목록, config, status, alerts:[], watch:[], wiki{latest 값·합계·z·문서별 최신값·series 60일}, trends{hits·samples·z·상위 매칭 제목 최대 5개(escape 전제)}.
- `run()` → `(alerts, lines)`.

## B. air_monitor.py → `data/air.json` (06 항공 교통)
- 소스: OpenSky Network 익명 API `https://opensky-network.org/api/states/all?lamin=33&lomin=124&lamax=39&lomax=132`
  (한반도 상공 박스, 1회 호출 ≈ 크레딧 2, 익명 일 한도 내). 하루 08:47 KST 한 번의 스냅샷.
- 지표: `on_ground=false` 항공기 수. 보조: 콜사인 접두 기준 국내 항공사(KAL, AAR, JJA, TWB, JNA, ESR, ASV, APJ?)는 몰라도 됨 —
  단순화를 위해 총 항공기 수와 국적(origin_country) 상위 3개만 기록.
- `data/air_log.csv`(date,airborne,total_states) 누적. 14일 미만 muted. 이후 직전 28일 중앙값·MAD robust z를 **하락 방향**(항공기 급감 = 스트레스)으로
  부호 반전. z ≥ 2.0 → watch. 스냅샷 1회라 노이즈가 크므로 문구에 "하루 한 시점 스냅샷" 명시.
- 401/429/시간초과는 재시도 없이 1회 15초 대기 후 1회 재시도만, 실패 시 RuntimeError(→ [점검])이 아니라
  **muted + error 필드**로 처리하고 직전 값 유지(익명 API가 자주 막히므로 [점검] 남발 방지). 단 `air.json`이 한 번도 없으면 빈 상태.
- `air.json`: generated_at, source "opensky-anonymous", status, alerts:[], watch, latest{airborne,z,base_n,date,top_countries}, series.

## 수정 가능 파일
`attention_monitor.py`, `air_monitor.py`, `tests/test_attention_monitor.py`, `tests/test_air_monitor.py`(모두 신규),
`daily_report.py`(parts에 두 줄), `mail_report.py`(05·06 섹션, render/build에 인자 연결, 파일 없어도 렌더),
`index.html`(sec-attention, sec-air 섹션 + 데이터 로드; hero 집계 제외, escape, 모바일 대응).
**수정 금지**: CLAUDE.md, 워크플로, hotelRisk/hotel_risk, market_monitor.py, news/gdelt 모듈.

## 수용 기준
- `python -m pytest tests/` 전체 통과(기존 68개 + 신규). 합성 응답으로 파싱·z·판정·부분 실패·파일 보존·MAD 0·표본 부족·null 처리 테스트.
- 실제 `python attention_monitor.py`, `python air_monitor.py` 실행 결과를 RESULT에 원문으로 기록(네트워크 불가 시 사유와 합성으로 대체한 범위 명시, 통과로 위장 금지).
  Codex 샌드박스가 DNS 불가면 Claude가 검수 때 실데이터로 재실행한다.
- 메일 미리보기: 05·06 포함/미포함(JSON 없음) 모두 렌더. 사이트: JSON 없음/있음 모두 깨지지 않음(브라우저 불가 시 미검증 명시).
- **금지**: `daily_report.py` 실행/임포트 후 실행, SerpApi, 메일 발송, 커밋·푸시, 비밀값 기재.

## 보고
RESULT.md: 변경 파일, 실제 실행한 명령과 출력 원문, 미검증 범위. 검수: Claude(diff·pytest·실데이터 실행·REVIEW.md).
