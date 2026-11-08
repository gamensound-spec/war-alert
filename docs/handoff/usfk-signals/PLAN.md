# PLAN: 주한미군·대사관 관련 공개 보도 신호 (07) — 참고 지표

## 배경·원칙
- 주한미군 항공기는 공개 ADS-B에 거의 안 보이고(반경 250해리에서 군용 플래그 0대 확인), Stripes는 공개 RSS 주소 미확인 → 제외.
- 대안: **Google News RSS 검색**(키 불필요, 공개)으로 비전투원 후송(NEO)·경계태세·가족 이동 관련 보도 건수를 하루 1회 기록한다.
- 표시 이름은 "주한미군·공관 관련 공개 보도 신호". '직원·부대 움직임'을 직접 보여준다고 주장하지 않는다. 개인·특정 부대 위치 정보는 다루지 않는다.
- **참고 지표·신뢰도 낮음·경보 없음**: `alerts`는 항상 `[]`, 판정 `normal|watch|muted`. 전체 [경보] 제목·hero 집계에 영향 없음.
- 실패 패턴·z 규칙은 `attention_monitor.py`·`market_monitor.py`를 따른다(같은 단위끼리만 비교, `news_monitor.robust_z` 재사용, 원자적 쓰기, 실패 시 직전 JSON 보존).
- 비밀값·새 환경변수 없음. 자동 접속을 막는 사이트 우회 금지(뉴스 RSS만 사용, 기사 원문 크롤링 금지).

## usfk_monitor.py → `data/usfk.json`, `data/usfk_log.csv`
Google News RSS: `https://news.google.com/rss/search?q=<쿼리>&hl=<lang>&gl=<country>&ceid=<country>:<lang>` (UA는 일반 이름 "war-alert/1.0").
쿼리 그룹(각각 `when:7d` 포함, 일 1회 수집, 그룹 간 2초 간격):
1. `evac` 비전투원 후송: `("noncombatant evacuation" OR "ordered departure" OR "authorized departure" OR NEO) (Korea OR USFK)` (en-US/US) + `주한미군 (비전투원 OR 소개 OR 철수)` (ko/KR)
2. `readiness` 경계태세: `("force protection condition" OR FPCON OR "heightened alert" OR "alert status") (USFK OR "U.S. Forces Korea")`
3. `families` 가족·이동: `("military families" OR dependents OR "PCS") Korea (evacuate OR relocate OR suspend OR freeze)`
- 각 항목에서 title, link, pubDate, source를 파싱한다. 제목 소문자 앞 60자로 중복 제거.
- **훈련 구분**: 제목에 `exercise|drill|training|훈련`이 있으면 `training` 으로 분류해 스트레스 건수에서 제외하고 별도로 센다
  (NEO 훈련 보도가 흔하므로). 
- 일별 스냅샷을 `data/usfk_log.csv`(date,group,hits_24h,hits_7d,training_7d)에 누적, 같은 date·group 재실행은 덮어쓰기.
- 지표: 그룹별 `hits_24h`(최근 24시간 신규 보도, 훈련 제외). 기준선은 같은 그룹의 직전 28일 `hits_24h`(같은 단위). 14일 미만 muted.
  MAD 0(평소 0건)이면 z 없이 건수 표시, 기준선 충분 + `evac` hits_24h ≥ 3 이고 서로 다른 매체 2곳 이상이면 watch.
  그 외 그룹은 robust z ≥ 2.0이면 watch.
- 출력 JSON: generated_at(KST), source "google-news-rss", config(쿼리·임계값), status, alerts:[], watch:[문구], groups{그룹별 latest hits·z·base_n·training_7d·status},
  headlines(최대 8개: title, source, date, link — 링크는 http(s)만, 사이트에서 escape).
- 실패: 한 그룹 실패 → 그 그룹만 error. 전 그룹 실패 → muted + error로 저장하고 직전 값 유지(RuntimeError로 [점검] 남발하지 않음. 단 JSON이 한 번도 없으면 빈 상태).
- `run()` → `(alerts, lines)`, 라인 끝에 "참고 지표 · 신뢰도 낮음 · 경보 없음".

## 수정 가능 파일
`usfk_monitor.py`, `tests/test_usfk_monitor.py`(신규), `daily_report.py`(parts에 한 줄 + import),
`mail_report.py`(07 섹션, render/build 인자 연결, JSON 없어도 렌더), `index.html`(sec-usfk 07 섹션, 기존 market/attention 카드 패턴 재사용, 외부 문자열 모두 esc, 링크는 http(s)만, hero 집계 제외).
**수정 금지**: CLAUDE.md, 워크플로, hotelRisk/hotel_risk, 기존 모니터 모듈.

## 수용 기준
- `python -m pytest tests/` 전체 통과(현재 143개 + 신규). 합성 RSS로 파싱·중복 제거·훈련 분류·z·MAD 0·watch 조건·부분/전체 실패·파일 보존·XSS(제목에 `<script>`)·링크 스킴 필터 테스트.
- 가능하면 실제 `python usfk_monitor.py` 실행 결과를 RESULT에 원문 기록(샌드박스 DNS 불가면 사유와 합성 대체 범위 명시, 통과로 위장 금지). Claude가 검수 때 실데이터로 재실행한다.
- 메일 미리보기: 07 포함 / JSON 없음 모두 렌더. 사이트 브라우저 렌더 불가 시 미검증 명시.
- **금지**: daily_report.py 실행, SerpApi, 메일 발송, 커밋·푸시, 비밀값 기재.

## 보고
RESULT.md: 변경 파일, 실제 실행 명령과 출력 원문, 미검증 범위. 검수(Claude): diff·pytest·실데이터 실행·REVIEW.md.
