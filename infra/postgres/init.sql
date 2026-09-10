-- SPILLTRACE — database bootstrap.
-- Runs once on an empty data directory, AFTER the postgis image's own scripts
-- (hence the 99- prefix), so it can remove what we do not use.
--
-- The postgis image installs postgis_tiger_geocoder, which is US address geocoding we
-- have no use for and which also appends 'tiger' to the database search_path.  Left in
-- place it pollutes schema reflection: Alembic autogenerate reflects its ~40 tables and
-- proposes dropping every one of them.

DROP EXTENSION IF EXISTS postgis_tiger_geocoder CASCADE;
DROP EXTENSION IF EXISTS fuzzystrmatch CASCADE;
DROP EXTENSION IF EXISTS postgis_topology CASCADE;
DROP SCHEMA IF EXISTS tiger CASCADE;
DROP SCHEMA IF EXISTS tiger_data CASCADE;
DROP SCHEMA IF EXISTS topology CASCADE;

-- Reset the search path the tiger extension modified.
ALTER DATABASE spilltrace SET search_path TO public;

-- What SPILLTRACE actually needs.
CREATE EXTENSION IF NOT EXISTS postgis;        -- geometry types + spatial indexing
CREATE EXTENSION IF NOT EXISTS postgis_raster; -- probability/density raster support
CREATE EXTENSION IF NOT EXISTS pgcrypto;       -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS btree_gist;     -- combined spatial + scalar exclusion
CREATE EXTENSION IF NOT EXISTS citext;         -- case-insensitive email
CREATE EXTENSION IF NOT EXISTS pg_trgm;        -- vessel name search

SELECT 'SPILLTRACE database bootstrap complete: ' || postgis_version() AS status;
