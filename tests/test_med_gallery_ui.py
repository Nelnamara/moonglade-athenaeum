"""The gallery's INLINE JavaScript, tested where it actually lives.

Five findings from the 2026-07-27 adversarial review live in template strings inside
`moonglade_gallery.py` -- the star widget (M10), the bulk "Send to The Loom (cast)"
video filter (M14), the Edit tab's reference-cap truncation (M19), the saved-prompt
snippet delete (M26), and the browser half of M20: the drawer really can emit a value the
server clamps (`gateField()` takes a model's published `restrictions` verbatim), which is
what makes the clamp's receipt load-bearing rather than defensive. None of them are
reachable from Python: they are handler shapes and closure state in a `<script>` block.
So this module works the way the rest of the suite already does with embedded JS --
render the real page through the real client and assert on what came out -- with a
second, sharper instrument on top.

Two instruments, deliberately
-----------------------------
1. **Markup / handler shape.** Cheap, dependency-free, runs everywhere. It pins the
   thing a future edit is most likely to undo by accident: that the snippet x fires on
   `click` and not `mousedown`, that `bulkSendCast` no longer asks the DOM, that the
   star click handler has a `.catch`. Each assertion names the *old* string as well as
   the new one, so it fails against the pre-fix template rather than merely passing
   against the fixed one.
2. **Behaviour, executed.** `tests/test_js_syntax.py` already shells out to Node to prove
   the embedded JS *parses*; parsing is not behaviour. For the three findings whose bug
   is a state machine rather than an attribute -- the retry-clears-the-rating trap, the
   off-page video, the undo -- the function under test is lifted out of the rendered page
   by brace-matching and run in Node against a stub DOM small enough to read in one
   screen. That reproduces each finding's own repro steps literally, which a substring
   check cannot. Skips cleanly with no Node, exactly like test_js_syntax.py, and the
   shape assertions above stand alone when it does.

Nothing here monkeypatches or reaches into the app: every test starts from
`client.get('/classic')` or `client.get('/image/1')`.
"""
import json
import re
import shutil
import subprocess

import pytest

from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_client

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not installed")


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


@pytest.fixture
def client(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", prompt_preview="an image",
             created_at="2025-01-01T00:00:00"),
        _row(media_id="2", filename="b_2.mp4", prompt_preview="a clip", is_video="1",
             created_at="2025-01-02T00:00:00"),
    ])
    return login_client(tmp_path)


def _js_function(js, name):
    """Lift `function <name>(...) { ... }` out of a rendered page by brace matching.

    Regex alone cannot find the end of a JS function and a real parser is a dependency
    this suite does not have; brace counting is the honest middle. It is safe *for these
    specific functions* because none of them contains a brace inside a string literal or
    a comment -- which is a property of the code being extracted, so a future edit that
    breaks it will break loudly here (unbalanced source, Node syntax error) rather than
    silently extracting half a function.
    """
    m = re.search(r"function\s+" + re.escape(name) + r"\s*\(", js)
    if not m:
        return None
    start = js.index("{", m.end() - 1)
    depth = 0
    for i in range(start, len(js)):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                return js[m.start():i + 1]
    return None


def _uncommented(js):
    """Strip `// ...` so an "old shape is gone" assertion reads the CODE, not the prose.

    Not incidental: this codebase's house style is to name the failure a guard prevents,
    and the four fixes below all quote the exact line they replaced -- which is why they
    are legible, and why a naive substring check for the old code finds it in the comment
    explaining that it is gone.
    """
    return "\n".join(re.sub(r"//.*$", "", ln) for ln in js.splitlines())


