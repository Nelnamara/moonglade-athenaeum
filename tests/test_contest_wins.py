"""Contest wins, VERIFIED (Session L, item L3).

A win counts only when PixAI's own winners list says so: the entry's artwork id is in the list,
its `entry.rank` is an INTEGER (the prize TIER), and the author is this account. An EMPTY list
is undecided, never "lost". The automatic check runs at the contest's result time and then
daily for up to 14 days; the E4 "Check" fallback verifies a pasted pixai.art link by the very
same rule and keeps the link as the receipt.

The shapes come from the read-only probe (moonglade-internal/probes/PROBE_2026-09-29_contest-
results-l3.md): one unpaged winners list; each row an artwork with a `contest.entry` of
`{rank, prizeAmount, source, submittedAt}`; a non-winner's entry has `rank: null`.

Everything here is mocked: nothing reaches PixAI, and the end-to-end tests run the real check
against the FakePixAI transport, so a write to PixAI would fail by name.
"""
import inspect
import json
import time

import pytest

import moonglade_backup as core
import moonglade_contest_wins as cw
import moonglade_gallery as g
from tests.conftest import login_client, record_own_sleeps

DAY = 86400.0
T0 = 1790000000.0                       # a result time (2026-09-21, UTC); only differences matter


def _iso(ts):
    import datetime as dt
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _placed(aid, author, tier, prize=100000, source="manual"):
    """One winners row as the live response sends it: an artwork with a `contest` block whose
    nested `entry` carries the placement."""
    return {"id": aid, "authorId": author, "authorName": "@n", "mediaId": "M" + aid,
            "contest": {"id": "c1", "slug": "s1", "title": {"en": "T"}, "tackId": "9",
                        "entry": {"rank": tier, "prizeAmount": prize, "source": source,
                                  "submittedAt": "2026-09-10T00:00:00.000Z"}}}


def _raw_winner(aid, author, entry):
    """The RAW upstream shape, for the mapper tests (entry may be malformed)."""
    return {"id": aid, "authorId": author, "contest": {"id": "c1", "slug": "s1", "entry": entry}}


@pytest.fixture(autouse=True)
def _fresh_cw_state():
    g._cw_state["board_retry_at"] = 0.0
    g._cw_state["manual"].clear()
    yield
    g._cw_state["board_retry_at"] = 0.0
    g._cw_state["manual"].clear()


def _board_row(cid, slug, result_ts, reward="", status="ended"):
    return {"id": cid, "slug": slug, "title": {"en": "Contest " + cid}, "type": "official",
            "runtimeStatus": status, "voteType": "creator_pick", "prizeAmount": 100,
            "startAt": _iso(result_ts - 20 * DAY), "endAt": _iso(result_ts - 7 * DAY),
            "resultAt": _iso(result_ts), "rewardStatus": reward}


def _register_board(pixai, rows):
    pixai.on("/contest/list", {"data": rows, "page": 1, "totalPage": 1})


def _enter(tmp_path, *keys):
    for k in keys:
        g.telem_set_add("contest_entry_keys", k, out_dir=tmp_path)


def _state(tmp_path, cid):
    return g.load_telemetry(tmp_path)["contest_results"]["checks"].get(cid)


def _wins(tmp_path):
    return g.load_telemetry(tmp_path)["contest_results"].get("wins", {})


def _assert_reads_only(pixai):
    """Every call the check made was a GET. There is no other verb on this road."""
    assert pixai.calls, "the check should have read something"
    assert {c.verb for c in pixai.calls} == {"rest_get"}
    assert all(c.path.startswith("/contest/") for c in pixai.calls)


def _winners_calls(pixai, slug):
    return [c for c in pixai.calls if c.path == "/contest/%s/winners" % slug]


# ==================================================================================== the mapper

class TestMapperKeepsTheEntry:
    def test_a_winner_keeps_rank_prize_source_and_submitted_at(self, pixai):
        pixai.on("/contest/s1/winners", [_placed("a1", "u-1", 3, 100000)])
        (row,) = core.contest_winners(pixai, "s1")
        assert row["entry"] == {"rank": 3, "prizeAmount": 100000, "source": "manual",
                                "submittedAt": "2026-09-10T00:00:00.000Z"}
        assert row["id"] == "a1" and row["authorId"] == "u-1"
        assert "contest" not in row, "the echoed contest object itself is still dropped"

    def test_a_non_winner_entry_keeps_a_null_rank(self, pixai):
        pixai.on("/contest/s1/artwork/u-test", {"data": [_raw_winner(
            "a2", "u-test", {"rank": None, "prizeAmount": 0, "source": "tack",
                             "submittedAt": "2026-09-11T00:00:00.000Z"})]})
        (row,) = core.contest_my_entries(pixai, "s1", "u-test")
        assert row["entry"]["rank"] is None and row["entry"]["source"] == "tack"
        assert row["entry"]["prizeAmount"] == 0

    def test_a_numeric_string_rank_is_not_coerced_to_an_integer(self, pixai):
        """"Is this an integer rank" is the win check's whole question."""
        pixai.on("/contest/s1/winners", [_raw_winner("a1", "u", {"rank": "1", "prizeAmount": 5}),
                                         _raw_winner("a2", "u", {"rank": True}),
                                         _raw_winner("a3", "u", {"rank": 2})])
        got = core.contest_winners(pixai, "s1")
        assert [r["entry"]["rank"] for r in got] == [None, None, 2]

    def test_a_row_without_the_block_maps_exactly_as_before(self, pixai):
        pixai.on("/contest/s1/winners", [{"id": "a1", "authorId": "u-9", "rank": 2}])
        assert core.contest_winners(pixai, "s1") == [{"id": "a1", "authorId": "u-9", "rank": 2}]

    def test_the_board_carries_the_settlement_fields(self, pixai):
        _register_board(pixai, [_board_row("c1", "s1", T0, reward="distributed")])
        (c,) = core.list_contests(pixai)
        assert c["reward_status"] == "distributed" and c["result_at"] == _iso(T0)
        _register_board(pixai, [{"id": "c2", "slug": "s2"}])
        assert core.list_contests(pixai)[0]["reward_status"] == ""

    def test_the_winners_route_uses_the_real_tier_and_prize(self, tmp_path, pixai):
        pixai.on("/contest/s1/winners", [_placed("a1", "u-x", 1, 500000),
                                         _placed("a2", "u-test", 2, 200000)])
        cli = login_client(tmp_path)
        d = cli.get("/api/contest/s1/winners").get_json()
        assert [(w["rank"], w["prize_amount"]) for w in d["winners"]] == [(1, 500000), (2, 200000)]
        assert [w["mine"] for w in d["winners"]] == [False, True]


