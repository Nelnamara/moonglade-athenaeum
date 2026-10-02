"""The Vigil chip's numbers, server side (Folio for completionists, O5).

  * vigil_status(): the run of consecutive days with a generation that ends today (or yesterday,
    while today has none yet), the best run ever, a miss simply starting again at day 1 with
    nothing said about it, and hostile input never raising.
  * /api/achievements carries `vigil: {day, best}` and opening the page writes nothing for it.

Dates are pinned with the `today` argument and a synthetic roster, so nothing here depends on
the clock and nothing asserts on a real honor.
"""
import datetime as dt

import pytest

import moonglade_gallery as g

from tests.test_achievement_progress import _client, _get

TODAY = dt.date(2026, 9, 29)


def _d(*back):
    return [(TODAY - dt.timedelta(days=n)).isoformat() for n in back]


def test_a_run_ending_today_is_its_length():
    assert g.vigil_status(_d(0, 1, 2), TODAY) == {"day": 3, "best": 3}


def test_today_with_no_generation_yet_keeps_yesterdays_run_alive():
    assert g.vigil_status(_d(1, 2, 3, 4), TODAY) == {"day": 4, "best": 4}


def test_a_miss_starts_again_at_day_one_and_best_remembers():
    v = g.vigil_status(_d(2, 3, 4, 5, 6), TODAY)          # last made the day before yesterday
    assert v == {"day": 1, "best": 5}


def test_a_gap_inside_the_history_ends_the_run_it_is_not_bridged():
    assert g.vigil_status(_d(0, 1, 3, 4, 5, 6), TODAY) == {"day": 2, "best": 4}


def test_no_history_is_day_one_and_never_zero():
    assert g.vigil_status([], TODAY) == {"day": 1, "best": 1}
    assert g.vigil_status(None, TODAY) == {"day": 1, "best": 1}


def test_best_is_never_below_the_current_day():
    v = g.vigil_status(_d(0), TODAY)
    assert v["best"] >= v["day"] == 1


def test_a_future_date_or_junk_is_skipped_not_raised():
    days = _d(0, 1) + ["2999-01-01", "not a date", None, 7, ""]
    assert g.vigil_status(days, TODAY) == {"day": 2, "best": 2}


def test_duplicates_count_once():
    assert g.vigil_status(_d(0, 0, 1, 1), TODAY) == {"day": 2, "best": 2}


def test_today_may_be_an_iso_string():
    assert g.vigil_status(_d(0, 1), TODAY.isoformat()) == {"day": 2, "best": 2}


def _set_days(tmp_path, days):
    def _put(d):
        dl = d.setdefault("day_lists", {})
        dl["gen_days"] = list(days)
    g._telem_mutate(tmp_path, _put)


def test_the_route_carries_the_vigil(tmp_path):
    cli = _client(tmp_path)
    _set_days(tmp_path, [
        (dt.date.today() - dt.timedelta(days=n)).isoformat() for n in (0, 1, 2, 5, 6, 7, 8)])
    v = _get(cli)["vigil"]
    assert v["day"] == 3 and v["best"] == 4


def test_a_fresh_library_answers_day_one(tmp_path):
    cli = _client(tmp_path)
    assert _get(cli)["vigil"] == {"day": 1, "best": 1}


def test_opening_the_route_writes_no_vigil_day(tmp_path):
    cli = _client(tmp_path)
    _set_days(tmp_path, [])
    _get(cli)
    _get(cli)
    dl = g.load_telemetry(tmp_path).get("day_lists") or {}
    assert not dl.get("gen_days")
