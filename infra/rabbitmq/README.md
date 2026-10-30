# RabbitMQ development boundary

Daily coding can use a separate local RabbitMQ on each member's machine, with the shared transport code and message contract. Supabase remains the shared PostgreSQL database: database writes are visible to the team, while messages stay on the broker that received them. A complete local workflow requires all participating services/workers and their implemented handlers. Cross-machine service integration needs one common broker/vhost; none has been provisioned here.

Inventory, Order and Payment use BROKER_URL in their own ignored .env. Start APIs independently; no worker/consumer is auto-started. Declare transport topology explicitly through scripts/broker.py topology --apply on the intended dev vhost. No business consumer has been implemented yet.

For local development run `scripts/dev.ps1 infra dev init` then `scripts/dev.ps1 infra dev up`. Only RabbitMQ starts. Credentials stay in ignored `infra/.local/dev.env`; native messaging service commands use the host broker by default. Container apps use the internal `rabbitmq` hostname. See [step 6](../../docs/development/SETUP-STEP-6.md) for ports, topology/smoke commands and switching to a configured broker.

For test-only verification, pytest --run-rabbitmq creates and removes its own loopback-only Docker container, random credentials and test vhost. The separate Compose test stack is for manual API/worker/migration testing and guarded resets. Neither path uses or resets the dev broker.

See [step 4](../../docs/development/SETUP-STEP-4.md) for commands, known limitations and verification results.
