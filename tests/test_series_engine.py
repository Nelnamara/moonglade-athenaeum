"""Issue #34 -- the dial-in series engine: the owner-validated clustering rule
(same model · gap <= 8h · clause-Jaccard >= 0.5, chained over tasks in id order)
replicated server-side, plus the two LOGIN-tier reads that expose it
(POST /api/series, GET /api/series/<sid>). Pins:
  * the frost-queen fixture: 4 tasks -> ONE series, rerolls flagged, the v3
    delta label carries the added clause, the title resolves from the
    character token;
  * the 1200-char cap: the engine reads EXACTLY the library API's
    (prompt_full or prompt_preview or "")[:1200] -- prompts differing only
    past the cap are the SAME dial (engine requirement comment on #34);
  * model split (never merged), the 8h gap boundary, singletons invisible,
    blank task_id excluded, blank created_at = a fresh series;
  * the cache: recompute only when (COUNT(*), MAX(media_id)) changed AND the
    30s floor has passed (review item 3);
  * route hygiene mirroring /api/siblings (400 on non-list/non-object, 200-id
    cap).
"""
import moonglade_gallery as G


def _seed(tmp_path, rows):
    from moonglade_gallery import CATALOG_FIELDS, save_catalog
    (tmp_path / "2026-08").mkdir(parents=True, exist_ok=True)
    full = []
    for r in rows:
        name = "2026-08/pic_%s.png" % r["media_id"]
        (tmp_path / name).write_bytes(b"\x00" * 16)
        full.append({f: "" for f in CATALOG_FIELDS} | {
            "filename": name, "created_at": "2026-08-20T01:02:03Z"} | r)
    save_catalog(tmp_path / "catalog.db", full)


def _client(tmp_path):
    from moonglade_gallery import create_app
    from tests.conftest import login_test_client
    return login_test_client(create_app(tmp_path))


def _task(tid, prompt, ts, mids, model_id="M1", model_name="Model One"):
    """All rows of one task: same task_id/prompt/timestamp, one row per output."""
    return [{"media_id": m, "task_id": tid, "prompt_full": prompt,
             "created_at": ts, "model_id": model_id, "model_name": model_name}
            for m in mids]


# ---- the clause tokenizer: the validated JS, replicated -------------------------------

def test_clause_tokenizer_replicates_the_validated_js():
    """Strip <...> tokens, turn . ; and newlines into commas, split on commas,
    trim, lowercase, keep len > 3 -- the exact rule the owner validated."""
    s = ("Masterpiece, best quality; Frost Queen.\n"
         "<lora:ice palace:0.8> glacial crown, ice, a b")
    assert G._series_clauses(s) == {
        "masterpiece", "best quality", "frost queen", "glacial crown"}
    # reorderings are the SAME set (the differ drops them for free)
    assert G._series_clauses("a snow fox, b moon") == G._series_clauses(
        "b moon, a snow fox")


def test_series_text_is_the_library_apis_capped_prompt_expression():
    """#34's binding engine requirement: the engine reads the SAME expression
    the owner validated on -- (prompt_full or prompt_preview or '')[:1200]."""
    long = "x" * 2000
    assert G._series_text({"prompt_full": long, "prompt_preview": ""}) == "x" * 1200
    assert G._series_text({"prompt_full": "", "prompt_preview": "pv"}) == "pv"
    assert G._series_text({"prompt_full": None, "prompt_preview": None}) == ""


# ---- (a) the frost-queen fixture ------------------------------------------------------

_FROST_BASE = ("masterpiece, best quality, <character-a>, "
               "frost queen on an ice throne, glacial crown, aurora sky over the tundra")
_FROST_SWAP = _FROST_BASE.replace(
    "<character-a>", "<character-b>") + ", crystal scepter"


def _seed_frost_queen(tmp_path):
    rows = []
    # S1's two outputs carry PixAI batch indexes that DISAGREE with media_id
    # order -- first_media_id must follow the batch order (#33).
    rows += _task("S1", _FROST_BASE, "2026-08-20T10:00:00Z", ["911", "912"])
    rows[0]["batch_index"], rows[0]["batch_size"] = "1", "2"
    rows[1]["batch_index"], rows[1]["batch_size"] = "0", "2"
    rows += _task("S2", _FROST_BASE, "2026-08-20T10:40:00Z", ["913"])
    rows += _task("S3", _FROST_SWAP, "2026-08-20T11:20:00Z", ["914"])
    rows += _task("S4", _FROST_SWAP, "2026-08-20T12:00:00Z", ["915"])
    _seed(tmp_path, rows)


