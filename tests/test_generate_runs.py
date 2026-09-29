"""Session M (Generate power tools): the run road -- every send of more than one generation.

What is pinned here, all with the network mocked (no PixAI call of any kind, not even a GET):

* the template expander against the shared vectors (tests/fixtures/template_vectors.json, the
  same file loom/test/template-core.test.js reads), every refusal in its own words;
* /api/generate/plan: CSRF, writes nothing, the confirm's numbers (review F1: `count` is
  images, `jobs` is tasks, total = each x (jobs - covered)), the free cards per mode, a matrix
  never card-checked;
* /api/generate/run's guard order: CSRF, READ_ONLY before ANY PixAI call, local refusals
  (a 25-cell matrix refused whatever the client claims), the acknowledgement against a fresh
  quote (any field, a changed list, a changed negative), the sends (cell order, resolved
  prompts and seeds, matrix cells without a card), the first failure stopping the rest,
  nothing resent, idempotency and the one-run-in-flight lock;
* the Runs store: written only by the run, served only to its own account, read back after a
  lost answer (F4), a job left mid-send never read as not sent (F5);
* the two spend helpers' new hooks (before_send, on_send, exact) and Copy as CLI's real
  command, parsed by the CLI's own argparse and rebuilt by its own _gen_parameters.

Design and the adversarial review this answers:
moonglade-internal/design/notes/generate-power-tools/BUILD-w5-m.md.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import uuid

import pytest
import requests

import moonglade_backup as core
import moonglade_gallery
import moonglade_recipes
import moonglade_runs as runs
from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_client, login_test_client

HERE = os.path.dirname(os.path.abspath(__file__))
VECTORS = json.load(open(os.path.join(HERE, "fixtures", "template_vectors.json"), encoding="utf-8"))

BASE = {"version_id": "V1", "model_id": "", "prompt": "a moonlit glade", "negative": "lowres",
        "width": 1024, "height": 1024, "mode": "auto", "steps": 25, "cfg": 7, "seed": None,
        "high_priority": False, "prompt_helper": True, "loras": []}


# ---------------------------------------------------------------------------------------
# The rig: every PixAI-facing function counted, none reachable
# ---------------------------------------------------------------------------------------

class Rig(object):
    def __init__(self):
        self.calls = []
        self.mutations = []
        self.price = 1600
        self.cards = []            # match_kaisuuken answers, in order; exhausted -> None
        self.card_default = None
        self.on_mutate = None      # (index, params) -> raise or return an id

    def count(self, name):
        return sum(1 for c in self.calls if c == name)

    @property
    def network(self):
        return len(self.calls) + len(self.mutations)


@pytest.fixture
def rig(monkeypatch):
    r = Rig()

    def rest_get(*a, **k):
        r.calls.append("rest_get")
        raise core.PixAIError("live /v2 REST blocked in tests")

    def rest_post(*a, **k):
        r.calls.append("rest_post")
        raise core.PixAIError("live /v2 REST blocked in tests")

    def account_info(*a, **k):
        r.calls.append("account_info")
        return {}

    def price_task(session, params):
        r.calls.append("price_task")
        return r.price

    def match(session, params, enrich=False, raise_on_error=False, **k):
        r.calls.append("match_kaisuuken")
        if r.cards:
            got = r.cards.pop(0)
        else:
            got = r.card_default
        if isinstance(got, Exception):
            raise got
        return dict(got) if got else None

    def gql_mutate(session, document, variables=None):
        params = dict((variables or {}).get("parameters") or {})
        r.mutations.append(params)
        if r.on_mutate is not None:
            got = r.on_mutate(len(r.mutations) - 1, params)
            if got is not None:
                return {"createGenerationTask": {"id": got}}
        return {"createGenerationTask": {"id": str(9000 + len(r.mutations))}}

    def gql_adhoc(*a, **k):
        r.calls.append("gql_adhoc")
        raise core.PixAIError("no ad-hoc GraphQL in these tests")

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_rest_get", rest_get)
    monkeypatch.setattr(core, "_rest_post", rest_post)
    monkeypatch.setattr(core, "account_info", account_info)
    monkeypatch.setattr(core, "price_task", price_task)
    monkeypatch.setattr(core, "match_kaisuuken", match)
    monkeypatch.setattr(core, "gql_mutate", gql_mutate)
    monkeypatch.setattr(core, "gql_adhoc", gql_adhoc)
    monkeypatch.setattr(core, "_bump_card_use", lambda params: None)
    monkeypatch.setattr(core, "RUN_SEND_GAP_S", 0)
    monkeypatch.setattr(core, "READ_ONLY", False)
    monkeypatch.setattr(core, "_read_only_now", lambda: False)
    monkeypatch.setattr(moonglade_recipes, "batch", lambda s, ids: (_ for _ in ()).throw(
        AssertionError("recipe lookup not expected")))
    return r


def _csrf(cli):
    return cli.get("/api/account/prefs").get_json()["csrf"]


@pytest.fixture
def cli(tmp_path, rig):
    c = login_client(tmp_path)
    c.csrf = _csrf(c)
    return c


def _lists(cli, lists):
    r = cli.post("/api/account/prefs", json={"csrf": cli.csrf, "set": {runs.LISTS_KEY: lists}})
    assert r.status_code == 200, r.get_json()


def body(cli, **kw):
    b = dict(BASE, csrf=cli.csrf, var_mode="random", count=1, run_seed=12345)
    b.update(kw)
    return b


def plan(cli, **kw):
    return cli.post("/api/generate/plan", json=body(cli, **kw))


def ack_of(p):
    return {k: p.get(k) for k in runs.ACK_FIELDS}


def run(cli, run_id=None, ack=None, **kw):
    b = body(cli, **kw)
    b["run_id"] = run_id or uuid.uuid4().hex
    if ack is not None:
        b["ack"] = ack
    return cli.post("/api/generate/run", json=b)


def plan_and_run(cli, rig, **kw):
    p = plan(cli, **kw).get_json()
    assert "error" not in p, p
    before = rig.network
    r = run(cli, ack=ack_of(p), **kw).get_json()
    return p, r, before


CARD = {"id": "K1", "expiresAt": None, "templateId": "t1", "total": 5, "consumeAmount": 1,
        "covered": True, "balance_unknown": False, "name": "Tsubaki card"}


# ---------------------------------------------------------------------------------------
# The expander (NOTES 1): the shared vectors and the refusals
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("case", VECTORS["cases"], ids=[c["name"] for c in VECTORS["cases"]])
def test_the_expander_matches_the_shared_vectors(case):
    got = runs.plan_jobs(case["template"], VECTORS["lists"], case["var_mode"], case["count"],
                         case["run_seed"])
    assert got == case["plan"]
    assert runs.parse(case["template"], VECTORS["lists"])["syntax"] is case["syntax"]


@pytest.mark.parametrize("e", VECTORS["escape"], ids=[e["text"] for e in VECTORS["escape"]])
def test_escape_literal_round_trips_byte_for_byte(e):
    assert runs.escape_literal(e["text"]) == e["escaped"]
    p = runs.parse(e["escaped"], {})
    assert p["error"] is None and not p["vars"]
    assert "".join(x["lit"] for x in p["parts"]) == e["text"]


@pytest.mark.parametrize("t", VECTORS["trim"], ids=[ascii(t["raw"]) for t in VECTORS["trim"]])
def test_options_and_list_items_trim_the_one_shared_set(t):
    """Review N5: one explicit trim set in both halves (templateCore.js reads these too)."""
    assert runs.trim(t["raw"]) == t["trimmed"]
    assert runs.clean_list([t["raw"]]) == ([t["trimmed"]] if t["trimmed"] else [])
    p = runs.parse("{" + t["raw"] + "|z}", {})
    assert p["vars"][0]["options"] == ([t["trimmed"]] if t["trimmed"] else []) + ["z"]


@pytest.mark.parametrize("t", VECTORS["invariant"], ids=[ascii(t) for t in VECTORS["invariant"]])
def test_a_prompt_with_no_pipe_group_and_no_list_token_is_byte_identical(t):
    """The S1 ruling's invariant: it never changes what PixAI receives, never needs a confirm."""
    for vm in ("random", "matrix"):
        got = runs.plan_jobs(t, VECTORS["lists"], vm, 1, 5)
        assert got["mode"] == "single" and got["jobs"][0]["prompt"] == t
    assert runs.parse(t, VECTORS["lists"])["syntax"] is False


