-- Enable PostGIS
CREATE EXTENSION IF NOT EXISTS postgis;
-- CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- ---------------------------------------------------------------------------
-- hazard_features
-- Stores point / linestring / polygon hazards from OSM, EPA TRI, USDA FSIS.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hazard_features (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT        NOT NULL,          -- 'osm', 'epa_tri', 'usda_fsis'
    category    TEXT        NOT NULL,          -- 'highway', 'rail', 'industrial', 'meat_processing', 'landfill', 'airport'
    subcategory TEXT        NOT NULL,          -- 'motorway', 'rail', 'chemical', 'slaughter', etc.
    name        TEXT,
    properties  JSONB       NOT NULL DEFAULT '{}',
    geom        GEOMETRY(Geometry, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_hazard_features_geom
    ON hazard_features USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_hazard_features_category
    ON hazard_features (category);

CREATE INDEX IF NOT EXISTS idx_hazard_features_source
    ON hazard_features (source);

-- Prevent exact duplicate OSM IDs per source
CREATE INDEX IF NOT EXISTS idx_hazard_features_source_cat
    ON hazard_features (source, category, subcategory);

-- ---------------------------------------------------------------------------
-- flood_zones
-- FEMA National Flood Hazard Layer (NFHL) flood zones.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS flood_zones (
    id          BIGSERIAL PRIMARY KEY,
    zone_code   TEXT    NOT NULL,   -- 'AE', 'A', 'AH', 'AO', 'VE', 'X', etc.
    flood_label TEXT    NOT NULL,   -- Human-readable label
    geom        GEOMETRY(MultiPolygon, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_flood_zones_geom
    ON flood_zones USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_flood_zones_zone_code
    ON flood_zones (zone_code);

-- ---------------------------------------------------------------------------
-- future_development
-- MUD districts and bond issuances for development proximity queries.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS future_development (
    id              BIGSERIAL PRIMARY KEY,
    dev_type        TEXT    NOT NULL,       -- 'mud_district', 'bond_issuance'
    name            TEXT,
    status          TEXT,
    formed_year     INT,
    last_bond_year  INT,
    bond_amount_usd BIGINT,
    geom            GEOMETRY(Geometry, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_future_development_geom
    ON future_development USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_future_development_dev_type
    ON future_development (dev_type);

-- ---------------------------------------------------------------------------
-- zoning
-- Municipal zoning boundaries.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS zoning (
    id            BIGSERIAL PRIMARY KEY,
    city          TEXT    NOT NULL,
    zone_code     TEXT    NOT NULL,
    zone_label    TEXT    NOT NULL,
    max_height_m  FLOAT,
    geom          GEOMETRY(MultiPolygon, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_zoning_geom
    ON zoning USING GIST (geom);

CREATE INDEX IF NOT EXISTS idx_zoning_city
    ON zoning (city);

CREATE INDEX IF NOT EXISTS idx_zoning_zone_code
    ON zoning (zone_code);
