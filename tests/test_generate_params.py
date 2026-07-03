"""Image-gen parameter builder (_gen_parameters): batchSize must always be >= 1
(guards the --count/--batch-size dest collision that could deliver False), and the
free-card id wires through. Pure; no network."""
from types import SimpleNamespace

import pixai_gallery_backup as core


def _gen_args(**kw):
    base = dict(params_json="", prompt="p", model="", width=512, height=512, steps=25,
                cfg=7, count=1, priority=500, mode="", negative="", seed=None, lora=None,
                prompt_helper=True, kaisuuken_id="")
    base.update(kw)
    return SimpleNamespace(**base)


def test_batch_size_coerced_from_false():
    # the --count (store_true) / --batch-size (dest=count) collision can deliver False
    assert core._gen_parameters(_gen_args(count=False))["batchSize"] == 1


def test_batch_size_zero_and_none_coerced():
    assert core._gen_parameters(_gen_args(count=0))["batchSize"] == 1
    assert core._gen_parameters(_gen_args(count=None))["batchSize"] == 1


def test_batch_size_explicit_kept():
    assert core._gen_parameters(_gen_args(count=4))["batchSize"] == 4


def test_gen_kaisuuken_injected():
    p = core._gen_parameters(_gen_args(kaisuuken_id="card9"))
    assert p["kaisuukenId"] == "card9"


def test_gen_no_kaisuuken_by_default():
    assert "kaisuukenId" not in core._gen_parameters(_gen_args())
