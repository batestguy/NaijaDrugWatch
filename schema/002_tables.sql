-- 002_tables.sql
-- Eight tables. Names are fixed by the project contract (AGENTS.md, "Fixed schema contract");
-- the dashboard and the Data API are built on them, so do not rename.
--
-- Design notes that are not obvious from the names:
--   * nafdac_status_snapshots is an append-only ledger. We never update a registration's
--     status in place: status history is the product.
--   * scrape_runs gets a row even when a run fails, because v_pipeline_health reads it.
--   * pharmacy_listings carries pack_size/pack_unit/unit_price. These are an addition to the
--     original spec: without them "cheapest" compares a 12-tablet pack to a 500-tablet jar.

-- ---------------------------------------------------------------- pharmacies

create table if not exists pharmacies (
    id          bigserial primary key,
    name        text        not null,
    website     text,
    state       text        not null,          -- required: the price index is partitioned by state
    city        text,
    address     text,
    latitude    numeric(9, 6),
    longitude   numeric(9, 6),
    created_at  timestamptz not null default now(),
    constraint pharmacies_name_state_key unique (name, state)
);

comment on column pharmacies.state is
    'Nigerian state or "FCT". v_cheapest_per_product_state partitions on this.';

-- -------------------------------------------------------- nafdac_registrations

create table if not exists nafdac_registrations (
    registration_number   text primary key,     -- NRN, e.g. A4-100160
    product_name          text,
    brand_name            text,
    generic_name          text,
    active_ingredients    text,
    dosage_form           text,
    strength              text,
    applicant             text,
    manufacturer          text,
    manufacturer_country  text,
    status                text,                 -- Active | Expired | Inactive (strings come from NAFDAC)
    approval_date         date,
    expiry_date           date,
    pack_description      text,                 -- free text, e.g. "1 x 500's (in a jar)"
    atc_code              text,
    product_category      text,
    source_url            text,
    scraped_at            timestamptz not null default now()
);

comment on column nafdac_registrations.pack_description is
    'Free-text as published. Blank on ~70% of pages, so pack size must come from listing titles.';

-- ---------------------------------------------------- nafdac_status_snapshots

create table if not exists nafdac_status_snapshots (
    id                   bigserial primary key,
    registration_number  text not null
                         references nafdac_registrations (registration_number) on delete cascade,
    status               text not null,
    expiry_date          date,
    snapshot_date        date not null default current_date,
    observed_at          timestamptz not null default now(),

    -- Contract constraint: one observation per registration per day.
    constraint nafdac_status_snapshots_reg_day_key
        unique (registration_number, snapshot_date)
);

comment on table nafdac_status_snapshots is
    'Append-only. Status and expiry can disagree (seen on NRN A4-.../id 4125: Expired, expiry 2030), '
    'so store both and never derive one from the other.';

-- ----------------------------------------------------------------- products

create table if not exists products (
    id                         bigserial primary key,
    canonical_name             text not null,
    generic_name               text,
    brand_name                 text,
    brand_aliases              text[],          -- from #FixMedPrices: up to 88 per drug
    form                       text,
    strength                   text,
    nafdac_registration_number text
                               references nafdac_registrations (registration_number) on delete set null,
    embedding                  vector(384),     -- dimension must match the embedding model; see docs/schema.md
    created_at                 timestamptz not null default now()
);

-- Expression index so NULL strength/form still collapse to one row per product.
create unique index if not exists products_canonical_key
    on products (canonical_name, coalesce(strength, ''), coalesce(form, ''));

create index if not exists products_embedding_idx
    on products using hnsw (embedding vector_cosine_ops);

create index if not exists products_canonical_trgm_idx
    on products using gin (canonical_name gin_trgm_ops);

-- --------------------------------------------------------- drug_match_rules

create table if not exists drug_match_rules (
    id                 bigserial primary key,
    canonical_name     text not null,
    match_pattern      text not null,           -- regex or ILIKE fragment applied to raw titles
    required_strength  text,
    required_form      text,
    active_ingredient  text,
    priority           integer not null default 100,  -- lower wins when several rules match
    created_at         timestamptz not null default now()
);

create unique index if not exists drug_match_rules_key
    on drug_match_rules (canonical_name, coalesce(required_strength, ''), coalesce(required_form, ''));

comment on table drug_match_rules is
    'Stage two of the matcher: pgvector proposes candidates, these rules decide. '
    'Similarity-only or pg_trgm-only matching is an explicitly rejected failure mode.';

-- -------------------------------------------------------- pharmacy_listings

create table if not exists pharmacy_listings (
    id           bigserial primary key,
    pharmacy_id  bigint not null references pharmacies (id) on delete cascade,
    product_id   bigint references products (id) on delete set null,
    raw_title    text   not null,               -- never overwrite: the matcher is re-runnable from it
    url          text   not null,
    price_ngn    numeric(12, 2),
    in_stock     boolean,
    pack_size    integer,                       -- 28 in "Amlodipine 10mg Tablets x28"
    pack_unit    text,                          -- tab | cap | ml | g | sachet
    unit_price   numeric(12, 4),                -- price_ngn / pack_size, comparable across packs
    scraped_at   timestamptz not null default now(),
    source_hash  text   not null,

    constraint pharmacy_listings_price_positive
        check (price_ngn is null or price_ngn >= 0),
    constraint pharmacy_listings_unit_price_positive
        check (unit_price is null or unit_price > 0),

    -- Contract constraint. NOTE: this cannot dedupe across runs because scraped_at moves;
    -- source_hash is the handle that actually does. Both are kept deliberately.
    constraint pharmacy_listings_pharmacy_url_ts_key
        unique (pharmacy_id, url, scraped_at)
);

create index if not exists pharmacy_listings_hash_idx
    on pharmacy_listings (pharmacy_id, source_hash);

create index if not exists pharmacy_listings_product_idx
    on pharmacy_listings (product_id);

-- ------------------------------------------------------------- price_history

create table if not exists price_history (
    id           bigserial primary key,
    listing_id   bigint not null references pharmacy_listings (id) on delete cascade,
    price_ngn    numeric(12, 2) not null,
    in_stock     boolean,
    unit_price   numeric(12, 4),
    recorded_at  timestamptz not null default now()
);

create index if not exists price_history_listing_time_idx
    on price_history (listing_id, recorded_at desc);

create index if not exists price_history_recorded_idx
    on price_history (recorded_at);

-- --------------------------------------------------------------- scrape_runs

create table if not exists scrape_runs (
    id             bigserial primary key,
    source         text not null,               -- nafdac_greenbook | healthplus | drugstore | medplus
    started_at     timestamptz not null default now(),
    finished_at    timestamptz,
    status         text not null default 'running',   -- running | success | failed
    record_count   integer,
    error_message  text,

    constraint scrape_runs_status_check
        check (status in ('running', 'success', 'failed'))
);

comment on table scrape_runs is
    'A row is written even when a run fails; v_pipeline_health flags a source STALE after 48 h '
    'without a successful run.';

create index if not exists scrape_runs_source_status_idx
    on scrape_runs (source, status, finished_at desc);