def _lcg_strings(alphabet, count, seed, max_len=14):
    """Deterministic pseudo-random strings (the same generator loom/test/template-core.test.js
    uses), so the two halves are driven by the same inputs."""
    s = seed
    out = []
    for _ in range(count):
        s = (s * 1664525 + 1013904223) & 0xFFFFFFFF
        n = s % max_len
        w = []
        for _k in range(n):
            s = (s * 1664525 + 1013904223) & 0xFFFFFFFF
            w.append(alphabet[s % len(alphabet)])
        out.append("".join(w))
    return out


PROPERTY_ALPHABET = ["{", "}", "\\", "_", "a", " ", "(", ")", ",", "__x__", "é"]


def test_property_no_pipe_and_no_list_token_resolves_to_itself():
    """Review S1: the invariant as a property -- any text with no `|` and no __name__ token,
    whatever its braces and backslashes, resolves to itself byte for byte with no syntax."""
    checked = 0
    for t in _lcg_strings(PROPERTY_ALPHABET, 4000, 20260929):
        if "|" in t or runs._LIST_TOKEN_RE.search(t):
            continue
        checked += 1
        assert runs.parse(t, {})["syntax"] is False, t
        assert runs.plan_jobs(t, {}, "matrix", 1, 1)["jobs"][0]["prompt"] == t, t
    assert checked > 500


def test_property_escape_literal_always_round_trips():
    """History reuse: any text at all, escaped, parses back to exactly itself, no variable."""
    for t in _lcg_strings(PROPERTY_ALPHABET + ["|"], 4000, 7):
        p = runs.parse(runs.escape_literal(t), {"x": ["q"]})
        assert p["error"] is None and not p["vars"], t
        assert "".join(x["lit"] for x in p["parts"]) == t, t


def test_the_keys_and_numbers_match_the_dock():
    js = open(os.path.join(HERE, "..", "gallery", "src", "gen", "templateCore.js"),
              encoding="utf-8").read()
    assert 'export const LISTS_KEY = "{}";'.format(runs.LISTS_KEY) in js
    for name, value in (("MAX_VARS", runs.MAX_VARS), ("MAX_OPTIONS", runs.MAX_OPTIONS),
                        ("CELL_CAP", runs.CELL_CAP), ("RUN_SEED_MAX", runs.RUN_SEED_MAX),
                        ("SEED_MOD", runs.SEED_MOD)):
        assert "export const {} = {};".format(name, value) in js


def test_strict_count_never_clamps_and_never_takes_a_bool():
    assert runs.strict_int(4, 1, 4) == 4
    assert runs.strict_int("3", 1, 4) == 3
    assert runs.strict_int(2.0, 1, 4) == 2
    for bad in (5, 0, True, False, "2.7", 2.7, None, "", "x"):
        assert runs.strict_int(bad, 1, 4) is None


# ---------------------------------------------------------------------------------------
# /api/generate stays a single send (review F2)
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("count", [2, 4, 9, 0, "3", True])
def test_api_generate_refuses_more_than_one_with_nothing_sent(cli, rig, count):
    r = cli.post("/api/generate", json=dict(BASE, count=count))
    assert r.status_code == 400
    assert "through the confirm" in r.get_json()["error"]
    assert rig.network == 0


@pytest.mark.parametrize("prompt", ["a {b|c}", "a __poses__", "a \\{b|c\\}", "{unclosed | pipe",
                                    "{{nested|group}}", "\\__poses__"])
def test_api_generate_refuses_the_template_syntax_with_nothing_sent(cli, rig, prompt):
    r = cli.post("/api/generate", json=dict(BASE, prompt=prompt, count=1))
    assert r.status_code == 400
    assert "template syntax" in r.get_json()["error"]
    assert rig.network == 0


@pytest.mark.parametrize("prompt", VECTORS["invariant"] + [
    "masterpiece, {{best quality}}, (smile:1.2), a | b, ¯\\_(ツ)_/¯"])
def test_ordinary_braces_and_backslashes_reach_pixai_exactly_as_typed(cli, rig, prompt):
    """The S1 ruling: a prompt with no `|` group and no __name__ token is an ordinary single
    send -- /api/generate takes it and PixAI receives it byte for byte, braces and all."""
    rig.card_default = None
    d = cli.post("/api/generate", json=dict(BASE, prompt=prompt, count=1)).get_json()
    assert d.get("task_id"), d
    assert rig.mutations[-1]["prompts"] == prompt


