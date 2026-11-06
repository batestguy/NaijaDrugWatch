-- 001_extensions.sql
-- Run first. The `vector` type must exist before any table declares a vector column,
-- so this file cannot be merged into the table definitions.
--
-- Neon Free supports all three extensions.

create extension if not exists pg_trgm;   -- fuzzy / trigram name matching
create extension if not exists vector;    -- pgvector: embedding similarity (stage one of the matcher)
create extension if not exists unaccent;  -- so "Paracétamol" and "Paracetamol" compare equal
