# RESULT: GDELT GKG 폴백 구현

작성일: 2026-11-08. 작업 디렉터리: `/Users/dex/war-alert`.

구현은 완료했으나 수용 기준 전체 통과로 판정하지 않는다. 로컬 가상환경에 pytest가 없고 설치 대상 PyPI 및 GDELT 호스트의 DNS 조회가 실패했다. 지정된 pytest 명령과 실제 2일 집계는 실패했다. 같은 합성 테스트를 표준 unittest로 실행한 최종 결과는 28개 통과다.

## 변경 파일

- `news_monitor.py`: DOC 주 수집 실패·빈 데이터·마지막 온전한 날의 3일 초과 지연 시 GKG 폴백. DOC 부가 논조·기사 목록의 기존 선택적 실패 처리는 유지. JSON 루트 및 series에 출처 표시. GKG의 긴 대체 제목은 URL로 중복 제거.
- `gdelt_gkg.py` (신규): UTC 날짜 규칙으로 하루 96개 URL 생성, 리다이렉트 허용, HTTP 청크 수신 및 TSV 줄 단위 집계, 일별 CSV 체크포인트, 기존 DOC series 병합, 최대 3일 증분 처리와 `--backfill 1|2|3`, 다운로드 바이트·소요 시간 출력.
- `tests/test_gdelt_gkg.py` (신규): 합성 GKG 파싱·집계·오류·캐시·폴백 분기·JSON 계약·기존 평가 결과 비교·합성 2일 CLI 경로 등 28개 테스트. unittest TestCase이므로 pytest에서도 수집 가능한 형태이나, 실제 pytest 실행은 아래와 같이 실패했다.
- `docs/handoff/gdelt-gkg-fallback/RESULT.md` (신규): 이 보고서.

`PLAN.md`는 수정하지 않았다. 수정 금지 파일 4개와 기존 `data/news.json`이 HEAD와 바이트 단위로 동일함을 확인했다. 실제 백필은 첫 다운로드 전에 실패했으므로 `data/news_gkg_daily.csv`가 생성되지 않았다. 합성 검증의 CSV·JSON은 임시 디렉터리에만 작성했다. 원본 ZIP·TSV를 저장소에 저장하지 않았다. 커밋·푸시·daily_report 실행·SerpApi 호출·메일 발송은 하지 않았다.

## 구현 해석 및 컬럼 확인