def test_the_upscale_road_keeps_its_stored_prompt_braces_and_all(cli, rig):
    """The Upscale road re-sends the source picture's own prompt, never a template."""
    rig.card_default = None
    r = cli.post("/api/generate", json=dict(BASE, prompt="{{masterpiece}}, a cat",
                                            ref_media_id="777", upscale=1.5, count=1))
    assert r.get_json().get("task_id"), r.get_json()
    assert rig.mutations[0]["prompts"] == "{{masterpiece}}, a cat"


def test_a_single_send_is_recorded_for_inspect_without_changing_it(cli, rig, tmp_path):
    r = cli.post("/api/generate", json=dict(BASE, count=1)).get_json()
    tid = r["task_id"]
    assert len(rig.mutations) == 1
    d = cli.get("/api/generate/request/" + tid).get_json()
    assert d["source"] == "local"
    sent = d["request"]["variables"]["parameters"]
    assert sent == rig.mutations[0]
    assert d["cli"]["command"].startswith("python moonglade_backup.py --generate")
    assert "--confirm" not in d["cli"]["command"]


# ---------------------------------------------------------------------------------------
# /plan -- the confirm's numbers; read-only
# ---------------------------------------------------------------------------------------

def test_plan_needs_the_csrf_token_and_touches_nothing_without_it(cli, rig):
    r = cli.post("/api/generate/plan", json=dict(body(cli, count=3), csrf="nope"))
    assert r.status_code == 403
    assert rig.network == 0


def test_plan_writes_nothing(cli, rig, tmp_path):
    _lists(cli, {"poses": ["kneeling", "seated"]})
    prefs_before = cli.get("/api/account/prefs").get_json()["prefs"]
    jobs = tmp_path / core.JOBS_LOG_NAME
    jobs_before = jobs.read_text(encoding="utf-8") if jobs.exists() else ""
    d = plan(cli, prompt="{silver|cobalt} hair, __poses__", count=4).get_json()
    assert d["count"] == 4 and d["jobs"] == 4
    assert not (tmp_path / runs.RUNS_DB).exists(), "/plan must not create the Runs store"
    assert (jobs.read_text(encoding="utf-8") if jobs.exists() else "") == jobs_before
    assert cli.get("/api/account/prefs").get_json()["prefs"] == prefs_before
    assert rig.mutations == []


def test_a_plain_batch_is_one_task_and_its_total_is_one_task_price(cli, rig):
    """Review F1: `each` is /v2/task-price for the ONE task (batchSize already prices all N
    images), so a paid batch x4 totals each x 1, never each x 4."""
    d = plan(cli, count=4).get_json()
    assert (d["mode"], d["count"], d["jobs"]) == ("batch", 4, 1)
    assert (d["each"], d["covered"], d["total"]) == (1600, 0, 1600)
    assert d["cells"][0]["count"] == 4
    assert d["cells"][0]["request"]["variables"]["parameters"]["batchSize"] == 4


def test_a_plain_batch_a_card_covers_totals_zero(cli, rig):
    rig.card_default = CARD
    d = plan(cli, count=4).get_json()
    assert (d["jobs"], d["covered"], d["total"]) == (1, 1, 0)
    assert d["card"]["name"] == "Tsubaki card" and d["card"]["left_after"] == 4


def test_random_cards_cover_the_first_min_n_held(cli, rig):
    rig.card_default = dict(CARD, total=2)
    d = plan(cli, prompt="{a|b|c} x", count=4).get_json()
    assert (d["mode"], d["count"], d["jobs"], d["covered"], d["total"]) == ("random", 4, 4, 2, 3200)
    assert d["card"]["left_after"] == 0
    # a multi-ticket card: held // need
    rig.card_default = dict(CARD, total=5, consumeAmount=2)
    d = plan(cli, prompt="{a|b|c} x", count=4).get_json()
    assert d["covered"] == 2 and d["total"] == 3200


def test_random_with_an_unreadable_balance_counts_only_one_covered(cli, rig):
    rig.card_default = dict(CARD, total=None, balance_unknown=True)
    d = plan(cli, prompt="{a|b} x", count=3).get_json()
    assert d["covered"] == 1 and d["total"] == 3200


def test_a_matrix_never_asks_for_a_card(cli, rig):
    rig.card_default = CARD
    d = plan(cli, prompt="{a|b} {x|y}", var_mode="matrix").get_json()
    assert (d["mode"], d["count"], d["covered"], d["total"]) == ("matrix", 4, 0, 6400)
    assert rig.count("match_kaisuuken") == 0
    assert d["card_note"] == "Free cards don\u2019t cover queued matrix runs."
    assert all(c["no_card"] for c in d["cells"])
    assert all("--no-card" in c["cli"]["command"] for c in d["cells"])


def test_an_unreadable_price_refuses_the_plan(cli, rig):
    rig.price = None
    d = plan(cli, count=3).get_json()
    assert "Couldn't read the price" in d["error"]


def test_plan_answers_read_only_and_each_cells_request_and_command(cli, rig, monkeypatch):
    monkeypatch.setattr(core, "READ_ONLY", True)
    d = plan(cli, prompt="{a|b} glade", count=2).get_json()
    assert d["read_only"] is True
    assert [c["prompt"] for c in d["cells"]] == [j["prompt"] for j in runs.plan_jobs(
        "{a|b} glade", {}, "random", 2, 12345)["jobs"]]
    assert [c["seed"] for c in d["cells"]] == [12345, 12346]
    for c in d["cells"]:
        assert "csrf" not in json.dumps(c["request"])


# ---------------------------------------------------------------------------------------
# /run -- the guard order
# ---------------------------------------------------------------------------------------

def test_run_bad_csrf_is_403_with_no_pixai_call(cli, rig):
    r = cli.post("/api/generate/run", json=dict(body(cli, count=2), csrf="x",
                                                run_id="a" * 32, ack={"count": 2}))
    assert r.status_code == 403
    assert rig.network == 0


def test_run_read_only_refuses_before_any_pixai_call(cli, rig, monkeypatch, tmp_path):
    p = plan(cli, count=2).get_json()
    before = rig.network
    monkeypatch.setattr(core, "_read_only_now", lambda: True)
    d = run(cli, ack=ack_of(p), count=2).get_json()
    assert "READ_ONLY" in d["error"]
    assert rig.network == before, "no entitlement, gate, price, card or mutation call"
    assert rig.mutations == []