def _run_node(tmp_path, source, name):
    """Run a stub-DOM harness and return the single JSON object it prints."""
    f = tmp_path / (name + ".js")
    f.write_text(source, encoding="utf-8")
    out = tmp_path / (name + ".out")
    err = tmp_path / (name + ".err")
    # Real files + DEVNULL stdin, matching test_js_syntax.py: some sandboxes here cannot
    # duplicate a pipe for a child process.
    with open(out, "wb") as fo, open(err, "wb") as fe:
        rc = subprocess.run([NODE, str(f)], stdout=fo, stderr=fe,
                            stdin=subprocess.DEVNULL, cwd=str(tmp_path)).returncode
    stdout = out.read_text(encoding="utf-8", errors="replace")
    stderr = err.read_text(encoding="utf-8", errors="replace")
    assert rc == 0, "node exited {}:\n{}\n{}".format(rc, stderr[:2000], stdout[:2000])
    return json.loads(stdout.strip().splitlines()[-1])


# The stub world the star tests run in. Shared, because M10 is a state machine with four
# reachable orderings (success, failure, two clicks in flight, an out-of-order answer) and
# a per-test copy of the DOM stub is how those four quietly start testing four slightly
# different widgets. `_delay(n)` decides how long the nth POST takes to answer, which is
# the only knob the ordering test needs.
_STAR_HARNESS_PRELUDE = """
var _posts = [], _fail = false, _delay = null;
function fetch(url, opts){
  var v = JSON.parse(opts.body).rating;
  _posts.push({url: url, rating: v});
  if(_fail) return Promise.reject(new Error('network down'));
  var res = {json: function(){ return Promise.resolve({ok: true, rating: v}); }};
  var wait = _delay ? _delay(_posts.length) : 0;
  if(!wait) return Promise.resolve(res);
  return new Promise(function(ok){ setTimeout(function(){ ok(res); }, wait); });
}
function mkEl(){
  var e = {_cls: {}, children: [], _h: {}, textContent: '', title: ''};
  e.classList = {add: function(c){ e._cls[c] = 1; }, remove: function(c){ delete e._cls[c]; },
                 toggle: function(c, on){ if(on) e._cls[c] = 1; else delete e._cls[c]; },
                 contains: function(c){ return !!e._cls[c]; }};
  e.addEventListener = function(t, f){ (e._h[t] = e._h[t] || []).push(f); };
  e.appendChild = function(c){ e.children.push(c); };
  e.querySelectorAll = function(){ return e.children; };
  e.click = function(){ (e._h.click || []).forEach(function(f){
    f({preventDefault: function(){}, stopPropagation: function(){}}); }); };
  return e;
}
var document = {createElement: function(){ return mkEl(); }};
var window = {};            // the detail page's world: no Toast loaded
function filled(box){ return box.children.map(function(b){ return !!b._cls.on; }); }
"""


def _star_code(html):
    """The four functions the widget is made of, lifted out of the rendered page."""
    code = "\n".join(filter(None, (
        _js_function(html, "setRating"),
        _js_function(html, "updateStars"),
        _js_function(html, "ratingFailed"),
        _js_function(html, "buildStars"),
    )))
    for name in ("setRating", "updateStars", "ratingFailed", "buildStars"):
        assert "function " + name in code, name + "() not found in the rendered page"
    return code


# ---------------------------------------------------------------------------
# M10 -- the star widget committed its rating before the server confirmed it
# ---------------------------------------------------------------------------

def test_star_click_handler_no_longer_commits_before_the_server_answers(client):
    """buildStars() used to run `rating = newVal;` one line above the POST, and
    setRating() had neither an else nor a .catch -- so a failed write left the closure
    at 4 while the stars showed 0.

    The two variables are the point. `confirmed` is what a failure rolls back to and the
    only thing safe to repaint from; `asked` is what the click-again-to-unrate gesture is
    computed against. Collapsing them into one is what produced the original finding, and
    then -- when the single variable stopped advancing instead -- its mirror image.
    """
    html = client.get("/classic").get_data(as_text=True)
    handler = _js_function(html, "buildStars")
    post = _js_function(html, "setRating")
    assert handler and post, "buildStars()/setRating() not found in the rendered page"

    assert "rating = newVal;" not in _uncommented(handler)     # the optimistic commit
    assert "if (data.ok) updateStars" not in _uncommented(post)  # success-only, no rollback

    assert ".catch(function(err)" in handler, "a failed rating POST is still unhandled"
    assert "confirmed = asked = stored;" in handler, (
        "the closure must take the value the SERVER stored")
    assert "asked = confirmed;" in handler, (
        "without the rollback, the optimistic value survives a failed write -- which is the "
        "original finding, one variable over")
    assert "ratingFailed(" in handler


