# 전쟁 알림 서비스

한국 내 전쟁 위험 신호를 매일 모니터링해 Gmail로 알리고 GitHub Pages 사이트로 보여주는 프로젝트. 사용자와는 한국어로, 간결하게 소통한다.

## 감시 지표
1. **남산 그랜드 하얏트 가격** (구현 완료) — 미군 소개 거점이라는 속설에 기반한 대리 지표. 사실로 확인된 전제가 아니므로 신뢰도는 낮게 본다. 예약 건수는 외부에서 볼 수 없어 공개 최저가와 매진 여부를 쓴다.
2. **주한 대사관 철수·이상 동향** (구현 완료) — 미 국무부 Travel Advisory, 영국 FCDO(gov.uk API), 캐나다, 독일 외무부, 뉴질랜드, 싱가포르, 중국 외교부 안전 알림, 일본 외무성 여행경보 단계 변경, 주한 미국대사관 Security Alert, 각국 대사관 공지의 "ordered departure", "자진 출국 권고" 등 키워드.
3. **세계 언론 동향** (구현 완료) — GDELT로 한반도 분쟁 기사량·논조 추적.
4. **시장 스트레스** (구현 완료, 참고 지표) — 원/달러 환율·코스피. 대리 지표라 신뢰도 낮음, 경보는 만들지 않음.
5. **대중 관심도** (구현 완료, 참고 지표) — 위키백과 조회수(North Korea·Korean War·DMZ·Kim Jong Un 합산)와 Google Trends KR 인기 검색어의 전쟁 키워드 건수.
6. **항공 교통** (구현 완료, 참고 지표) — OpenSky 익명 API로 한반도 상공 비행 중 항공기 수(하루 한 시점 스냅샷, 급감 시 주의).
7. **주한미군·공관 관련 공개 보도 신호** (구현 완료, 참고 지표) — Google News RSS로 비전투원 후송·경계태세·가족 이동 보도 건수.

## 현재 구조
- `hotel_monitor.py` — SerpApi Google Hotels로 하루 1회 수집. 체크인 D+1, D+3, D+7, D+14 (하루 4회 검색, 월 약 120회, 무료 플랜 250회 이내).
  - 대상: Grand Hyatt Seoul. 대조군: 신라, 반얀트리, 포시즌스, JW메리어트.
  - 지표: 하얏트 가격 ÷ 대조군 중앙값. 같은 체크인 요일·같은 선행일수 과거 분포 대비 z-score. 표본 4개 미만이면 보류.
  - 경보: z(비율) ≥ 2.5 → 하얏트 단독 급등 / z(대조군) ≥ 2.5 → 서울 고급호텔 전반 급등 / 대조군 정상인데 하얏트 요금 미노출 → 매진 가능.
  - 출력: `data/hotel_prices.csv`(누적), `data/metrics.json`(사이트용), `data/hotel_chart.png`, Gmail 리포트(SMTP, 앱 비밀번호).
- `embassy_monitor.py` — 대사관·여행경보. API 키 불필요.
  - 소스: 미 국무부 cadataapi(JSON), 영국 gov.uk content API, 캐나다 data.international.gc.ca(JSON), 일본 외무성 오픈데이터 XML(0082A.xml, 위험정보 레벨 + 영사메일), 독일 외무부 opendata API(플래그 4개 → 공통 단계, 변경 메모만 키워드 분류. 호주 Smartraveller는 자동 접속 차단으로 제외), 뉴질랜드 SafeTravel(페이지의 js-advice-level-accordion JSON, "level N of 4"), 싱가포르 외교부 RSS(South Korea 항목 category: Travel page=1·notice=2·advisory=3), 중국 영사서비스망 cs.mfa.gov.cn/aqtx 안전 알림(전 세계 목록에서 韩国·朝鲜·半岛 제목만, 단계 없는 공지 피드), 주한 미국대사관 Alert RSS(브라우저 UA 필요, 없으면 403).
  - 공통 단계 1~4로 정규화(일본: 위험정보 없음=1, 레벨n=n+1, 최대 4).
  - 경보: 단계 상승 / 공통 3단계 이상 지속(매일) / 새 공지에 철수·출국 키워드(ordered departure, 退避 등). 주의: 북한·미사일·군사 키워드(리포트·사이트에만). 훈련(drill, 訓練) 제목은 제외, Worldwide Caution은 주의로 낮춤.
  - 첫 실행은 기준선만 저장(기존 공지로 경보 안 냄). 소스 실패 시 직전 상태 유지, '수집 실패' 표시.
  - 출력: `data/embassy.json`(사이트), `data/embassy_state.json`(직전 단계·본 공지 ID), `data/embassy_log.csv`(일별 단계 누적).