# ============================================================================ what counts as a win

class TestVerify:
    UID = "u-me"

    def test_a_winner_is_verified_with_its_tier_and_prize(self):
        rows = [{"id": "a1", "authorId": self.UID,
                 "entry": {"rank": 2, "prizeAmount": 200000, "source": "manual"}}]
        r = cw.verify(rows, self.UID, ["a1"])
        assert r["decided"] and r["outcome"] == "won"
        assert r["wins"] == [{"artwork_id": "a1", "tier": 2, "prize": 200000, "source": "manual"}]

    def test_an_entry_that_is_not_in_a_non_empty_list_is_a_miss_not_a_win(self):
        rows = [{"id": "zz", "authorId": "someone", "entry": {"rank": 1, "prizeAmount": 1}}]
        r = cw.verify(rows, self.UID, ["a1"])
        assert r == {"decided": True, "wins": [], "outcome": "not_found", "unsettled": False}

    def test_a_non_winner_entry_with_a_null_rank_is_not_a_win(self):
        rows = [{"id": "a1", "authorId": self.UID,
                 "entry": {"rank": None, "prizeAmount": 0, "source": "tack"}}]
        r = cw.verify(rows, self.UID, ["a1"])
        assert r["wins"] == [] and r["outcome"] == "no_placement" and r["unsettled"] is True

    def test_an_empty_list_is_undecided_never_lost(self):
        r = cw.verify([], self.UID, ["a1"])
        assert r == {"decided": False, "wins": [], "outcome": "undecided", "unsettled": False}
        assert cw.verify(None, self.UID, ["a1"])["decided"] is False

    @pytest.mark.parametrize("rank", ["1", True, False, 1.0, None, "", [1]])
    def test_only_a_real_integer_rank_counts(self, rank):
        rows = [{"id": "a1", "authorId": self.UID, "entry": {"rank": rank, "prizeAmount": 9}}]
        assert cw.verify(rows, self.UID, ["a1"])["wins"] == []

    def test_a_row_with_no_entry_block_is_not_a_win(self):
        assert cw.verify([{"id": "a1", "authorId": self.UID}], self.UID, ["a1"])["wins"] == []

    def test_the_author_must_be_the_account(self):
        rows = [{"id": "a1", "authorId": "someone-else", "entry": {"rank": 1, "prizeAmount": 5}}]
        r = cw.verify(rows, self.UID, ["a1"])
        assert r["wins"] == [] and r["outcome"] == "not_yours"

    def test_only_the_named_entries_are_considered(self):
        rows = [{"id": "other", "authorId": self.UID, "entry": {"rank": 1, "prizeAmount": 5}}]
        assert cw.verify(rows, self.UID, ["a1"])["wins"] == []
        # ...and with no entry named at all, any artwork this account authored will do
        assert [w["artwork_id"] for w in cw.verify(rows, self.UID, None)["wins"]] == ["other"]

    def test_a_placed_entry_and_an_unplaced_one_in_one_contest(self):
        rows = [{"id": "a1", "authorId": self.UID, "entry": {"rank": 3, "prizeAmount": 10}},
                {"id": "a2", "authorId": self.UID, "entry": {"rank": None}}]
        r = cw.verify(rows, self.UID, ["a1", "a2"])
        assert [w["artwork_id"] for w in r["wins"]] == ["a1"] and r["unsettled"] is True


class TestWording:
    def test_a_tier_plus_the_prize_never_a_numbered_place(self):
        assert cw.tier_label(2, 200000) == "Tier 2, 200,000 credits"
        assert cw.tier_label(1, 0) == "Tier 1"
        for t in (1, 2, 3, 11):
            label = cw.tier_label(t, 100000)
            assert "place" not in label.lower()
            assert not any(label.endswith(s) or (" %d%s" % (t, s)) in label
                           for s in ("st", "nd", "rd", "th"))

    def test_a_miss_names_what_did_not_match(self):
        assert "not your entry #2061…302" in cw.message("not_found", "2061111111111111302")
        assert "hasn't published" in cw.message("undecided")
        assert "pixai.art" in cw.message("not_pixai")


# ================================================================================== the pasted link

class TestEvidence:
    def test_an_artwork_link_gives_the_artwork_id_and_is_the_receipt(self):
        p = cw.parse_evidence("https://pixai.art/en/artwork/2061111111111111302?ref=x#y")
        assert p["ok"] and p["artwork_id"] == "2061111111111111302" and p["slug"] == ""
        assert p["receipt"] == "https://pixai.art/en/artwork/2061111111111111302"

    def test_a_contest_link_gives_the_slug(self):
        p = cw.parse_evidence("https://pixai.art/en/contest/pixai-pet-humanization/artworks")
        assert p["ok"] and p["slug"] == "pixai-pet-humanization" and p["artwork_id"] == ""

    def test_the_scheme_may_be_left_off(self):
        assert cw.parse_evidence("pixai.art/contest/some-slug/results")["slug"] == "some-slug"
        assert cw.parse_evidence("www.pixai.art/artwork/12345")["artwork_id"] == "12345"

    def test_the_designs_placeholder_names_no_contest(self):
        p = cw.parse_evidence("pixai.art/contest/…/results")
        assert p["ok"] and p["slug"] == "" and p["artwork_id"] == ""

    @pytest.mark.parametrize("bad", [
        "https://evil.example/en/artwork/123",
        "https://pixai.art.evil.example/en/artwork/123",
        "https://evilpixai.art/en/artwork/123",
        "https://user:pw@pixai.art/en/artwork/123",
        "https://pixai.art:8443/en/artwork/123",
        "ftp://pixai.art/en/artwork/123",
        "javascript:alert(1)",
    ])
    def test_only_pixai_arts_own_pages_count(self, bad):
        p = cw.parse_evidence(bad)
        assert p["ok"] is False and p["reason"] == "not_pixai"

    def test_nothing_pasted(self):
        assert cw.parse_evidence("   ")["reason"] == "no_link"

    def test_a_slug_that_could_escape_the_path_is_refused(self):
        assert cw.clean_slug("../../v1/me") == "" and cw.clean_slug("a/b") == ""
        assert cw.clean_slug("pixai-pet-humanization") == "pixai-pet-humanization"
        assert cw.parse_evidence("pixai.art/contest/%2e%2e%2fme/x")["slug"] == ""


