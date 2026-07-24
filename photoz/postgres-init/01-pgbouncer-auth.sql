-- Enable pg_stat_statements so benchmark scripts can inspect per-query execution counts.
-- This is a standard PostgreSQL extension included in the postgres image.
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Create the pgbouncer user for auth_query
CREATE ROLE pgbouncer LOGIN PASSWORD 'pgbouncer_password';

-- Create a security definer function so pgbouncer can read password hashes without being a superuser
CREATE OR REPLACE FUNCTION pgbouncer_get_auth(p_usename TEXT)
RETURNS TABLE(username TEXT, password TEXT) AS
$$
BEGIN
    RETURN QUERY
    SELECT usename::TEXT, passwd::TEXT FROM pg_catalog.pg_shadow
    WHERE usename = p_usename;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Revoke execute from public and grant it only to pgbouncer
REVOKE ALL ON FUNCTION pgbouncer_get_auth(p_usename TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pgbouncer_get_auth(p_usename TEXT) TO pgbouncer;
