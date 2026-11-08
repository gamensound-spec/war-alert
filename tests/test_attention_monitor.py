"""외부 호출 없이 관심도 수집·단위·실패 격리·메일 연결을 검증한다."""
import ast
import datetime as dt
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

import attention_monitor as attention
import mail_report
from news_monitor import robust_z

TODAY = dt.date(2026, 11, 8)


def pageviews(values):
    start = TODAY - dt.timedelta(days=len(values))
    return {"items": [{"timestamp": f"{start + dt.timedelta(days=i):%Y%m%d}00", "views": value}
                      for i, value in enumerate(values)]}


def days(values=None):
    values = values if values is not None else [90, 100, 110, 120] * 14 + [100, 100, 100, 300]
    return [{"date": row["date"], "total": row["views"], "documents": {"North_Korea": row["views"]}}
            for row in attention.parse_pageviews(pageviews(values), TODAY)]


def rss(titles, news=None):
    from html import escape
    news = news or [[] for _ in titles]
    return ('<rss xmlns:ht="https://trends.google.com/trending/rss"><channel>'
            + ''.join('<item><title>' + escape(title) + '</title>'
                      + ''.join('<ht:news_item><ht:news_item_title>' + escape(n)
                                + '</ht:news_item_title></ht:news_item>' for n in group) + '</item>'
                      for title, group in zip(titles, news)) + '</channel></rss>')


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(attention, "JSON_FILE", tmp_path / "attention.json")
    monkeypatch.setattr(attention, "CSV_FILE", tmp_path / "attention_trends.csv")
    return tmp_path


def test_pageviews_excludes_invalid_and_unconfirmed_preserving_dates():
    payload = pageviews([10, None, False, -1, "20", 0, 30])
    payload["items"] += [{"timestamp": f"{TODAY:%Y%m%d}00", "views": 999},
                         {"timestamp": "bad", "views": 99}, None]
    actual = attention.parse_pageviews(payload, TODAY)
    assert [(d["date"], d["views"]) for d in actual] == [
        ((TODAY - dt.timedelta(days=n)).isoformat(), v) for n, v in [(7, 10), (2, 0), (1, 30)]]


@pytest.mark.parametrize("payload", [None, [], {}, {"items": None}, {"items": []}, pageviews([None])])
def test_invalid_pageviews(payload):
    with pytest.raises(ValueError, match="Wikimedia"):
        attention.parse_pageviews(payload, TODAY)


def test_pageviews_sorted_deduplicated_last_60_calendar_days():
    payload = pageviews(list(range(70)))
    payload["items"].reverse()
    payload["items"].append({**payload["items"][0], "views": 99})
    actual = attention.parse_pageviews(payload, TODAY)
    assert len(actual) == 60
    assert actual[0]["views"] == 10 and actual[-1]["views"] == 99


def test_fetch_wiki_404_skip_and_sum_same_dates(monkeypatch):
    missing = Mock(status_code=404)
    good = Mock(status_code=200)
    good.json.return_value = pageviews([10, 20, 30])
    gap = Mock(status_code=200)
    gap.json.return_value = pageviews([40, None, 60])
    get = Mock(side_effect=[missing, good, gap, good])
    monkeypatch.setattr(attention.requests, "get", get)
    series = attention.fetch_wiki(TODAY)
    assert [day["total"] for day in series] == [60, 120]
    assert set(series[-1]["documents"]) == set(attention.ARTICLES[1:])
    assert get.call_count == 4
    first = get.call_args_list[0]
    assert first.kwargs["headers"] == {"User-Agent": "war-alert/1.0"}
    assert first.args[0].endswith('/daily/20260909/20261107')


def test_fetch_wiki_all_404_fails(monkeypatch):
    monkeypatch.setattr(attention.requests, "get", Mock(return_value=Mock(status_code=404)))
    with pytest.raises(ValueError, match="4개 모두"):
        attention.fetch_wiki(TODAY)


def test_wiki_no_common_dates_is_failure(monkeypatch):
    responses = [Mock(status_code=200) for _ in range(4)]
    for i, response in enumerate(responses):
        response.json.return_value = {"items": [pageviews([10] * 4)["items"][i]]}
    monkeypatch.setattr(attention.requests, "get", Mock(side_effect=responses))
    with pytest.raises(ValueError, match="공통 확정일"):
        attention.fetch_wiki(TODAY)


def test_daily_z_matches_prior_28_daily_counts_and_excludes_latest():
    series = days()
    result = attention.evaluate_wiki(series)
    expected = robust_z(300, [d["total"] for d in series[-29:-1]])
    assert result["latest"]["base_n"] == 28
    assert result["latest"]["median"] == expected[0]
    assert result["latest"]["z"] == pytest.approx(expected[1])
    assert result["status"] == "watch"


