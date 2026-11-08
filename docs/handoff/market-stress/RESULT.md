# RESULT: 시장 스트레스 참고 지표

## 결과

- PLAN 범위 구현 완료. 전체 pytest **68개 통과**(기존 29개 + 신규 39개).
- `python -c "import market_monitor"` 성공. `python market_monitor.py`는 실제로 실행했으나 샌드박스의 Yahoo DNS 해석 실패로 두 심볼 모두 실패했다. **실제 최근 종가·z·판정 및 실제 `data/market.json` 생성은 미검증**이다.
- `python -m http.server`는 샌드박스에서 포트 바인딩이 거부되어 시작하지 못했다. 브라우저에서는 원본 HTML과 합성 JSON을 주입하여 화면을 확인했다. 이 확인은 HTTP 서버 및 실데이터 검증을 대체하지 않는다.
- `daily_report.py` 실행/임포트, SerpApi 사용, 메일 발송, 커밋·푸시는 하지 않았다. 비밀값이나 새 환경변수를 추가하지 않았다.

## 변경 파일

| 파일 | 변경 내용 |
|---|---|
| `market_monitor.py` | Yahoo chart 수집, null/비정상 응답 방어, 90거래일 보관, robust z, 참고 판정, 429·비 JSON 응답 15·30초 재시도, 심볼별 실패 분리, 원자적 JSON 교체 |
| `tests/test_market_monitor.py` | 신규 39개 합성 테스트: 파싱·계산·경계값·실패·기존 파일 보존·메일 연결/이스케이프/지연/배너 유지 |
| `daily_report.py` | 모듈 import 및 parts에 시장 스트레스 추가. 실행하지 않고 AST/소스만 확인 |
| `mail_report.py` | `render`의 선택적 `M` 인자, `build` 로딩 연결, 빈 상태를 포함한 04 섹션. 기존 판정 배너 유지 |
| `index.html` | 04 섹션, 카드 2개, 빈 상태·데이터 지연·실패 표시, 외부 문자열 escape, 560px 이하 1열. `hero()` 유지 |
| `docs/handoff/market-stress/RESULT.md` | 이 결과서 |

`PLAN.md`는 작업 시작 전부터 untracked 상태였으며 수정하지 않았다. `CLAUDE.md`, 워크플로, 호텔 위험도 로직은 수정하지 않았다.

## 구현 해석 및 동작

- 20거래일 변화율 `x = (최근 종가 / 20거래일 전 종가 - 1) * 100`을 계산한다. 기준선은 이 20일 구간을 제외한 그 이전 최대 60개 일간 변화율이다. `news_monitor.robust_z`를 재사용하여 `(x - 중앙값) / (1.4826 * MAD)`를 구한다. 코스피 z에는 -1을 곱한다. 계산식/기간/임계값은 JSON `config`에 명시한다.
- 어느 하나라도 반올림 전 z ≥ 2.0이면 watch, 둘 다 해당하면 동시 악화 문구를 추가한다. 판단 가능한 두 값이 모두 임계 미만이면 normal, 판단할 수 없는 값이 있으면 muted다. 다른 심볼이 watch이면 부분 실패 상태에서도 watch를 표시한다. `alerts`는 항상 빈 배열이다.
- 표본 30개 미만 또는 MAD 0이면 해당 심볼 판단을 보류한다. 한 심볼 실패 시 `latest[심볼].error` 및 최상위 `error`에 기록하고 다른 심볼을 처리한다. 두 심볼 실패 시 쓰기 전에 RuntimeError를 올린다. JSON은 임시 파일의 직렬화·쓰기 완료 후 교체하므로 실패 시 기존 파일을 유지한다.
- 날짜는 Yahoo 거래소 시간대로 읽고, 종가 null/비유한 수/0 이하 및 비정상 타임스탬프를 제외한다. 종가와 타임스탬프의 위치 관계를 유지한다. 배열 불일치·예상 밖 응답 형태는 심볼 실패로 처리한다.
- 출처 `Yahoo Finance (비공식 API)`와 `대리 지표 · 신뢰도 낮음 · 경보 없음`을 사이트·메일에 표시한다. 사이트의 지연은 열람 시점 KST 날짜와 최신 거래일을 비교한다(3일 초과).