def test_rating_failure_is_surfaced_on_the_detail_page_which_has_no_toast(client):
    """The detail page does not load static/mg-notify.js, so `window.Toast` is undefined
    there -- and the detail page carries the biggest star widget on the site. Assert both
    halves of ratingFailed() ship, and that the fallback has CSS behind it."""
    html = client.get("/image/1").get_data(as_text=True)
    assert "/static/mg-notify.js" not in html, (
        "the detail page now loads mg-notify.js -- if that is intended, ratingFailed()'s "
        "no-Toast fallback and this test can both be simplified")
    fn = _js_function(html, "ratingFailed")
    assert fn, "ratingFailed() not found -- a failed rating is silent again"
    assert "Toast.show(" in fn and "rate-fail" in fn
    assert "alert(" not in _uncommented(fn)
    assert ".stars.rate-fail button" in html, "the no-Toast fallback has no styling"


@needs_node
def test_retrying_a_failed_rating_sends_the_rating_not_a_clear(client, tmp_path):
    """The finding's repro, executed. Click star 4 with the network down, then click
    star 4 again. The second POST must carry rating 4.

    Against the old code the closure had already advanced to 4, so `(rating === star)`
    made the retry compute 0 and the user's second click CLEARED the rating -- the
    opposite of what they pressed, with no error shown at any point.
    """
    html = client.get("/image/1").get_data(as_text=True)
    harness = _STAR_HARNESS_PRELUDE + _star_code(html) + """
_fail = true;
var box = mkEl();
box.parentElement = {querySelector: function(){ return null; }};
buildStars('m1', 0, box);
box.children[3].click();                      // star 4, POST fails
setTimeout(function(){
  var afterFail = {filled: filled(box), flagged: !!box._cls['rate-fail'], title: box.title};
  _fail = false;
  box.children[3].click();                    // the user's natural retry
  setTimeout(function(){
    console.log(JSON.stringify({sent: _posts.map(function(p){ return p.rating; }),
                                url: _posts[0].url, afterFail: afterFail, filled: filled(box)}));
  }, 40);
}, 40);
"""
    r = _run_node(tmp_path, harness, "stars")
    assert r["url"] == "/rate/m1"
    assert r["sent"] == [4, 4], "the retry submitted {} -- clicking 4 twice must never clear".format(r["sent"])
    assert r["afterFail"]["filled"] == [False] * 5, "a failed write must not paint stars"
    assert r["afterFail"]["flagged"] is True, "the failure was never surfaced"
    assert "Rating not saved" in r["afterFail"]["title"]
    assert r["filled"] == [True, True, True, True, False], "the confirmed 4 never landed"


@needs_node
def test_clicking_the_same_star_twice_still_unrates_before_the_write_lands(client, tmp_path):
    """The regression the M10 repair introduced, executed.

    "Click it, click it again to unrate" is a deliberate gesture, and both clicks land
    inside one round trip -- the server is on localhost, so the window is the whole
    interaction. Once `rating` stopped advancing until the response came back, the second
    click recomputed `(rating === star)` from the same un-advanced 0 and POSTed 4 a second
    time: the gesture became a no-op, and the image kept a rating the owner had just asked
    to remove. Both writes succeed here -- this is the happy path, not a failure case.
    """
    html = client.get("/image/1").get_data(as_text=True)
    harness = _STAR_HARNESS_PRELUDE + _star_code(html) + """
var box = mkEl();
box.parentElement = {querySelector: function(){ return null; }};
buildStars('m1', 0, box);
box.children[3].click();      // star 4 -- rate it
box.children[3].click();      // star 4 again, still in flight -- unrate it
setTimeout(function(){
  console.log(JSON.stringify({sent: _posts.map(function(p){ return p.rating; }),
                              filled: filled(box)}));
}, 40);
"""
    r = _run_node(tmp_path, harness, "stars_toggle")
    assert r["sent"] == [4, 0], (
        "the second click sent {} -- clicking a lit star again must clear it, in flight or "
        "not".format(r["sent"]))
    assert r["filled"] == [False] * 5, "the widget still shows a rating the server cleared"


