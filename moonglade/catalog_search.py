"""
moonglade/catalog_search.py
===========================
The search box's grammar: the key:value operators (`_SEARCH_OPS` and their clauses), the
aspect, type, date and LoRA-weight clauses, and `_build_where`, which turns a search and the
filter bar into one parameterised WHERE. Every user value is a bound parameter; the only text
interpolated into SQL comes from the hard-coded maps here (dev/tests/test_search_operators.py's
hostile-value test). Moved verbatim out of moonglade/gallery.py in the 3.22 split (phase 4).

The LIKE helpers it reads from the catalog are imported inside the functions that use them,
never at the top, so importing this module never imports the gallery.
"""
import re


# ---------------------------------------------------------------------------
# Search field operators: key:value tokens inside the search box
# ---------------------------------------------------------------------------
# alias -> (kind, column). Kinds:
#   text       substring, case-insensitive, * / ? wildcards via _like_pattern
#   prompt     like a free-text term (prompt_full OR prompt_preview) but explicit,
#              which matters for quoted phrases: prompt:"night elf"
#   num        key:N exact, or key:>N / key:<N / key:>=N / key:<=N; a blank column
#              value never matches a comparison (except rating -- see below)
#   exact      whole-value equality (ids and seeds; substring matching ids is the
#              exact chance-collision failure the long-digit gate below exists for)
#   bool       1/true/yes/on -> col='1'; 0/false/no/off -> anything else
#   date       created_at prefix (2026 / 2026-07 / 2026-07-04) or a </>/<=/>=
#              prefix-compare (created:<2026-07 = strictly before July)
#   collection exact-token match in the comma-joined list, same as the dropdown
#   tag        the art_tags substring OR a whole personal tag (Session N3)
#   note       substring of the personal note (Session N3)
#   source     the dropdown's semantics (online = blank-or-online, deleted =
#              deleted_remote flag), else substring on the source column
#   aspect     width/height: W:H (within 3 percent), square, portrait, landscape, tall,
#              wide, >N, <N (Session N7)
#   type       image | video | loom, a partition of the library (Session N6)
#
# Deliberately NOT operators (one line each):
#   url             expiring PixAI CDN link -- nothing sane to filter on
#   prompt_preview/ covered by free text and prompt:
#     prompt_full
#   poster_media_id internal video->poster linkage; media: finds either row
#   blurhash        opaque placeholder hash, not human-meaningful
#   nsfw_scores     JSON blob; nsfw: covers the sane ask
#   deleted_remote  already surfaced as source:deleted (mirrors the dropdown)
#
# Injection safety: every user value is a bound SQL parameter. The only strings
# interpolated into SQL are column names and comparison operators, and both come
# exclusively from these hardcoded maps -- never from user input. Pinned by
# dev/tests/test_search_operators.py's hostile-value test.
_SEARCH_OPS = {
    "prompt":   ("prompt", None),
    "negative": ("text", "negative_prompt"), "negative_prompt": ("text", "negative_prompt"),
    "model":    ("text", "model_name"),      "model_name": ("text", "model_name"),
    "lora":     ("text", "loras"),           "loras": ("text", "loras"),
    # tag: reads BOTH tag stores (Session N3): PixAI's published art tags, substring as it
    # always did, and the owner's own personal tags, whole-tag. `art_tags:` keeps the
    # PixAI-only reading for anyone who needs it. See _operator_clause's "tag" kind.
    "tag":      ("tag", "art_tags"),         "tags": ("tag", "art_tags"),
    "art_tags": ("text", "art_tags"),
    # note: reads the owner's personal note (Session N3), substring, case-insensitive.
    "note":     ("note", None),              "notes": ("note", None),
    "title":    ("text", "title"),
    "sampler":  ("text", "sampler"),
    "filename": ("text", "filename"),
    "batch":    ("text", "batch"),
    "status":   ("text", "status"),
    "natural":  ("text", "natural_prompt"),  "natural_prompt": ("text", "natural_prompt"),
    "width":    ("num", "width"),
    "height":   ("num", "height"),
    "rating":   ("num", "rating"),
    "steps":    ("num", "steps"),
    "cfg":      ("num", "cfg_scale"),        "cfg_scale": ("num", "cfg_scale"),
    "clip_skip": ("num", "clip_skip"),
    "aes":      ("num", "aes_score"),        "aes_score": ("num", "aes_score"),
    "likes":    ("num", "liked_count"),      "liked_count": ("num", "liked_count"),
    "comments": ("num", "comment_count"),    "comment_count": ("num", "comment_count"),
    "duration": ("num", "video_duration"),   "video_duration": ("num", "video_duration"),
    "seed":     ("exact", "seed"),
    "task":     ("exact", "task_id"),        "task_id": ("exact", "task_id"),
    "media":    ("exact", "media_id"),       "media_id": ("exact", "media_id"),
    "artwork":  ("exact", "artwork_id"),     "artwork_id": ("exact", "artwork_id"),
    "model_id": ("exact", "model_id"),
    "video":    ("bool", "is_video"),        "is_video": ("bool", "is_video"),
    "published": ("bool", "is_published"),   "is_published": ("bool", "is_published"),
    "nsfw":     ("bool", "is_nsfw"),         "is_nsfw": ("bool", "is_nsfw"),
    "created":  ("date", "created_at"),      "created_at": ("date", "created_at"),
    "date":     ("date", "created_at"),
    "collection": ("collection", "collections"),
    "collections": ("collection", "collections"),
    "source":   ("source", "source"),
    # ar: the picture's shape, read from the width and height already on every row (Session
    # N7). Evaluated HERE, in SQL, because the grid is paginated: a client-side filter would
    # only ever see the page it holds. See _aspect_clause for the accepted values.
    "ar":       ("aspect", None),            "aspect": ("aspect", None),
    # type: which kind of picture -- image, video or loom (Session N6). The three PARTITION the
    # library (a Loom render is a loom, whether it is a clip or a still), which is what lets
    # the Storage bars' segments add up to the total and each segment's click land on exactly it.
    "type":     ("type", None),
}

