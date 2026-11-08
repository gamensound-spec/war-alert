"""합성 RSS·일별 기준선·실패 격리·HTML 안전성. 네트워크·발송 없이 검증한다."""
import ast
import datetime as dt
import json
import shutil
import subprocess
from email.utils import format_datetime
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

import mail_report
import usfk_monitor as usfk
from news_monitor import robust_z

NOW = dt.datetime(2026, 11, 9, 8, 47, tzinfo=usfk.KST)
DATE = NOW.date().isoformat()


def rss(items):
    return '<rss><channel>' + ''.join(
        '<item>' + ''.join(f'<{key}>{escape(str(value))}</{key}>' for key, value in item.items()) + '</item>'
        for item in items) + '</channel></rss>'


def article(title="USFK report", hours=1, source="Outlet A", link="https://example.test/news"):
    return {"title": title, "pubDate": format_datetime(NOW - dt.timedelta(hours=hours)),
            "source": source, "link": link}


def articles(n=3, sources=("Outlet A", "Outlet B")):
    return usfk.parse_rss(rss([article(f"USFK report {i}", source=sources[i % len(sources)]) for i in range(n)]))


def history(values, group="evac"):
    start = NOW.date() - dt.timedelta(days=len(values))
    return [{"date": (start + dt.timedelta(days=i)).isoformat(), "group": group,
             "hits_24h": value, "hits_7d": 1000, "training_7d": 900} for i, value in enumerate(values)]


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(usfk, "JSON_FILE", tmp_path / "usfk.json")
    monkeypatch.setattr(usfk, "CSV_FILE", tmp_path / "usfk_log.csv")
    monkeypatch.setattr(usfk.time, "sleep", Mock())
    return tmp_path


def output():
    return json.loads(Path(usfk.JSON_FILE).read_text())


def test_rss_parses_fields_preserving_title_for_render_escape():
    parsed = usfk.parse_rss(rss([article('<script>alert(1)</script>', source='A & B')]))
    assert parsed == [{"title": '<script>alert(1)</script>', "source": 'A & B',
                       "date": (NOW - dt.timedelta(hours=1)).isoformat(),
                       "link": "https://example.test/news", "training": False}]


@pytest.mark.parametrize("text", ["not XML", "<html/>", "<rss/>"])
def test_malformed_feed_fails(text):
    with pytest.raises(ValueError, match="Google News RSS"):
        usfk.parse_rss(text)


def test_empty_valid_feed_and_invalid_items():
    assert usfk.parse_rss(rss([])) == []
    assert usfk.parse_rss(rss([article(""), {"title": "no date"}, {**article(), "pubDate": "bad"}])) == []
    no_timezone = {**article(), "pubDate": "Sun, 08 Nov 2026 23:00:00"}
    assert usfk.parse_rss(rss([no_timezone]))[0]["date"] == "2026-11-09T08:00:00+09:00"


@pytest.mark.parametrize("title", ["NEO EXERCISE", "evacuation drills", "USFK Training", "주한미군 소개 훈련"])
def test_training_classification_excludes_stress_and_sources(title):
    item, headlines = usfk.snapshot(usfk.parse_rss(rss([article(title)])), NOW)
    assert item == {"hits_24h": 0, "hits_7d": 0, "training_7d": 1, "sources_24h": 0}
    assert headlines == []


def test_deduplicate_lowercase_first_60_characters_and_keep_newest():
    prefix = "A" * 60
    items = [article(prefix + " first", hours=48), article(prefix.lower() + " latest"),
             article("Mixed Case Title"), article("mixed case title", hours=2)]
    snapshot, headlines = usfk.snapshot(usfk.parse_rss(rss(items)), NOW)
    assert snapshot["hits_24h"] == snapshot["hits_7d"] == 2
    assert headlines[0]["title"] == prefix.lower() + " latest"