@pytest.mark.parametrize("values", [[10] * 60, [10, 20] * 6 + [100], [10]])
def test_wiki_mad_zero_or_insufficient_baseline_muted(values):
    result = attention.evaluate_wiki(days(values))
    assert result["status"] == "muted" and result["latest"]["z"] is None


def test_baseline_is_calendar_days_and_same_day_is_excluded():
    rows = [{"date": (TODAY - dt.timedelta(days=i)).isoformat(), "keyword_hits": i} for i in [0, 1, 28, 29]]
    assert attention.baseline(rows, TODAY.isoformat(), "keyword_hits") == [1, 28]
    assert attention.score(100, [10, 20] * 7)["status"] == "watch"
    assert attention.score(0, [10, 20] * 7)["status"] == "normal"


@pytest.mark.parametrize("target,status", [(1.9999, "normal"), (2.0, "watch")])
def test_z_threshold_without_rounding(target, status):
    base = [0, 10] * 7
    result = attention.score(5 + target * 5 * 1.4826, base)
    assert result["z"] == pytest.approx(target) and result["status"] == status


def test_rss_counts_matching_titles_excludes_martial_law_and_limits_titles():
    parsed = attention.parse_trends(rss(["계엄", "스포츠", "북한 미사일", "전쟁", "대피", "핵", "징집", "참전"],
                                       [[], ["북한 <속보>", "미사일 발사"], ["북한 뉴스"], [], [], [], [], []]))
    assert parsed["hits"] == 9 and parsed["items"] == 8
    assert len(parsed["titles"]) == 5
    assert "북한 <속보>" in parsed["titles"] and "계엄" not in parsed["titles"]


@pytest.mark.parametrize("text", ["<html/>", "<rss/>", "not xml"])
def test_invalid_rss_is_failure(text):
    with pytest.raises(ValueError, match="Google Trends"):
        attention.parse_trends(text)


def test_empty_valid_rss_is_zero_and_fetch_uses_official_url(monkeypatch):
    response = Mock()
    response.text = rss([])
    get = Mock(return_value=response)
    monkeypatch.setattr(attention.requests, "get", get)
    assert attention.fetch_trends() == {"hits": 0, "items": 0, "titles": []}
    assert get.call_args.args == (attention.TRENDS_API,)
    assert get.call_args.kwargs["timeout"] == 30


def log_rows(values):
    return [{"date": row["date"], "keyword_hits": row["views"], "items": 20}
            for row in attention.parse_pageviews(pageviews(values), TODAY)]


@pytest.mark.parametrize("hits,status", [(0, "normal"), (2, "normal"), (3, "watch")])
def test_trends_zero_mad_fallback_after_minimum_baseline(hits, status):
    result = attention.evaluate_trends({"hits": hits, "items": 20, "titles": []}, log_rows([0] * 14), TODAY.isoformat())
    assert result["status"] == status and result["z"] is None
    assert result["note"] == f"평소 0건 대비 {hits}건 · MAD 0"


def test_trends_short_sample_never_watch_even_with_many_hits():
    result = attention.evaluate_trends({"hits": 20}, log_rows([0] * 13), TODAY.isoformat())
    assert result["status"] == "muted" and result["samples"] == 13


def test_trends_daily_z_excludes_same_day_and_uses_28_days():
    rows = log_rows([50] * 5 + [0, 1, 2, 3] * 7)
    rows.append({"date": TODAY.isoformat(), "keyword_hits": 999, "items": 999})
    item = attention.evaluate_trends({"hits": 10}, rows, TODAY.isoformat())
    assert item["base_n"] == 28 and item["z"] == pytest.approx(robust_z(10, [0, 1, 2, 3] * 7)[1])


def test_run_twice_same_day_overwrites_csv_and_never_alerts(storage):
    for hits in [1, 3]:
        alerts, lines = attention.run(lambda: days(), lambda: {"hits": hits, "items": 10, "titles": []}, TODAY)
        assert alerts == [] and any(attention.NOTICE in line for line in lines)
    rows = attention.read_log(attention.CSV_FILE, ["keyword_hits", "items"])
    assert rows == [{"date": TODAY.isoformat(), "keyword_hits": 3, "items": 10}]
    data = json.loads(Path(attention.JSON_FILE).read_text())
    assert data["alerts"] == [] and data["status"] == "watch"
    assert data["trends"]["samples"] == 1 and data["trends"]["base_n"] == 0
    assert data["generated_at"].endswith("+09:00")
    assert data["source"] == ["wikimedia-pageviews", "google-trends-kr-rss"]