class TestPlanManual:
    ENTRIES = {"c1": ["a1", "a2"], "c2": ["a9"]}
    SLUGS = {"c1": "slug-one", "c2": "slug-two"}

    def _plan(self, parsed, cid="", slug="", **kw):
        return cw.plan_manual(parsed, cid, slug, kw.get("entries", self.ENTRIES),
                              lambda c: self.SLUGS.get(c, ""),
                              lambda s: {v: k for k, v in self.SLUGS.items()}.get(s, ""))

    def test_the_artworks_own_read_carries_no_contest_so_the_picked_contest_is_used(self):
        p = self._plan(cw.parse_evidence("pixai.art/en/artwork/a1"), cid="c1")
        assert p == {"ok": True, "cid": "c1", "slug": "slug-one", "entry_ids": ["a1"]}

    def test_without_a_pick_the_app_s_own_entry_record_names_the_contest(self):
        p = self._plan(cw.parse_evidence("pixai.art/en/artwork/a9"))
        assert p["ok"] and p["cid"] == "c2" and p["slug"] == "slug-two"

    def test_an_unrecorded_artwork_with_no_pick_needs_the_contest(self):
        p = self._plan(cw.parse_evidence("pixai.art/en/artwork/a-unknown"))
        assert p == {"ok": False, "reason": "no_contest"}

    def test_a_contest_link_alone_checks_the_recorded_entries_there(self):
        p = self._plan(cw.parse_evidence("pixai.art/en/contest/slug-one"))
        assert p["ok"] and p["cid"] == "c1" and p["entry_ids"] == ["a1", "a2"]

    def test_a_typed_slug_works_too_and_no_record_means_any_own_artwork(self):
        p = self._plan(cw.parse_evidence(""), slug="slug-two", entries={})
        assert p["ok"] and p["slug"] == "slug-two" and p["entry_ids"] is None


# ================================================================================== the schedule

class TestSchedule:
    def test_the_first_check_is_due_at_the_result_time_not_before(self):
        st = cw.new_state("s1", T0, T0 - DAY)
        assert not cw.is_due(st, T0 - 1)
        assert cw.is_due(st, T0)
        assert cw.is_due(st, T0 + 3600)

    def test_an_empty_list_is_undecided_and_the_next_check_is_a_day_later(self):
        st = cw.new_state("s1", T0, T0)
        cw.after_read(st, T0, cw.verify([], "u", ["a"]), "")
        assert st["status"] == cw.PENDING and st["decided"] is False
        assert st["next_at"] == T0 + DAY, "daily spacing"
        assert not cw.is_due(st, T0 + DAY - 1) and cw.is_due(st, T0 + DAY)

    def test_distributed_and_settled_stops_the_schedule(self):
        st = cw.new_state("s1", T0, T0)
        res = cw.verify([{"id": "a", "authorId": "u", "entry": {"rank": 1}}], "u", ["a"])
        cw.after_read(st, T0, res, "distributed")
        assert st["status"] == cw.SETTLED and not cw.is_due(st, T0 + 10 * DAY)

    def test_a_non_winning_entry_in_a_settled_contest_stops_too(self):
        st = cw.new_state("s1", T0, T0)
        res = cw.verify([{"id": "zz", "authorId": "x", "entry": {"rank": 1}}], "u", ["a"])
        cw.after_read(st, T0, res, "distributed")
        assert st["status"] == cw.SETTLED

    def test_distributed_alone_does_not_stop_it_while_the_list_is_empty(self):
        st = cw.new_state("s1", T0, T0)
        cw.after_read(st, T0, cw.verify([], "u", ["a"]), "distributed")
        assert st["status"] == cw.PENDING, "an empty list is undecided even after payout"

    def test_a_decided_list_without_a_payout_keeps_checking_daily(self):
        st = cw.new_state("s1", T0, T0)
        res = cw.verify([{"id": "a", "authorId": "u", "entry": {"rank": 1}}], "u", ["a"])
        cw.after_read(st, T0, res, "")
        assert st["status"] == cw.PENDING and st["next_at"] == T0 + DAY

    def test_an_entry_listed_without_a_rank_is_not_settled(self):
        st = cw.new_state("s1", T0, T0)
        res = cw.verify([{"id": "a", "authorId": "u", "entry": {"rank": None}}], "u", ["a"])
        cw.after_read(st, T0, res, "distributed")
        assert st["status"] == cw.PENDING

    def test_after_fourteen_days_it_stops(self):
        st = cw.new_state("s1", T0, T0)
        end = T0 + 14 * DAY
        assert cw.is_due(st, end), "the fourteenth day is still inside the window"
        assert not cw.is_due(st, end + 1)
        assert cw.effective_status(st, end + 1) == cw.EXPIRED
        # walking it a day at a time: checks happen on days 0..14, then it expires by itself
        t, n = T0, 0
        while cw.is_due(st, t):
            cw.after_read(st, t, cw.verify([], "u", ["a"]), "")
            n += 1
            t = st["next_at"]
            if st["status"] != cw.PENDING:
                break
        assert n == 15 and st["status"] == cw.EXPIRED
        assert not cw.is_due(st, T0 + 30 * DAY)

    def test_a_failed_read_waits_an_hour_and_is_not_retried_in_a_loop(self):
        st = cw.new_state("s1", T0, T0)
        cw.after_error(st, T0)
        assert st["next_at"] == T0 + 3600 and st["errors"] == 1 and st["status"] == cw.PENDING
        assert not cw.is_due(st, T0 + 3599)

    def test_a_contest_already_past_its_window_is_born_expired(self):
        assert cw.new_state("s", T0 - 20 * DAY, T0)["status"] == cw.EXPIRED

    def test_an_unknown_result_time_uses_first_sight(self):
        st = cw.new_state("s", None, T0)
        assert st["anchor"] == T0 and cw.is_due(st, T0)

    def test_a_moved_result_time_is_followed_until_the_first_check(self):
        st = cw.new_state("s", T0, T0 - DAY)
        assert cw.refresh_state(st, T0 + 2 * DAY, "s", T0 - DAY)
        assert st["anchor"] == T0 + 2 * DAY and not cw.is_due(st, T0)
        st["checks"] = 1
        assert not cw.refresh_state(st, T0 + 5 * DAY, "s", T0)
        assert st["anchor"] == T0 + 2 * DAY

    def test_the_plan_seeds_new_contests_and_finds_the_due_ones(self):
        entries = {"c1": ["a"], "c2": ["b"], "c3": ["c"]}
        checks = {"c2": cw.new_state("s2", T0, T0), "c3": cw.new_state("s3", T0 + DAY, T0)}
        plan = cw.plan_pass(entries, [], {}, checks, T0)
        assert plan == {"seed": ["c1"], "legacy": [], "due": ["c2"]}

    def test_nothing_entered_and_nothing_recorded_means_nothing_to_do(self):
        assert cw.plan_pass({}, [], {}, {}, T0) == {"seed": [], "legacy": [], "due": []}


