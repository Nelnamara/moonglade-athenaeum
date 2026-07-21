#!/usr/bin/env bash
# Environment setup for cloud review containers (ultrareview / cloud agents).
#
# Why this exists: an ultrareview run on PR #2 came back with only 3 candidate
# findings, and its "Run setup script" step was unchecked -- the container had no
# dependencies, so the reviewer could not run pytest, could not start the Flask
# app, and was reduced to purely static reading. This script gives it teeth.
#
# The dependency list is deliberately IDENTICAL to .github/workflows/tests.yml's
# install step, including the one omission, so a reviewer's environment matches
# the one CI actually gates on:
#   - pixeltable is NOT installed. It is a heavy, optional, GPU-oriented dep;
#     tests/test_similar.py skips itself cleanly without it via importorskip.
# If you change one list, change the other.

set -euo pipefail

echo "--- Python dependencies ---"
python -m pip install --upgrade pip
python -m pip install requests pillow flask truststore websockets pytest pytest-mock pytest-cov

echo "--- Verifying the suite runs ---"
# Mirrors CI exactly. --ignore=tests/test_similar.py because pixeltable is absent
# by design (see above); the file would skip itself anyway, this just keeps the
# output clean.
python -m pytest -q --ignore=tests/test_similar.py

# The Loom ships a pure-logic Node suite. Best-effort: a missing Node toolchain
# must not fail the whole setup, since the Python side is what most reviews need.
if command -v npm >/dev/null 2>&1; then
  echo "--- Loom (Node) dependencies ---"
  ( cd loom && npm ci && npm run build && node --test ) || \
    echo "WARNING: Loom Node suite did not complete; Python review is unaffected."
else
  echo "npm not found -- skipping the Loom's Node suite."
fi

echo "--- Setup complete ---"
# Note for reviewers: config.json is git-ignored and absent in a fresh clone. It
# holds PIXAI_API_KEY / AUTH_SECRET_KEY / AUTH_USERS. Its absence is CORRECT and
# expected -- the tests build their own throwaway config per tmp_path. Do not
# create one, and do not report its absence as a finding.
