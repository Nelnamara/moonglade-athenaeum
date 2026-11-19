"""Guard rails for splitting the two megamodules (3.21.0, item 9 of the library-cluster scope).

`moonglade/backup.py` and `moonglade/gallery.py` are being lifted apart seam by seam, verbatim.
One map drives every check here: SEAMS, new module -> the old module it came from and the names
it now owns. Phase 0 moves nothing, so the map is EMPTY and every check passes trivially; each
check is proven to fire by a synthetic case further down. A move adds one entry to SEAMS (and
runs `py dev/tools/retarget_patches.py` to move the patches with it).

What a move must satisfy:
  1. Every mapped name is DEFINED in the new module (not just imported there).
  2. The old module does NOT re-export a moved name. The one exception: a name some other
     PRODUCTION module (moonglade/*.py, the launcher) reaches through the old module -- that
     re-export must be the identical object (`is`). Why so strict: without a re-export, a stale
     `monkeypatch.setattr(core, "name", ...)` raises AttributeError at once; with one, it
     silently patches a binding nobody calls. So the old module reaches a moved name as
     `_newmod.name`, never through `from moonglade.newmod import name`.
  3. A new module imports moonglade.backup / moonglade.gallery only INSIDE functions (the
     existing lazy idiom), never at import time, so no import cycle can form.
  4. THE PATCH-TARGET LINT: no file under dev/tests patches a moved name through its old module
     (setattr / delattr / mock.patch / patch.object / plain `alias.name = ...`), and no patch of
     a moved name sits on a receiver the scanner cannot resolve. The scanner lives in
     dev/tools/retarget_patches.py so the lint and the codemod can never disagree.
     Production code gets the same treatment: a `core.name` on a `core` the scanner cannot pin
     to a module there (tuple-bound, a parameter its calls disagree about) is listed, and one
     naming a moved name fails (check_production_gaps).
  5. The tests that read a megamodule's SOURCE (inspect.getsource, opening the file by path,
     AST walks of create_app) are a known set, SOURCE_READERS. A move that touches what one of
     them reads must be acknowledged in SOURCE_READERS_REVIEWED after someone looked.

SEAMS must stay a plain literal: the codemod reads it with ast.literal_eval, without importing
this file.
"""
import ast
import importlib
import importlib.util
import inspect
import re
import types
from pathlib import Path

import pytest

DEV = Path(__file__).resolve().parents[1]
REPO = DEV.parent

_TOOL = DEV / "tools" / "retarget_patches.py"
_spec = importlib.util.spec_from_file_location("retarget_patches", _TOOL)
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)

OLD_MODULES = rp.OLD_MODULES