def test_time_windows_ignore_old_future_and_training():
    items = [article(str(hours), hours=hours) for hours in [-1, 0, 24, 24.01, 168, 168.01]]
    items += [article("NEO training", hours=20), article("drill", hours=100)]
    item, headlines = usfk.snapshot(usfk.parse_rss(rss(items)), NOW)
    assert item == {"hits_24h": 2, "hits_7d": 4, "training_7d": 2, "sources_24h": 1}
    assert len(headlines) == 4


@pytest.mark.parametrize("link", ["javascript:alert(1)", "data:text/html,hi", "//example.test", "file:///tmp/x",
                                 "https://", "https://[bad", "https://example.test/\nfoo", None])
def test_link_filter_rejects_non_http_and_invalid_links(link):
    assert usfk.safe_link(link) == ""


@pytest.mark.parametrize("link", ["https://example.test/a?x=1&y=2", "http://example.test/", "HTTPS://example.test/"])
def test_link_filter_accepts_http_https(link):
    assert usfk.safe_link(link) == link


def test_fetch_both_evac_languages_uses_rss_only_and_group_dedup(monkeypatch):
    response = Mock()
    response.text = rss([article("USFK reviews noncombatant evacuation plan")])
    get = Mock(return_value=response)
    monkeypatch.setattr(usfk.requests, "get", get)
    item, _ = usfk.snapshot(usfk.fetch("evac"), NOW)
    assert item["hits_24h"] == 1 and get.call_count == 2
    assert [call.kwargs["params"]["hl"] for call in get.call_args_list] == ["en-US", "ko"]
    for call in get.call_args_list:
        assert call.args == ("https://news.google.com/rss/search",)
        assert call.kwargs["params"]["q"].endswith("when:7d")
        assert call.kwargs["headers"] == {"User-Agent": "war-alert/1.0"}
        assert call.kwargs["timeout"] == 30


def test_evac_query_failure_does_not_count_incomplete_group(monkeypatch):
    good = Mock(text=rss([article()]))
    monkeypatch.setattr(usfk.requests, "get", Mock(side_effect=[good, requests.ConnectionError("synthetic DNS failure")]))
    with pytest.raises(requests.ConnectionError):
        usfk.fetch("evac")


@pytest.mark.parametrize("group", ["readiness", "families"])
def test_z_compares_same_group_daily_units_and_prior_28_days(group):
    values = [999] * 5 + [0, 1, 2, 3] * 7
    rows = history(values, group) + history([1000] * 28, "evac")
    rows += [{"date": DATE, "group": group, "hits_24h": 9999}]
    item, _ = usfk.snapshot(articles(10), NOW)
    result = usfk.evaluate(group, item, rows, DATE)
    median, z = robust_z(10, values[-28:])
    assert result["base_n"] == 28 and result["median"] == median
    assert result["z"] == pytest.approx(z) and result["status"] == "watch"


@pytest.mark.parametrize("target,status", [(1.9999, "normal"), (2.0, "watch")])
def test_z_watch_threshold_without_rounding(target, status):
    item = {"hits_24h": 5 + target * 5 * 1.4826, "sources_24h": 2}
    result = usfk.evaluate("readiness", item, history([0, 10] * 7, "readiness"), DATE)
    assert result["z"] == pytest.approx(target) and result["status"] == status


@pytest.mark.parametrize("group", list(usfk.GROUPS))
def test_short_baseline_muted_even_with_high_counts(group):
    item, _ = usfk.snapshot(articles(30), NOW)
    result = usfk.evaluate(group, item, history([0] * 13, group), DATE)
    assert result["base_n"] == 13 and result["z"] is None and result["status"] == "muted"


@pytest.mark.parametrize("hits,sources,status", [(2, 2, "normal"), (3, 1, "normal"), (3, 2, "watch"), (0, 0, "normal")])
@pytest.mark.parametrize("base", [[0] * 14, [0, 1] * 7])
def test_evac_count_and_distinct_sources_gate_with_or_without_mad(base, hits, sources, status):
    result = usfk.evaluate("evac", {"hits_24h": hits, "sources_24h": sources}, history(base), DATE)
    assert result["status"] == status
    if not any(base):
        assert result["z"] is None and "MAD 0" in result["note"]