def test_frost_queen_four_tasks_one_series_rerolls_delta_and_title(tmp_path):
    _seed_frost_queen(tmp_path)
    cli = _client(tmp_path)
    r = cli.post("/api/series", json={"task_ids": ["S1", "S2", "S3", "S4", "NOPE"]})
    assert r.status_code == 200, r.get_data(as_text=True)
    by = r.get_json()["by_task"]
    assert set(by) == {"S1", "S2", "S3", "S4"}
    assert all(by[t]["sid"] == "S1" and by[t]["of"] == 4 for t in by)
    assert [by["S%d" % i]["v"] for i in (1, 2, 3, 4)] == [1, 2, 3, 4]
    # v2 and v4 repeat the previous task's clause set exactly: seed-only rerolls
    assert by["S2"]["reroll"] is True and by["S4"]["reroll"] is True
    assert by["S1"]["reroll"] is False and by["S3"]["reroll"] is False
    assert by["S2"]["label"] == "seed-only reroll"
    # v3's dial: the <character-a> -> <character-b> swap is markup (stripped),
    # the ADDED CLAUSE is the visible delta
    assert "crystal scepter" in by["S3"]["label"]
    assert by["S1"]["label"] == "series start"
    # the title resolves from the first task's character token
    assert all(by[t]["title"] == "Character a" for t in by)


def test_frost_queen_series_detail_struct(tmp_path):
    _seed_frost_queen(tmp_path)
    cli = _client(tmp_path)
    r = cli.get("/api/series/S1")
    assert r.status_code == 200, r.get_data(as_text=True)
    s = r.get_json()
    assert s["sid"] == "S1" and s["title"] == "Character a"
    assert s["model"] == "Model One"
    assert s["count_tasks"] == 4 and s["count_images"] == 5
    assert s["span"] == ["2026-08-20T10:00:00Z", "2026-08-20T12:00:00Z"]
    assert [st["task_id"] for st in s["steps"]] == ["S1", "S2", "S3", "S4"]
    assert [st["v"] for st in s["steps"]] == [1, 2, 3, 4]
    assert [st["reroll"] for st in s["steps"]] == [False, True, False, True]
    # S1's first output by PixAI's own batch order (#33), not media_id order
    assert s["steps"][0]["first_media_id"] == "912"
    assert s["steps"][0]["n"] == 2
    assert [st["n"] for st in s["steps"][1:]] == [1, 1, 1]
    # the sid is the FIRST task's id; a member id is NOT a series id
    assert cli.get("/api/series/S2").status_code == 404
    assert cli.get("/api/series/NOPE").status_code == 404


# ---- (b) the 1200-char cap pin --------------------------------------------------------

_CAP_HEAD = "frost queen, glacial crown, aurora sky, "        # 40 chars


def test_prompts_differing_only_past_1200_chars_chain_as_rerolls(tmp_path):
    """The owner validated on the library API's CAPPED prompt; text past char
    1200 must be invisible to the engine (engine requirement comment, #34)."""
    p1 = _CAP_HEAD + "w" * 1200 + ", zebra clause far past the cap"
    p2 = _CAP_HEAD + "w" * 1200 + ", quokka clause far past the cap"
    assert p1[:1200] == p2[:1200] and p1 != p2
    _seed(tmp_path, _task("B1", p1, "2026-08-20T10:00:00Z", ["921"])
          + _task("B2", p2, "2026-08-20T10:30:00Z", ["922"]))
    by_task, by_sid = G.compute_series(tmp_path / "catalog.db")
    assert set(by_task) == {"B1", "B2"} and set(by_sid) == {"B1"}
    assert by_sid["B1"]["steps"][1]["reroll"] is True


def test_prompts_differing_before_1200_chars_are_not_rerolls(tmp_path):
    """The mirror: the same one-clause change BEFORE the cap is a real dial."""
    p1 = _CAP_HEAD + "silver gown, " + "w" * 1200
    p2 = _CAP_HEAD + "golden gown, " + "w" * 1200
    _seed(tmp_path, _task("B1", p1, "2026-08-20T10:00:00Z", ["931"])
          + _task("B2", p2, "2026-08-20T10:30:00Z", ["932"]))
    by_task, by_sid = G.compute_series(tmp_path / "catalog.db")
    assert set(by_sid) == {"B1"}                    # still one series (4/6 shared)
    step = by_sid["B1"]["steps"][1]
    assert step["reroll"] is False
    assert "golden gown" in step["label"] and "silver gown" in step["label"]


