# RESULT: 주한미군·공관 관련 공개 보도 신호 (07)

## 결과

PLAN 범위의 구현을 완료했다. 전체 테스트 **200개 통과**(기존 143개 + 신규 57개), 경고 1개다. 실제 Google News RSS 수집은 샌드박스 DNS 실패로 확인하지 못했다. 종료 코드 0은 실패를 muted로 기록하는 동작의 결과이며, 실데이터 수집 성공을 뜻하지 않는다.

## 변경 파일

- `usfk_monitor.py` (신규): 세 그룹·네 쿼리의 Google News RSS 수집, 그룹 간 2초 간격, RSS 필드 파싱, 제목 소문자 앞 60자 중복 제거, 훈련 분리, 최근 24시간/7일 건수 및 24시간 매체 수 계산.
- `tests/test_usfk_monitor.py` (신규): 합성 RSS, 날짜 경계, 중복·훈련·매체 수, 같은 그룹·같은 하루 단위 기준선, z 임계값, MAD 0, watch 조건, 부분/전체 실패, 원자적 파일 보존, HTML escape·링크 스킴 제한, 메일 연결, 사이트 JavaScript 합성 실행, daily_report 정적 연결 검사.
- `daily_report.py`: import와 parts 항목만 추가. 기존 테스트의 마지막 두 모듈 순서를 유지하도록 시장 스트레스 다음에 연결했다. 메일과 사이트에서는 07 섹션이다.
- `mail_report.py`: 07 렌더러 및 render/build 인자 연결. JSON 없음, 직전 관측 유지, 최대 8개 제목, 외부 문자열 escape, HTTP(S) 링크 필터.
- `index.html`: sec-usfk 07, JSON 로딩 및 기존 referenceTile/market-tiles 카드 재사용. 외부 문자열 esc, safeUrl 링크 제한. hero의 집계 로직은 변경하지 않았다.
- `docs/handoff/usfk-signals/RESULT.md`: 이 기록.

기존 모니터 모듈, CLAUDE.md, 워크플로, hotelRisk/hotel_risk, PLAN.md는 수정하지 않았다. 새 환경변수·비밀값은 추가하지 않았다. 실제 실행으로 생성된 빈 실패 상태 `data/usfk.json`은 검증 후 제거했다. 실데이터 또는 합성 스냅샷을 프로젝트 data/에 남기지 않았다.

## 판정·저장 동작

- 직전 28일 중 **같은 그룹의 hits_24h**만 기준선으로 사용한다. 당일·다른 그룹·hits_7d·training_7d는 제외한다. 14일 미만은 muted.
- evac은 기준선 14일 이상, hits_24h ≥ 3, 서로 다른 매체 ≥ 2를 모두 만족해야 watch다. MAD 0에서도 z를 만들지 않고 이 건수 조건을 적용한다. 다른 그룹은 유효한 robust z ≥ 2.0에서 watch이며, MAD 0이면 기존 모니터 패턴대로 muted로 건수만 표시한다.
- alerts는 항상 빈 배열이며, 전체 경보와 hero에 추가하지 않는다.
- 한 그룹 실패는 해당 그룹만 error/muted로 기록한다. 직전 값이 있으면 날짜·건수를 함께 유지한다. 전 그룹 실패도 RuntimeError 없이 muted/error JSON을 저장하고 직전 관측값·제목을 유지한다. 실패한 그룹의 당일 CSV 행은 만들지 않는다.
- CSV는 date·group 키로 덮어쓰며, JSON/CSV 각각 원자적으로 교체한다. 직렬화·파일 교체 실패 시 해당 기존 파일의 바이트를 보존한다.

## 실제 실행 명령과 출력 원문

아래는 검증에 사용한 셸 명령과 반환된 출력이다. 읽기 전용 참고 파일 확인·diff 열람·스킬 검색은 제외했다. 출력을 줄이거나 성공으로 바꿔 적지 않았다.

### 1. 전체 테스트 — 최초 실행

명령:

```sh
source .venv/bin/activate && python -m pytest tests/
```

종료 코드: 0

출력 원문:

```text
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
rootdir: /Users/dex/war-alert
collected 199 items

tests/test_air_monitor.py ................................               [ 16%]
tests/test_attention_monitor.py ........................................ [ 36%]
                                                                         [ 36%]
tests/test_gdelt_gkg.py ................................                 [ 52%]
tests/test_market_monitor.py .......................................     [ 71%]
tests/test_usfk_monitor.py ............................................. [ 94%]
...........                                                              [100%]

=============================== warnings summary ===============================
.venv/lib/python3.9/site-packages/urllib3/__init__.py:35
  /Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
    warnings.warn(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 199 passed, 1 warning in 0.65s ========================
```

### 2. 실제 RSS 수집 시도

명령:

```sh
source .venv/bin/activate && python usfk_monitor.py
```

종료 코드: 0

출력 원문:

```text
/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
비전투원 후송: 수집 실패 · HTTPSConnectionPool(host='news.google.com', port=443): Max retries exceeded with url: /rss/search?q=%28%22noncombatant+evacuation%22+OR+%22ordered+departure%22+OR+%22authorized+departure%22+OR+NEO%29+%28Korea+OR+USFK%29+when%3A7d&hl=en-US&gl=US&ceid=US%3Aen (Caused by NameResolutionError("HTTPSConnection(host='news.google.com', port=443): Failed to resolve 'news.google.com' ([Errno 8] nodename nor servname provided, or not known)")) · 이전 관측값 없음 · 참고 지표 · 신뢰도 낮음 · 경보 없음
경계태세: 수집 실패 · HTTPSConnectionPool(host='news.google.com', port=443): Max retries exceeded with url: /rss/search?q=%28%22force+protection+condition%22+OR+FPCON+OR+%22heightened+alert%22+OR+%22alert+status%22%29+%28USFK+OR+%22U.S.+Forces+Korea%22%29+when%3A7d&hl=en-US&gl=US&ceid=US%3Aen (Caused by NameResolutionError("HTTPSConnection(host='news.google.com', port=443): Failed to resolve 'news.google.com' ([Errno 8] nodename nor servname provided, or not known)")) · 이전 관측값 없음 · 참고 지표 · 신뢰도 낮음 · 경보 없음
가족·이동: 수집 실패 · HTTPSConnectionPool(host='news.google.com', port=443): Max retries exceeded with url: /rss/search?q=%28%22military+families%22+OR+dependents+OR+%22PCS%22%29+Korea+%28evacuate+OR+relocate+OR+suspend+OR+freeze%29+when%3A7d&hl=en-US&gl=US&ceid=US%3Aen (Caused by NameResolutionError("HTTPSConnection(host='news.google.com', port=443): Failed to resolve 'news.google.com' ([Errno 8] nodename nor servname provided, or not known)")) · 이전 관측값 없음 · 참고 지표 · 신뢰도 낮음 · 경보 없음
판정: muted · 참고 지표 · 신뢰도 낮음 · 경보 없음
출처: Google News RSS · 참고 지표 · 신뢰도 낮음 · 경보 없음
```

### 3. 전체 테스트 — 사이트 합성 검증 추가 후 최종 실행

명령:

```sh
source .venv/bin/activate && python -m pytest tests/
```

종료 코드: 0

출력 원문:

```text
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
rootdir: /Users/dex/war-alert
collected 200 items

tests/test_air_monitor.py ................................               [ 16%]
tests/test_attention_monitor.py ........................................ [ 36%]
                                                                         [ 36%]
tests/test_gdelt_gkg.py ................................                 [ 52%]
tests/test_market_monitor.py .......................................     [ 71%]
tests/test_usfk_monitor.py ............................................. [ 94%]
............                                                             [100%]

=============================== warnings summary ===============================
.venv/lib/python3.9/site-packages/urllib3/__init__.py:35
  /Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
    warnings.warn(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 200 passed, 1 warning in 0.77s ========================
```

### 4. 합성 RSS 및 메일·사이트 미리보기 생성

명령:

```sh
source .venv/bin/activate && python - <<'PY'
import datetime as dt
import json
import tempfile
from email.utils import format_datetime
from html import escape
from pathlib import Path
from unittest.mock import patch

import mail_report
import usfk_monitor as u

root = Path(tempfile.mkdtemp(prefix="war-alert-usfk-", dir="/private/tmp"))
now = dt.datetime(2026, 11, 9, 8, 47, tzinfo=u.KST)
rss = '<rss><channel>' + ''.join(
    '<item><title>' + escape(title) + '</title><pubDate>'
    + format_datetime(now - dt.timedelta(hours=1)) + '</pubDate><source>'
    + source + '</source><link>' + escape(link) + '</link></item>'
    for title, source, link in [
        ('&lt;unused&gt;', 'Outlet A', 'https://example.test/one'),
        ('USFK public report two', 'Outlet B', 'https://example.test/two'),
        ('<script>alert("synthetic")</script>', 'Outlet A', 'javascript:alert(1)'),
        ('NEO training drill', 'Outlet C', 'https://example.test/training'),
    ]) + '</channel></rss>'
with patch.object(u, "JSON_FILE", root / "usfk.json"), patch.object(u, "CSV_FILE", root / "usfk_log.csv"), patch.object(u.time, "sleep"):
    u.write_log([
        {"date": (now.date() - dt.timedelta(days=i)).isoformat(), "group": group,
         "hits_24h": i % 2, "hits_7d": 100, "training_7d": 10}
        for group in u.GROUPS for i in range(1, 15)
    ])
    alerts, lines = u.run(lambda group: u.parse_rss(rss), now)
    print(*lines, sep="\n")
    data = json.loads((root / "usfk.json").read_text())
    assert alerts == [] and data["status"] == "watch"
    assert all(item["hits_24h"] == 3 and item["training_7d"] == 1 for item in data["groups"].values())
for present in (True, False):
    with patch.object(mail_report, "load", lambda path: data if present and path == "data/usfk.json" else None):
        html = mail_report.build("2026-11-09", [], [])
    assert "07 주한미군·공관 관련 공개 보도 신호" in html
    assert ("공개 보도 데이터를 기다리는 중" in html) != present
    assert "<script>" not in html and "javascript:" not in html
    (root / ("mail-with-json.html" if present else "mail-without-json.html")).write_text(html, encoding="utf-8")
    fixture = json.dumps(data if present else None, ensure_ascii=False).replace("<", "\\u003c")
    stub = "<script>const previewData=" + fixture + ";window.fetch=async url=>({ok:url==='data/usfk.json'&&!!previewData,json:async()=>previewData});</script>"
    site = Path("index.html").read_text().replace("<script>", stub + "<script>", 1)
    (root / ("site-with-json.html" if present else "site-without-json.html")).write_text(site, encoding="utf-8")
print("mail preview: with JSON / without JSON / XSS / HTTP(S) PASS")
print("preview_dir=" + str(root))
PY
```

종료 코드: 0

출력 원문:

```text
/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
비전투원 후송 2026-11-09: 24시간 3건 · 7일 3건 · 훈련 1건 제외 · 매체 2곳 · z +3.37 · 참고 지표 · 신뢰도 낮음 · 경보 없음
경계태세 2026-11-09: 24시간 3건 · 7일 3건 · 훈련 1건 제외 · 매체 2곳 · z +3.37 · 참고 지표 · 신뢰도 낮음 · 경보 없음
가족·이동 2026-11-09: 24시간 3건 · 7일 3건 · 훈련 1건 제외 · 매체 2곳 · z +3.37 · 참고 지표 · 신뢰도 낮음 · 경보 없음
주의: 비전투원 후송 관련 공개 보도 증가 (24시간 3건) · 참고 지표 · 신뢰도 낮음 · 경보 없음
주의: 경계태세 관련 공개 보도 증가 (24시간 3건) · 참고 지표 · 신뢰도 낮음 · 경보 없음
주의: 가족·이동 관련 공개 보도 증가 (24시간 3건) · 참고 지표 · 신뢰도 낮음 · 경보 없음
판정: watch · 참고 지표 · 신뢰도 낮음 · 경보 없음
출처: Google News RSS · 참고 지표 · 신뢰도 낮음 · 경보 없음
mail preview: with JSON / without JSON / XSS / HTTP(S) PASS
preview_dir=/private/tmp/war-alert-usfk-wwfknst5
```

### 5. diff 공백 검사

명령:

```sh
git diff --check
```

종료 코드: 0

표준 출력/표준 오류: 없음.

### 6. 수정 범위·금지 함수·임시 데이터 확인

명령:

```sh
source .venv/bin/activate && python - <<'PY'
import ast
import subprocess
from pathlib import Path

allowed = {"daily_report.py", "mail_report.py", "index.html"}
changed = set(subprocess.check_output(["git", "diff", "--name-only"], text=True).splitlines())
assert changed <= allowed, changed - allowed
before = subprocess.check_output(["git", "show", "HEAD:mail_report.py"], text=True)
after = Path("mail_report.py").read_text()
def function(text, name):
    return ast.dump(next(node for node in ast.parse(text).body if isinstance(node, ast.FunctionDef) and node.name == name))
assert function(before, "hotel_risk") == function(after, "hotel_risk")
before_site = subprocess.check_output(["git", "show", "HEAD:index.html"], text=True)
after_site = Path("index.html").read_text()
def hotel_risk(text):
    return text.split("function hotelRisk(o){", 1)[1].split("function hotelWorst()", 1)[0]
assert hotel_risk(before_site) == hotel_risk(after_site)
assert not Path("data/usfk.json").exists()
assert not Path("data/usfk_log.csv").exists()
print("scope: tracked changes limited to daily_report.py, mail_report.py, index.html")
print("hotel_risk / hotelRisk: unchanged")
print("live-run temporary data: removed; no production snapshot retained")
print("daily_report.py: parsed only; not imported or executed")
PY
```

종료 코드: 0

출력 원문:

```text
scope: tracked changes limited to daily_report.py, mail_report.py, index.html
hotel_risk / hotelRisk: unchanged
live-run temporary data: removed; no production snapshot retained
daily_report.py: parsed only; not imported or executed
```

## 브라우저 검증 시도

`cua.getState()`의 브라우저 관련 오류 원문(앱 목록 등 무관한 항목 제외):

```text
Browsers: Error: The browser access host is unavailable
```

네이티브 Chrome 대체 경로도 시도했다.

호출:

```javascript
let chrome = await cua.getApp("Google Chrome");
```

출력 원문:

```text
Computer Use was not approved to use Google Chrome
```

자동 승인 검토에서 Google Chrome 사용이 승인되지 않았다. 도구가 구체적인 거절 사유를 제공하지 않았으며, 실제 브라우저 화면은 열람하지 못했다. 미리보기 파일 생성과 Node.js VM의 합성 실행 결과를 브라우저 시각 검증 통과로 간주하지 않았다.

## 대체 검증 및 미검증 범위

- 실데이터: Google News RSS의 DNS 조회가 세 그룹 모두 실패했다. 실제 RSS 응답·보도 건수·검색 쿼리의 실효성은 **미검증**이며 Claude 검수 시 재실행이 필요하다. 기사 원문 크롤링이나 차단 우회는 하지 않았다.
- 합성 대체: RSS 파싱, 중복 제거, 훈련 제외, 24시간/7일 경계, 28일 기준선, 14일 최소 표본, MAD 0, evac 매체 조건, 다른 그룹 z 조건, 부분/전체 실패, CSV/JSON 보존, XSS, HTTP(S) 제한을 테스트했다.
- 메일: JSON 포함/없음 양쪽 `mail_report.build()` 실행과 HTML 생성·문구·escape·링크 검사를 완료했다. 미리보기는 `/private/tmp/war-alert-usfk-wwfknst5/mail-with-json.html`, `mail-without-json.html`에 생성했다. 실제 메일 클라이언트의 시각 배치와 발송은 검증하지 않았다.
- 사이트: 실제 index.html JavaScript를 Node.js VM에서 실행해 JSON 없음, XSS escape, 링크 제한, 제목 8개 상한, hero 제외를 검증했다. 같은 임시 폴더에 합성 fetch 응답을 주입한 `site-with-json.html`, `site-without-json.html`도 생성했다. **실제 브라우저 렌더·반응형 배치·실제 HTTP JSON 로딩은 미검증**이다.
- 환경 경고: Python 3.9.6/LibreSSL 2.8.3 환경에서 urllib3의 NotOpenSSLWarning 1개가 나왔다. 위 테스트 출력에 원문을 기록했다.
- 금지 작업: daily_report.py 실행·import, SerpApi 호출, 메일 발송, git commit/push는 하지 않았다. daily_report.py는 소스 AST로만 검사했다.