@pytest.mark.parametrize("group", ["readiness", "families"])
def test_other_groups_zero_mad_show_counts_without_invented_z(group):
    item, _ = usfk.snapshot(articles(10), NOW)
    result = usfk.evaluate(group, item, history([0] * 14, group), DATE)
    assert result["z"] is None and result["status"] == "muted" and "10건 · MAD 0" in result["note"]


def test_sources_are_counted_only_in_24h_and_ignore_empty_and_case_duplicates():
    items = [article("one", source="Outlet A"), article("two", source="outlet a"), article("empty", source=""),
             article("old", hours=25, source="Outlet B"), article("NEO drill", source="Outlet C")]
    snapshot, _ = usfk.snapshot(usfk.parse_rss(rss(items)), NOW)
    assert snapshot["sources_24h"] == 1


def test_run_same_day_upserts_all_groups_never_alerts_and_waits_between_groups(storage):
    for n in [1, 3]:
        alerts, lines = usfk.run(lambda group: articles(n), NOW)
        assert alerts == [] and all(line.endswith(usfk.NOTICE) for line in lines)
    rows = usfk.read_log()
    assert len(rows) == 3 and all(row["hits_24h"] == 3 for row in rows)
    assert {row["group"] for row in rows} == set(usfk.GROUPS)
    data = output()
    assert data["alerts"] == [] and data["status"] == "muted" and data["watch"] == []
    assert data["generated_at"].endswith("+09:00") and data["source"] == "google-news-rss"
    assert data["config"]["min_base"] == 14 and data["config"]["z_watch"] == 2
    assert [call.args for call in usfk.time.sleep.call_args_list] == [(2,), (2,)] * 2


def test_run_watch_and_global_headlines_dedup_sorted_capped(storage):
    usfk.write_log(sum((history([0, 1, 2, 3] * 7, group) for group in usfk.GROUPS), []))
    alerts, _ = usfk.run(lambda group: articles(12), NOW)
    data = output()
    assert alerts == data["alerts"] == [] and data["status"] == "watch"
    assert len(data["watch"]) == 3 and len(data["headlines"]) == 8
    assert all(set(item) == {"title", "source", "date", "link"} for item in data["headlines"])


@pytest.mark.parametrize("failed", list(usfk.GROUPS))
def test_one_group_failure_keeps_other_groups_watch_and_skips_failed_log(storage, failed):
    usfk.write_log(sum((history([0, 1] * 7, group) for group in usfk.GROUPS), []))

    def fetcher(group):
        if group == failed:
            raise requests.ConnectionError("synthetic DNS failure")
        return articles(10)

    usfk.run(fetcher, NOW)
    data = output()
    assert data["status"] == "watch" and list(data["error"]) == [failed]
    assert data["groups"][failed] == {"status": "muted", "error": "synthetic DNS failure"}
    assert all(data["groups"][key]["status"] == "watch" for key in usfk.GROUPS if key != failed)
    assert len([row for row in usfk.read_log() if row["date"] == DATE]) == 2


def test_all_fail_saves_muted_error_preserves_previous_values_and_csv(storage):
    usfk.write_log(history([0] * 14))
    usfk.run(lambda group: articles(), NOW)
    before, csv_before = output(), Path(usfk.CSV_FILE).read_bytes()
    failure = Mock(side_effect=requests.ConnectionError("synthetic DNS failure"))
    assert usfk.run(failure, NOW + dt.timedelta(days=1))[0] == []
    after = output()
    assert after["status"] == "muted" and after["alerts"] == after["watch"] == []
    assert after["headlines"] == before["headlines"] and set(after["error"]) == set(usfk.GROUPS)
    for group in usfk.GROUPS:
        assert after["groups"][group]["hits_24h"] == before["groups"][group]["hits_24h"]
        assert after["groups"][group]["date"] == DATE and after["groups"][group]["status"] == "muted"
    assert Path(usfk.CSV_FILE).read_bytes() == csv_before


