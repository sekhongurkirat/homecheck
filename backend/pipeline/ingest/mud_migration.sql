-- future_development table migration
-- Stores MUD district boundaries (TWDB) and bond issuances (MSRB EMMA).

CREATE TABLE IF NOT EXISTS future_development (
    id              BIGSERIAL PRIMARY KEY,
    source          TEXT    NOT NULL,           -- 'twdb_mud', 'emma'
    dev_type        TEXT    NOT NULL,           -- 'mud_district', 'bond_issuance', 'tif_district'
    name            TEXT,
    description     TEXT,
    formed_year     INT,
    last_bond_year  INT,
    bond_amount_usd BIGINT,
    status          TEXT    DEFAULT 'active',
    properties      JSONB   NOT NULL DEFAULT '{}',
    geom            GEOMETRY(Geometry, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_future_dev_geom    ON future_development USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_future_dev_type    ON future_development (dev_type);
CREATE INDEX IF NOT EXISTS idx_future_dev_source  ON future_development (source);
