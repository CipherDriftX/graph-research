-- Store schema. Idempotent: safe to apply on every start.
--
-- channels and videos are shared across runs. Which rows belong to which
-- run is recorded in category_tags, so one channel can sit in a Finance run
-- and a Crime run at the same time without being duplicated.

CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    subscriber_count BIGINT DEFAULT 0,
    description TEXT DEFAULT '',
    -- The channel's creation date from channels.list snippet.publishedAt,
    -- not the date this pipeline first saw it.
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    discovery_method TEXT NOT NULL,
    extra JSONB DEFAULT '{}'::jsonb,
    country_code TEXT,
    country_source TEXT NOT NULL DEFAULT 'unknown'
        CHECK (country_source IN ('self_reported', 'inferred_language', 'inferred_llm', 'unknown')),
    country_confidence NUMERIC(3,2),
    region TEXT,
    is_us_market BOOLEAN NOT NULL DEFAULT FALSE,
    primary_language_code TEXT,
    audience_language_code TEXT,
    language_confidence NUMERIC(3,2),
    face_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (face_status IN ('face', 'faceless', 'mixed', 'unknown')),
    dominant_format TEXT,
    primary_niche_id INTEGER,
    meets_subscriber_floor BOOLEAN NOT NULL DEFAULT FALSE,
    floor_override_reason TEXT,
    evergreen_score NUMERIC(5,2),
    is_likely_news BOOLEAN,
    engagement_score NUMERIC(5,2),
    entertainment_score NUMERIC(5,2),
    engagement_components JSONB,
    priority_score NUMERIC(8,3),
    has_affiliate_signal BOOLEAN,
    has_sponsor_signal BOOLEAN,
    has_membership_signal BOOLEAN,
    uploads_per_week_avg NUMERIC(6,2),
    upload_consistency_score NUMERIC(3,2),
    data_completeness_score NUMERIC(3,2),
    missing_required_fields TEXT[] NOT NULL DEFAULT '{}',
    classifier_model TEXT,
    classifier_version TEXT,
    first_discovered_run_id TEXT,
    last_enriched_run_id TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Found by paging the uploads playlist to its end. The videos table only
    -- holds a recent sample, so this cannot be derived from it.
    first_video_published_at TIMESTAMPTZ,
    primary_topic TEXT,
    secondary_topic TEXT,
    geography_focus TEXT,
    target_audience TEXT,
    content_approach TEXT,
    channel_size_bucket TEXT,
    sub_growth_30d BIGINT,
    sub_growth_90d BIGINT,
    views_30d BIGINT,
    views_90d BIGINT,
    upload_frequency TEXT,
    creator_authority TEXT DEFAULT 'unknown'
        CHECK (creator_authority IN (
            'financial_professional', 'economist', 'accountant', 'trader', 'investor',
            'academic', 'entrepreneur', 'media_personality', 'general_creator',
            'anonymous_brand', 'unknown')),
    creator_authority_evidence TEXT,
    channel_creation_date DATE,
    vertical_start_date DATE,
    vertical_start_date_confidence NUMERIC(3,2),
    vertical_start_date_basis TEXT
        CHECK (vertical_start_date_basis IS NULL OR vertical_start_date_basis IN (
            'first_vertical_video_observed', 'earliest_observed_video_lower_bound',
            'channel_creation_date', 'self_reported', 'unknown')),
    is_comparison_pool BOOLEAN NOT NULL DEFAULT FALSE,
    success_failure_factors_checked_at TIMESTAMPTZ,
    creator_authority_checked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL REFERENCES channels(channel_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    view_count BIGINT DEFAULT 0,
    like_count BIGINT DEFAULT 0,
    comment_count BIGINT DEFAULT 0,
    published_at TIMESTAMPTZ,
    outlier_score DOUBLE PRECISION DEFAULT 0,
    scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    extra JSONB DEFAULT '{}'::jsonb,
    description TEXT,
    tags TEXT[],
    hashtags TEXT[],
    duration_seconds INTEGER,
    is_short BOOLEAN,
    language_code TEXT,
    evergreen_score NUMERIC(5,2),
    is_likely_news BOOLEAN,
    views_per_day_since_publish NUMERIC(12,2),
    title_char_count INTEGER,
    title_word_count INTEGER,
    title_has_number BOOLEAN,
    title_is_question BOOLEAN,
    title_capitalization TEXT
        CHECK (title_capitalization IN ('title_case', 'sentence_case', 'all_caps', 'mixed_emphasis')),
    title_emoji_count INTEGER,
    thumbnail_has_face BOOLEAN,
    thumbnail_text_density TEXT
        CHECK (thumbnail_text_density IN ('none', 'low', 'medium', 'high')),
    data_completeness_score NUMERIC(3,2),
    missing_required_fields TEXT[] NOT NULL DEFAULT '{}',
    -- One-sentence description of what the video is about, from its title.
    video_description TEXT,
    search_browse_estimate TEXT
        CHECK (search_browse_estimate IN ('search_driven', 'browse_driven', 'news_driven', 'mixed', 'unclear')),
    sponsor_status TEXT DEFAULT 'not_clearly_sponsored'
        CHECK (sponsor_status IN ('sponsored', 'not_clearly_sponsored')),
    sponsor_category TEXT
        CHECK (sponsor_category IN (
            'finance_investing', 'banking', 'credit_cards', 'insurance', 'software',
            'vpn', 'education', 'other')),
    sponsor_name TEXT,
    sample_reason TEXT
        CHECK (sample_reason IS NULL OR sample_reason IN ('latest', 'top_lifetime', 'shorts_sample'))
);