def test_first_run_all_fail_is_empty_muted_not_runtime_error(storage):
    assert usfk.run(Mock(side_effect=ValueError("synthetic bad RSS")), NOW)[0] == []
    data = output()
    assert data["status"] == "muted" and data["headlines"] == [] and len(data["error"]) == 3
    assert not Path(usfk.CSV_FILE).exists()
    assert all("hits_24h" not in item for item in data["groups"].values())


def test_corrupt_csv_keeps_bytes_and_previous_values(storage):
    usfk.run(lambda group: articles(), NOW)
    Path(usfk.CSV_FILE).write_bytes(b'date,wrong\n2026-11-08,1\n')
    usfk.run(lambda group: articles(10), NOW)
    assert Path(usfk.CSV_FILE).read_bytes() == b'date,wrong\n2026-11-08,1\n'
    assert output()["status"] == "muted"
    assert output()["groups"]["evac"]["hits_24h"] == 3


@pytest.mark.parametrize("failure", ["serialize", "replace"])
def test_atomic_json_failure_preserves_previous_bytes_and_removes_temp(storage, monkeypatch, failure):
    path = Path(usfk.JSON_FILE)
    path.write_bytes(b'previous\n')
    if failure == "replace":
        monkeypatch.setattr(usfk.atomic_write.__globals__["os"], "replace", Mock(side_effect=OSError("synthetic write failure")))
    with pytest.raises((ValueError, OSError)):
        usfk.write_json({"value": float("nan") if failure == "serialize" else 1})
    assert path.read_bytes() == b'previous\n' and list(storage.iterdir()) == [path]


def test_atomic_csv_failure_preserves_both_previous_files(storage, monkeypatch):
    usfk.run(lambda group: articles(), NOW)
    json_before, csv_before = Path(usfk.JSON_FILE).read_bytes(), Path(usfk.CSV_FILE).read_bytes()
    monkeypatch.setattr(usfk.atomic_write.__globals__["os"], "replace", Mock(side_effect=OSError("synthetic write failure")))
    with pytest.raises(OSError, match="synthetic write failure"):
        usfk.run(lambda group: articles(10), NOW)
    assert Path(usfk.JSON_FILE).read_bytes() == json_before and Path(usfk.CSV_FILE).read_bytes() == csv_before
    assert len(list(storage.iterdir())) == 2


def test_mail_missing_json_and_build_wiring(storage, monkeypatch):
    monkeypatch.chdir(storage)
    html = mail_report.build(DATE, [], [])
    assert "07 주한미군·공관 관련 공개 보도 신호" in html and "공개 보도 데이터를 기다리는 중" in html
    Path("data").mkdir()
    Path("data/usfk.json").write_text(json.dumps({"groups": {}, "watch": ["공개 보도 증가"]}))
    assert "공개 보도 증가" in mail_report.build(DATE, [], [])


class Links(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.hrefs = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.append(dict(attrs).get("href"))


def test_mail_escape_links_stale_values_headline_limit_and_no_hero_change():
    malicious = '<script>alert("x")</script>'
    data = {"status": "watch", "alerts": ["must be ignored"], "watch": [malicious],
            "groups": {"evac": {"date": malicious, "hits_24h": 3, "note": malicious,
                                 "error": malicious, "status": "watch"}},
            "headlines": [{"title": malicious, "source": malicious, "date": malicious, "link": "javascript:alert(1)"},
                          {"title": malicious, "source": malicious, "date": malicious, "link": 'https://example.test/?q="&x=1'}]
                         + [{"title": f"capped-{i}", "link": "data:text/html,hi"} for i in range(10)]}
    html = mail_report.render(DATE, [], [], None, None, None, U=data)
    assert "특이 동향 없음" in html and "must be ignored" not in html
    assert malicious not in html and "&lt;script&gt;" in html and "직전 관측값 유지" in html
    assert "javascript:" not in html and "data:text/html" not in html
    assert 'https://example.test/?q="&x=1' in Links(html).hrefs
    assert "capped-5" in html and "capped-6" not in html


def test_daily_report_wiring_without_import_or_execution():
    path = Path(__file__).resolve().parents[1] / "daily_report.py"
    tree = ast.parse(path.read_text())
    assert any(isinstance(node, ast.Import) and any(alias.name == "usfk_monitor" for alias in node.names) for node in tree.body)
    run = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run")
    parts = next(node.value for node in run.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "parts" for target in node.targets))
    assert ("주한미군·공관 관련 공개 보도 신호", "usfk_monitor.run") in [
        (node.elts[0].value, ast.unparse(node.elts[1])) for node in parts.elts]