@pytest.mark.parametrize("kw,words", [
    ({"prompt": "a {b|c"}, "Unclosed or nested brace"),
    ({"prompt": "{{a|b}}"}, "Unclosed or nested brace"),
    ({"prompt": "__nope__ x"}, "No list named __nope__."),
    ({"prompt": "{a|b|c|d|e} {1|2|3|4|5}", "var_mode": "matrix"}, "over the 24-cell cap"),
    ({"count": 5}, "Pick 1 to 4 images."),
    ({"count": "2.7"}, "Pick 1 to 4 images."),
    ({"count": True}, "Pick 1 to 4 images."),
    ({"prompt": "{a|b}", "var_mode": "matrix", "count": 2}, "one image per cell"),
    ({"var_mode": "both"}, "Pick Random or Matrix"),
    ({"prompt": "{a|b}", "count": 2, "seed": "7", "run_seed": 8}, "doesn't match the seed field"),
    ({"prompt": "{a|b}", "count": 2}, "Confirm the 2 generations first"),
])
def test_local_refusals_make_no_pixai_call(cli, rig, kw, words):
    d = run(cli, **kw).get_json()
    assert words in d["error"], d
    assert rig.network == 0
    assert rig.mutations == []


def test_a_25_cell_matrix_is_refused_whatever_the_client_claims(cli, rig):
    forged = {"count": 24, "jobs": 24, "each": 1600, "covered": 0, "total": 38400, "digest": "x"}
    d = run(cli, prompt="{a|b|c|d|e} {1|2|3|4|5}", var_mode="matrix", ack=forged).get_json()
    assert "25 combinations is over the 24-cell cap" in d["error"]
    assert rig.network == 0 and rig.mutations == []


@pytest.mark.parametrize("field,value", [("count", 3), ("jobs", 3), ("each", 1500),
                                         ("covered", 1), ("total", 1), ("digest", "0" * 64)])
def test_any_acknowledgement_difference_refuses_with_the_fresh_plan(cli, rig, field, value):
    p = plan(cli, prompt="{a|b} x", count=2).get_json()
    ack = dict(ack_of(p), **{field: value})
    d = run(cli, ack=ack, prompt="{a|b} x", count=2).get_json()
    assert "nothing was sent" in d["error"]
    assert d["plan"]["total"] == p["total"] and d["plan"]["digest"] == p["digest"]
    assert rig.mutations == []


def test_a_cheaper_price_is_refused_too(cli, rig):
    p = plan(cli, count=2).get_json()
    rig.price = 1000
    d = run(cli, ack=ack_of(p), count=2).get_json()
    assert d["error"] == "The price moved since you confirmed \u2014 nothing was sent."
    assert d["plan"]["total"] == 1000
    assert rig.mutations == []


def test_a_list_changed_between_plan_and_run_changes_the_digest(cli, rig):
    _lists(cli, {"poses": ["kneeling", "seated"]})
    p = plan(cli, prompt="__poses__ x", var_mode="matrix").get_json()
    _lists(cli, {"poses": ["kneeling", "standing"]})
    d = run(cli, ack=ack_of(p), prompt="__poses__ x", var_mode="matrix").get_json()
    assert d["changed"] == "digest"
    assert rig.mutations == []


@pytest.mark.parametrize("change", [{"negative": "blurry"}, {"cfg": 5}, {"prompt_helper": False}])
def test_a_setting_that_does_not_move_the_price_still_changes_the_digest(cli, rig, change):
    """Review F3: the digest covers every job's full built parameters, not only the priced
    ones -- a negative, a CFG or the helper changed after the confirm is refused."""
    p = plan(cli, prompt="{a|b} x", count=2).get_json()
    d = run(cli, ack=ack_of(p), prompt="{a|b} x", count=2, **change).get_json()
    assert d.get("changed") == "digest", d
    assert rig.mutations == []


# ---------------------------------------------------------------------------------------
# /run -- the sends
# ---------------------------------------------------------------------------------------

def test_a_random_run_sends_each_job_in_order_with_its_prompt_and_seed(cli, rig):
    p, d, _ = plan_and_run(cli, rig, prompt="{silver|cobalt|ember} hair", count=4)
    assert d["status"] == "sent" and d["sent"] == 4
    expected = runs.plan_jobs("{silver|cobalt|ember} hair", {}, "random", 4, 12345)["jobs"]
    assert [m["prompts"] for m in rig.mutations] == [j["prompt"] for j in expected]
    assert [m["seed"] for m in rig.mutations] == [12345, 12346, 12347, 12348]
    assert all(m["batchSize"] == 1 for m in rig.mutations)
    assert [j["task_id"] for j in d["jobs"]] == ["9001", "9002", "9003", "9004"]


def test_a_plain_batch_sends_one_task_of_n(cli, rig):
    _, d, _ = plan_and_run(cli, rig, count=3)
    assert len(rig.mutations) == 1 and rig.mutations[0]["batchSize"] == 3
    assert d["status"] == "sent" and d["jobs"][0]["expected"] == 1600


def test_matrix_cells_go_out_without_a_card_in_order(cli, rig):
    rig.card_default = CARD
    _, d, _ = plan_and_run(cli, rig, prompt="{a|b} {x|y|z}", var_mode="matrix")
    assert [m["prompts"] for m in rig.mutations] == ["a x", "a y", "a z", "b x", "b y", "b z"]
    assert all("kaisuukenId" not in m for m in rig.mutations)
    assert rig.count("match_kaisuuken") == 0
    assert d["axes"][-1]["values"] == ["x", "y", "z"]


def test_random_jobs_carry_a_card_for_the_covered_ones(cli, rig):
    rig.cards = [dict(CARD, total=2)]                 # the plan's check
    p = plan(cli, prompt="{a|b} x", count=3).get_json()
    assert p["covered"] == 2 and p["total"] == 1600
    # the run's own quote, then the first two sends' own checks; the third finds none
    rig.cards = [dict(CARD, total=2), dict(CARD, total=2), dict(CARD, total=1)]
    d = run(cli, ack=ack_of(p), prompt="{a|b} x", count=3).get_json()
    assert d["status"] == "sent"
    assert ["kaisuukenId" in m for m in rig.mutations] == [True, True, False]
    assert [j["expected"] for j in d["jobs"]] == [0, 0, 1600]


