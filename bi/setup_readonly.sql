-- Run with psql as the database owner, after Alembic migrations.
-- This script assumes the application lives in schema public.
\set ON_ERROR_STOP on
BEGIN;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='photoprint_bi') THEN
    CREATE ROLE photoprint_bi LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='photoprint_bi'
             AND (rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls))
     OR EXISTS (SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='photoprint_bi')) THEN
    RAISE EXCEPTION 'photoprint_bi has elevated privileges or role memberships; configure a separate BI role';
  END IF;
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO photoprint_bi', current_database());
END $$;
GRANT USAGE ON SCHEMA public TO photoprint_bi;
GRANT SELECT ON
  public.v_dashboard_kpi, public.v_revenue_by_day, public.v_orders_by_status,
  public.v_sales_plan_fact, public.v_production_quality, public.v_support_sla,
  public.v_staffing_coverage, public.v_capacity_forecast
TO photoprint_bi;
ALTER ROLE photoprint_bi SET default_transaction_read_only=on;
ALTER ROLE photoprint_bi SET search_path=public;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables t
    WHERE t.table_schema='public' AND t.table_type='BASE TABLE'
      AND has_table_privilege('photoprint_bi', format('%I.%I',t.table_schema,t.table_name), 'SELECT')
  ) THEN
    RAISE EXCEPTION 'BI can read base tables through existing grants/PUBLIC; transaction rolled back. Restrict those privileges before retrying.';
  END IF;
END $$;
COMMIT;
-- psql prompts interactively; the password is not put in SQL, shell history or this repository.
\password photoprint_bi
