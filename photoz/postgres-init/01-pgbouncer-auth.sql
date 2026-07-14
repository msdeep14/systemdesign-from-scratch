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