# Tokens: quoted runs group (model:"Ether Real" / "night elf" are ONE token each);
# everything else splits on whitespace exactly like q.split() always did.
_SEARCH_TOKEN_RE = re.compile(r'[^\s"]*"[^"]*"[^\s"]*|\S+')
_SEARCH_KEY_RE   = re.compile(r"[A-Za-z_]+")
_SEARCH_NUM_RE   = re.compile(r"^(>=|<=|>|<)?(-?\d+(?:\.\d+)?)$")
_SEARCH_DATE_RE  = re.compile(r"^(>=|<=|>|<)?(\d{4}(?:-\d{2}(?:-\d{2})?)?)$")
# Dates beyond a single prefix: a quarter (2026Q3) and an inclusive range (A..B, either end
# open), each end a year / month / day / quarter.
_SEARCH_DATE_PART_RE = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?|[Qq]([1-4]))?$")
# lora:Name>0.7 -- a LoRA name (blank or * = any LoRA) then a weight comparison.
_SEARCH_LORA_WEIGHT_RE = re.compile(r"^(.*?)(>=|<=|>|<|=)\s*(-?\d+(?:\.\d+)?)$")
_LORA_ENTRY_RE = re.compile(r"\s*(.*?):(-?\d+(?:\.\d+)?)(?=,\s|$)")
_SEARCH_TRUTHY = frozenset({"1", "true", "yes", "on"})
_SEARCH_FALSY  = frozenset({"0", "false", "no", "off"})


def _unquote(s):
    """Strip one pair of surrounding double quotes, if present."""
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def _personal_tag_pattern(value):
    r"""LIKE pattern matching ONE whole personal tag inside personal_meta's `,a,b,` list.
    The value is folded the way tags are stored (lowercase, whitespace and underscores to
    hyphens) so `tag:"Pose Study"` finds pose-study; `*` and `?` keep their wildcard meaning."""
    t = re.sub(r"[\s_]+", "-", str(value).strip().lower())
    t = t.replace("\\", "\\\\").replace("%", "\\%")
    return "%," + t.replace("*", "%").replace("?", "_") + ",%"


# A leading `-` negates a search token (Session N3: `-reject`, `-tag:x`, `-blurry`). A `-` in
# front of a bare number stays what it always was, literal text -- "-5" is a prompt fragment.
_SEARCH_NEG_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
_SEARCH_STAR_RE = re.compile("^★([0-5])\\+?$")


