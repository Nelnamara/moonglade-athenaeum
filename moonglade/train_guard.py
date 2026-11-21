"""
moonglade/train_guard.py
========================
`TrainGuard`: the two spend guards LoRA training keeps ON DISK (train_guard.json among the
library's records), so neither a restart nor a second tab can clear them. The training routes
(moonglade/routes_train.py) build the one guard the server holds. Moved verbatim out of
moonglade/gallery.py in the 3.22 split (phase 4).

It needs nothing from the gallery or the engine.
"""
import json
import os
import threading
import time
from pathlib import Path


class TrainGuard:
    """The two spend guards the training routes keep ON DISK (train_guard.json among the
    library's records, _moonglade/records/), so neither a restart nor a second tab can clear
    them (spend review 2026-09-28, findings 1 and 2; BUILD-w3-train.md section 7).

      * BASIC START: a Basic run has no task id until PixAI creates it, so the per-task lock
        cannot cover it. The guard is keyed on what the run IS (base, dataset, name), checked
        and ARMED before the mutation under the one Basic lock, and resolved after it: a run
        PixAI started keeps it armed for DUPLICATE_WINDOW (a second identical Start inside a
        minute is a double click, not an intent); a definite refusal disarms it; an unclear
        failure -- a timeout, a dropped connection, a 5xx, after which PixAI may well have
        created and charged the run -- keeps it as "ambiguous" for AMBIGUOUS_WINDOW, and the
        panel says the run may have started.
      * RETRY: PixAI leaves a failed run as it is after a retry, so it would accept a second
        retry and charge a second run. The failed id is armed before the POST; a success
        records the new run's id for good; an unclear failure is "ambiguous" for
        AMBIGUOUS_RETRY_WINDOW; only a definite refusal disarms it.
      * ADVANCED DESCRIBE / START (spend review of waves 2+3, finding F1): the per-task lock
        covers two requests at once, and the task's status covers a POST PixAI answered --
        but after an UNCLEAR failure the status may not have moved yet, so a second confirm
        would send a second paid POST. Each is armed (keyed "<what>:<task id>", with the
        status it was confirmed from) before the POST; a success or a definite refusal
        clears it; an unclear failure keeps it "ambiguous" for AMBIGUOUS_WINDOW. While it
        stands, the next confirm is refused unless the task's status has moved on since.

    Every read-modify-write holds one lock, and the file is rewritten whole each time."""

    DUPLICATE_WINDOW = 60.0
    AMBIGUOUS_WINDOW = 15 * 60.0
    AMBIGUOUS_RETRY_WINDOW = 24 * 3600.0

    def __init__(self, path):
        # `path` may be a callable, asked at each use (the server's own guard): the library's
        # records can be brought across, or moved back by a round trip to 3.19, while the
        # server runs, and the guard must never keep writing where nobody reads.
        self._where = path if callable(path) else (lambda p=Path(path): p)
        self._lock = threading.Lock()

    @property
    def path(self):
        return Path(self._where())

    def _load(self):
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        if not isinstance(d, dict):
            d = {}
        d.setdefault("basic", {})
        d.setdefault("retried", {})
        d.setdefault("paid", {})
        return d

    def _save(self, d):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(d, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(str(tmp), str(self.path))

    @staticmethod
    def basic_key(base_model_id, media_ids, dataset_task_id, title):
        import hashlib
        parts = [str(base_model_id or ""), "reuse:" + str(dataset_task_id) if dataset_task_id
                 else ",".join(sorted(str(m) for m in (media_ids or []))),
                 " ".join(str(title or "").split()).lower()]
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()

    def basic_blocked(self, key, now=None):
        """None when a Basic start with this key may go ahead, else the refusal's words."""
        now = time.time() if now is None else now
        with self._lock:
            d = self._load()
            e = d["basic"].get(key)
            if not isinstance(e, dict):
                return None
            age = now - float(e.get("at") or 0)
            # "armed" seen here is a start that never resolved -- the process stopped between
            # the arm and the answer (the one Basic lock means no live request can be holding
            # it) -- so it is as unclear as an ambiguous one.
            if e.get("state") in ("ambiguous", "armed") and age < self.AMBIGUOUS_WINDOW:
                return ("Your last start of this run may have gone through: PixAI didn't "
                        "answer clearly. Check Runs before starting it again (this guard "
                        "clears by itself after 15 minutes). Nothing was sent.")
            if e.get("state") == "started" and age < self.DUPLICATE_WINDOW:
                return ("You just started this run. Nothing was sent again; it is in Runs.")
            return None

    def basic_arm(self, key, now=None):
        now = time.time() if now is None else now
        with self._lock:
            d = self._load()
            d["basic"] = {k: v for k, v in d["basic"].items()
                          if now - float((v or {}).get("at") or 0) < self.AMBIGUOUS_WINDOW}
            d["basic"][key] = {"at": now, "state": "armed"}
            self._save(d)

    def basic_resolve(self, key, outcome, now=None):
        """outcome: "started" (keep for the duplicate window), "refused" (disarm),
        "ambiguous" (keep, say it may have started)."""
        now = time.time() if now is None else now
        with self._lock:
            d = self._load()
            if outcome == "refused":
                d["basic"].pop(key, None)
            else:
                d["basic"][key] = {"at": now, "state": outcome}
            self._save(d)

    def retry_state(self, task_id, now=None):
        """None (never retried here, or an old unclear attempt), else {state, new_id}."""
        now = time.time() if now is None else now
        with self._lock:
            e = self._load()["retried"].get(str(task_id))
        if not isinstance(e, dict):
            return None
        st = e.get("state") or "armed"
        if st == "armed":            # never resolved: the process stopped mid-retry
            st = "ambiguous"
        if st == "ambiguous" and now - float(e.get("at") or 0) >= self.AMBIGUOUS_RETRY_WINDOW:
            return None
        return {"state": st, "new_id": e.get("new_id") or ""}

    def retry_arm(self, task_id, now=None):
        now = time.time() if now is None else now
        with self._lock:
            d = self._load()
            d["retried"][str(task_id)] = {"at": now, "state": "armed", "new_id": ""}
            self._save(d)

    def retry_resolve(self, task_id, outcome, new_id="", now=None):
        """outcome: "done" (keep for good, with the new run's id), "refused" (disarm),
        "ambiguous"."""
        now = time.time() if now is None else now
        with self._lock:
            d = self._load()
            if outcome == "refused":
                d["retried"].pop(str(task_id), None)
            else:
                d["retried"][str(task_id)] = {"at": now, "state": outcome,
                                              "new_id": str(new_id or "")}
            self._save(d)

    @staticmethod
    def paid_key(what, task_id):
        return "%s:%s" % (what, task_id)

    def paid_blocked(self, what, task_id, status, now=None):
        """True when an earlier `what` ("caption" | "submit") confirm on this task may have
        gone through and the task's status (`status`, read just now) has not moved on from
        the one it was confirmed from. A status that moved clears the entry: PixAI took it,
        and the route's own status check says what happens next. "armed" seen here is a
        confirm that never resolved (the process stopped mid-POST): as unclear as
        "ambiguous"."""
        now = time.time() if now is None else now
        key = self.paid_key(what, task_id)
        with self._lock:
            d = self._load()
            e = d["paid"].get(key)
            if not isinstance(e, dict):
                return False
            fresh = now - float(e.get("at") or 0) < self.AMBIGUOUS_WINDOW
            if fresh and str(e.get("status") or "") == str(status or ""):
                return True
            d["paid"].pop(key, None)
            self._save(d)
            return False

    def paid_arm(self, what, task_id, status, now=None):
        now = time.time() if now is None else now
        with self._lock:
            d = self._load()
            d["paid"] = {k: v for k, v in d["paid"].items()
                         if now - float((v or {}).get("at") or 0) < self.AMBIGUOUS_WINDOW}
            d["paid"][self.paid_key(what, task_id)] = {"at": now, "state": "armed",
                                                       "status": str(status or "")}
            self._save(d)

    def paid_resolve(self, what, task_id, outcome, now=None):
        """outcome: "done" or "refused" (clear: PixAI answered, and its status now says what
        happened), "ambiguous" (keep for AMBIGUOUS_WINDOW)."""
        now = time.time() if now is None else now
        key = self.paid_key(what, task_id)
        with self._lock:
            d = self._load()
            if outcome == "ambiguous":
                e = d["paid"].get(key) or {}
                d["paid"][key] = {"at": now, "state": "ambiguous",
                                  "status": str(e.get("status") or "")}
            else:
                d["paid"].pop(key, None)
            self._save(d)

    def retried(self):
        """{failed_id: {state, new_id}} for the Runs list (a guarded id shows no Retry)."""
        with self._lock:
            ids = list(self._load()["retried"])
        out = {}
        for tid in ids:
            st = self.retry_state(tid)
            if st:
                out[tid] = st
        return out