CREATE INDEX IF NOT EXISTS idx_videos_channel_id ON videos (channel_id);
CREATE INDEX IF NOT EXISTS idx_videos_published ON videos (published_at);
CREATE INDEX IF NOT EXISTS idx_channels_country ON channels (country_code);
CREATE INDEX IF NOT EXISTS idx_channels_engagement ON channels (engagement_score);
CREATE INDEX IF NOT EXISTS idx_channels_entertainment ON channels (entertainment_score);
CREATE INDEX IF NOT EXISTS idx_channels_evergreen ON channels (evergreen_score);
CREATE INDEX IF NOT EXISTS idx_channels_niche ON channels (primary_niche_id);
CREATE INDEX IF NOT EXISTS idx_channels_floor ON channels (meets_subscriber_floor)
    WHERE meets_subscriber_floor = TRUE;
CREATE INDEX IF NOT EXISTS idx_channels_us_market ON channels (is_us_market)
    WHERE is_us_market = TRUE;

-- Run membership. Tree node ids are only unique within a run (every run
-- has a "root"), so run_id is part of the key.
CREATE TABLE IF NOT EXISTS category_tags (
    id SERIAL PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('channel', 'video')),
    entity_id TEXT NOT NULL,
    tree_node_id TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    tagged_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (entity_type, entity_id, tree_node_id, run_id)
);

CREATE INDEX IF NOT EXISTS idx_category_tags_run ON category_tags (run_id);
CREATE INDEX IF NOT EXISTS idx_category_tags_tree_node ON category_tags (tree_node_id);
CREATE INDEX IF NOT EXISTS idx_category_tags_entity_tree ON category_tags (entity_id, tree_node_id);