@pytest.mark.parametrize("failed", ["wiki", "trends"])
def test_source_failure_keeps_other_source(storage, failed):
    failure = Mock(side_effect=requests.ConnectionError("synthetic DNS failure"))
    attention.run(failure if failed == "wiki" else lambda: days([10] * 30),
                  failure if failed == "trends" else lambda: {"hits": 0, "items": 1, "titles": []}, TODAY)
    data = json.loads(Path(attention.JSON_FILE).read_text())
    assert data[failed]["error"] == data["error"][failed] == "synthetic DNS failure"
    assert data[failed]["status"] == data["status"] == "muted"
    assert "error" not in data["trends" if failed == "wiki" else "wiki"]


def test_partial_failure_does_not_suppress_healthy_watch(storage):
    attention.run(lambda: days(), Mock(side_effect=ValueError("synthetic RSS failure")), TODAY)
    data = json.loads(Path(attention.JSON_FILE).read_text())
    assert data["status"] == "watch" and data["wiki"]["status"] == "watch"
    assert data["trends"]["status"] == "muted" and data["alerts"] == []


def test_bad_existing_csv_is_preserved_and_only_trends_fails(storage):
    Path(attention.CSV_FILE).write_bytes(b'date,wrong\n2026-11-07,1\n')
    attention.run(lambda: days(), lambda: {"hits": 0, "items": 10, "titles": []}, TODAY)
    data = json.loads(Path(attention.JSON_FILE).read_text())
    assert data["trends"]["error"] == "스냅샷 CSV 열 불일치"
    assert Path(attention.CSV_FILE).read_bytes() == b'date,wrong\n2026-11-07,1\n'


def test_both_fail_preserves_json_and_csv(storage):
    Path(attention.JSON_FILE).write_bytes(b'{"previous":true}\n')
    Path(attention.CSV_FILE).write_bytes(b'date,keyword_hits,items\n2026-11-01,0,20\n')
    before = Path(attention.CSV_FILE).read_bytes()
    failure = Mock(side_effect=requests.ConnectionError("synthetic DNS failure"))
    with pytest.raises(RuntimeError, match="모두 수집 실패"):
        attention.run(failure, failure, TODAY)
    assert Path(attention.JSON_FILE).read_bytes() == b'{"previous":true}\n'
    assert Path(attention.CSV_FILE).read_bytes() == before


@pytest.mark.parametrize("failure", ["serialize", "replace"])
def test_atomic_json_failure_preserves_bytes_and_cleans_temp(storage, monkeypatch, failure):
    path = Path(attention.JSON_FILE)
    path.write_bytes(b'previous\n')
    if failure == "replace":
        monkeypatch.setattr(attention.os, "replace", Mock(side_effect=OSError("synthetic write failure")))
    with pytest.raises((ValueError, OSError)):
        attention.write_json({"value": float("nan") if failure == "serialize" else 1})
    assert path.read_bytes() == b'previous\n' and list(storage.iterdir()) == [path]


def test_atomic_csv_failure_preserves_previous(storage, monkeypatch):
    path = Path(attention.CSV_FILE)
    path.write_bytes(b'previous\n')
    monkeypatch.setattr(attention.os, "replace", Mock(side_effect=OSError("synthetic write failure")))
    with pytest.raises(OSError):
        attention.write_log(path, [], ["keyword_hits", "items"])
    assert path.read_bytes() == b'previous\n' and list(storage.iterdir()) == [path]


def test_mail_missing_files_build_and_escape(storage, monkeypatch):
    monkeypatch.chdir(storage)
    html = mail_report.build("2026-11-08", [], [])
    assert "05 대중 관심도" in html and "관심도 데이터를 기다리는 중" in html
    assert "06 항공 교통" in html and "항공 데이터를 기다리는 중" in html
    malicious = '<img src=x onerror="alert(1)">'
    data = {"status": "watch", "alerts": ["must be ignored"], "wiki": {"error": malicious},
            "trends": {"hits": 3, "status": "watch", "titles": [malicious], "note": "평소 0건 대비 3건"}}
    Path("data").mkdir()
    Path("data/attention.json").write_text(json.dumps(data))
    html = mail_report.build("2026-11-08", [], [])
    assert "특이 동향 없음" in html and "must be ignored" not in html
    assert "평소 0건 대비 3건" in html and malicious not in html and "&lt;img" in html


def test_mail_null_reference_values():
    data = {"wiki": {"latest": {"total": None, "z": None, "documents": None}},
            "trends": {"hits": None, "titles": None}}
    assert "데이터 없음" in mail_report.attention_html(data)


def test_daily_report_wiring_without_importing_or_running():
    path = Path(__file__).resolve().parents[1] / "daily_report.py"
    tree = ast.parse(path.read_text())
    run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run")
    parts = next(node.value for node in run.body if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "parts" for t in node.targets))
    assert [(node.elts[0].value, ast.unparse(node.elts[1])) for node in parts.elts][-2:] == [
        ("대중 관심도", "attention_monitor.run"), ("항공 교통", "air_monitor.run")]