# ================================================================ the record and the metric's rule

class TestTheRecord:
    def test_verified_count_counts_contests_that_hold_a_verified_win(self):
        wins = {}
        assert cw.record_win(wins, "c1", {"artwork_id": "a", "tier": 1, "prize": 5}, "auto", T0)
        assert cw.record_win(wins, "c1", {"artwork_id": "b", "tier": 2, "prize": 5}, "auto", T0)
        assert cw.record_win(wins, "c2", {"artwork_id": "c", "tier": 3, "prize": 5}, "check", T0)
        assert cw.verified_count(wins) == 2
        assert cw.verified_count(None) == 0 and cw.verified_count({"c": {}}) == 0

    def test_a_recorded_win_is_never_replaced_but_can_gain_a_receipt(self):
        wins = {}
        cw.record_win(wins, "c1", {"artwork_id": "a", "tier": 1, "prize": 5}, "auto", T0)
        assert not cw.record_win(wins, "c1", {"artwork_id": "a", "tier": 3, "prize": 1},
                                 "check", T0 + 1, "https://pixai.art/en/artwork/a")
        (w,) = cw.wins_for(wins, "c1")
        assert w["tier"] == 1 and w["how"] == "auto"
        assert w["receipt_url"] == "https://pixai.art/en/artwork/a"


# ========================================================= the automatic check, end to end (mocked)

def _setup_contest(tmp_path, pixai, winners, *, reward="", entered=("c1:aw1",), result_ts=T0,
                   slug="s1", cid="c1"):
    _register_board(pixai, [_board_row(cid, slug, result_ts, reward=reward)])
    pixai.on("/contest/%s/winners" % slug, winners)
    _enter(tmp_path, *entered)


