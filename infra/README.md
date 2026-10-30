# Infrastructure workspace

Supabase is the shared development database. [Bootstrap instructions and variable template](supabase/README.md) are available from setup step 3; actual dev access is configured locally outside Git. `compose.dev.yaml` has no PostgreSQL: by default it starts only local RabbitMQ; the `apps` profile optionally runs the six APIs and Next.js. It has no worker services.

Each member can use a local RabbitMQ while coding. Cross-machine service integration requires a common broker/vhost. See [broker instructions](rabbitmq/README.md) and [step 6](../docs/development/SETUP-STEP-6.md). Supabase data is shared regardless of which broker a member uses.

`compose.test.yaml` supplies a separate PostgreSQL database/vhost named `commerce_test`. Scripts generate ignored credentials under `.local/`, verify ownership/loopback endpoints and restrict `reset --apply` to test volumes. Pytest integration fixtures still create their own disposable containers; they never reset this Compose stack or Supabase. See step 4's record for the earlier isolation correction.
