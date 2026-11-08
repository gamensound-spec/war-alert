"""외부 호출·메일 발송 없이 Yahoo 합성 응답과 참고 지표를 검증한다."""
import datetime as dt
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

import mail_report
import market_monitor as market
from news_monitor import robust_z


def chart(closes, timestamps=None, timezone="Asia/Seoul"):
    start = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc).timestamp()
    return {"chart": {"error": None, "result": [{
        "meta": {"exchangeTimezoneName": timezone},
        "timestamp": timestamps if timestamps is not None else [start + i * 86400 for i in range(len(closes))],
        "indicators": {"quote": [{"close": closes}]}}]}}


def history(returns=None):
    closes = [100.0]
    for value in returns if returns is not None else [-0.2, -0.1, 0.1, 0.2] * 15 + [0.5] * 20:
        closes.append(closes[-1] * (1 + value / 100))
    return market.parse_chart(chart(closes))


def test_null_invalid_closes_keep_timestamp_alignment():
    days = market.parse_chart(chart([100, None, 102, False, "103", float("nan"), float("inf"), -1, 0, 104]))
    assert [(day["date"], day["close"]) for day in days] == [
        ("2026-01-01", 100), ("2026-01-03", 102), ("2026-01-10", 104)]


@pytest.mark.parametrize("payload", [None, [], {}, {"chart": None}, {"chart": {"result": None}},
                                    {"chart": {"result": []}}, {"chart": {"error": {"code": "Not Found"}}},
                                    chart([None, None])])
def test_unexpected_responses_fail_cleanly(payload):
    with pytest.raises(ValueError, match="Yahoo"):
        market.parse_chart(payload)


def test_reject_misaligned_arrays():
    with pytest.raises(ValueError, match="불일치"):
        market.parse_chart(chart([100, 101], [1]))


def test_sort_deduplicate_and_keep_90_closes():
    payload = chart(list(range(1, 102)))
    item = payload["chart"]["result"][0]
    item["timestamp"].reverse()
    item["indicators"]["quote"][0]["close"].reverse()
    days = market.parse_chart(payload)
    assert len(days) == 90
    assert [d["close"] for d in days] == list(range(12, 102))


def test_exchange_date_and_invalid_timestamp():
    timestamp = dt.datetime(2026, 1, 1, 23, tzinfo=dt.timezone.utc).timestamp()
    days = market.parse_chart(chart([10, 20, 30], [None, 1e100, timestamp]))
    assert days == [{"date": "2026-01-02", "close": 30}]


def test_unknown_timezone_falls_back_to_utc():
    assert market.parse_chart(chart([100], timezone="Unknown/Zone"))[0]["date"] == "2026-01-01"


def test_z_uses_20_day_return_and_preceding_60_daily_returns():
    days = history([9] * 9 + [-0.2, -0.1, 0.1, 0.2] * 15 + [0.5] * 20)
    actual_returns = [(b["close"] / a["close"] - 1) * 100 for a, b in zip(days, days[1:])]
    change = (days[-1]["close"] / days[-21]["close"] - 1) * 100
    med, z = robust_z(change / 20 ** 0.5, actual_returns[-80:-20])  # 누적 변화는 √20으로 단위 보정
    item = market.evaluate("KRW=X", days)
    assert item["base_n"] == 60
    assert item["median"] == pytest.approx(med)
    assert item["change_pct"] == pytest.approx(0.5)
    assert item["change_20d_pct"] == pytest.approx(change)
    assert item["z"] == pytest.approx(z)
    assert item["status"] == "watch"
    assert market.evaluate("^KS11", days)["z"] == pytest.approx(-z)


@pytest.mark.parametrize("symbol,direction", [("KRW=X", 1), ("^KS11", -1)])
def test_stress_direction(symbol, direction):
    assert market.evaluate(symbol, history([-0.2, -0.1, 0.1, 0.2] * 15 + [direction * 0.5] * 20))["status"] == "watch"
    assert market.evaluate(symbol, history([-0.2, -0.1, 0.1, 0.2] * 15 + [-direction * 0.5] * 20))["status"] == "normal"


def test_minimum_baseline_excludes_latest_window():
    short = market.evaluate("KRW=X", history([-0.2, 0.1] * 14 + [0.2] + [0.5] * 20))
    assert short["base_n"] == 29
    assert short["z"] is None and short["status"] == "muted"
    enough = market.evaluate("KRW=X", history([-0.2, 0.1] * 15 + [0.5] * 20))
    assert enough["base_n"] == 30 and enough["z"] is not None


@pytest.mark.parametrize("closes", [[100], [100] * 90])
def test_short_or_zero_mad_is_muted(closes):
    item = market.evaluate("KRW=X", market.parse_chart(chart(closes)))
    assert item["status"] == "muted" and item["z"] is None


@pytest.mark.parametrize("scores,status,simultaneous", [
    ((1.9999, -3), "normal", False), ((2.0, 0), "watch", False),
    ((2.0, 2.1), "watch", True), ((None, None), "muted", False),
    ((None, 0), "muted", False), ((None, 2), "watch", False)])
def test_classify_threshold_and_partial_data(scores, status, simultaneous):
    actual, watch = market.classify({symbol: {"z": z} for symbol, z in zip(market.SYMBOLS, scores)})
    assert actual == status
    assert any("동시 악화" in text for text in watch) == simultaneous