-- Channel-to-channel edges found by the graph walk. featured_channels names
-- its target by URL or handle, and a UC id only exists once that channel has
-- been fetched, so the ref is the identity and the id is filled in later.
CREATE TABLE IF NOT EXISTS discovery_edges (
    id SERIAL PRIMARY KEY,
    source_channel_id TEXT NOT NULL,
    target_channel_id TEXT,
    target_channel_ref TEXT NOT NULL,
    edge_type TEXT NOT NULL CHECK (edge_type IN (
        'featured_channel', 'recommendation', 'comment_author', 'playlist',
        'collaboration', 'comment_mention')),
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_id TEXT NOT NULL,
    UNIQUE (source_channel_id, target_channel_ref, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_discovery_edges_run ON discovery_edges (run_id);
CREATE INDEX IF NOT EXISTS idx_discovery_edges_source_target
    ON discovery_edges (source_channel_id, target_channel_id);

-- One row per run. Every enrichment row elsewhere traces back to a run_id.
CREATE TABLE IF NOT EXISTS harness_runs (
    run_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed', 'partial')),
    seed_niches TEXT[] NOT NULL DEFAULT '{}',
    channels_discovered INTEGER NOT NULL DEFAULT 0,
    channels_enriched INTEGER NOT NULL DEFAULT 0,
    channels_refreshed INTEGER NOT NULL DEFAULT 0,
    videos_persisted INTEGER NOT NULL DEFAULT 0,
    total_cost_usd NUMERIC(10,4) NOT NULL DEFAULT 0,
    cost_by_model JSONB,
    config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    schema_version INTEGER NOT NULL DEFAULT 7,
    notes TEXT,
    run_mode TEXT NOT NULL DEFAULT 'cold_start'
        CHECK (run_mode IN ('cold_start', 'augment', 'snapshot_refresh'))
);

-- Point-in-time stats, one row per entity per run. Growth and evergreen
-- measures need history that a single run cannot produce.
CREATE TABLE IF NOT EXISTS channel_snapshots (
    snapshot_id BIGSERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    subscriber_count BIGINT,
    total_view_count BIGINT,
    total_video_count INTEGER,
    -- From YouTube's own UULF / UUSH / UULV playlists, not a duration guess.
    long_video_count INTEGER,
    shorts_count INTEGER,
    live_stream_count INTEGER,
    UNIQUE (channel_id, run_id)
);

CREATE TABLE IF NOT EXISTS video_snapshots (
    snapshot_id BIGSERIAL PRIMARY KEY,
    video_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    view_count BIGINT,
    like_count BIGINT,
    comment_count BIGINT,
    video_age_hours NUMERIC(12,2),
    UNIQUE (video_id, run_id)
);

CREATE INDEX IF NOT EXISTS idx_video_snapshots_run ON video_snapshots (run_id);
CREATE INDEX IF NOT EXISTS idx_video_snapshots_age ON video_snapshots (video_id, video_age_hours);

-- Niche families: several niche_taxonomy rows can share one group.
CREATE TABLE IF NOT EXISTS primary_niche_groups (
    group_id SERIAL PRIMARY KEY,
    vertical TEXT NOT NULL,
    group_label TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (vertical, group_label)
);

-- Canonical niche labels. Niches the model proposes are fuzzy-matched
-- against these before a new row is inserted.
CREATE TABLE IF NOT EXISTS niche_taxonomy (
    niche_id SERIAL PRIMARY KEY,
    niche_name TEXT NOT NULL UNIQUE,
    parent_category TEXT NOT NULL,
    description TEXT NOT NULL,
    is_evergreen_prone BOOLEAN,
    proposed_by_run_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    primary_niche_group_id INTEGER,
    commercial_intent TEXT CHECK (commercial_intent IN ('low', 'medium', 'high'))
);

CREATE TABLE IF NOT EXISTS channel_niches (
    channel_id TEXT NOT NULL,
    niche_id INTEGER NOT NULL,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    confidence NUMERIC(3,2),
    -- The label as the classifier proposed it, before matching. Never
    -- overwritten once set.
    raw_niche_label TEXT,
    admitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (channel_id, niche_id)
);

-- Which family each niche belonged to in one run, so a later run cannot
-- change an earlier run's workbook.
CREATE TABLE IF NOT EXISTS run_niche_families (
    run_id TEXT NOT NULL,
    niche_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, niche_id)
);

CREATE INDEX IF NOT EXISTS idx_run_niche_families_run ON run_niche_families (run_id);

CREATE TABLE IF NOT EXISTS niche_adjacency (
    id SERIAL PRIMARY KEY,
    vertical TEXT NOT NULL,
    niche_a TEXT NOT NULL,
    niche_b TEXT NOT NULL,
    adjacency_type TEXT NOT NULL CHECK (adjacency_type IN (
        'sibling_overlap', 'parent_child', 'format_shared', 'audience_shared')),
    rationale TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'curated'
        CHECK (source IN ('curated', 'llm_proposed', 'empirically_confirmed')),
    empirical_score NUMERIC(6,4),
    empirical_status TEXT NOT NULL DEFAULT 'unvalidated'
        CHECK (empirical_status IN ('unvalidated', 'confirmed', 'demoted', 'rejected')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (vertical, niche_a, niche_b, adjacency_type)
);

CREATE INDEX IF NOT EXISTS idx_niche_adjacency_lookup ON niche_adjacency (vertical, niche_a);

CREATE TABLE IF NOT EXISTS run_niche_cluster (
    id SERIAL PRIMARY KEY,
    run_id TEXT NOT NULL,
    niche_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('target', 'adjacent_admitted', 'adjacent_rejected')),
    adjacency_score NUMERIC(6,4),
    rejected_reason TEXT,
    UNIQUE (run_id, niche_name)
);

CREATE TABLE IF NOT EXISTS cohort_definitions (
    cohort_code TEXT PRIMARY KEY,
    vertical TEXT NOT NULL,
    exclusive_group TEXT,
    label TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_cohorts (
    id BIGSERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL,
    vertical TEXT NOT NULL,
    cohort_code TEXT NOT NULL REFERENCES cohort_definitions(cohort_code),
    criteria_snapshot JSONB NOT NULL,
    assigned_by_run_id TEXT NOT NULL,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (channel_id, vertical, cohort_code)
);

CREATE INDEX IF NOT EXISTS idx_channel_cohorts_channel ON channel_cohorts (channel_id);

-- Success and failure factors. Metadata-level only: titles, cadence,
-- format, niche fit. Nothing is read from inside the videos.
CREATE TABLE IF NOT EXISTS success_factor_taxonomy (
    factor_id SERIAL PRIMARY KEY,
    factor_code TEXT NOT NULL UNIQUE,
    factor_label TEXT NOT NULL,
    factor_group TEXT NOT NULL CHECK (factor_group IN (
        'title_metadata', 'thumbnail', 'format', 'cadence', 'niche_fit', 'monetization', 'other')),
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS failure_factor_taxonomy (
    factor_id SERIAL PRIMARY KEY,
    factor_code TEXT NOT NULL UNIQUE,
    factor_label TEXT NOT NULL,
    factor_group TEXT NOT NULL CHECK (factor_group IN (
        'title_metadata', 'thumbnail', 'format', 'cadence', 'niche_fit', 'monetization', 'other')),
    description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_success_factors (
    id BIGSERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL,
    factor_id INTEGER NOT NULL,
    evidence_grade TEXT NOT NULL CHECK (evidence_grade IN ('strong', 'moderate', 'weak')),
    corroboration_count INTEGER NOT NULL,
    compared_against TEXT,
    evidence_note TEXT,
    extracted_by_run_id TEXT NOT NULL,
    classifier_model TEXT NOT NULL,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (channel_id, factor_id, extracted_by_run_id)
);

CREATE TABLE IF NOT EXISTS channel_failure_factors (
    id BIGSERIAL PRIMARY KEY,
    channel_id TEXT NOT NULL,
    factor_id INTEGER NOT NULL,
    evidence_grade TEXT NOT NULL CHECK (evidence_grade IN ('strong', 'moderate', 'weak')),
    corroboration_count INTEGER NOT NULL,
    compared_against TEXT,
    evidence_note TEXT,
    extracted_by_run_id TEXT NOT NULL,
    classifier_model TEXT NOT NULL,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (channel_id, factor_id, extracted_by_run_id)
);

CREATE INDEX IF NOT EXISTS idx_success_factors_channel ON channel_success_factors (channel_id);
CREATE INDEX IF NOT EXISTS idx_success_factors_factor ON channel_success_factors (factor_id);
CREATE INDEX IF NOT EXISTS idx_failure_factors_channel ON channel_failure_factors (channel_id);
CREATE INDEX IF NOT EXISTS idx_failure_factors_factor ON channel_failure_factors (factor_id);

-- Crime vertical extension: case-level fields for crime videos.
CREATE TABLE IF NOT EXISTS crime_case_metadata (
    video_id TEXT PRIMARY KEY REFERENCES videos(video_id) ON DELETE CASCADE,
    crime_type TEXT,
    victim_type TEXT,
    suspect_relationship TEXT,
    investigation_type TEXT,
    evidence_type_primary TEXT,
    case_status TEXT CHECK (case_status IN ('solved', 'unsolved', 'ongoing', 'cold_case', 'unknown')),
    case_fame_level TEXT CHECK (case_fame_level IN (
        'nationally_known', 'regionally_known', 'locally_known', 'obscure', 'unknown')),
    case_country TEXT,
    case_year INTEGER,
    interrogation_available BOOLEAN,
    bodycam_available BOOLEAN,
    cctv_available BOOLEAN,
    call_911_available BOOLEAN,
    court_footage_available BOOLEAN,
    classifier_model TEXT,
    classifier_version TEXT,
    classified_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS video_reveal_mechanisms (
    video_id TEXT NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    mechanism TEXT NOT NULL CHECK (mechanism IN (
        'interrogation_confession', 'suspect_mistake', 'cctv', 'phone_device_data', 'dna',
        'call_911', 'witness', 'social_media', 'financial_records', 'location_data', 'other')),
    PRIMARY KEY (video_id, mechanism)
);