## 실행한 검증 명령과 출력 원문

작업 디렉터리는 모두 `/Users/dex/war-alert`이다. 아래는 실제 실행한 검증·미리보기·검사 명령이며, 출력은 stdout/stderr 원문이다. 출력이 없으면 별도로 표시했다. 기존 환경의 LibreSSL/urllib3 경고도 생략하지 않았다.

### 1. 구현 전 기존 테스트

실행 명령:

```sh
source .venv/bin/activate && python -m pytest tests/
```

종료 코드: 0

출력 원문:

```text
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
rootdir: /Users/dex/war-alert
collected 29 items

tests/test_gdelt_gkg.py .............................                    [100%]

=============================== warnings summary ===============================
.venv/lib/python3.9/site-packages/urllib3/__init__.py:35
  /Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
    warnings.warn(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 29 passed, 1 warning in 0.41s =========================
```

### 2. 구현 후 전체 테스트

실행 명령:

```sh
source .venv/bin/activate && python -m pytest tests/
```

종료 코드: 0

출력 원문:

```text
============================= test session starts ==============================
platform darwin -- Python 3.9.6, pytest-8.4.2, pluggy-1.6.0
rootdir: /Users/dex/war-alert
collected 68 items

tests/test_gdelt_gkg.py .............................                    [ 42%]
tests/test_market_monitor.py .......................................     [100%]

=============================== warnings summary ===============================
.venv/lib/python3.9/site-packages/urllib3/__init__.py:35
  /Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
    warnings.warn(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 68 passed, 1 warning in 0.37s =========================
```

### 3. 임포트 확인

실행 명령:

```sh
source .venv/bin/activate && python -c "import market_monitor"
```

종료 코드: 0

출력 원문:

```text
/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
```

### 4. 실제 Yahoo 실행 시도 — DNS 실패

실행 명령:

```sh
source .venv/bin/activate && python market_monitor.py
```

종료 코드: 1

출력 원문:

```text
/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
Traceback (most recent call last):
  File "/Users/dex/war-alert/market_monitor.py", line 163, in <module>
    alerts, lines = run()
  File "/Users/dex/war-alert/market_monitor.py", line 146, in run
    raise RuntimeError("시장 데이터 모두 수집 실패: " + "; ".join(f"{s}: {e}" for s, e in errors.items()))
RuntimeError: 시장 데이터 모두 수집 실패: KRW=X: HTTPSConnectionPool(host='query1.finance.yahoo.com', port=443): Max retries exceeded with url: /v8/finance/chart/KRW%3DX?range=6mo&interval=1d (Caused by NameResolutionError("HTTPSConnection(host='query1.finance.yahoo.com', port=443): Failed to resolve 'query1.finance.yahoo.com' ([Errno 8] nodename nor servname provided, or not known)")); ^KS11: HTTPSConnectionPool(host='query1.finance.yahoo.com', port=443): Max retries exceeded with url: /v8/finance/chart/%5EKS11?range=6mo&interval=1d (Caused by NameResolutionError("HTTPSConnection(host='query1.finance.yahoo.com', port=443): Failed to resolve 'query1.finance.yahoo.com' ([Errno 8] nodename nor servname provided, or not known)"))
```

### 5. HTTP 서버 실행 시도 — 바인딩 거부

실행 명령:

```sh
source .venv/bin/activate && python -m http.server 8765 --bind 127.0.0.1
```

종료 코드: 1

출력 원문:

```text
Traceback (most recent call last):
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/runpy.py", line 197, in _run_module_as_main
    return _run_code(code, main_globals, None,
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/runpy.py", line 87, in _run_code
    exec(code, run_globals)
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/http/server.py", line 1297, in <module>
    test(
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/http/server.py", line 1252, in test
    with ServerClass(addr, HandlerClass) as httpd:
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/socketserver.py", line 452, in __init__
    self.server_bind()
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/http/server.py", line 1295, in server_bind
    return super().server_bind()
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/http/server.py", line 138, in server_bind
    socketserver.TCPServer.server_bind(self)
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/socketserver.py", line 466, in server_bind
    self.socket.bind(self.server_address)
PermissionError: [Errno 1] Operation not permitted
```