def _personal_mark_clause(mark):
    return ("EXISTS (SELECT 1 FROM personal_meta pm WHERE pm.media_id = catalog.media_id "
            "AND pm.mark = ?)", [mark])


def _search_token_clause(tok):
    """One whitespace-delimited search token -> (sql, params). The token is already stripped
    of any leading `-` negation by the caller."""
    from moonglade.gallery import _like_pattern
    # the bare marks are operators on their own (an UNQUOTED word: "reject" in quotes is a
    # phrase and stays a prompt search)
    if tok.lower() in ("keeper", "reject"):
        return _personal_mark_clause(tok.lower())
    m = _SEARCH_STAR_RE.match(tok)
    if m:
        # star-N-plus (and star-N): that many stars or more, unrated counting as 0 -- the
        # Min-rating dropdown's own semantics
        return ("CAST(COALESCE(NULLIF(rating,''),'0') AS INTEGER) >= ?", [int(m.group(1))])
    if ":" in tok and not tok.startswith(":"):
        key, _, raw = tok.partition(":")
        if _SEARCH_KEY_RE.fullmatch(key):
            hit = _operator_clause(key, _unquote(raw))
            if hit:
                return hit
    term = _unquote(tok)
    if term.isdigit() and len(term) >= 8:
        return ("(task_id = ? OR media_id = ?)", [term, term])
    like = _like_pattern(term)
    return ("(LOWER(COALESCE(prompt_full,'')) LIKE ? ESCAPE '\\' "
            "OR LOWER(COALESCE(prompt_preview,'')) LIKE ? ESCAPE '\\')", [like, like])


# ---- ar: the aspect operator (Session N7) -------------------------------------------------
# The picture's shape as width / height. The width and height columns are TEXT and blank on
# old imports, so the ratio is NULL for those rows; every comparison below is wrapped in
# COALESCE(.., 0) so an unmeasured picture matches no ar: filter and, because NOT of a false
# is true, still shows up under `-ar:tall` (the unknown is not "tall").
#
#   ar:W:H        within 3 percent of W/H       ar:3:2  ar:9:16  ar:1.91:1
#   ar:square     0.97 to 1.03
#   ar:portrait   below 1                        ar:landscape   above 1
#   ar:tall       9:16 or taller                 ar:wide        16:9 or wider
#   ar:>N ar:<N   the ratio itself               ar:>2  ar:<0.5
#
# The bounds are the design page's own (Curation Handoff, N7): "tall" is 9/16 with 0.005 to
# spare and "wide" 16/9 with 0.01 to spare, so an exact 576x1024 and an exact 1920x1080
# count without a rounding argument. Values are bound parameters; only the fixed expression is interpolated.
_AR_EXPR = ("(CAST(COALESCE(NULLIF(width,''),'0') AS REAL) / "
            "NULLIF(CAST(COALESCE(NULLIF(height,''),'0') AS REAL), 0))")
AR_SQUARE = (0.97, 1.03)
AR_TALL_MAX = 9 / 16 + 0.005
AR_WIDE_MIN = 16 / 9 - 0.01
AR_TOLERANCE = 0.03
_AR_WH_RE = re.compile(r"^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$")
_AR_CMP_RE = re.compile(r"^([<>])(\d*\.?\d+)$")


def _aspect_clause(value):
    """`ar:` value -> (sql, params), or None when the value is not one of the accepted forms
    (the token then degrades to a plain prompt search, like any malformed operator)."""
    v = str(value).strip().lower()
    e = _AR_EXPR
    if v == "square":
        return ("COALESCE({0} >= ? AND {0} <= ?, 0)".format(e), [AR_SQUARE[0], AR_SQUARE[1]])
    if v == "portrait":
        return ("COALESCE({} < 1, 0)".format(e), [])
    if v == "landscape":
        return ("COALESCE({} > 1, 0)".format(e), [])
    if v == "tall":
        return ("COALESCE({} <= ?, 0)".format(e), [AR_TALL_MAX])
    if v == "wide":
        return ("COALESCE({} >= ?, 0)".format(e), [AR_WIDE_MIN])
    m = _AR_CMP_RE.match(v)
    if m:
        return ("COALESCE({} {} ?, 0)".format(e, m.group(1)), [float(m.group(2))])
    m = _AR_WH_RE.match(v)
    if m:
        w, h = float(m.group(1)), float(m.group(2))
        if w <= 0 or h <= 0:
            return None
        n = w / h
        # within 3 percent of n, either side; the epsilon keeps an exact 3 percent in
        return ("COALESCE(ABS({} - ?) <= ?, 0)".format(e), [n, n * AR_TOLERANCE + 1e-9])
    return None