공식 [GKG 2.1 코드북](https://data.gdeltproject.org/documentation/GDELT-Global_Knowledge_Graph_Codebook-V2.1.pdf)의 필드 순서와 형식을 확인했다. 실제 원본 행 다운로드는 DNS 실패로 확인하지 못했다.

| 구현 명칭 | 공식 명칭 | 1부터 센 열 / Python 인덱스 | 사용 |
| --- | --- | --- | --- |
| DocumentIdentifier | V2DOCUMENTIDENTIFIER | 5 / 4 | 기사 URL |
| V2Themes | V2ENHANCEDTHEMES | 9 / 8 | 테마 및 문자 위치 |
| V2Tone | V1.5TONE | 16 / 15 | 쉼표 앞 첫 논조 값 |
| DATE | V2.1DATE | 2 / 1 | 기사 날짜 |

GKG는 제목 전용 컬럼이 없으므로 테마와 URL에서 영어 문구·키워드를 찾고 기사 제목은 도메인과 URL로 대체한다. URL 퍼센트 인코딩을 해제하고 구두점·밑줄·하이픈을 공백으로 정규화한 뒤 두 지역 문구 중 하나와 여섯 전쟁 단어 중 하나를 단어 경계로 함께 검사한다. V1Themes·Locations·본문을 추가 검색하지 않는다. 같은 URL의 중복 레코드도 total/count에는 각각 포함하고 기사 목록에서만 중복 제거한다. 논조가 없는 관련 행은 건수에는 포함하고 유효한 논조들의 평균을 사용한다. 잘못된 컬럼·논조·ZIP 및 네트워크 오류는 RuntimeError로 전파한다.

압축 파일 하나를 HTTP 청크로 RAM의 BytesIO에 받고 ZipFile로 열어 해제된 TSV를 줄 단위로 읽는다. ZIP 중앙 디렉터리 탐색을 위해 압축 파일 하나는 메모리에 보관한다. 디스크 원본 저장과 전체 하루 원본 적재는 하지 않는다.

증분 수집은 UTC 오늘을 제외한 최근 29일(최신 하루 + 기준선 28일)의 CSV 누락일 중 최신 날짜부터 처리한다. 기본 최대 3일, `--backfill 2`는 누락일 최대 2일이다. 96개 전부 성공한 날마다 CSV를 원자적으로 교체하고, 다음 날짜 실패 시 성공한 날짜는 남긴 채 예외를 올린다. 이전 DOC series를 유지하고 같은 날짜는 GKG로 덮어쓴다. JSON 루트 source는 날짜가 가장 최근인 series 행의 출처이며, 각 series 행에도 출처가 있다. 기사 목록은 가장 최근에 확보한 집계일의 파일·행 순서에서 중복 없는 HTTP(S) URL 최대 12개를 쓴다. 더 오래된 백필이 기존 최신 기사 목록을 덮지 않는다.

## 수용 기준별 실제 결과

| 수용 기준 | 결과 | 근거 |
| --- | --- | --- |
| `python -m pytest tests/` | 실패 / 미충족 | pytest 모듈 없음. 오프라인 설치 캐시 없음, 온라인 설치 DNS 실패. 아래 원문 |
| 네트워크 없는 합성 검증 | 대체 실행 통과 | `python -m unittest discover -s tests -v`: 최종 28 tests, OK. pytest 통과로 대신 표기하지 않음 |
| `python -c "import news_monitor"` | 통과 | 종료 코드 0. 기존 urllib3/LibreSSL 경고 있음 |
| 기존 `evaluate()` 결과 불변 | 통과 | evaluate/robust_z AST 동일. 기존 news.json의 latest와 동일. 합성 기준선·급증·부분일·MAD 0·기준선 부족 사례를 HEAD의 원본 함수와 비교 |
| 실제 `python gdelt_gkg.py --backfill 2` | 실패 / 미충족 | 2026-11-07 첫 파일 DNS 실패. 완료 집계 0일, 0바이트, CLI 집계 구간 0.03초, 도구 측 프로세스 대기 0.096286917초 |
| 2일 CLI 처리 연결 | 합성으로만 통과 | 192개 합성 ZIP을 요청하는 main 경로, CSV 2행·GKG JSON·비율 및 바이트 출력 확인. 실데이터 성공이 아님 |
| 수정 금지 파일·daily_report 금지 | 준수 | 4개 파일 HEAD와 동일. daily_report 미실행 |

## 미검증 범위 및 검수 시 주의점

- 실제 GDELT 2일 집계·실제 압축 파일 구조·실제 행 내용·실제 리다이렉트 응답은 미검증이다. 리다이렉트 허용 옵션과 합성 ZIP 96개 집계는 테스트했다.
- pytest 자체 실행, GitHub Actions의 시간·다운로드 용량·최대 메모리 및 운영 메일 연동은 미검증이다. 기존 LibreSSL 환경에서 urllib3 경고가 출력된다.
- 기존 evaluate()는 전체 series의 total 중앙값 절반으로 partial을 판단한다. DOC와 GKG의 total 분포 차이가 크면 96개 파일을 모두 읽은 GKG 날짜도 partial로 분류되어 latest가 이전 DOC 날짜에 머물 수 있다. 이 현상을 합성 테스트로 확인했으며 판정 함수는 변경하지 않았다. 실제 2일 수집 후 분포·latest 검수가 필요하다.
- GKG 메타데이터·URL 매칭은 DOC의 본문 검색과 모집단·검색 범위가 다르다. 출처를 표기했으나 두 출처 비율의 동등성 및 혼합 기준선의 통계적 적합성은 미검증이다.
- 28일 전체 백필은 실행하지 않았다. 28일은 2,688개 파일이며, 성공한 2일의 소요 시간 T2와 다운로드 B2가 있으면 단순 예상은 T28 ≈ 14×T2, B28 ≈ 14×B2다. 이번 0.03초·0바이트는 DNS 실패값이므로 이 식에 대입하지 않는다. 성공 실측이 없어 분·GB 단위의 신뢰할 만한 예상은 산출하지 못했다. 최초 29일(최신+28일) 확보는 2,784개 파일이며 실행당 3일 상한으로 나누어 처리해야 한다.

## 실제 명령 및 출력 원문

아래는 구현 검증·의존성 설치·실제 백필에 사용한 명령의 실행 순서와 도구가 반환한 stdout/stderr 결합 원문이다. 탐색용 파일 조회(cat/rg/ls)와 편집 호출은 제외했다. 출력은 생략하거나 성공 문구로 바꾸지 않았다. 모든 명령의 작업 디렉터리는 `/Users/dex/war-alert`다.

### 실행 1 (종료 코드 1)

```sh
source .venv/bin/activate
uv pip install --offline --python .venv/bin/python pytest
```

```text
error: No solution found when resolving dependencies
  cause: Because pytest was not found in the cache and you require pytest, we can conclude that your requirements are unsatisfiable.

hint: Packages were unavailable because the network was disabled. When the network is disabled, registry packages may only be read from the cache.
```

### 실행 2 (종료 코드 1)

```sh
source .venv/bin/activate
python -m pytest tests/
```

```text
/Users/dex/war-alert/.venv/bin/python: No module named pytest
```

### 실행 3 (종료 코드 0)

```sh
source .venv/bin/activate
python -c "import news_monitor"
```

```text
/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
```

### 실행 4 (종료 코드 0)

```sh
source .venv/bin/activate
python -m unittest discover -s tests -v
```

```text
/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
test_backfill_over_three_is_rejected (test_gdelt_gkg.CacheTests) ... ok
test_cached_window_needs_no_network_and_preserves_articles (test_gdelt_gkg.CacheTests) ... ok
test_doc_history_merge_overwrite_and_newest_articles (test_gdelt_gkg.CacheTests) ... ok
test_failed_partial_day_is_not_saved (test_gdelt_gkg.CacheTests) ... ok
test_incremental_cap_and_cached_dates_are_not_downloaded (test_gdelt_gkg.CacheTests) ... ok
test_old_backfill_does_not_replace_saved_latest_articles (test_gdelt_gkg.CacheTests) ... ok
test_successful_day_persists_when_next_day_fails (test_gdelt_gkg.CacheTests) ... ok
test_doc_failures_empty_and_malformed_use_gkg (test_gdelt_gkg.FallbackTests) ... ok
test_evaluate_matches_original_on_existing_series_and_alert_cases (test_gdelt_gkg.FallbackTests) ... ok
test_exactly_three_days_late_remains_doc (test_gdelt_gkg.FallbackTests) ... ok
test_gkg_failure_propagates (test_gdelt_gkg.FallbackTests) ... ok
test_optional_doc_metadata_failure_preserves_existing_behavior (test_gdelt_gkg.FallbackTests) ... ok
test_run_preserves_json_contract_and_adds_source (test_gdelt_gkg.FallbackTests) ... ok
test_stale_full_day_ignores_new_partial_day (test_gdelt_gkg.FallbackTests) ... ok
test_all_six_keywords_case_and_separators (test_gdelt_gkg.ParsingTests) ... ok
test_articles_are_bounded_and_http_only (test_gdelt_gkg.ParsingTests) ... ok
test_bad_rows_and_tone_are_explicit_errors (test_gdelt_gkg.ParsingTests) ... ok
test_matching_uses_only_document_and_enhanced_themes (test_gdelt_gkg.ParsingTests) ... ok
test_missing_tone_and_no_matches (test_gdelt_gkg.ParsingTests) ... ok
test_network_http_and_zip_errors_become_runtime_errors (test_gdelt_gkg.ParsingTests) ... ok
test_records_are_counted_even_if_url_is_duplicate (test_gdelt_gkg.ParsingTests) ... ok
test_streamed_day_totals_tone_and_download_bytes (test_gdelt_gkg.ParsingTests) ... ok
test_urls_cover_exactly_one_utc_day (test_gdelt_gkg.ParsingTests) ... ok

----------------------------------------------------------------------
Ran 23 tests in 0.178s

OK
```

### 실행 5 (종료 코드 2)

```sh
source .venv/bin/activate
UV_HTTP_TIMEOUT=10 UV_HTTP_RETRIES=0 uv pip install --python .venv/bin/python pytest
```

```text
error: Failed to fetch: https://pypi.org/simple/pytest/
  cause: error sending request for url (https://pypi.org/simple/pytest/)
  cause: client error (Connect)
  cause: dns error
  cause: error resolving DNS
  cause: failed to lookup address information: nodename nor servname provided, or not known
```

### 실행 6 (종료 코드 1)

```sh
source .venv/bin/activate
python gdelt_gkg.py --backfill 2
```

```text
/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
GKG run: bytes=0 MiB=0.00 elapsed=0.03s
Traceback (most recent call last):
  File "/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/connection.py", line 204, in _new_conn
    sock = connection.create_connection(
  File "/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/util/connection.py", line 60, in create_connection
    for res in socket.getaddrinfo(host, port, family, socket.SOCK_STREAM):
  File "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/lib/python3.9/socket.py", line 953, in getaddrinfo
    for res in _socket.getaddrinfo(host, port, family, type, proto, flags):
socket.gaierror: [Errno 8] nodename nor servname provided, or not known

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/connectionpool.py", line 787, in urlopen
    response = self._make_request(
  File "/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/connectionpool.py", line 488, in _make_request
    raise new_e
  File "/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/connectionpool.py", line 464, in _make_request
    self._validate_conn(conn)
  File "/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/connectionpool.py", line 1093, in _validate_conn
    conn.connect()
  File "/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/connection.py", line 759, in connect
    self.sock = sock = self._new_conn()
  File "/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/connection.py", line 211, in _new_conn
    raise NameResolutionError(self.host, self, e) from e
urllib3.exceptions.NameResolutionError: HTTPSConnection(host='data.gdeltproject.org', port=443): Failed to resolve 'data.gdeltproject.org' ([Errno 8] nodename nor servname provided, or not known)

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/Users/dex/war-alert/.venv/lib/python3.9/site-packages/requests/adapters.py", line 644, in send
    resp = conn.urlopen(
  File "/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/connectionpool.py", line 841, in urlopen
    retries = retries.increment(
  File "/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/util/retry.py", line 535, in increment
    raise MaxRetryError(_pool, url, reason) from reason  # type: ignore[arg-type]
urllib3.exceptions.MaxRetryError: HTTPSConnectionPool(host='data.gdeltproject.org', port=443): Max retries exceeded with url: /gdeltv2/20261107000000.gkg.csv.zip (Caused by NameResolutionError("HTTPSConnection(host='data.gdeltproject.org', port=443): Failed to resolve 'data.gdeltproject.org' ([Errno 8] nodename nor servname provided, or not known)"))

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/dex/war-alert/gdelt_gkg.py", line 84, in download_day
    with session.get(url, stream=True, timeout=(15, 90),
  File "/Users/dex/war-alert/.venv/lib/python3.9/site-packages/requests/sessions.py", line 602, in get
    return self.request("GET", url, **kwargs)
  File "/Users/dex/war-alert/.venv/lib/python3.9/site-packages/requests/sessions.py", line 589, in request
    resp = self.send(prep, **send_kwargs)
  File "/Users/dex/war-alert/.venv/lib/python3.9/site-packages/requests/sessions.py", line 703, in send
    r = adapter.send(request, **kwargs)
  File "/Users/dex/war-alert/.venv/lib/python3.9/site-packages/requests/adapters.py", line 677, in send
    raise ConnectionError(e, request=request)
requests.exceptions.ConnectionError: HTTPSConnectionPool(host='data.gdeltproject.org', port=443): Max retries exceeded with url: /gdeltv2/20261107000000.gkg.csv.zip (Caused by NameResolutionError("HTTPSConnection(host='data.gdeltproject.org', port=443): Failed to resolve 'data.gdeltproject.org' ([Errno 8] nodename nor servname provided, or not known)"))

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/Users/dex/war-alert/gdelt_gkg.py", line 202, in <module>
    main()
  File "/Users/dex/war-alert/gdelt_gkg.py", line 191, in main
    days, arts = fetch(backfill=args.backfill, metrics=metrics)
  File "/Users/dex/war-alert/gdelt_gkg.py", line 168, in fetch
    row, new_arts = download_day(day, session, metrics)
  File "/Users/dex/war-alert/gdelt_gkg.py", line 101, in download_day
    raise RuntimeError(f"GKG 수집 실패 ({url}): {exc}") from exc
RuntimeError: GKG 수집 실패 (https://data.gdeltproject.org/gdeltv2/20261107000000.gkg.csv.zip): HTTPSConnectionPool(host='data.gdeltproject.org', port=443): Max retries exceeded with url: /gdeltv2/20261107000000.gkg.csv.zip (Caused by NameResolutionError("HTTPSConnection(host='data.gdeltproject.org', port=443): Failed to resolve 'data.gdeltproject.org' ([Errno 8] nodename nor servname provided, or not known)"))
```

### 실행 7 (종료 코드 1)

```sh
source .venv/bin/activate
python -m pytest tests/
```

```text
/Users/dex/war-alert/.venv/bin/python: No module named pytest
```

### 실행 8 (종료 코드 0)

```sh
source .venv/bin/activate
python -m unittest discover -s tests -v
```

```text
/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
test_articles_can_recover_after_checkpoint_without_json (test_gdelt_gkg.CacheTests) ... ok
test_backfill_over_three_is_rejected (test_gdelt_gkg.CacheTests) ... ok
test_cached_window_needs_no_network_and_preserves_articles (test_gdelt_gkg.CacheTests) ... ok
test_cli_backfills_two_synthetic_days_and_writes_news_without_doc (test_gdelt_gkg.CacheTests) ... ok
test_doc_history_merge_overwrite_and_newest_articles (test_gdelt_gkg.CacheTests) ... ok
test_failed_partial_day_is_not_saved (test_gdelt_gkg.CacheTests) ... ok
test_incremental_cap_and_cached_dates_are_not_downloaded (test_gdelt_gkg.CacheTests) ... ok
test_old_backfill_does_not_replace_saved_latest_articles (test_gdelt_gkg.CacheTests) ... ok
test_successful_day_persists_when_next_day_fails (test_gdelt_gkg.CacheTests) ... ok
test_doc_failures_empty_and_malformed_use_gkg (test_gdelt_gkg.FallbackTests) ... ok
test_evaluate_matches_original_on_existing_series_and_alert_cases (test_gdelt_gkg.FallbackTests) ... ok
test_exactly_three_days_late_remains_doc (test_gdelt_gkg.FallbackTests) ... ok
test_failed_fetch_leaves_previous_news_json_untouched (test_gdelt_gkg.FallbackTests) ... ok
test_gkg_failure_propagates (test_gdelt_gkg.FallbackTests) ... ok
test_optional_doc_metadata_failure_preserves_existing_behavior (test_gdelt_gkg.FallbackTests) ... ok
test_run_preserves_json_contract_and_adds_source (test_gdelt_gkg.FallbackTests) ... ok
test_stale_full_day_ignores_new_partial_day (test_gdelt_gkg.FallbackTests) ... ok
test_all_six_keywords_case_and_separators (test_gdelt_gkg.ParsingTests) ... ok
test_articles_are_bounded_and_http_only (test_gdelt_gkg.ParsingTests) ... ok
test_bad_rows_and_tone_are_explicit_errors (test_gdelt_gkg.ParsingTests) ... ok
test_long_url_titles_keep_twelve_distinct_articles (test_gdelt_gkg.ParsingTests) ... ok
test_matching_uses_only_document_and_enhanced_themes (test_gdelt_gkg.ParsingTests) ... ok
test_missing_tone_and_no_matches (test_gdelt_gkg.ParsingTests) ... ok
test_network_http_and_zip_errors_become_runtime_errors (test_gdelt_gkg.ParsingTests) ... ok
test_records_are_counted_even_if_url_is_duplicate (test_gdelt_gkg.ParsingTests) ... ok
test_streamed_day_totals_tone_and_download_bytes (test_gdelt_gkg.ParsingTests) ... ok
test_urls_cover_exactly_one_utc_day (test_gdelt_gkg.ParsingTests) ... ok

----------------------------------------------------------------------
Ran 27 tests in 0.204s

OK
```

### 실행 9 (종료 코드 0)

```sh
source .venv/bin/activate
python -c "import news_monitor"
```

```text
/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
```

### 실행 10 (종료 코드 0)

```sh
source .venv/bin/activate
python - <<'PY'
import ast
import copy
import json
from pathlib import Path
import subprocess
import news_monitor

original = ast.parse(subprocess.check_output(['git', 'show', 'HEAD:news_monitor.py'], text=True))
current = ast.parse(Path('news_monitor.py').read_text())
for name in ('evaluate', 'robust_z'):
    old = next(n for n in original.body if isinstance(n, ast.FunctionDef) and n.name == name)
    new = next(n for n in current.body if isinstance(n, ast.FunctionDef) and n.name == name)
    assert ast.dump(old) == ast.dump(new), name
    print(name + ': AST unchanged')
payload = json.loads(Path('data/news.json').read_text())
result = news_monitor.evaluate(copy.deepcopy(payload['series']))
assert result[3] == payload['latest']
print('existing latest: identical')
print(json.dumps(result[3], ensure_ascii=False, sort_keys=True))
protected = ['.github/workflows/hotel.yml', 'index.html', 'mail_report.py', 'daily_report.py', 'data/news.json']
for name in protected:
    assert Path(name).read_bytes() == subprocess.check_output(['git', 'show', 'HEAD:' + name]), name
    print(name + ': unchanged')
assert not Path('data/news_gkg_daily.csv').exists()
print('real backfill: no cache created after DNS failure')
PY
```

```text
/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
evaluate: AST unchanged
robust_z: AST unchanged
existing latest: identical
{"base_n": 28, "count": 244, "date": "2026-10-24", "median": 15.299, "ratio": 2.05, "share": 31.434, "tone": -0.6895, "z": 1.92}
.github/workflows/hotel.yml: unchanged
index.html: unchanged
mail_report.py: unchanged
daily_report.py: unchanged
data/news.json: unchanged
real backfill: no cache created after DNS failure
```

### 실행 11 (종료 코드 0)

```sh
source .venv/bin/activate
python -m unittest discover -s tests -v
```

```text
/Users/dex/war-alert/.venv/lib/python3.9/site-packages/urllib3/__init__.py:35: NotOpenSSLWarning: urllib3 v2 only supports OpenSSL 1.1.1+, currently the 'ssl' module is compiled with 'LibreSSL 2.8.3'. See: https://github.com/urllib3/urllib3/issues/3020
  warnings.warn(
test_articles_can_recover_after_checkpoint_without_json (test_gdelt_gkg.CacheTests) ... ok
test_backfill_over_three_is_rejected (test_gdelt_gkg.CacheTests) ... ok
test_cached_window_needs_no_network_and_preserves_articles (test_gdelt_gkg.CacheTests) ... ok
test_cli_backfills_two_synthetic_days_and_writes_news_without_doc (test_gdelt_gkg.CacheTests) ... ok
test_doc_history_merge_overwrite_and_newest_articles (test_gdelt_gkg.CacheTests) ... ok
test_failed_partial_day_is_not_saved (test_gdelt_gkg.CacheTests) ... ok
test_incremental_cap_and_cached_dates_are_not_downloaded (test_gdelt_gkg.CacheTests) ... ok
test_old_backfill_does_not_replace_saved_latest_articles (test_gdelt_gkg.CacheTests) ... ok
test_successful_day_persists_when_next_day_fails (test_gdelt_gkg.CacheTests) ... ok
test_doc_failures_empty_and_malformed_use_gkg (test_gdelt_gkg.FallbackTests) ... ok
test_evaluate_matches_original_on_existing_series_and_alert_cases (test_gdelt_gkg.FallbackTests) ... ok
test_exactly_three_days_late_remains_doc (test_gdelt_gkg.FallbackTests) ... ok
test_failed_fetch_leaves_previous_news_json_untouched (test_gdelt_gkg.FallbackTests) ... ok
test_gkg_failure_propagates (test_gdelt_gkg.FallbackTests) ... ok
test_optional_doc_metadata_failure_preserves_existing_behavior (test_gdelt_gkg.FallbackTests) ... ok
test_root_source_tracks_newest_series_row_when_latest_is_partial (test_gdelt_gkg.FallbackTests) ... ok
test_run_preserves_json_contract_and_adds_source (test_gdelt_gkg.FallbackTests) ... ok
test_stale_full_day_ignores_new_partial_day (test_gdelt_gkg.FallbackTests) ... ok
test_all_six_keywords_case_and_separators (test_gdelt_gkg.ParsingTests) ... ok
test_articles_are_bounded_and_http_only (test_gdelt_gkg.ParsingTests) ... ok
test_bad_rows_and_tone_are_explicit_errors (test_gdelt_gkg.ParsingTests) ... ok
test_long_url_titles_keep_twelve_distinct_articles (test_gdelt_gkg.ParsingTests) ... ok
test_matching_uses_only_document_and_enhanced_themes (test_gdelt_gkg.ParsingTests) ... ok
test_missing_tone_and_no_matches (test_gdelt_gkg.ParsingTests) ... ok
test_network_http_and_zip_errors_become_runtime_errors (test_gdelt_gkg.ParsingTests) ... ok
test_records_are_counted_even_if_url_is_duplicate (test_gdelt_gkg.ParsingTests) ... ok
test_streamed_day_totals_tone_and_download_bytes (test_gdelt_gkg.ParsingTests) ... ok
test_urls_cover_exactly_one_utc_day (test_gdelt_gkg.ParsingTests) ... ok

----------------------------------------------------------------------
Ran 28 tests in 0.204s

OK
```

### 실행 12 (종료 코드 0)

```sh
git diff --check
git status --short --untracked-files=all
source .venv/bin/activate
python - <<'PY'
from pathlib import Path
files = ['news_monitor.py', 'gdelt_gkg.py', 'tests/test_gdelt_gkg.py', 'docs/handoff/gdelt-gkg-fallback/RESULT.md']
for name in files:
    data = Path(name).read_text()
    assert data.endswith('\n'), name
    assert all(line == line.rstrip() for line in data.splitlines()), name
print('all changed files: trailing whitespace/newline check passed')
PY
```

```text
 M news_monitor.py
?? docs/handoff/gdelt-gkg-fallback/PLAN.md
?? docs/handoff/gdelt-gkg-fallback/RESULT.md
?? gdelt_gkg.py
?? tests/test_gdelt_gkg.py
all changed files: trailing whitespace/newline check passed
```

PLAN.md는 작업 시작 전부터 있던 untracked 파일이다. 상태 출력의 PLAN.md는 이번에 생성하거나 수정한 파일을 뜻하지 않는다.