@needs_node
def test_a_failed_write_still_rolls_the_gesture_back(client, tmp_path):
    """The optimistic value is only safe because a failure returns it to what the database
    holds. Rate 4 and confirm it, then try 5 with the network down: the widget must go back
    to showing 4, AND the next click on star 4 must read as "clear it" -- i.e. the rollback
    moved the gesture's own state, not just the pixels."""
    html = client.get("/image/1").get_data(as_text=True)
    harness = _STAR_HARNESS_PRELUDE + _star_code(html) + """
var box = mkEl();
box.parentElement = {querySelector: function(){ return null; }};
buildStars('m1', 0, box);
box.children[3].click();                       // 4, succeeds
setTimeout(function(){
  _fail = true;
  box.children[4].click();                     // 5, fails
  setTimeout(function(){
    var afterFail = {filled: filled(box), flagged: !!box._cls['rate-fail']};
    _fail = false;
    box.children[3].click();                   // star 4 again: it is lit, so this clears
    setTimeout(function(){
      console.log(JSON.stringify({sent: _posts.map(function(p){ return p.rating; }),
                                  afterFail: afterFail, filled: filled(box)}));
    }, 40);
  }, 40);
}, 40);
"""
    r = _run_node(tmp_path, harness, "stars_rollback")
    assert r["sent"] == [4, 5, 0]
    assert r["afterFail"]["filled"] == [True, True, True, True, False], (
        "a failed 5 must leave the confirmed 4 on screen")
    assert r["afterFail"]["flagged"] is True
    assert r["filled"] == [False] * 5


@needs_node
def test_a_slow_response_cannot_repaint_over_a_newer_click(client, tmp_path):
    """Two clicks, first response deliberately slow. The stale answer must not move the
    widget back: `seq` means only the newest write may repaint or advance the confirmed
    value, which is why setRating no longer paints from inside its own resolve -- from
    there it cannot know it has been superseded."""
    html = client.get("/image/1").get_data(as_text=True)
    harness = _STAR_HARNESS_PRELUDE + _star_code(html) + """
_delay = function(n){ return n === 1 ? 60 : 0; };   // the FIRST POST answers last
var box = mkEl();
box.parentElement = {querySelector: function(){ return null; }};
buildStars('m1', 0, box);
box.children[1].click();      // 2, slow
box.children[4].click();      // 5, fast
setTimeout(function(){
  console.log(JSON.stringify({sent: _posts.map(function(p){ return p.rating; }),
                              filled: filled(box)}));
}, 150);
"""
    r = _run_node(tmp_path, harness, "stars_order")
    assert r["sent"] == [2, 5]
    assert r["filled"] == [True] * 5, (
        "the slow first response repainted over the newer one -- the widget now disagrees "
        "with the last write the database took")


# ---------------------------------------------------------------------------
# M20 -- the drawer CAN emit a value the server clamps, which is why it is reported
# ---------------------------------------------------------------------------