# ---- (c) model split ------------------------------------------------------------------

def test_model_change_splits_series_and_blank_id_falls_back_to_name(tmp_path):
    prompt = "frost queen, glacial crown, aurora sky"
    rows = []
    rows += _task("C1", prompt, "2026-08-20T10:00:00Z", ["941"], "MA", "Alpha")
    rows += _task("C2", prompt, "2026-08-20T10:30:00Z", ["942"], "MA", "Alpha")
    rows += _task("C3", prompt, "2026-08-20T11:00:00Z", ["943"], "MB", "Beta")
    rows += _task("C4", prompt, "2026-08-20T11:30:00Z", ["944"], "MB", "Beta")
    # review item 2's fallback: no model_id -> the key is the display name
    rows += _task("C5", prompt, "2026-08-20T12:00:00Z", ["945"], "", "Gamma")
    rows += _task("C6", prompt, "2026-08-20T12:30:00Z", ["946"], "", "Gamma")
    _seed(tmp_path, rows)
    by_task, by_sid = G.compute_series(tmp_path / "catalog.db")
    assert set(by_sid) == {"C1", "C3", "C5"}        # never merged across models
    assert all(s["count_tasks"] == 2 for s in by_sid.values())
    assert by_task["C4"] == ("C3", 2)
    assert by_sid["C5"]["model"] == "Gamma"


# ---- (d) the 8h gap -------------------------------------------------------------------

def test_a_9h_gap_splits_two_series_a_7h_gap_does_not(tmp_path):
    prompt = "frost queen, glacial crown, aurora sky"
    rows = (_task("D1", prompt, "2026-08-20T10:00:00Z", ["951"])
            + _task("D2", prompt, "2026-08-20T10:30:00Z", ["952"])
            + _task("D3", prompt, "2026-08-20T19:30:00Z", ["953"])   # 9h after D2
            + _task("D4", prompt, "2026-08-20T20:00:00Z", ["954"]))
    _seed(tmp_path, rows)
    by_task, by_sid = G.compute_series(tmp_path / "catalog.db")
    assert set(by_sid) == {"D1", "D3"}
    assert by_task["D2"] == ("D1", 2) and by_task["D4"] == ("D3", 2)


def test_a_7h_gap_chains_one_series(tmp_path):
    prompt = "frost queen, glacial crown, aurora sky"
    rows = (_task("D1", prompt, "2026-08-20T10:00:00Z", ["961"])
            + _task("D2", prompt, "2026-08-20T10:30:00Z", ["962"])
            + _task("D3", prompt, "2026-08-20T17:30:00Z", ["963"])   # 7h after D2
            + _task("D4", prompt, "2026-08-20T18:00:00Z", ["964"]))
    _seed(tmp_path, rows)
    by_task, by_sid = G.compute_series(tmp_path / "catalog.db")
    assert set(by_sid) == {"D1"}
    assert by_sid["D1"]["count_tasks"] == 4


def test_two_empty_clause_sets_chain_as_identical(tmp_path):
    """Jaccard of two EMPTY sets is 1 (identical empties chain -- matches the
    validated board): prompts with nothing over 3 chars still dial together."""
    rows = (_task("E1", "ice", "2026-08-20T10:00:00Z", ["971"])
            + _task("E2", "ice", "2026-08-20T10:30:00Z", ["972"]))
    _seed(tmp_path, rows)
    by_task, by_sid = G.compute_series(tmp_path / "catalog.db")
    assert set(by_sid) == {"E1"}
    assert by_sid["E1"]["steps"][1]["reroll"] is True


# ---- (e) singletons cost nothing ------------------------------------------------------

def test_singleton_task_appears_in_no_series_response(tmp_path):
    rows = (_task("F1", "frost queen, glacial crown", "2026-08-20T10:00:00Z", ["981"])
            + _task("F2", "frost queen, glacial crown", "2026-08-20T10:30:00Z", ["982"])
            + _task("F9", "a lone unrelated moth portrait", "2026-08-21T10:00:00Z",
                    ["983"], "MZ", "Zeta"))
    _seed(tmp_path, rows)
    cli = _client(tmp_path)
    by = cli.post("/api/series",
                  json={"task_ids": ["F1", "F2", "F9"]}).get_json()["by_task"]
    assert set(by) == {"F1", "F2"}
    assert cli.get("/api/series/F9").status_code == 404


