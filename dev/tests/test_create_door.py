"""THE create door (DESIGN_3.22 2.2-2.6, step S2a): `PixAIClient.create`.

Driven over a mocked requests.Session, the way test_spend_no_retry.py drives rest_post: the
session's `post` records every call and answers (or raises) what the test set, so what is
asserted is what would have gone on the wire -- the exact bytes, the redirect flag, the
timeout, and how many POSTs. FakePixAI is not used here; it serves the road-level tests above
the door. Recorded bodies follow the harvested schema (BaseTaskSubmitForm-BYhygXK9.js) and the
probe answers, never invention. Nothing here touches the network.
"""
import ast
import inspect
import json
import textwrap

import pytest
import requests

from moonglade import backup as core
from moonglade import gen_params
from moonglade import gen_road
from moonglade import mirror as mirror_mod
from moonglade import pixai_client as pc


class _Answer:
    def __init__(self, status=200, body=None, text=None, not_json=False):
        self.status_code = status
        self._body = body
        self._not_json = not_json
        self.text = text if text is not None else ("" if body is None else json.dumps(body))
        self.headers = {}

    @property
    def ok(self):
        return 200 <= self.status_code < 400

    def json(self):
        if self._not_json:
            raise ValueError("not json")
        return self._body


class _Session:
    """A requests.Session stand-in: records each POST and answers the one thing it was set."""

    def __init__(self, answer=None, raises=None):
        self.posts = []
        self._answer = answer if answer is not None else _Answer(200, {"id": "T1"})
        self._raises = raises
        self.headers = {}

    def post(self, url, **kw):
        self.posts.append((url, kw))
        if self._raises is not None:
            raise self._raises
        return self._answer

    def get(self, *a, **k):                                  # pragma: no cover
        raise AssertionError("the door never GETs")


def _client(answer=None, raises=None, auth_kind="api-key"):
    s = _Session(answer, raises)
    return pc.PixAIClient(s, auth_kind=auth_kind), s


def _sent(s):
    """The one POST's (url, decoded body, kwargs)."""
    (url, kw), = s.posts
    return url, json.loads(kw["data"].decode("utf-8")), kw


IMAGE_P = {"prompts": "a cat", "modelId": "1983308862240288769", "width": 512, "height": 512,
           "samplingSteps": 25, "cfgScale": 7, "batchSize": 1, "priority": 0,
           "promptHelper": {"withStage": True, "userWantToEnable": True,
                            "forcePromptHelperDetectionSide": "server"}}
EDIT_P = {"chat": {"prompts": "make it night", "mediaId": "111", "mediaIds": ["111", "222"],
                   "modelId": gen_params.EDIT_PRO_MODEL_ID,
                   "modelConfig": {"resolution": "1K", "aspectRatio": "3:5",
                                   "quality": "medium"}}}
SCENE_B = {"sceneId": "character-card", "mediaIds": ["111"], "preset": "random",
           "selectorValues": [{"id": "aspect", "value": "3:4"}]}
ENHANCE_B = {"enhanceType": "background-remover", "mediaId": "111"}
FIX_B = {"mediaId": "111", "boxes": [{"x": 1, "y": 2, "width": 30, "height": 40, "tag": "hand"}]}


@pytest.fixture(autouse=True)
def _writable(monkeypatch):
    monkeypatch.setattr(core, "READ_ONLY", False)
    monkeypatch.setattr(core, "_read_only_now", lambda: False)


# ---------------------------------------------------------------------------
# One POST, never a redirect, never a retry
# ---------------------------------------------------------------------------