class TestTheAutomaticCheck:
    def test_a_winner_is_recorded_with_its_tier_and_prize_and_counts(self, tmp_path, pixai):
        _setup_contest(tmp_path, pixai, [_placed("aw1", "u-test", 2, 200000)], reward="distributed")
        out = g.contest_win_pass(tmp_path, now=T0 + 60, pause=0)
        assert out["checked"] == ["c1"] and out["recorded"] == 1
        (w,) = cw.wins_for(_wins(tmp_path), "c1")
        assert (w["tier"], w["prize_amount"], w["how"]) == (2, 200000, "auto")
        assert w["receipt_url"] == "https://pixai.art/en/artwork/aw1"
        assert g.telemetry_metrics(tmp_path)["contest_wins"] == 1
        assert _state(tmp_path, "c1")["status"] == cw.SETTLED
        _assert_reads_only(pixai)

    def test_a_non_winner_records_nothing_and_settles_once_paid(self, tmp_path, pixai):
        _setup_contest(tmp_path, pixai, [_placed("someone-else", "u-x", 1)], reward="distributed")
        out = g.contest_win_pass(tmp_path, now=T0 + 60, pause=0)
        assert out["recorded"] == 0 and _wins(tmp_path) == {}
        assert g.telemetry_metrics(tmp_path)["contest_wins"] == 0
        assert _state(tmp_path, "c1")["status"] == cw.SETTLED and _state(tmp_path, "c1")["decided"]

    def test_the_authors_must_be_the_accounts_even_when_the_id_and_tier_match(self, tmp_path, pixai):
        _setup_contest(tmp_path, pixai, [_placed("aw1", "another-account", 1, 500000)])
        g.contest_win_pass(tmp_path, now=T0 + 60, pause=0)
        assert _wins(tmp_path) == {} and g.telemetry_metrics(tmp_path)["contest_wins"] == 0

    def test_an_empty_list_is_undecided_and_the_next_check_is_a_day_away(self, tmp_path, pixai):
        _setup_contest(tmp_path, pixai, [], reward="")
        g.contest_win_pass(tmp_path, now=T0 + 60, pause=0)
        st = _state(tmp_path, "c1")
        assert st["status"] == cw.PENDING and st["decided"] is False and _wins(tmp_path) == {}
        assert st["next_at"] == T0 + 60 + DAY
        n = len(_winners_calls(pixai, "s1"))
        g.contest_win_pass(tmp_path, now=T0 + 60 + DAY / 2, pause=0)
        assert len(_winners_calls(pixai, "s1")) == n, "not due yet: no read at all"
        g.contest_win_pass(tmp_path, now=T0 + 60 + DAY, pause=0)
        assert len(_winners_calls(pixai, "s1")) == n + 1, "due a day later: one read"

    def test_nothing_is_read_before_the_result_time(self, tmp_path, pixai):
        _setup_contest(tmp_path, pixai, [], result_ts=T0 + 5 * DAY)
        g.contest_win_pass(tmp_path, now=T0, pause=0)          # seeds from the board; no winners GET
        assert _winners_calls(pixai, "s1") == []
        assert _state(tmp_path, "c1")["next_at"] == T0 + 5 * DAY

    def test_a_win_that_lands_on_a_later_day_is_caught(self, tmp_path, pixai):
        _setup_contest(tmp_path, pixai, [])
        g.contest_win_pass(tmp_path, now=T0 + 10, pause=0)
        assert g.telemetry_metrics(tmp_path)["contest_wins"] == 0
        pixai.on("/contest/s1/winners", [_placed("aw1", "u-test", 3, 100000)])
        g.contest_win_pass(tmp_path, now=T0 + 10 + DAY, pause=0)
        assert g.telemetry_metrics(tmp_path)["contest_wins"] == 1

    def test_rewardstatus_distributed_stops_the_schedule_early(self, tmp_path, pixai):
        _setup_contest(tmp_path, pixai, [_placed("aw1", "u-test", 1, 5)], reward="")
        g.contest_win_pass(tmp_path, now=T0 + 10, pause=0)
        assert _state(tmp_path, "c1")["status"] == cw.PENDING      # decided but not paid yet
        g._contests_cache.clear()
        _register_board(pixai, [_board_row("c1", "s1", T0, reward="distributed")])
        g.contest_win_pass(tmp_path, now=T0 + 10 + DAY, pause=0)
        assert _state(tmp_path, "c1")["status"] == cw.SETTLED
        n = len(_winners_calls(pixai, "s1"))
        g.contest_win_pass(tmp_path, now=T0 + 10 + 3 * DAY, pause=0)
        assert len(_winners_calls(pixai, "s1")) == n, "settled: never read again"

    def test_after_fourteen_days_it_gives_up(self, tmp_path, pixai):
        _setup_contest(tmp_path, pixai, [])
        for day in range(0, 20):
            g._contests_cache.clear()
            g.contest_win_pass(tmp_path, now=T0 + day * DAY, pause=0)
        st = _state(tmp_path, "c1")
        assert st["status"] == cw.EXPIRED
        assert len(_winners_calls(pixai, "s1")) == 15,             "one read at the result time, then daily through day 14: never more"
        before = len(pixai.calls)
        g.contest_win_pass(tmp_path, now=T0 + 40 * DAY, pause=0)
        assert len(pixai.calls) == before, "expired: no network at all"

    def test_one_read_per_contest_per_pass_and_the_contests_are_spaced(self, tmp_path, pixai,
                                                                       monkeypatch):
        _register_board(pixai, [_board_row("c1", "s1", T0), _board_row("c2", "s2", T0),
                                _board_row("c3", "s3", T0)])
        for s in ("s1", "s2", "s3"):
            pixai.on("/contest/%s/winners" % s, [])
        _enter(tmp_path, "c1:a1", "c2:a2", "c3:a3")
        naps = record_own_sleeps(monkeypatch)       # never another thread's sleep
        out = g.contest_win_pass(tmp_path, now=T0 + 5)
        assert sorted(out["checked"]) == ["c1", "c2", "c3"]
        assert [len(_winners_calls(pixai, s)) for s in ("s1", "s2", "s3")] == [1, 1, 1]
        assert len(pixai.calls_for("/contest/list")) == 1, "the board is read once"
        assert naps == [g._CW_PAUSE, g._CW_PAUSE] and g._CW_PAUSE > 0
        _assert_reads_only(pixai)

    def test_a_failed_read_is_fail_soft_pushed_an_hour_out_and_not_retried(self, tmp_path, pixai):
        _register_board(pixai, [_board_row("c1", "s1", T0), _board_row("c2", "s2", T0)])
        pixai.fail("/contest/s1/winners", core.PixAIError("REST GET /contest -> 503"))
        pixai.on("/contest/s2/winners", [_placed("aw2", "u-test", 1, 9)])
        _enter(tmp_path, "c1:aw1", "c2:aw2")
        out = g.contest_win_pass(tmp_path, now=T0 + 5, pause=0)
        assert out["errors"] == 1 and out["checked"] == ["c2"], "one bad contest, not the pass"
        assert len(_winners_calls(pixai, "s1")) == 1, "no retry loop"
        assert _state(tmp_path, "c1")["next_at"] == T0 + 5 + 3600
        assert g.telemetry_metrics(tmp_path)["contest_wins"] == 1
        g.contest_win_pass(tmp_path, now=T0 + 5 + 60, pause=0)
        assert len(_winners_calls(pixai, "s1")) == 1, "not due for an hour"

    def test_a_board_failure_is_fail_soft_and_backs_off(self, tmp_path, pixai):
        pixai.fail("/contest/list", core.PixAIError("board down"))
        _enter(tmp_path, "c1:aw1")
        out = g.contest_win_pass(tmp_path, now=T0, pause=0)
        assert out["checked"] == [] and g._cw_state["board_retry_at"] > T0
        assert g.contest_win_due(tmp_path, now=T0 + 60) is False, "not re-asked for a while"
        assert len(pixai.calls_for("/contest/list")) == 1

    def test_no_entry_means_no_check(self, tmp_path, pixai):
        out = g.contest_win_pass(tmp_path, now=T0, pause=0)
        assert out["ran"] is False and pixai.calls == []
        assert g.contest_win_due(tmp_path, now=T0) is False

    def test_a_bad_row_in_the_list_does_not_break_the_check(self, tmp_path, pixai):
        _setup_contest(tmp_path, pixai, ["junk", None, 7, {"id": "aw1", "authorId": "u-test",
                                                            "entry": "nope"}])
        g.contest_win_pass(tmp_path, now=T0 + 5, pause=0)
        assert g.telemetry_metrics(tmp_path)["contest_wins"] == 0

    def test_it_never_writes_to_pixai_and_the_pass_source_has_no_write_verb(self):
        src = inspect.getsource(g.contest_win_pass) + inspect.getsource(g.contest_win_check)
        for banned in ("_rest_post", "_rest_put", "_rest_patch", "gql_mutate", "gql_adhoc",
                       "contest_enter", "rest_post", "mutate("):
            assert banned not in src, banned