# ---- type: image | video | loom (Session N6) -----------------------------------------------
def _type_clause(value):
    v = str(value).strip().lower()
    if v == "loom":
        return ("mg_loom_render(media_id) = 1", [])
    if v == "video":
        return ("(is_video = '1' AND mg_loom_render(media_id) = 0)", [])
    if v == "image":
        return ("(COALESCE(is_video,'') != '1' AND mg_loom_render(media_id) = 0)", [])
    return None


def _date_part_bounds(part):
    """One date spec (2026 / 2026-07 / 2026-07-04 / 2026Q3) -> (start, end_exclusive) as ISO
    prefixes that compare correctly against created_at strings, or None if it is not a real
    date. The end is the START of the next period, so `created_at >= start AND created_at <
    end` covers the whole period whatever the timestamp's length."""
    m = _SEARCH_DATE_PART_RE.match(part)
    if not m:
        return None
    y, mo, d, q = m.group(1), m.group(2), m.group(3), m.group(4)
    yi = int(y)
    if yi < 1:
        return None
    if q:
        sm = (int(q) - 1) * 3 + 1
        em, ey = sm + 3, yi
        if em > 12:
            em, ey = 1, yi + 1
        return ("%s-%02d" % (y, sm), "%04d-%02d" % (ey, em))
    if mo is None:
        return (y, "%04d" % (yi + 1))
    mi = int(mo)
    if not 1 <= mi <= 12:
        return None
    if d is None:
        return ("%s-%s" % (y, mo), "%04d-%02d" % (yi + (mi == 12), 1 if mi == 12 else mi + 1))
    import datetime as _dt
    try:
        day = _dt.date(yi, mi, int(d))
    except ValueError:
        return None
    return (day.isoformat(), (day + _dt.timedelta(days=1)).isoformat())


def _date_clause(value):
    """created: beyond a plain prefix -- a quarter (2026Q3), an inclusive range
    (2026-08..2026-10, 2026-09-15.., ..2026Q2), or a comparison against a quarter. None when
    the value is not one of those (the caller's prefix compare handles the rest)."""
    if ".." in value:
        lo, _, hi = value.partition("..")
        if not lo and not hi:
            return None
        parts, sql = [], []
        if lo:
            b = _date_part_bounds(lo)
            if not b:
                return None
            sql.append("created_at >= ?")
            parts.append(b[0])
        if hi:
            b = _date_part_bounds(hi)
            if not b:
                return None
            sql.append("created_at < ?")
            parts.append(b[1])
        return ("(" + " AND ".join(sql) + ")", parts)
    m = re.match(r"^(>=|<=|>|<)?(\d{4}[Qq][1-4])$", value)
    if not m:
        return None
    b = _date_part_bounds(m.group(2))
    op = m.group(1) or "="
    if op == "=":
        return ("(created_at >= ? AND created_at < ?)", [b[0], b[1]])
    if op == ">=":
        return ("created_at >= ?", [b[0]])
    if op == ">":
        return ("created_at >= ?", [b[1]])
    if op == "<":
        return ("created_at < ?", [b[0]])
    return ("created_at < ?", [b[1]])        # <=


def _lora_name_regex(name):
    name = name.strip()
    if name in ("", "*"):
        return None
    return re.compile(re.escape(name).replace(r"\*", ".*").replace(r"\?", "."), re.I)


def _lora_weight_match(loras, name_pat, op, num):
    """SQL function body: does any LoRA in the 'Name:0.7, Other:1' list match the name (a
    substring, * and ? wildcards, blank/* = any) AND have a weight satisfying `op num`?"""
    try:
        rx = re.compile(name_pat, re.I) if name_pat else None
        num = float(num)
    except (re.error, TypeError, ValueError):
        return 0
    for nm, w in _LORA_ENTRY_RE.findall(str(loras or "")):
        if rx is not None and not rx.search(nm):
            continue
        w = float(w)
        if ((op == ">" and w > num) or (op == ">=" and w >= num) or (op == "<" and w < num)
                or (op == "<=" and w <= num) or (op == "=" and abs(w - num) < 1e-9)):
            return 1
    return 0