### 6. 합성 Yahoo 응답으로 전체 수집·계산·JSON 출력

실행 명령:

```sh
source .venv/bin/activate && python - <<'PY'
import datetime as dt
import json
from pathlib import Path
from unittest.mock import Mock, patch
import market_monitor as market

outdir = Path('/private/tmp/war-alert-market-stress')
outdir.mkdir(exist_ok=True)
market.JSON_FILE = outdir / 'market.json'
start = dt.datetime(2026, 8, 13, tzinfo=dt.timezone.utc)
payloads = []
for symbol in market.SYMBOLS:
    closes = [1000.0 if symbol == 'KRW=X' else 2500.0]
    returns = [-0.2, -0.1, 0.1, 0.2] * 15 + ([0.5] if symbol == 'KRW=X' else [-0.5]) * 20
    for value in returns:
        closes.append(closes[-1] * (1 + value / 100))
    closes.append(None)
    payloads.append({'chart': {'error': None, 'result': [{'meta': {'exchangeTimezoneName': 'Asia/Seoul'}, 'timestamp': [(start + dt.timedelta(days=i)).timestamp() for i in range(len(closes))], 'indicators': {'quote': [{'close': closes}]}}]}})
responses = []
for payload in payloads:
    response = Mock(status_code=200)
    response.json.return_value = payload
    responses.append(response)
with patch.object(market.requests, 'get', side_effect=responses):
    alerts, lines = market.run()
print('SYNTHETIC DATA ONLY: mocked Yahoo responses; not real-data verification')
print(*lines, sep='\n')
data = json.loads(market.JSON_FILE.read_text())
assert alerts == data['alerts'] == []
assert data['status'] == 'watch'
print('synthetic JSON:', market.JSON_FILE)
print('production data/market.json exists:', Path('data/market.json').exists())
print(json.dumps({'status': data['status'], 'latest': data['latest']}, ensure_ascii=False, indent=2))
PY
```

종료 코드: 0

출력 원문:

```text
/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
SYNTHETIC DATA ONLY: mocked Yahoo responses; not real-data verification
원/달러 환율 2026-11-01: 종가 1,104.81 · 전일 대비 +0.50% · z +47.17
코스피 2026-11-01: 종가 2,261.36 · 전일 대비 -0.50% · z +42.89
주의: 원/달러 환율 스트레스 증가 (z +47.17)
주의: 코스피 스트레스 증가 (z +42.89)
주의: 환율·코스피 동시 악화
판정: watch
출처: Yahoo Finance (비공식 API) · 대리 지표 · 신뢰도 낮음 · 경보 없음
synthetic JSON: /private/tmp/war-alert-market-stress/market.json
production data/market.json exists: False
{
  "status": "watch",
  "latest": {
    "KRW=X": {
      "date": "2026-11-01",
      "close": 1104.8127129850143,
      "change_pct": 0.49999999999998934,
      "change_20d_pct": 10.489557718672838,
      "base_n": 60,
      "median": -5.551115123125783e-15,
      "z": 47.167398348276556,
      "status": "watch"
    },
    "^KS11": {
      "date": "2026-11-01",
      "close": 2261.3565922935472,
      "change_pct": -0.5000000000000004,
      "change_20d_pct": -9.538951972538223,
      "base_n": 60,
      "median": 0.0,
      "z": 42.89289973712044,
      "status": "watch"
    }
  }
}
```

### 7. market.json 없는 실제 로컬 데이터로 메일 미리보기

실행 명령:

```sh
source .venv/bin/activate && python -c "import mail_report; from pathlib import Path; html = mail_report.build('2026-11-08', [], []); path = Path('/private/tmp/war-alert-market-stress/mail-without-market.html'); path.write_text(html, encoding='utf-8'); assert '04 시장 스트레스' in html; assert '시장 데이터를 기다리는 중' in html; assert 'Yahoo Finance (비공식 API)' in html; print('PASS: missing market.json -> 04 section and empty state'); print(path)"
```