# ================================================ what already-recorded wins do (the migration)

class TestAlreadyRecordedWins:
    def _legacy(self, tmp_path, *cids):
        for c in cids:
            g.telem_set_add("contest_win_keys", c, out_dir=tmp_path)

    def test_they_stay_recorded_but_do_not_count_until_verified(self, tmp_path):
        self._legacy(tmp_path, "c1", "c2")
        assert g.telemetry_metrics(tmp_path)["contest_wins"] == 0
        assert g.load_telemetry(tmp_path)["sets"]["contest_win_keys"] == ["c1", "c2"], "kept"

    def test_a_check_verifies_one_after_the_fact_and_it_then_counts(self, tmp_path, pixai):
        self._legacy(tmp_path, "c1")
        _setup_contest(tmp_path, pixai, [_placed("aw1", "u-test", 2, 200000)],
                       result_ts=T0 - 40 * DAY)            # long past the 14 days: still re-checked once
        g.contest_win_pass(tmp_path, now=T0, pause=0)
        assert g.telemetry_metrics(tmp_path)["contest_wins"] == 1
        assert g.load_telemetry(tmp_path)["sets"]["contest_win_keys"] == ["c1"], "still kept"
        assert _state(tmp_path, "c1")["legacy"] is True

    def test_one_the_list_does_not_confirm_stays_unverified(self, tmp_path, pixai):
        self._legacy(tmp_path, "c1")
        _setup_contest(tmp_path, pixai, [_placed("someone-else", "u-x", 1)],
                       result_ts=T0 - 40 * DAY)
        g.contest_win_pass(tmp_path, now=T0, pause=0)
        assert g.telemetry_metrics(tmp_path)["contest_wins"] == 0
        cli = login_client(tmp_path)
        row = cli.get("/api/contest/mine").get_json()["contests"][0]
        assert row["won"] is False and row["unverified_legacy"] is True

    def test_the_relook_has_its_own_fourteen_days_and_then_stops(self, tmp_path, pixai):
        self._legacy(tmp_path, "c1")
        _setup_contest(tmp_path, pixai, [], result_ts=T0 - 40 * DAY)
        for day in range(0, 20):
            g._contests_cache.clear()
            g.contest_win_pass(tmp_path, now=T0 + day * DAY, pause=0)
        assert _state(tmp_path, "c1")["status"] == cw.EXPIRED
        assert len(_winners_calls(pixai, "s1")) == 15, "the first look, then daily through day 14"

    def test_a_legacy_win_with_no_entry_record_is_still_re_verified_by_author(self, tmp_path, pixai):
        self._legacy(tmp_path, "c1")
        _register_board(pixai, [_board_row("c1", "s1", T0 - 40 * DAY)])
        pixai.on("/contest/s1/winners", [_placed("aw1", "u-test", 1, 5)])
        g.contest_win_pass(tmp_path, now=T0, pause=0)
        assert g.telemetry_metrics(tmp_path)["contest_wins"] == 1

    def test_an_already_verified_win_is_untouched_by_the_legacy_set(self, tmp_path, pixai):
        g._cw_edit(tmp_path, lambda w, ch: cw.record_win(
            w, "c1", {"artwork_id": "aw1", "tier": 1, "prize": 1}, "auto", T0))
        self._legacy(tmp_path, "c1")
        _setup_contest(tmp_path, pixai, [_placed("aw1", "u-test", 1, 1)], result_ts=T0 - 40 * DAY)
        assert g.telemetry_metrics(tmp_path)["contest_wins"] == 1
        g.contest_win_pass(tmp_path, now=T0, pause=0)
        assert _winners_calls(pixai, "s1") == [], "a verified contest is not re-verified as legacy"
        assert g.telemetry_metrics(tmp_path)["contest_wins"] == 1


# ============================================================================ the tick and the kick

class TestTheHeartbeat:
    def test_it_rides_the_schedulers_own_tick_and_adds_no_thread_of_its_own(self):
        src = inspect.getsource(g.create_app)
        loop = src[src.index("def _scheduler_loop():"):]
        body = loop[:loop.index("threading.Thread(target=_scheduler_loop")]
        assert "\n            _contest_win_tick()" in body
        assert body.index("_contest_win_tick()") < body.index("            try:")
        assert body.count("threading.Thread") == 0 and "threading.Timer" not in body
        tick = src[src.index("def _contest_win_tick():"):]
        tick = tick[:tick.index("def ", 40)]
        assert "if not _bg_release_check:" in tick and "contest_win_kick(out_dir)" in tick

    def test_the_tick_is_local_when_nothing_is_due(self, tmp_path, pixai):
        assert g.contest_win_kick(tmp_path) is False and pixai.calls == []

    def test_a_due_contest_starts_one_pass_off_thread_and_single_flight(self, tmp_path, pixai,
                                                                        monkeypatch):
        _setup_contest(tmp_path, pixai, [_placed("aw1", "u-test", 1, 5)])
        started = []

        class _T:
            def __init__(self, target=None, daemon=None, **kw):
                started.append(target)

            def start(self):
                pass
        monkeypatch.setattr(g.threading, "Thread", _T)
        assert g.contest_win_kick(tmp_path, now=T0 + 5) is True
        assert len(started) == 1
        assert g.contest_win_kick(tmp_path, now=T0 + 5) is False, "a pass is already in flight"
        g._cw_lock.release()

    def test_importing_and_opening_the_app_read_nothing(self, tmp_path, pixai):
        """create_app() under the suite's gate starts no thread that reaches PixAI, and the
        My-entries read is local: no winners request from opening a page."""
        _enter(tmp_path, "c1:aw1")
        _register_board(pixai, [_board_row("c1", "s1", T0)])
        cli = login_client(tmp_path)
        cli.get("/api/contest/mine")
        assert _winners_calls(pixai, "s1") == []