def test_site_javascript_missing_data_escape_schemes_and_hero_exclusion():
    node = shutil.which("node")
    if not node:
        pytest.skip("사이트 JavaScript 합성 실행에 필요한 Node.js 없음")
    path = Path(__file__).resolve().parents[1] / "index.html"
    script = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const code = fs.readFileSync(process.argv[1], 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];
const elements = {};
const element = id => elements[id] ||= {innerHTML:'', textContent:'', style:{setProperty(){}}};
const sandbox = vm.createContext({
  document:{getElementById:element, documentElement:{}},
  getComputedStyle:()=>({getPropertyValue:()=>''}),
  fetch:async()=>({ok:false}),
});
(async()=>{
  vm.runInContext(code, sandbox);
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(element('usfkBody').innerHTML, /공개 보도 데이터를 기다리는 중/);
  const malicious='<script>alert(1)</script>';
  sandbox.fixture={status:'watch',alerts:['must be ignored'],watch:[malicious],
    groups:{evac:{hits_24h:3,date:malicious,note:malicious,error:malicious}},
    headlines:[{title:malicious,source:malicious,date:malicious,link:'javascript:alert(1)'},
      {title:'safe',source:'news',date:'2026-11-09',link:'https://example.test/?x="&y=1'},
      ...Array.from({length:10},(_,i)=>({title:'capped-'+i,link:'data:text/html,hi'}))]};
  vm.runInContext('U=fixture; usfk(); hero();', sandbox);
  const html=element('usfkBody').innerHTML;
  assert.ok(!html.includes(malicious));
  assert.match(html, /&lt;script&gt;/);
  assert.ok(!html.includes('javascript:') && !html.includes('data:text/html'));
  assert.match(html, /href="https:\/\/example.test\/\?x=&quot;&amp;y=1"/);
  assert.match(html, /직전 관측값 유지/);
  assert.match(html, /capped-5/);
  assert.ok(!html.includes('capped-6'));
  assert.equal(element('verdict').textContent, '데이터 수집 전');
  assert.ok(!element('heroAlerts').innerHTML.includes('must be ignored'));
  console.log('site synthetic JavaScript: missing JSON, XSS, HTTP(S), headline cap, hero exclusion PASS');
})().catch(error=>{console.error(error); process.exitCode=1;});
'''
    result = subprocess.run([node, "-e", script, str(path)], text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("group,title,expected", [
    ("evac", "USFK reviews noncombatant evacuation plan", True),
    ("evac", "미 대사관, 주한 미국인 대상 출국 권고... 철수 준비", True),
    ("evac", "12 Photo Booths & Studios For Nostalgic Neoprints From $3.30", False),
    ("evac", "주한미군 제19지원사령부 ‘제37기 한미 친선 써클’ 개회", False),
    ("evac", "Samsung Galaxy A15 4G Now Receiving One UI 9 Android 17 Update", False),
    ("evac", "South Korea: New elementary school enrolment to drop below 300,000", False),
    ("evac", "대기업 베트남 공장 철수 검토", False),   # 철수는 맞지만 주한미군·공관 맥락 없음
    ("readiness", "USFK raises force protection condition at Camp Humphreys", True),
    ("readiness", "Alert status at a hotel in Seoul", False),
    ("families", "USFK military families told to relocate; PCS suspended", True),
    ("families", "Korea dependents of local workers face relocation", False),
])
def test_title_relevance_filter(group, title, expected):
    assert usfk.relevant(group, title) is expected
