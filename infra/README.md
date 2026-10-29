# Infrastructure workspace

Supabase is the shared development database. [Bootstrap instructions and variable template](supabase/README.md) are prepared in setup step 3; no cloud resources have been changed. Compose and broker configuration remain scheduled for later steps. Tests can create a disposable PostgreSQL container with `pytest --run-postgres`.