def _lora_weight_clause(value):
    m = _SEARCH_LORA_WEIGHT_RE.match(value)
    if not m:
        return None
    rx = _lora_name_regex(_unquote(m.group(1).strip()))
    return ("mg_lora_weight(loras, ?, ?, ?) = 1",
            [rx.pattern if rx else "", m.group(2), float(m.group(3))])


def _operator_clause(key, value):
    """Compile one key:value search token into (sql_clause, params), or None when
    the token isn't a valid operator and should be searched as plain prompt text
    instead (unknown key, empty value, malformed number/date, unrecognized bool)
    -- the way search engines degrade, so a stray colon never errors or surprises."""
    from moonglade.gallery import _like_escape, _like_pattern
    spec = _SEARCH_OPS.get(key.lower())
    if not spec or value == "":
        return None
    kind, col = spec
    if kind == "aspect":
        return _aspect_clause(value)
    if kind == "type":
        return _type_clause(value)
    if kind == "tag":
        # Session N3: the published art tags (substring, as before) OR a whole personal tag.
        return ("(LOWER(COALESCE(art_tags,'')) LIKE ? ESCAPE '\\' OR EXISTS ("
                "SELECT 1 FROM personal_meta pm WHERE pm.media_id = catalog.media_id "
                "AND (',' || pm.tags || ',') LIKE ? ESCAPE '\\'))",
                [_like_pattern(value), _personal_tag_pattern(value)])
    if kind == "note":
        return ("EXISTS (SELECT 1 FROM personal_meta pm WHERE pm.media_id = catalog.media_id "
                "AND LOWER(pm.note) LIKE ? ESCAPE '\\')", [_like_pattern(value)])
    if kind == "text" and col == "loras":
        hit = _lora_weight_clause(value)
        if hit:
            return hit
    if kind == "text":
        return ("LOWER(COALESCE({},'')) LIKE ? ESCAPE '\\'".format(col),
                [_like_pattern(value)])
    if kind == "prompt":
        like = _like_pattern(value)
        return ("(LOWER(COALESCE(prompt_full,'')) LIKE ? ESCAPE '\\' "
                "OR LOWER(COALESCE(prompt_preview,'')) LIKE ? ESCAPE '\\')",
                [like, like])
    if kind == "exact":
        return ("{} = ?".format(col), [value])
    if kind == "num":
        m = _SEARCH_NUM_RE.match(value)
        if not m:
            return None
        op = m.group(1) or "="
        num = float(m.group(2))
        if col == "rating":
            # unrated ('') counts as 0 -- identical to the Min-rating dropdown
            return ("CAST(COALESCE(NULLIF(rating,''),'0') AS REAL) {} ?".format(op),
                    [num])
        return ("(COALESCE({0},'') != '' AND CAST({0} AS REAL) {1} ?)".format(col, op),
                [num])
    if kind == "bool":
        v = value.lower()
        if v in _SEARCH_TRUTHY:
            return ("{} = '1'".format(col), [])
        if v in _SEARCH_FALSY:
            return ("COALESCE({},'') != '1'".format(col), [])
        return None
    if kind == "date":
        hit = _date_clause(value)
        if hit:
            return hit
        m = _SEARCH_DATE_RE.match(value)
        if not m:
            return None
        op = m.group(1) or "="
        prefix = m.group(2)
        # prefix-compare: created:>2026-07 excludes July itself, created:>=2026-07
        # includes it -- comparing the row's SAME-LENGTH prefix keeps that intuitive
        # (a raw string compare against full timestamps would drag July into '>')
        return ("SUBSTR(created_at,1,?) {} ?".format(op), [len(prefix), prefix])
    if kind == "collection":
        # exact-token in the comma-joined list, mirroring the Collection dropdown
        return ("(',' || COALESCE(collections,'') || ',') LIKE ? ESCAPE '\\'",
                ["%," + _like_escape(value) + ",%"])
    if kind == "source":
        v = value.lower()
        if v == "online":
            return ("COALESCE(source,'') IN ('', 'online')", [])
        if v in ("api", "local"):
            return ("source = ?", [v])
        if v == "deleted":
            return ("deleted_remote = '1'", [])
        return ("LOWER(COALESCE(source,'')) LIKE ? ESCAPE '\\'",
                [_like_pattern(value)])
    return None