종료 코드: 0

출력 원문:

```text
PASS: missing market.json -> 04 section and empty state
/private/tmp/war-alert-market-stress/mail-without-market.html
```

### 8. 합성 market JSON으로 메일 미리보기

실행 명령:

```sh
source .venv/bin/activate && python -c "import json, mail_report; from pathlib import Path; market = json.loads(Path('/private/tmp/war-alert-market-stress/market.json').read_text()); html = mail_report.render('2026-11-08', [], [], None, None, None, market); path = Path('/private/tmp/war-alert-market-stress/mail-with-market.html'); path.write_text(html, encoding='utf-8'); assert '04 시장 스트레스' in html; assert '동시 악화' in html; assert '데이터 지연' in html; assert '특이 동향 없음' in html; print('PASS: synthetic watch -> 04 section, simultaneous watch, data lag, unchanged verdict'); print(path)"
```

종료 코드: 0

출력 원문:

```text
PASS: synthetic watch -> 04 section, simultaneous watch, data lag, unchanged verdict
/private/tmp/war-alert-market-stress/mail-with-market.html
```

### 9. diff 공백 검사

실행 명령:

```sh
git diff --check
```

종료 코드: 0

출력 없음.

### 10. Python 문법·금지 로직·수정 범위 검사

실행 명령:

```sh
source .venv/bin/activate && python - <<'PY'
import ast
from pathlib import Path
import subprocess

for filename in ('market_monitor.py', 'mail_report.py', 'daily_report.py', 'tests/test_market_monitor.py'):
    ast.parse(Path(filename).read_text(), filename=filename)
def original(filename):
    return subprocess.check_output(['git', 'show', 'HEAD:' + filename], text=True)
def function(source, name):
    return next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == name)
assert ast.dump(function(Path('mail_report.py').read_text(), 'hotel_risk')) == ast.dump(function(original('mail_report.py'), 'hotel_risk'))
site, old_site = Path('index.html').read_text(), original('index.html')
for start, end in [('function hotelRisk(', 'const CC='), ('function hero(){', '/* ───── 대사관·여행경보 ───── */')]:
    assert site[site.index(start):site.index(end)] == old_site[old_site.index(start):old_site.index(end)]
changed = subprocess.check_output(['git', 'diff', '--name-only'], text=True).splitlines()
assert set(changed) <= {'daily_report.py', 'mail_report.py', 'index.html', 'docs/handoff/market-stress/RESULT.md'}
assert 'market_monitor.run' in Path('daily_report.py').read_text()
print('PASS: Python syntax; hotel_risk, hotelRisk, hotelWorst and hero unchanged; tracked changes within PLAN scope')
print('daily_report.py parsed only; not imported or executed')
PY
```

종료 코드: 0

출력 원문:

```text
PASS: Python syntax; hotel_risk, hotelRisk, hotelWorst and hero unchanged; tracked changes within PLAN scope
daily_report.py parsed only; not imported or executed
```

### 11. 사이트 JavaScript 문법 검사

실행 명령:

```sh
node - <<'JS'
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync('index.html', 'utf8');
new vm.Script(html.match(/<script>([\s\S]*?)<\/script>/)[1], {filename:'index.html'});
console.log('PASS: index.html JavaScript syntax');
JS
```

종료 코드: 0

출력 원문:

```text
PASS: index.html JavaScript syntax
```

### 12. 금지 파일 diff 검사

실행 명령:

```sh
git diff --exit-code -- CLAUDE.md .github/workflows hotel_monitor.py
```

종료 코드: 0

출력 없음.

### 13. 브라우저 임시 파일 이동 전 상태 확인

실행 명령:

```sh
git status --short --untracked-files=all
```

종료 코드: 0

출력 원문:

```text
 M daily_report.py
 M index.html
 M mail_report.py
?? .playwright-mcp/element-2026-11-08T14-09-11-708Z.png
?? .playwright-mcp/page-2026-11-08T14-08-41-467Z.yml
?? docs/handoff/market-stress/PLAN.md
?? market_monitor.py
?? tests/test_market_monitor.py
```