@needs_node
def test_a_published_restriction_wider_than_the_drawer_really_does_widen_the_field(client, tmp_path):
    """Pinned deliberately, because the comment beside the server clamp used to assert the
    opposite and a reader who believes it will conclude the receipt is dead code.

    gateField() REPLACES the control's min/max with whatever `restrictions` carries; it
    does not clip them. Every restriction PixAI has been seen to publish is narrower, but
    `restrictions` is live remote data, so samplingSteps.max = 200 makes the drawer's own
    #gen-steps offer 200, the POST carries 200, and _gen_args_from_payload clamps it to 150
    on the way to a PAID submit. That path is real, which is why /api/generate reports the
    clamp instead of quietly billing the difference (see tests/test_med_gallery_routes.py).

    If this ever starts failing because gateField learned to clip, that is a genuine
    improvement -- delete this test and say so; do not weaken the report that stands in
    for it today.
    """
    html = client.get("/classic").get_data(as_text=True)
    fn = _js_function(html, "gateField")
    assert fn, "gateField() not found in the rendered page"
    harness = """
var _f = {};
function el(id){ return _f[id]; }
function mkField(){ return {min: null, max: null, disabled: false, title: '',
  classList: {toggle: function(){}}}; }
__CODE__
function gate(bounds, lo, hi){
  _f.x = mkField();
  gateField('x', true, bounds, lo, hi);
  return {min: _f.x.min, max: _f.x.max};
}
console.log(JSON.stringify({
  narrower: gate({min: 16, max: 50}, 1, 150),
  wider:    gate({min: 0, max: 200}, 1, 150),
  none:     gate(null, 1, 150)
}));
""".replace("__CODE__", fn)
    r = _run_node(tmp_path, harness, "gatefield")
    assert r["narrower"] == {"min": 16, "max": 50}, "a genuine restriction stopped applying"
    assert r["wider"] == {"min": 0, "max": 200}, (
        "gateField now clips the published bounds -- the drawer can no longer emit a value "
        "the server clamps, so this test has been superseded (see its docstring)")
    assert r["none"] == {"min": 1, "max": 150}


def test_a_clamped_submit_is_reported_where_the_submit_is_reported(client):
    """The server hands back `adjusted` when a clamp fired (see tests/test_med_gallery_routes.py);
    something has to draw it, or the receipt is a key nobody reads. runTask owns every
    submit response in this drawer, so it is where the report belongs."""
    html = client.get("/classic").get_data(as_text=True)
    fn = _js_function(html, "runTask")
    assert fn, "runTask() not found in the rendered page"
    assert "d.adjusted" in fn, (
        "a clamped, already-charged submit is reported nowhere -- the silent substitution "
        "the clamp introduced is back")
    assert "Toast.show(" in fn
    assert fn.index("d.adjusted") > fn.index("d.task_id"), (
        "the receipt must be drawn on the accepted-submit path, not the error path")


# ---------------------------------------------------------------------------
# M14 -- the cast filter asked the DOM about a selection that outlives the page
# ---------------------------------------------------------------------------

def test_lowering_the_edit_reference_cap_tells_the_user_what_it_dropped(client):
    """setEditModel()'s `editRefs.slice(0, maxAdd)` had no message of any kind, while the
    near-identical truncation in bulkSendVideo has always toasted."""
    html = client.get("/classic").get_data(as_text=True)
    assert "if(editRefs.length>maxAdd) editRefs=editRefs.slice(0,maxAdd);" not in html, (
        "the silent one-line truncation is back")
    fn = _js_function(html, "setEditModel")
    assert fn, "setEditModel() not found in the rendered page"
    assert "editRefs.slice(0,maxAdd)" in fn
    assert "Toast.show(" in fn, "references are dropped without telling anyone again"
    # Same register as bulkSendVideo's cap toast, which says '... were left out.'
    assert "were left out" in fn
    assert fn.index("Toast.show(") > fn.index("var maxAdd"), (
        "the toast must belong to the cap truncation, not to something earlier")


# ---------------------------------------------------------------------------
# M26 -- one stray press permanently deleted a saved prompt
# ---------------------------------------------------------------------------

