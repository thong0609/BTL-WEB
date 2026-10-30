"""Explicit worker entrypoint; no business consumer handlers are implemented yet."""

from commerce_backend_common.messaging_worker import worker_main
from commerce_payment.settings import Settings

if __name__ == "__main__":
    raise SystemExit(worker_main(Settings))