@pytest.mark.parametrize("failure", ["429", "json"])
def test_retry_15_30_then_success(monkeypatch, failure):
    bad = Mock(status_code=429 if failure == "429" else 200)
    bad.json.side_effect = ValueError("HTML")
    good = Mock(status_code=200)
    good.json.return_value = chart([100, None, 102])
    get = Mock(side_effect=[bad, bad, good])
    sleep = Mock()
    monkeypatch.setattr(market.requests, "get", get)
    monkeypatch.setattr(market.time, "sleep", sleep)
    assert len(market.fetch("^KS11")) == 2
    assert [call.args[0] for call in sleep.call_args_list] == [15, 30]
    assert get.call_count == 3
    assert "%5EKS11" in get.call_args.args[0]
    assert get.call_args.kwargs["headers"]["User-Agent"]
    assert get.call_args.kwargs["params"] == {"range": "6mo", "interval": "1d"}


@pytest.mark.parametrize("failure", ["429", "json"])
def test_retry_exhaustion(monkeypatch, failure):
    bad = Mock(status_code=429 if failure == "429" else 200)
    bad.json.side_effect = ValueError("HTML")
    get, sleep = Mock(return_value=bad), Mock()
    monkeypatch.setattr(market.requests, "get", get)
    monkeypatch.setattr(market.time, "sleep", sleep)
    with pytest.raises(RuntimeError, match="15·30초 재시도 후 포기"):
        market.fetch("KRW=X")
    assert get.call_count == 3
    assert [call.args[0] for call in sleep.call_args_list] == [15, 30]


def test_network_exception_is_not_retried(monkeypatch):
    get = Mock(side_effect=requests.ConnectionError("synthetic DNS failure"))
    monkeypatch.setattr(market.requests, "get", get)
    with pytest.raises(requests.ConnectionError):
        market.fetch("KRW=X")
    assert get.call_count == 1


def test_run_output_never_alerts(tmp_path, monkeypatch):
    path = tmp_path / "market.json"
    monkeypatch.setattr(market, "JSON_FILE", path)
    alerts, lines = market.run(lambda symbol: history([-0.2, -0.1, 0.1, 0.2] * 15 + [0.5 if symbol == "KRW=X" else -0.5] * 20))
    data = json.loads(path.read_text())
    assert alerts == data["alerts"] == []
    assert data["status"] == "watch" and "동시 악화" in data["watch"][-1]
    assert data["source"] == "yahoo-chart-unofficial"
    assert data["generated_at"].endswith("+09:00")
    assert data["config"]["z_watch"] == market.Z_WATCH
    assert any(market.NOTICE in line for line in lines)


@pytest.mark.parametrize("failed_symbol", list(market.SYMBOLS))
def test_one_failure_keeps_other_symbol(tmp_path, monkeypatch, failed_symbol):
    path = tmp_path / "market.json"
    monkeypatch.setattr(market, "JSON_FILE", path)
    calls = []

    def fetcher(symbol):
        calls.append(symbol)
        if symbol == failed_symbol:
            raise ValueError("synthetic invalid response")
        return history([0.1, -0.1] * 30 + [0.0] * 20)

    assert market.run(fetcher)[0] == []
    data = json.loads(path.read_text())
    assert calls == list(market.SYMBOLS)
    assert data["status"] == "muted"
    assert data["error"][failed_symbol] == data["latest"][failed_symbol]["error"]
    assert data["series"][failed_symbol] == []
    assert len(data["series"][next(s for s in market.SYMBOLS if s != failed_symbol)]) == 81


def test_both_fail_preserves_previous_bytes(tmp_path, monkeypatch):
    path = tmp_path / "market.json"
    path.write_bytes(b'{"previous":true}\n')
    monkeypatch.setattr(market, "JSON_FILE", path)
    with pytest.raises(RuntimeError, match="모두 수집 실패"):
        market.run(Mock(side_effect=requests.ConnectionError("synthetic DNS failure")))
    assert path.read_bytes() == b'{"previous":true}\n'


@pytest.mark.parametrize("failure", ["serialize", "replace"])
def test_atomic_write_failure_preserves_previous(tmp_path, monkeypatch, failure):
    path = tmp_path / "market.json"
    path.write_text("previous")
    monkeypatch.setattr(market, "JSON_FILE", path)
    if failure == "replace":
        monkeypatch.setattr(market.os, "replace", Mock(side_effect=OSError("synthetic write failure")))
    with pytest.raises((ValueError, OSError)):
        market.write_json({"value": float("nan") if failure == "serialize" else 1})
    assert path.read_text() == "previous"
    assert list(tmp_path.iterdir()) == [path]


def test_mail_missing_market_and_build_wiring(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    html = mail_report.build("2026-11-08", [], [])
    assert "04 시장 스트레스" in html and "시장 데이터를 기다리는 중" in html
    assert "대리 지표 · 신뢰도 낮음 · 경보 없음" in html
    market_path = Path("data/market.json")
    market_path.parent.mkdir()
    market_path.write_text(json.dumps({"latest": {}, "status": "watch", "watch": ["동시 악화"]}))
    assert "동시 악화" in mail_report.build("2026-11-08", [], [])


def test_mail_stale_escaped_and_no_verdict_change():
    malicious = '<img src=x onerror="alert(1)">'
    M = {"status": "watch", "alerts": ["must be ignored"], "watch": ["동시 악화", malicious],
         "latest": {"KRW=X": {"date": "2026-11-04", "close": 1400, "change_pct": 1,
                              "z": 2, "status": "watch"}, "^KS11": {"error": malicious}}}
    html = mail_report.render("2026-11-08", [], [], None, None, None, M)
    assert "특이 동향 없음" in html and "경보 1건" not in html and "must be ignored" not in html
    assert "데이터 지연" in html and "동시 악화" in html
    assert "&lt;img" in html and malicious not in html


def test_mail_three_day_lag_is_not_delayed():
    M = {"status": "normal", "latest": {s: {"date": "2026-11-05", "close": 1,
         "change_pct": None, "z": 0, "status": "normal"} for s in market.SYMBOLS}}
    assert "데이터 지연" not in mail_report.market_html(M, "2026-11-08")