def test_a_card_gone_stops_the_run_before_it_costs_more_than_confirmed(cli, rig):
    rig.cards = [dict(CARD, total=2)]
    p = plan(cli, prompt="{a|b} x", count=3).get_json()
    rig.cards = [dict(CARD, total=2), dict(CARD, total=2)]   # the quote, job 1; then none
    d = run(cli, ack=ack_of(p), prompt="{a|b} x", count=3).get_json()
    assert len(rig.mutations) == 2                    # 0 + 1600 fits; the next would not
    assert d["status"] == "stopped"
    assert [j["state"] for j in d["jobs"]] == ["sent", "sent", "not_sent"]
    assert "cost more than you confirmed" in d["reason"]


def test_read_only_switched_on_mid_run_stops_before_the_next_job(cli, rig, monkeypatch):
    p = plan(cli, prompt="{a|b} x", count=4).get_json()
    flag = {"on": False}
    monkeypatch.setattr(core, "_read_only_now", lambda: flag["on"])

    def after(i, params):
        if i == 1:
            flag["on"] = True
    rig.on_mutate = after
    d = run(cli, ack=ack_of(p), prompt="{a|b} x", count=4).get_json()
    assert len(rig.mutations) == 2
    assert [j["state"] for j in d["jobs"]] == ["sent", "sent", "not_sent", "not_sent"]


def test_a_graphql_refusal_stops_the_rest_and_is_never_retried(cli, rig):
    p = plan(cli, prompt="{a|b|c|d} x", count=4).get_json()

    def refuse(i, params):
        if i == 2:
            raise core.PixAIError('GraphQL error: [{"message": "moderation blocked"}]')
    rig.on_mutate = refuse
    d = run(cli, ack=ack_of(p), prompt="{a|b|c|d} x", count=4).get_json()
    assert len(rig.mutations) == 3
    assert [j["state"] for j in d["jobs"]] == ["sent", "sent", "refused", "not_sent"]
    assert "moderation blocked" in d["jobs"][2]["error"]


def test_an_unclear_answer_is_may_have_started_and_is_never_resent(cli, rig):
    p = plan(cli, prompt="{a|b|c|d} x", count=4).get_json()

    def timeout(i, params):
        if i == 2:
            raise requests.ReadTimeout("read timed out")
    rig.on_mutate = timeout
    d = run(cli, ack=ack_of(p), prompt="{a|b|c|d} x", count=4).get_json()
    assert len(rig.mutations) == 3
    assert [j["state"] for j in d["jobs"]] == ["sent", "sent", "may_have_started", "not_sent"]


def test_an_inference_profile_refusal_in_a_run_is_one_mutation(cli, rig):
    """Review F6: a run job goes out exactly as quoted -- no profile-drop resubmit."""
    p = plan(cli, prompt="{a|b} x", count=2, mode="pro").get_json()

    def refuse(i, params):
        raise core.PixAIError('GraphQL error: [{"message": "invalid inferenceProfile"}]')
    rig.on_mutate = refuse
    d = run(cli, ack=ack_of(p), prompt="{a|b} x", count=2, mode="pro").get_json()
    assert len(rig.mutations) == 1
    assert d["jobs"][0]["state"] == "refused"


# ---------------------------------------------------------------------------------------
# Idempotency, the lock, the read-back
# ---------------------------------------------------------------------------------------

def test_the_same_run_id_twice_sends_once(cli, rig):
    p = plan(cli, prompt="{a|b} x", count=2).get_json()
    rid = "b" * 32
    first = run(cli, run_id=rid, ack=ack_of(p), prompt="{a|b} x", count=2).get_json()
    again = run(cli, run_id=rid, ack=ack_of(p), prompt="{a|b} x", count=2).get_json()
    assert len(rig.mutations) == 2
    assert again["replay"] is True and again["status"] == "sent"
    assert [j["task_id"] for j in again["jobs"]] == [j["task_id"] for j in first["jobs"]]


def test_a_second_run_while_one_is_sending_is_refused(tmp_path, cli, rig):
    p = plan(cli, prompt="{a|b} x", count=2).get_json()
    gate, entered = threading.Event(), threading.Event()

    def hold(i, params):
        entered.set()
        gate.wait(10)
    rig.on_mutate = hold
    out = {}

    def first():
        out["r"] = run(cli, run_id="c" * 32, ack=ack_of(p), prompt="{a|b} x", count=2).get_json()
    t = threading.Thread(target=first)
    t.start()
    assert entered.wait(10)
    try:
        second = run(cli, run_id="d" * 32, ack=ack_of(p), prompt="{a|b} x", count=2).get_json()
        assert "A run is still being sent" in second["error"]
    finally:
        gate.set()
        t.join(10)
    assert out["r"]["status"] == "sent"
    assert len(rig.mutations) == 2


def test_the_in_flight_mark_is_released_after_an_exception(cli, rig, monkeypatch):
    p = plan(cli, prompt="{a|b} x", count=2).get_json()
    real = core.send_run

    def boom(*a, **k):
        raise RuntimeError("unexpected")
    monkeypatch.setattr(core, "send_run", boom)
    with pytest.raises(RuntimeError):
        cli.application.config["PROPAGATE_EXCEPTIONS"] = True
        run(cli, run_id="e" * 32, ack=ack_of(p), prompt="{a|b} x", count=2)
    monkeypatch.setattr(core, "send_run", real)
    d = run(cli, run_id="f" * 32, ack=ack_of(p), prompt="{a|b} x", count=2).get_json()
    assert d["status"] == "sent"


def test_a_refused_run_reads_back_as_refused(cli, rig):
    """Review F4: every POST that reached the server can be read back."""
    rid = "1" * 32
    d = run(cli, run_id=rid, prompt="{a|b|c|d|e} {1|2|3|4|5}", var_mode="matrix").get_json()
    assert d["status"] == "refused"
    g = cli.get("/api/generate/runs/" + rid).get_json()
    assert g["status"] == "refused" and "24-cell cap" in g["reason"]


def test_an_unknown_run_is_404(cli, rig):
    assert cli.get("/api/generate/runs/" + "9" * 32).status_code == 404