class TestOnePostEveryTime:
    CASES = [
        ("200 with an id", dict(answer=_Answer(200, {"id": "T1"})), None),
        ("read timeout", dict(raises=requests.ReadTimeout("slow")), core.CreateOutcomeUnknown),
        ("connection dropped", dict(raises=requests.ConnectionError("gone")),
         core.CreateOutcomeUnknown),
        ("503", dict(answer=_Answer(503, {"code": "SERVICE_UNAVAILABLE"})), core.PixAIRestError),
        ("307", dict(answer=_Answer(307, None)), core.CreateOutcomeUnknown),
        ("200 html", dict(answer=_Answer(200, None, text="<html>", not_json=True)),
         core.CreateOutcomeUnknown),
        ("200 without an id", dict(answer=_Answer(200, {"task": {}})), core.CreateOutcomeUnknown),
        ("200 with a blank id", dict(answer=_Answer(200, {"id": "  "})), core.CreateOutcomeUnknown),
        ("200 with a numeric id", dict(answer=_Answer(200, {"id": 7})), core.CreateOutcomeUnknown),
        ("408 with an oRPC body", dict(answer=_Answer(408, {"code": "BAD_REQUEST"})),
         core.PixAIRestError),
        ("499", dict(answer=_Answer(499, {"code": "BAD_REQUEST"})), core.PixAIRestError),
        ("bare 403", dict(answer=_Answer(403, None, text="<html>Forbidden</html>",
                                         not_json=True)), core.PixAIRestError),
    ]

    @pytest.mark.parametrize("name, how, raised", CASES, ids=[c[0] for c in CASES])
    def test_exactly_one_post_never_following_a_redirect(self, name, how, raised):
        client, s = _client(**how)
        if raised is None:
            assert client.create("image", IMAGE_P)["id"] == "T1"
        else:
            with pytest.raises(raised) as ei:
                client.create("image", IMAGE_P)
            if raised is not core.CreateOutcomeUnknown:
                # every non-2xx but a definite code is an unknown outcome (2.6)
                assert gen_road.classify_outcome(ei.value) == "unknown"
        assert len(s.posts) == 1, name
        _url, kw = s.posts[0]
        assert kw["allow_redirects"] is False
        assert kw["timeout"] == (10, 120)

    def test_the_door_offers_no_retries_and_has_no_loop(self):
        assert "retries" not in inspect.signature(pc.PixAIClient.create).parameters
        from tests.conftest import _REAL_CREATE            # core._create is blocked in tests
        assert list(inspect.signature(_REAL_CREATE).parameters) == ["session", "kind", "body"]
        for fn in (pc.PixAIClient.create, _REAL_CREATE):
            tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
            loops = [n for n in ast.walk(tree)
                     if isinstance(n, (ast.For, ast.AsyncFor, ast.While, ast.ListComp,
                                       ast.SetComp, ast.DictComp, ast.GeneratorExp))]
            assert not loops, "the create door grew a loop: a second POST pays twice"
        calls = [n for n in ast.walk(ast.parse(textwrap.dedent(
            inspect.getsource(pc.PixAIClient.create))))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        on_session = [n.func.attr for n in calls
                      if isinstance(n.func.value, ast.Attribute) and n.func.value.attr == "_session"]
        assert on_session == ["post"]                     # ONE send, on the chosen session
        assert not [n for n in calls if n.func.attr in ("rest_post", "mutate", "query", "put",
                                                         "patch", "request")]

    def test_create_outcome_unknown_is_not_a_pixai_error(self):
        assert not issubclass(core.CreateOutcomeUnknown, core.PixAIError)
        assert issubclass(core.CreateOutcomeUnknown, core.PixAIOutcomeError)
        e = core.CreateOutcomeUnknown("x", kind="image")
        assert gen_road.classify_outcome(e) == "unknown"
        assert gen_road.definite_refusal(e) is False
        assert gen_road.send_outcome(e, True) == "may_have_started"

    def test_a_connection_error_is_chained_and_unknown(self):
        client, s = _client(raises=requests.ConnectionError("gone"))
        with pytest.raises(core.CreateOutcomeUnknown) as ei:
            client.create("fix", FIX_B)
        assert isinstance(ei.value.__cause__, requests.ConnectionError)
        assert ei.value.kind == "fix"


# ---------------------------------------------------------------------------
# The path table and the quote-path tripwires
# ---------------------------------------------------------------------------

class TestPathTable:
    @pytest.mark.parametrize("kind, body, path", [
        ("image", IMAGE_P, "/task/create"), ("edit", EDIT_P, "/task/create"),
        ("scene", SCENE_B, "/task/chat-editing-scene"), ("enhance", ENHANCE_B, "/task/enhance"),
        ("fix", FIX_B, "/task/fixer")])
    def test_each_kind_posts_to_its_one_route(self, kind, body, path):
        client, s = _client(auth_kind="web-jwt")
        client.create(kind, body)
        url, _b, _kw = _sent(s)
        assert url == core.REST_API_BASE + path

    @pytest.mark.parametrize("kind", ["video", "refvideo", "/task/fixer/price", "", None,
                                      "IMAGE", "image "])
    def test_a_kind_outside_the_table_is_refused_with_nothing_sent(self, kind):
        client, s = _client()
        with pytest.raises(core.LocalRefusal):
            client.create(kind, IMAGE_P)
        assert s.posts == []

    def test_no_door_path_is_a_quote_route(self):
        assert pc.CREATE_PATHS == {"image": "/task/create", "edit": "/task/create",
                                   "scene": "/task/chat-editing-scene",
                                   "enhance": "/task/enhance", "fix": "/task/fixer"}
        assert not set(pc.CREATE_PATHS.values()) & pc.CREATE_QUOTE_PATHS
        from moonglade import pricing
        assert pricing._FIXER_PRICE_PATH == "/task/fixer/price"
        assert pricing._FIXER_PRICE_PATH in pc.CREATE_QUOTE_PATHS
        assert "/task/enhance/price" in pc.CREATE_QUOTE_PATHS

    def test_the_tripwire_is_an_if_not_an_assert(self):
        src = inspect.getsource(pc)
        assert "raise ImportError(\"CREATE_PATHS must be exactly" in src


# ---------------------------------------------------------------------------
# The wire guard, on the exact bytes the mocked post received
# ---------------------------------------------------------------------------

class TestWireGuard:
    def test_golden_image_body_with_the_card_inside_parameters(self):
        client, s = _client()
        client.create("image", dict(IMAGE_P, kaisuukenId="K1"))
        _url, body, kw = _sent(s)
        assert body == {"parameters": dict(IMAGE_P, kaisuukenId="K1")}
        assert body["parameters"]["kaisuukenId"] == "K1" and "kaisuukenId" not in body
        assert kw["data"] == json.dumps(body, separators=(",", ":"),
                                        ensure_ascii=False).encode("utf-8")
        assert kw["headers"] == {"Content-Type": "application/json"}

    def test_golden_edit_scene_enhance_fix_bodies(self):
        for kind, body, want in (("edit", EDIT_P, {"parameters": EDIT_P}),
                                 ("scene", SCENE_B, SCENE_B),
                                 ("enhance", ENHANCE_B, ENHANCE_B),
                                 ("fix", FIX_B, FIX_B)):
            client, s = _client(auth_kind="web-jwt")
            client.create(kind, body)
            assert _sent(s)[1] == want, kind

    @pytest.mark.parametrize("kind, body, where", [
        ("edit", {"chat": dict(EDIT_P["chat"], modelConfig={"resolution": "1K",
                                                             "outputFormatt": "png"})},
         "modelConfig.outputFormatt"),
        ("image", dict(IMAGE_P, promptHelper={"enable": True, "extra": 1}),
         "promptHelper.extra"),
        ("edit", dict(EDIT_P, extra={"foo": "x"}), "extra.foo"),
        ("image", dict(IMAGE_P, loraParameters=[{"versionId": "1", "weight": 1, "bad": 2}]),
         "loraParameters[0].bad"),
        ("image", dict(IMAGE_P, colorPalette={"name": "n", "palette": {
            "overall": {"colors": [{"hex": "#FFFFFF", "ratio": 1, "alpha": 1}]}}}),
         "colors[0].alpha"),
        ("image", dict(IMAGE_P, controlNets=[{"type": "x", "mediaId": "1", "extra": {}}]),
         "controlNets[0].extra"),
        ("image", dict(IMAGE_P, newKnob=True), "newKnob"),
        ("scene", dict(SCENE_B, extra=1), "extra"),
        ("enhance", dict(ENHANCE_B, strength=0.5), "strength"),
        ("fix", dict(FIX_B, boxes=[dict(FIX_B["boxes"][0], label="x")]), "boxes[0].label"),
        ("image", dict(IMAGE_P, promptHelper="on"), "promptHelper"),
        ("image", dict(IMAGE_P, prompts={"nested": "x"}), "prompts"),
    ])
    def test_an_unknown_key_at_any_depth_is_refused_never_stripped(self, kind, body, where):
        client, s = _client(auth_kind="web-jwt")
        with pytest.raises(core.LocalRefusal) as ei:
            client.create(kind, body)
        assert where in str(ei.value)
        assert s.posts == []

    def test_naturalprompts_at_the_top_level_is_refused(self):
        """PixAI's `yt` has no top-level naturalPrompts (it lives under `extra`, where the site
        nests it), so REST would drop one silently. The guard refuses a stray one (a
        --params-json, a hand-built dict); _gen_parameters writes it under `extra`, which
        passes (test_create_roads: the builder's Tsubaki.2 image over the real door)."""
        client, s = _client()
        with pytest.raises(core.LocalRefusal, match="naturalPrompts"):
            client.create("image", dict(IMAGE_P, naturalPrompts="a cat"))
        client.create("image", dict(IMAGE_P, extra={"naturalPrompts": "a cat"}))
        assert len(s.posts) == 1

    @pytest.mark.parametrize("kind, body", [
        ("scene", dict(SCENE_B, kaisuukenId="K1")),
        ("enhance", dict(ENHANCE_B, kaisuukenId="K1")),
        ("fix", dict(FIX_B, kaisuukenId="K1")),
        ("image", dict(IMAGE_P, kaisuukenId="K1", kaisuukenExtraCredits=100)),
        ("edit", dict(EDIT_P, kaisuukenExtraCredits=0)),
        ("scene", dict(SCENE_B, kaisuukenExtraCredits=1)),
    ])
    def test_cards_never_ride_a_cardless_kind_and_extra_credits_never_go(self, kind, body):
        client, s = _client(auth_kind="web-jwt")
        with pytest.raises(core.LocalRefusal, match="free card"):
            client.create(kind, body)
        assert s.posts == []

    def test_isprivate_becomes_the_channel_and_a_disagreeing_pair_is_refused(self):
        client, s = _client()
        client.create("image", dict(IMAGE_P, isPrivate=True, enablePreview=True,
                                    hidePrompts=False))
        p = _sent(s)[1]["parameters"]
        assert p["channel"] == "private"
        assert not {"isPrivate", "enablePreview", "hidePrompts"} & set(p)
        client, s = _client()
        client.create("image", dict(IMAGE_P, isPrivate=False))
        assert _sent(s)[1]["parameters"]["channel"] == "normal"
        client, s = _client()
        client.create("image", dict(IMAGE_P, isPrivate=True, channel="private"))
        assert _sent(s)[1]["parameters"]["channel"] == "private"
        for pair in ({"isPrivate": True, "channel": "normal"},
                     {"isPrivate": False, "channel": "private"},
                     {"isPrivate": "yes"}):
            client, s = _client()
            with pytest.raises(core.LocalRefusal):
                client.create("image", dict(IMAGE_P, **pair))
            assert s.posts == []

    @pytest.mark.parametrize("key", gen_params.WIRE_WORKFLOW_KEYS)
    def test_workflow_keys_are_refused_on_task_create(self, key):
        client, s = _client()
        with pytest.raises(core.LocalRefusal, match="workflow"):
            client.create("image", dict(IMAGE_P, **{key: "x"}))
        assert s.posts == []

    @pytest.mark.parametrize("extra, ok", [
        ({"channel": "secret"}, False), ({"lane": "fast"}, False), ({"watermark": "none"}, False),
        ({"channel": "private", "lane": "infinite", "watermark": "pixai"}, True)])
    def test_value_rules(self, extra, ok):
        client, s = _client()
        if ok:
            client.create("image", dict(IMAGE_P, **extra))
            assert len(s.posts) == 1
        else:
            with pytest.raises(core.LocalRefusal):
                client.create("image", dict(IMAGE_P, **extra))
            assert s.posts == []

    @pytest.mark.parametrize("mc, ok", [
        ({"outputFormat": "gif", "frameCount": 9, "frameDurationMs": 200}, True),
        ({"outputFormat": "svg"}, True), ({"outputFormat": "png", "background": "transparent"}, True),
        ({"outputFormat": "jpeg"}, False), ({"outputFormat": "png", "frameCount": 9}, False),
        ({"outputFormat": "gif", "frameCount": 17}, False),
        ({"outputFormat": "gif", "frameDurationMs": 10}, False),
        ({"outputFormat": "gif", "frameCount": True}, False)])
    def test_edit_output_format_rules(self, mc, ok):
        body = {"chat": dict(EDIT_P["chat"], modelConfig=dict(EDIT_P["chat"]["modelConfig"], **mc))}
        client, s = _client()
        if ok:
            client.create("edit", body)
            assert len(s.posts) == 1
        else:
            with pytest.raises(core.LocalRefusal):
                client.create("edit", body)
            assert s.posts == []

    def test_a_value_that_is_not_json_is_refused(self):
        client, s = _client()
        with pytest.raises(core.LocalRefusal):
            client.create("image", dict(IMAGE_P, cfgScale=float("nan")))
        assert s.posts == []

    def test_the_callers_dict_is_never_mutated(self):
        p = dict(IMAGE_P, isPrivate=True)
        client, _s = _client()
        client.create("image", p)
        assert p["isPrivate"] is True and "channel" not in p


# ---------------------------------------------------------------------------
# The kind comes from the caller (V10), the identity from the client (2.5, T-F5)
# ---------------------------------------------------------------------------

class TestKindAndIdentity:
    @pytest.mark.parametrize("kind, body, words", [
        ("image", dict(IMAGE_P, i2vPro={"model": "x", "mediaId": "1"}), "video request"),
        ("image", dict(IMAGE_P, referenceVideo={"model": "x"}), "video request"),
        ("edit", dict(EDIT_P, i2vPro={"model": "x", "mediaId": "1"}), "video request"),
        ("edit", IMAGE_P, "no edit block"),
        ("image", EDIT_P, "be sent as an image"),
    ])
    def test_a_shape_that_disagrees_with_the_kind_is_refused(self, kind, body, words):
        """V10's own check, named by its sentence: the wire guard would also refuse a video
        block on these kinds, but the kind check must not lean on it."""
        client, s = _client()
        with pytest.raises(core.LocalRefusal, match=words):
            client.create(kind, body)
        assert s.posts == []

    @pytest.mark.parametrize("kind, body", [("scene", SCENE_B), ("enhance", ENHANCE_B)])
    def test_scene_and_enhance_never_ride_the_api_key(self, kind, body):
        client, s = _client(auth_kind="api-key")
        with pytest.raises(core.LocalRefusal, match="website sign-in"):
            client.create(kind, body)
        assert s.posts == []

    def test_session_for_create_marks_the_mirror_client_and_the_log_names_it(self, monkeypatch,
                                                                            caplog):
        mirror = _Session()
        monkeypatch.setattr(mirror_mod, "mirror_enabled", lambda: True)
        monkeypatch.setattr(mirror_mod, "make_mirror_session", lambda: mirror)
        made = pc.PixAIClient(_Session()).for_create()
        assert made.auth_kind == "web-jwt" and made.session is mirror
        import logging
        with caplog.at_level(logging.INFO, logger="moonglade.create"):
            made.create("scene", SCENE_B)
        assert len(mirror.posts) == 1
        line, = [r.getMessage() for r in caplog.records if r.name == "moonglade.create"]
        assert "as web-jwt" in line and "/task/chat-editing-scene" in line
        assert "character-card" not in line                 # never the body

    def test_the_log_line_never_carries_the_prompt(self, caplog):
        import logging
        client, _s = _client()
        with caplog.at_level(logging.INFO, logger="moonglade.create"):
            client.create("image", dict(IMAGE_P, prompts="a secret prompt", kaisuukenId="K9"))
        line, = [r.getMessage() for r in caplog.records if r.name == "moonglade.create"]
        assert "secret" not in line and "K9" not in line and "card attached" in line

    def test_for_create_require_web_jwt_refuses_without_the_mirror(self, monkeypatch):
        monkeypatch.setattr(mirror_mod, "mirror_enabled", lambda: False)
        with pytest.raises(core.LocalRefusal):
            pc.PixAIClient(_Session()).for_create(require="web-jwt")
        monkeypatch.setattr(mirror_mod, "mirror_enabled", lambda: True)
        monkeypatch.setattr(mirror_mod, "make_mirror_session", lambda: _Session())
        assert pc.PixAIClient(_Session()).for_create(require="web-jwt").auth_kind == "web-jwt"

    def test_a_mirror_toggle_after_the_choice_changes_nothing(self, monkeypatch):
        """V8: the identity is chosen once per send. A marked client asked again answers
        itself, whatever the toggle now says."""
        monkeypatch.setattr(mirror_mod, "mirror_enabled", lambda: False)
        made = pc.PixAIClient(_Session()).for_create()
        monkeypatch.setattr(mirror_mod, "mirror_enabled", lambda: True)
        monkeypatch.setattr(mirror_mod, "make_mirror_session",
                            lambda: pytest.fail("chose the identity twice"))
        assert made.for_create() is made
        assert mirror_mod._session_for_create(made) is made


# ---------------------------------------------------------------------------
# READ_ONLY first
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind, body", [("image", IMAGE_P), ("edit", EDIT_P), ("scene", SCENE_B),
                                        ("enhance", ENHANCE_B), ("fix", FIX_B)])
