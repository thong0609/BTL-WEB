# RabbitMQ development boundary

Shared development needs one reachable broker/vhost and credentials distributed outside Git. Supabase provides the PostgreSQL database, not this RabbitMQ connection. No shared broker has been provisioned in setup step 4.

Inventory, Order and Payment use BROKER_URL in their own ignored .env. Start APIs independently; no worker/consumer is auto-started. Declare transport topology explicitly through scripts/broker.py topology --apply on the intended dev vhost. No business consumer has been implemented yet.

For test-only verification, use pytest --run-rabbitmq: it creates and removes its own loopback-only Docker container, random credentials and test vhost. Do not redirect this fixture to the shared dev broker. Compose configuration is planned for setup step 6.

See [step 4](../../docs/development/SETUP-STEP-4.md) for commands, known limitations and verification results.
