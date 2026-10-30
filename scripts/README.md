# Development scripts

Service run scripts will be implemented in setup step 6. For commands verified in step 1, see [setup step 1](../docs/development/SETUP-STEP-1.md).

`database.py` supports explicit bootstrap, upgrade/current/check/revision and runtime permission inspection. See [step 3](../docs/development/SETUP-STEP-3.md) for environment variables, target guards and apply flags. It never runs on API startup and does not contain credentials.

`broker.py` supports explicit check, topology --apply and smoke --apply for Inventory/Order/Payment. See [step 4](../docs/development/SETUP-STEP-4.md). It neither starts business consumers nor reads/writes PostgreSQL.
