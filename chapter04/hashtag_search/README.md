# Hashtag Search

This folder documents the implementation of hashtag-based photo search in the Photoz application. It uses PostgreSQL's `pg_trgm` extension with a GIN trigram index on the `caption` column to enable fast substring matching for hashtag queries.
