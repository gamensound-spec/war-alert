"""합성 GKG만 사용한다. pytest 및 표준 unittest로 실행할 수 있다."""
import copy
from contextlib import redirect_stdout
import datetime as dt
import io
import json
from pathlib import Path
import statistics
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

import requests

import gdelt_gkg as gkg
import news_monitor as news


TODAY = dt.date(2026, 11, 8)


def record(url="https://example.org/north-korea-missile", themes="", tone="-2,1,3,4,5,6,7"):
    fields = [""] * 27
    fields[0] = "20261107000000-1"
    fields[1] = "20261107000000"
    fields[2] = "1"
    fields[3] = "example.org"
    fields[4], fields[8], fields[15] = url, themes, tone
    return "\t".join(fields) + "\n"


def zipped(text):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("20261107000000.gkg.csv", text)
    return buffer.getvalue()


class Response:
    def __init__(self, content, error=None):
        self.content = content
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        if self.error:
            raise self.error

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.content), 17):
            yield self.content[offset:offset + 17]


def daily(date="2026-11-07", count=2, total=4, tone=-1.0):
    return {"date": date, "count": count, "total": total, "tone": tone}


def doc_volume(date="20261107", count=2, total=100):
    return {"timeline": [{"data": [{"date": date + "T000000Z", "value": count, "norm": total}]}]}