def test_another_accounts_run_is_neither_served_nor_replayed(tmp_path, rig, monkeypatch):
    app = create_app(tmp_path)
    a = login_test_client(app, username="alice")
    a.csrf = _csrf(a)
    p = plan(a, prompt="{a|b} x", count=2).get_json()
    rid = "2" * 32
    d = run(a, run_id=rid, ack=ack_of(p), prompt="{a|b} x", count=2).get_json()
    tid = d["jobs"][0]["task_id"]
    b = login_test_client(app, username="bobby")
    b.csrf = _csrf(b)
    assert b.get("/api/generate/runs/" + rid).status_code == 404
    reuse = run(b, run_id=rid, ack=ack_of(p), prompt="{a|b} x", count=2).get_json()
    assert reuse["error"] == "That run id is taken \u2014 nothing was sent."
    before = rig.network
    assert b.get("/api/generate/request/" + tid).status_code == 404
    assert rig.network == before, "no PixAI fallback for another account's task (review F9)"
    assert len(rig.mutations) == 2


def test_the_inspector_falls_back_to_pixai_only_for_a_library_task_with_no_record(cli, rig, tmp_path, monkeypatch):
    assert cli.get("/api/generate/request/424242").status_code == 404
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": "M1", "task_id": "424242", "filename": "2025-01/a.png"}])
    monkeypatch.setattr(core, "task_detail_gql", lambda s, tid, retries=None: {
        "parameters": {"prompts": "x", "modelId": "V1", "authToken": "SECRET"}})
    d = cli.get("/api/generate/request/424242").get_json()
    assert d["source"] == "pixai"
    assert "authToken" not in json.dumps(d) and "SECRET" not in json.dumps(d)


# ---------------------------------------------------------------------------------------
# The Runs store (NOTES 3) and the job-state writes (review F5)
# ---------------------------------------------------------------------------------------

def test_the_store_holds_the_template_the_vars_and_the_exact_request(cli, rig, tmp_path):
    _lists(cli, {"poses": ["kneeling", "seated"]})
    _, d, _ = plan_and_run(cli, rig, prompt="{silver|cobalt} __poses__", var_mode="matrix")
    rec = runs.RunsStore(tmp_path).get(d["run_id"])
    assert rec["template"] == "{silver|cobalt} __poses__" and rec["mode"] == "matrix"
    assert rec["jobs"][1]["vars"] == [{"token": "{silver|cobalt}", "value": "silver"},
                                      {"token": "__poses__", "value": "seated"}]
    assert rec["jobs"][1]["request"] == rig.mutations[1]
    assert "csrf" not in json.dumps(rec["payload"])


def test_history_reuse_gets_the_template_back(cli, rig, tmp_path):
    _, d, _ = plan_and_run(cli, rig, prompt="{a|b} glade", count=2)
    tid = d["jobs"][1]["task_id"]
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": "M9", "task_id": tid, "filename": "2025-01/m9.png", "prompt_full": "b glade"}])
    got = cli.get("/api/next/detail/M9").get_json()["run"]
    assert got["template"] == "{a|b} glade" and got["var_mode"] == "random"
    assert got["run_seed"] == 12345 and got["cell"] == 1 and got["count"] == 2


def test_a_single_send_record_has_no_run_template_so_reuse_escapes(cli, rig, tmp_path):
    tid = cli.post("/api/generate", json=dict(BASE, count=1)).get_json()["task_id"]
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": "M8", "task_id": tid, "filename": "2025-01/m8.png"}])
    assert cli.get("/api/next/detail/M8").get_json()["run"]["var_mode"] == ""


def test_a_failed_sending_write_stops_before_the_mutation(cli, rig, monkeypatch):
    p = plan(cli, prompt="{a|b} x", count=2).get_json()
    real = runs.RunsStore.set_job

    def flaky(self, run_id, cell, **fields):
        if fields.get("state") == "sending" and cell == 1:
            raise runs.sqlite3.OperationalError("database is locked")
        return real(self, run_id, cell, **fields)
    monkeypatch.setattr(runs.RunsStore, "set_job", flaky)
    d = run(cli, ack=ack_of(p), prompt="{a|b} x", count=2).get_json()
    assert len(rig.mutations) == 1
    assert [j["state"] for j in d["jobs"]] == ["sent", "not_sent"]


def test_a_failed_task_id_write_still_answers_with_the_task_and_never_reads_not_sent(cli, rig, monkeypatch, tmp_path):
    p = plan(cli, prompt="{a|b} x", count=2).get_json()
    real = runs.RunsStore.set_job

    def flaky(self, run_id, cell, **fields):
        if fields.get("state") == "sent" and cell == 0:
            raise runs.sqlite3.OperationalError("database is locked")
        return real(self, run_id, cell, **fields)
    monkeypatch.setattr(runs.RunsStore, "set_job", flaky)
    d = run(cli, ack=ack_of(p), prompt="{a|b} x", count=2).get_json()
    assert d["jobs"][0]["state"] == "sent" and d["jobs"][0]["task_id"] == "9001"
    back = cli.get("/api/generate/runs/" + d["run_id"]).get_json()
    assert back["jobs"][0]["state"] == "may_have_started"
    logged = [j for j in core.read_jobs(tmp_path) if j["job_id"] == "9001"]
    assert logged and logged[0]["run"] == d["run_id"] and logged[0]["cell"] == 0


def test_strip_secrets_removes_credential_keys_at_any_depth():
    got = runs.strip_secrets({"prompts": "x", "Authorization": "Bearer k", "csrf": "t",
                              "nested": {"apiKey": "k", "session_id": "s", "kaisuukenId": "K1",
                                         "list": [{"cookie": "c", "ok": 1}]}},
                             redact=lambda s: s.replace("C:\\Users\\me", "<home>"))
    assert got == {"prompts": "x", "nested": {"kaisuukenId": "K1", "list": [{"ok": 1}]}}


# ---------------------------------------------------------------------------------------
# Count 1 through /run (review F11), Unlimited, no_card, price groups, paid vs expected
# ---------------------------------------------------------------------------------------

def test_a_single_send_with_variables_needs_no_ack_and_no_quote(cli, rig):
    rig.card_default = CARD
    d = run(cli, prompt="{a|b} glade", count=1).get_json()
    assert d["status"] == "sent" and len(rig.mutations) == 1
    assert rig.count("price_task") == 0, "a single send is not quoted (as /api/generate)"
    assert rig.mutations[0].get("kaisuukenId") == "K1", "the card auto-applies as today"


def test_a_payload_no_card_is_kept_for_a_random_run(cli, rig):
    rig.card_default = CARD
    p = plan(cli, prompt="{a|b} x", count=2, no_card=True).get_json()
    assert p["covered"] == 0
    run(cli, ack=ack_of(p), prompt="{a|b} x", count=2, no_card=True)
    assert rig.count("match_kaisuuken") == 0
    assert all("kaisuukenId" not in m for m in rig.mutations)


