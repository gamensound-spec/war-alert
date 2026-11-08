"""OpenSky 합성 응답과 실패 시 이전 관측 보존. 실제 대기·네트워크·메일 없음."""
import datetime as dt
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

import air_monitor as air
import attention_monitor as attention
import mail_report
from news_monitor import robust_z

TODAY = dt.date(2026, 11, 8)


def state(country, ground=False):
    return [None, None, country, None, None, None, None, None, ground] + [None] * 8


def test_states_counts_only_false_and_top_three_airborne_countries():
    rows = [state("Korea") for _ in range(3)] + [state("Japan"), state("Japan"), state("China"),
            state("USA"), state(None), state("Korea", True), state("Unknown", None), state("Unknown", 0)]
    parsed = air.parse_states({"states": rows})
    assert parsed == {"airborne": 8, "total_states": 11,
                      "top_countries": [{"country": "Korea", "count": 3}, {"country": "Japan", "count": 2},
                                        {"country": "China", "count": 1}]}


@pytest.mark.parametrize("states", [None, []])
def test_null_states_is_empty_snapshot(states):
    assert air.parse_states({"states": states}) == {"airborne": 0, "total_states": 0, "top_countries": []}


@pytest.mark.parametrize("payload", [None, [], {}, {"states": {}}, {"states": [None]}, {"states": [[1, 2]]}])
def test_malformed_states_is_failure(payload):
    with pytest.raises(ValueError, match="OpenSky"):
        air.parse_states(payload)


@pytest.mark.parametrize("failure", [401, 429, "timeout"])
@pytest.mark.parametrize("success", [True, False])
def test_only_one_retry_after_15_seconds(monkeypatch, failure, success):
    bad = requests.Timeout("synthetic timeout") if failure == "timeout" else Mock(status_code=failure)
    if failure != "timeout":
        bad.raise_for_status.side_effect = requests.HTTPError(f"synthetic {failure}")
    good = Mock(status_code=200)
    good.json.return_value = {"states": [state("Korea")]}
    get, sleep = Mock(side_effect=[bad, good if success else bad]), Mock()
    monkeypatch.setattr(air.requests, "get", get)
    monkeypatch.setattr(air.time, "sleep", sleep)
    if success:
        assert air.fetch()["airborne"] == 1
    else:
        with pytest.raises(requests.RequestException):
            air.fetch()
    assert get.call_count == 2
    assert [call.args for call in sleep.call_args_list] == [(15,)]
    assert get.call_args.kwargs["params"] == {"lamin": 33, "lomin": 124, "lamax": 39, "lomax": 132}
    assert "auth" not in get.call_args.kwargs and "Authorization" not in get.call_args.kwargs["headers"]


@pytest.mark.parametrize("failure", ["connection", "500", "json"])
def test_other_failures_are_not_retried(monkeypatch, failure):
    response = Mock(status_code=500 if failure == "500" else 200)
    response.json.side_effect = ValueError("synthetic invalid JSON")
    if failure == "500":
        response.raise_for_status.side_effect = requests.HTTPError("synthetic 500")
    get = Mock(side_effect=requests.ConnectionError("synthetic DNS failure")) if failure == "connection" else Mock(return_value=response)
    sleep = Mock()
    monkeypatch.setattr(air.requests, "get", get)
    monkeypatch.setattr(air.time, "sleep", sleep)
    with pytest.raises((requests.RequestException, ValueError)):
        air.fetch()
    assert get.call_count == 1 and not sleep.called


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(air, "JSON_FILE", tmp_path / "air.json")
    monkeypatch.setattr(air, "CSV_FILE", tmp_path / "air_log.csv")
    return tmp_path


def snapshot(n=100):
    return {"airborne": n, "total_states": n + 10, "top_countries": [{"country": "Korea", "count": n}]}


def seed(values):
    start = TODAY - dt.timedelta(days=len(values))
    rows = [{"date": (start + dt.timedelta(days=i)).isoformat(), "airborne": value, "total_states": value + 10}
            for i, value in enumerate(values)]
    attention.write_log(air.CSV_FILE, rows, ["airborne", "total_states"])


@pytest.mark.parametrize("latest,status", [(20, "watch"), (300, "normal")])
def test_daily_count_z_sign_inverted_no_alerts(storage, latest, status):
    values = [900] * 5 + [90, 100, 110, 120] * 7
    seed(values)
    alerts, lines = air.run(lambda: snapshot(latest), TODAY)
    data = json.loads(Path(air.JSON_FILE).read_text())
    med, z = robust_z(latest, values[-28:])
    assert data["latest"]["base_n"] == 28 and data["latest"]["median"] == med
    assert data["latest"]["z"] == pytest.approx(-z) and data["status"] == status
    assert bool(data["watch"]) == (status == "watch") and alerts == data["alerts"] == []
    assert any(air.NOTICE in line for line in lines)
    assert data["source"] == "opensky-anonymous" and data["generated_at"].endswith("+09:00")