def _build_where(q, model, date_from, date_to, batch="", rating_min=0,
                 published_only=False, art_tag="", lora="", media_type="", source="",
                 collection="", no_svg=False):
    """Return (where_clause, params) for the common filter set. `no_svg` leaves SVG rows
    out (by the recorded output format, then the file's extension): the picture list the
    create pickers and the Apple TV client read, since tvOS cannot draw one and no create
    road takes one as a source (3.22 S5)."""
    from moonglade.gallery import _like_escape
    clauses = ["filename != ''"]
    params  = []
    if collection:
        # exact-token match within the comma-joined list (no partial-name bleed)
        clauses.append("(',' || COALESCE(collections,'') || ',') LIKE ? ESCAPE '\\'")
        params.append("%," + _like_escape(collection) + ",%")
    if media_type == "video":
        clauses.append("is_video = '1'")
    elif media_type == "image":
        clauses.append("COALESCE(is_video,'') != '1'")
    if source == "online":
        clauses.append("COALESCE(source,'') IN ('', 'online')")
    elif source in ("api", "local"):
        clauses.append("source = ?")
        params.append(source)
    elif source == "deleted":
        clauses.append("deleted_remote = '1'")   # flagged by --reconcile-deleted
    if rating_min:
        clauses.append("CAST(COALESCE(NULLIF(rating,''),'0') AS INTEGER) >= ?")
        params.append(int(rating_min))
    if published_only:
        clauses.append("is_published = '1'")
    if art_tag:
        clauses.append("LOWER(COALESCE(art_tags,'')) LIKE ? ESCAPE '\\'")
        params.append("%" + _like_escape(art_tag.strip().lower()) + "%")
    if lora:
        clauses.append("LOWER(COALESCE(loras,'')) LIKE ? ESCAPE '\\'")
        params.append("%" + _like_escape(lora.strip().lower()) + "%")
    if q:
        # Whitespace-separated tokens are ANDed. A token can be a FIELD OPERATOR
        # (key:value -- see _SEARCH_OPS/_operator_clause above; quoted values group,
        # so model:"Ether Real" is one token); anything else is free text, whose
        # behavior is UNCHANGED from before operators existed (pinned at the SQL
        # level by dev/tests/test_search_operators.py): each term may use * / ?
        # wildcards over prompt text, and a term that looks like a WHOLE task/media
        # id (all digits, long enough that a short numeric prompt word can't
        # collide -- PixAI ids run ~18-19 digits) also matches that id EXACTLY, so
        # pasting an id from PixAI's site (or --dump-params output) finds the row.
        # Short numeric terms stay prompt-only: a substring match on ids made a
        # term like "88" match ~14% of the whole catalog by id chance alone,
        # swamping any real prompt hits (found 2026-07-16).
        #
        # A leading `-` negates the token (Session N3): -reject, -tag:x, -"night elf". The
        # clause is wrapped, never rewritten, so a token without one builds the same SQL.
        for tok in _SEARCH_TOKEN_RE.findall(q):
            neg = len(tok) > 1 and tok[0] == "-" and not _SEARCH_NEG_NUMBER_RE.match(tok)
            clause, cparams = _search_token_clause(tok[1:] if neg else tok)
            clauses.append("NOT " + clause if neg else clause)
            params += cparams
    if model:
        clauses.append("model_name = ?")
        params.append(model)
    if batch:
        # EITHER column: --organize blanks `batch` (r["batch"] = ""), so a library
        # that has been organized would resolve a batch filter to nothing. The Details
        # "View Batch" button passes the task_id (issue #30); the legacy batches/
        # folder-name filter keeps working through the same param.
        clauses.append("(batch = ? OR task_id = ?)")
        params.extend([batch, batch])
    if date_from:
        clauses.append("SUBSTR(created_at,1,7) >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("SUBSTR(created_at,1,7) <= ?")
        params.append(date_to)
    if no_svg:
        clauses.append("COALESCE(output_format,'') != 'svg' "
                       "AND LOWER(COALESCE(filename,'')) NOT LIKE '%.svg'")
    return " AND ".join(clauses), params