def test_more_than_one_price_group_is_refused(cli, rig, monkeypatch):
    seen = {"n": 0}

    def varying(session, params):
        seen["n"] += 1
        return {"width": seen["n"]}
    monkeypatch.setattr(core, "_task_price_query", varying)
    d = plan(cli, prompt="{a|b} x", count=2).get_json()
    assert "don't all cost the same" in d["error"]


def test_unlimited_mode_takes_one_task_at_a_time(cli, rig, monkeypatch, tmp_path):
    monkeypatch.setattr(core, "unlimited_resolver", lambda s: (
        lambda params, vid: dict(params, lane=core.UNLIMITED_LANE)))
    d = plan(cli, prompt="{a|b} x", count=2, unlimited=True).get_json()
    assert "one picture at a time" in d["error"]
    core.append_job_event(tmp_path, "5555", status="running", type="generate",
                          lane=core.UNLIMITED_LANE)
    d = run(cli, prompt="{a|b} x", count=1, unlimited=True).get_json()
    assert d["error"] == core.UNLIMITED_BUSY
    assert rig.mutations == []


def test_a_lane_single_is_logged_with_its_lane(cli, rig, monkeypatch, tmp_path):
    monkeypatch.setattr(core, "unlimited_resolver", lambda s: (
        lambda params, vid: dict(params, lane=core.UNLIMITED_LANE)))
    d = run(cli, prompt="{a|b} x", count=1, unlimited=True).get_json()
    assert d["status"] == "sent"
    job = [j for j in core.read_jobs(tmp_path) if j["job_id"] == d["jobs"][0]["task_id"]][0]
    assert job["lane"] == core.UNLIMITED_LANE


def test_task_status_reports_the_expected_charge_beside_the_paid_one(cli, rig, monkeypatch, tmp_path):
    """Review F14: the store keeps each job's expected cost and the dock compares."""
    rig.cards = [dict(CARD, total=1)]
    p = plan(cli, prompt="{a|b} x", count=2).get_json()
    rig.cards = [dict(CARD, total=1)]
    d = run(cli, ack=ack_of(p), prompt="{a|b} x", count=2).get_json()
    tid = d["jobs"][0]["task_id"]
    monkeypatch.setattr(core, "generation_status",
                        lambda s, t: {"phase": "done", "paid_credit": 1600, "status": "completed"})
    monkeypatch.setattr(core, "collect_generation",
                        lambda s, t, out, **k: {"media_ids": ["OUT1"], "saved": 1, "is_video": False})
    st = cli.get("/api/task-status", query_string={"task_id": tid}).get_json()
    assert st["expected_credit"] == 0 and st["paid_credit"] == 1600
    assert runs.RunsStore(tmp_path).get(d["run_id"])["jobs"][0]["paid"] == 1600


# ---------------------------------------------------------------------------------------
# Recipes ride the same road, per job (BUILD-w2-recipes)
# ---------------------------------------------------------------------------------------

R1 = "1900000000000000001"


def test_every_job_carries_its_recipes_and_passes_the_recipe_guards(cli, rig, monkeypatch):
    monkeypatch.setattr(moonglade_recipes, "batch", lambda s, ids: [{"id": R1, "prompt_len": 10}])
    _, d, _ = plan_and_run(cli, rig, prompt="{a|b} x", count=2, recipeIds=[R1])
    assert d["status"] == "sent"
    assert all(m.get("recipeIds") == [R1] for m in rig.mutations)


def test_recipes_beside_context_images_are_refused_for_every_cell(cli, rig, monkeypatch):
    d = plan(cli, prompt="{a|b} @image1", count=2, recipeIds=[R1],
             context_images=["111"]).get_json()
    assert "held while context images are on" in d["error"]
    assert rig.mutations == []


def test_a_cell_the_recipes_would_take_over_the_prompt_budget_is_named(cli, rig, monkeypatch):
    """Review F7: checked on every resolved prompt before anything goes out."""
    monkeypatch.setattr(moonglade_recipes, "batch", lambda s, ids: [{"id": R1, "prompt_len": 4001}])
    long = "x" * 90
    d = run(cli, prompt="{short|" + long + "} glade", var_mode="matrix", recipeIds=[R1],
            ack={"count": 2}).get_json()
    assert d["error"].startswith("Cell 2 (" + long + "): a recipe would make the prompt too long")
    assert rig.mutations == []


# ---------------------------------------------------------------------------------------
# The spend helpers' hooks (s3.4)
# ---------------------------------------------------------------------------------------

def test_submit_without_hooks_sends_the_same_request_as_before(rig):
    req = core.build_request(dict(BASE, count=1), mode="image")
    core.submit(object(), req)
    assert rig.mutations[0] == req.parameters


def test_on_send_sees_a_copy_of_every_attempt_and_cannot_alter_or_block_it(rig):
    seen = []

    def spy(v):
        seen.append(v)
        v["prompts"] = "tampered"
        raise ValueError("a broken recorder")

    def refuse_profile(i, params):
        if i == 0:
            raise core.PixAIError('GraphQL error: [{"message": "bad inferenceProfile"}]')
    rig.on_mutate = refuse_profile
    core.submit_generation(object(), {"prompts": "a", "modelId": "V", "inferenceProfile": "pro"},
                           on_send=spy)
    assert len(rig.mutations) == 2 and len(seen) == 2          # the resubmit is observed too
    assert rig.mutations[0]["prompts"] == "a" and rig.mutations[1]["prompts"] == "a"
    assert "inferenceProfile" not in rig.mutations[1]


def test_exact_turns_off_both_resubmits(rig):
    def refuse(i, params):
        raise core.PixAIError('GraphQL error: [{"message": "bad inferenceProfile"}]')
    rig.on_mutate = refuse
    with pytest.raises(core.PixAIError):
        core.submit_generation(object(), {"prompts": "a", "inferenceProfile": "pro"}, exact=True)
    assert len(rig.mutations) == 1


def test_before_send_runs_after_the_card_and_can_stop_the_send(rig):
    rig.card_default = CARD
    req = core.build_request(dict(BASE, count=1), mode="image")
    seen = []

    def stop(params):
        seen.append(params.get("kaisuukenId"))
        raise core.LocalRefusal("over budget")
    with pytest.raises(core.LocalRefusal):
        core.submit(object(), req, before_send=stop)
    assert seen == ["K1"] and rig.mutations == []


