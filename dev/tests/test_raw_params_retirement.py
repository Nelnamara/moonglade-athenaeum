"""A raw --params-json naming a retired video engine is refused on every CLI create road.

--generate-video, --reference-video and --edit-image send their mutation themselves (not
through submit_generation), and a --params-json never passes through the builders that
check the engine, so V3.2 could still be submitted from the command line after PixAI retired
it (red team, 2026-11-19). The refusal must come before any network call: no session, no
free-card check, no price read, no mutation.
"""
import datetime
import json
from types import SimpleNamespace

import pytest

from moonglade import backup as core
from moonglade import cards as cards_mod
from moonglade import gen_cli as gen_cli_mod
from moonglade import gen_params as gen_params_mod

UTC = datetime.timezone.utc
CUT = datetime.datetime(2026, 11, 23, 3, 0, 0, tzinfo=UTC)

V32_I2V = json.dumps({"i2vPro": {"model": "v3.2", "mediaId": "1", "duration": 5}})
V32_REF = json.dumps({"referenceVideo": {"model": "v3.2", "prompts": "@image1"}})


@pytest.fixture()
def no_network(monkeypatch, tmp_path):
    """Every road off this machine fails the test by name."""
    monkeypatch.setattr(gen_params_mod, "_video_clock", lambda: CUT)
    monkeypatch.setattr(core, "_check_read_only", lambda *a, **k: None)

    def _boom(name):
        def f(*a, **k):
            raise AssertionError(name + " was reached before the retirement refusal")
        return f

    for name in ("_make_session", "gql_mutate", "upload_media"):
        monkeypatch.setattr(core, name, _boom(name))
    for name in ("_resolve_refs",):                              # in gen_cli since 3.22
        monkeypatch.setattr(gen_cli_mod, name, _boom(name))
    for name in ("_apply_kaisuuken", "_preview_card_note"):    # in cards since 3.22
        monkeypatch.setattr(cards_mod, name, _boom(name))
    return tmp_path


def _args(out, **kw):
    base = dict(out=str(out), task_id="", token=None, prompt="p", poll_timeout=1)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("confirm", [False, True], ids=["preview", "confirm"])
def test_generate_video_params_json(no_network, confirm):
    with pytest.raises(core.PixAIError, match="retired by PixAI"):
        gen_cli_mod.run_generate_video(_args(no_network, image="1", params_json=V32_I2V,
                                      confirm=confirm))


@pytest.mark.parametrize("confirm", [False, True], ids=["preview", "confirm"])
def test_reference_video_params_json(no_network, confirm):
    with pytest.raises(core.PixAIError, match="retired by PixAI"):
        gen_cli_mod.run_reference_video(_args(no_network, params_json=V32_REF, confirm=confirm))


@pytest.mark.parametrize("confirm", [False, True], ids=["preview", "confirm"])
def test_edit_image_params_json(no_network, confirm):
    with pytest.raises(core.PixAIError, match="retired by PixAI"):
        gen_cli_mod.run_edit_image(_args(no_network, edit_src=[], params_json=V32_I2V,
                                  confirm=confirm))


def test_another_engine_in_params_json_is_not_refused(no_network):
    """The check refuses only a retired engine: a v4.0.1 raw shape reaches the next step."""
    with pytest.raises(AssertionError, match="_preview_card_note was reached"):
        gen_cli_mod.run_generate_video(_args(no_network, image="1", confirm=False,
                                      params_json=json.dumps({"i2vPro": {"model": "v4.0.1"}})))


def test_recovering_an_existing_task_is_not_refused(no_network, monkeypatch):
    """--task-id spends nothing and sends no parameters, so the engine is not checked."""
    with pytest.raises(AssertionError, match="_make_session was reached"):
        gen_cli_mod.run_generate_video(_args(no_network, task_id="T1", params_json=V32_I2V,
                                      confirm=False))
