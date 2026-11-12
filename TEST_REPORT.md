# Backend verification — 2026-11-12

## Verified locally

Final command:

```sh
uv run --python 3.12 --no-project --with pgserver python scripts/test_postgres.py -q
```

Result: **84 passed in 49.87s**, no skips. The helper launched a fresh temporary PostgreSQL and removed it afterwards. Application and tests used Python 3.13; Python 3.12 was used only to host pgserver. The configured remote database was not used.

Coverage includes:

- Login, invalid/inactive users, access-token validation/expiry/type, refresh rotation, revoked-token reuse, concurrent refresh reuse and logout.
- Admin/director/manager/analyst/employee boundaries, department filtering, employee's explicitly linked orders/decisions, restricted audit.
- Creation and editing of orders/decisions/tasks, review and verification, histories, no automatic decision completion, optimistic version conflicts and concurrent Idempotency-Key requests.
- Seed volume and repeatability; 12 KPI; defect/financial/HR calculations; threshold boundaries; product filters and ignored HR filter; inclusive Minsk dates; first purchase across scoped history; loaded empty data versus missing source; future-period Dashboard.
- Alert manual closure, no reopening on recalculation; history and drill-down.
- Sales/production/finance/HR summaries, financial reconciliation, four-week forecast, deficit/reserve and missing capacity for a demanded pair.
- Partial imports, duplicates, upserts, invalid links, won deal without an order, all supplied JSON/CSV samples and replay without duplicates; quality checks and preservation of unchecked issues.
- Signed BI JWT, immutable manager department, fail-closed configuration; actual native SQL templates against API totals; execution of the BI-role SQL setup and denial of base/auth/audit table reads.
- Demo restoration preserving credentials, audit and decision history.

Before the modular refactor, a separate real HTTP smoke test started Uvicorn on an ephemeral local port, applied the full Alembic revision chain to a fresh temporary database, ran the seed CLI and exercised health, login, 12 KPI, task creation/replay/update, forecast and OpenAPI. It passed. This was a Backend network test; no browser or Frontend was involved.

Also passed: Ruff lint/format, compileall, Bash syntax for start.sh, `git diff --check`, README link and sample JSON checks, deterministic OpenAPI re-export. YAML parsed successfully; this does not substitute for running GitHub Actions or Render Blueprint validation.

## Modular refactor and agreed assumptions

Large schemas/models were split into domain packages; seed now coordinates six stages with a shared context. Existing import facades remain available. PostgreSQL table/index SQL was compared before/after: all 29 definitions are identical. OpenAPI was compared in full: the only change is the user-approved nullable `CampaignOut.budget`.

Manager sees campaigns linked to their department, including shared campaigns, with `budget=null`. Other authorized roles retain the global budget. New integration tests verify this scope, the hidden budget, and that an own-department support record does not grant access to a linked foreign-department order. Passwords are excluded from seed-context representation.

## Checkpoint, integrity fixes and shell launchers

- Local checkpoint commit `6a1277c` (`feat: add Photoprint MVP backend`) saved the reviewed MVP. Five CSV samples were normalized to LF and compared with JSON; sample import/replay passed. Local environment secrets and ignored coordination files were excluded. No push was performed.
- Shared order/deal validation now checks customer, department, optional deal product and occupied links in both directions. API failures return 422. Import failures reject only the bad record; accepted records remain committed. Updates and reverse-only references cannot bypass the checks by omitting the direct reference. Valid replay and updates remain supported.
- Failed independent audit writes emit a safe structured ERROR with request ID and original HTTP status. Tests force audit commit failures for 403/409/422 and verify unchanged API refusals and absence of credential/exception contents in responses and logs.
- Five executable wrappers in `sh/` call the existing seed/import/export/start/test entrypoints. Tests use a fake uv process from another cwd to verify arguments (including spaces/metacharacters) and exit-status propagation, without executing real seed, imports or migrations.
- Final full suite: 84 passed in 49.87s on temporary PostgreSQL, no skips. Ruff lint/format, unchanged production OpenAPI re-export, Bash syntax for all wrappers, compileall and diff checks passed. No schema changes or migrations were introduced.

## Prepared, not verified in the target environment

- Dockerfile and GitHub Actions workflow were written. Docker build, image vulnerability scan and GitHub runner execution were not performed locally.
- Render Blueprint and migration-at-start entrypoint were written. No Render service was provisioned or deployed, no Git push was made.
- Remote PostgreSQL/Supabase credentials were not used; remote migrations and seed were not executed.
- BI views, role SQL, queries and token endpoint were tested locally. A real Metabase instance, actual dashboard filters, manager iframe isolation and token expiry in Metabase still require deployment checks. The API returns 503 until configuration and the verified-dashboard gate are supplied.
- Frontend integration, visual checks and mobile/browser behavior were not tested.

## Next integration steps

1. Review connection targets, configure deployment secrets/origins and apply migrations to the designated demo database.
2. Load seed once using private DEMO passwords; verify remote health/login/KPI/workflow.
3. Configure Metabase as described in [bi/README.md](bi/README.md), test every card's locked scope, then enable only verified dashboard keys.
4. Connect Frontend using [openapi.json](openapi.json), and verify persistence, roles, conflicts and the complete Alert → decision → task → result review scenario.

Commands and credentials variable names are documented in [README.md](README.md). Implementation assumptions and local coordination are in gitignored root files; they must be shared explicitly across clones.