# ---------------------------------------------------------------------------------------
# Copy as CLI (NOTES 7, Settled 1): the CLI's real flags, parsed by its own argparse
# ---------------------------------------------------------------------------------------

class _Parser(Exception):
    pass


@pytest.fixture(scope="module")
def cli_parser():
    real = argparse.ArgumentParser.parse_args

    def grab(self, *a, **k):
        raise _Parser(self)
    argparse.ArgumentParser.parse_args = grab
    try:
        core.main()
    except _Parser as e:
        ap = e.args[0]
    finally:
        argparse.ArgumentParser.parse_args = real
    return ap


def _posix_argv(command):
    import shlex
    words = shlex.split(command)
    assert words[:3] == ["python", "moonglade_backup.py", "--generate"]
    return words[2:]


def _web_params(**kw):
    req = core.build_request(dict(BASE, **kw), mode="image")
    return dict(req.parameters)


FLAG_CASES = [
    {},
    {"negative": ""},
    {"seed": "42", "high_priority": True},
    {"mode": "pro", "prompt_helper": False},
    {"loras": [{"version_id": "L1", "weight": 0.7}, {"version_id": "L2", "weight": -0.25}]},
    {"face_fix": True, "quality_tag": "Masterpiece"},
    {"upscale": 1.5, "upscale_denoise": 0.6, "upscale_denoise_steps": 20},
    {"enlarge": 1.5, "enlarge_model": "SwinIR_4x"},
    {"prompt": "-starts with a dash, it's \"quoted\" and $HOME `tick` \u2019curly\u2019"},
    {"prompt": "line one\nline two \\ ending in a backslash\\"},
]


@pytest.mark.parametrize("kw", FLAG_CASES, ids=[str(i) for i in range(len(FLAG_CASES))])
def test_the_flag_command_rebuilds_the_same_parameters(cli_parser, kw):
    params = _web_params(**kw)
    out = runs.cli_command(core, params, shell="posix")
    assert out["form"] == "flags", out
    ns = cli_parser.parse_args(_posix_argv(out["command"]))
    assert core._gen_parameters(ns) == params
    for dest, value in runs._CLI_DEFAULTS.items():
        if dest in ("priority",):
            continue
        assert hasattr(ns, dest), dest
    assert "--confirm" not in out["command"] and "--kaisuuken-id" not in out["command"]


def test_the_cli_defaults_are_the_parsers_own(cli_parser):
    ns = cli_parser.parse_args(["--generate"])
    for dest, value in runs._CLI_DEFAULTS.items():
        if dest == "priority":
            assert ns.priority == core.PRIORITY_TURBO
            continue
        if dest == "count":
            # --batch-size shares dest="count" with the top-level --count switch, so its
            # default can arrive as False; _gen_parameters reads both as 1
            assert max(1, int(getattr(ns, dest) or 1)) == value
            continue
        assert getattr(ns, dest) == value, dest


@pytest.mark.parametrize("extra", [
    {"contextImages": ["1", "2"]}, {"recipeIds": [R1]},
    {"colorPalette": {"name": "p", "palette": ["#000000"]}},
    {"promptHelper": {"creativity": "low", "forcePromptHelperDetectionSide": "server"}},
    {"mediaId": "123", "strength": 0.5}, {"qualityTag": {"prefix": "a", "suffix": "b"}},
    {"naturalPrompts": "something else"}, {"lane": "infinite"},
])
def test_what_the_flags_cannot_say_goes_as_params_json(cli_parser, extra):
    params = dict(_web_params(), **extra)
    params["kaisuukenId"] = "K1"
    out = runs.cli_command(core, params, no_card=True, shell="posix")
    assert out["form"] == "json"
    ns = cli_parser.parse_args(_posix_argv(out["command"]))
    expect = dict(params)
    expect.pop("kaisuukenId")
    assert json.loads(ns.params_json) == expect
    assert ns.no_card is True and not ns.confirm and ns.kaisuuken_id == ""


def test_powershell_quoting_doubles_every_single_quote_form():
    q = runs._ps_quote("it's \u2018a\u2019 \u201ab\u201b")
    assert q == "'\"it''s \u2018\u2018a\u2019\u2019 \u201a\u201ab\u201b\u201b\"'"
    # whitespace or a quote: wrapped here, each inner quote the runtime's "" pair
    assert runs._ps_quote('say "hi"') == "'\"say \"\"hi\"\"\"'"
    assert runs._ps_quote('{"k":"v"}') == "'\"{\"\"k\"\":\"\"v\"\"}\"'"
    # backslashes before a quote (the closing one too) doubled, the rest left single
    assert runs._ps_quote("ends\\ with space\\") == "'\"ends\\ with space\\\\\"'"
    assert runs._ps_quote("no_space\\") == "'no_space\\'"


@pytest.mark.skipif(os.name != "nt" or not shutil.which("powershell.exe"),
                    reason="the server's own shell is Windows PowerShell only on Windows")
@pytest.mark.parametrize("kw", [
    {"prompt": 'a "quoted" word, it\u2019s \u201cfancy\u201d, $HOME and `tick`'},
    {"prompt": "-dash first and a trailing backslash \\"},
    {"prompt": "{braces} and C:\\path\\ with spaces\\"},
], ids=["quotes", "dash", "backslashes"])
def test_the_powershell_command_survives_real_windows_powershell(tmp_path, cli_parser, kw):
    """Review F8: run the emitted line through real powershell.exe against a stub that dumps
    sys.argv, and check the CLI rebuilds the same parameters -- the JSON form too."""
    stub = tmp_path / "argv_stub.py"
    dump = tmp_path / "argv.json"
    stub.write_text("import json, sys\nopen(r'%s', 'w', encoding='utf-8').write("
                    "json.dumps(sys.argv[1:]))\n" % dump, encoding="utf-8")
    for extra in ({}, {"contextImages": ["1"]}):
        params = dict(_web_params(**kw), **extra)
        out = runs.cli_command(core, params, shell="powershell")
        line = out["command"].replace("python moonglade_backup.py",
                                      "& '%s' '%s'" % (sys.executable, stub), 1)
        script = tmp_path / "line.ps1"
        script.write_bytes(b"\xef\xbb\xbf" + line.encode("utf-8"))
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-File", str(script)], check=True, timeout=120,
                       capture_output=True, stdin=subprocess.DEVNULL)
        argv = json.loads(dump.read_text(encoding="utf-8"))
        ns = cli_parser.parse_args(argv)
        assert core._gen_parameters(ns) == params, (out["command"], argv)