class ParsingTests(unittest.TestCase):
    def test_matching_uses_only_document_and_enhanced_themes(self):
        lines = [
            record(),
            record("https://example.org/story", "NORTH_KOREA,10;WAR,20;", "2,0"),
            record("https://example.org/Korean%20Peninsula?event=attack", tone=""),
            record("https://example.org/war", "ECONOMY,10;"),
            record("https://example.org/north-korea-reward"),
            record("https://example.org/north-korea"),
        ]
        result = gkg.aggregate(iter(lines))
        self.assertEqual((result["total"], result["count"]), (6, 3))
        self.assertEqual((result["tone_sum"], result["tone_n"]), (0, 2))
        self.assertEqual(len(result["articles"]), 3)
        self.assertIn("example.org | https://", result["articles"][0]["title"])
        fields = record("https://example.org/unrelated").rstrip("\n").split("\t")
        fields[7] = "NORTH_KOREA;WAR;"  # V1Themes는 조회하지 않는다.
        fields[9] = "North Korea war"  # Locations도 조회하지 않는다.
        self.assertEqual(gkg.aggregate(["\t".join(fields)])["count"], 0)

    def test_all_six_keywords_case_and_separators(self):
        for keyword in ("war", "missile", "attack", "invasion", "evacuation", "troops"):
            with self.subTest(keyword=keyword):
                self.assertEqual(gkg.aggregate([record(f"https://example.org/NORTH_KOREA/{keyword}")])["count"], 1)

    def test_records_are_counted_even_if_url_is_duplicate(self):
        result = gkg.aggregate([record(), record(tone="4,0")])
        self.assertEqual((result["count"], result["total"]), (2, 2))
        self.assertEqual(result["tone_sum"] / result["tone_n"], 1)
        self.assertEqual(len(result["articles"]), 1)

    def test_articles_are_bounded_and_http_only(self):
        lines = [record(f"https://example.org/north-korea-war/{i}") for i in range(20)]
        lines.append(record("citation:north-korea-war"))
        result = gkg.aggregate(lines)
        self.assertEqual(result["count"], 21)
        self.assertEqual(len(result["articles"]), 12)
        self.assertEqual(result["articles"][0]["url"], "https://example.org/north-korea-war/0")

    def test_long_url_titles_keep_twelve_distinct_articles(self):
        prefix = "https://example.org/" + "long-path/" * 10
        lines = [record(f"{prefix}north-korea-war/{i}") for i in range(20)]
        self.assertEqual(len(news.articles(gkg.aggregate(lines)["articles"])), 12)

    def test_missing_tone_and_no_matches(self):
        self.assertEqual(gkg.aggregate([record(tone="")])["tone_n"], 0)
        self.assertEqual(gkg.aggregate([record("https://example.org/sports")])["count"], 0)

    def test_bad_rows_and_tone_are_explicit_errors(self):
        for row in ("broken\trow\n", record(tone="NaN"), record(tone="not-a-number")):
            with self.subTest(row=row[:20]), self.assertRaises(RuntimeError):
                gkg.aggregate([row])

    def test_urls_cover_exactly_one_utc_day(self):
        urls = gkg.day_urls(dt.date(2026, 11, 7))
        self.assertEqual(len(set(urls)), 96)
        self.assertTrue(urls[0].endswith("20261107000000.gkg.csv.zip"))
        self.assertTrue(urls[-1].endswith("20261107234500.gkg.csv.zip"))

    def test_streamed_day_totals_tone_and_download_bytes(self):
        payload = zipped(record() + record(tone="4,0") + record("https://example.org/sports"))
        session = Mock()
        session.get.side_effect = lambda *a, **kw: Response(payload)
        metrics = {"bytes": 0}
        with patch("builtins.print"):
            row, arts = gkg.download_day(TODAY - dt.timedelta(days=1), session, metrics)
        self.assertEqual(row, daily(count=192, total=288, tone=1))
        self.assertEqual(len(arts), 1)
        self.assertEqual(session.get.call_count, 96)
        self.assertEqual(metrics["bytes"], len(payload) * 96)
        for call in session.get.call_args_list:
            self.assertTrue(call.kwargs["stream"])
            self.assertTrue(call.kwargs["allow_redirects"])

    def test_network_http_and_zip_errors_become_runtime_errors(self):
        for response in (requests.ConnectionError("offline"),
                         Response(b"", requests.HTTPError("404")), Response(b"invalid zip"),
                         Response(zipped("malformed\n")), Response(zipped(""))):
            with self.subTest(response=type(response).__name__):
                session = Mock()
                if isinstance(response, Exception):
                    session.get.side_effect = response
                else:
                    session.get.return_value = response
                with patch("builtins.print"), self.assertRaises(RuntimeError):
                    gkg.download_day(TODAY, session, {"bytes": 0})


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.csv = Path(self.temporary.name) / "daily.csv"
        self.json = Path(self.temporary.name) / "news.json"

    def fetch(self, **kwargs):
        return gkg.fetch(today=TODAY, csv_file=self.csv, json_file=self.json, **kwargs)

    def test_incremental_cap_and_cached_dates_are_not_downloaded(self):
        def download(day, *args):
            return daily(day.isoformat()), []
        with patch.object(gkg, "download_day", side_effect=download) as fetch:
            days, _ = self.fetch()
            self.assertEqual([c.args[0] for c in fetch.call_args_list],
                             [dt.date(2026, 11, d) for d in (7, 6, 5)])
        self.assertEqual(len(days), 3)
        self.assertEqual(self.csv.read_text().splitlines()[0], "date,count,total,tone")
        with patch.object(gkg, "download_day", side_effect=download) as fetch:
            days, _ = self.fetch(backfill=2)
            self.assertEqual([c.args[0] for c in fetch.call_args_list],
                             [dt.date(2026, 11, d) for d in (4, 3)])
        self.assertEqual(len(gkg.load_daily(self.csv)), 5)
        self.assertEqual(len(days), 5)

    def test_successful_day_persists_when_next_day_fails(self):
        with patch.object(gkg, "download_day", side_effect=[(daily(), []), RuntimeError("offline")]):
            with self.assertRaisesRegex(RuntimeError, "offline"):
                self.fetch(backfill=2)
        self.assertEqual(gkg.load_daily(self.csv), {"2026-11-07": daily()})

    def test_failed_partial_day_is_not_saved(self):
        session = Mock()
        session.get.side_effect = [Response(zipped(record())), requests.ConnectionError("offline")]
        with patch.object(gkg.requests, "Session") as session_factory:
            session_factory.return_value.__enter__.return_value = session
            with self.assertRaisesRegex(RuntimeError, "offline"):
                self.fetch(backfill=1)
        self.assertFalse(self.csv.exists())

    def test_cached_window_needs_no_network_and_preserves_articles(self):
        rows = {day.isoformat(): daily(day.isoformat(), tone=None)
                for day in (TODAY - dt.timedelta(days=i) for i in range(1, 30))}
        gkg.save_daily(rows, self.csv)
        self.json.write_text(json.dumps({"source": "gdelt-gkg", "series": [],
                                        "articles": [{"title": "prior", "url": "https://example.org/a",
                                                      "date": "2026-11-07"}]}))
        with patch.object(gkg, "download_day") as fetch:
            days, arts = self.fetch()
        fetch.assert_not_called()
        self.assertEqual(len(days), 29)
        self.assertIsNone(days[-1]["tone"])
        self.assertEqual(news.articles(arts)[0]["date"], "2026-11-07")

    def test_doc_history_is_not_mixed_into_gkg_baseline(self):
        self.json.write_text(json.dumps({"series": [
            {**daily("2026-10-24"), "share": 10, "partial": False},
            {**daily("2026-11-07"), "share": 20}]}))
        with patch.object(gkg, "download_day", side_effect=[
                (daily(), [{"title": "newest", "url": "https://example.org/new"}]),
                (daily("2026-11-06"), [{"title": "older"}])]):
            days, arts = self.fetch(backfill=2)
        self.assertEqual([d["date"] for d in days], ["2026-11-06", "2026-11-07"])
        self.assertEqual({d["source"] for d in days}, {"gdelt-gkg"})
        self.assertEqual(days[-1]["share"], 5000)
        self.assertEqual(arts[0]["title"], "newest")

    def test_non_utf8_bytes_do_not_abort_the_day(self):
        bad = record(url="https://example.org/north-korea-missile").encode("utf-8") + \
            b"x\xa1y\t" + b"\t" * 25 + b"\n"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("20261107000000.gkg.csv", bad)
        session = Mock()
        session.get.side_effect = lambda *a, **kw: Response(buffer.getvalue())
        try:
            row, _ = gkg.download_day(dt.date(2026, 11, 7), session, {"bytes": 0})
        except RuntimeError as exc:   # 비UTF-8 때문이 아닌 행 형식 오류는 허용
            self.assertNotIn("utf-8", str(exc))
        else:
            self.assertGreaterEqual(row["total"], 1)

    def test_old_backfill_does_not_replace_saved_latest_articles(self):
        gkg.save_daily({"2026-11-07": daily()}, self.csv)
        self.json.write_text(json.dumps({"source": "gdelt-gkg", "series": [],
                                        "articles": [{"title": "latest", "date": "2026-11-07"}]}))
        with patch.object(gkg, "download_day", return_value=(daily("2026-11-06"), [{"title": "old"}])):
            _, arts = self.fetch(backfill=1)
        self.assertEqual(arts[0]["title"], "latest")

    def test_articles_can_recover_after_checkpoint_without_json(self):
        gkg.save_daily({"2026-11-07": daily()}, self.csv)
        with patch.object(gkg, "download_day", return_value=(daily("2026-11-06"), [{"title": "recovered"}])):
            _, arts = self.fetch(backfill=1)
        self.assertEqual(arts[0]["title"], "recovered")

    def test_backfill_over_three_is_rejected(self):
        for size in (0, 4, 28):
            with self.subTest(size=size), self.assertRaises(ValueError):
                self.fetch(backfill=size)

    def test_cli_backfills_two_synthetic_days_and_writes_news_without_doc(self):
        payload = zipped(record() + record("https://example.org/sports"))
        session = Mock()
        session.get.side_effect = lambda *a, **kw: Response(payload)
        output = io.StringIO()
        with patch.object(gkg, "CSV_FILE", self.csv), patch.object(gkg, "JSON_FILE", self.json), patch.object(news, "JSON_FILE", str(self.json)), patch.object(gkg.requests, "Session") as session_factory, patch.object(news, "gdelt", side_effect=AssertionError("DOC must not be called")), patch("sys.argv", ["gdelt_gkg.py", "--backfill", "2"]), redirect_stdout(output):
            session_factory.return_value.__enter__.return_value = session
            gkg.main()
        rows = gkg.load_daily(self.csv)
        self.assertEqual(len(rows), 2)
        self.assertEqual(session.get.call_count, 192)
        self.assertTrue(all(row["count"] == 96 and row["total"] == 192 for row in rows.values()))
        result = json.loads(self.json.read_text())
        self.assertEqual(result["source"], "gdelt-gkg")
        self.assertEqual(result["latest"]["share"], 5000)
        self.assertIn(f"GKG run: bytes={len(payload) * 192}", output.getvalue())


