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
        "LOCALSTORAGE_JWT_KEY", "MIRROR_WEB_USER_AGENT", "MIRROR_WEB_ORIGIN", "_b64url_decode",
        "jwt_claims", "jwt_expiry", "jwt_days_left", "mirror_needs_refresh", "_read_file_shared",
        "_lvarint", "_snappy_decompress", "_lvldb_decompress_block", "_lvldb_block_pairs",
        "_LVLDB_SSTABLE_MAGIC", "_lvldb_sstable_entries", "_lvldb_log_entries",
        "_lvldb_value_to_jwt", "_pick_pixai_token", "read_browser_jwt", "_is_api_key",
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
    "moonglade.task_reads": {"from": "moonglade.backup", "names": [
        "_TASK_DETAIL_DOC", "task_detail_gql", "_GEN_STATUS", "_poll_task_status",
        "_task_failure_reason", "describe_failure", "_pixai_reason_suffix", "_never_dispatched",
        "_GEN_DONE", "_GEN_FAIL", "generation_status"]},
    "moonglade.cloud_delete": {"from": "moonglade.backup", "names": [
        "_TASK_ID_RE", "TASK_DELETE_PATH", "ImageDeleteRoute", "batch_entry", "live_batch_media",
        "deleted_batch_media", "route_image_delete", "_DELETE_BATCH_MEDIA_MUT",
        "delete_batch_media_gql", "delete_task", "ImageDeletePlan", "task_artwork_ids",
        "_image_delete_plan", "plan_image_delete", "NO_CONFIRMED_PLAN", "delete_image_routed"]},
    "moonglade.models": {"from": "moonglade.backup", "names": [
        "model_search_gql", "_model_preview_url", "_row_should_blur", "model_search_rest",
        "rest_model_row", "MARKET_CATEGORIES", "LORA_BASE_MODEL_TYPES", "MARKET_SORTS",
        "MARKET_SORT_ALIASES", "market_sort", "MODEL_TYPE_FILTERS", "LORA_SOURCE_TYPES",
        "PERMITTED_USES", "POSTED_AT_DAYS", "posted_at_range", "_market_row", "_MODEL_BLUR_FIELD",
        "_model_blur_supported", "_model_blur_refusals", "_MODEL_BLUR_REFUSALS_BEFORE_GIVING_UP",
        "_model_conn_query", "model_search_market_gql", "_bookmark_node_fields",
        "model_bookmarks_gql", "workflow_catalog", "_empty_version_meta", "_version_quality_tag",
        "_routed_default_negative", "_version_row_to_meta", "_attach_profiles", "_profile_row",
        "_attach_features", "_attach_unlimited", "resolve_version_meta", "list_model_versions",
        "resolve_latest_version", "is_lora_compatible", "annotate_lora_compat",
        "_MODEL_LOOKUP_FAILED", "_MODEL_VERSION_DOC", "_model_version_gql", "model_name_gql",
        "resolve_model_base_id", "_PROFILE_CACHE_TTL", "_PROFILE_FAIL_TTL", "_profile_cache",
        "_model_profiles", "DIT_SIZE_STEP_TYPES", "NO_HIRES_FACEFIX_TYPES", "_HIRES_FIELDS",
        "_FEATURE_STRIP_FIELDS", "_GATE_READ_TIMEOUT", "_SIZE_FALLBACK_RANGE", "_features_cache",
        "_size_config_cache", "_CONTEXT_REF_LORA_REFUSAL", "_CONTEXT_LORA_REFUSAL",
        "_cached_version_read", "_parse_features", "_SizeRanges", "_parse_size_config",
        "_size_tier_row", "_model_features", "_model_size_config", "_model_config_cache",
        "_parse_model_config_context_max", "_model_context_max", "features_resolver",
        "_context_images_on", "_size_rule", "_snap_size", "_lora_out_of_range",
        "_CREATIVITY_LEVELS", "CONTEXT_IMAGES_FALLBACK_MAX", "_CONTEXT_UNREAD",
        "_CONTEXT_NOT_TAKEN", "_check_context_images", "_gate_image_params",
        "_gate_params_for_model", "_LOST_UPSCALE_REFUSAL", "_refuse_lost_upscale",
        "_profile_listing", "generation_model_brief"]},
    "moonglade.pricing": {"from": "moonglade.backup", "names": [
        "_FIXER_PRICE_PATH", "price_fixer", "_PRICE_SCALARS", "_PRICE_NESTED", "_task_price_query",
        "price_task", "queue_wait_estimate"]},
    "moonglade.cards": {"from": "moonglade.backup", "names": [
        "_bump_card_use", "_normalize_kaisuuken", "_expiry_counts", "list_kaisuukens",
        "list_kaisuuken_logs", "kaisuuken_type_catalog", "COUPON_STATUSES_ON_HAND",
        "COUPON_STATUSES_HISTORY", "list_extra_package_boosts", "_QUOTA_LOG_QUERY",
        "CREDIT_LOG_REASONS", "list_credit_log", "_target_model_id", "_KAISUUKEN_CHECK_VERSION",
        "match_kaisuuken", "card_covers", "_card_uses_note", "card_short_note",
        "_SIGNIN_REFUSED_MIRROR", "_SIGNIN_REFUSED_API_KEY", "_is_signin_refusal",
        "_apply_kaisuuken", "_preview_card_note"]},
    "moonglade.gen_params": {"from": "moonglade.backup", "names": [
        "DEFAULT_GEN_MODEL", "LORA_WEIGHT_STEP", "LORA_WEIGHT_RANGES", "LORA_WEIGHT_MIN",
        "LORA_WEIGHT_MAX", "lora_weight_range", "_lora_params", "ENLARGE_MODELS",
        "DEFAULT_ENLARGE_MODEL", "DEFAULT_QUALITY_TAG", "UPSCALE_FALLBACK_VERSION_ID",
        "DEFAULT_UPSCALE_DENOISING_STRENGTH", "DEFAULT_UPSCALE_DENOISING_STEPS",
        "UPSCALE_RATIO_STEP", "UPSCALE_PIXEL_CEILING", "UPSCALE_RATIO_HARD_MAX",
        "upscale_output_dims", "max_upscale_ratio", "_upscale_ratio", "PRIORITY_LOW",
        "PRIORITY_TURBO", "PRIORITY_HIGH", "PRIORITY_XHIGH", "PRIORITY_CHOICES",
        "_coerce_priority", "PALETTE_GROUPS", "PALETTE_MAX_COLORS", "PALETTE_NAME_MAX",
        "PALETTE_NAME_DEFAULT", "_PALETTE_HEX_RE", "_palette_ratio", "_palette_group_colors",
        "clean_color_palette", "color_palette_presets", "_gen_parameters", "DEFAULT_VIDEO_MODEL",
        "VIDEO_CAMERA_MOVES", "VIDEO_AUDIO_LANGS", "VIDEO_DURATIONS", "VIDEO_MODELS",
        "VIDEO_MODEL_RETIRED", "_video_clock", "video_model_retired", "check_video_model_retired",
        "_params_video_models", "check_params_retired", "video_model_id", "_video_model_id_fits",
        "VIDEO_CHANNELS", "TSUBAKI_VIDEO_MODELS", "VIDEO_MODEL_DURATIONS",
        "VIDEO_NO_NEGATIVE_MODELS", "VIDEO_NO_CAMERA_MODELS", "VIDEO_REF_CAPS",
        "VIDEO_RATIO_MODELS", "VIDEO_RATIOS", "VIDEO_I2V_NO_MODELID_MODELS",
        "video_model_durations", "_check_video_ref_caps", "build_video_parameters",
        "REFVIDEO_MODEL_ID", "build_reference_video_parameters", "input_video_durations",
        "INPUT_VIDEO_UNKNOWN_WHY", "make_video_duration_lookup", "VIDEO_15S_MODELS",
        "VIDEO_PROMPT_MAXLEN", "VIDEO_AUDIO_MODELS", "_snap_video_duration",
        "build_shot_video_params", "build_panelplugin_parameters", "BRIDGE_ENHANCE_PRESETS",
        "ENHANCE_EMOTION_WORKFLOW", "ENHANCE_EMOTION_ARG", "ENHANCE_EMOTION_PROMPTS",
        "ENHANCE_EMOTION_MEMBERSHIP", "_gen_video_parameters", "EDIT_PRO_MODEL_ID",
        "EDIT_ASPECT_AUTO", "EDIT_MODELS", "DEFAULT_EDIT_MODEL", "_EDIT_ASPECT_UNKNOWN_MODEL",
        "FIXER_MODEL_ID", "edit_model_id", "edit_model_by_id", "edit_default_aspect",
        "clamp_edit_config", "_is_local_source", "build_chat_edit_parameters",
        "_edit_config_from_args", "clean_fix_boxes", "FIX_ONE_KIND", "build_fixer_body"]},
    "moonglade.gen_road": {"from": "moonglade.backup", "names": [
        "_GEN_MUTATION", "priority_for_submit", "_is_turbo_refusal", "_SCENE_LIST_Q",
        "_SCENE_SUBMIT_M", "chat_editing_scenes", "submit_scene", "UNLIMITED_LANE",
        "UNLIMITED_VERSIONS", "TSUBAKI3_MODEL_ID", "TSUBAKI3_VERSION_ID", "_UNLIMITED_CACHE_TTL",
        "_UNLIMITED_FAIL_TTL", "_unlimited_cache", "UNLIMITED_BUSY", "_UNLIMITED_REFUSED",
        "_UNLIMITED_NO_CARD", "_UNLIMITED_UNWIRED", "_UNLIMITED_T3_ONLY", "_UNLIMITED_IMAGE_ONLY",
        "_UNLIMITED_UNREAD", "_UNLIMITED_UNCONFIRMED", "_UNLIMITED_ENDED", "_UNLIMITED_NOT_HELD",
        "asks_unlimited", "is_lane_request", "_unlimited_identity", "_unlimited_session",
        "_unlimited_raw", "_expiry_epoch", "infinite_mode_status", "_lane_size_rule",
        "_lane_size_ok", "_unlimited_check", "unlimited_resolver", "_graphql_reason",
        "submit_generation", "_SPEND_WATCH", "_SpendMark", "spend_watch", "_mark_spend_reached",
        "_observe_send", "submit_fixer", "GenerationRequest", "RequestResolver",
        "model_version_resolver", "gate_resolver", "_gen_args_from_web_payload",
        "_edit_parameters_from_payload", "_ENHANCE_PRICE_NOTE", "_SUBMIT_ACTIONS",
        "_SUBMIT_ACTION_DEFAULT", "build_request", "_IMAGE_REF_RE", "_image_refs", "_recipes_in",
        "_shape_creativity", "price", "_price_breakdown", "_price_answer", "submit",
        "_send_kwargs", "RUN_SEND_GAP_S", "_run_budget_note", "send_run", "collect_generation",
        "PIXAI_REJECTED_CODES", "DEFINITE_CODES", "TRAINING_CODES", "ANY_PIXAI_CODE",
        "_UNKNOWN_OUTCOME_STATUSES", "classify_outcome", "_GRAPHQL_NUMERIC_CODES",
        "graphql_error_code", "outcome_reason", "definite_refusal", "send_outcome", "CLI_UNCLEAR",
        "SendOutcomeUnclear", "_cli_send_once", "_cli_create_once"]},
    "moonglade.gen_cli": {"from": "moonglade.backup", "names": [
        "_maybe_dump_params", "_outputs_or_raise", "_print_gate_receipt", "run_generate",
        "_video_row_model", "_download_video_task", "_task_image_media", "_task_detail_query",
        "_fix_source_label", "_download_image_task", "_i2v_cli_unsent_notes", "run_generate_video",
        "_resolve_refs", "run_reference_video", "run_upload", "run_edit_image"]},
    "moonglade.training": {"from": "moonglade.backup", "names": [
        "_TRAIN_FREE_CURRENCY", "_CREATE_TRAINING", "TRAIN_CATEGORIES", "TRAIN_MIN_IMAGES",
        "TRAIN_MAX_IMAGES", "_TRAIN_ARCHS", "_TRAIN_BASE_MODELS", "_TRAIN_PRICING",
        "_TRAIN_IMAGE_CONSTRAINTS", "_TRAIN_LONG_TRIGGER_TYPES", "TRAIN_TRIGGER_MAX",
        "TRAIN_TRIGGER_MIN_DIT", "_train_models_from", "_train_pricing_from",
        "_train_constraints_from", "training_config", "training_model_type",
        "training_price_for_version", "TRAIN_RECOMMENDED_TYPE", "default_training_base",
        "list_trainable_base_models", "training_free_quota", "match_training_kaisuuken",
        "_TRAIN_STATUS_TTL", "training_pause", "normalize_trigger_words", "trigger_word_length",
        "validate_training", "check_training_images", "describe_rejected_training_images",
        "submit_training", "TRAIN_GOALS", "TRAIN_ADVANCED_TYPES", "TRAIN_DEFAULT_OPTIONS",
        "TRAIN_CAPTION_MAX", "_TRAINING_TASK_FIELDS", "_TRAINING_TASK_Q", "_MY_LORAS_Q",
        "training_eta", "advanced_training_bases", "training_price_tier", "_TRAIN_ERROR_WORDS",
        "training_error_words", "_task_path", "training_task", "list_training_in_progress",
        "list_training_completed", "list_my_trained_loras", "training_caption_quote",
        "training_quote", "training_captions", "fetch_caption_text",
        "create_advanced_training_draft", "replace_training_media", "start_training_captions",
        "save_training_caption", "submit_advanced_training", "retry_training",
        "publish_training"]},
    "moonglade.task_feed": {"from": "moonglade.backup", "names": [
        "_WS_URI", "_WS_SUBSCRIPTION", "_WS_DONE_STATUS", "_WS_STALE_TIMEOUT", "_WS_HEARTBEAT",
        "_watch_events_async", "run_watch"]},
    "moonglade.contests": {"from": "moonglade.backup", "names": [
        "_CONTEST_PAGE_SIZE", "_CONTEST_MAX_PAGES", "_CONTEST_PAGE_PAUSE", "_contest_title",
        "_contest_rule", "list_contests", "run_contests", "_contest_rows", "contest_my_entries",
        "contest_winners", "contest_artworks", "contest_enter"]},
    # Split phase 4: the first route family. Its routes and helpers are closures inside
    # register(app, ctx), not module attributes, so register is the one name it owns.
    "moonglade.routes_generate": {"from": "moonglade.gallery", "names": ["register"]},
    # Split phase 4: the Loom family, the same way: its store (the board files, the render
    # journal, the sends ledger, the beds) and its routes, each a register(app, ctx). A name has
    # one owner and routes_generate owns gallery's `register`, so these two list none: no
    # gallery attribute moved, and every reader of gallery's text counts as touched.
    "moonglade.web_loom_store": {"from": "moonglade.gallery", "names": []},
    "moonglade.routes_loom": {"from": "moonglade.gallery", "names": []},
    # Split phase 4: the front door and its security core (the sign-in routes, every request
    # hook, the CSRF and session checks, the page shells), the same way: one register(app, ctx),
    # and no gallery attribute moved.
    "moonglade.routes_gate": {"from": "moonglade.gallery", "names": []},
    # Split phase 4: the background block (the Control Panel's job runner, the job log, the
    # schedule and its thread, the watch and its threads, the export job's state), the same
    # way: one register(app, ctx), and no gallery attribute moved.
    "moonglade.web_threads": {"from": "moonglade.gallery", "names": []},
    # Split phase 4: the Control Panel's routes (health and integrity, users, the server's
    # power and library folder, the updater, Bonjour, the exports, the job runner's routes),
    # the same way: one register(app, ctx), and no gallery attribute moved.
    "moonglade.routes_panel": {"from": "moonglade.gallery", "names": []},
    # Split phase 4: the delete routes (the per-image cloud delete, the local delete, the bulk
    # task delete and its preview, the Trash panel), the same way: one register(app, ctx), and
    # no gallery attribute moved.
    "moonglade.routes_delete": {"from": "moonglade.gallery", "names": []},
    # Split phase 4: the recipe market and the model pickers' Saved tab, the same way: one
    # register(app, ctx), and no gallery attribute moved.
    "moonglade.routes_recipes": {"from": "moonglade.gallery", "names": []},
    # Split phase 4: the library's routes (rating, collections, curation, thumbnails, the video
    # file, the full image, the ZIP export, the model search, the duplicates, /api/library,
    # /api/detail, /api/history) and the app-bound _find_local_video_file and
    # _loom_complete_clip, the same way: one register(app, ctx), and no gallery attribute moved.
    "moonglade.routes_library": {"from": "moonglade.gallery", "names": []},
    # Split phase 4: the account's routes (the header chip and account detail, stats, the API-key
    # save, the asset fetch, the claim, snippets, Toolbox presets, saved views, preferences and
    # the in-app guide), the same way: one register(app, ctx), and no gallery attribute moved.
    "moonglade.routes_account": {"from": "moonglade.gallery", "names": []},
    # Split phase 4: the community routes (contests, My Art, lineage, siblings, series, a
    # batch's detail, the inbox, comments and gifts), the same way: one register(app, ctx), and
    # no gallery attribute moved.
    "moonglade.routes_community": {"from": "moonglade.gallery", "names": []},
    # Split phase 4: LoRA training's routes (the Basic submit, the advanced flow, runs, retry,
    # publish, make public) with the start lock, the per-run locks and the train guard, the same
    # way: one register(app, ctx), and no gallery attribute moved (TrainGuard stays in gallery).
    "moonglade.routes_train": {"from": "moonglade.gallery", "names": []},
    # Split phase 4: the achievement routes (the Folio's read, the skin switch, the beacon's nonce
    # and event, the narrator's poke) with create_app's own _ach_lock, the same way: one
    # register(app, ctx), and no gallery attribute moved (the nonce tables stay in gallery).
    "moonglade.routes_ach": {"from": "moonglade.gallery", "names": []},
    # Split phase 4: the Mirror's routes (status, the switch, Disconnect, Connect, the Connect
    # from PixAI window and its token), the same way: one register(app, ctx), and no gallery
    # attribute moved (the sign-in and its renewal stay in moonglade.mirror).
    "moonglade.routes_mirror": {"from": "moonglade.gallery", "names": []},
    # Split phase 4: the branding routes (the public branding art, badge thumbnails, feat masks
    # and the branding panel's API), the same way: one register(app, ctx), and no gallery
    # attribute moved.
    "moonglade.routes_branding": {"from": "moonglade.gallery", "names": []},
    # Split phase 4: the import and outside routes (Fix them, Suggest prompt, tag autocomplete,
    # the upload and the local import with its zip extractor), the same way: one
    # register(app, ctx), and no gallery attribute moved (the zip caps stay in gallery).
    "moonglade.routes_import": {"from": "moonglade.gallery", "names": []},
    # Split phase 4, the module-level sections: gallery's top level leaves section by section,
    # the same way phase 3's did (moved names are reached through the new module, not gallery).
    "moonglade.redact": {"from": "moonglade.gallery", "names": [
        "_USER_HOME_RE", "_redact_host_paths_cli"]},
    "moonglade.web_tiers": {"from": "moonglade.gallery", "names": [
        "PUBLIC", "LOGIN", "LOCALHOST", "TIERS", "LOCALHOST_REFUSAL", "_TIER_ATTR", "tier",
        "route_tier", "route_tier_message", "declare_endpoint_tier",
        "assert_every_route_declares_a_tier"]},
    "moonglade.watch_plans": {"from": "moonglade.gallery", "names": [
        "WATCH_HEALTHY_S", "WATCH_RECONNECT_WAIT", "WATCH_BACKOFF_FIRST", "WATCH_BACKOFF_MAX",
        "WATCH_CATCHUP_MIN_GAP", "WATCH_SWEEP_FLOOR", "WATCH_SUBSCRIBE_SETTLE",
        "WATCH_COLLECT_RETRY_S", "watch_reconnect_plan", "catchup_plan", "watch_close_info"]},
    "moonglade.name_hunt": {"from": "moonglade.gallery", "names": [
        "_HUNT_MAX_PAGES", "_hunt_by_name"]},
    "moonglade.ach_beacon": {"from": "moonglade.gallery", "names": [
        "_ACH_NONCE_TTL_S", "_ACH_NONCE_MAX", "_ACH_DEBOUNCE_S", "_ACH_RATE_MAX",
        "_ACH_RATE_WINDOW_S", "_ach_lock", "_ach_nonces", "_ach_last", "_ach_rate", "_ach_sweep",
        "_ach_mint", "_ach_consume", "_ach_debounced", "_ach_rate_ok"]},
    "moonglade.scenes": {"from": "moonglade.gallery", "names": [
        "SCENES_TTL", "_scenes_cache", "_scenes_cache_lock", "_SCENE_LANG_KEYS", "_SCENE_CDN_HOST",
        "pixai_cdn_url_ok", "scene_catalog", "_scene_label", "_scene_shape", "_scene_detail",
        "scene_thumb_url", "scene_local_art", "scene_row"]},
    "moonglade.pages": {"from": "moonglade.gallery", "names": [
        "DESIGN_TOKENS_CSS", "_upscale_const_js", "_PREPAINT_BOOT_JS", "_AUTH_401_GUARD_JS",
        "_LOOM_SHELL", "LOOM_PAGE_BUNDLE"]},
    "moonglade.web_policy": {"from": "moonglade.gallery", "names": [
        "_GB", "REQUEST_MAX_BYTES", "UPLOAD_MAX_BYTES", "IMPORT_REQUEST_MAX_BYTES",
        "LOOM_BUNDLE_REQUEST_MAX_BYTES", "ZIP_MAX_MEMBERS", "ZIP_MAX_MEMBER_BYTES",
        "ZIP_MAX_TOTAL_BYTES", "IMPORT_CLI_HINT", "ZIP_TOO_MANY_MEMBERS", "ZIP_MEMBER_TOO_BIG",
        "ZIP_TOO_BIG", "ZipTooBig", "_too_large_sentence", "SESSION_ABSOLUTE_LIFETIME_S",
        "SESSION_IDLE_LIFETIME_DAYS", "_INLINE_FILE_TYPES", "FILE_RESPONSE_CSP", "SVG_FILE_CSP",
        "_MEDIA_TYPE_BY_EXT", "media_type_for", "_attachment_disposition", "harden_file_response",
        "CSP_NONCE_MARK", "CSP_PAGE_POLICY", "page_csp", "CROSS_ORIGIN_REFUSED",
        "PLAIN_HTTP_REFUSED", "CONNECT_TOKEN_NEEDS_HTTPS", "_origin_tuple", "same_origin_write"]},
    "moonglade.loom_files": {"from": "moonglade.gallery", "names": [
        "_LOOM_IDS_CACHE", "_loom_board_files", "loom_render_ids", "LOOM_BED_MAX_BYTES",
        "LOOM_BED_FORM_SLACK", "LOOM_BED_FILE_RE", "LOOM_BUNDLE_MAX_BEDS", "LOOM_BED_MIMES",
        "LOOM_BED_UNUSED_GRACE_S", "LOOM_BED_TEMP_SWEEP_AGE_S", "LOOM_EDL_CLIP_RE",
        "LOOM_EDL_BED_NAME_RE", "LOOM_MEDIA_ID_RE", "LOOM_BUNDLE_MEDIA_RE",
        "LOOM_BUNDLE_MEDIA_MAX_BYTES", "LOOM_EDL_MAX_EDL_CHARS", "LOOM_EDL_MAX_CSV_CHARS",
        "LOOM_EDL_MAX_CLIPS", "LOOM_EXPORT_SWEEP_AGE_S", "LOOM_FRAME_FPS", "LOOM_FRAME_WIDTH",
        "LOOM_FRAME_MAX_SECONDS", "LOOM_FRAME_CACHE_MAX_FILES", "LOOM_FRAME_CACHE_MAX_BYTES",
        "LOOM_FRAME_THUMBS_MAX", "LOOM_FRAME_THUMBS_PAUSE_S", "LOOM_FRAME_THUMB_ID_RE",
        "LOOM_FRAME_FILE_RE", "LOOM_BED_FADE_IN", "LOOM_BED_FADE_OUT", "LOOM_BED_DUCK_DB",
        "sniff_audio_ext", "_unlink_quiet", "loom_edl_zip_stem", "_LOOM_BOARD_NAME_RE",
        "_json_string_body", "loom_board_name_salvage", "loom_board_beds", "loom_bed_windows",
        "loom_bed_audio_graph"]},
    "moonglade.catalog_search": {"from": "moonglade.gallery", "names": [
        "_SEARCH_OPS", "_SEARCH_TOKEN_RE", "_SEARCH_KEY_RE", "_SEARCH_NUM_RE", "_SEARCH_DATE_RE",
        "_SEARCH_DATE_PART_RE", "_SEARCH_LORA_WEIGHT_RE", "_LORA_ENTRY_RE", "_SEARCH_TRUTHY",
        "_SEARCH_FALSY", "_unquote", "_personal_tag_pattern", "_SEARCH_NEG_NUMBER_RE",
        "_SEARCH_STAR_RE", "_personal_mark_clause", "_search_token_clause", "_AR_EXPR",
        "AR_SQUARE", "AR_TALL_MAX", "AR_WIDE_MIN", "AR_TOLERANCE", "_AR_WH_RE", "_AR_CMP_RE",
        "_aspect_clause", "_type_clause", "_date_part_bounds", "_date_clause", "_lora_name_regex",
        "_lora_weight_match", "_lora_weight_clause", "_operator_clause", "_build_where"]},
    "moonglade.catalog": {"from": "moonglade.gallery", "names": [
        "CATALOG_FIELDS", "THUMB_SIZE", "THUMB_QUALITY", "_CREATE_TABLE", "_UPSERT", "init_db",
        "_VIDEO_NAME_TO_ID", "_VIDEO_ROW_REPAIR_SQL", "_MIGRATIONS", "_MIGRATED", "_MIGRATE_LOCK",
        "_MIGRATE_RETRY_AT", "MIGRATE_BUSY_BACKOFF_S", "MIGRATE_BUSY_TIMEOUT_S", "_catalog_key",
        "migrate", "catalog", "catalog_csv_text", "load_catalog", "save_catalog",
        "merge_over_current", "save_catalog_over_snapshot", "update_rating", "delete_from_catalog",
        "update_prompt_full", "bulk_replace_prompt", "_db_is_empty", "_SORT_SQL",
        "_DEFAULT_SORT_SQL", "_MANUAL_SORT_SQL", "_order_sql", "_like_pattern", "_like_escape",
        "get_row", "get_row_by_task", "is_archive_only", "_split_collections",
        "unique_collections", "_COLLECTIONS_LOCK", "add_to_collection", "remove_from_collection"]},
    "moonglade.curation": {"from": "moonglade.gallery", "names": [
        "CurationError", "PERSONAL_MARKS", "PERSONAL_TAG_MAX_LEN", "PERSONAL_TAGS_MAX",
        "PERSONAL_NOTE_MAX", "CURATE_MAX_IDS", "_TAG_SPACE_RE", "_TAG_STRIP_RE", "_TAG_DASHES_RE",
        "normalize_tag", "_split_tags", "_CURATION_LOCK", "_now_stamp", "_clean_collection_name",
        "_all_collection_names", "_is_smart_name", "list_smart_collections",
        "smart_collection_query", "_expand_smart", "_auto_smart_name", "save_smart_collection",
        "_rows_with_label", "rename_collection", "merge_collections", "delete_collection",
        "_collection_kind", "ordered_members", "set_collection_order", "collection_summaries",
        "personal_get", "_curation_state", "_write_curation_state", "_clean_tag", "_clean_note",
        "_clean_mark", "_clean_rating", "_clean_ids", "curate_apply", "curation_rows",
        "curate_restore", "query_catalog", "_narrow_to_series", "_series_member_task_ids",
        "batch_member_order", "_filters_from_args", "catalog_counts"]},
    "moonglade.train_guard": {"from": "moonglade.gallery", "names": [
        "TrainGuard"]},
    "moonglade.catalog_verbs": {"from": "moonglade.gallery", "names": [
        "task_media", "media_dims", "published_delete_note", "mark_cloud_deleted",
        "task_media_count", "_TASK_CHUNK", "_delete_targets", "_members_of_tasks",
        "delete_targets", "delete_preview_rows", "myart_items", "SNAPSHOT_KEEP_DAYS",
        "MYART_WINDOW_DAYS", "_local_day", "record_artwork_snapshots", "myart_window",
        "myart_coverage", "artwork_media_ids", "artwork_row", "publish_state",
        "ARTWORK_META_FIELDS", "apply_artwork_meta", "apply_artwork_views", "lineage",
        "sibling_media", "recent_train_task_page", "history_page", "history_created_ats",
        "distinct_task_count", "backup_coverage", "rows_for_media_ids", "paid_credit_for_tasks",
        "loom_cost", "loom_send_key", "loom_sends_fold", "loom_backfill_sends", "integrity_rows",
        "list_media_ids", "list_group_rows", "unique_models", "backfill_batches", "catalog_years",
        "find_image_file"]},
    "moonglade.thumbs": {"from": "moonglade.gallery", "names": [
        "compute_dhash", "_THUMBLESS_EXTS", "thumbnail_renders", "_PIL_EXTS", "CHECKER_A",
        "CHECKER_B", "CHECKER_SQUARE", "CHECKER_MARKER", "_see_through_rgba", "_checkerboard",
        "thumb_rgb", "_could_be_see_through", "source_is_see_through", "make_thumbnail",
        "make_video_thumbnail", "probe_has_audio", "probe_duration", "build_thumbnails",
        "_write_checker_marker", "recheck_see_through_thumbnails", "start_see_through_recheck"]},
    "moonglade.trash": {"from": "moonglade.gallery", "names": [
        "DELETE_PREVIEW_TASK_CAP", "DELETE_PREVIEW_LIVE_CAP", "DELETE_PREVIEW_LIVE_WORKERS",
        "DELETE_PREVIEW_LIVE_BUDGET_S", "_trash_meta_path", "_read_trash_meta",
        "_snapshot_before_purge", "purge_media_local", "_find_quarantined_file",
        "list_quarantined", "_list_quarantined", "_ensure_trash_thumbs",
        "restore_quarantined_media", "delete_quarantined_forever", "empty_trash"]},
    "moonglade.dupe_review": {"from": "moonglade.gallery", "names": [
        "_quarantine_meta_path", "_resolve_under", "_reconcile_one_row_after_move",
        "quarantine_duplicate_file", "restore_quarantined_duplicate", "_validate_duplicate_pair"]},
    "moonglade.web_accounts": {"from": "moonglade.backup", "names": [
        "WEB_PASSWORD_HASH_METHOD", "get_or_create_secret_key", "_find_web_user",
        "_EPOCH_SEQ_KEY", "_EPOCH_LEGACY_MARGIN", "_next_sess_epoch", "list_web_users",
        "MIN_WEB_PASSWORD_LEN", "MAX_WEB_USERNAME_LEN", "_COMMON_PASSWORDS", "_is_single_run",
        "password_problem", "username_problem", "add_or_update_web_user",
        "set_web_user_password_guarded", "add_web_user_if_new", "remove_web_user",
        "remove_web_user_guarded", "get_web_user_session_epoch", "bump_web_user_session_epoch",
        "_dummy_hash_cache", "_dummy_password_hash", "verify_web_user", "run_add_web_user",
        "run_remove_web_user", "remove_login_files", "run_list_web_users"]},
    "moonglade.history": {"from": "moonglade.backup", "names": [
        "_HISTORY_PAGE_DOC", "HISTORY_REFUSED", "HISTORY_RETRY_WAIT_S", "HISTORY_FALLBACK_LAST",
        "COUNT_PAGE_SIZE", "_history_wait", "_feed_refusal", "gql", "_history_answer",
        "find_connection", "slug_from_prompt", "build_stem_name", "_FIX_TAGS", "local_media_id",
        "_LOCAL_SUFFIX_RE", "build_local_name", "migrate_local_filenames", "fixer_block",
        "fix_marker", "build_fix_stem_name", "already_downloaded", "already_downloaded_video",
        "_file_sha", "_same_bytes", "_same_pixels", "media_ids_for", "cataloged_media_ids",
        "_is_video_task_node", "extract_meta"]},
    "moonglade.media_fetch": {"from": "moonglade.backup", "names": [
        "URL_VARIANT_PREFERENCE", "_MEDIA_TLS_LOCK", "_media_tls_warned", "_CONSOLE_LOCK",
        "_console_block", "_warn_media_tls_once", "resolve_media", "ext_from_ct",
        "embed_metadata", "convert_image", "download", "page_variables"]},
    "moonglade.full_meta": {"from": "moonglade.backup", "names": [
        "_FULL_META_FIELDS", "_paid_credit_str", "media_file_gql", "video_outputs",
        "run_list_models", "_GEN_SURFACE_FIELDS", "_TASK_ROW_FIELDS", "_prompt_helper_label",
        "_RECORDED_OUTPUT_FORMATS", "_output_format_of", "_mc_int_str", "_task_for_full_meta",
        "extract_full_meta", "batch_position", "_with_batch_position", "_resolve_model_preset",
        "_fill_preset_defaults", "resolve_loras", "_merge_full", "known_catalog_rows",
        "carry_local_fields", "_created_at_utc", "build_catalog_row", "cmd_convert_existing"]},
    "moonglade.library_runs": {"from": "moonglade.backup", "names": [
        "run_sync_artworks", "run_sync_videos", "_under", "run_faststart_videos",
        "run_import_local", "_resolved_loras", "_resolved_model_name", "_edit_model_label",
        "_needs_model_fix", "run_fix_models", "RECONCILE_STAMP", "_NO_PICTURE_STATUSES",
        "feed_counts", "read_reconcile_stamp", "_stamp_reconcile", "run_reconcile_deleted",
        "DiskCounts", "_count_backup_images", "run_rebuild_similar", "run_sync_similar",
        "_one_line", "run_search", "run_catalog_stats", "_META_COVERAGE",
        "_print_meta_coverage"]},
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
    "tests/test_contest_wins.py": ("moonglade.backup",),   # its scheduler read: web_threads
    "tests/test_create_door.py": ("moonglade.backup",),
    "tests/test_csrf_coverage.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_edit_upload.py": ("moonglade.backup",),
    "tests/test_enhance.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_evidence_counters.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_first_party_sources.py": ("moonglade.gallery",),
    "tests/test_full_meta_rest_fallback.py": ("moonglade.backup",),
    "tests/test_gen_surface.py": ("moonglade.backup",),   # its Loom read is routes_loom's now
    "tests/test_history_feed_document.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_jwt.py": ("moonglade.backup",),   # its scheduler read is web_threads' now
    "tests/test_living_library.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_logging.py": ("moonglade.gallery",),
    "tests/test_loom_notify.py": ("moonglade.backup",),
    "tests/test_loom_p_routes.py": ("moonglade.gallery",),
    "tests/test_media_tools.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_move_edges.py": ("moonglade.gallery",),
    "tests/test_network.py": ("moonglade.gallery",),   # its page_variables read: media_fetch
    "tests/test_outside_notice.py": ("moonglade.gallery",),
    "tests/test_pack_file_name.py": ("moonglade.gallery",),
    "tests/test_pack_file_type.py": ("moonglade.gallery",),
    "tests/test_pixai_client.py": ("moonglade.backup",),
    "tests/test_module_seams.py": ("moonglade.backup", "moonglade.gallery"),   # every module
    "tests/test_rest_delete_and_renewal.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_security_review_fixes.py": ("moonglade.gallery",),
    "tests/test_server_one_module.py": ("moonglade.gallery",),
    "tests/test_server_stop_record.py": ("moonglade.gallery",),
    "tests/test_settings_store.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_setup_prepare.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_spend_no_retry.py": ("moonglade.backup",),
    "tests/test_task_model_detail_document.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_telemetry.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_training_advanced.py": ("moonglade.backup",),
    "tests/test_training_parity.py": ("moonglade.backup",),
    "tests/test_tsubaki3_image_gate.py": ("moonglade.backup", "moonglade.gallery"),
    "tests/test_unclear_single_sends.py": ("moonglade.backup",),
    "tools/split_names.py": ("moonglade.backup", "moonglade.gallery"),   # the move proof's sweep
    "loom/test/import-batches.test.js": ("moonglade.scan",),
    "loom/test/ledger-known-reasons.test.js": ("moonglade.cards",),
    "loom/test/med-loom-bundle-missing-report.test.js": ("moonglade.routes_loom",),
    "loom/test/mg-art-filters.test.js": ("moonglade.pages",),
    "loom/test/mg-notify-queue-phase.test.js": ("moonglade.pages",),
    "loom/test/mg-notify-website-source.test.js": ("moonglade.pages",
                                                   "moonglade.routes_generate",
                                                   "moonglade.web_threads"),
    "loom/test/phone-back-layers.test.js": ("moonglade.pages", "moonglade.routes_gate"),
    "loom/test/video-roster-parity.test.js": ("moonglade.gen_params",),
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
    # 3.21.2 (L1): test_unclear_single_sends reads the CLI runners' and main()'s own source
    # (run_generate*, run_reference_video, run_edit_image, main), which stayed in backup;
    # nothing it reads moved to pixai_client or mirror.
    ('tests/test_unclear_single_sends.py', 'moonglade.pixai_client'),
    ('tests/test_unclear_single_sends.py', 'moonglade.mirror'),
    # 3.22 phase 5, task_reads: no reader reads text that left backup.py. The ones that name a moved
    # read (test_network, test_pixai_client, test_task_model_detail_document, test_spend_no_retry,
    # test_poll) call or getsource it through task_reads_mod; test_pixai_client's detail-read loop
    # looks the name up in whichever module holds it, which made it an untraced reader: nothing it
    # reads moved to organize, jobs or media_tools either. test_watch's gallery reads expect
    # `_task_reads._GEN_DONE`.
    ('tests/test_pixai_client.py', 'moonglade.jobs'),
    ('tests/test_pixai_client.py', 'moonglade.media_tools'),
    ('tests/test_pixai_client.py', 'moonglade.organize'),
    ('loom/test/ledger-known-reasons.test.js', 'moonglade.task_reads'),
    ('loom/test/video-roster-parity.test.js', 'moonglade.task_reads'),
    ('tests/test_artworks_adhoc.py', 'moonglade.task_reads'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.task_reads'),
    ('tests/test_config_path_routing.py', 'moonglade.task_reads'),
    ('tests/test_csrf_coverage.py', 'moonglade.task_reads'),
    ('tests/test_delete_routing.py', 'moonglade.task_reads'),
    ('tests/test_enhance.py', 'moonglade.task_reads'),
    ('tests/test_evidence_counters.py', 'moonglade.task_reads'),
    ('tests/test_gen_surface.py', 'moonglade.task_reads'),
    ('tests/test_history_feed_document.py', 'moonglade.task_reads'),
    ('tests/test_jwt.py', 'moonglade.task_reads'),
    ('tests/test_living_library.py', 'moonglade.task_reads'),
    ('tests/test_loom_notify.py', 'moonglade.task_reads'),
    ('tests/test_network.py', 'moonglade.task_reads'),
    ('tests/test_pixai_client.py', 'moonglade.task_reads'),
    ('tests/test_read_only.py', 'moonglade.task_reads'),
    ('tests/test_settings_store.py', 'moonglade.task_reads'),
    ('tests/test_setup_prepare.py', 'moonglade.task_reads'),
    ('tests/test_spend_no_retry.py', 'moonglade.task_reads'),
    ('tests/test_task_model_detail_document.py', 'moonglade.task_reads'),
    ('tests/test_telemetry.py', 'moonglade.task_reads'),
    ('tests/test_training_advanced.py', 'moonglade.task_reads'),
    ('tests/test_training_parity.py', 'moonglade.task_reads'),
    ('tests/test_video_tsubaki.py', 'moonglade.task_reads'),
    ('tests/test_web_auth.py', 'moonglade.task_reads'),
    # 3.22 phase 5, cloud_delete: no reader reads text that left backup.py. test_spend_no_retry
    # reads its spend paths through _spend_path (backup, or the module a path moved to) and the
    # delete paths' parsed source through cloud_delete_mod; test_task_model_detail_document's delete
    # plan reads go through cloud_delete_mod. test_delete_routing and test_read_only read only the
    # moved router's source, now through cloud_delete_mod, so they left SOURCE_READERS.
    ('loom/test/ledger-known-reasons.test.js', 'moonglade.cloud_delete'),
    ('loom/test/video-roster-parity.test.js', 'moonglade.cloud_delete'),
    ('tests/test_artworks_adhoc.py', 'moonglade.cloud_delete'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.cloud_delete'),
    ('tests/test_config_path_routing.py', 'moonglade.cloud_delete'),
    ('tests/test_csrf_coverage.py', 'moonglade.cloud_delete'),
    ('tests/test_enhance.py', 'moonglade.cloud_delete'),
    ('tests/test_evidence_counters.py', 'moonglade.cloud_delete'),
    ('tests/test_gen_surface.py', 'moonglade.cloud_delete'),
    ('tests/test_history_feed_document.py', 'moonglade.cloud_delete'),
    ('tests/test_jwt.py', 'moonglade.cloud_delete'),
    ('tests/test_living_library.py', 'moonglade.cloud_delete'),
    ('tests/test_loom_notify.py', 'moonglade.cloud_delete'),
    ('tests/test_network.py', 'moonglade.cloud_delete'),
    ('tests/test_pixai_client.py', 'moonglade.cloud_delete'),
    ('tests/test_settings_store.py', 'moonglade.cloud_delete'),
    ('tests/test_setup_prepare.py', 'moonglade.cloud_delete'),
    ('tests/test_spend_no_retry.py', 'moonglade.cloud_delete'),
    ('tests/test_task_model_detail_document.py', 'moonglade.cloud_delete'),
    ('tests/test_telemetry.py', 'moonglade.cloud_delete'),
    ('tests/test_training_advanced.py', 'moonglade.cloud_delete'),
    ('tests/test_training_parity.py', 'moonglade.cloud_delete'),
    ('tests/test_web_auth.py', 'moonglade.cloud_delete'),
    # 3.22 phase 5, models: no reader reads text that left backup.py. The model readers' source
    # (test_pixai_client's loop, test_task_model_detail_document, test_network's document names) is
    # read through models_mod; test_enhance's workflow_catalog and test_unclear_single_sends' gate
    # names are reached through models_mod; the whole-file readers look for names that stayed.
    ('loom/test/ledger-known-reasons.test.js', 'moonglade.models'),
    ('loom/test/video-roster-parity.test.js', 'moonglade.models'),
    ('tests/test_artworks_adhoc.py', 'moonglade.models'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.models'),
    ('tests/test_config_path_routing.py', 'moonglade.models'),
    ('tests/test_csrf_coverage.py', 'moonglade.models'),
    ('tests/test_enhance.py', 'moonglade.models'),
    ('tests/test_evidence_counters.py', 'moonglade.models'),
    ('tests/test_gen_surface.py', 'moonglade.models'),
    ('tests/test_history_feed_document.py', 'moonglade.models'),
    ('tests/test_jwt.py', 'moonglade.models'),
    ('tests/test_living_library.py', 'moonglade.models'),
    ('tests/test_loom_notify.py', 'moonglade.models'),
    ('tests/test_network.py', 'moonglade.models'),
    ('tests/test_pixai_client.py', 'moonglade.models'),
    ('tests/test_settings_store.py', 'moonglade.models'),
    ('tests/test_setup_prepare.py', 'moonglade.models'),
    ('tests/test_spend_no_retry.py', 'moonglade.models'),
    ('tests/test_task_model_detail_document.py', 'moonglade.models'),
    ('tests/test_telemetry.py', 'moonglade.models'),
    ('tests/test_training_advanced.py', 'moonglade.models'),
    ('tests/test_training_parity.py', 'moonglade.models'),
    ('tests/test_unclear_single_sends.py', 'moonglade.models'),
    ('tests/test_video_tsubaki.py', 'moonglade.models'),
    ('tests/test_web_auth.py', 'moonglade.models'),
    # 3.22 phase 5, pricing: no reader reads text that left backup.py. test_edit_upload and
    # test_video_tsubaki reach price_task through pricing_mod; test_fix's quote-path checks read
    # _FIXER_PRICE_PATH there; the whole-file readers look for names that stayed.
    ('loom/test/ledger-known-reasons.test.js', 'moonglade.pricing'),
    ('loom/test/video-roster-parity.test.js', 'moonglade.pricing'),
    ('tests/test_artworks_adhoc.py', 'moonglade.pricing'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.pricing'),
    ('tests/test_config_path_routing.py', 'moonglade.pricing'),
    ('tests/test_csrf_coverage.py', 'moonglade.pricing'),
    ('tests/test_edit_upload.py', 'moonglade.pricing'),
    ('tests/test_enhance.py', 'moonglade.pricing'),
    ('tests/test_evidence_counters.py', 'moonglade.pricing'),
    ('tests/test_gen_surface.py', 'moonglade.pricing'),
    ('tests/test_history_feed_document.py', 'moonglade.pricing'),
    ('tests/test_jwt.py', 'moonglade.pricing'),
    ('tests/test_living_library.py', 'moonglade.pricing'),
    ('tests/test_loom_notify.py', 'moonglade.pricing'),
    ('tests/test_network.py', 'moonglade.pricing'),
    ('tests/test_pixai_client.py', 'moonglade.pricing'),
    ('tests/test_settings_store.py', 'moonglade.pricing'),
    ('tests/test_setup_prepare.py', 'moonglade.pricing'),
    ('tests/test_spend_no_retry.py', 'moonglade.pricing'),
    ('tests/test_task_model_detail_document.py', 'moonglade.pricing'),
    ('tests/test_telemetry.py', 'moonglade.pricing'),
    ('tests/test_training_advanced.py', 'moonglade.pricing'),
    ('tests/test_training_parity.py', 'moonglade.pricing'),
    ('tests/test_video_tsubaki.py', 'moonglade.pricing'),
    ('tests/test_web_auth.py', 'moonglade.pricing'),
    # 3.22 phase 5, cards: the one reader that read moved text is loom/test/ledger-known-reasons,
    # whose CREDIT_LOG_REASONS table it now reads from moonglade/cards.py (its SOURCE_READERS entry
    # says so). The others reach the card names through cards_mod (test_training_parity,
    # test_edit_upload, test_video_tsubaki, test_unclear_single_sends, test_telemetry) or look for
    # names that stayed.
    ('loom/test/video-roster-parity.test.js', 'moonglade.cards'),
    ('tests/test_artworks_adhoc.py', 'moonglade.cards'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.cards'),
    ('tests/test_config_path_routing.py', 'moonglade.cards'),
    ('tests/test_csrf_coverage.py', 'moonglade.cards'),
    ('tests/test_edit_upload.py', 'moonglade.cards'),
    ('tests/test_enhance.py', 'moonglade.cards'),
    ('tests/test_evidence_counters.py', 'moonglade.cards'),
    ('tests/test_gen_surface.py', 'moonglade.cards'),
    ('tests/test_history_feed_document.py', 'moonglade.cards'),
    ('tests/test_jwt.py', 'moonglade.cards'),
    ('tests/test_living_library.py', 'moonglade.cards'),
    ('tests/test_loom_notify.py', 'moonglade.cards'),
    ('tests/test_network.py', 'moonglade.cards'),
    ('tests/test_pixai_client.py', 'moonglade.cards'),
    ('tests/test_settings_store.py', 'moonglade.cards'),
    ('tests/test_setup_prepare.py', 'moonglade.cards'),
    ('tests/test_spend_no_retry.py', 'moonglade.cards'),
    ('tests/test_task_model_detail_document.py', 'moonglade.cards'),
    ('tests/test_telemetry.py', 'moonglade.cards'),
    ('tests/test_training_advanced.py', 'moonglade.cards'),
    ('tests/test_training_parity.py', 'moonglade.cards'),
    ('tests/test_unclear_single_sends.py', 'moonglade.cards'),
    ('tests/test_video_tsubaki.py', 'moonglade.cards'),
    ('tests/test_web_auth.py', 'moonglade.cards'),
    # 3.22 phase 5, gen_params: two readers read text that left backup.py and now read
    # moonglade/gen_params.py: loom/test/video-roster-parity (the video tables; its SOURCE_READERS
    # entry says so) and test_enhance's restored-panelplugin check (the builder's literals; the
    # `--workflow-id` absence check still reads backup, where the parser is). The rest reach the
    # builders through gen_params_mod or look for names that stayed.
    ('tests/test_artworks_adhoc.py', 'moonglade.gen_params'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.gen_params'),
    ('tests/test_config_path_routing.py', 'moonglade.gen_params'),
    ('tests/test_csrf_coverage.py', 'moonglade.gen_params'),
    ('tests/test_edit_upload.py', 'moonglade.gen_params'),
    ('tests/test_enhance.py', 'moonglade.gen_params'),
    ('tests/test_evidence_counters.py', 'moonglade.gen_params'),
    ('tests/test_gen_surface.py', 'moonglade.gen_params'),
    ('tests/test_history_feed_document.py', 'moonglade.gen_params'),
    ('tests/test_jwt.py', 'moonglade.gen_params'),
    ('tests/test_living_library.py', 'moonglade.gen_params'),
    ('tests/test_loom_notify.py', 'moonglade.gen_params'),
    ('tests/test_network.py', 'moonglade.gen_params'),
    ('tests/test_pixai_client.py', 'moonglade.gen_params'),
    ('tests/test_settings_store.py', 'moonglade.gen_params'),
    ('tests/test_setup_prepare.py', 'moonglade.gen_params'),
    ('tests/test_spend_no_retry.py', 'moonglade.gen_params'),
    ('tests/test_task_model_detail_document.py', 'moonglade.gen_params'),
    ('tests/test_telemetry.py', 'moonglade.gen_params'),
    ('tests/test_training_advanced.py', 'moonglade.gen_params'),
    ('tests/test_training_parity.py', 'moonglade.gen_params'),
    ('tests/test_unclear_single_sends.py', 'moonglade.gen_params'),
    ('tests/test_video_tsubaki.py', 'moonglade.gen_params'),
    ('tests/test_web_auth.py', 'moonglade.gen_params'),
    # 3.22 phase 5, gen_road: no reader reads text that left backup.py. test_spend_no_retry reads
    # submit_generation and send_run through _spend_path; test_unclear_single_sends' main() pin
    # expects `_gen_road.SendOutcomeUnclear`; test_training_advanced and test_telemetry reach the
    # code tables and the creates through gen_road_mod; test_loom_generate_guard's gallery check
    # also bans `_gen_road.submit(`; the whole-file readers look for names that stayed.
    ('tests/test_artworks_adhoc.py', 'moonglade.gen_road'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.gen_road'),
    ('tests/test_config_path_routing.py', 'moonglade.gen_road'),
    ('tests/test_csrf_coverage.py', 'moonglade.gen_road'),
    ('tests/test_edit_upload.py', 'moonglade.gen_road'),
    ('tests/test_enhance.py', 'moonglade.gen_road'),
    ('tests/test_evidence_counters.py', 'moonglade.gen_road'),
    ('tests/test_gen_surface.py', 'moonglade.gen_road'),
    ('tests/test_history_feed_document.py', 'moonglade.gen_road'),
    ('tests/test_jwt.py', 'moonglade.gen_road'),
    ('tests/test_living_library.py', 'moonglade.gen_road'),
    ('tests/test_loom_notify.py', 'moonglade.gen_road'),
    ('tests/test_network.py', 'moonglade.gen_road'),
    ('tests/test_pixai_client.py', 'moonglade.gen_road'),
    ('tests/test_settings_store.py', 'moonglade.gen_road'),
    ('tests/test_setup_prepare.py', 'moonglade.gen_road'),
    ('tests/test_spend_no_retry.py', 'moonglade.gen_road'),
    ('tests/test_task_model_detail_document.py', 'moonglade.gen_road'),
    ('tests/test_telemetry.py', 'moonglade.gen_road'),
    ('tests/test_training_advanced.py', 'moonglade.gen_road'),
    ('tests/test_training_parity.py', 'moonglade.gen_road'),
    ('tests/test_unclear_single_sends.py', 'moonglade.gen_road'),
    ('tests/test_video_tsubaki.py', 'moonglade.gen_road'),
    ('tests/test_web_auth.py', 'moonglade.gen_road'),
    # 3.22 phase 5, gen_cli: two readers read text that left backup.py and now read
    # moonglade/gen_cli.py as well: test_gen_surface (the capture paths' row building, and
    # run_generate's sampling fields) and test_network (the live capture's written fields, in
    # _download_image_task). test_unclear_single_sends, test_read_only, test_spend_no_retry and
    # test_video_tsubaki reach the runners through gen_cli_mod.
    ('tests/test_artworks_adhoc.py', 'moonglade.gen_cli'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.gen_cli'),
    ('tests/test_config_path_routing.py', 'moonglade.gen_cli'),
    ('tests/test_csrf_coverage.py', 'moonglade.gen_cli'),
    ('tests/test_edit_upload.py', 'moonglade.gen_cli'),
    ('tests/test_enhance.py', 'moonglade.gen_cli'),
    ('tests/test_evidence_counters.py', 'moonglade.gen_cli'),
    ('tests/test_gen_surface.py', 'moonglade.gen_cli'),
    ('tests/test_history_feed_document.py', 'moonglade.gen_cli'),
    ('tests/test_jwt.py', 'moonglade.gen_cli'),
    ('tests/test_living_library.py', 'moonglade.gen_cli'),
    ('tests/test_loom_notify.py', 'moonglade.gen_cli'),
    ('tests/test_network.py', 'moonglade.gen_cli'),
    ('tests/test_pixai_client.py', 'moonglade.gen_cli'),
    ('tests/test_settings_store.py', 'moonglade.gen_cli'),
    ('tests/test_setup_prepare.py', 'moonglade.gen_cli'),
    ('tests/test_spend_no_retry.py', 'moonglade.gen_cli'),
    ('tests/test_task_model_detail_document.py', 'moonglade.gen_cli'),
    ('tests/test_telemetry.py', 'moonglade.gen_cli'),
    ('tests/test_training_advanced.py', 'moonglade.gen_cli'),
    ('tests/test_training_parity.py', 'moonglade.gen_cli'),
    ('tests/test_unclear_single_sends.py', 'moonglade.gen_cli'),
    ('tests/test_video_tsubaki.py', 'moonglade.gen_cli'),
    ('tests/test_web_auth.py', 'moonglade.gen_cli'),
    # 3.22 phase 5, training: no reader reads text that left backup.py. test_training_advanced,
    # test_training_parity, test_read_only, test_spend_no_retry (_spend_path) and test_telemetry
    # reach the training names through training_mod; the whole-file readers look for names that
    # stayed (the config road among them).
    ('tests/test_artworks_adhoc.py', 'moonglade.training'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.training'),
    ('tests/test_config_path_routing.py', 'moonglade.training'),
    ('tests/test_csrf_coverage.py', 'moonglade.training'),
    ('tests/test_enhance.py', 'moonglade.training'),
    ('tests/test_evidence_counters.py', 'moonglade.training'),
    ('tests/test_gen_surface.py', 'moonglade.training'),
    ('tests/test_history_feed_document.py', 'moonglade.training'),
    ('tests/test_jwt.py', 'moonglade.training'),
    ('tests/test_living_library.py', 'moonglade.training'),
    ('tests/test_loom_notify.py', 'moonglade.training'),
    ('tests/test_pixai_client.py', 'moonglade.training'),
    ('tests/test_settings_store.py', 'moonglade.training'),
    ('tests/test_setup_prepare.py', 'moonglade.training'),
    ('tests/test_spend_no_retry.py', 'moonglade.training'),
    ('tests/test_task_model_detail_document.py', 'moonglade.training'),
    ('tests/test_telemetry.py', 'moonglade.training'),
    ('tests/test_training_advanced.py', 'moonglade.training'),
    ('tests/test_training_parity.py', 'moonglade.training'),
    ('tests/test_web_auth.py', 'moonglade.training'),
    # 3.22 phase 5, task_feed: no reader reads text that left backup.py. test_watch drives the
    # socket through task_feed_mod and its gallery check also bans `_task_feed._WS_DONE_STATUS`;
    # test_pixai_client's run_watch mention is prose.
    ('tests/test_artworks_adhoc.py', 'moonglade.task_feed'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.task_feed'),
    ('tests/test_config_path_routing.py', 'moonglade.task_feed'),
    ('tests/test_csrf_coverage.py', 'moonglade.task_feed'),
    ('tests/test_enhance.py', 'moonglade.task_feed'),
    ('tests/test_evidence_counters.py', 'moonglade.task_feed'),
    ('tests/test_gen_surface.py', 'moonglade.task_feed'),
    ('tests/test_history_feed_document.py', 'moonglade.task_feed'),
    ('tests/test_jwt.py', 'moonglade.task_feed'),
    ('tests/test_living_library.py', 'moonglade.task_feed'),
    ('tests/test_loom_notify.py', 'moonglade.task_feed'),
    ('tests/test_pixai_client.py', 'moonglade.task_feed'),
    ('tests/test_settings_store.py', 'moonglade.task_feed'),
    ('tests/test_setup_prepare.py', 'moonglade.task_feed'),
    ('tests/test_spend_no_retry.py', 'moonglade.task_feed'),
    ('tests/test_task_model_detail_document.py', 'moonglade.task_feed'),
    ('tests/test_telemetry.py', 'moonglade.task_feed'),
    ('tests/test_training_advanced.py', 'moonglade.task_feed'),
    ('tests/test_training_parity.py', 'moonglade.task_feed'),
    ('tests/test_web_auth.py', 'moonglade.task_feed'),
    # 3.22 phase 5, contests: no reader reads text that left backup.py. test_contest_wins and
    # test_contest reach the contest reads and the entry through contests_mod; the whole-file
    # readers look for names that stayed.
    ('tests/test_artworks_adhoc.py', 'moonglade.contests'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.contests'),
    ('tests/test_config_path_routing.py', 'moonglade.contests'),
    ('tests/test_contest_wins.py', 'moonglade.contests'),
    ('tests/test_csrf_coverage.py', 'moonglade.contests'),
    ('tests/test_enhance.py', 'moonglade.contests'),
    ('tests/test_evidence_counters.py', 'moonglade.contests'),
    ('tests/test_gen_surface.py', 'moonglade.contests'),
    ('tests/test_history_feed_document.py', 'moonglade.contests'),
    ('tests/test_jwt.py', 'moonglade.contests'),
    ('tests/test_living_library.py', 'moonglade.contests'),
    ('tests/test_loom_notify.py', 'moonglade.contests'),
    ('tests/test_pixai_client.py', 'moonglade.contests'),
    ('tests/test_settings_store.py', 'moonglade.contests'),
    ('tests/test_setup_prepare.py', 'moonglade.contests'),
    ('tests/test_spend_no_retry.py', 'moonglade.contests'),
    ('tests/test_task_model_detail_document.py', 'moonglade.contests'),
    ('tests/test_telemetry.py', 'moonglade.contests'),
    ('tests/test_training_advanced.py', 'moonglade.contests'),
    ('tests/test_training_parity.py', 'moonglade.contests'),
    ('tests/test_web_auth.py', 'moonglade.contests'),
    # 3.22 S2a: the create door's test reads only backup's `_create` delegate (and
    # pixai_client's own source), neither of which any move touched.
    *(("tests/test_create_door.py", "moonglade." + _m) for _m in (
        "cards", "cloud_delete", "contests", "gen_cli", "gen_params", "gen_road", "jobs",
        "media_tools", "mirror", "models", "organize", "pixai_client", "pricing", "task_feed",
        "task_reads", "training")),
    # 3.22 F4: the full-meta fallback test reads the source of backup's run_backfill_full_meta
    # and run_download (both stayed in backup) and of cloud_delete; it was written after every
    # move, so nothing it reads has since moved.
    *(("tests/test_full_meta_rest_fallback.py", "moonglade." + _m) for _m in (
        "cards", "cloud_delete", "contests", "gen_cli", "gen_params", "gen_road", "jobs",
        "media_tools", "mirror", "models", "organize", "pixai_client", "pricing", "task_feed",
        "task_reads", "training")),
    # Split phase 4 step 0a: the one-server-module test reads only gallery.py's closing
    # `if __name__ == "__main__":` block (its self-test swaps it for the old one); it was written
    # after every move, and none of them touched that block.
    *(("tests/test_server_one_module.py", "moonglade." + _m) for _m in (
        "about", "account_prefs", "achievements", "branding", "contest_sync", "dupes", "health",
        "living", "scan", "series", "telemetry", "updater")),
    # Split phase 4: the create routes -> moonglade.routes_generate. Readers that read text which
    # left gallery.py now read routes_generate too: test_csrf_coverage (the _check_csrf callers),
    # test_catalog_verbs (the "no SQL in a handler" walk covers register), test_telemetry (the
    # two bridge-set writers), test_evidence_counters, test_settings_store, test_catchup_query,
    # test_artworks_adhoc and test_history_feed_document (their absence checks keep covering the
    # moved code) and mg-notify-website-source.test.js (/api/jobs' "web" default). The rest read
    # code that did not move (main, the Loom routes, the watch, the page shells, the palettes,
    # create_app's setup and its other closures).
    *((_r, "moonglade.routes_generate") for _r in (
        "loom/test/med-loom-bundle-missing-report.test.js", "loom/test/mg-art-filters.test.js",
        "loom/test/mg-notify-queue-phase.test.js", "loom/test/mg-notify-website-source.test.js",
        "loom/test/phone-back-layers.test.js", "tests/test_app_paths.py",
        "tests/test_artworks_adhoc.py", "tests/test_bonjour.py", "tests/test_branding.py",
        "tests/test_branding_tree_rules.py", "tests/test_catalog_verbs.py",
        "tests/test_catchup_query.py", "tests/test_csrf_coverage.py",
        "tests/test_design_kit_sync.py", "tests/test_doc_truth_residuals.py",
        "tests/test_evidence_counters.py", "tests/test_first_party_sources.py",
        "tests/test_gen_surface.py", "tests/test_history_feed_document.py",
        "tests/test_library_dir.py", "tests/test_living_library.py", "tests/test_logging.py",
        "tests/test_loom_generate_guard.py", "tests/test_loom_notify.py",
        "tests/test_loom_p_routes.py", "tests/test_network.py",
        "tests/test_security_review_fixes.py", "tests/test_server_one_module.py",
        "tests/test_settings_store.py", "tests/test_setup_prepare.py",
        "tests/test_task_model_detail_document.py", "tests/test_telemetry.py", "tests/test_watch.py",
        "tools/export_design_kit.py")),
    # Split phase 4: the Loom -> moonglade.web_loom_store and moonglade.routes_loom. Readers of
    # the moved text now read the Loom modules: test_loom_p_routes (its no-spend walks cover all
    # three files), test_loom_generate_guard (the JSON-body and handoff source checks),
    # test_security_review_fixes (the bundle import's named cap), test_gen_surface (the bundle
    # import's catalog rows) and med-loom-bundle-missing-report.test.js (its label shapes); the
    # absence and coverage readers routes_generate's move widened (test_csrf_coverage,
    # test_catalog_verbs, test_telemetry, test_evidence_counters, test_settings_store,
    # test_catchup_query, test_artworks_adhoc, test_history_feed_document) read both Loom
    # modules too. The rest read code that did not move (main, the page shells and _LOOM_SHELL,
    # the palettes, the scheduler and its ticks, create_app's setup and its other closures).
    *((_r, "moonglade." + _m) for _m in ("web_loom_store", "routes_loom") for _r in (
        "loom/test/med-loom-bundle-missing-report.test.js", "loom/test/mg-art-filters.test.js",
        "loom/test/mg-notify-queue-phase.test.js", "loom/test/mg-notify-website-source.test.js",
        "loom/test/phone-back-layers.test.js", "tests/test_app_paths.py",
        "tests/test_artworks_adhoc.py", "tests/test_bonjour.py", "tests/test_branding.py",
        "tests/test_branding_tree_rules.py", "tests/test_catalog_verbs.py",
        "tests/test_catchup_query.py", "tests/test_contest_wins.py", "tests/test_csrf_coverage.py",
        "tests/test_design_kit_sync.py", "tests/test_doc_truth_residuals.py",
        "tests/test_evidence_counters.py", "tests/test_first_party_sources.py",
        "tests/test_gen_surface.py", "tests/test_history_feed_document.py", "tests/test_jwt.py",
        "tests/test_library_dir.py", "tests/test_living_library.py", "tests/test_logging.py",
        "tests/test_loom_generate_guard.py", "tests/test_loom_notify.py",
        "tests/test_loom_p_routes.py", "tests/test_move_edges.py", "tests/test_network.py",
        "tests/test_outside_notice.py", "tests/test_pack_file_name.py",
        "tests/test_pack_file_type.py", "tests/test_panel.py",
        "tests/test_rest_delete_and_renewal.py", "tests/test_security_review_fixes.py",
        "tests/test_server_one_module.py", "tests/test_server_stop_record.py",
        "tests/test_settings_store.py", "tests/test_setup_prepare.py",
        "tests/test_task_model_detail_document.py", "tests/test_telemetry.py",
        "tests/test_updater.py", "tests/test_watch.py", "tools/export_design_kit.py")),
    # Split phase 4: the front door -> moonglade.routes_gate. Readers of the moved text now read
    # it there: phone-back-layers.test.js (three of the four served shells' viewport metas) and
    # test_doc_truth_residuals (app_page()'s boot payload; /api/import-local's half stayed); the
    # absence and coverage readers the earlier moves widened (test_csrf_coverage,
    # test_catalog_verbs, test_telemetry, test_evidence_counters, test_settings_store,
    # test_catchup_query, test_artworks_adhoc, test_history_feed_document, test_first_party_sources)
    # read routes_gate too. The rest read code that did not move (main, _LOOM_SHELL, the palettes
    # and DESIGN_TOKENS_CSS, the scheduler and the watch, create_app's setup and its other
    # closures), or reach the moved code through a built app, not its text.
    *((_r, "moonglade.routes_gate") for _r in (
        "loom/test/mg-art-filters.test.js", "loom/test/mg-notify-queue-phase.test.js",
        "loom/test/mg-notify-website-source.test.js", "loom/test/phone-back-layers.test.js",
        "tests/test_app_paths.py", "tests/test_artworks_adhoc.py", "tests/test_bonjour.py",
        "tests/test_branding.py", "tests/test_branding_tree_rules.py", "tests/test_catalog_verbs.py",
        "tests/test_catchup_query.py", "tests/test_contest_wins.py", "tests/test_csrf_coverage.py",
        "tests/test_design_kit_sync.py", "tests/test_doc_truth_residuals.py",
        "tests/test_evidence_counters.py", "tests/test_first_party_sources.py",
        "tests/test_history_feed_document.py", "tests/test_jwt.py", "tests/test_library_dir.py",
        "tests/test_living_library.py", "tests/test_logging.py", "tests/test_loom_notify.py",
        "tests/test_loom_p_routes.py", "tests/test_move_edges.py", "tests/test_network.py",
        "tests/test_outside_notice.py", "tests/test_pack_file_name.py",
        "tests/test_pack_file_type.py", "tests/test_panel.py",
        "tests/test_rest_delete_and_renewal.py", "tests/test_security_review_fixes.py",
        "tests/test_server_one_module.py", "tests/test_server_stop_record.py",
        "tests/test_settings_store.py", "tests/test_setup_prepare.py",
        "tests/test_task_model_detail_document.py", "tests/test_telemetry.py",
        "tests/test_updater.py", "tests/test_watch.py", "tools/export_design_kit.py")),
    # Split phase 4: the background block -> moonglade.web_threads. Readers of the moved text now
    # read it there: test_watch (the mirror's collect branch, the catch-up), test_contest_wins,
    # test_jwt, test_panel, test_rest_delete_and_renewal and test_updater (the scheduler loop and
    # its ticks), mg-notify-website-source.test.js (the website-run labels; _LOOM_SHELL stayed),
    # and test_living_library, whose pins read create_app and web_threads together;
    # test_outside_notice's "create_app never starts it" covers the moved block too; the absence
    # and coverage readers the earlier moves widened read web_threads too. The rest read code that
    # did not move (main, _LOOM_SHELL, the palettes and DESIGN_TOKENS_CSS, the routes, create_app's
    # setup), or reach the moved code through a built app, not its text.
    *((_r, "moonglade.web_threads") for _r in (
        "loom/test/mg-art-filters.test.js", "loom/test/mg-notify-queue-phase.test.js",
        "loom/test/mg-notify-website-source.test.js", "loom/test/phone-back-layers.test.js",
        "tests/test_app_paths.py", "tests/test_artworks_adhoc.py", "tests/test_bonjour.py",
        "tests/test_branding.py", "tests/test_branding_tree_rules.py",
        "tests/test_catalog_verbs.py", "tests/test_catchup_query.py", "tests/test_csrf_coverage.py",
        "tests/test_design_kit_sync.py", "tests/test_doc_truth_residuals.py",
        "tests/test_enhance.py", "tests/test_evidence_counters.py",
        "tests/test_first_party_sources.py", "tests/test_history_feed_document.py",
        "tests/test_library_dir.py", "tests/test_living_library.py", "tests/test_logging.py",
        "tests/test_loom_notify.py", "tests/test_loom_p_routes.py", "tests/test_media_tools.py",
        "tests/test_module_seams.py", "tests/test_move_edges.py", "tests/test_network.py",
        "tests/test_outside_notice.py", "tests/test_pack_file_name.py",
        "tests/test_pack_file_type.py", "tests/test_rest_delete_and_renewal.py",
        "tests/test_security_review_fixes.py", "tests/test_server_one_module.py",
        "tests/test_server_stop_record.py", "tests/test_settings_store.py",
        "tests/test_setup_prepare.py", "tests/test_task_model_detail_document.py",
        "tests/test_telemetry.py", "tests/test_tsubaki3_image_gate.py", "tests/test_updater.py",
        "tools/export_design_kit.py", "tools/split_names.py")),
    # Split phase 4: the Control Panel's routes -> moonglade.routes_panel. Readers of the moved text
    # now read it there: test_library_dir (api_library_path), test_server_stop_record and
    # test_updater (the update's own restart), and test_living_library, whose pins read create_app,
    # web_threads and routes_panel together; the absence and coverage readers the earlier moves
    # widened (test_csrf_coverage among them, for the panel's POST routes) read routes_panel too.
    # The rest read code that did not move, name the panel's routes only as URLs they request, or
    # reach the moved code through a built app, not its text.
    *((_r, "moonglade.routes_panel") for _r in (
        "loom/test/mg-art-filters.test.js", "loom/test/mg-notify-queue-phase.test.js",
        "loom/test/mg-notify-website-source.test.js", "loom/test/phone-back-layers.test.js",
        "tests/test_app_paths.py", "tests/test_artworks_adhoc.py", "tests/test_bonjour.py",
        "tests/test_branding.py", "tests/test_branding_tree_rules.py",
        "tests/test_catalog_verbs.py", "tests/test_catchup_query.py", "tests/test_csrf_coverage.py",
        "tests/test_design_kit_sync.py", "tests/test_doc_truth_residuals.py",
        "tests/test_enhance.py", "tests/test_evidence_counters.py",
        "tests/test_first_party_sources.py", "tests/test_history_feed_document.py",
        "tests/test_living_library.py", "tests/test_logging.py", "tests/test_loom_notify.py",
        "tests/test_loom_p_routes.py", "tests/test_media_tools.py", "tests/test_module_seams.py",
        "tests/test_move_edges.py", "tests/test_network.py", "tests/test_outside_notice.py",
        "tests/test_pack_file_name.py", "tests/test_pack_file_type.py",
        "tests/test_rest_delete_and_renewal.py", "tests/test_security_review_fixes.py",
        "tests/test_server_one_module.py", "tests/test_server_stop_record.py",
        "tests/test_settings_store.py", "tests/test_setup_prepare.py",
        "tests/test_task_model_detail_document.py", "tests/test_telemetry.py",
        "tests/test_tsubaki3_image_gate.py", "tools/export_design_kit.py", "tools/split_names.py")),
    # Split phase 4: the delete routes -> moonglade.routes_delete. No reader slices the moved text
    # out of gallery by name; the absence and coverage readers the earlier moves widened
    # (test_csrf_coverage among them, for the delete routes' POSTs) read routes_delete too. The
    # rest read code that did not move, name the delete routes only as URLs they request, or reach
    # the moved code through a built app, not its text.
    *((_r, "moonglade.routes_delete") for _r in (
        "loom/test/mg-art-filters.test.js", "loom/test/mg-notify-queue-phase.test.js",
        "loom/test/mg-notify-website-source.test.js", "loom/test/phone-back-layers.test.js",
        "tests/test_app_paths.py", "tests/test_artworks_adhoc.py", "tests/test_bonjour.py",
        "tests/test_branding.py", "tests/test_branding_tree_rules.py",
        "tests/test_catalog_verbs.py", "tests/test_catchup_query.py", "tests/test_csrf_coverage.py",
        "tests/test_design_kit_sync.py", "tests/test_doc_truth_residuals.py",
        "tests/test_enhance.py", "tests/test_evidence_counters.py",
        "tests/test_first_party_sources.py", "tests/test_history_feed_document.py",
        "tests/test_living_library.py", "tests/test_logging.py", "tests/test_loom_notify.py",
        "tests/test_loom_p_routes.py", "tests/test_media_tools.py", "tests/test_module_seams.py",
        "tests/test_move_edges.py", "tests/test_network.py", "tests/test_outside_notice.py",
        "tests/test_pack_file_name.py", "tests/test_pack_file_type.py",
        "tests/test_rest_delete_and_renewal.py", "tests/test_security_review_fixes.py",
        "tests/test_server_one_module.py", "tests/test_server_stop_record.py",
        "tests/test_settings_store.py", "tests/test_setup_prepare.py",
        "tests/test_task_model_detail_document.py", "tests/test_telemetry.py",
        "tests/test_tsubaki3_image_gate.py", "tools/export_design_kit.py", "tools/split_names.py")),
    # Split phase 4: the recipe market and the Saved tab -> moonglade.routes_recipes. No reader
    # slices the moved text out of gallery by name; the absence and coverage readers the earlier
    # moves widened (test_csrf_coverage among them, for the recipe and Saved writes) read
    # routes_recipes too. The rest read code that did not move, name these routes only as URLs
    # they request, or reach the moved code through a built app, not its text.
    *((_r, "moonglade.routes_recipes") for _r in (
        "loom/test/mg-art-filters.test.js", "loom/test/mg-notify-queue-phase.test.js",
        "loom/test/mg-notify-website-source.test.js", "loom/test/phone-back-layers.test.js",
        "tests/test_app_paths.py", "tests/test_artworks_adhoc.py", "tests/test_bonjour.py",
        "tests/test_branding.py", "tests/test_branding_tree_rules.py",
        "tests/test_catalog_verbs.py", "tests/test_catchup_query.py", "tests/test_csrf_coverage.py",
        "tests/test_design_kit_sync.py", "tests/test_doc_truth_residuals.py",
        "tests/test_enhance.py", "tests/test_evidence_counters.py",
        "tests/test_first_party_sources.py", "tests/test_history_feed_document.py",
        "tests/test_living_library.py", "tests/test_logging.py", "tests/test_loom_notify.py",
        "tests/test_loom_p_routes.py", "tests/test_media_tools.py", "tests/test_module_seams.py",
        "tests/test_move_edges.py", "tests/test_network.py", "tests/test_outside_notice.py",
        "tests/test_pack_file_name.py", "tests/test_pack_file_type.py",
        "tests/test_rest_delete_and_renewal.py", "tests/test_security_review_fixes.py",
        "tests/test_server_one_module.py", "tests/test_server_stop_record.py",
        "tests/test_settings_store.py", "tests/test_setup_prepare.py",
        "tests/test_task_model_detail_document.py", "tests/test_telemetry.py",
        "tests/test_tsubaki3_image_gate.py", "tools/export_design_kit.py", "tools/split_names.py")),
    # Split phase 4: the library's routes -> moonglade.routes_library. test_loom_p_routes' walk
    # of the Loom's helpers reads routes_library too, for _loom_complete_clip, which went with
    # the library's routes; the absence and coverage readers the earlier moves widened
    # (test_csrf_coverage among them, for the library's POSTs, and test_catalog_verbs' no-SQL
    # guard) read routes_library too. The rest read code that did not move, name these routes
    # only as URLs they request, or reach the moved code through a built app, not its text.
    *((_r, "moonglade.routes_library") for _r in (
        "loom/test/mg-art-filters.test.js", "loom/test/mg-notify-queue-phase.test.js",
        "loom/test/mg-notify-website-source.test.js", "loom/test/phone-back-layers.test.js",
        "tests/test_app_paths.py", "tests/test_artworks_adhoc.py", "tests/test_bonjour.py",
        "tests/test_branding.py", "tests/test_branding_tree_rules.py",
        "tests/test_catalog_verbs.py", "tests/test_catchup_query.py", "tests/test_csrf_coverage.py",
        "tests/test_design_kit_sync.py", "tests/test_doc_truth_residuals.py",
        "tests/test_enhance.py", "tests/test_evidence_counters.py",
        "tests/test_first_party_sources.py", "tests/test_history_feed_document.py",
        "tests/test_living_library.py", "tests/test_logging.py", "tests/test_loom_notify.py",
        "tests/test_loom_p_routes.py", "tests/test_media_tools.py", "tests/test_module_seams.py",
        "tests/test_move_edges.py", "tests/test_network.py", "tests/test_outside_notice.py",
        "tests/test_pack_file_name.py", "tests/test_pack_file_type.py",
        "tests/test_rest_delete_and_renewal.py", "tests/test_security_review_fixes.py",
        "tests/test_server_one_module.py", "tests/test_server_stop_record.py",
        "tests/test_settings_store.py", "tests/test_setup_prepare.py",
        "tests/test_task_model_detail_document.py", "tests/test_telemetry.py",
        "tests/test_tsubaki3_image_gate.py", "tools/export_design_kit.py", "tools/split_names.py")),
    # Split phase 4: the account's routes -> moonglade.routes_account. No reader slices the moved
    # text out of gallery by name; the absence and coverage readers the earlier moves widened
    # (test_csrf_coverage among them, for the snippet, preset, saved-view and preference writes,
    # and test_catalog_verbs' no-SQL guard) read routes_account too. The rest read code that did
    # not move, name these routes only as URLs they request, or reach the moved code through a
    # built app, not its text.
    *((_r, "moonglade.routes_account") for _r in (
        "loom/test/mg-art-filters.test.js", "loom/test/mg-notify-queue-phase.test.js",
        "loom/test/mg-notify-website-source.test.js", "loom/test/phone-back-layers.test.js",
        "tests/test_app_paths.py", "tests/test_artworks_adhoc.py", "tests/test_bonjour.py",
        "tests/test_branding.py", "tests/test_branding_tree_rules.py",
        "tests/test_catalog_verbs.py", "tests/test_catchup_query.py",
        "tests/test_csrf_coverage.py", "tests/test_design_kit_sync.py",
        "tests/test_doc_truth_residuals.py", "tests/test_evidence_counters.py",
        "tests/test_first_party_sources.py", "tests/test_history_feed_document.py",
        "tests/test_living_library.py", "tests/test_logging.py", "tests/test_loom_notify.py",
        "tests/test_loom_p_routes.py", "tests/test_move_edges.py", "tests/test_network.py",
        "tests/test_outside_notice.py", "tests/test_pack_file_name.py",
        "tests/test_pack_file_type.py", "tests/test_security_review_fixes.py",
        "tests/test_server_one_module.py", "tests/test_server_stop_record.py",
        "tests/test_settings_store.py", "tests/test_setup_prepare.py",
        "tests/test_task_model_detail_document.py", "tests/test_telemetry.py",
        "tools/export_design_kit.py")),
    # Split phase 4: the community routes -> moonglade.routes_community. test_living_library's
    # _app_src reads routes_community too, for the pins that slice My Art's publish out by name
    # (api_myart_publish up to _lineage_card, and the artworks kick inside it); the absence and
    # coverage readers the earlier moves widened (test_csrf_coverage among them, for the contest,
    # My Art, inbox, comment and gift writes, and test_catalog_verbs' no-SQL guard) read
    # routes_community too. The rest read code that did not move, name these routes only as URLs
    # they request, or reach the moved code through a built app, not its text.
    *((_r, "moonglade.routes_community") for _r in (
        "loom/test/mg-art-filters.test.js", "loom/test/mg-notify-queue-phase.test.js",
        "loom/test/mg-notify-website-source.test.js", "loom/test/phone-back-layers.test.js",
        "tests/test_app_paths.py", "tests/test_artworks_adhoc.py", "tests/test_bonjour.py",
        "tests/test_branding.py", "tests/test_branding_tree_rules.py",
        "tests/test_catalog_verbs.py", "tests/test_catchup_query.py",
        "tests/test_csrf_coverage.py", "tests/test_design_kit_sync.py",
        "tests/test_doc_truth_residuals.py", "tests/test_evidence_counters.py",
        "tests/test_first_party_sources.py", "tests/test_history_feed_document.py",
        "tests/test_living_library.py", "tests/test_logging.py", "tests/test_loom_notify.py",
        "tests/test_loom_p_routes.py", "tests/test_move_edges.py", "tests/test_network.py",
        "tests/test_outside_notice.py", "tests/test_pack_file_name.py",
        "tests/test_pack_file_type.py", "tests/test_security_review_fixes.py",
        "tests/test_server_one_module.py", "tests/test_server_stop_record.py",
        "tests/test_settings_store.py", "tests/test_setup_prepare.py",
        "tests/test_task_model_detail_document.py", "tests/test_telemetry.py",
        "tools/export_design_kit.py")),
    # Split phase 4: LoRA training's routes -> moonglade.routes_train. No reader slices the moved
    # text out of gallery by name; the absence and coverage readers the earlier moves widened
    # (test_csrf_coverage among them, whose walk follows /api/train/submit through
    # _train_csrf_body, and test_catalog_verbs' no-SQL guard) read routes_train too. The rest read
    # code that did not move, name these routes only as URLs they request, or reach the moved code
    # through a built app, not its text; TrainGuard did not move.
    *((_r, "moonglade.routes_train") for _r in (
        "loom/test/mg-art-filters.test.js", "loom/test/mg-notify-queue-phase.test.js",
        "loom/test/mg-notify-website-source.test.js", "loom/test/phone-back-layers.test.js",
        "tests/test_app_paths.py", "tests/test_artworks_adhoc.py", "tests/test_bonjour.py",
        "tests/test_branding.py", "tests/test_branding_tree_rules.py",
        "tests/test_catalog_verbs.py", "tests/test_catchup_query.py",
        "tests/test_csrf_coverage.py", "tests/test_design_kit_sync.py",
        "tests/test_doc_truth_residuals.py", "tests/test_evidence_counters.py",
        "tests/test_first_party_sources.py", "tests/test_history_feed_document.py",
        "tests/test_living_library.py", "tests/test_logging.py", "tests/test_loom_notify.py",
        "tests/test_loom_p_routes.py", "tests/test_move_edges.py", "tests/test_network.py",
        "tests/test_outside_notice.py", "tests/test_pack_file_name.py",
        "tests/test_pack_file_type.py", "tests/test_security_review_fixes.py",
        "tests/test_server_one_module.py", "tests/test_server_stop_record.py",
        "tests/test_settings_store.py", "tests/test_setup_prepare.py",
        "tests/test_task_model_detail_document.py", "tests/test_telemetry.py",
        "tools/export_design_kit.py")),
    # Split phase 4: the achievement routes -> moonglade.routes_ach. test_evidence_counters'
    # pin that slices api_achievements out by name reads routes_ach.register now; the absence
    # and coverage readers the earlier moves widened (test_csrf_coverage among them, whose walk
    # checks the narrator's poke, and test_catalog_verbs' no-SQL guard) read routes_ach too. The
    # rest read code that did not move (the nonce tables and the skin palettes stay in gallery),
    # name these routes only as URLs they request, or reach the moved code through a built app,
    # not its text.
    *((_r, "moonglade.routes_ach") for _r in (
        "loom/test/mg-art-filters.test.js", "loom/test/mg-notify-queue-phase.test.js",
        "loom/test/mg-notify-website-source.test.js", "loom/test/phone-back-layers.test.js",
        "tests/test_app_paths.py", "tests/test_artworks_adhoc.py", "tests/test_bonjour.py",
        "tests/test_branding.py", "tests/test_branding_tree_rules.py",
        "tests/test_catalog_verbs.py", "tests/test_catchup_query.py",
        "tests/test_csrf_coverage.py", "tests/test_design_kit_sync.py",
        "tests/test_doc_truth_residuals.py", "tests/test_evidence_counters.py",
        "tests/test_first_party_sources.py", "tests/test_history_feed_document.py",
        "tests/test_living_library.py", "tests/test_logging.py", "tests/test_loom_notify.py",
        "tests/test_loom_p_routes.py", "tests/test_move_edges.py", "tests/test_network.py",
        "tests/test_outside_notice.py", "tests/test_pack_file_name.py",
        "tests/test_pack_file_type.py", "tests/test_security_review_fixes.py",
        "tests/test_server_one_module.py", "tests/test_server_stop_record.py",
        "tests/test_settings_store.py", "tests/test_setup_prepare.py",
        "tests/test_task_model_detail_document.py", "tests/test_telemetry.py",
        "tools/export_design_kit.py")),
    # Split phase 4: the Mirror's routes -> moonglade.routes_mirror. No reader slices the
    # moved text out of gallery by name; the absence and coverage readers the earlier moves
    # widened (test_csrf_coverage among them, whose walk follows Connect, Disconnect and the
    # Connect from PixAI token, and test_settings_store's guard that no writer puts the switch
    # back in config.json) read routes_mirror too. The rest read code that did not move (the
    # sign-in and its renewal are moonglade.mirror's), name these routes only as URLs they
    # request, or reach the moved code through a built app, not its text.
    *((_r, "moonglade.routes_mirror") for _r in (
        "loom/test/mg-art-filters.test.js", "loom/test/mg-notify-queue-phase.test.js",
        "loom/test/mg-notify-website-source.test.js", "loom/test/phone-back-layers.test.js",
        "tests/test_app_paths.py", "tests/test_artworks_adhoc.py", "tests/test_bonjour.py",
        "tests/test_branding.py", "tests/test_branding_tree_rules.py",
        "tests/test_catalog_verbs.py", "tests/test_catchup_query.py",
        "tests/test_csrf_coverage.py", "tests/test_design_kit_sync.py",
        "tests/test_doc_truth_residuals.py", "tests/test_evidence_counters.py",
        "tests/test_first_party_sources.py", "tests/test_history_feed_document.py",
        "tests/test_living_library.py", "tests/test_logging.py", "tests/test_loom_notify.py",
        "tests/test_loom_p_routes.py", "tests/test_move_edges.py", "tests/test_network.py",
        "tests/test_outside_notice.py", "tests/test_pack_file_name.py",
        "tests/test_pack_file_type.py", "tests/test_security_review_fixes.py",
        "tests/test_server_one_module.py", "tests/test_server_stop_record.py",
        "tests/test_settings_store.py", "tests/test_setup_prepare.py",
        "tests/test_task_model_detail_document.py", "tests/test_telemetry.py",
        "tools/export_design_kit.py")),
    # Split phase 4: the branding routes -> moonglade.routes_branding. No reader slices the
    # moved text out of gallery by name; the absence and coverage readers the earlier moves
    # widened (test_csrf_coverage among them, whose token walk reads every handler's syntax
    # tree, and test_catalog_verbs' no-SQL guard) read routes_branding too. The rest read code
    # that did not move (main(), the shortcut's icon bytes and the branding module itself), name
    # these routes only as URLs they request, or reach the moved code through a built app, not
    # its text.
    *((_r, "moonglade.routes_branding") for _r in (
        "loom/test/mg-art-filters.test.js", "loom/test/mg-notify-queue-phase.test.js",
        "loom/test/mg-notify-website-source.test.js", "loom/test/phone-back-layers.test.js",
        "tests/test_app_paths.py", "tests/test_artworks_adhoc.py", "tests/test_bonjour.py",
        "tests/test_branding.py", "tests/test_branding_tree_rules.py",
        "tests/test_catalog_verbs.py", "tests/test_catchup_query.py",
        "tests/test_csrf_coverage.py", "tests/test_design_kit_sync.py",
        "tests/test_doc_truth_residuals.py", "tests/test_evidence_counters.py",
        "tests/test_first_party_sources.py", "tests/test_history_feed_document.py",
        "tests/test_living_library.py", "tests/test_logging.py", "tests/test_loom_notify.py",
        "tests/test_loom_p_routes.py", "tests/test_move_edges.py", "tests/test_network.py",
        "tests/test_outside_notice.py", "tests/test_pack_file_name.py",
        "tests/test_pack_file_type.py", "tests/test_security_review_fixes.py",
        "tests/test_server_one_module.py", "tests/test_server_stop_record.py",
        "tests/test_settings_store.py", "tests/test_setup_prepare.py",
        "tests/test_task_model_detail_document.py", "tests/test_telemetry.py",
        "tools/export_design_kit.py")),
    # Split phase 4: the import routes -> moonglade.routes_import. Three readers slice the moved
    # text and read routes_import now: test_doc_truth_residuals (the /api/import-local tier pin;
    # it read gallery.py for nothing else, so it left SOURCE_READERS above and is not listed here),
    # test_security_review_fixes (the upload and import request caps, sliced by def name) and
    # test_outside_notice (create_app never primes the outside look; its Fix them route's module
    # is read beside it). The absence and coverage readers the earlier moves widened
    # (test_csrf_coverage and test_catalog_verbs' no-SQL guard among them) read routes_import too.
    # The rest read code that did not move (main(), the zip caps, the outside scan), name these
    # routes only as URLs they request, or reach the moved code through a built app, not its text
    # (test_security_review_fixes' _safe_extract_zip closure lookup is one of those).
    *((_r, "moonglade.routes_import") for _r in (
        "loom/test/mg-art-filters.test.js", "loom/test/mg-notify-queue-phase.test.js",
        "loom/test/mg-notify-website-source.test.js", "loom/test/phone-back-layers.test.js",
        "tests/test_app_paths.py", "tests/test_artworks_adhoc.py", "tests/test_bonjour.py",
        "tests/test_branding.py", "tests/test_branding_tree_rules.py",
        "tests/test_catalog_verbs.py", "tests/test_catchup_query.py",
        "tests/test_csrf_coverage.py", "tests/test_design_kit_sync.py",
        "tests/test_evidence_counters.py",
        "tests/test_first_party_sources.py", "tests/test_history_feed_document.py",
        "tests/test_living_library.py", "tests/test_logging.py", "tests/test_loom_notify.py",
        "tests/test_loom_p_routes.py", "tests/test_move_edges.py", "tests/test_network.py",
        "tests/test_outside_notice.py", "tests/test_pack_file_name.py",
        "tests/test_pack_file_type.py", "tests/test_security_review_fixes.py",
        "tests/test_server_one_module.py", "tests/test_server_stop_record.py",
        "tests/test_settings_store.py", "tests/test_setup_prepare.py",
        "tests/test_task_model_detail_document.py", "tests/test_telemetry.py",
        "tools/export_design_kit.py")),
    # Split phase 4, redact: no reader reads text that left gallery.py (no reader names the
    # redactor or its pattern; test_task_params reaches it through moonglade.redact).
    ('loom/test/mg-art-filters.test.js', 'moonglade.redact'),
    ('loom/test/mg-notify-queue-phase.test.js', 'moonglade.redact'),
    ('loom/test/mg-notify-website-source.test.js', 'moonglade.redact'),
    ('loom/test/phone-back-layers.test.js', 'moonglade.redact'),
    ('tests/test_app_paths.py', 'moonglade.redact'),
    ('tests/test_artworks_adhoc.py', 'moonglade.redact'),
    ('tests/test_bonjour.py', 'moonglade.redact'),
    ('tests/test_branding.py', 'moonglade.redact'),
    ('tests/test_catalog_verbs.py', 'moonglade.redact'),
    ('tests/test_catchup_query.py', 'moonglade.redact'),
    ('tests/test_csrf_coverage.py', 'moonglade.redact'),
    ('tests/test_design_kit_sync.py', 'moonglade.redact'),
    ('tests/test_evidence_counters.py', 'moonglade.redact'),
    ('tests/test_first_party_sources.py', 'moonglade.redact'),
    ('tests/test_history_feed_document.py', 'moonglade.redact'),
    ('tests/test_living_library.py', 'moonglade.redact'),
    ('tests/test_logging.py', 'moonglade.redact'),
    ('tests/test_loom_notify.py', 'moonglade.redact'),
    ('tests/test_loom_p_routes.py', 'moonglade.redact'),
    ('tests/test_network.py', 'moonglade.redact'),
    ('tests/test_security_review_fixes.py', 'moonglade.redact'),
    ('tests/test_server_one_module.py', 'moonglade.redact'),
    ('tests/test_settings_store.py', 'moonglade.redact'),
    ('tests/test_setup_prepare.py', 'moonglade.redact'),
    ('tests/test_task_model_detail_document.py', 'moonglade.redact'),
    ('tests/test_telemetry.py', 'moonglade.redact'),
    ('tools/export_design_kit.py', 'moonglade.redact'),
    # Split phase 4, web_tiers: no reader reads the tier definitions; the readers that name a tier
    # name it in prose, a route's docstring or a payload, and test_route_tiers and
    # test_outside_notice reach the tier helpers through moonglade.web_tiers.
    ('loom/test/mg-art-filters.test.js', 'moonglade.web_tiers'),
    ('loom/test/mg-notify-queue-phase.test.js', 'moonglade.web_tiers'),
    ('loom/test/mg-notify-website-source.test.js', 'moonglade.web_tiers'),
    ('loom/test/phone-back-layers.test.js', 'moonglade.web_tiers'),
    ('tests/test_app_paths.py', 'moonglade.web_tiers'),
    ('tests/test_artworks_adhoc.py', 'moonglade.web_tiers'),
    ('tests/test_bonjour.py', 'moonglade.web_tiers'),
    ('tests/test_branding.py', 'moonglade.web_tiers'),
    ('tests/test_branding_tree_rules.py', 'moonglade.web_tiers'),
    ('tests/test_catalog_verbs.py', 'moonglade.web_tiers'),
    ('tests/test_catchup_query.py', 'moonglade.web_tiers'),
    ('tests/test_csrf_coverage.py', 'moonglade.web_tiers'),
    ('tests/test_design_kit_sync.py', 'moonglade.web_tiers'),
    ('tests/test_evidence_counters.py', 'moonglade.web_tiers'),
    ('tests/test_first_party_sources.py', 'moonglade.web_tiers'),
    ('tests/test_history_feed_document.py', 'moonglade.web_tiers'),
    ('tests/test_living_library.py', 'moonglade.web_tiers'),
    ('tests/test_logging.py', 'moonglade.web_tiers'),
    ('tests/test_loom_notify.py', 'moonglade.web_tiers'),
    ('tests/test_loom_p_routes.py', 'moonglade.web_tiers'),
    ('tests/test_network.py', 'moonglade.web_tiers'),
    ('tests/test_outside_notice.py', 'moonglade.web_tiers'),
    ('tests/test_security_review_fixes.py', 'moonglade.web_tiers'),
    ('tests/test_server_one_module.py', 'moonglade.web_tiers'),
    ('tests/test_settings_store.py', 'moonglade.web_tiers'),
    ('tests/test_setup_prepare.py', 'moonglade.web_tiers'),
    ('tests/test_task_model_detail_document.py', 'moonglade.web_tiers'),
    ('tests/test_telemetry.py', 'moonglade.web_tiers'),
    ('tools/export_design_kit.py', 'moonglade.web_tiers'),
    # Split phase 4, watch_plans: no reader reads the timing plans' text; test_watch reaches them
    # through moonglade.watch_plans, and web_threads imports them from there.
    ('loom/test/mg-art-filters.test.js', 'moonglade.watch_plans'),
    ('loom/test/mg-notify-queue-phase.test.js', 'moonglade.watch_plans'),
    ('loom/test/mg-notify-website-source.test.js', 'moonglade.watch_plans'),
    ('loom/test/phone-back-layers.test.js', 'moonglade.watch_plans'),
    ('tests/test_app_paths.py', 'moonglade.watch_plans'),
    ('tests/test_artworks_adhoc.py', 'moonglade.watch_plans'),
    ('tests/test_bonjour.py', 'moonglade.watch_plans'),
    ('tests/test_branding.py', 'moonglade.watch_plans'),
    ('tests/test_catalog_verbs.py', 'moonglade.watch_plans'),
    ('tests/test_catchup_query.py', 'moonglade.watch_plans'),
    ('tests/test_csrf_coverage.py', 'moonglade.watch_plans'),
    ('tests/test_design_kit_sync.py', 'moonglade.watch_plans'),
    ('tests/test_evidence_counters.py', 'moonglade.watch_plans'),
    ('tests/test_first_party_sources.py', 'moonglade.watch_plans'),
    ('tests/test_history_feed_document.py', 'moonglade.watch_plans'),
    ('tests/test_living_library.py', 'moonglade.watch_plans'),
    ('tests/test_logging.py', 'moonglade.watch_plans'),
    ('tests/test_loom_notify.py', 'moonglade.watch_plans'),
    ('tests/test_loom_p_routes.py', 'moonglade.watch_plans'),
    ('tests/test_network.py', 'moonglade.watch_plans'),
    ('tests/test_security_review_fixes.py', 'moonglade.watch_plans'),
    ('tests/test_server_one_module.py', 'moonglade.watch_plans'),
    ('tests/test_settings_store.py', 'moonglade.watch_plans'),
    ('tests/test_setup_prepare.py', 'moonglade.watch_plans'),
    ('tests/test_task_model_detail_document.py', 'moonglade.watch_plans'),
    ('tests/test_telemetry.py', 'moonglade.watch_plans'),
    ('tools/export_design_kit.py', 'moonglade.watch_plans'),
    # Split phase 4, name_hunt: no reader reads the hunt's text; routes_library imports it from
    # moonglade.name_hunt at call time.
    ('loom/test/mg-art-filters.test.js', 'moonglade.name_hunt'),
    ('loom/test/mg-notify-queue-phase.test.js', 'moonglade.name_hunt'),
    ('loom/test/mg-notify-website-source.test.js', 'moonglade.name_hunt'),
    ('loom/test/phone-back-layers.test.js', 'moonglade.name_hunt'),
    ('tests/test_app_paths.py', 'moonglade.name_hunt'),
    ('tests/test_artworks_adhoc.py', 'moonglade.name_hunt'),
    ('tests/test_bonjour.py', 'moonglade.name_hunt'),
    ('tests/test_branding.py', 'moonglade.name_hunt'),
    ('tests/test_catalog_verbs.py', 'moonglade.name_hunt'),
    ('tests/test_catchup_query.py', 'moonglade.name_hunt'),
    ('tests/test_csrf_coverage.py', 'moonglade.name_hunt'),
    ('tests/test_design_kit_sync.py', 'moonglade.name_hunt'),
    ('tests/test_evidence_counters.py', 'moonglade.name_hunt'),
    ('tests/test_first_party_sources.py', 'moonglade.name_hunt'),
    ('tests/test_history_feed_document.py', 'moonglade.name_hunt'),
    ('tests/test_living_library.py', 'moonglade.name_hunt'),
    ('tests/test_logging.py', 'moonglade.name_hunt'),
    ('tests/test_loom_notify.py', 'moonglade.name_hunt'),
    ('tests/test_loom_p_routes.py', 'moonglade.name_hunt'),
    ('tests/test_network.py', 'moonglade.name_hunt'),
    ('tests/test_security_review_fixes.py', 'moonglade.name_hunt'),
    ('tests/test_server_one_module.py', 'moonglade.name_hunt'),
    ('tests/test_settings_store.py', 'moonglade.name_hunt'),
    ('tests/test_setup_prepare.py', 'moonglade.name_hunt'),
    ('tests/test_task_model_detail_document.py', 'moonglade.name_hunt'),
    ('tests/test_telemetry.py', 'moonglade.name_hunt'),
    ('tools/export_design_kit.py', 'moonglade.name_hunt'),
    # Split phase 4, ach_beacon: no reader reads the beacon's text; test_telemetry's whole-module
    # read counts bridge_gen_tasks writers, which never sat in the beacon, and it reaches the
    # tables through moonglade.ach_beacon.
    ('loom/test/mg-art-filters.test.js', 'moonglade.ach_beacon'),
    ('loom/test/mg-notify-queue-phase.test.js', 'moonglade.ach_beacon'),
    ('loom/test/mg-notify-website-source.test.js', 'moonglade.ach_beacon'),
    ('loom/test/phone-back-layers.test.js', 'moonglade.ach_beacon'),
    ('tests/test_app_paths.py', 'moonglade.ach_beacon'),
    ('tests/test_artworks_adhoc.py', 'moonglade.ach_beacon'),
    ('tests/test_bonjour.py', 'moonglade.ach_beacon'),
    ('tests/test_branding.py', 'moonglade.ach_beacon'),
    ('tests/test_catalog_verbs.py', 'moonglade.ach_beacon'),
    ('tests/test_catchup_query.py', 'moonglade.ach_beacon'),
    ('tests/test_csrf_coverage.py', 'moonglade.ach_beacon'),
    ('tests/test_design_kit_sync.py', 'moonglade.ach_beacon'),
    ('tests/test_evidence_counters.py', 'moonglade.ach_beacon'),
    ('tests/test_first_party_sources.py', 'moonglade.ach_beacon'),
    ('tests/test_history_feed_document.py', 'moonglade.ach_beacon'),
    ('tests/test_living_library.py', 'moonglade.ach_beacon'),
    ('tests/test_logging.py', 'moonglade.ach_beacon'),
    ('tests/test_loom_notify.py', 'moonglade.ach_beacon'),
    ('tests/test_loom_p_routes.py', 'moonglade.ach_beacon'),
    ('tests/test_network.py', 'moonglade.ach_beacon'),
    ('tests/test_security_review_fixes.py', 'moonglade.ach_beacon'),
    ('tests/test_server_one_module.py', 'moonglade.ach_beacon'),
    ('tests/test_settings_store.py', 'moonglade.ach_beacon'),
    ('tests/test_setup_prepare.py', 'moonglade.ach_beacon'),
    ('tests/test_task_model_detail_document.py', 'moonglade.ach_beacon'),
    ('tests/test_telemetry.py', 'moonglade.ach_beacon'),
    ('tools/export_design_kit.py', 'moonglade.ach_beacon'),
    # Split phase 4, scenes: no reader reads the scene catalog's text (test_app_paths and
    # test_branding name branding_root only in patches); test_ai_tools_scenes reaches it through
    # moonglade.scenes.
    ('loom/test/mg-art-filters.test.js', 'moonglade.scenes'),
    ('loom/test/mg-notify-queue-phase.test.js', 'moonglade.scenes'),
    ('loom/test/mg-notify-website-source.test.js', 'moonglade.scenes'),
    ('loom/test/phone-back-layers.test.js', 'moonglade.scenes'),
    ('tests/test_app_paths.py', 'moonglade.scenes'),
    ('tests/test_artworks_adhoc.py', 'moonglade.scenes'),
    ('tests/test_bonjour.py', 'moonglade.scenes'),
    ('tests/test_branding.py', 'moonglade.scenes'),
    ('tests/test_catalog_verbs.py', 'moonglade.scenes'),
    ('tests/test_catchup_query.py', 'moonglade.scenes'),
    ('tests/test_csrf_coverage.py', 'moonglade.scenes'),
    ('tests/test_design_kit_sync.py', 'moonglade.scenes'),
    ('tests/test_evidence_counters.py', 'moonglade.scenes'),
    ('tests/test_first_party_sources.py', 'moonglade.scenes'),
    ('tests/test_history_feed_document.py', 'moonglade.scenes'),
    ('tests/test_living_library.py', 'moonglade.scenes'),
    ('tests/test_logging.py', 'moonglade.scenes'),
    ('tests/test_loom_notify.py', 'moonglade.scenes'),
    ('tests/test_loom_p_routes.py', 'moonglade.scenes'),
    ('tests/test_network.py', 'moonglade.scenes'),
    ('tests/test_security_review_fixes.py', 'moonglade.scenes'),
    ('tests/test_server_one_module.py', 'moonglade.scenes'),
    ('tests/test_settings_store.py', 'moonglade.scenes'),
    ('tests/test_setup_prepare.py', 'moonglade.scenes'),
    ('tests/test_task_model_detail_document.py', 'moonglade.scenes'),
    ('tests/test_telemetry.py', 'moonglade.scenes'),
    ('tools/export_design_kit.py', 'moonglade.scenes'),
    # Split phase 4, pages: the readers that read the moved text now read moonglade/pages.py: the
    # design kit's exporter and test_design_kit_sync (DESIGN_TOKENS_CSS by path; both leave
    # SOURCE_READERS), test_loom_notify's shell font check, and the node tests mg-art-filters,
    # mg-notify-queue-phase, mg-notify-website-source and phone-back-layers (each extracts the
    # tokens or _LOOM_SHELL and fails when it finds none). No other reader reads the shells' text.
    ('tests/test_app_paths.py', 'moonglade.pages'),
    ('tests/test_artworks_adhoc.py', 'moonglade.pages'),
    ('tests/test_bonjour.py', 'moonglade.pages'),
    ('tests/test_branding.py', 'moonglade.pages'),
    ('tests/test_catalog_verbs.py', 'moonglade.pages'),
    ('tests/test_catchup_query.py', 'moonglade.pages'),
    ('tests/test_csrf_coverage.py', 'moonglade.pages'),
    ('tests/test_evidence_counters.py', 'moonglade.pages'),
    ('tests/test_first_party_sources.py', 'moonglade.pages'),
    ('tests/test_history_feed_document.py', 'moonglade.pages'),
    ('tests/test_living_library.py', 'moonglade.pages'),
    ('tests/test_logging.py', 'moonglade.pages'),
    ('tests/test_loom_p_routes.py', 'moonglade.pages'),
    ('tests/test_network.py', 'moonglade.pages'),
    ('tests/test_security_review_fixes.py', 'moonglade.pages'),
    ('tests/test_server_one_module.py', 'moonglade.pages'),
    ('tests/test_settings_store.py', 'moonglade.pages'),
    ('tests/test_setup_prepare.py', 'moonglade.pages'),
    ('tests/test_task_model_detail_document.py', 'moonglade.pages'),
    ('tests/test_telemetry.py', 'moonglade.pages'),
    # Split phase 4, web_policy: no reader reads the moved text. test_security_review_fixes reads
    # gallery's main() and the import and Loom route sources, test_csrf_coverage the functions
    # that call _check_csrf; both reach the policy names through moonglade.web_policy.
    ('tests/test_app_paths.py', 'moonglade.web_policy'),
    ('tests/test_artworks_adhoc.py', 'moonglade.web_policy'),
    ('tests/test_bonjour.py', 'moonglade.web_policy'),
    ('tests/test_branding.py', 'moonglade.web_policy'),
    ('tests/test_catalog_verbs.py', 'moonglade.web_policy'),
    ('tests/test_catchup_query.py', 'moonglade.web_policy'),
    ('tests/test_csrf_coverage.py', 'moonglade.web_policy'),
    ('tests/test_evidence_counters.py', 'moonglade.web_policy'),
    ('tests/test_first_party_sources.py', 'moonglade.web_policy'),
    ('tests/test_history_feed_document.py', 'moonglade.web_policy'),
    ('tests/test_living_library.py', 'moonglade.web_policy'),
    ('tests/test_logging.py', 'moonglade.web_policy'),
    ('tests/test_loom_p_routes.py', 'moonglade.web_policy'),
    ('tests/test_network.py', 'moonglade.web_policy'),
    ('tests/test_security_review_fixes.py', 'moonglade.web_policy'),
    ('tests/test_server_one_module.py', 'moonglade.web_policy'),
    ('tests/test_settings_store.py', 'moonglade.web_policy'),
    ('tests/test_setup_prepare.py', 'moonglade.web_policy'),
    ('tests/test_task_model_detail_document.py', 'moonglade.web_policy'),
    ('tests/test_telemetry.py', 'moonglade.web_policy'),
    # Split phase 4, loom_files: no reader reads the moved text. test_loom_p_routes' AST walks look
    # for the Loom's route and store functions (none moved here) and its regex parity checks read
    # the compiled patterns through moonglade.loom_files.
    ('tests/test_app_paths.py', 'moonglade.loom_files'),
    ('tests/test_artworks_adhoc.py', 'moonglade.loom_files'),
    ('tests/test_bonjour.py', 'moonglade.loom_files'),
    ('tests/test_branding.py', 'moonglade.loom_files'),
    ('tests/test_catalog_verbs.py', 'moonglade.loom_files'),
    ('tests/test_catchup_query.py', 'moonglade.loom_files'),
    ('tests/test_csrf_coverage.py', 'moonglade.loom_files'),
    ('tests/test_evidence_counters.py', 'moonglade.loom_files'),
    ('tests/test_first_party_sources.py', 'moonglade.loom_files'),
    ('tests/test_history_feed_document.py', 'moonglade.loom_files'),
    ('tests/test_living_library.py', 'moonglade.loom_files'),
    ('tests/test_logging.py', 'moonglade.loom_files'),
    ('tests/test_loom_p_routes.py', 'moonglade.loom_files'),
    ('tests/test_network.py', 'moonglade.loom_files'),
    ('tests/test_security_review_fixes.py', 'moonglade.loom_files'),
    ('tests/test_server_one_module.py', 'moonglade.loom_files'),
    ('tests/test_settings_store.py', 'moonglade.loom_files'),
    ('tests/test_setup_prepare.py', 'moonglade.loom_files'),
    ('tests/test_task_model_detail_document.py', 'moonglade.loom_files'),
    ('tests/test_telemetry.py', 'moonglade.loom_files'),
    # Split phase 4, catalog_search: no reader reads the operators' text (the hits are catalog
    # column names; test_catalog_verbs reads create_app and the registers only).
    # test_search_operators reaches the grammar through moonglade.catalog_search.
    ('tests/test_app_paths.py', 'moonglade.catalog_search'),
    ('tests/test_artworks_adhoc.py', 'moonglade.catalog_search'),
    ('tests/test_bonjour.py', 'moonglade.catalog_search'),
    ('tests/test_branding.py', 'moonglade.catalog_search'),
    ('tests/test_catalog_verbs.py', 'moonglade.catalog_search'),
    ('tests/test_catchup_query.py', 'moonglade.catalog_search'),
    ('tests/test_csrf_coverage.py', 'moonglade.catalog_search'),
    ('tests/test_evidence_counters.py', 'moonglade.catalog_search'),
    ('tests/test_first_party_sources.py', 'moonglade.catalog_search'),
    ('tests/test_history_feed_document.py', 'moonglade.catalog_search'),
    ('tests/test_living_library.py', 'moonglade.catalog_search'),
    ('tests/test_logging.py', 'moonglade.catalog_search'),
    ('tests/test_loom_p_routes.py', 'moonglade.catalog_search'),
    ('tests/test_network.py', 'moonglade.catalog_search'),
    ('tests/test_security_review_fixes.py', 'moonglade.catalog_search'),
    ('tests/test_server_one_module.py', 'moonglade.catalog_search'),
    ('tests/test_settings_store.py', 'moonglade.catalog_search'),
    ('tests/test_setup_prepare.py', 'moonglade.catalog_search'),
    ('tests/test_task_model_detail_document.py', 'moonglade.catalog_search'),
    ('tests/test_telemetry.py', 'moonglade.catalog_search'),
    # Split phase 4, catalog: no reader reads the catalog helpers' text; the hits are column names,
    # the readers' own fixtures and main()/create_app reads. The whole-module absence guards
    # (test_settings_store, test_catchup_query, test_evidence_counters; test_telemetry's writer
    # count) now also read the modules split out of gallery's top level, this one included.
    ('tests/test_app_paths.py', 'moonglade.catalog'),
    ('tests/test_artworks_adhoc.py', 'moonglade.catalog'),
    ('tests/test_bonjour.py', 'moonglade.catalog'),
    ('tests/test_branding.py', 'moonglade.catalog'),
    ('tests/test_branding_tree_rules.py', 'moonglade.catalog'),
    ('tests/test_catalog_verbs.py', 'moonglade.catalog'),
    ('tests/test_catchup_query.py', 'moonglade.catalog'),
    ('tests/test_csrf_coverage.py', 'moonglade.catalog'),
    ('tests/test_evidence_counters.py', 'moonglade.catalog'),
    ('tests/test_first_party_sources.py', 'moonglade.catalog'),
    ('tests/test_history_feed_document.py', 'moonglade.catalog'),
    ('tests/test_living_library.py', 'moonglade.catalog'),
    ('tests/test_logging.py', 'moonglade.catalog'),
    ('tests/test_loom_p_routes.py', 'moonglade.catalog'),
    ('tests/test_move_edges.py', 'moonglade.catalog'),
    ('tests/test_network.py', 'moonglade.catalog'),
    ('tests/test_pack_file_name.py', 'moonglade.catalog'),
    ('tests/test_security_review_fixes.py', 'moonglade.catalog'),
    ('tests/test_server_one_module.py', 'moonglade.catalog'),
    ('tests/test_server_stop_record.py', 'moonglade.catalog'),
    ('tests/test_settings_store.py', 'moonglade.catalog'),
    ('tests/test_setup_prepare.py', 'moonglade.catalog'),
    ('tests/test_task_model_detail_document.py', 'moonglade.catalog'),
    ('tests/test_telemetry.py', 'moonglade.catalog'),
    # Split phase 4, curation: no reader reads the curation text; test_living_library's banned-call
    # guard reads living's functions and the scheduler blocks, not this section. The whole-module
    # absence guards read moonglade.curation too.
    ('tests/test_app_paths.py', 'moonglade.curation'),
    ('tests/test_artworks_adhoc.py', 'moonglade.curation'),
    ('tests/test_bonjour.py', 'moonglade.curation'),
    ('tests/test_branding.py', 'moonglade.curation'),
    ('tests/test_catalog_verbs.py', 'moonglade.curation'),
    ('tests/test_catchup_query.py', 'moonglade.curation'),
    ('tests/test_csrf_coverage.py', 'moonglade.curation'),
    ('tests/test_evidence_counters.py', 'moonglade.curation'),
    ('tests/test_first_party_sources.py', 'moonglade.curation'),
    ('tests/test_history_feed_document.py', 'moonglade.curation'),
    ('tests/test_living_library.py', 'moonglade.curation'),
    ('tests/test_logging.py', 'moonglade.curation'),
    ('tests/test_loom_p_routes.py', 'moonglade.curation'),
    ('tests/test_network.py', 'moonglade.curation'),
    ('tests/test_security_review_fixes.py', 'moonglade.curation'),
    ('tests/test_server_one_module.py', 'moonglade.curation'),
    ('tests/test_settings_store.py', 'moonglade.curation'),
    ('tests/test_setup_prepare.py', 'moonglade.curation'),
    ('tests/test_task_model_detail_document.py', 'moonglade.curation'),
    ('tests/test_telemetry.py', 'moonglade.curation'),
    # Split phase 4, train_guard: no reader reads TrainGuard's text (test_setup_prepare names
    # train_guard.json as a records file); the whole-module absence guards read it too.
    ('tests/test_app_paths.py', 'moonglade.train_guard'),
    ('tests/test_artworks_adhoc.py', 'moonglade.train_guard'),
    ('tests/test_bonjour.py', 'moonglade.train_guard'),
    ('tests/test_branding.py', 'moonglade.train_guard'),
    ('tests/test_catalog_verbs.py', 'moonglade.train_guard'),
    ('tests/test_catchup_query.py', 'moonglade.train_guard'),
    ('tests/test_csrf_coverage.py', 'moonglade.train_guard'),
    ('tests/test_evidence_counters.py', 'moonglade.train_guard'),
    ('tests/test_first_party_sources.py', 'moonglade.train_guard'),
    ('tests/test_history_feed_document.py', 'moonglade.train_guard'),
    ('tests/test_living_library.py', 'moonglade.train_guard'),
    ('tests/test_logging.py', 'moonglade.train_guard'),
    ('tests/test_loom_p_routes.py', 'moonglade.train_guard'),
    ('tests/test_network.py', 'moonglade.train_guard'),
    ('tests/test_security_review_fixes.py', 'moonglade.train_guard'),
    ('tests/test_server_one_module.py', 'moonglade.train_guard'),
    ('tests/test_settings_store.py', 'moonglade.train_guard'),
    ('tests/test_setup_prepare.py', 'moonglade.train_guard'),
    ('tests/test_task_model_detail_document.py', 'moonglade.train_guard'),
    ('tests/test_telemetry.py', 'moonglade.train_guard'),
    # Split phase 4, catalog_verbs: no reader reads the verbs' text. test_catalog_verbs names the
    # verbs but reads create_app and the registers (its no-SQL guard); test_living_library's
    # banned-call guard reads apply_artwork_meta through catalog_verbs_mod; the history_page hits
    # are backup's retired feed. The whole-module absence guards read the module too.
    ('tests/test_app_paths.py', 'moonglade.catalog_verbs'),
    ('tests/test_artworks_adhoc.py', 'moonglade.catalog_verbs'),
    ('tests/test_bonjour.py', 'moonglade.catalog_verbs'),
    ('tests/test_branding.py', 'moonglade.catalog_verbs'),
    ('tests/test_catalog_verbs.py', 'moonglade.catalog_verbs'),
    ('tests/test_catchup_query.py', 'moonglade.catalog_verbs'),
    ('tests/test_csrf_coverage.py', 'moonglade.catalog_verbs'),
    ('tests/test_evidence_counters.py', 'moonglade.catalog_verbs'),
    ('tests/test_first_party_sources.py', 'moonglade.catalog_verbs'),
    ('tests/test_history_feed_document.py', 'moonglade.catalog_verbs'),
    ('tests/test_living_library.py', 'moonglade.catalog_verbs'),
    ('tests/test_logging.py', 'moonglade.catalog_verbs'),
    ('tests/test_loom_p_routes.py', 'moonglade.catalog_verbs'),
    ('tests/test_network.py', 'moonglade.catalog_verbs'),
    ('tests/test_security_review_fixes.py', 'moonglade.catalog_verbs'),
    ('tests/test_server_one_module.py', 'moonglade.catalog_verbs'),
    ('tests/test_settings_store.py', 'moonglade.catalog_verbs'),
    ('tests/test_setup_prepare.py', 'moonglade.catalog_verbs'),
    ('tests/test_task_model_detail_document.py', 'moonglade.catalog_verbs'),
    ('tests/test_telemetry.py', 'moonglade.catalog_verbs'),
    # Split phase 4, thumbs: no reader reads the thumbnail section as text except
    # test_living_library's _atomic_replace pin, which reads make_thumbnail through thumbs_mod; the
    # other hits are patches of thumbs_mod. The whole-module absence guards read the module too.
    ('tests/test_app_paths.py', 'moonglade.thumbs'),
    ('tests/test_artworks_adhoc.py', 'moonglade.thumbs'),
    ('tests/test_bonjour.py', 'moonglade.thumbs'),
    ('tests/test_branding.py', 'moonglade.thumbs'),
    ('tests/test_catalog_verbs.py', 'moonglade.thumbs'),
    ('tests/test_catchup_query.py', 'moonglade.thumbs'),
    ('tests/test_csrf_coverage.py', 'moonglade.thumbs'),
    ('tests/test_evidence_counters.py', 'moonglade.thumbs'),
    ('tests/test_first_party_sources.py', 'moonglade.thumbs'),
    ('tests/test_history_feed_document.py', 'moonglade.thumbs'),
    ('tests/test_living_library.py', 'moonglade.thumbs'),
    ('tests/test_logging.py', 'moonglade.thumbs'),
    ('tests/test_loom_p_routes.py', 'moonglade.thumbs'),
    ('tests/test_network.py', 'moonglade.thumbs'),
    ('tests/test_security_review_fixes.py', 'moonglade.thumbs'),
    ('tests/test_server_one_module.py', 'moonglade.thumbs'),
    ('tests/test_settings_store.py', 'moonglade.thumbs'),
    ('tests/test_setup_prepare.py', 'moonglade.thumbs'),
    ('tests/test_task_model_detail_document.py', 'moonglade.thumbs'),
    ('tests/test_telemetry.py', 'moonglade.thumbs'),
    # Split phase 4, trash: no reader reads the trash section's text (test_network names
    # purge_media_local in prose); the whole-module absence guards read the module too.
    ('tests/test_app_paths.py', 'moonglade.trash'),
    ('tests/test_artworks_adhoc.py', 'moonglade.trash'),
    ('tests/test_bonjour.py', 'moonglade.trash'),
    ('tests/test_branding.py', 'moonglade.trash'),
    ('tests/test_catalog_verbs.py', 'moonglade.trash'),
    ('tests/test_catchup_query.py', 'moonglade.trash'),
    ('tests/test_csrf_coverage.py', 'moonglade.trash'),
    ('tests/test_evidence_counters.py', 'moonglade.trash'),
    ('tests/test_first_party_sources.py', 'moonglade.trash'),
    ('tests/test_history_feed_document.py', 'moonglade.trash'),
    ('tests/test_living_library.py', 'moonglade.trash'),
    ('tests/test_logging.py', 'moonglade.trash'),
    ('tests/test_loom_p_routes.py', 'moonglade.trash'),
    ('tests/test_network.py', 'moonglade.trash'),
    ('tests/test_security_review_fixes.py', 'moonglade.trash'),
    ('tests/test_server_one_module.py', 'moonglade.trash'),
    ('tests/test_settings_store.py', 'moonglade.trash'),
    ('tests/test_setup_prepare.py', 'moonglade.trash'),
    ('tests/test_task_model_detail_document.py', 'moonglade.trash'),
    ('tests/test_telemetry.py', 'moonglade.trash'),
    # Split phase 4, dupe_review: no reader reads Duplicate Review's text; the whole-module absence
    # guards read the module too.
    ('tests/test_app_paths.py', 'moonglade.dupe_review'),
    ('tests/test_artworks_adhoc.py', 'moonglade.dupe_review'),
    ('tests/test_bonjour.py', 'moonglade.dupe_review'),
    ('tests/test_branding.py', 'moonglade.dupe_review'),
    ('tests/test_catalog_verbs.py', 'moonglade.dupe_review'),
    ('tests/test_catchup_query.py', 'moonglade.dupe_review'),
    ('tests/test_csrf_coverage.py', 'moonglade.dupe_review'),
    ('tests/test_evidence_counters.py', 'moonglade.dupe_review'),
    ('tests/test_first_party_sources.py', 'moonglade.dupe_review'),
    ('tests/test_history_feed_document.py', 'moonglade.dupe_review'),
    ('tests/test_living_library.py', 'moonglade.dupe_review'),
    ('tests/test_logging.py', 'moonglade.dupe_review'),
    ('tests/test_loom_p_routes.py', 'moonglade.dupe_review'),
    ('tests/test_network.py', 'moonglade.dupe_review'),
    ('tests/test_security_review_fixes.py', 'moonglade.dupe_review'),
    ('tests/test_server_one_module.py', 'moonglade.dupe_review'),
    ('tests/test_settings_store.py', 'moonglade.dupe_review'),
    ('tests/test_setup_prepare.py', 'moonglade.dupe_review'),
    ('tests/test_task_model_detail_document.py', 'moonglade.dupe_review'),
    ('tests/test_telemetry.py', 'moonglade.dupe_review'),
    # Split phase 4, web_accounts: no reader reads the login accounts' text; test_web_auth's
    # shipped-hash read goes to moonglade/web_accounts.py, so it leaves SOURCE_READERS.
    ('tests/test_artworks_adhoc.py', 'moonglade.web_accounts'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.web_accounts'),
    ('tests/test_config_path_routing.py', 'moonglade.web_accounts'),
    ('tests/test_create_door.py', 'moonglade.web_accounts'),
    ('tests/test_csrf_coverage.py', 'moonglade.web_accounts'),
    ('tests/test_enhance.py', 'moonglade.web_accounts'),
    ('tests/test_evidence_counters.py', 'moonglade.web_accounts'),
    ('tests/test_full_meta_rest_fallback.py', 'moonglade.web_accounts'),
    ('tests/test_gen_surface.py', 'moonglade.web_accounts'),
    ('tests/test_history_feed_document.py', 'moonglade.web_accounts'),
    ('tests/test_jwt.py', 'moonglade.web_accounts'),
    ('tests/test_living_library.py', 'moonglade.web_accounts'),
    ('tests/test_loom_notify.py', 'moonglade.web_accounts'),
    ('tests/test_pixai_client.py', 'moonglade.web_accounts'),
    ('tests/test_settings_store.py', 'moonglade.web_accounts'),
    ('tests/test_setup_prepare.py', 'moonglade.web_accounts'),
    ('tests/test_spend_no_retry.py', 'moonglade.web_accounts'),
    ('tests/test_task_model_detail_document.py', 'moonglade.web_accounts'),
    ('tests/test_telemetry.py', 'moonglade.web_accounts'),
    ('tests/test_training_advanced.py', 'moonglade.web_accounts'),
    ('tests/test_training_parity.py', 'moonglade.web_accounts'),
    # Split phase 4, history: no reader reads the feed's or the extraction's text but through
    # history_mod; test_history_feed_document's retired-hash guard reads history_mod too.
    ('tests/test_artworks_adhoc.py', 'moonglade.history'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.history'),
    ('tests/test_config_path_routing.py', 'moonglade.history'),
    ('tests/test_create_door.py', 'moonglade.history'),
    ('tests/test_csrf_coverage.py', 'moonglade.history'),
    ('tests/test_enhance.py', 'moonglade.history'),
    ('tests/test_evidence_counters.py', 'moonglade.history'),
    ('tests/test_full_meta_rest_fallback.py', 'moonglade.history'),
    ('tests/test_gen_surface.py', 'moonglade.history'),
    ('tests/test_history_feed_document.py', 'moonglade.history'),
    ('tests/test_jwt.py', 'moonglade.history'),
    ('tests/test_living_library.py', 'moonglade.history'),
    ('tests/test_loom_notify.py', 'moonglade.history'),
    ('tests/test_network.py', 'moonglade.history'),
    ('tests/test_pixai_client.py', 'moonglade.history'),
    ('tests/test_settings_store.py', 'moonglade.history'),
    ('tests/test_setup_prepare.py', 'moonglade.history'),
    ('tests/test_spend_no_retry.py', 'moonglade.history'),
    ('tests/test_task_model_detail_document.py', 'moonglade.history'),
    ('tests/test_telemetry.py', 'moonglade.history'),
    ('tests/test_training_advanced.py', 'moonglade.history'),
    ('tests/test_training_parity.py', 'moonglade.history'),
    # Split phase 4, media_fetch: no reader reads the media fetch's text but through
    # media_fetch_mod; test_network's page_variables read goes there, so it no longer reads backup.
    ('tests/test_artworks_adhoc.py', 'moonglade.media_fetch'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.media_fetch'),
    ('tests/test_config_path_routing.py', 'moonglade.media_fetch'),
    ('tests/test_create_door.py', 'moonglade.media_fetch'),
    ('tests/test_csrf_coverage.py', 'moonglade.media_fetch'),
    ('tests/test_enhance.py', 'moonglade.media_fetch'),
    ('tests/test_evidence_counters.py', 'moonglade.media_fetch'),
    ('tests/test_full_meta_rest_fallback.py', 'moonglade.media_fetch'),
    ('tests/test_gen_surface.py', 'moonglade.media_fetch'),
    ('tests/test_history_feed_document.py', 'moonglade.media_fetch'),
    ('tests/test_jwt.py', 'moonglade.media_fetch'),
    ('tests/test_living_library.py', 'moonglade.media_fetch'),
    ('tests/test_loom_notify.py', 'moonglade.media_fetch'),
    ('tests/test_pixai_client.py', 'moonglade.media_fetch'),
    ('tests/test_settings_store.py', 'moonglade.media_fetch'),
    ('tests/test_setup_prepare.py', 'moonglade.media_fetch'),
    ('tests/test_spend_no_retry.py', 'moonglade.media_fetch'),
    ('tests/test_task_model_detail_document.py', 'moonglade.media_fetch'),
    ('tests/test_telemetry.py', 'moonglade.media_fetch'),
    ('tests/test_training_advanced.py', 'moonglade.media_fetch'),
    ('tests/test_training_parity.py', 'moonglade.media_fetch'),
    ('tests/test_video_tsubaki.py', 'moonglade.media_fetch'),
    # Split phase 4, full_meta: no reader reads the full-meta text but through full_meta_mod;
    # test_gen_surface's row-builder read takes moonglade/full_meta.py beside backup and gen_cli.
    ('tests/test_artworks_adhoc.py', 'moonglade.full_meta'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.full_meta'),
    ('tests/test_config_path_routing.py', 'moonglade.full_meta'),
    ('tests/test_create_door.py', 'moonglade.full_meta'),
    ('tests/test_csrf_coverage.py', 'moonglade.full_meta'),
    ('tests/test_edit_upload.py', 'moonglade.full_meta'),
    ('tests/test_enhance.py', 'moonglade.full_meta'),
    ('tests/test_evidence_counters.py', 'moonglade.full_meta'),
    ('tests/test_full_meta_rest_fallback.py', 'moonglade.full_meta'),
    ('tests/test_gen_surface.py', 'moonglade.full_meta'),
    ('tests/test_history_feed_document.py', 'moonglade.full_meta'),
    ('tests/test_jwt.py', 'moonglade.full_meta'),
    ('tests/test_living_library.py', 'moonglade.full_meta'),
    ('tests/test_loom_notify.py', 'moonglade.full_meta'),
    ('tests/test_pixai_client.py', 'moonglade.full_meta'),
    ('tests/test_settings_store.py', 'moonglade.full_meta'),
    ('tests/test_setup_prepare.py', 'moonglade.full_meta'),
    ('tests/test_spend_no_retry.py', 'moonglade.full_meta'),
    ('tests/test_task_model_detail_document.py', 'moonglade.full_meta'),
    ('tests/test_telemetry.py', 'moonglade.full_meta'),
    ('tests/test_training_advanced.py', 'moonglade.full_meta'),
    ('tests/test_training_parity.py', 'moonglade.full_meta'),
    ('tests/test_video_tsubaki.py', 'moonglade.full_meta'),
    # Split phase 4, library_runs: no reader reads the library runs' text but through
    # library_runs_mod; test_gen_surface's import-local read takes moonglade/library_runs.py too,
    # test_artworks_adhoc's retired-hash guard reads library_runs_mod, and test_video_tsubaki's
    # run_fix_models read goes there, so it leaves SOURCE_READERS.
    ('tests/test_artworks_adhoc.py', 'moonglade.library_runs'),
    ('tests/test_cli_doc_coverage.py', 'moonglade.library_runs'),
    ('tests/test_community_surface.py', 'moonglade.library_runs'),
    ('tests/test_config_path_routing.py', 'moonglade.library_runs'),
    ('tests/test_create_door.py', 'moonglade.library_runs'),
    ('tests/test_csrf_coverage.py', 'moonglade.library_runs'),
    ('tests/test_enhance.py', 'moonglade.library_runs'),
    ('tests/test_evidence_counters.py', 'moonglade.library_runs'),
    ('tests/test_full_meta_rest_fallback.py', 'moonglade.library_runs'),
    ('tests/test_gen_surface.py', 'moonglade.library_runs'),
    ('tests/test_history_feed_document.py', 'moonglade.library_runs'),
    ('tests/test_jwt.py', 'moonglade.library_runs'),
    ('tests/test_living_library.py', 'moonglade.library_runs'),
    ('tests/test_loom_notify.py', 'moonglade.library_runs'),
    ('tests/test_pixai_client.py', 'moonglade.library_runs'),
    ('tests/test_settings_store.py', 'moonglade.library_runs'),
    ('tests/test_setup_prepare.py', 'moonglade.library_runs'),
    ('tests/test_spend_no_retry.py', 'moonglade.library_runs'),
    ('tests/test_task_model_detail_document.py', 'moonglade.library_runs'),
    ('tests/test_telemetry.py', 'moonglade.library_runs'),
    ('tests/test_training_advanced.py', 'moonglade.library_runs'),
    ('tests/test_training_parity.py', 'moonglade.library_runs'),
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
            stack.extend(getattr(node, "decorator_list", []))      # a Lambda has none
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
    # Since 3.22 phase 4 the node tests that read the gallery's page shells read the module they
    # moved to (pages), not gallery.py itself; import-batches (scan) does not count here.
    from_gallery = {"moonglade.gallery"} | {m for m, e in SEAMS.items()
                                            if e["from"] == "moonglade.gallery"}
    assert any(set(readers[p]) & from_gallery for p in js
               if p != "loom/test/import-batches.test.js")
    # Since 3.22 the node tests that read the engine read the modules split out of it
    # (cards, gen_params), not backup.py itself.
    from_backup = {"moonglade.backup"} | {m for m, e in SEAMS.items()
                                          if e["from"] == "moonglade.backup"}
    assert any(set(readers[p]) & from_backup for p in js)


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