def test_read_only_refuses_every_kind_before_anything_is_sent(monkeypatch, kind, body):
    monkeypatch.setattr(core, "READ_ONLY", True)
    client, s = _client(auth_kind="web-jwt")
    with pytest.raises(core.LocalRefusal, match="READ_ONLY"):
        client.create(kind, body)
    assert s.posts == []


# ---------------------------------------------------------------------------
# The classifier, every row of 2.6 (T-F3, T-V5)
# ---------------------------------------------------------------------------

def _rest(status, code=None, body=None):
    b = body if body is not None else ({"code": code, "message": "m"} if code else None)
    return core.PixAIRestError("REST POST /task/create -> {}".format(status), status=status,
                               body=b)


class TestClassifier:
    @pytest.mark.parametrize("code", sorted(gen_road.DEFINITE_CODES))
    def test_every_definite_code_reads_refused(self, code):
        assert gen_road.classify_outcome(_rest(400, code), "create") == "refused"
        assert gen_road.classify_outcome(_rest(400, code), "fixer") == "refused"

    @pytest.mark.parametrize("code", [
        "FILE_NOT_FOUND", "NOT_FOUND", "LORA_NUM_EXCEEDED", "MODEL_LORA_INCOMPATIBLE",
        "IMAGE_SIZE_NOT_ALLOWED", "INPUT_IMAGE_TOO_LARGE", "NSFW_DETECTED",
        "KAISUUKEN_MATCH_PARAMS_INVALID", "KAISUUKEN_INSUFFICIENT",
        "KAISUUKEN_SETTINGS_NOT_COVERED", "KAISUUKEN_EXTRA_CREDITS_REQUIRED", "REMIX_UNAVAILABLE",
        "THREAD_NOT_FOUND", "CREATION_FAILED", "INVALID_ARGUMENT", "NSFW_PROMPT_REJECTED"])
    def test_a_declared_code_outside_the_table_reads_unknown(self, code):
        assert gen_road.classify_outcome(_rest(422, code), "create") == "unknown"

    @pytest.mark.parametrize("status", [408, 499])
    def test_408_and_499_are_unknown_whatever_the_body(self, status):
        assert gen_road.classify_outcome(_rest(status, "BAD_REQUEST")) == "unknown"

    def test_the_bare_4xx_rule(self):
        assert gen_road.classify_outcome(_rest(403, body={"error": "html"})) == "unknown"
        assert gen_road.classify_outcome(_rest(403)) == "unknown"

    @pytest.mark.parametrize("status", [500, 502, 503, 301, 307])
    def test_a_listed_code_outside_4xx_is_unknown(self, status):
        assert gen_road.classify_outcome(_rest(status, "INSUFFICIENT_BALANCE")) == "unknown"

    def test_the_training_family_reads_its_own_table(self):
        e = _rest(400, "TRAINING_IMAGE_REJECTED")
        assert gen_road.classify_outcome(e, "training") == "refused"
        assert gen_road.classify_outcome(e, "create") == "unknown"
        assert gen_road.classify_outcome(e) == "unknown"

    def test_local_and_transport(self):
        assert gen_road.classify_outcome(core.LocalRefusal("x")) == "local"
        assert gen_road.classify_outcome(requests.ReadTimeout("x")) == "unknown"
        assert gen_road.classify_outcome(core.CreateOutcomeUnknown("x")) == "unknown"