- `news_monitor.py` — 세계 언론 동향(GDELT DOC 2.0, 키 불필요). 지표는 하루 전체 기사 중 관련 기사 비율(만 건당). 직전 28일 중앙값·MAD로 robust z. z≥2 주의, z≥3이면서 2배 이상이면 경보. 덜 수집된 날(전체 기사량이 중앙값의 절반 미만)은 판단·그래프에서 제외. GDELT는 IP당 5초 1회 제한이 엄격해 429 시 15/30/60초 재시도, 논조·기사 목록은 실패해도 생략하고 진행. 출력 data/news.json.
- `market_monitor.py` — 시장 스트레스(참고). Yahoo Finance chart API(비공식·키 불필요, 약관 회색지대·예고 없이 막힐 수 있음)로 `KRW=X`·`^KS11` 일별 종가 90거래일 수집. 20거래일 누적 변화율을 √20으로 보정해 직전 60일 일간 변화율의 median/MAD로 robust z(코스피는 부호 반전, 표본 30 미만·MAD 0이면 보류). z ≥ 2.0이면 '주의', 둘 다면 '동시 악화'. **alerts는 항상 빈 배열**(전체 [경보]·사이트 hero 경보 집계에 영향 없음). 한 심볼 실패는 해당 카드만 '수집 실패', 둘 다 실패면 [점검]. 첫 구현의 z는 보정 없이 누적 변화를 일간 분포와 비교해 √20배 부풀려졌다가 수정됨. 출력 `data/market.json`. Stooq·일본 방위성은 봇 차단이라 제외(우회 금지).
- `attention_monitor.py` — 대중 관심도(참고, 05). Wikimedia Pageviews(공식, 키 불필요) 4문서 합산 일 조회수의 직전 28일 robust z(최신 확정일은 API 지연으로 보통 2~3일 전) + Google Trends KR RSS 키워드 건수(하루 스냅샷을 `data/attention_trends.csv`에 누적, 14일 전 판단 보류, MAD 0이면 건수만, hits ≥ 3이면 주의). 출력 `data/attention.json`. alerts 항상 빈 배열.
- `air_monitor.py` — 항공 교통(참고, 06). OpenSky 익명 API(박스 33~39N·124~132E) 비행 중 항공기 수, 하락 방향 robust z(기준선 14일 전 보류). 익명 API가 막히면 [점검] 대신 muted+error로 직전 값 유지. 출력 `data/air.json`·`data/air_log.csv`. 커뮤니티 수신망이라 절대 수치가 작음(20~30대 안팎).
- `usfk_monitor.py` — 주한미군·공관 공개 보도 신호(참고, 07). Google News RSS 세 그룹(evac·readiness·families) 24시간 신규 보도 건수. **제목 필터 필수**: 그룹별 주제어 + 주한미군·공관 맥락이 제목에 모두 있어야 집계(검색이 NEO→Neoprints처럼 넓게 걸려 필터 없이는 잡음). 훈련 보도는 분리. evac이 24시간 3건 이상·매체 2곳 이상이면 주의. 출력 `data/usfk.json`·`data/usfk_log.csv`. 군용 ADS-B는 주한미군기가 거의 안 보여 제외, Stripes는 공개 RSS 미확인으로 제외.
- `daily_report.py` — 일곱 모듈(대사관·호텔·언론·시장·관심도·항공·주한미군)을 실행해 Gmail 한 통으로 발송. 제목 [경보]/[점검](모듈 실패)/[일간]. 한 모듈이 실패해도 나머지는 발송. 오류 메시지의 api_key는 가림.
- `mail_report.py` — 일간 메일 HTML 템플릿. data/*.json을 읽어 판정 배너·요약 카드 3개·섹션별 표를 인라인 스타일 table 레이아웃으로 렌더(메일 앱이 <style> 제거). 호텔 위험도 판정은 index.html의 hotelRisk와 동일하게 유지. GDELT가 3일 넘게 지연되면 경고 표시. 04~07 참고 지표 섹션 포함(market.json 없어도 렌더). 메일은 텍스트+HTML multipart로 발송.
- `index.html` — GitHub Pages 정적 사이트(외부 라이브러리 없음, 차트는 자체 SVG). `data/embassy.json`·`metrics.json`·`news.json`·`market.json`·`attention.json`·`air.json`·`usfk.json`을 따로 읽음(04~07 참고 지표 섹션, 모두 hero 경보 집계 제외). 외부 피드 문자열은 escape 후 출력. 모바일(≤560px) 대응.
  - 호텔 위험도(hotelRisk): 비율이 **오르면** 위험, 내리면 위험 아님. 대조군 2곳 이상 정상인데 하얏트 no_rate → 빨강. 같은 요일 z ≥ 2.5 빨강, ≥ 1.5 노랑, 그 외 초록. 같은 요일 z가 없으면 같은 선행일 전체 표본 7개 이상일 때 임시 기준(요일 무시). 표본 부족 → 회색(판단 보류). mail_report.py의 hotel_risk와 반드시 같게 유지.
  - 공지 피드형 소스(중국·주한 미대사관)는 `level_norm == null`로 구분.
  - 언론: 마지막 온전한 날이 수집일보다 3일 넘게 뒤처지면 '데이터 지연' 배너·회색 카드.
- `.github/workflows/hotel.yml` — (이름 daily-monitor) 매일 KST 08:47 `daily_report.py` 실행, data/ 전체를 커밋.
- 환경변수(GitHub Secrets): `SERPAPI_KEY`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `MAIL_TO`.

## 결정 사항
- Amadeus Self-Service API는 2026-07-17 종료되어 사용 불가 → SerpApi 선택.
- 호텔 공식 사이트·OTA 직접 크롤링은 약관 위반 소지로 하지 않음.
- Google Hotels는 객실 타입별 잔여를 주지 않아 스위트 체크는 미지원.
- 사이트는 GitHub Pages 공개. 무료 플랜이면 저장소가 public이라 수집 데이터도 공개됨.

## 배포·운영
- 저장소 github.com/gamensound-spec/war-alert (main, public). 사이트 https://reset589.com — GitHub Pages + 커스텀 도메인(repo의 CNAME 파일). 도메인은 Cloudflare Registrar: A @ → 185.199.108~111.153, CNAME www → gamensound-spec.github.io, 프록시 끔(DNS only).
- Actions 봇이 매일 data/를 커밋하므로 푸시 전 항상 `git pull --rebase --autostash`.
- 수동 실행: GitHub → Actions → daily-monitor → Run workflow.
- 비밀값(Gmail 앱 비밀번호, SerpApi 키)은 GitHub Secrets에만. 채팅·코드·저장소에 절대 넣지 않음. 로컬 테스트용은 git에서 제외된 `.env`.
- 봇 차단하는 사이트(예: 호주 Smartraveller)는 우회하지 않고 제외.

## 로컬 개발 (macOS)
```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m http.server 8765        # 사이트 확인: http://localhost:8765 (data/의 실데이터 사용)
python -c "import mail_report; open('/tmp/mail.html','w').write(mail_report.build('2026-11-08', [], []))"  # 메일 미리보기
```
- 실제 수집·발송(`python daily_report.py`)은 환경변수가 필요하고 SerpApi 사용량을 소모하므로 로컬에서는 가급적 돌리지 않는다. GDELT는 로컬 IP에서 429가 잦다.

## 현황·다음 할 일
- GDELT DOC API 색인은 10-25경 멈췄다가 11-08 수동 실행에서 복구 확인(latest 11-06). 정지 기간 동안 Actions에서 429가 풀리지 않아 11-06~08 언론 모듈이 실패했다. 대비책으로 `gdelt_gkg.py` 폴백 추가: DOC 실패·빈 데이터·3일 초과 지연 시 GKG 15분 원본 파일(하루 96개, 약 265MiB, 약 20초)을 집계해 `data/news_gkg_daily.csv`에 누적(실행당 최대 3일). 매칭 범위가 DOC보다 훨씬 좁아(하루 2건 안팎) 과거 DOC 시리즈는 섞지 않고 GKG 단독 기준선을 쓴다(14일 전까지 판단 보류). news.json에 `source`(gdelt-doc|gdelt-gkg) 필드. Actions에서 폴백 실제 실행은 아직 검증 전 — DOC가 다시 실패하는 날 로그 확인. 인수인계 문서: docs/handoff/gdelt-gkg-fallback/. 이후 보완: DOC가 429여도 직전 news.json이 DOC 출처이고 3일 이내로 최신이면 그 결과를 유지하고 GKG는 누적만 한다(`previous_doc`). 11-09 수동 실행에서 DOC 429 → GKG 폴백이 Actions에서 실제 동작함(3일분 약 1분). news.json이 GKG 출처가 된 뒤에는 DOC가 한 번 성공해야 DOC 기준으로 복귀하며, GKG 기준선은 14일(약 11-18)부터 판정.
- 05~07 참고 지표는 모두 기준선 14일(약 11-23까지) 전에는 판단 보류. 05의 위키 조회수는 API가 11-06까지만 제공해 최신일이 뒤처짐. 04~07 사이트 섹션의 실제 브라우저 렌더는 미확인(Playwright 점유로 스크립트 문법만 확인).
- 시장 스트레스: 코스피가 10월 초 7,003 → 11-06 5,060으로 하락 중이라 '주의'가 계속 표시될 수 있음(전쟁 외 요인 가능). 며칠 지켜본 뒤 임계값·문구 조정 검토. 사이트 04 섹션 실제 브라우저 렌더는 미확인.
- 호텔 z-score는 표본이 쌓여야 의미 있음(같은 요일 4개 = 약 4주, 임시 기준 7일).
- SerpApi 무료 250회/월, 현재 하루 4회(약 120회/월).