# =================================================================================== the Check button

def _csrf(cli):
    return cli.get("/api/myart/items").get_json()["csrf"]


def _check(cli, **body):
    body.setdefault("csrf", _csrf(cli))
    return cli.post("/api/contest/check", json=body)


class TestTheCheckButton:
    def test_it_requires_the_csrf_token(self, tmp_path, pixai):
        cli = login_client(tmp_path)
        r = cli.post("/api/contest/check", json={"url": "pixai.art/en/artwork/1"})
        assert r.status_code == 400 and "session expired" in r.get_json()["error"]
        r = cli.post("/api/contest/check", json={"url": "pixai.art/en/artwork/1", "csrf": "nope"})
        assert r.status_code == 400
        assert pixai.calls == [], "refused before anything was read"

    def test_a_matched_entry_is_verified_and_the_link_is_kept_as_the_receipt(self, tmp_path, pixai):
        _setup_contest(tmp_path, pixai, [_placed("2061111111111111302", "u-test", 2, 200000)],
                       entered=("c1:2061111111111111302",))
        cli = login_client(tmp_path)
        d = _check(cli, url="https://pixai.art/en/artwork/2061111111111111302?utm=1",
                   contest_id="c1").get_json()
        assert d["verified"] is True and d["state"] == "verified"
        assert d["wins"] == [{"artwork_id": "2061111111111111302", "tier": 2,
                              "prize_amount": 200000, "label": "Tier 2, 200,000 credits"}]
        assert d["receipt_url"] == "https://pixai.art/en/artwork/2061111111111111302"
        (w,) = cw.wins_for(_wins(tmp_path), "c1")
        assert w["how"] == "check" and w["receipt_url"] == d["receipt_url"]
        assert g.telemetry_metrics(tmp_path)["contest_wins"] == 1
        assert len(_winners_calls(pixai, "s1")) == 1, "one GET"
        _assert_reads_only(pixai)

    def test_the_artwork_link_alone_is_enough_when_the_app_recorded_the_entry(self, tmp_path, pixai):
        """The app's own artwork read carries no contest slug, so the contest comes from the
        entry the app recorded for that artwork."""
        _setup_contest(tmp_path, pixai, [_placed("aw1", "u-test", 3, 100000)])
        cli = login_client(tmp_path)
        d = _check(cli, url="pixai.art/en/artwork/aw1".replace("aw1", "555")).get_json()
        assert d["state"] == "no_contest", "an artwork we never recorded says nothing of its contest"
        assert _winners_calls(pixai, "s1") == []
        _enter(tmp_path, "c1:555")
        pixai.on("/contest/s1/winners", [_placed("555", "u-test", 3, 100000)])
        d = _check(cli, url="pixai.art/en/artwork/555").get_json()
        assert d["verified"] is True and d["slug"] == "s1"

    def test_a_contest_link_or_slug_stands_in_when_the_artwork_read_has_no_slug(self, tmp_path, pixai):
        _setup_contest(tmp_path, pixai, [_placed("aw1", "u-test", 1, 500000)])
        cli = login_client(tmp_path)
        d = _check(cli, url="https://pixai.art/en/contest/s1/artworks").get_json()
        assert d["verified"] is True and d["wins"][0]["label"] == "Tier 1, 500,000 credits"
        assert d["receipt_url"] == "https://pixai.art/en/contest/s1/artworks"

    def test_a_typed_slug_with_an_artwork_link_works_for_an_entry_made_off_the_app(self, tmp_path, pixai):
        _register_board(pixai, [_board_row("c1", "s1", T0)])
        pixai.on("/contest/s1/winners", [_placed("777", "u-test", 2, 200000)])
        cli = login_client(tmp_path)
        d = _check(cli, url="pixai.art/en/artwork/777", slug="s1").get_json()
        assert d["verified"] is True

    def test_an_entry_not_among_the_winners_is_not_verified_and_says_why(self, tmp_path, pixai):
        _setup_contest(tmp_path, pixai, [_placed("other", "u-x", 1)], entered=("c1:2061111111111111302",))
        cli = login_client(tmp_path)
        d = _check(cli, url="pixai.art/en/artwork/2061111111111111302", contest_id="c1").get_json()
        assert d["verified"] is False and d["state"] == "not_found"
        assert "not your entry #2061…302" in d["message"] and "right contest" in d["message"]
        assert _wins(tmp_path) == {} and g.telemetry_metrics(tmp_path)["contest_wins"] == 0

    def test_an_empty_list_reads_as_not_published_yet_never_lost(self, tmp_path, pixai):
        _setup_contest(tmp_path, pixai, [], entered=("c1:9",))
        cli = login_client(tmp_path)
        d = _check(cli, url="pixai.art/en/artwork/9", contest_id="c1").get_json()
        assert d["verified"] is False and d["state"] == "undecided"
        assert "lost" not in d["message"].lower() and "re-checks daily" in d["message"]

    def test_a_listed_entry_without_an_integer_rank_is_no_placement(self, tmp_path, pixai):
        row = _placed("9", "u-test", None)
        _setup_contest(tmp_path, pixai, [row], entered=("c1:9",))
        cli = login_client(tmp_path)
        d = _check(cli, url="pixai.art/en/artwork/9", contest_id="c1").get_json()
        assert d["state"] == "no_placement" and _wins(tmp_path) == {}

    def test_someone_elses_winning_artwork_is_not_yours(self, tmp_path, pixai):
        _setup_contest(tmp_path, pixai, [_placed("9", "u-other", 1)], entered=())
        cli = login_client(tmp_path)
        d = _check(cli, url="pixai.art/en/artwork/9", slug="s1").get_json()
        assert d["state"] == "not_yours" and _wins(tmp_path) == {}

    @pytest.mark.parametrize("bad", ["https://evil.example/en/artwork/9",
                                     "https://pixai.art.evil.example/en/artwork/9"])
    def test_a_page_that_is_not_pixais_is_refused_before_any_read(self, tmp_path, pixai, bad):
        cli = login_client(tmp_path)
        d = _check(cli, url=bad, slug="s1").get_json()
        assert d["state"] == "not_pixai" and d["verified"] is False
        assert pixai.calls == []

    def test_nothing_pasted_and_nothing_picked_reads_nothing(self, tmp_path, pixai):
        cli = login_client(tmp_path)
        assert _check(cli, url="").get_json()["state"] == "no_link"
        assert pixai.calls == []

    def test_a_slug_is_shape_checked_before_it_becomes_a_path(self, tmp_path, pixai):
        cli = login_client(tmp_path)
        d = _check(cli, url="pixai.art/en/artwork/9", slug="../../v1/me").get_json()
        assert d["state"] == "no_contest"
        assert pixai.calls == []

    def test_a_failed_read_says_so_and_records_nothing(self, tmp_path, pixai):
        _register_board(pixai, [_board_row("c1", "s1", T0)])
        pixai.fail("/contest/s1/winners", core.PixAIError("REST GET /contest -> 500"))
        _enter(tmp_path, "c1:9")
        cli = login_client(tmp_path)
        d = _check(cli, url="pixai.art/en/artwork/9", contest_id="c1").get_json()
        assert d["state"] == "failed" and d["verified"] is False and _wins(tmp_path) == {}

    def test_pressing_twice_does_not_hammer_the_contest(self, tmp_path, pixai):
        _setup_contest(tmp_path, pixai, [], entered=("c1:9",))
        cli = login_client(tmp_path)
        _check(cli, url="pixai.art/en/artwork/9", contest_id="c1")
        d = _check(cli, url="pixai.art/en/artwork/9", contest_id="c1").get_json()
        assert d["state"] == "cooldown"
        assert len(_winners_calls(pixai, "s1")) == 1

    def test_a_check_after_the_fact_settles_the_schedule_it_belongs_to(self, tmp_path, pixai):
        # The Check route runs on the real clock, so the contest's result time is set a day
        # before now: a fixed T0 put the seeding read's next check past the 14-day window
        # once the real date came within a day of it (2026-10-04), and the row expired.
        _setup_contest(tmp_path, pixai, [], reward="distributed", entered=("c1:9",),
                       result_ts=time.time() - DAY)
        g.contest_win_pass(tmp_path, now=time.time() - 5, pause=0)    # seeds the row, empty list
        pixai.on("/contest/s1/winners", [_placed("9", "u-test", 1, 5)])
        cli = login_client(tmp_path)
        d = _check(cli, url="pixai.art/en/artwork/9", contest_id="c1").get_json()
        assert d["verified"] is True
        assert _state(tmp_path, "c1")["status"] == cw.SETTLED

    def test_it_never_writes_to_pixai_whatever_the_outcome(self, tmp_path, pixai):
        _setup_contest(tmp_path, pixai, [_placed("9", "u-test", 1, 5)], entered=("c1:9",))
        cli = login_client(tmp_path)
        _check(cli, url="pixai.art/en/artwork/9", contest_id="c1")
        _assert_reads_only(pixai)


