# 전쟁 알림 서비스

한국 내 전쟁 위험 신호를 매일 모니터링해 Gmail로 알리고 GitHub Pages 사이트로 보여주는 프로젝트. 사용자와는 한국어로, 간결하게 소통한다.

## 감시 지표
1. **남산 그랜드 하얏트 가격** (구현 완료) — 미군 소개 거점이라는 속설에 기반한 대리 지표. 사실로 확인된 전제가 아니므로 신뢰도는 낮게 본다. 예약 건수는 외부에서 볼 수 없어 공개 최저가와 매진 여부를 쓴다.
2. **주한 대사관 철수·이상 동향** (구현 완료) — 미 국무부 Travel Advisory, 영국 FCDO(gov.uk API), 캐나다, 독일 외무부, 일본 외무성 여행경보 단계 변경, 주한 미국대사관 Security Alert, 각국 대사관 공지의 "ordered departure", "자진 출국 권고" 등 키워드.
3. **세계 언론 동향** (미구현) — GDELT로 한반도 분쟁 기사량·논조 추적, Google News RSS 보조.

## 현재 구조
- `hotel_monitor.py` — SerpApi Google Hotels로 하루 1회 수집. 체크인 D+1, D+3, D+7 (하루 3회 검색, 월 약 90회, 무료 플랜 250회 이내).
  - 대상: Grand Hyatt Seoul. 대조군: 신라, 반얀트리, 포시즌스, JW메리어트.
  - 지표: 하얏트 가격 ÷ 대조군 중앙값. 같은 체크인 요일·같은 선행일수 과거 분포 대비 z-score. 표본 4개 미만이면 보류.
  - 경보: z(비율) ≥ 2.5 → 하얏트 단독 급등 / z(대조군) ≥ 2.5 → 서울 고급호텔 전반 급등 / 대조군 정상인데 하얏트 요금 미노출 → 매진 가능.
  - 출력: `data/hotel_prices.csv`(누적), `data/metrics.json`(사이트용), `data/hotel_chart.png`, Gmail 리포트(SMTP, 앱 비밀번호).
- `embassy_monitor.py` — 대사관·여행경보. API 키 불필요.
  - 소스: 미 국무부 cadataapi(JSON), 영국 gov.uk content API, 캐나다 data.international.gc.ca(JSON), 일본 외무성 오픈데이터 XML(0082A.xml, 위험정보 레벨 + 영사메일), 독일 외무부 opendata API(플래그 4개 → 공통 단계, 변경 메모만 키워드 분류. 호주 Smartraveller는 자동 접속 차단으로 제외), 주한 미국대사관 Alert RSS(브라우저 UA 필요, 없으면 403).
  - 공통 단계 1~4로 정규화(일본: 위험정보 없음=1, 레벨n=n+1, 최대 4).
  - 경보: 단계 상승 / 공통 3단계 이상 지속(매일) / 새 공지에 철수·출국 키워드(ordered departure, 退避 등). 주의: 북한·미사일·군사 키워드(리포트·사이트에만). 훈련(drill, 訓練) 제목은 제외, Worldwide Caution은 주의로 낮춤.
  - 첫 실행은 기준선만 저장(기존 공지로 경보 안 냄). 소스 실패 시 직전 상태 유지, '수집 실패' 표시.
  - 출력: `data/embassy.json`(사이트), `data/embassy_state.json`(직전 단계·본 공지 ID), `data/embassy_log.csv`(일별 단계 누적).
- `news_monitor.py` — 세계 언론 동향(GDELT DOC 2.0, 키 불필요). 지표는 하루 전체 기사 중 관련 기사 비율(만 건당). 직전 28일 중앙값·MAD로 robust z. z≥2 주의, z≥3이면서 2배 이상이면 경보. 덜 수집된 날(전체 기사량이 중앙값의 절반 미만)은 판단·그래프에서 제외. GDELT는 IP당 5초 1회 제한이 엄격해 429 시 15/30/60초 재시도, 논조·기사 목록은 실패해도 생략하고 진행. 출력 data/news.json.
- `daily_report.py` — 세 모듈(대사관·호텔·언론)을 실행해 Gmail 한 통으로 발송. 제목 [경보]/[점검](모듈 실패)/[일간]. 한 모듈이 실패해도 나머지는 발송. 오류 메시지의 api_key는 가림.
- `index.html` — GitHub Pages 정적 사이트. `data/metrics.json`(호텔), `data/embassy.json`(대사관)을 따로 읽음. 외부 피드 문자열은 escape 후 출력. 언론 칸은 자리만 있음.
- `.github/workflows/hotel.yml` — (이름 daily-monitor) 매일 KST 08:47 `daily_report.py` 실행, data/ 전체를 커밋.
- 환경변수(GitHub Secrets): `SERPAPI_KEY`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `MAIL_TO`.

## 결정 사항
- Amadeus Self-Service API는 2026-07-17 종료되어 사용 불가 → SerpApi 선택.
- 호텔 공식 사이트·OTA 직접 크롤링은 약관 위반 소지로 하지 않음.
- Google Hotels는 객실 타입별 잔여를 주지 않아 스위트 체크는 미지원.
- 사이트는 GitHub Pages 공개. 무료 플랜이면 저장소가 public이라 수집 데이터도 공개됨.

## 다음 할 일
- 첫 Actions 실행에서 GDELT 수집 확인 (로컬 IP는 테스트 중 429 제한에 걸려 실데이터 미검증)
- 호텔: SerpApi 검색어 폴백 3개(SEARCH_QUERIES). 첫 검색어에서 5곳 다 찾는지 사용량으로 확인(무료 250회/월)
- 호텔·언론 z-score는 표본이 쌓인 뒤(호텔 약 4주) 의미 있음
