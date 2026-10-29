# Development scripts

Service run scripts will be implemented in setup step 6. For commands verified in step 1, see [setup step 1](../docs/development/SETUP-STEP-1.md).

`database.py` supports explicit bootstrap, upgrade/current/check/revision and runtime permission inspection. See [step 3](../docs/development/SETUP-STEP-3.md) for environment variables, target guards and apply flags. It never runs on API startup and does not contain credentials.