def test_snippet_delete_fires_on_click_not_mousedown(client):
    """mousedown commits before the button is released, so there is no
    press-then-slide-away-to-cancel -- on a control 4px from 'insert' in a 220-340px
    popover."""
    html = client.get("/classic").get_data(as_text=True)
    assert 'onmousedown="event.preventDefault();Snips.del(' not in html, (
        "the snippet delete is armed on mousedown again")
    assert 'onclick="event.stopPropagation();Snips.del(' in html
    # Insert is untouched -- it is not destructive and keeps its focus-preserving mousedown.
    assert 'onmousedown="event.preventDefault();Snips.insert(' in html


def test_snippet_delete_offers_an_undo_instead_of_a_confirm(client):
    html = client.get("/classic").get_data(as_text=True)
    assert "Snips.undo()" in html, "a deleted snippet is unrecoverable again"
    assert "snip-undo" in html, "the undo affordance has no row to live in"
    assert "#snip-menu .snip-undo{" in html, "the undo row has no styling"
    fn = _js_function(html, "del")
    assert fn, "Snips.del() not found in the rendered page"
    assert "pendingUndo=" in fn
    assert "confirm(" not in _uncommented(fn), (
        "a modal on every delete is friction paid by the deletes that were meant -- "
        "if this is now wanted, it is an owner decision, not a drive-by")


@needs_node
def test_deleting_a_snippet_can_be_undone_and_the_undo_is_persisted(client, tmp_path):
    """del() then undo() must restore the snippet AT ITS OLD INDEX and POST the restored
    list, not just repaint the popover -- the delete already reached /api/snippets."""
    html = client.get("/classic").get_data(as_text=True)
    code = "\n".join(filter(None, (_js_function(html, "del"), _js_function(html, "undo"))))
    assert "function del(" in code and "function undo(" in code

    harness = """
var window = {}, _persisted = [], pendingUndo = null;
var list = ['alpha', 'beta', 'gamma'];
function persist(){ _persisted.push(list.slice()); }
function render(){}
// reflow() re-measures the popover's on-screen position after a re-render changes its
// height (the undo strip appearing/disappearing). Pure DOM geometry, no bearing on the
// list arithmetic this test pins -- stubbed so the lifted del()/undo() can run headless.
function reflow(){}
__CODE__
del(1);
var afterDel = list.slice();
undo();
console.log(JSON.stringify({afterDel: afterDel, afterUndo: list.slice(),
                            persisted: _persisted}));
""".replace("__CODE__", code)

    r = _run_node(tmp_path, harness, "snips")
    assert r["afterDel"] == ["alpha", "gamma"]
    assert r["afterUndo"] == ["alpha", "beta", "gamma"], "undo did not restore in place"
    assert r["persisted"] == [["alpha", "gamma"], ["alpha", "beta", "gamma"]], (
        "the undo never reached /api/snippets, so a reload would lose it again")


# --- M14 (closed by origin/master's selectedVideoIds, which arrived for H16) ------------
#
# M14 and H16 are the same defect in sibling functions: an images-only bulk action asking
# `document.getElementById('card-'+mid)` whether a SELECTED id is a video. The selection is
# persisted in localStorage and deliberately outlives the page it was made on, so for a video
# ticked on page 2 that lookup returns null on page 1, the `card &&` guard is skipped, and the
# video rides into a destination whose own comment says it cannot.
#
# The med-review branch fixed M14 with a persisted id->kind map; master fixed H16 with
# selectedVideoIds(), which asks the server for the ids this page cannot see and serves BOTH
# call sites. Master's is the better instrument -- it is right for a selection persisted before
# any map existed -- so the duplicate was dropped in favour of it during the rebase. These
# tests came with the duplicate and are re-pointed at the survivor rather than deleted: nothing
# in the suite covered selectedVideoIds, and M14 would otherwise close with no test at all.