# new module -> {"from": old module, "names": [names it owns]}. One entry per move.
SEAMS = {
    "moonglade.scan": {"from": "moonglade.gallery", "names": [
        "_IMAGE_EXTS", "GALLERY_DIRNAME", "DUPLICATES_DIRNAME", "DELETED_DIRNAME",
        "BRANDING_DIRNAME", "RECORDS_DIRNAME", "QUARANTINE_EXCLUDE", "QUARANTINE_EXCLUDE_ANYWHERE",
        "IMPORT_EXCLUDE", "IMPORT_REQUEST_CAP", "HEALTH_EXCLUDE", "_VIDEO_EXTS", "_EMBED_EXTS",
        "SCAN_KINDS", "_KIND_BY_EXT", "MediaEntry", "bucket_of", "media_id_of", "_is_under",
        "_kind_map", "_split_exclusions", "scan_library", "files_for", "find_files_for_media_id",
        "find_local_video_file"]},
    "moonglade.dupes": {"from": "moonglade.gallery", "names": [
        "DHASH_SIZE", "duplicate_groups", "same_seed_groups", "NEAR_DUP_HAMMING_THRESHOLD",
        "near_duplicate_groups"]},
    "moonglade.series": {"from": "moonglade.gallery", "names": [
        "_series_text", "_series_clause_list", "_series_ts", "_SERIES_SCAFFOLD",
        "_series_is_scaffold", "_series_cap_first", "_series_title", "_series_delta_label",
        "compute_series", "_SERIES_CACHE", "_SERIES_CACHE_LOCK", "_SERIES_RECOMPUTE_FLOOR_S",
        "series_index", "_series_cover_row", "fold_series_units"]},
    "moonglade.organize": {"from": "moonglade.backup", "names": [
        "_BUCKET_PRIORITY", "_scan_media_files", "audit_collection", "_fmt_bytes",
        "cmd_audit", "cmd_dedup", "verify_quarantine", "cmd_verify_dupes",
        "reconcile_catalog_with_disk", "ORGANIZE_MANIFEST", "cmd_organize", "cmd_undo_organize"]},
    "moonglade.health": {"from": "moonglade.gallery", "names": [
        "_fmt_size", "collection_health", "STORAGE_TOP", "_STORAGE_TYPES", "storage_breakdown",
        "_HEALTH_CACHE", "_HEALTH_LOCK", "_HEALTH_BUSY", "HEALTH_MAX_AGE", "_health_key",
        "_health_dir_key", "_health_memo_key", "health_snapshot", "_health_refresh_async",
        "health_cached", "health_avg_file_bytes", "_health_prime"]},
    "moonglade.account_prefs": {"from": "moonglade.gallery", "names": [
        "_account_key", "ACCOUNT_PREFS_NAME", "ACCOUNT_PREF_KEY_MAX", "ACCOUNT_PREF_VALUE_MAX",
        "ACCOUNT_PREFS_DOC_MAX", "ACCOUNT_PREF_KEY_RE", "_ACCOUNT_PREFS_LOCK", "_AccountLocal",
        "ACCOUNT_LOCAL", "AccountPrefsError", "AccountPrefsBusy", "account_prefs_path",
        "_account_prefs_read", "account_pref_key_problem", "_account_pref_normalise",
        "account_prefs_get", "account_prefs_update", "ACCOUNT_STATE_NAME", "_ACCOUNT_STATE_LOCK",
        "account_state_path", "account_state_locked", "_narrator_clock", "account_state_read",
        "account_state_write", "_account_prefs_set_aside"]},
    "moonglade.jobs": {"from": "moonglade.backup", "names": [
        "JOBS_LOG_NAME", "JOBS_KEEP", "JOBS_MAX_AGE", "_JOBS_TERMINAL", "_JOBS_COMPACT_AT",
        "JOBS_ORPHAN_SWEEP_AGE", "_jobs_compact_lock", "_jobs_path", "append_job_event",
        "_cli_job_start", "_cli_job_finish", "_reconstruct_jobs", "_job_expired", "_select_jobs",
        "read_jobs", "resolve_orphan_jobs", "_JOBS_SERVER_OWNED_PREFIXES",
        "resolve_interrupted_local_jobs", "maybe_compact_jobs"]},
    "moonglade.pixai_client": {"from": "moonglade.backup", "names": [
        "_is_mutation_document", "PixAIClient", "_client_of"]},
    "moonglade.updater": {"from": "moonglade.gallery", "names": [
        "GITHUB_RELEASES_URL", "UPDATE_CHECK_TTL", "UPDATE_FAILURE_TTL", "UPDATE_RESTART_DELAY",
        "UPDATE_FETCH_TIMEOUT", "_VERSION_TAG_RE", "_update_cache", "_update_state",
        "_update_lock", "version_tuple", "pick_latest_release", "fetch_releases",
        "check_for_update", "UPDATE_TICK_SECONDS", "UPDATE_PANEL_FLOOR", "_update_tick",
        "_update_floor", "_update_notice", "note_update_transition", "update_notice",
        "run_update_tick", "check_for_update_fresh", "_git", "update_state", "_set_update_state",
        "_requirements_changed", "split_porcelain", "incoming_paths", "untracked_in_the_way",
        "run_update", "_pip_install"]},
    "moonglade.about": {"from": "moonglade.gallery", "names": [
        "WIKI_WEB_URL", "WIKI_RAW_URL", "RELEASES_WEB_URL", "ISSUES_WEB_URL", "_WIKI_SLUG_RE",
        "_WIKI_LINK_RE", "_MD_HEADING_RE", "_GLOSSARY_ITEM_RE", "_CHANGELOG_HEAD_RE",
        "_SURFACE_MARK_RE", "HELP_SURFACES", "_SURFACE_WORDS", "WIKI_ONLINE_TTL",
        "WIKI_ONLINE_FAILURE_TTL", "_wiki_online_cache", "_wiki_online_lock", "wiki_dir",
        "changelog_path", "md_plain", "display_version", "release_kind", "wiki_web_url",
        "_wiki_pages_on_disk", "md_headings", "wiki_index", "wiki_glossary", "_changelog_surface",
        "_changelog_item", "changelog_entries", "art_pack_info", "about_payload", "_md_same",
        "wiki_online_differs"]},
    "moonglade.media_tools": {"from": "moonglade.backup", "names": [
        "NO_WINDOW", "PROBE_TIMEOUT", "FRAME_TIMEOUT", "THUMB_TIMEOUT", "THUMB_RETRY_TIMEOUT",
        "REMUX_TIMEOUT", "ToolResult", "_TOOL_PATHS", "_tool_path", "ffmpeg_path", "ffprobe_path",
        "_reset_tool_cache", "_as_text", "_run_tool", "run_ffmpeg", "run_ffprobe", "duration",
        "has_audio", "frame_seek_point", "extract_last_frame", "frame_at", "video_poster_thumb",
        "_mp4_is_faststart", "FASTSTART_REWROTE", "FASTSTART_NOT_NEEDED", "FASTSTART_REFUSED",
        "_video_faststart_attempt", "video_faststart"]},
    "moonglade.mirror": {"from": "moonglade.backup", "names": [
        "MIRROR_REFRESH_PATH", "MIRROR_REFRESH_WHEN_DAYS_LEFT", "MIRROR_TOKEN_LIFE_S",
        "MIRROR_WEB_USER_AGENT", "MIRROR_WEB_ORIGIN", "_b64url_decode",
        "jwt_claims", "jwt_expiry", "jwt_days_left", "mirror_needs_refresh", "_is_api_key",
        "_renewal_headers", "_fresh_pixai_token", "refresh_jwt", "_drop_cookies", "_refresh_last",
        "_mirror_lock", "_MIRROR_REFRESH_COOLDOWN", "MIRROR_RENEW_BACKOFF_CAP_S",
        "MIRROR_RENEW_FLOOR_S", "MIRROR_RENEW_TICK_S", "_mirror_renewal", "_mirror_renewal_reset",
        "_mirror_state_path", "load_mirror_state", "save_mirror_state", "mirror_enabled",
        "_jwt_usable", "_mirror_session_from", "WEB_IDENTITY_HEADERS", "present_as_web",
        "mirror_token_span", "_mirror_try_renew", "make_mirror_session", "mirror_renew_tick",
        "mirror_renewal_status", "_session_for_create", "run_mirror_check"]},
    "moonglade.living": {"from": "moonglade.gallery", "names": [
        "ARTWORKS_SWEEP_S", "ARTWORKS_YOUNG_DAYS", "ARTWORKS_DEEP_S", "ARTWORKS_GRACE",
        "ARTWORKS_PAGE", "ARTWORKS_PAUSE", "ARTWORKS_MAX_PAGES", "ARTWORKS_STARTUP_DELAY",
        "_artworks_lock", "_artworks_state", "_artworks_refusal", "_note_artworks_refusal",
        "published_index", "published_local_ids", "artworks_page_needed", "artworks_sweep",
        "artworks_sweep_fresh", "artworks_sweep_in_flight", "artworks_sweep_kick",
        "STALE_BACKSTOP_S", "LIVING_JOBS", "LIVING_STALE_JOBS", "LIVING_ALL", "LIVING_BY_ACTION",
        "LIVING_STALE_ACTIONS", "ARTWORKS_TOUCHING_ACTIONS", "LIVING_SWEEP_ACTION",
        "LIVING_MIN_INTERVAL_S", "LIVING_MAX_INTERVAL_S", "_torch_present",
        "living_clamp_interval", "living_merge", "living_due", "SPIKE_MIN_GAIN",
        "SPIKE_RATE_MULTIPLE", "SPIKE_MIN_WINDOW_H", "SPIKE_MIN_LIFETIME_H", "SPIKE_SELF_READ",
        "views_spike", "top_published_rows", "published_totals", "published_spikes"]},
    "moonglade.telemetry": {"from": "moonglade.gallery", "names": [
        "_TELEM_LOCK", "_TELEM_OUT", "_telemetry_path", "set_telemetry_out", "_TELEM_EMPTY",
        "load_telemetry", "_save_telemetry", "_telem_file_lock", "_excl_lockfile",
        "_telem_mutate", "telem_bump", "telem_max", "telem_set_discard", "telem_set_add",
        "telem_set_add_many", "telem_flag", "telem_mark_day", "_best_day_streak", "vigil_status",
        "telemetry_metrics", "CATALOG_EVIDENCE_METRICS", "SESSION_HOUR_WINDOW",
        "SESSION_HOUR_FRESH_S", "_SESSION_HOUR_SKEW_S", "_utc_now", "session_hour_generation",
        "stamp_session_hour", "first_sync_complete", "sweep_telemetry"]},
    "moonglade.contest_sync": {"from": "moonglade.gallery", "names": [
        "CONTESTS_TTL", "_contests_cache", "_contests_cache_lock", "contest_board",
        "contest_board_meta", "CONTEST_SYNC_RECENT_S", "_contest_sync_last_ok",
        "_CONTEST_SYNC_MAX", "_CONTEST_SYNC_RECENT_DAYS", "_CONTEST_SYNC_PAUSE",
        "_CONTEST_SYNC_STARTUP_DELAY", "_contest_sync_lock", "_contest_sync_is_recent",
        "_contest_detection_sync", "_contest_sync_kick", "_CW_PAUSE", "_CW_BOARD_BACKOFF_S",
        "_cw_lock", "_cw_state", "_cw_sections", "_cw_edit", "_cw_inputs", "contest_win_due",
        "contest_win_refresh", "contest_win_pass", "contest_win_kick", "contest_win_check",
        "_cw_check_view"]},
    "moonglade.achievements": {"from": "moonglade.gallery", "names": [
        "_FALLBACK_DEFS", "_sealed_cache", "_sealed_lock", "_sealed_defs", "_derive_sealed",
        "_roster", "_skins", "_skin_unlock", "_ach_criteria", "_ladder_tracks", "_ach_ids",
        "_ach_hidden", "_ach_rung", "_skin_ids", "_moment_ach", "_poke_lines",
        "_PROMPT_STOPWORDS", "_prompt_word_counter", "_ACH_METRICS_CACHE", "_ACH_METRICS_LOCK",
        "achievement_metrics", "_TIER_POINTS", "LADDER_METRIC_WORDS", "metric_words",
        "_build_ach_rung", "achievement_points", "achievement_criteria", "compute_achievements",
        "_MEASURED_METRICS", "achievement_progress", "claim_job_label", "_ach_state_path",
        "load_ach_state", "save_ach_state", "badge_cache_dir", "_badge_thumb",
        "_BADGE_ANIM_MAX_BYTES", "_badge_anim"]},
    "moonglade.branding": {"from": "moonglade.gallery", "names": [
        "MARK_ANIMS", "MARK_ANIMS_RETIRED", "_BRAND_NUM_RANGES", "_HEX_COLOR_RE",
        "_BRAND_DEFAULTS", "_brand_num", "_brand_color", "branding_root", "_GOODS_ROOT_NAME",
        "_GOODS_MID", "_LEGACY_THUMB_DIR", "ROLE_CODE", "_MOMENT_CLIPS", "_MOMENT_CLIP_ROLES",
        "_role_rel", "_role_dir", "_SYSTEM_TOP_FILES", "_public_rel_to_coded", "_container_path",
        "_container_cache", "_container_lock", "_get_container", "_branding_bytes",
        "_branding_exists", "_branding_mtime", "_moment_clip_cache", "_moment_clip_cache_lock",
        "_moment_clip_rels", "_container_clip_bytes", "_ranged_bytes_response", "_seal_rule",
        "_earned_ids_cache", "_earned_ids_lock", "_earned_achievement_ids",
        "_seed_loose_manifest", "_MARK_TOMBSTONES", "MARK_EXTS", "mark_art_ext", "list_marks",
        "_earned_roster_flags", "earned_relic_marks", "FEAT_MASK_PX", "feat_mask_png",
        "_feat_riddles", "_pick_masked_feat", "_feat_mask_token", "_feats_payload",
        "feat_mask_cache_dir", "_feat_mask_bytes", "_ach_name", "_mark_unlock_for",
        "BANNER_SLOTS", "ROLE_SLOTS", "BRANDING_SLOTS", "ROLE_MAX_BYTES", "ROLE_MAX_SIDE",
        "ROLE_ASPECT_TOLERANCE", "ROLE_SEE_THROUGH_MIN", "ROLE_MAX_FRAMES",
        "ROLE_MAX_ANIM_PIXELS", "ROLE_OPEN_FORMATS", "BANNER_MAX_SIDE", "_slot_dir",
        "_asset_transform", "list_slot_assets", "_recorded_slot_active", "resolve_slot_active",
        "load_slot_active", "save_slot_active", "add_slot_asset", "set_slot_crop",
        "set_slot_active", "_mark_earned", "ICO_SIZES", "_cut_mark_ico", "add_custom_mark",
        "remove_custom_mark", "branding_slots_payload", "_ratio_label", "role_image_spec",
        "_aspect_words", "role_spec_failures", "_ROLE_NEED_VERB", "role_refusal_text",
        "ImageRefused", "_UNREADABLE", "webp_declared_size", "guard_webp_canvas", "role_measure",
        "_ROLE_KEEP_CHUNKS", "_role_animation_bytes", "_role_coded_rel", "_role_override_path",
        "_role_coded_rels", "_role_decode_memo", "_role_file_decodes", "branding_roles_payload",
        "_role_payload", "branding_role_upload", "branding_role_restore", "_BRANDING_README",
        "_BRANDING_DISCOVERY_SLOTS", "_migrate_legacy_branding_root",
        "ensure_branding_discovery_tree", "_migrate_root_banner_flats", "_is_readable_image",
        "_BRANDING_WALK_MAX_DEPTH", "_BASELINE_GOODS", "_BASELINE_HEAD", "_BASELINE_SETTLE_NS",
        "_BASELINE_CLEAN_MEMO", "_BASELINE_CLEAN_MEMO_MAX", "_branding_tree_files",
        "_file_fingerprint", "_baseline_key", "_branding_baseline", "_record_branding_baseline",
        "_baseline_note_app_write", "_branding_tree_has_new_art", "_adopt_dropped_file",
        "_adopt_mark", "_SWEEPABLE_SLOTS", "_BANNER_FLAT", "_BANNER_FLAT_DEFAULT",
        "_flat_default_rel", "banner_cache_dir", "banner_keep_dir", "_EARNED_BANNERS",
        "_served_flat_dir", "_worn_banner", "_set_worn_banner", "_BANNER_RATIO", "_BANNER_OUT",
        "_banner_window", "_banner_record_path", "_read_banner_record", "_write_banner_record",
        "_slot_render_record", "_render_banner_flat", "_write_banner_flat", "_earned_banner_ok",
        "_ensure_banner_flat", "_record_slot_resolution", "_ensure_banner_renders",
        "sweep_branding_drops", "load_branding", "save_branding", "_branding_tuning",
        "brand_context", "_mark_ico_path", "make_launcher_shortcut", "PACK_PROGID",
        "PACK_TYPE_NAME", "register_pack_file_type", "_pack_type_icon",
        "_tell_explorer_file_types_changed"]},
}

# Every file under dev/ (the suite and the tools) that reads an old module's source, and which
# old module(s); and every node test (loom/test, loom/test-support, gallery/; keyed from the repo
# root) that reads a moonglade/*.py file, and which. Kept exact: a new reader, or one that stops
# reading, fails test_source_readers_are_the_known_set.
SOURCE_READERS = {
    "tests/test_app_paths.py": ("moonglade.gallery",),
    "tests/test_artworks_adhoc.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_bonjour.py": ("moonglade.gallery",),
    "tests/test_branding.py": ("moonglade.gallery",),
    "tests/test_branding_tree_rules.py": ("moonglade.gallery",),
    "tests/test_catalog_verbs.py": ("moonglade.gallery",),
    "tests/test_catchup_query.py": ("moonglade.gallery",),
    "tests/test_cli_doc_coverage.py": ("moonglade.backup",),
    "tests/test_community_surface.py": ("moonglade.backup",),
    "tests/test_config_path_routing.py": ("moonglade.backup",),
    "tests/test_contest_wins.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_csrf_coverage.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_delete_routing.py": ("moonglade.backup",),
    "tests/test_design_kit_sync.py": ("moonglade.gallery",),
    "tests/test_doc_truth_residuals.py": ("moonglade.gallery",),
    "tests/test_edit_upload.py": ("moonglade.backup",),
    "tests/test_enhance.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_evidence_counters.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_first_party_sources.py": ("moonglade.gallery",),
    "tests/test_gen_surface.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_history_feed_document.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_jwt.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_library_dir.py": ("moonglade.gallery",),
    "tests/test_living_library.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_logging.py": ("moonglade.gallery",),
    "tests/test_loom_generate_guard.py": ("moonglade.gallery",),
    "tests/test_loom_notify.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_loom_p_routes.py": ("moonglade.gallery",),
    "tests/test_media_tools.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_move_edges.py": ("moonglade.gallery",),
    "tests/test_network.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_outside_notice.py": ("moonglade.gallery",),
    "tests/test_pack_file_name.py": ("moonglade.gallery",),
    "tests/test_pack_file_type.py": ("moonglade.gallery",),
    "tests/test_panel.py": ("moonglade.gallery",),
    "tests/test_pixai_client.py": ("moonglade.backup",),
    "tests/test_read_only.py": ("moonglade.backup",),
    "tests/test_module_seams.py": ("moonglade.backup", "moonglade.gallery"),   # every module
    "tests/test_rest_delete_and_renewal.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_security_review_fixes.py": ("moonglade.gallery",),
    "tests/test_server_stop_record.py": ("moonglade.gallery",),
    "tests/test_settings_store.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_setup_prepare.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_spend_no_retry.py": ("moonglade.backup",),
    "tests/test_task_model_detail_document.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_telemetry.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_training_advanced.py": ("moonglade.backup",),
    "tests/test_training_parity.py": ("moonglade.backup",),
    "tests/test_tsubaki3_image_gate.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_updater.py": ("moonglade.gallery",),
    "tests/test_video_tsubaki.py": ("moonglade.backup",),
    "tests/test_watch.py": ("moonglade.gallery",),
    "tests/test_web_auth.py": ("moonglade.backup",),
    "tools/export_design_kit.py": ("moonglade.gallery",),     # reads DESIGN_TOKENS_CSS by path
    "loom/test/import-batches.test.js": ("moonglade.scan",),
    "loom/test/ledger-known-reasons.test.js": ("moonglade.backup",),
    "loom/test/med-loom-bundle-missing-report.test.js": ("moonglade.gallery",),
    "loom/test/mg-art-filters.test.js": ("moonglade.gallery",),
    "loom/test/mg-notify-queue-phase.test.js": ("moonglade.gallery",),
    "loom/test/mg-notify-website-source.test.js": ("moonglade.gallery",),
    "loom/test/phone-back-layers.test.js": ("moonglade.gallery",),
    "loom/test/video-roster-parity.test.js": ("moonglade.backup",),
}