class FallbackTests(unittest.TestCase):
    def setUp(self):
        # 실제 data/news.json 내용에 따라 동작이 달라지지 않도록 임시 경로를 쓴다
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.json = Path(self.temporary.name) / "news.json"
        patcher = patch.object(news, "JSON_FILE", str(self.json))
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_previous(self, latest, source="gdelt-doc", row_source="gdelt-doc"):
        self.json.write_text(json.dumps({
            "source": source, "latest": {"date": latest},
            "series": [{"date": latest, "count": 5, "total": 100, "share": 500, "tone": None, "source": row_source}],
            "articles": [{"title": "prev", "url": "https://example.org/p", "date": latest}]}))

    def test_doc_429_keeps_recent_previous_doc_and_only_accumulates_gkg(self):
        self.write_previous("2026-11-05")   # TODAY(11-08) 기준 정확히 3일 → 유지
        with patch.object(news, "gdelt", side_effect=RuntimeError("429")), \
                patch.object(gkg, "fetch", return_value=([daily()], [])) as accumulate, patch("builtins.print"):
            days, arts = news.fetch(today=TODAY)
        accumulate.assert_called_once()
        self.assertEqual([d["date"] for d in days], ["2026-11-05"])
        self.assertEqual(days[0]["source"], "gdelt-doc")
        self.assertEqual(arts[0]["seendate"], "20261105")

    def test_gkg_accumulation_failure_does_not_break_kept_doc(self):
        self.write_previous("2026-11-06")
        with patch.object(news, "gdelt", side_effect=RuntimeError("429")), \
                patch.object(gkg, "fetch", side_effect=RuntimeError("offline")), patch("builtins.print"):
            days, _ = news.fetch(today=TODAY)
        self.assertEqual(days[0]["date"], "2026-11-06")

    def test_stale_or_gkg_previous_falls_back_to_gkg(self):
        for kwargs in ({"latest": "2026-11-04"}, {"latest": "2026-11-07", "source": "gdelt-gkg"},
                       {"latest": "2026-11-07", "row_source": "gdelt-gkg"}):
            with self.subTest(**kwargs):
                self.write_previous(**kwargs)
                with patch.object(news, "gdelt", side_effect=RuntimeError("429")), \
                        patch.object(gkg, "fetch", return_value=([daily()], [])) as fallback, patch("builtins.print"):
                    self.assertEqual(news.fetch(today=TODAY), ([daily()], []))
                fallback.assert_called_once()

    def test_doc_failures_empty_and_malformed_use_gkg(self):
        for failure in (RuntimeError("429"), requests.ConnectionError("offline"),
                        ValueError("invalid JSON"), {"timeline": [{"data": []}]}, {},
                        {"timeline": []}, {"timeline": [{"data": [{"date": "bad"}]}]}):
            with self.subTest(failure=str(failure)):
                with patch.object(news, "gdelt") as doc, patch.object(gkg, "fetch", return_value=([daily()], [])) as fallback, patch("builtins.print"):
                    if isinstance(failure, Exception):
                        doc.side_effect = failure
                    else:
                        doc.return_value = failure
                    self.assertEqual(news.fetch(today=TODAY), ([daily()], []))
                    fallback.assert_called_once_with(today=TODAY, json_file=news.JSON_FILE)
                    self.assertEqual(doc.call_count, 1)

    def test_stale_full_day_ignores_new_partial_day(self):
        volume = doc_volume("20261104")
        volume["timeline"][0]["data"].append({"date": "20261108T000000Z", "value": 1, "norm": 1})
        with patch.object(news, "gdelt", return_value=volume) as doc, patch.object(gkg, "fetch", return_value=([], [])) as fallback, patch("builtins.print"):
            news.fetch(today=TODAY)
        fallback.assert_called_once()
        self.assertEqual(doc.call_count, 1)

    def test_exactly_three_days_late_remains_doc(self):
        with patch.object(news, "gdelt", side_effect=[doc_volume("20261105"),
                {"timeline": [{"data": [{"date": "20261105T000000Z", "value": -3}]}]},
                {"articles": [{"title": "DOC", "url": "https://example.org/doc"}]}]), patch.object(gkg, "fetch") as fallback:
            days, arts = news.fetch(today=TODAY)
        fallback.assert_not_called()
        self.assertEqual(days[0]["source"], "gdelt-doc")
        self.assertEqual(days[0]["tone"], -3)
        self.assertEqual(days[0]["share"], 200)
        self.assertEqual(arts[0]["title"], "DOC")

    def test_optional_doc_metadata_failure_preserves_existing_behavior(self):
        with patch.object(news, "gdelt", side_effect=[doc_volume(), RuntimeError("429"), RuntimeError("429")]), patch.object(gkg, "fetch") as fallback, patch("builtins.print"):
            days, arts = news.fetch(today=TODAY)
        fallback.assert_not_called()
        self.assertEqual(arts, [])
        self.assertIsNone(days[0]["tone"])

    def test_gkg_failure_propagates(self):
        with patch.object(news, "gdelt", side_effect=RuntimeError("429")), patch.object(gkg, "fetch", side_effect=RuntimeError("GKG offline")), patch("builtins.print"):
            with self.assertRaisesRegex(RuntimeError, "GKG offline"):
                news.fetch(today=TODAY)

    def test_failed_fetch_leaves_previous_news_json_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "news.json"
            output.write_text('{"previous": true}\n')
            with patch.object(news, "JSON_FILE", str(output)):
                with self.assertRaisesRegex(RuntimeError, "network failure"):
                    news.run(fetcher=Mock(side_effect=RuntimeError("network failure")))
            self.assertEqual(output.read_text(), '{"previous": true}\n')

    def test_run_preserves_json_contract_and_adds_source(self):
        for source in ("gdelt-doc", "gdelt-gkg"):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "news.json"
                days = [{**daily(), "share": 5000, "source": source}]
                arts = gkg.aggregate([record()])["articles"]
                with patch.object(news, "JSON_FILE", str(output)):
                    news.run(fetcher=lambda: (days, arts))
                result = json.loads(output.read_text())
                self.assertEqual(result["source"], source)
                self.assertTrue({"date", "count", "total", "share", "tone", "partial"} <= result["series"][0].keys())
                self.assertEqual(set(result["latest"]), {"date", "share", "count", "tone", "base_n", "median", "ratio", "z"})
                self.assertEqual(set(result["articles"][0]), {"title", "url", "domain", "language", "country", "date"})

    def test_root_source_tracks_newest_series_row_when_latest_is_partial(self):
        days = [{**daily(f"2026-10-{day:02d}", total=100), "share": 200, "source": "gdelt-doc"}
                for day in range(1, 25)]
        days.append({**daily(total=10), "share": 2000, "source": "gdelt-gkg"})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "news.json"
            with patch.object(news, "JSON_FILE", str(output)):
                news.run(fetcher=lambda: (days, []))
            result = json.loads(output.read_text())
        self.assertEqual(result["source"], "gdelt-gkg")
        self.assertTrue(result["series"][-1]["partial"])
        self.assertEqual(result["latest"]["date"], "2026-10-24")

    def test_evaluate_matches_original_on_existing_series_and_alert_cases(self):
        # 검수 대상 원본 함수를 git에서 가져온다. 모듈 본문/main은 실행하지 않는다.
        import ast
        original = subprocess.check_output(["git", "show", "HEAD:news_monitor.py"], text=True)
        tree = ast.parse(original)
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name in ("robust_z", "evaluate")]
        namespace = {"statistics": statistics, **{name: getattr(news, name) for name in
                     ("BASE_DAYS", "MIN_BASE", "Z_WATCH", "Z_ALERT", "RATIO_ALERT")}}
        exec(compile(ast.Module(body=functions, type_ignores=[]), "original_news_monitor", "exec"), namespace)
        existing = json.loads(Path("data/news.json").read_text())["series"]
        synthetic = [{**daily((TODAY - dt.timedelta(days=30 - i)).isoformat(), total=100),
                      "share": 10 + i % 5} for i in range(30)]
        cases = [existing, synthetic, synthetic[:-1] + [{**synthetic[-1], "share": 50}],
                 synthetic[:-1] + [{**synthetic[-1], "total": 0, "share": None}],
                 [{**d, "share": 10} for d in synthetic], synthetic[:2]]
        for days in cases:
            before, after = copy.deepcopy(days), copy.deepcopy(days)
            self.assertEqual(news.evaluate(after), namespace["evaluate"](before))
            self.assertEqual(after, before)
        with self.assertRaisesRegex(RuntimeError, "일별 데이터가 비어 있음"):
            news.evaluate([])


if __name__ == "__main__":
    unittest.main()