# ==================================================== the payload the My-entries rows are drawn from

class TestTheMyEntriesPayload:
    def test_a_verified_win_carries_tier_prize_receipt_and_the_check_state(self, tmp_path, pixai):
        _setup_contest(tmp_path, pixai, [_placed("aw1", "u-test", 2, 200000)], reward="distributed")
        g.contest_win_pass(tmp_path, now=T0 + 60, pause=0)
        cli = login_client(tmp_path)
        (row,) = cli.get("/api/contest/mine").get_json()["contests"]
        assert row["won"] is True and row["unverified_legacy"] is False
        assert row["wins"][0]["label"] == "Tier 2, 200,000 credits"
        assert row["wins"][0]["receipt_url"] == "https://pixai.art/en/artwork/aw1"
        assert row["check"]["state"] == "settled"

    def test_a_pending_contest_reports_when_it_is_next_checked_and_when_it_stops(self, tmp_path, pixai):
        _setup_contest(tmp_path, pixai, [])
        g.contest_win_pass(tmp_path, now=T0 + 60, pause=0)
        (row,) = login_client(tmp_path).get("/api/contest/mine").get_json()["contests"]
        assert row["won"] is False
        assert row["check"] == {"state": "pending", "last_at": T0 + 60, "next_at": T0 + 60 + DAY,
                                "until": T0 + 14 * DAY, "decided": False}

    def test_a_contest_the_check_has_not_met_yet_says_none(self, tmp_path, pixai):
        _enter(tmp_path, "c1:aw1")
        _register_board(pixai, [_board_row("c1", "s1", T0)])
        (row,) = login_client(tmp_path).get("/api/contest/mine").get_json()["contests"]
        assert row["check"]["state"] == "none"

    def test_the_metric_name_never_appears_in_the_payload(self, tmp_path, pixai):
        _setup_contest(tmp_path, pixai, [_placed("aw1", "u-test", 2, 200000)])
        g.contest_win_pass(tmp_path, now=T0 + 60, pause=0)
        cli = login_client(tmp_path)
        for payload in (cli.get("/api/contest/mine").get_json(),
                        _check(cli, url="pixai.art/en/artwork/aw1", contest_id="c1").get_json()):
            assert "contest_wins" not in json.dumps(payload)


# ===================================================================== the app's own artwork read

def test_the_apps_own_artwork_reads_do_not_carry_the_contest_slug():
    """Why the Check fallback also accepts a contest link or slug: neither of the app's artwork
    reads carries `contest.slug`. The published-artwork list node feeds extract_artwork_meta,
    which keeps a fixed set of fields; the live-view read asks for `views` alone."""
    node = {"id": "1", "mediaId": "m", "title": "t", "visibility": "PUBLIC",
            "contest": {"id": "c1", "slug": "s1", "entry": {"rank": 1}}}
    meta = core.extract_artwork_meta(node)
    assert "contest" not in json.dumps(meta) and "s1" not in json.dumps(meta)
    assert "slug" not in meta
    src = inspect.getsource(core.artwork_views)
    assert "artwork(id:$id){ views }" in src.replace("\n", " ")