# (reader file, new module) pairs someone has checked after a move touched what the reader
# reads (see check_source_readers_reviewed). One block per move.
SOURCE_READERS_REVIEWED = {
    ("tests/test_app_paths.py", "moonglade.scan"),
    ("tests/test_artworks_adhoc.py", "moonglade.scan"),
    ("tests/test_bonjour.py", "moonglade.scan"),
    ("tests/test_branding.py", "moonglade.scan"),
    ("tests/test_catalog_verbs.py", "moonglade.scan"),
    ("tests/test_catchup_query.py", "moonglade.scan"),
    ("tests/test_csrf_coverage.py", "moonglade.scan"),
    ("tests/test_design_kit_sync.py", "moonglade.scan"),
    ("tests/test_doc_truth_residuals.py", "moonglade.scan"),
    ("tests/test_enhance.py", "moonglade.scan"),
    ("tests/test_evidence_counters.py", "moonglade.scan"),
    ("tests/test_first_party_sources.py", "moonglade.scan"),
    ("tests/test_gen_surface.py", "moonglade.scan"),
    ("tests/test_history_feed_document.py", "moonglade.scan"),
    ("tests/test_library_dir.py", "moonglade.scan"),
    ("tests/test_living_library.py", "moonglade.scan"),
    ("tests/test_logging.py", "moonglade.scan"),
    ("tests/test_loom_generate_guard.py", "moonglade.scan"),
    ("tests/test_loom_notify.py", "moonglade.scan"),
    ("tests/test_loom_p_routes.py", "moonglade.scan"),
    ("tests/test_media_tools.py", "moonglade.scan"),
    ("tests/test_network.py", "moonglade.scan"),
    ("tests/test_panel.py", "moonglade.scan"),
    ("tests/test_settings_store.py", "moonglade.scan"),
    ("tests/test_setup_prepare.py", "moonglade.scan"),
    ("tests/test_task_model_detail_document.py", "moonglade.scan"),
    ("tests/test_telemetry.py", "moonglade.scan"),
    ("tests/test_tsubaki3_image_gate.py", "moonglade.scan"),
    ("tests/test_watch.py", "moonglade.scan"),
    ("tools/export_design_kit.py", "moonglade.scan"),
    ("tests/test_app_paths.py", "moonglade.dupes"),
    ("tests/test_artworks_adhoc.py", "moonglade.dupes"),
    ("tests/test_bonjour.py", "moonglade.dupes"),
    ("tests/test_branding.py", "moonglade.dupes"),
    ("tests/test_catalog_verbs.py", "moonglade.dupes"),
    ("tests/test_catchup_query.py", "moonglade.dupes"),
    ("tests/test_csrf_coverage.py", "moonglade.dupes"),
    ("tests/test_design_kit_sync.py", "moonglade.dupes"),
    ("tests/test_doc_truth_residuals.py", "moonglade.dupes"),
    ("tests/test_enhance.py", "moonglade.dupes"),
    ("tests/test_evidence_counters.py", "moonglade.dupes"),
    ("tests/test_first_party_sources.py", "moonglade.dupes"),
    ("tests/test_gen_surface.py", "moonglade.dupes"),
    ("tests/test_history_feed_document.py", "moonglade.dupes"),
    ("tests/test_library_dir.py", "moonglade.dupes"),
    ("tests/test_living_library.py", "moonglade.dupes"),
    ("tests/test_logging.py", "moonglade.dupes"),
    ("tests/test_loom_generate_guard.py", "moonglade.dupes"),
    ("tests/test_loom_notify.py", "moonglade.dupes"),
    ("tests/test_loom_p_routes.py", "moonglade.dupes"),
    ("tests/test_media_tools.py", "moonglade.dupes"),
    ("tests/test_network.py", "moonglade.dupes"),
    ("tests/test_settings_store.py", "moonglade.dupes"),
    ("tests/test_setup_prepare.py", "moonglade.dupes"),
    ("tests/test_task_model_detail_document.py", "moonglade.dupes"),
    ("tests/test_telemetry.py", "moonglade.dupes"),
    ("tests/test_tsubaki3_image_gate.py", "moonglade.dupes"),
    ("tests/test_watch.py", "moonglade.dupes"),
    ("tools/export_design_kit.py", "moonglade.dupes"),
    ("tests/test_app_paths.py", "moonglade.series"),
    ("tests/test_artworks_adhoc.py", "moonglade.series"),
    ("tests/test_bonjour.py", "moonglade.series"),
    ("tests/test_branding.py", "moonglade.series"),
    ("tests/test_catalog_verbs.py", "moonglade.series"),
    ("tests/test_catchup_query.py", "moonglade.series"),
    ("tests/test_csrf_coverage.py", "moonglade.series"),
    ("tests/test_design_kit_sync.py", "moonglade.series"),
    ("tests/test_doc_truth_residuals.py", "moonglade.series"),
    ("tests/test_enhance.py", "moonglade.series"),
    ("tests/test_evidence_counters.py", "moonglade.series"),
    ("tests/test_first_party_sources.py", "moonglade.series"),
    ("tests/test_gen_surface.py", "moonglade.series"),
    ("tests/test_history_feed_document.py", "moonglade.series"),
    ("tests/test_library_dir.py", "moonglade.series"),
    ("tests/test_living_library.py", "moonglade.series"),
    ("tests/test_logging.py", "moonglade.series"),
    ("tests/test_loom_generate_guard.py", "moonglade.series"),
    ("tests/test_loom_notify.py", "moonglade.series"),
    ("tests/test_loom_p_routes.py", "moonglade.series"),
    ("tests/test_media_tools.py", "moonglade.series"),
    ("tests/test_network.py", "moonglade.series"),
    ("tests/test_settings_store.py", "moonglade.series"),
    ("tests/test_setup_prepare.py", "moonglade.series"),
    ("tests/test_task_model_detail_document.py", "moonglade.series"),
    ("tests/test_telemetry.py", "moonglade.series"),
    ("tests/test_tsubaki3_image_gate.py", "moonglade.series"),
    ("tests/test_watch.py", "moonglade.series"),
    ("tools/export_design_kit.py", "moonglade.series"),
    ("tests/test_artworks_adhoc.py", "moonglade.organize"),
    ("tests/test_cli_doc_coverage.py", "moonglade.organize"),
    ("tests/test_config_path_routing.py", "moonglade.organize"),
    ("tests/test_csrf_coverage.py", "moonglade.organize"),
    ("tests/test_enhance.py", "moonglade.organize"),
    ("tests/test_evidence_counters.py", "moonglade.organize"),
    ("tests/test_gen_surface.py", "moonglade.organize"),
    ("tests/test_history_feed_document.py", "moonglade.organize"),
    ("tests/test_jwt.py", "moonglade.organize"),
    ("tests/test_living_library.py", "moonglade.organize"),
    ("tests/test_loom_notify.py", "moonglade.organize"),
    ("tests/test_media_tools.py", "moonglade.organize"),
    ("tests/test_network.py", "moonglade.organize"),
    ("tests/test_read_only.py", "moonglade.organize"),
    ("tests/test_settings_store.py", "moonglade.organize"),
    ("tests/test_setup_prepare.py", "moonglade.organize"),
    ("tests/test_spend_no_retry.py", "moonglade.organize"),
    ("tests/test_task_model_detail_document.py", "moonglade.organize"),
    ("tests/test_training_advanced.py", "moonglade.organize"),
    ("tests/test_training_parity.py", "moonglade.organize"),
    ("tests/test_tsubaki3_image_gate.py", "moonglade.organize"),
    ("tests/test_web_auth.py", "moonglade.organize"),
    # the node tests, reviewed for the phase-1 moves when they joined the set (phase 2)
    ("loom/test/med-loom-bundle-missing-report.test.js", "moonglade.scan"),
    ("loom/test/med-loom-bundle-missing-report.test.js", "moonglade.dupes"),
    ("loom/test/med-loom-bundle-missing-report.test.js", "moonglade.series"),
    ("loom/test/mg-art-filters.test.js", "moonglade.scan"),
    ("loom/test/mg-art-filters.test.js", "moonglade.dupes"),
    ("loom/test/mg-art-filters.test.js", "moonglade.series"),
    ("loom/test/mg-notify-queue-phase.test.js", "moonglade.scan"),
    ("loom/test/mg-notify-queue-phase.test.js", "moonglade.dupes"),
    ("loom/test/mg-notify-queue-phase.test.js", "moonglade.series"),
    ("loom/test/mg-notify-website-source.test.js", "moonglade.scan"),
    ("loom/test/mg-notify-website-source.test.js", "moonglade.dupes"),
    ("loom/test/mg-notify-website-source.test.js", "moonglade.series"),
    ("loom/test/phone-back-layers.test.js", "moonglade.scan"),
    ("loom/test/phone-back-layers.test.js", "moonglade.dupes"),
    ("loom/test/phone-back-layers.test.js", "moonglade.series"),
    ("loom/test/ledger-known-reasons.test.js", "moonglade.organize"),
    ("loom/test/video-roster-parity.test.js", "moonglade.organize"),
    ('loom/test/med-loom-bundle-missing-report.test.js', 'moonglade.health'),
    ('loom/test/mg-art-filters.test.js', 'moonglade.health'),
    ('loom/test/mg-notify-queue-phase.test.js', 'moonglade.health'),
    ('loom/test/mg-notify-website-source.test.js', 'moonglade.health'),
    ('loom/test/phone-back-layers.test.js', 'moonglade.health'),
    ('tests/test_app_paths.py', 'moonglade.health'),
    ('tests/test_artworks_adhoc.py', 'moonglade.health'),
    ('tests/test_bonjour.py', 'moonglade.health'),
    ('tests/test_branding.py', 'moonglade.health'),
    ('tests/test_catalog_verbs.py', 'moonglade.health'),
    ('tests/test_catchup_query.py', 'moonglade.health'),
    ('tests/test_csrf_coverage.py', 'moonglade.health'),
    ('tests/test_design_kit_sync.py', 'moonglade.health'),
    ('tests/test_doc_truth_residuals.py', 'moonglade.health'),
    ('tests/test_evidence_counters.py', 'moonglade.health'),
    ('tests/test_first_party_sources.py', 'moonglade.health'),
    ('tests/test_gen_surface.py', 'moonglade.health'),
    ('tests/test_history_feed_document.py', 'moonglade.health'),
    ('tests/test_library_dir.py', 'moonglade.health'),
    ('tests/test_living_library.py', 'moonglade.health'),
    ('tests/test_logging.py', 'moonglade.health'),
    ('tests/test_loom_generate_guard.py', 'moonglade.health'),
    ('tests/test_loom_notify.py', 'moonglade.health'),
    ('tests/test_loom_p_routes.py', 'moonglade.health'),
    ('tests/test_network.py', 'moonglade.health'),
    ('tests/test_settings_store.py', 'moonglade.health'),
    ('tests/test_setup_prepare.py', 'moonglade.health'),
    ('tests/test_task_model_detail_document.py', 'moonglade.health'),
    ('tests/test_telemetry.py', 'moonglade.health'),
    ('tests/test_watch.py', 'moonglade.health'),
    ('tools/export_design_kit.py', 'moonglade.health'),
    ('loom/test/med-loom-bundle-missing-report.test.js', 'moonglade.account_prefs'),
    ('loom/test/mg-art-filters.test.js', 'moonglade.account_prefs'),
    ('loom/test/mg-notify-queue-phase.test.js', 'moonglade.account_prefs'),
    ('loom/test/mg-notify-website-source.test.js', 'moonglade.account_prefs'),
    ('loom/test/phone-back-layers.test.js', 'moonglade.account_prefs'),
    ('tests/test_app_paths.py', 'moonglade.account_prefs'),
    ('tests/test_artworks_adhoc.py', 'moonglade.account_prefs'),
    ('tests/test_bonjour.py', 'moonglade.account_prefs'),
    ('tests/test_branding.py', 'moonglade.account_prefs'),
    ('tests/test_catalog_verbs.py', 'moonglade.account_prefs'),
    ('tests/test_catchup_query.py', 'moonglade.account_prefs'),
    ('tests/test_csrf_coverage.py', 'moonglade.account_prefs'),
    ('tests/test_design_kit_sync.py', 'moonglade.account_prefs'),
    ('tests/test_doc_truth_residuals.py', 'moonglade.account_prefs'),
    ('tests/test_evidence_counters.py', 'moonglade.account_prefs'),
    ('tests/test_first_party_sources.py', 'moonglade.account_prefs'),
    ('tests/test_gen_surface.py', 'moonglade.account_prefs'),
    ('tests/test_history_feed_document.py', 'moonglade.account_prefs'),
    ('tests/test_library_dir.py', 'moonglade.account_prefs'),
    ('tests/test_living_library.py', 'moonglade.account_prefs'),
    ('tests/test_logging.py', 'moonglade.account_prefs'),
    ('tests/test_loom_generate_guard.py', 'moonglade.account_prefs'),
    ('tests/test_loom_notify.py', 'moonglade.account_prefs'),
    ('tests/test_loom_p_routes.py', 'moonglade.account_prefs'),
    ('tests/test_network.py', 'moonglade.account_prefs'),
    ('tests/test_settings_store.py', 'moonglade.account_prefs'),
    ('tests/test_setup_prepare.py', 'moonglade.account_prefs'),
    ('tests/test_task_model_detail_document.py', 'moonglade.account_prefs'),
    ('tests/test_telemetry.py', 'moonglade.account_prefs'),
    ('tests/test_watch.py', 'moonglade.account_prefs'),
    ('tools/export_design_kit.py', 'moonglade.account_prefs'),
    ('loom/test/ledger-known-reasons.test.js', 'moonglade.jobs'),
    ('loom/test/video-roster-parity.test.js', 'moonglade.jobs'),
    ('tests/test_artworks_adhoc.py', 'moonglade.jobs'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.jobs'),
    ('tests/test_config_path_routing.py', 'moonglade.jobs'),
    ('tests/test_csrf_coverage.py', 'moonglade.jobs'),
    ('tests/test_enhance.py', 'moonglade.jobs'),
    ('tests/test_evidence_counters.py', 'moonglade.jobs'),
    ('tests/test_gen_surface.py', 'moonglade.jobs'),
    ('tests/test_history_feed_document.py', 'moonglade.jobs'),
    ('tests/test_jwt.py', 'moonglade.jobs'),
    ('tests/test_living_library.py', 'moonglade.jobs'),
    ('tests/test_loom_notify.py', 'moonglade.jobs'),
    ('tests/test_network.py', 'moonglade.jobs'),
    ('tests/test_settings_store.py', 'moonglade.jobs'),
    ('tests/test_setup_prepare.py', 'moonglade.jobs'),
    ('tests/test_spend_no_retry.py', 'moonglade.jobs'),
    ('tests/test_task_model_detail_document.py', 'moonglade.jobs'),
    ('tests/test_training_advanced.py', 'moonglade.jobs'),
    ('tests/test_training_parity.py', 'moonglade.jobs'),
    ('tests/test_web_auth.py', 'moonglade.jobs'),
    ('loom/test/ledger-known-reasons.test.js', 'moonglade.pixai_client'),
    ('loom/test/video-roster-parity.test.js', 'moonglade.pixai_client'),
    ('tests/test_artworks_adhoc.py', 'moonglade.pixai_client'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.pixai_client'),
    ('tests/test_community_surface.py', 'moonglade.pixai_client'),
    ('tests/test_config_path_routing.py', 'moonglade.pixai_client'),
    ('tests/test_csrf_coverage.py', 'moonglade.pixai_client'),
    ('tests/test_edit_upload.py', 'moonglade.pixai_client'),
    ('tests/test_enhance.py', 'moonglade.pixai_client'),
    ('tests/test_evidence_counters.py', 'moonglade.pixai_client'),
    ('tests/test_gen_surface.py', 'moonglade.pixai_client'),
    ('tests/test_history_feed_document.py', 'moonglade.pixai_client'),
    ('tests/test_jwt.py', 'moonglade.pixai_client'),
    ('tests/test_living_library.py', 'moonglade.pixai_client'),
    ('tests/test_loom_notify.py', 'moonglade.pixai_client'),
    ('tests/test_network.py', 'moonglade.pixai_client'),
    ('tests/test_pixai_client.py', 'moonglade.pixai_client'),
    ('tests/test_settings_store.py', 'moonglade.pixai_client'),
    ('tests/test_setup_prepare.py', 'moonglade.pixai_client'),
    ('tests/test_spend_no_retry.py', 'moonglade.pixai_client'),
    ('tests/test_task_model_detail_document.py', 'moonglade.pixai_client'),
    ('tests/test_training_advanced.py', 'moonglade.pixai_client'),
    ('tests/test_training_parity.py', 'moonglade.pixai_client'),
    ('tests/test_web_auth.py', 'moonglade.pixai_client'),
    ('tests/test_updater.py', 'moonglade.scan'),
    ('tests/test_updater.py', 'moonglade.dupes'),
    ('tests/test_updater.py', 'moonglade.series'),
    ('tests/test_updater.py', 'moonglade.health'),
    ('tests/test_updater.py', 'moonglade.account_prefs'),
    ('loom/test/med-loom-bundle-missing-report.test.js', 'moonglade.updater'),
    ('loom/test/mg-art-filters.test.js', 'moonglade.updater'),
    ('loom/test/mg-notify-queue-phase.test.js', 'moonglade.updater'),
    ('loom/test/mg-notify-website-source.test.js', 'moonglade.updater'),
    ('loom/test/phone-back-layers.test.js', 'moonglade.updater'),
    ('tests/test_app_paths.py', 'moonglade.updater'),
    ('tests/test_artworks_adhoc.py', 'moonglade.updater'),
    ('tests/test_bonjour.py', 'moonglade.updater'),
    ('tests/test_branding.py', 'moonglade.updater'),
    ('tests/test_catalog_verbs.py', 'moonglade.updater'),
    ('tests/test_catchup_query.py', 'moonglade.updater'),
    ('tests/test_csrf_coverage.py', 'moonglade.updater'),
    ('tests/test_design_kit_sync.py', 'moonglade.updater'),
    ('tests/test_doc_truth_residuals.py', 'moonglade.updater'),
    ('tests/test_evidence_counters.py', 'moonglade.updater'),
    ('tests/test_first_party_sources.py', 'moonglade.updater'),
    ('tests/test_gen_surface.py', 'moonglade.updater'),
    ('tests/test_history_feed_document.py', 'moonglade.updater'),
    ('tests/test_library_dir.py', 'moonglade.updater'),
    ('tests/test_living_library.py', 'moonglade.updater'),
    ('tests/test_logging.py', 'moonglade.updater'),
    ('tests/test_loom_generate_guard.py', 'moonglade.updater'),
    ('tests/test_loom_notify.py', 'moonglade.updater'),
    ('tests/test_loom_p_routes.py', 'moonglade.updater'),
    ('tests/test_network.py', 'moonglade.updater'),
    ('tests/test_server_stop_record.py', 'moonglade.updater'),
    ('tests/test_settings_store.py', 'moonglade.updater'),
    ('tests/test_setup_prepare.py', 'moonglade.updater'),
    ('tests/test_task_model_detail_document.py', 'moonglade.updater'),
    ('tests/test_telemetry.py', 'moonglade.updater'),
    ('tests/test_updater.py', 'moonglade.updater'),
    ('tests/test_watch.py', 'moonglade.updater'),
    ('tools/export_design_kit.py', 'moonglade.updater'),
    ('loom/test/med-loom-bundle-missing-report.test.js', 'moonglade.about'),
    ('loom/test/mg-art-filters.test.js', 'moonglade.about'),
    ('loom/test/mg-notify-queue-phase.test.js', 'moonglade.about'),
    ('loom/test/mg-notify-website-source.test.js', 'moonglade.about'),
    ('loom/test/phone-back-layers.test.js', 'moonglade.about'),
    ('tests/test_app_paths.py', 'moonglade.about'),
    ('tests/test_artworks_adhoc.py', 'moonglade.about'),
    ('tests/test_bonjour.py', 'moonglade.about'),
    ('tests/test_branding.py', 'moonglade.about'),
    ('tests/test_catalog_verbs.py', 'moonglade.about'),
    ('tests/test_catchup_query.py', 'moonglade.about'),
    ('tests/test_csrf_coverage.py', 'moonglade.about'),
    ('tests/test_design_kit_sync.py', 'moonglade.about'),
    ('tests/test_doc_truth_residuals.py', 'moonglade.about'),
    ('tests/test_evidence_counters.py', 'moonglade.about'),
    ('tests/test_first_party_sources.py', 'moonglade.about'),
    ('tests/test_gen_surface.py', 'moonglade.about'),
    ('tests/test_history_feed_document.py', 'moonglade.about'),
    ('tests/test_library_dir.py', 'moonglade.about'),
    ('tests/test_living_library.py', 'moonglade.about'),
    ('tests/test_logging.py', 'moonglade.about'),
    ('tests/test_loom_generate_guard.py', 'moonglade.about'),
    ('tests/test_loom_notify.py', 'moonglade.about'),
    ('tests/test_loom_p_routes.py', 'moonglade.about'),
    ('tests/test_network.py', 'moonglade.about'),
    ('tests/test_settings_store.py', 'moonglade.about'),
    ('tests/test_setup_prepare.py', 'moonglade.about'),
    ('tests/test_task_model_detail_document.py', 'moonglade.about'),
    ('tests/test_telemetry.py', 'moonglade.about'),
    ('tests/test_watch.py', 'moonglade.about'),
    ('tools/export_design_kit.py', 'moonglade.about'),
    ('loom/test/ledger-known-reasons.test.js', 'moonglade.media_tools'),
    ('loom/test/video-roster-parity.test.js', 'moonglade.media_tools'),
    ('tests/test_artworks_adhoc.py', 'moonglade.media_tools'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.media_tools'),
    ('tests/test_config_path_routing.py', 'moonglade.media_tools'),
    ('tests/test_csrf_coverage.py', 'moonglade.media_tools'),
    ('tests/test_enhance.py', 'moonglade.media_tools'),
    ('tests/test_evidence_counters.py', 'moonglade.media_tools'),
    ('tests/test_gen_surface.py', 'moonglade.media_tools'),
    ('tests/test_history_feed_document.py', 'moonglade.media_tools'),
    ('tests/test_jwt.py', 'moonglade.media_tools'),
    ('tests/test_living_library.py', 'moonglade.media_tools'),
    ('tests/test_loom_notify.py', 'moonglade.media_tools'),
    ('tests/test_network.py', 'moonglade.media_tools'),
    ('tests/test_settings_store.py', 'moonglade.media_tools'),
    ('tests/test_setup_prepare.py', 'moonglade.media_tools'),
    ('tests/test_spend_no_retry.py', 'moonglade.media_tools'),
    ('tests/test_task_model_detail_document.py', 'moonglade.media_tools'),
    ('tests/test_training_advanced.py', 'moonglade.media_tools'),
    ('tests/test_training_parity.py', 'moonglade.media_tools'),
    ('tests/test_video_tsubaki.py', 'moonglade.media_tools'),
    ('tests/test_web_auth.py', 'moonglade.media_tools'),
    ('loom/test/ledger-known-reasons.test.js', 'moonglade.mirror'),
    ('loom/test/video-roster-parity.test.js', 'moonglade.mirror'),
    ('tests/test_artworks_adhoc.py', 'moonglade.mirror'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.mirror'),
    ('tests/test_config_path_routing.py', 'moonglade.mirror'),
    ('tests/test_csrf_coverage.py', 'moonglade.mirror'),
    ('tests/test_enhance.py', 'moonglade.mirror'),
    ('tests/test_evidence_counters.py', 'moonglade.mirror'),
    ('tests/test_gen_surface.py', 'moonglade.mirror'),
    ('tests/test_history_feed_document.py', 'moonglade.mirror'),
    ('tests/test_jwt.py', 'moonglade.mirror'),
    ('tests/test_living_library.py', 'moonglade.mirror'),
    ('tests/test_loom_notify.py', 'moonglade.mirror'),
    ('tests/test_network.py', 'moonglade.mirror'),
    ('tests/test_pixai_client.py', 'moonglade.mirror'),
    ('tests/test_settings_store.py', 'moonglade.mirror'),
    ('tests/test_setup_prepare.py', 'moonglade.mirror'),
    ('tests/test_spend_no_retry.py', 'moonglade.mirror'),
    ('tests/test_task_model_detail_document.py', 'moonglade.mirror'),
    ('tests/test_training_advanced.py', 'moonglade.mirror'),
    ('tests/test_training_parity.py', 'moonglade.mirror'),
    ('tests/test_web_auth.py', 'moonglade.mirror'),
    ('loom/test/med-loom-bundle-missing-report.test.js', 'moonglade.living'),
    ('loom/test/mg-art-filters.test.js', 'moonglade.living'),
    ('loom/test/mg-notify-queue-phase.test.js', 'moonglade.living'),
    ('loom/test/mg-notify-website-source.test.js', 'moonglade.living'),
    ('loom/test/phone-back-layers.test.js', 'moonglade.living'),
    ('tests/test_app_paths.py', 'moonglade.living'),
    ('tests/test_artworks_adhoc.py', 'moonglade.living'),
    ('tests/test_bonjour.py', 'moonglade.living'),
    ('tests/test_branding.py', 'moonglade.living'),
    ('tests/test_catalog_verbs.py', 'moonglade.living'),
    ('tests/test_catchup_query.py', 'moonglade.living'),
    ('tests/test_community_surface.py', 'moonglade.living'),
    ('tests/test_csrf_coverage.py', 'moonglade.living'),
    ('tests/test_design_kit_sync.py', 'moonglade.living'),
    ('tests/test_doc_truth_residuals.py', 'moonglade.living'),
    ('tests/test_evidence_counters.py', 'moonglade.living'),
    ('tests/test_first_party_sources.py', 'moonglade.living'),
    ('tests/test_gen_surface.py', 'moonglade.living'),
    ('tests/test_history_feed_document.py', 'moonglade.living'),
    ('tests/test_library_dir.py', 'moonglade.living'),
    ('tests/test_living_library.py', 'moonglade.living'),
    ('tests/test_logging.py', 'moonglade.living'),
    ('tests/test_loom_generate_guard.py', 'moonglade.living'),
    ('tests/test_loom_notify.py', 'moonglade.living'),
    ('tests/test_loom_p_routes.py', 'moonglade.living'),
    ('tests/test_network.py', 'moonglade.living'),
    ('tests/test_settings_store.py', 'moonglade.living'),
    ('tests/test_setup_prepare.py', 'moonglade.living'),
    ('tests/test_task_model_detail_document.py', 'moonglade.living'),
    ('tests/test_telemetry.py', 'moonglade.living'),
    ('tests/test_watch.py', 'moonglade.living'),
    ('tools/export_design_kit.py', 'moonglade.living'),
    ('loom/test/med-loom-bundle-missing-report.test.js', 'moonglade.telemetry'),
    ('loom/test/mg-art-filters.test.js', 'moonglade.telemetry'),
    ('loom/test/mg-notify-queue-phase.test.js', 'moonglade.telemetry'),
    ('loom/test/mg-notify-website-source.test.js', 'moonglade.telemetry'),
    ('loom/test/phone-back-layers.test.js', 'moonglade.telemetry'),
    ('tests/test_app_paths.py', 'moonglade.telemetry'),
    ('tests/test_artworks_adhoc.py', 'moonglade.telemetry'),
    ('tests/test_bonjour.py', 'moonglade.telemetry'),
    ('tests/test_branding.py', 'moonglade.telemetry'),
    ('tests/test_branding_tree_rules.py', 'moonglade.telemetry'),
    ('tests/test_catalog_verbs.py', 'moonglade.telemetry'),
    ('tests/test_catchup_query.py', 'moonglade.telemetry'),
    ('tests/test_contest_wins.py', 'moonglade.telemetry'),
    ('tests/test_csrf_coverage.py', 'moonglade.telemetry'),
    ('tests/test_design_kit_sync.py', 'moonglade.telemetry'),
    ('tests/test_doc_truth_residuals.py', 'moonglade.telemetry'),
    ('tests/test_evidence_counters.py', 'moonglade.telemetry'),
    ('tests/test_first_party_sources.py', 'moonglade.telemetry'),
    ('tests/test_gen_surface.py', 'moonglade.telemetry'),
    ('tests/test_history_feed_document.py', 'moonglade.telemetry'),
    ('tests/test_library_dir.py', 'moonglade.telemetry'),
    ('tests/test_living_library.py', 'moonglade.telemetry'),
    ('tests/test_logging.py', 'moonglade.telemetry'),
    ('tests/test_loom_generate_guard.py', 'moonglade.telemetry'),
    ('tests/test_loom_notify.py', 'moonglade.telemetry'),
    ('tests/test_loom_p_routes.py', 'moonglade.telemetry'),
    ('tests/test_network.py', 'moonglade.telemetry'),
    ('tests/test_settings_store.py', 'moonglade.telemetry'),
    ('tests/test_setup_prepare.py', 'moonglade.telemetry'),
    ('tests/test_task_model_detail_document.py', 'moonglade.telemetry'),
    ('tests/test_telemetry.py', 'moonglade.telemetry'),
    ('tests/test_watch.py', 'moonglade.telemetry'),
    ('tools/export_design_kit.py', 'moonglade.telemetry'),
    ('loom/test/med-loom-bundle-missing-report.test.js', 'moonglade.contest_sync'),
    ('loom/test/mg-art-filters.test.js', 'moonglade.contest_sync'),
    ('loom/test/mg-notify-queue-phase.test.js', 'moonglade.contest_sync'),
    ('loom/test/mg-notify-website-source.test.js', 'moonglade.contest_sync'),
    ('loom/test/phone-back-layers.test.js', 'moonglade.contest_sync'),
    ('tests/test_app_paths.py', 'moonglade.contest_sync'),
    ('tests/test_artworks_adhoc.py', 'moonglade.contest_sync'),
    ('tests/test_bonjour.py', 'moonglade.contest_sync'),
    ('tests/test_branding.py', 'moonglade.contest_sync'),
    ('tests/test_catalog_verbs.py', 'moonglade.contest_sync'),
    ('tests/test_catchup_query.py', 'moonglade.contest_sync'),
    ('tests/test_contest_wins.py', 'moonglade.contest_sync'),
    ('tests/test_csrf_coverage.py', 'moonglade.contest_sync'),
    ('tests/test_design_kit_sync.py', 'moonglade.contest_sync'),
    ('tests/test_doc_truth_residuals.py', 'moonglade.contest_sync'),
    ('tests/test_evidence_counters.py', 'moonglade.contest_sync'),
    ('tests/test_first_party_sources.py', 'moonglade.contest_sync'),
    ('tests/test_gen_surface.py', 'moonglade.contest_sync'),
    ('tests/test_history_feed_document.py', 'moonglade.contest_sync'),
    ('tests/test_library_dir.py', 'moonglade.contest_sync'),
    ('tests/test_living_library.py', 'moonglade.contest_sync'),
    ('tests/test_logging.py', 'moonglade.contest_sync'),
    ('tests/test_loom_generate_guard.py', 'moonglade.contest_sync'),
    ('tests/test_loom_notify.py', 'moonglade.contest_sync'),
    ('tests/test_loom_p_routes.py', 'moonglade.contest_sync'),
    ('tests/test_network.py', 'moonglade.contest_sync'),
    ('tests/test_settings_store.py', 'moonglade.contest_sync'),
    ('tests/test_setup_prepare.py', 'moonglade.contest_sync'),
    ('tests/test_task_model_detail_document.py', 'moonglade.contest_sync'),
    ('tests/test_telemetry.py', 'moonglade.contest_sync'),
    ('tests/test_watch.py', 'moonglade.contest_sync'),
    ('tools/export_design_kit.py', 'moonglade.contest_sync'),
    ('loom/test/med-loom-bundle-missing-report.test.js', 'moonglade.achievements'),
    ('loom/test/mg-art-filters.test.js', 'moonglade.achievements'),
    ('loom/test/mg-notify-queue-phase.test.js', 'moonglade.achievements'),
    ('loom/test/mg-notify-website-source.test.js', 'moonglade.achievements'),
    ('loom/test/phone-back-layers.test.js', 'moonglade.achievements'),
    ('tests/test_app_paths.py', 'moonglade.achievements'),
    ('tests/test_artworks_adhoc.py', 'moonglade.achievements'),
    ('tests/test_bonjour.py', 'moonglade.achievements'),
    ('tests/test_branding.py', 'moonglade.achievements'),
    ('tests/test_branding_tree_rules.py', 'moonglade.achievements'),
    ('tests/test_catalog_verbs.py', 'moonglade.achievements'),
    ('tests/test_catchup_query.py', 'moonglade.achievements'),
    ('tests/test_csrf_coverage.py', 'moonglade.achievements'),
    ('tests/test_design_kit_sync.py', 'moonglade.achievements'),
    ('tests/test_doc_truth_residuals.py', 'moonglade.achievements'),
    ('tests/test_evidence_counters.py', 'moonglade.achievements'),
    ('tests/test_first_party_sources.py', 'moonglade.achievements'),
    ('tests/test_gen_surface.py', 'moonglade.achievements'),
    ('tests/test_history_feed_document.py', 'moonglade.achievements'),
    ('tests/test_library_dir.py', 'moonglade.achievements'),
    ('tests/test_living_library.py', 'moonglade.achievements'),
    ('tests/test_logging.py', 'moonglade.achievements'),
    ('tests/test_loom_generate_guard.py', 'moonglade.achievements'),
    ('tests/test_loom_notify.py', 'moonglade.achievements'),
    ('tests/test_loom_p_routes.py', 'moonglade.achievements'),
    ('tests/test_network.py', 'moonglade.achievements'),
    ('tests/test_settings_store.py', 'moonglade.achievements'),
    ('tests/test_setup_prepare.py', 'moonglade.achievements'),
    ('tests/test_task_model_detail_document.py', 'moonglade.achievements'),
    ('tests/test_telemetry.py', 'moonglade.achievements'),
    ('tests/test_watch.py', 'moonglade.achievements'),
    ('tools/export_design_kit.py', 'moonglade.achievements'),
    ('loom/test/med-loom-bundle-missing-report.test.js', 'moonglade.branding'),
    ('loom/test/mg-art-filters.test.js', 'moonglade.branding'),
    ('loom/test/mg-notify-queue-phase.test.js', 'moonglade.branding'),
    ('loom/test/mg-notify-website-source.test.js', 'moonglade.branding'),
    ('loom/test/phone-back-layers.test.js', 'moonglade.branding'),
    ('tests/test_app_paths.py', 'moonglade.branding'),
    ('tests/test_artworks_adhoc.py', 'moonglade.branding'),
    ('tests/test_bonjour.py', 'moonglade.branding'),
    ('tests/test_branding.py', 'moonglade.branding'),
    ('tests/test_branding_tree_rules.py', 'moonglade.branding'),
    ('tests/test_catalog_verbs.py', 'moonglade.branding'),
    ('tests/test_catchup_query.py', 'moonglade.branding'),
    ('tests/test_csrf_coverage.py', 'moonglade.branding'),
    ('tests/test_design_kit_sync.py', 'moonglade.branding'),
    ('tests/test_doc_truth_residuals.py', 'moonglade.branding'),
    ('tests/test_evidence_counters.py', 'moonglade.branding'),
    ('tests/test_first_party_sources.py', 'moonglade.branding'),
    ('tests/test_gen_surface.py', 'moonglade.branding'),
    ('tests/test_history_feed_document.py', 'moonglade.branding'),
    ('tests/test_library_dir.py', 'moonglade.branding'),
    ('tests/test_living_library.py', 'moonglade.branding'),
    ('tests/test_logging.py', 'moonglade.branding'),
    ('tests/test_loom_generate_guard.py', 'moonglade.branding'),
    ('tests/test_loom_notify.py', 'moonglade.branding'),
    ('tests/test_loom_p_routes.py', 'moonglade.branding'),
    ('tests/test_move_edges.py', 'moonglade.branding'),
    ('tests/test_network.py', 'moonglade.branding'),
    ('tests/test_outside_notice.py', 'moonglade.branding'),
    ('tests/test_pack_file_name.py', 'moonglade.branding'),
    ('tests/test_pack_file_type.py', 'moonglade.branding'),
    ('tests/test_panel.py', 'moonglade.branding'),
    ('tests/test_settings_store.py', 'moonglade.branding'),
    ('tests/test_setup_prepare.py', 'moonglade.branding'),
    ('tests/test_task_model_detail_document.py', 'moonglade.branding'),
    ('tests/test_telemetry.py', 'moonglade.branding'),
    ('tests/test_watch.py', 'moonglade.branding'),
    ('tools/export_design_kit.py', 'moonglade.branding'),
    # After the review: test_telemetry's bridge-set guard reads a tuple of modules, which the
    # scanner cannot trace. They are the gallery and its split-out modules; nothing moved out
    # of backup is in it, and no backup-origin module writes the bridge set.
    ('tests/test_telemetry.py', 'moonglade.organize'),
    ('tests/test_telemetry.py', 'moonglade.jobs'),
    ('tests/test_telemetry.py', 'moonglade.pixai_client'),
    ('tests/test_telemetry.py', 'moonglade.media_tools'),
    ('tests/test_telemetry.py', 'moonglade.mirror'),
    # 2026-11-19 security review: it reads gallery.py for main()'s startup secrets sweep and
    # three upload routes' named caps -- names that live in gallery.py itself, none moved.
    ('tests/test_security_review_fixes.py', 'moonglade.about'),
    ('tests/test_security_review_fixes.py', 'moonglade.account_prefs'),
    ('tests/test_security_review_fixes.py', 'moonglade.achievements'),
    ('tests/test_security_review_fixes.py', 'moonglade.branding'),
    ('tests/test_security_review_fixes.py', 'moonglade.contest_sync'),
    ('tests/test_security_review_fixes.py', 'moonglade.dupes'),
    ('tests/test_security_review_fixes.py', 'moonglade.health'),
    ('tests/test_security_review_fixes.py', 'moonglade.living'),
    ('tests/test_security_review_fixes.py', 'moonglade.scan'),
    ('tests/test_security_review_fixes.py', 'moonglade.series'),
    ('tests/test_security_review_fixes.py', 'moonglade.telemetry'),
    ('tests/test_security_review_fixes.py', 'moonglade.updater'),
}


def production_files():
    """The modules whose imports from an old module justify a re-export."""
    files = sorted((REPO / "moonglade").glob("*.py"))
    return files + [REPO / "Moonglade Launcher.pyw"]


def module_file(modname):
    return REPO / Path(*modname.split(".")).with_suffix(".py")


# ---------------------------------------------------------------------------------------------
# The checks. Each returns a list of problems (empty = fine) and takes its world as arguments,
# so the synthetic cases below can prove it fires.
# ---------------------------------------------------------------------------------------------

def _top_level_defines(source):
    """Names a module's source DEFINES at the top level (def, class, assignment), not imports."""
    names = set()
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                for sub in ast.walk(t):
                    if isinstance(sub, ast.Name):
                        names.add(sub.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def check_defined_in(seams, load, source_of):
    problems = []
    for new_mod, entry in seams.items():
        try:
            mod = load(new_mod)
        except ImportError as exc:
            problems.append("%s does not import: %s" % (new_mod, exc))
            continue
        defined = _top_level_defines(source_of(new_mod))
        for name in entry["names"]:
            if not hasattr(mod, name):
                problems.append("%s.%s does not exist" % (new_mod, name))
                continue
            obj = getattr(mod, name)
            # A stand-in the suite itself installs for the whole session (conftest pins
            # branding_root() before any test runs) is not an import; the source check below
            # still has to find the real definition.
            stand_in = (getattr(obj, "__module__", None) or "").startswith("tests.")
            if ((inspect.isfunction(obj) or inspect.isclass(obj)) and obj.__module__ != new_mod
                    and not stand_in):
                problems.append("%s.%s is defined in %s" % (new_mod, name, obj.__module__))
            elif name not in defined:
                problems.append("%s.%s is imported there, not defined" % (new_mod, name))
    return problems


def check_reexports(seams, load, production_refs):
    """production_refs: {(old_module, name)} that production code reaches through old_module."""
    problems = []
    for new_mod, entry in seams.items():
        old_name = entry["from"]
        old, new = load(old_name), load(new_mod)
        for name in entry["names"]:
            wanted = (old_name, name) in production_refs
            if hasattr(old, name):
                if not wanted:
                    problems.append("%s re-exports %s, which moved to %s and no production "
                                    "module imports from %s" % (old_name, name, new_mod, old_name))
                elif hasattr(new, name) and getattr(old, name) is not getattr(new, name):
                    problems.append("%s.%s is not the identical object as %s.%s"
                                    % (old_name, name, new_mod, name))
            elif wanted:
                problems.append("production code reaches %s.%s, which moved to %s: re-export it "
                                "or retarget the importer" % (old_name, name, new_mod))
    return problems


def _import_time_imports(tree):
    """Import nodes (and import_module calls) that run when the module is imported: everything
    outside a def/lambda body (class bodies, if/try blocks at top level DO run)."""
    stack = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            stack.extend(node.decorator_list)
            stack.extend(node.args.defaults)
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        elif isinstance(node, ast.Call) and rp._import_module_target(node):
            yield node
        stack.extend(ast.iter_child_nodes(node))


def _imported_modules(node, package="moonglade"):
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if isinstance(node, ast.ImportFrom):
        base = node.module or ""
        if node.level:
            base = package + ("." + base if base else "")
        return [base] + [base + "." + a.name for a in node.names]
    return [rp._import_module_target(node)]


def check_lazy_imports(seams, source_of):
    problems = []
    old_set = set(OLD_MODULES) | {e["from"] for e in seams.values()}
    for new_mod in seams:
        tree = ast.parse(source_of(new_mod))
        for node in _import_time_imports(tree):
            hit = sorted(set(_imported_modules(node)) & old_set)
            if hit:
                problems.append("%s line %d imports %s at import time; import it inside the "
                                "function that needs it" % (new_mod, node.lineno, hit[0]))
    return problems


def lint_patches(seams, files, module_binding=rp.repo_module_binding):
    """files: {path: text}. -> (stale, unresolved) as 'path:line ...' strings."""
    stale, unresolved = [], []
    for path, text in sorted(files.items()):
        edits, unres, _ = rp.plan_file(path, text, seams, module_binding=module_binding)
        stale += ["%s:%d %s (moved to %s)" % (path, e.site.line, e.old_target, e.new_module)
                  for e in edits]
        unresolved += ["%s:%d %s" % (path, line, msg) for line, msg in unres]
    return stale, unresolved


def check_production_gaps(seams, files, module_binding=rp.repo_module_binding):
    """files: {path: production source}. A production reach the scanner cannot pin (see
    rp.scan_reference_gaps) that may name a moved name through its old module, or a computed
    getattr on an old module something moved out of. Point it at the new module."""
    moved = rp.moved_index(seams)
    moved_from = {old for old, _ in moved}
    problems = []
    for path, text in sorted(files.items()):
        for line, recv, name, mods in rp.scan_reference_gaps(text, module_binding=module_binding):
            if name:
                hit = [(m, moved[(m, name)]) for m in mods if (m, name) in moved]
                if hit:
                    problems.append("%s:%d %s.%s may be %s.%s, which moved to %s: reach it "
                                    "through the new module" % (path, line, recv, name,
                                                                hit[0][0], name, hit[0][1]))
            elif set(mods) & moved_from:
                problems.append("%s:%d getattr(%s, <computed>) on %s, which names have moved "
                                "out of: check by hand" % (path, line, recv, mods[0]))
    return problems


def detect_source_readers(files):
    """{path: text} -> {path: (old modules whose source it reads)}."""
    out = {}
    for path, text in files.items():
        scan = rp.scan_any(path, text)
        if scan.reads_source:
            out[path] = tuple(sorted(scan.reads_source))
    return out


def check_source_readers_reviewed(seams, files, readers, reviewed):
    """A reader of a seam's old module is TOUCHED by the move if it reads the old module whole
    (its text, getsource(module), something untraceable) or names one of the moved symbols. One
    that reads every module of the package (a glob, kind "all") never is: the moved code is
    still in what it reads."""
    problems = []
    for new_mod, entry in seams.items():
        words = re.compile(r"\b(%s)\b" % "|".join(map(re.escape, entry["names"])))
        for path, mods in sorted(readers.items()):
            if entry["from"] not in mods or (path, new_mod) in reviewed:
                continue
            kind = rp.scan_any(path, files[path]).reads_source.get(entry["from"])
            if kind == "all":
                continue
            if kind in ("whole", "indirect") or words.search(files[path]):
                problems.append("%s reads %s's source and the move to %s touches it: check what "
                                "it reads, then add (%r, %r) to SOURCE_READERS_REVIEWED"
                                % (path, entry["from"], new_mod, path, new_mod))
    return problems


# ---------------------------------------------------------------------------------------------
# The real tree
# ---------------------------------------------------------------------------------------------

def _source_of(modname):
    return module_file(modname).read_text(encoding="utf-8")


def _test_files(folder="tests"):
    root = DEV / folder if folder else DEV
    return {p.relative_to(DEV).as_posix(): p.read_text(encoding="utf-8")
            for p in rp.iter_test_files(root)}


def _reader_files():
    """Every file that may read the Python source: dev/ (keyed from dev/) and the node tests
    (keyed from the repo root)."""
    files = _test_files(folder=None)
    files.update({p.relative_to(REPO).as_posix(): p.read_text(encoding="utf-8")
                  for p in rp.iter_js_test_files(REPO)})
    return files


def _production_refs():
    refs = set()
    for p in production_files():
        own = "moonglade." + p.stem
        refs |= {r for r in rp.scan_references(p.read_text(encoding="utf-8")) if r[0] != own}
    return refs


def test_seams_map_is_one_readable_literal():
    assert rp.load_seams(Path(__file__)) == SEAMS
    owners = {}
    for new_mod, entry in SEAMS.items():
        assert set(entry) == {"from", "names"}, new_mod
        assert entry["from"] in OLD_MODULES, new_mod
        assert new_mod.startswith("moonglade.") and new_mod not in OLD_MODULES, new_mod
        for name in entry["names"]:
            assert (entry["from"], name) not in owners, (name, owners.get((entry["from"], name)))
            owners[(entry["from"], name)] = new_mod


def test_every_mapped_symbol_is_defined_in_its_new_module():
    assert check_defined_in(SEAMS, importlib.import_module, _source_of) == []


def test_old_modules_reexport_only_what_production_imports():
    assert check_reexports(SEAMS, importlib.import_module, _production_refs()) == []


def test_new_modules_import_the_old_ones_lazily():
    assert check_lazy_imports(SEAMS, _source_of) == []


def test_no_test_patches_a_moved_name_through_its_old_module():
    stale, unresolved = lint_patches(SEAMS, _test_files())
    assert stale == [], ("patches still aimed at the old module -- run "
                         "`py dev/tools/retarget_patches.py`:\n" + "\n".join(stale))
    assert unresolved == [], "patches of moved names to check by hand:\n" + "\n".join(unresolved)


def test_production_reaches_no_moved_name_through_an_unpinned_receiver():
    files = {p.relative_to(REPO).as_posix(): p.read_text(encoding="utf-8")
             for p in production_files()}
    assert check_production_gaps(SEAMS, files) == []


def test_the_scanner_sees_the_suites_patches():
    """The lint is only as good as its scanner: it must keep finding the suite's patches through
    its usual aliases (a scanner that silently finds nothing passes every move)."""
    scans = rp.scan_tree(DEV / "tests")
    assert not [s.path for s in scans if s.error]
    aliases = {(name, mod) for s in scans for name, mod in s.aliases}
    for pair in [("core", "moonglade.backup"), ("g", "moonglade.gallery")]:
        assert pair in aliases
    by_mod = {m: sum(1 for s in scans for x in s.sites if x.module == m) for m in OLD_MODULES}
    assert all(by_mod.values()), by_mod


def test_source_readers_are_the_known_set():
    assert detect_source_readers(_reader_files()) == SOURCE_READERS


def test_the_js_reader_scan_sees_the_node_tests():
    """A JS scan that silently finds nothing would pass every move: it must keep seeing the
    node tests' reads (the one that broke in phase 1 among them)."""
    readers = detect_source_readers(_reader_files())
    js = {p for p in readers if p.endswith(rp.JS_SUFFIXES)}
    assert "loom/test/import-batches.test.js" in js
    assert any("moonglade.gallery" in readers[p] for p in js)
    assert any("moonglade.backup" in readers[p] for p in js)


def test_source_readers_touched_by_a_move_were_reviewed():
    files = _reader_files()
    assert check_source_readers_reviewed(SEAMS, files, SOURCE_READERS,
                                         SOURCE_READERS_REVIEWED) == []


# ---------------------------------------------------------------------------------------------
# Each check fires: synthetic worlds
# ---------------------------------------------------------------------------------------------

def _module(name, source):
    mod = types.ModuleType(name)
    exec(compile(source, name, "exec"), mod.__dict__)
    return mod


@pytest.fixture
def world():
    """A fake old module and a fake new one: `moved` lives in new; `copied` was copied, not
    moved; `imported` is only imported into new; `kept` stayed home."""
    old_src = "def kept():\n    pass\n\ndef copied():\n    pass\n"
    new_src = ("def moved():\n    pass\n\ndef copied():\n    pass\n\n"
               "LIMIT = 3\n")
    old = _module("fake.old", old_src)
    new = _module("fake.new", new_src)
    new.imported = old.kept                    # `from fake.old import kept as imported`
    new_src += "from fake.old import kept as imported\n"
    mods = {"fake.old": old, "fake.new": new}
    sources = {"fake.old": old_src, "fake.new": new_src}
    return mods, sources


def test_defined_in_check_fires(world):
    mods, sources = world
    ok = {"fake.new": {"from": "fake.old", "names": ["moved", "LIMIT"]}}
    assert check_defined_in(ok, mods.__getitem__, sources.__getitem__) == []
    bad = {"fake.new": {"from": "fake.old", "names": ["imported", "missing"]}}
    problems = check_defined_in(bad, mods.__getitem__, sources.__getitem__)
    assert any("fake.new.imported is defined in fake.old" in p for p in problems), problems
    assert any("fake.new.missing does not exist" in p for p in problems), problems
    # a constant can only be checked by source: imported there, not defined
    mods["fake.new"].ALIAS_CONST = 5
    bad = {"fake.new": {"from": "fake.old", "names": ["ALIAS_CONST"]}}
    assert check_defined_in(bad, mods.__getitem__, sources.__getitem__) == [
        "fake.new.ALIAS_CONST is imported there, not defined"]
    gone = {"fake.nowhere": {"from": "fake.old", "names": ["x"]}}

    def load(name):
        raise ImportError(name)
    assert "does not import" in check_defined_in(gone, load, sources.__getitem__)[0]


def test_reexport_check_fires(world):
    mods, _ = world
    load = mods.__getitem__
    seams = {"fake.new": {"from": "fake.old", "names": ["moved"]}}
    assert check_reexports(seams, load, set()) == []                       # moved cleanly
    # an internal re-export: the old module still answers to the moved name
    mods["fake.old"].moved = mods["fake.new"].moved
    assert "re-exports moved" in check_reexports(seams, load, set())[0]
    # ... allowed when production imports it from there, and it is the same object
    assert check_reexports(seams, load, {("fake.old", "moved")}) == []
    # ... but not when it is a different object (a copy left behind)
    seams = {"fake.new": {"from": "fake.old", "names": ["copied"]}}
    assert "not the identical object" in check_reexports(seams, load, {("fake.old", "copied")})[0]
    # production still reaches the old home of a name nobody re-exported
    seams = {"fake.new": {"from": "fake.old", "names": ["LIMIT"]}}
    assert "retarget the importer" in check_reexports(seams, load, {("fake.old", "LIMIT")})[0]


def test_lazy_import_check_fires():
    seams = {"moonglade.fake_seam": {"from": "moonglade.gallery", "names": ["x"]}}
    lazy = ("import os\n\ndef x():\n    from moonglade import gallery as g\n"
            "    import moonglade.backup\n    return g\n")
    assert check_lazy_imports(seams, lambda _: lazy) == []
    for eager in ("from moonglade import gallery as g\n",
                  "import moonglade.backup as core\n",
                  "from moonglade.gallery import scan_library\n",
                  "from . import backup\n",
                  "try:\n    from moonglade import backup\nexcept ImportError:\n    pass\n",
                  "class C:\n    from moonglade import gallery\n",
                  "import importlib\ncore = importlib.import_module('moonglade.backup')\n"):
        problems = check_lazy_imports(seams, lambda _, s=eager: s)
        assert problems and "at import time" in problems[0], eager


SYNTH_SEAMS = {"moonglade.fake_seam": {"from": "moonglade.gallery",
                                       "names": ["scan_library", "Walker"]}}

SYNTH_TEST = '''\
import importlib
from unittest import mock
from unittest.mock import patch

import moonglade.gallery
from moonglade import gallery as gg
from moonglade import backup as core

g2 = gg
mg = importlib.import_module("moonglade.gallery")


def test_a(monkeypatch):
    monkeypatch.setattr(gg, "scan_library", lambda *a: [])            # line 14: stale
    monkeypatch.setattr(gg, "load_catalog", lambda *a: [])            # not moved
    monkeypatch.setattr(core, "scan_library", lambda *a: [])          # other module: not moved
    monkeypatch.setattr("moonglade.gallery.scan_library", None)       # line 17: stale string
    gg.scan_library = None                                            # line 18: stale assign
    monkeypatch.setattr(gg.Walker, "walk", None)                      # line 19: stale receiver


@mock.patch("moonglade.gallery.scan_library")                         # line 22: stale decorator
def test_b(m):
    with patch.object(g2, "scan_library"):                            # line 24: stale via copy
        pass
    moonglade.gallery.scan_library = None                             # line 26: dotted import
    mg.Walker.depth = 3                                               # line 27: import_module


def test_c(monkeypatch):
    from moonglade import gallery as local_g
    monkeypatch.setattr(local_g, "scan_library", None)                # line 32: local alias


def test_d(monkeypatch, gg):
    monkeypatch.setattr(gg, "scan_library", None)                     # line 36: shadowed, unresolved
    setattr(core, name_of(), None)                                    # computed name, other module
    setattr(mg, name_of(), None)                                      # line 38: computed, unresolved
'''


def test_patch_lint_passes_an_empty_map_and_flags_a_synthetic_move():
    files = {"tests/test_synth.py": SYNTH_TEST}
    assert lint_patches({}, files) == ([], [])
    stale, unresolved = lint_patches(SYNTH_SEAMS, files)
    lines = sorted(int(s.split(":")[1].split()[0]) for s in stale)
    assert lines == [14, 17, 18, 19, 22, 24, 26, 27, 32], stale
    assert sorted(int(u.split(":")[1].split()[0]) for u in unresolved) == [36, 38], unresolved
    assert any("gg.scan_library (moved to moonglade.fake_seam)" in s for s in stale)
    assert any('"moonglade.gallery.scan_library"' in s for s in stale)


def test_patch_lint_on_the_real_suite_flags_a_synthetic_move():
    """Against today's suite: a pretend move of a heavily patched name lights the lint up."""
    files = _test_files()
    stale, _ = lint_patches({"moonglade.fake_seam": {"from": "moonglade.backup",
                                                     "names": ["_make_session"]}}, files)
    assert len(stale) > 10


GAP_SRC = """\
from moonglade import backup as core


def _session():
    from moonglade import backup as core
    return core, object()


def _uses(g, row):
    return g.get_row(row)


def caller():
    from moonglade import gallery as g
    return _uses(g, 1)


def route():
    core, session = _session()
    core.scan_library(session)                    # line 20: tuple-bound, unpinned
    getattr(core, "scan_library")                 # line 21: the same, by name


def mixed(mod):
    return mod.scan_library()                     # line 25: sometimes the gallery


def calls_mixed():
    from moonglade import gallery as mod
    mixed(mod)
    mixed(None)


def computed(name):
    from moonglade import gallery as g
    return getattr(g, name)                       # line 36: computed name
"""


def test_reference_gaps_resolve_parameters_and_list_what_they_cannot():
    """integrity.py hands the gallery to its helpers as a parameter: a call pinning it makes it
    a reference (g.get_row); a tuple-bound `core`, a parameter its calls disagree about, and a
    computed getattr are listed, never dropped."""
    refs = rp.scan_references(GAP_SRC)
    assert ("moonglade.gallery", "get_row") in refs
    gaps = rp.scan_reference_gaps(GAP_SRC)
    assert [(line, name) for line, _, name, _ in gaps] == [
        (20, "scan_library"), (21, "scan_library"), (25, "scan_library"), (36, "")], gaps
    seams = {"moonglade.fake_seam": {"from": "moonglade.backup", "names": ["scan_library"]}}
    problems = check_production_gaps(seams, {"moonglade/fake.py": GAP_SRC})
    assert [p.split()[0] for p in problems] == ["moonglade/fake.py:20", "moonglade/fake.py:21"]
    problems = check_production_gaps(SYNTH_SEAMS, {"moonglade/fake.py": GAP_SRC})
    assert [p.split()[0] for p in problems] == ["moonglade/fake.py:25", "moonglade/fake.py:36"]
    assert check_production_gaps({}, {"moonglade/fake.py": GAP_SRC}) == []


PARAM_TEST = """\
import inspect
import pytest
from moonglade import gallery as gg
from moonglade import mcp_server as m
NAMES = ("load_catalog", "scan_library")


def _helper(monkeypatch, mod):
    monkeypatch.setattr(mod, "scan_library", None)              # line 9: stale, via the call


def test_a(monkeypatch):
    monkeypatch.setattr(m.g, "scan_library", None)              # line 13: stale, m.g
    _helper(monkeypatch, gg)
    for name in NAMES:
        inspect.getsource(getattr(gg, name))                    # line 16: loop name
    for name in ("load_catalog",):
        hasattr(gg, name)                                       # not moved


@pytest.mark.parametrize("name", NAMES)
def test_b(name):
    getattr(gg, name)                                           # line 23: parametrized


def test_c(gg):
    gg.scan_library = None                                      # line 27: fixture parameter
"""


def test_patch_lint_resolves_another_modules_attribute_and_parameters():
    """`monkeypatch.setattr(m.g, ...)` with m the MCP server patches the gallery (read off the
    server's own top level); a helper handed a module patches that module; getattr loops,
    parametrized names and an assignment through a fixture parameter are checked too."""
    binding = rp.source_module_binding({"moonglade.mcp_server":
                                        "from moonglade import gallery as g\n"})
    files = {"tests/test_x.py": PARAM_TEST}
    stale, unresolved = lint_patches(SYNTH_SEAMS, files, module_binding=binding)
    assert sorted(int(s.split(":")[1].split()[0]) for s in stale) == [9, 13], stale
    assert sorted(int(u.split(":")[1].split()[0]) for u in unresolved) == [16, 23, 27], unresolved
    assert lint_patches({}, files, module_binding=binding) == ([], [])


def test_scan_references_sees_production_reach():
    src = ("from moonglade.gallery import (a, b)\n"
           "from moonglade import backup as core\n"
           "def f():\n    from moonglade import gallery as _mg\n"
           "    return core.c() + _mg.d + getattr(core, 'e')\n")
    assert rp.scan_references(src) == {("moonglade.gallery", "a"), ("moonglade.gallery", "b"),
                                       ("moonglade.backup", "c"), ("moonglade.gallery", "d"),
                                       ("moonglade.backup", "e")}


def test_source_reader_detection_and_review_fire():
    files = {
        "tests/test_getsource.py": ("import inspect\nfrom moonglade import gallery as g\n"
                                    "def test():\n    inspect.getsource(g.scan_library)\n"),
        "tests/test_whole.py": ("import inspect\nfrom moonglade import backup as core\n"
                                "def test():\n    inspect.getsource(core)\n"),
        "tests/test_by_path.py": ("from pathlib import Path\nROOT = Path('.')\n"
                                  "def test():\n    (ROOT / 'moonglade' / 'gallery.py').read_text()\n"),
        "tests/test_create_app.py": ("import ast, inspect, textwrap\n"
                                     "from moonglade import gallery as G\n"
                                     "def test():\n    ast.parse(textwrap.dedent("
                                     "inspect.getsource(G.create_app)))\n"),
        "tests/test_argv_only.py": ("import sys\ndef test(monkeypatch):\n"
                                    "    monkeypatch.setattr(sys, 'argv', ['moonglade/backup.py'])\n"),
        "tests/test_plain.py": "from moonglade import gallery as g\ndef test():\n    g.x()\n",
        "loom/test/reads.test.js": ("// moonglade/backup.py is only named in this comment\n"
                                    "const re = /[\"'`]/g;\n"
                                    "const py = src(`${ROOT}/moonglade/gallery.py`);\n"),
        "loom/test/comment.test.js": "/* moonglade/gallery.py */ const s = 'gallery.py\\'s';\n",
        "tests/test_glob.py": ("from pathlib import Path\nROOT = Path('.')\ndef test():\n"
                               "    for p in (ROOT / 'moonglade').glob('*.py'):\n"
                               "        assert 'scan_library' not in p.read_text()\n"),
    }
    readers = detect_source_readers(files)
    assert readers == {"tests/test_getsource.py": ("moonglade.gallery",),
                       "tests/test_whole.py": ("moonglade.backup",),
                       "tests/test_by_path.py": ("moonglade.gallery",),
                       "tests/test_create_app.py": ("moonglade.gallery",),
                       "loom/test/reads.test.js": ("moonglade.gallery",),
                       "tests/test_glob.py": ("moonglade.backup", "moonglade.gallery")}
    problems = check_source_readers_reviewed(SYNTH_SEAMS, files, readers, set())
    touched = sorted(p.split()[0] for p in problems)
    # names scan_library / whole file by path; the create_app reader names neither; a node
    # test reads the file whole; the glob reads every module, so a move cannot hide code from it
    # even though it names scan_library
    assert touched == ["loom/test/reads.test.js", "tests/test_by_path.py",
                       "tests/test_getsource.py"], problems
    reviewed = {("tests/test_by_path.py", "moonglade.fake_seam"),
                ("tests/test_getsource.py", "moonglade.fake_seam"),
                ("loom/test/reads.test.js", "moonglade.fake_seam")}
    assert check_source_readers_reviewed(SYNTH_SEAMS, files, readers, reviewed) == []