def test_bulk_send_cast_does_not_ask_the_dom_directly_whether_a_selection_is_video(client):
    """The shape assertion, naming the OLD line so it fails against the pre-fix template."""
    html = client.get("/classic").get_data(as_text=True)
    fn = _uncommented(_js_function(html, "bulkSendCast"))
    assert fn, "bulkSendCast() is gone -- if it was renamed, re-point this test"
    assert "selectedVideoIds(" in fn
    assert "getElementById('card-'" not in fn, (
        "the DOM lookup is back inside bulkSendCast; it cannot answer for an off-page id")


@needs_node
def test_a_video_selected_on_a_page_this_one_cannot_render_stays_out_of_the_cast(client,
                                                                                tmp_path):
    """M14's own repro, executed: select an image and a video on page 2, navigate to page 1
    where neither card is rendered, then Actions -> Send to The Loom (cast).

    Both ids are unseen here, so the DOM can answer for neither and selectedVideoIds falls
    back to /api/image-meta -- which is the whole point of master's version over a map. The
    video must not reach the cast URL.
    """
    html = client.get("/classic").get_data(as_text=True)
    src = _js_function(html, "selectedVideoIds")
    assert src, "selectedVideoIds() is gone -- M14/H16 lost their only coverage"
    harness = """
var _store = {'gallery_sel': '["img1","vid1"]'};
var localStorage = { getItem: function(k){ return _store[k] || null; },
                     setItem: function(k,v){ _store[k] = String(v); },
                     removeItem: function(k){ delete _store[k]; } };
// page 1: NEITHER selected card is rendered, which is the whole finding
var document = { getElementById: function(){ return null; } };
var asked = [];
var fetch = function(url){
  asked.push(url);
  var isVid = url.indexOf('vid1') !== -1;
  return Promise.resolve({ ok: true, json: function(){ return Promise.resolve({is_video: isVid}); } });
};
function selGet() { try { return new Set(JSON.parse(localStorage.getItem('gallery_sel') || '[]')); } catch(e) { return new Set(); } }
__FN__
var ids = Array.from(selGet());
selectedVideoIds(ids).then(function(vids){
  var keep = ids.filter(function(mid){ return !vids.has(mid); });
  console.log(JSON.stringify({keep: keep, videos: Array.from(vids), asked: asked.length}));
});
""".replace("__FN__", src)
    got = _run_node(tmp_path, harness, "m14_offpage")
    assert got["keep"] == ["img1"], "the off-page video reached the Loom cast"
    assert got["videos"] == ["vid1"]
    assert got["asked"] == 2, (
        "both ids were unseen, so both had to be resolved server-side -- a DOM-only "
        "answer is exactly the bug")


def test_the_snippet_popover_is_re_measured_whenever_its_size_changes(client):
    """Owner-reported 2026-07-28, with a screenshot: after deleting a snippet the popover's
    header and Undo button were clipped at the right edge.

    Not a styling bug. `place()` ran exactly once, at open, and clamped `left` against the
    width the popover had THEN -- its 220px minimum, because the list was empty. Deleting
    adds the undo strip, whose quoted snippet text pushes the box out to its 340px maximum,
    and nothing re-clamped: the box grew rightward past the viewport edge it had already been
    positioned against. Every re-render that can change the popover's size has to re-measure,
    which is what reflow() is for.
    """
    html = client.get("/classic").get_data(as_text=True)
    assert "function reflow()" in html, "the re-measure helper is gone"
    reflow = _js_function(html, "reflow")
    assert "place(" in reflow, "reflow() must re-run the placement, not just redraw"

    for name in ("del", "undo", "saveCurrent"):
        fn = _uncommented(_js_function(html, name))
        assert fn, name + "() not found in the rendered page"
        assert "render()" in fn, name + "() no longer re-renders -- re-point this test"
        assert "reflow()" in fn, (
            name + "() re-renders the popover without re-measuring it; a size change that "
            "moves an edge past the viewport is exactly the clipping this closed")

    assert "max-height:min(300px, calc(100vh - 16px))" in html, (
        "the popover's height ceiling must also respect a short viewport")
