"""The narrator's poke ladder: moonglade_narrator.py, the pure core.

No I/O and no real clock: every test hands `poke()` the instant, so a whole simulated
fortnight runs in milliseconds. Every LINE here is synthetic ("test line one") -- the core
knows mechanics only, and the words come from the sealed pack. Nothing here needs the private
donor, so these run in public CI too.
"""
import random

import pytest

import moonglade_narrator as nar

DAY = 86400.0


def _pools(**named):
    """{pool name: [synthetic line, ...]} through the same cleaning the route applies."""
    return nar.clean_pools(named)


def _stage_pools():
    """A synthetic line pair for every stage, plus the special pools."""
    p = {name: ["test %s one" % name, "test %s two" % name] for name, _lo, _hi in nar.STAGES}
    p.update({"walk_off": ["test walk off"], "walked_off": ["test walked off"],
              "spam": ["test spam"], "daily_cap": ["test cap"], "too_soon": ["test soon"],
              "done": ["test done"], "eyeroll": ["test eyeroll"]})
    return nar.clean_pools(p)


class Clock:
    """A simulated clock: epoch seconds since 'midnight of day 0', and the local-day string
    derived from it. Nothing sleeps; the test moves it."""
    def __init__(self, at=9 * 3600.0):
        self.t = at

    def advance(self, seconds):
        self.t += seconds

    def next_day(self, at=9 * 3600.0):
        self.t = (int(self.t // DAY) + 1) * DAY + at

    @property
    def today(self):
        return "day-%d" % int(self.t // DAY)


def _poke(st, clock, pools=None, rng=None):
    return nar.poke(st, clock.t, clock.today, pools if pools is not None else {},
                    rng or random.Random(1))


# ---- the stage table ------------------------------------------------------------------------

def test_stage_table_covers_every_count_once_and_the_final_straw_is_not_a_stage():
    seen = []
    for n in range(1, nar.FINAL):
        name = nar.stage_of(n)
        assert name, "count %d falls in no stage" % n
        seen.append(name)
    assert [s[0] for s in nar.STAGES] == list(dict.fromkeys(seen)), "stages out of order"
    assert nar.stage_of(0) == "" and nar.stage_of(nar.FINAL) == ""
    # the recipe's boundaries, by name and edge
    edges = {s[0]: (s[1], s[2]) for s in nar.STAGES}
    assert edges["oblivious"] == (1, 10) and edges["irritated"] == (11, 25)
    assert edges["warning"] == (26, 40) and edges["seething"] == (41, 60)
    assert edges["threats"] == (61, 85) and edges["breaking"] == (86, nar.FINAL - 1)


# ---- pace: two seconds, then the cap, then seven minutes -------------------------------------

def test_spam_inside_two_seconds_does_not_count_but_still_answers():
    clock, st = Clock(), nar.new_state()
    st, r = _poke(st, clock, _stage_pools())
    assert r["counted"] and r["count"] == 1
    clock.advance(1.9)
    st, r = _poke(st, clock, _stage_pools())
    assert not r["counted"] and r["count"] == 1 and r["reason"] == "spam"
    assert r["line"] == "test spam", "a poke that does not count still gets its line"
    clock.advance(0.1)                          # 2.0 s since the last COUNTED one
    st, r = _poke(st, clock, _stage_pools())
    assert r["counted"] and r["count"] == 2, "the refused poke did not reset the clock"


def test_a_refused_poke_never_advances_the_count_however_often_it_repeats():
    clock, st = Clock(), nar.new_state()
    st, _ = _poke(st, clock)
    for _i in range(50):
        clock.advance(0.5)
        if clock.t - st["last_at"] >= nar.SPAM_GAP_S:
            break
        st, r = _poke(st, clock)
        assert r["count"] == 1 and not r["counted"]


def test_at_the_walk_off_she_leaves_until_tomorrow():
    clock, st, pools = Clock(), nar.new_state(), _stage_pools()
    last = None
    for i in range(nar.WALK_OFF_AT):
        st, last = _poke(st, clock, pools)
        assert last["counted"], "poke %d should count" % (i + 1)
        clock.advance(3)
    assert last["count"] == nar.WALK_OFF_AT and last["line"] == "test walk off"
    for _i in range(5):                          # later the same day: never counted
        clock.advance(3600)
        if clock.today != "day-0":
            break
        st, r = _poke(st, clock, pools)
        assert not r["counted"] and r["reason"] == "walked_off" and r["line"] == "test walked off"
    assert st["count"] == nar.WALK_OFF_AT
    clock.next_day()
    st, r = _poke(st, clock, pools)
    assert r["counted"] and r["count"] == nar.WALK_OFF_AT + 1, "she is back tomorrow"


def test_the_capped_stage_allows_three_a_day_and_the_fourth_answers_without_counting():
    clock, st, pools = Clock(), nar.new_state(), _stage_pools()
    st = dict(st, count=nar.CAP_FROM - 1)        # standing at the top of the walk-off's day
    for i in range(nar.DAILY_CAP):
        st, r = _poke(st, clock, pools)
        assert r["counted"] and r["count"] == nar.CAP_FROM + i
        clock.advance(5)
    st, r = _poke(st, clock, pools)
    assert not r["counted"] and r["reason"] == "daily_cap" and r["line"] == "test cap"
    assert r["count"] == nar.CAP_FROM + nar.DAILY_CAP - 1
    clock.next_day()
    st, r = _poke(st, clock, pools)
    assert r["counted"], "a new local day allows three more"


def test_the_slow_stages_need_seven_minutes_between_counted_pokes():
    clock, pools = Clock(), _stage_pools()
    st = dict(nar.new_state(), count=nar.SLOW_FROM - 1)
    st, r = _poke(st, clock, pools)
    assert r["counted"] and r["count"] == nar.SLOW_FROM
    clock.advance(7 * 60 - 1)
    st, r = _poke(st, clock, pools)
    assert not r["counted"] and r["reason"] == "too_soon" and r["line"] == "test soon"
    clock.advance(1)
    st, r = _poke(st, clock, pools)
    assert r["counted"] and r["count"] == nar.SLOW_FROM + 1


def test_the_daily_cap_does_not_follow_the_ladder_into_the_slow_stages():
    """From the seven-minute stage on, the pace is the only limit: a day may hold many."""
    clock, pools = Clock(), _stage_pools()
    st = dict(nar.new_state(), count=nar.SLOW_FROM - 1)
    for i in range(10):
        st, r = _poke(st, clock, pools)
        assert r["counted"], "slow-stage poke %d" % (i + 1)
        clock.advance(nar.SLOW_GAP_S)


# ---- the final straw -------------------------------------------------------------------------

def test_the_last_counted_poke_is_the_final_straw_and_carries_no_line_of_its_own():
    clock, pools = Clock(), _stage_pools()
    st = dict(nar.new_state(), count=nar.FINAL - 1, last_at=clock.t - 9999)
    st, r = _poke(st, clock, pools)
    assert r["final"] and r["counted"] and r["count"] == nar.FINAL and r["line"] == ""
    clock.advance(nar.SLOW_GAP_S)
    st, r = _poke(st, clock, pools)
    assert not r["counted"] and not r["final"] and r["reason"] == "done"
    assert r["line"] == "test done" and r["count"] == nar.FINAL, "progress never moves past it"


def test_the_final_straw_fires_exactly_once():
    clock = Clock()
    st = dict(nar.new_state(), count=nar.FINAL - 1, last_at=clock.t - 9999)
    finals = 0
    for _i in range(20):
        st, r = _poke(st, clock)
        finals += 1 if r["final"] else 0
        clock.advance(nar.SLOW_GAP_S)
    assert finals == 1


# ---- lines: pools, bounds, one-shots, repeats, the neutral fallback ---------------------------

def test_a_pack_with_no_lines_answers_a_bare_neutral_ellipsis_and_still_counts():
    clock = Clock()
    st, r = _poke(nar.new_state(), clock, {})
    assert r["counted"] and r["line"] == nar.NEUTRAL == "…"
    clock.advance(0.1)
    st, r = _poke(st, clock, {})
    assert not r["counted"] and r["line"] == nar.NEUTRAL


def test_a_stage_with_no_lines_falls_to_neutral_even_when_another_stage_has_some():
    clock = Clock()
    pools = _pools(irritated=["test irritated"])
    st, r = _poke(nar.new_state(), clock, pools)       # count 1 is the first stage
    assert r["stage"] == "oblivious" and r["line"] == nar.NEUTRAL


def test_lines_come_from_the_stage_the_count_is_in():
    pools = _stage_pools()
    for count, want in ((1, "oblivious"), (10, "oblivious"), (11, "irritated"), (25, "irritated"),
                        (26, "warning"), (39, "warning"), (41, "seething"), (60, "seething"),
                        (61, "threats"), (85, "threats"), (86, "breaking"), (99, "breaking")):
        clock = Clock()
        st = dict(nar.new_state(), count=count - 1, last_at=None)
        st, r = nar.poke(st, clock.t, clock.today, pools, random.Random(0))
        if count == nar.WALK_OFF_AT:
            continue
        # threats may roll an eyeroll; this seed's first draw is above the chance
        assert r["counted"] and r["stage"] == want and r["line"].startswith("test " + want), count


def test_never_the_same_line_twice_in_a_row():
    pools = _pools(oblivious=["test line one", "test line two", "test line three"])
    clock, st, prev = Clock(), nar.new_state(), None
    rng = random.Random(7)
    for _i in range(10):                              # stays inside the first stage
        st, r = nar.poke(st, clock.t, clock.today, pools, rng)
        assert r["counted"] and r["line"] != prev, "repeated %r" % prev
        prev = r["line"]
        clock.advance(3)


def test_a_pool_of_one_may_repeat_rather_than_go_silent():
    pools = _pools(oblivious=["test only line"])
    clock, st = Clock(), nar.new_state()
    for _i in range(3):
        st, r = _poke(st, clock, pools)
        assert r["line"] == "test only line"
        clock.advance(3)


def test_lines_are_drawn_at_random_from_the_whole_pool():
    lines = ["test line %d" % i for i in range(5)]
    pools = _pools(oblivious=lines)
    seen = set()
    for seed in range(60):
        st, r = nar.poke(nar.new_state(), 100.0, "d", pools, random.Random(seed))
        seen.add(r["line"])
    assert seen == set(lines)


def test_an_entry_can_be_bounded_to_a_run_of_counts():
    pools = _pools(breaking=[{"t": "test early", "from": 86, "to": 90},
                             {"t": "test late", "from": 91, "to": 99}])
    for count, want in ((86, "test early"), (90, "test early"), (91, "test late"),
                        (99, "test late")):
        st = dict(nar.new_state(), count=count - 1)
        _st, r = nar.poke(st, 1e6, "d", pools, random.Random(3))
        assert r["line"] == want, count


def test_a_one_shot_line_is_spoken_once_and_then_never_again():
    pools = _pools(oblivious=[{"t": "test once", "once": True}, "test plain"])
    clock, st, said = Clock(), nar.new_state(), []
    for seed in range(40):
        st, r = nar.poke(st, clock.t, clock.today, pools, random.Random(seed))
        said.append(r["line"])
        clock.advance(3)
        if st["count"] >= 10:
            break
    assert said.count("test once") <= 1
    # and it really is remembered by id, not by holding the words
    assert all(("test" not in o) for o in st["once"])


def test_the_eyeroll_pool_is_used_only_in_its_stage_and_only_now_and_then():
    pools = _stage_pools()
    in_stage, elsewhere = [], []
    for seed in range(200):
        st = dict(nar.new_state(), count=nar.SLOW_FROM)          # the poke counts as 62: threats
        _s, r = nar.poke(st, 1e6, "d", pools, random.Random(seed))
        in_stage.append(r["line"] == "test eyeroll")
        st = dict(nar.new_state(), count=20)
        _s, r = nar.poke(st, 1e6, "d", pools, random.Random(seed))
        elsewhere.append(r["line"] == "test eyeroll")
    assert 0.1 < sum(in_stage) / 200 < 0.45, "an eyeroll now and then, not always or never"
    assert not any(elsewhere)


def test_state_stores_line_ids_not_line_text():
    pools = _pools(oblivious=["test the words themselves"])
    st, _r = nar.poke(nar.new_state(), 5.0, "d", pools, random.Random(0))
    assert st["last"] == nar.line_id("test the words themselves")
    assert "words" not in repr(st)


# ---- state safety ----------------------------------------------------------------------------

def test_poke_never_mutates_the_state_it_was_given():
    st = nar.new_state()
    before = repr(st)
    nar.poke(st, 5.0, "d", _stage_pools(), random.Random(0))
    assert repr(st) == before


@pytest.mark.parametrize("junk", [None, 5, "x", [], {"count": "9"}, {"count": -3},
                                  {"count": True}, {"last_at": "now"}, {"once": "no"},
                                  {"count": 10 ** 9}])
def test_a_torn_or_hostile_state_reads_as_safe_values(junk):
    st = nar.clean_state(junk)
    assert 0 <= st["count"] <= nar.FINAL and isinstance(st["once"], list)
    nar.poke(junk, 5.0, "d", {}, random.Random(0))          # and a poke on it does not raise


def test_clean_pools_drops_what_is_not_a_well_formed_entry():
    raw = {"stages": {"oblivious": ["  test ok ", "", 5, None, {"t": 3}, {"t": "test obj"}]},
           "walk_off": "not a list", "spam": [{"t": "test spam", "from": "x", "to": True}]}
    pools = nar.clean_pools(raw)
    assert [e[0] for e in pools["oblivious"]] == ["test ok", "test obj"]
    assert "walk_off" not in pools
    assert pools["spam"][0][1:3] == (1, nar.FINAL), "a junk bound falls back to the whole range"
    assert nar.clean_pools("nope") == {} and nar.clean_pools(None) == {}


def test_a_clock_that_goes_backwards_refuses_once_and_then_recovers():
    clock, st = Clock(at=50000.0), nar.new_state()
    st, r = _poke(st, clock)
    assert r["counted"]
    clock.advance(-3600)                                   # the wall clock jumps back an hour
    st, r = _poke(st, clock)
    assert not r["counted"] and r["reason"] == "spam"
    clock.advance(3)
    st, r = _poke(st, clock)
    assert r["counted"] and r["count"] == 2, "the stored instant was re-anchored, not stuck"


def test_progress_never_resets_whatever_the_clock_does():
    rng = random.Random(11)
    st, clock, high = nar.new_state(), Clock(), 0
    for _i in range(3000):
        clock.advance(rng.choice([0.3, 1, 3, 60, 500, 4000, 90000, -20]))
        st, r = nar.poke(st, clock.t, clock.today, _stage_pools(), rng)
        assert r["count"] >= high, "the count went down"
        high = r["count"]
    assert high > 20, "the walk should have made progress"


# ---- the fastest possible path: 8 days ---------------------------------------------------------

def _play_greedily(spam_gap=3.0):
    """The fastest a person can go: poke the instant a poke would count, and only ever rest
    when told to. Returns (day reached at the final straw, {count: (day, clock seconds)},
    counted per day)."""
    clock, st, pools = Clock(), nar.new_state(), _stage_pools()
    at, per_day, day_of_final = {}, {}, None
    for _i in range(100000):
        st, r = _poke(st, clock, pools)
        if r["counted"]:
            at[r["count"]] = (int(clock.t // DAY) + 1, clock.t)
            per_day[clock.today] = per_day.get(clock.today, 0) + 1
            if r["final"]:
                day_of_final = int(clock.t // DAY) + 1
                break
            clock.advance(nar.SLOW_GAP_S if r["count"] + 1 >= nar.SLOW_FROM else spam_gap)
        elif r["reason"] in ("walked_off", "daily_cap"):
            clock.next_day()
        else:                                  # too soon / spam: wait just long enough
            clock.advance(nar.SLOW_GAP_S if r["reason"] == "too_soon" else spam_gap)
    return day_of_final, at, per_day


def test_the_fastest_possible_path_is_eight_days():
    day, at, per_day = _play_greedily()
    assert day == 8, "the fastest path is 8 days, the simulation says %r" % day
    # the recipe's own shape: the first 40 on day 1, three a day through 60, then 40 seven
    # minutes apart on day 8
    days = [per_day["day-%d" % i] for i in range(8)]
    assert days[0] == 40
    assert days[1:6] == [3] * 5
    assert days[6] == 3 and days[7] == 2 + 40, days
    assert at[nar.WALK_OFF_AT][0] == 1 and at[nar.CAP_FROM][0] == 2
    assert at[nar.CAP_TO][0] == 8 and at[nar.FINAL][0] == 8
    slow_span = at[nar.FINAL][1] - at[nar.CAP_TO][1]
    assert slow_span == (nar.FINAL - nar.CAP_TO) * nar.SLOW_GAP_S, "40 pokes, 7 minutes apart"
    assert 4 * 3600 < slow_span < 5 * 3600, "about four and a half hours on the last day"


def test_no_path_is_faster_than_eight_days():
    """Nobody can reach the final straw by day 7: by the end of day 7 the counted total is at
    most 40 + 3 x 6 = 58, whatever the pace, so poking harder changes nothing."""
    clock, st, pools = Clock(), nar.new_state(), _stage_pools()
    for day in range(7):
        for _i in range(2000):                              # hammer all day
            clock.advance(2.0)
            st, r = _poke(st, clock, pools)
            assert not r["final"]
        clock.next_day(at=0.0)
    assert st["count"] == 40 + 3 * 6


def test_a_normal_person_takes_weeks_not_days():
    """One poke every fifth day on average is a long game; a daily poker walks it slowly."""
    clock, st, days = Clock(), nar.new_state(), 0
    while st["count"] < nar.FINAL and days < 500:
        for _i in range(5):                                 # five casual pokes a day
            st, _r = _poke(st, clock, {})
            clock.advance(60)
        clock.next_day()
        days += 1
    assert st["count"] == nar.FINAL and days > 14


# ---- the choice's words -----------------------------------------------------------------------

def test_clean_choice_keeps_only_the_four_known_fields_and_only_real_strings():
    raw = {"title": " test title ", "keep": "test keep", "unleash": "", "foot": 5,
           "other": "test other", "x": "y" * 500}
    assert nar.clean_choice(raw) == {"title": "test title", "keep": "test keep"}
    assert nar.clean_choice({"title": "t" * 500})["title"] == "t" * 200
    assert nar.clean_choice(None) == {} and nar.clean_choice("nope") == {}


def test_the_choice_is_not_a_pool_of_lines():
    pools = nar.clean_pools({"choice": {"title": "test title"}, "oblivious": ["test line"]})
    assert "choice" not in pools and "oblivious" in pools