@pytest.mark.parametrize("values", [[], [100] * 13, [100] * 28])
def test_short_history_or_zero_mad_muted(storage, values):
    seed(values)
    air.run(lambda: snapshot(1), TODAY)
    data = json.loads(Path(air.JSON_FILE).read_text())
    assert data["status"] == "muted" and data["latest"]["z"] is None and data["watch"] == []


def test_same_day_snapshot_overwrite_and_excluded_from_baseline(storage):
    seed([90, 100] * 7)
    for n in [50, 40]:
        air.run(lambda: snapshot(n), TODAY)
    rows = attention.read_log(air.CSV_FILE, ["airborne", "total_states"])
    data = json.loads(Path(air.JSON_FILE).read_text())
    assert len(rows) == 15 and rows[-1]["airborne"] == 40
    assert data["latest"]["base_n"] == 14
    assert data["latest"]["z"] == pytest.approx(-robust_z(40, [90, 100] * 7)[1])


@pytest.mark.parametrize("has_previous", [True, False])
def test_failure_is_muted_keeps_previous_latest_series_and_csv(storage, has_previous):
    old = {"status": "watch", "latest": {"airborne": 10, "z": 5, "date": "2026-11-07"},
           "series": [{"date": "2026-11-07", "airborne": 10}], "alerts": [], "watch": ["stale watch"]}
    if has_previous:
        Path(air.JSON_FILE).write_text(json.dumps(old))
    Path(air.CSV_FILE).write_bytes(b'previous CSV\n')
    alerts, lines = air.run(Mock(side_effect=requests.HTTPError("synthetic 401")), TODAY)
    data = json.loads(Path(air.JSON_FILE).read_text())
    assert alerts == data["alerts"] == data["watch"] == []
    assert data["status"] == "muted" and data["error"] == "synthetic 401"
    assert data["latest"] == (old["latest"] if has_previous else {})
    assert data["series"] == (old["series"] if has_previous else [])
    assert Path(air.CSV_FILE).read_bytes() == b'previous CSV\n'
    assert any("수집 실패" in line for line in lines)


def test_corrupt_previous_json_falls_back_to_empty(storage):
    Path(air.JSON_FILE).write_text("not JSON")
    air.run(Mock(side_effect=ValueError("synthetic failure")), TODAY)
    data = json.loads(Path(air.JSON_FILE).read_text())
    assert data["status"] == "muted" and data["latest"] == {} and data["series"] == []


def test_csv_failure_is_muted_preserves_previous_snapshot_and_log(storage, monkeypatch):
    old = {"latest": {"airborne": 10, "date": "2026-11-07"}, "series": []}
    Path(air.JSON_FILE).write_text(json.dumps(old))
    seed([90, 100] * 7)
    previous_csv = Path(air.CSV_FILE).read_bytes()
    monkeypatch.setattr(air, "write_log", Mock(side_effect=OSError("synthetic CSV write failure")))
    air.run(lambda: snapshot(), TODAY)
    data = json.loads(Path(air.JSON_FILE).read_text())
    assert data["status"] == "muted" and data["latest"] == old["latest"]
    assert data["error"] == "synthetic CSV write failure"
    assert Path(air.CSV_FILE).read_bytes() == previous_csv


@pytest.mark.parametrize("failure", ["serialize", "replace"])
def test_atomic_json_failure_preserves_previous(storage, monkeypatch, failure):
    path = Path(air.JSON_FILE)
    path.write_bytes(b'previous\n')
    if failure == "replace":
        monkeypatch.setattr(attention.os, "replace", Mock(side_effect=OSError("synthetic write failure")))
    with pytest.raises((ValueError, OSError)):
        air.write_json({"value": float("nan") if failure == "serialize" else 1})
    assert path.read_bytes() == b'previous\n' and list(storage.iterdir()) == [path]


def test_mail_build_air_file_and_escape_country_error(storage, monkeypatch):
    monkeypatch.chdir(storage)
    malicious = '<img src=x onerror="alert(1)">'
    data = {"status": "watch", "alerts": ["must be ignored"], "error": malicious,
            "latest": {"airborne": 10, "date": "2026-11-07", "z": 3,
                       "top_countries": [{"country": malicious, "count": 10}]}}
    Path("data").mkdir()
    Path("data/air.json").write_text(json.dumps(data))
    html = mail_report.build("2026-11-08", [], [])
    assert "특이 동향 없음" in html and "경보 1건" not in html and "must be ignored" not in html
    assert "직전 관측값 유지" in html and "하루 한 시점 스냅샷" in html
    assert malicious not in html and "&lt;img" in html


def test_mail_null_air_values():
    assert "이전 관측값 없음" in mail_report.air_html({"latest": None, "series": None})
    assert "이전 관측값 없음" in mail_report.air_html({"latest": {"airborne": None, "z": None, "top_countries": None}})
