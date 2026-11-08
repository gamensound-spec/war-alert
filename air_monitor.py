"""한반도 상공 OpenSky 익명 API의 하루 한 시점 스냅샷. 경보 없음."""
import datetime as dt
import json
import time
from collections import Counter
from pathlib import Path

import requests

from attention_monitor import atomic_write, read_log, write_log, upsert, baseline, score

API = "https://opensky-network.org/api/states/all"
BOX = {"lamin": 33, "lomin": 124, "lamax": 39, "lomax": 132}
JSON_FILE, CSV_FILE = "data/air.json", "data/air_log.csv"
KST = dt.timezone(dt.timedelta(hours=9))
NOTICE = "참고 지표 · 신뢰도 낮음 · 경보 없음 · 하루 한 시점 스냅샷"


def parse_states(payload):
    if not isinstance(payload, dict) or "states" not in payload:
        raise ValueError("OpenSky states 필드 없음")
    # API의 states:null은 수신된 항공기가 없다는 뜻이다. null on_ground는 비행으로 세지 않는다.
    states = payload["states"]
    if states is None:
        states = []
    if not isinstance(states, list) or any(not isinstance(row, list) or len(row) < 9 for row in states):
        raise ValueError("OpenSky states 배열 형식 오류")
    airborne = [row for row in states if row[8] is False]
    countries = Counter(row[2].strip() for row in airborne if isinstance(row[2], str) and row[2].strip())
    top = sorted(countries.items(), key=lambda pair: (-pair[1], pair[0]))[:3]
    return {"airborne": len(airborne), "total_states": len(states),
            "top_countries": [{"country": name, "count": n} for name, n in top]}


def fetch():
    for attempt in range(2):
        try:
            response = requests.get(API, params=BOX, headers={"User-Agent": "war-alert/1.0"}, timeout=30)
        except requests.Timeout:
            if attempt:
                raise
        else:
            if response.status_code not in (401, 429) or attempt:
                response.raise_for_status()
                return parse_states(response.json())
        time.sleep(15)


def write_json(out):
    atomic_write(JSON_FILE, lambda f: json.dump(out, f, ensure_ascii=False, indent=1, allow_nan=False))


def previous():
    try:
        data = json.loads(Path(JSON_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def run(fetcher=fetch, today=None):
    today = today or dt.datetime.now(KST).date()
    out = {"generated_at": dt.datetime.now(KST).isoformat(timespec="minutes"),
           "source": "opensky-anonymous", "status": "muted", "alerts": [], "watch": [],
           "latest": {}, "series": [],
           "config": {"base_days": 28, "min_base": 14, "z_watch": 2.0, "snapshot_kst": "08:47",
                      "box": BOX, "method": "daily snapshot count vs preceding 28 calendar days; median/MAD * 1.4826; sign inverted"}}
    try:
        snapshot = fetcher()
        row = {"date": today.isoformat(), "airborne": snapshot["airborne"], "total_states": snapshot["total_states"]}
        rows = upsert(read_log(CSV_FILE, ["airborne", "total_states"]), row)
        latest = {**snapshot, "date": row["date"], **score(row["airborne"], baseline(rows, row["date"], "airborne"), -1)}
        write_log(CSV_FILE, rows, ["airborne", "total_states"])
        out.update(status=latest["status"], latest=latest, series=rows)
        if latest["status"] == "watch":
            out["watch"] = [f"한반도 상공 항공기 감소 (z {latest['z']:+.2f})"]
        hint = (f"하락 방향 z {latest['z']:+.2f}" if latest["z"] is not None
                else f"판단 보류(기준선 {latest['base_n']}/14일 또는 MAD 0)")
        lines = [f"OpenSky {latest['date']}: 비행 중 {latest['airborne']}대 / 전체 {latest['total_states']}대 · {hint}"]
    except (requests.RequestException, RuntimeError, ValueError, KeyError, IndexError, TypeError, OSError) as exc:
        old = previous()
        out.update(error=str(exc), latest=old.get("latest") or {}, series=old.get("series") or [])
        lines = [f"OpenSky: 수집 실패 · {exc}", "판단 보류 · 직전 관측값 유지" if out["latest"] else "판단 보류 · 이전 관측값 없음"]
    write_json(out)
    lines += [f"주의: {item}" for item in out["watch"]]
    lines += [f"판정: {out['status']}", f"출처: OpenSky Network (익명 API) · {NOTICE}"]
    return [], lines


if __name__ == "__main__":
    alerts, lines = run()
    print(*lines, sep="\n")