### 14. 생성한 브라우저 임시 파일을 작업 트리 밖으로 이동

실행 명령:

```sh
source .venv/bin/activate && python - <<'PY'
from pathlib import Path
import shutil
for name in ('element-2026-11-08T14-09-11-708Z.png', 'page-2026-11-08T14-08-41-467Z.yml'):
    source = Path('.playwright-mcp') / name
    target = Path('/private/tmp/war-alert-market-stress') / name
    shutil.move(str(source), str(target))
    print(f'Moved generated browser artifact: {source} -> {target}')
PY
```

종료 코드: 0

출력 원문:

```text
Moved generated browser artifact: .playwright-mcp/element-2026-11-08T14-09-11-708Z.png -> /private/tmp/war-alert-market-stress/element-2026-11-08T14-09-11-708Z.png
Moved generated browser artifact: .playwright-mcp/page-2026-11-08T14-08-41-467Z.yml -> /private/tmp/war-alert-market-stress/page-2026-11-08T14-08-41-467Z.yml
```

## 브라우저 검증

Playwright 도구를 사용했다. 로컬 HTTP 서버를 실행하지 못해 `about:blank`에서 원본 `index.html`을 `document.write`로 넣고 `window.fetch`가 합성 market 응답과 나머지 데이터의 실패 응답을 돌려주도록 했다. 실제 Yahoo 데이터·실제 HTTP 요청 검증이 아니다. 아래 `browser_evaluate`의 `### Result` 부분은 도구가 반환한 결과 원문이며, 자동으로 반복 출력되는 실행 코드 부분은 바로 위 입력과 중복되어 제외했다.

먼저 시도한 브라우저 경로의 실제 실패 기록:

- `browser_run_code_unsafe`: 로컬 파일을 읽어 응답을 주입하는 코드를 요청했으나 승인 정책으로 실행 전에 차단됨. 해당 코드는 실행되지 않았다.

```text
MCP tool call requires approval, but approval policy is never
```

- `browser_navigate` 입력:

```json
{
  "url": "file:///Users/dex/war-alert/index.html"
}
```

출력 원문:

```text
### Error
Error: Access to "file:" protocol is blocked. Attempted URL: "file:///Users/dex/war-alert/index.html"
```

이후 `browser_navigate({"url":"about:blank"})`가 성공했고, 호스트에서 코드를 실행하는 대신 브라우저 안에서 HTML/합성 응답을 주입하는 `browser_evaluate`를 사용했다. 주입 결과 원문:

```text
### Result
{
  "mode": "synthetic HTML and fetch injection in about:blank"
}
```

### 브라우저 확인 1: mcp__playwright__browser_resize

입력 원문:

```json
{
  "width": 1080,
  "height": 900
}
```

결과 원문:

```text
```

### 브라우저 확인 2: mcp__playwright__browser_evaluate

입력 원문:

```json
{
  "function": "() => ({\n  tiles: document.querySelectorAll('#marketBody .tile').length,\n  watch: document.querySelector('#marketBody').textContent.includes('동시 악화'),\n  lag: document.querySelector('#marketBody').textContent.includes('데이터 지연'),\n  hero: document.querySelector('#verdict').textContent,\n  columns: getComputedStyle(document.querySelector('.market-tiles')).gridTemplateColumns,\n  overflow: document.documentElement.scrollWidth > innerWidth,\n  marketText: document.querySelector('#marketBody').textContent\n})"
}
```

결과 원문:

```text
### Result
{
  "tiles": 2,
  "watch": true,
  "lag": true,
  "hero": "데이터 수집 전",
  "columns": "511.5px 511.5px",
  "overflow": false,
  "marketText": "주의 · 참고원/달러 환율 스트레스 증가 (z +47.17) · 코스피 스트레스 증가 (z +42.89) · 환율·코스피 동시 악화원/달러 환율1,104.81 원전일 대비 +0.50% · 스트레스 z +47.17주의2026-11-01 · 데이터 지연코스피2,261.36 pt전일 대비 -0.50% · 스트레스 z +42.89주의2026-11-01 · 데이터 지연"
}
```

