# Infrastructure workspace

Supabase is the shared development database. [Bootstrap instructions and variable template](supabase/README.md) are available from setup step 3; actual dev access is configured locally outside Git. Tests can create a disposable PostgreSQL container with `pytest --run-postgres`. Compose remains a later setup step.

RabbitMQ transport base is now available; [broker instructions](rabbitmq/README.md) describe the shared-dev boundary. `pytest --run-rabbitmq` provisions only a disposable Docker test broker. Compose remains a later setup step. See step 4's development record for the corrected test isolation and the earlier subprocess test that accessed the Catalog dev baseline.
