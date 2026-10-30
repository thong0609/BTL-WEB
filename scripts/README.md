# Development scripts

Service run scripts will be implemented in setup step 6. For commands verified in step 1, see [setup step 1](../docs/development/SETUP-STEP-1.md).

`database.py` supports explicit bootstrap, upgrade/current/check/revision and runtime permission inspection. See [step 3](../docs/development/SETUP-STEP-3.md) for environment variables, target guards and apply flags. It never runs on API startup and does not contain credentials.

`broker.py` supports explicit check, topology --apply and smoke --apply for Inventory/Order/Payment. See [step 4](../docs/development/SETUP-STEP-4.md). It neither starts business consumers nor reads/writes PostgreSQL.

`smoke_web.py` starts isolated loopback Catalog/gateway/Next.js processes to verify the HTTP chain, rewrite headers/cookies and upstream outages. Run with `uv run --locked --all-packages python scripts/smoke_web.py` after installing frontend dependencies. It disables DB/broker, ignores backend dev env files and cleans up its own processes. See [step 5](../docs/development/SETUP-STEP-5.md).