# ---- (f) blank task_id / blank created_at ---------------------------------------------

def test_blank_task_id_rows_are_excluded_and_blank_created_at_starts_fresh(tmp_path):
    prompt = "frost queen, glacial crown, aurora sky"
    rows = (_task("G1", prompt, "2026-08-20T10:00:00Z", ["991"])
            + _task("G2", prompt, "2026-08-20T10:30:00Z", ["992"])
            # no timestamp: gap is infinity BOTH ways -- G3 starts a new series
            # and G4 can't measure back to G3, so neither ever chains
            + _task("G3", prompt, "", ["993"])
            + _task("G4", prompt, "2026-08-20T11:30:00Z", ["994"])
            # imports: every one shares task_id '' -- the engine must never
            # weld them into one giant pseudo-series (same rule as /api/siblings)
            + [{"media_id": "998", "task_id": "", "prompt_full": prompt},
               {"media_id": "999", "task_id": "", "prompt_full": prompt}])
    _seed(tmp_path, rows)
    by_task, by_sid = G.compute_series(tmp_path / "catalog.db")
    assert set(by_sid) == {"G1"} and by_sid["G1"]["count_tasks"] == 2
    assert "G3" not in by_task and "G4" not in by_task
    assert "" not in by_task


# ---- (g) the cache: cheap key + 30s floor ---------------------------------------------

def test_cache_floor_holds_then_a_key_change_recomputes(tmp_path, monkeypatch):
    prompt = "frost queen, glacial crown, aurora sky"
    _seed(tmp_path, _task("H1", prompt, "2026-08-20T10:00:00Z", ["901"])
          + _task("H2", prompt, "2026-08-20T10:30:00Z", ["902"]))
    db = tmp_path / "catalog.db"
    by_task, _ = G.series_index(db)
    assert set(by_task) == {"H1", "H2"}
    # the live mirror writes a new task mid-sync...
    _seed(tmp_path, _task("H3", prompt, "2026-08-20T11:00:00Z", ["903"]))
    # ...the key changed, but the 30s floor holds: stale-but-recent is served
    by_task2, _ = G.series_index(db)
    assert set(by_task2) == {"H1", "H2"}, "the 30s recompute floor did not hold"
    # floor off: the changed key now recomputes and the new state is served
    monkeypatch.setattr(G, "_SERIES_RECOMPUTE_FLOOR_S", 0.0)
    by_task3, _ = G.series_index(db)
    assert set(by_task3) == {"H1", "H2", "H3"}
    # unchanged key: even with no floor, the cache is served (no recompute)
    assert G.series_index(db)[0] is by_task3


# ---- (h) route hygiene (mirrors /api/siblings) ----------------------------------------

def test_series_rejects_non_list_and_non_object_bodies(tmp_path):
    _seed(tmp_path, _task("K1", "frost queen", "2026-08-20T10:00:00Z", ["905"]))
    cli = _client(tmp_path)
    assert cli.post("/api/series", json={"task_ids": "K1"}).status_code == 400
    for body in ('["K1"]', '"K1"', '42'):
        r = cli.post("/api/series", data=body, content_type="application/json")
        assert r.status_code == 400, (body, r.status_code)
    assert cli.post("/api/series", json={}).get_json() == {"by_task": {}}


def test_series_caps_at_200_ids(tmp_path):
    prompt = "frost queen, glacial crown, aurora sky"
    rows = (_task("K0", prompt, "2026-08-20T10:00:00Z", ["906"], "MA", "Alpha")
            + _task("K1", prompt, "2026-08-20T10:30:00Z", ["907"], "MA", "Alpha")
            # a second real series, requested only PAST the cap
            + _task("K250", prompt, "2026-08-20T11:00:00Z", ["908"], "MB", "Beta")
            + _task("K251", prompt, "2026-08-20T11:30:00Z", ["909"], "MB", "Beta"))
    _seed(tmp_path, rows)
    cli = _client(tmp_path)
    ids = ["K%d" % i for i in range(300)]
    r = cli.post("/api/series", json={"task_ids": ids})
    assert r.status_code == 200
    assert set(r.get_json()["by_task"]) == {"K0", "K1"}