### 브라우저 확인 3: mcp__playwright__browser_resize

입력 원문:

```json
{
  "width": 375,
  "height": 812
}
```

결과 원문:

```text
```

### 브라우저 확인 4: mcp__playwright__browser_evaluate

입력 원문:

```json
{
  "function": "() => ({\n  tiles: document.querySelectorAll('#marketBody .tile').length,\n  watch: document.querySelector('#marketBody').textContent.includes('동시 악화'),\n  lag: document.querySelector('#marketBody').textContent.includes('데이터 지연'),\n  hero: document.querySelector('#verdict').textContent,\n  columns: getComputedStyle(document.querySelector('.market-tiles')).gridTemplateColumns,\n  overflow: document.documentElement.scrollWidth > innerWidth,\n  marketText: document.querySelector('#marketBody').textContent\n})"
}
```

결과 원문:

```text
### Result
{
  "tiles": 2,
  "watch": true,
  "lag": true,
  "hero": "데이터 수집 전",
  "columns": "328px",
  "overflow": false,
  "marketText": "주의 · 참고원/달러 환율 스트레스 증가 (z +47.17) · 코스피 스트레스 증가 (z +42.89) · 환율·코스피 동시 악화원/달러 환율1,104.81 원전일 대비 +0.50% · 스트레스 z +47.17주의2026-11-01 · 데이터 지연코스피2,261.36 pt전일 대비 -0.50% · 스트레스 z +42.89주의2026-11-01 · 데이터 지연"
}
```

### 브라우저 확인 5: mcp__playwright__browser_resize

입력 원문:

```json
{
  "width": 560,
  "height": 900
}
```

결과 원문:

```text
```

### 브라우저 확인 6: mcp__playwright__browser_evaluate

입력 원문:

```json
{
  "function": "() => ({width:innerWidth, columns:getComputedStyle(document.querySelector('.market-tiles')).gridTemplateColumns, overflow:document.documentElement.scrollWidth>innerWidth})"
}
```

결과 원문:

```text
### Result
{
  "width": 560,
  "columns": "513px",
  "overflow": false
}
```

### 브라우저 확인 7: mcp__playwright__browser_resize

입력 원문:

```json
{
  "width": 320,
  "height": 812
}
```

결과 원문:

```text
```

### 브라우저 확인 8: mcp__playwright__browser_evaluate

입력 원문:

```json
{
  "function": "() => {\n  const attack='<img src=x onerror=\"window.injected=true\">';\n  M=JSON.parse(JSON.stringify(window._marketFixture));\n  M.watch.push(attack);\n  M.latest['^KS11']={error:attack};\n  market();\n  return {\n    tiles:document.querySelectorAll('#marketBody .tile').length,\n    failure:document.querySelector('#marketBody').textContent.includes('수집 실패'),\n    escaped:!window.injected && !document.querySelector('#marketBody img') && document.querySelector('#marketBody').textContent.includes('<img'),\n    overflow:document.documentElement.scrollWidth>innerWidth,\n    hero:document.querySelector('#verdict').textContent\n  };\n}"
}
```

결과 원문:

```text
### Result
{
  "tiles": 2,
  "failure": true,
  "escaped": true,
  "overflow": false,
  "hero": "데이터 수집 전"
}
```

### 브라우저 확인 9: mcp__playwright__browser_evaluate

입력 원문:

```json
{
  "function": "() => {\n  M=null;\n  market();\n  return {\n    empty:!!document.querySelector('#marketBody .empty'),\n    message:document.querySelector('#marketBody').textContent,\n    source:document.querySelector('#sec-market').textContent.includes('Yahoo Finance (비공식 API)'),\n    overflow:document.documentElement.scrollWidth>innerWidth\n  };\n}"
}
```

결과 원문:

```text
### Result
{
  "empty": true,
  "message": "시장 데이터를 기다리는 중입니다다음 자동 수집 후 표시됩니다.",
  "source": true,
  "overflow": false
}
```

시장 섹션 모바일 캡처도 확인했다. 처음 `/private/tmp`로 직접 저장 요청은 Playwright 허용 경로 밖이라 거부되었다:

```text
### Error
Error: File access denied: /private/tmp/war-alert-market-stress/site-market-mobile.png is outside allowed roots. Allowed roots: /Users/dex/war-alert/.playwright-mcp, /Users/dex/war-alert
```

그 뒤 허용된 기본 경로에 캡처하고, 위 14번 명령으로 생성한 PNG와 snapshot만 `/private/tmp/war-alert-market-stress`로 이동했다. 캡처 도구 결과 원문:

```text
### Result
- [Screenshot of 시장 스트레스 섹션](.playwright-mcp/element-2026-11-08T14-09-11-708Z.png)
### Ran Playwright code
```js
// Screenshot 시장 스트레스 섹션 and save it as .playwright-mcp/element-2026-11-08T14-09-11-708Z.png
await page.locator('#sec-market').screenshot({
  path: '.playwright-mcp/element-2026-11-08T14-09-11-708Z.png',
  scale: 'css',
  type: 'png'
});
```
```

`browser_console_messages` 입력 `{"level":"error"}` 결과 원문:

```text
### Result
Total messages: 0 (Errors: 0, Warnings: 0)
```

## 산출물 및 미검증 범위

- 합성 JSON: `/private/tmp/war-alert-market-stress/market.json`. 합성 종가는 환율 1,104.8127129850143 / 코스피 2,261.3565922935472, 스트레스 z는 각각 +47.167398348276556 / +42.89289973712044, 판정 watch이다. **실제 시장값이 아니다.** 전체 출력 원문은 6번에 있다.
- 메일 미리보기: `/private/tmp/war-alert-market-stress/mail-without-market.html`, `/private/tmp/war-alert-market-stress/mail-with-market.html`. 전자는 시장 JSON 없이 로컬의 기존 01~03 데이터를 읽었고, 후자는 합성 market만 넣었다. SMTP 발송 및 실제 메일 앱 렌더링은 검증하지 않았다.
- 브라우저 모바일 캡처: `/private/tmp/war-alert-market-stress/element-2026-11-08T14-09-11-708Z.png`. 1080px에서 2열, 560px·375px에서 1열, 320px 부분 실패·escape·빈 상태에서 가로 넘침 없음. 시장 watch가 전체 hero 경보에 영향을 주지 않는 것을 확인했다.
- **샌드박스의 네트워크/DNS가 차단되어 `query1.finance.yahoo.com`의 이름을 해석하지 못했다.** 실제 Yahoo 응답 파싱·실제 최근 종가/z/판정과 운영용 `data/market.json` 생성은 미검증이다. 실제 실행 실패 후 운영용 파일은 없으며, 합성 파일을 운영 위치에 두지 않았다. 네트워크가 허용되는 환경에서 `source .venv/bin/activate && python market_monitor.py` 재실행이 필요하다.
- HTTP 서버는 `PermissionError: [Errno 1] Operation not permitted`로 실패했다. 실제 서버에서 JSON을 fetch하는 브라우저 검증은 미검증이다. 합성 HTML·fetch 주입 검증만 수행했다.
- 429·비 JSON 재시도, 한/두 심볼 실패, 기존 JSON 보존은 합성 테스트로 검증했다. 실제 429 응답/휴장일 API 응답은 검증하지 않았다. 재시도 테스트에서는 sleep을 mock 처리해 15·30초 호출 인자를 확인했다.
- `daily_report.py` 통합 실행·SerpApi·SMTP 발송·커밋·푸시는 요청의 금지 사항이므로 수행하지 않았다. Claude 검수와 `REVIEW.md` 작성은 이 작업에 포함하지 않았다.

## RESULT 작성 후 최종 검사

실행 명령:

```sh
git diff --check
```

종료 코드: 0

출력 없음.

실행 명령:

```sh
git status --short --untracked-files=all
```

종료 코드: 0

출력 원문:

```text
 M daily_report.py
 M index.html
 M mail_report.py
?? docs/handoff/market-stress/PLAN.md
?? docs/handoff/market-stress/RESULT.md
?? market_monitor.py
?? tests/test_market_monitor.py
```


