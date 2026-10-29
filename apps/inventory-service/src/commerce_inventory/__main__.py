"""Run this service using its validated port settings."""

import uvicorn

from commerce_inventory.settings import Settings


def main() -> None:
    settings = Settings()
    uvicorn.run(
        "commerce_inventory.main:create_app",
        factory=True,
        host=settings.http_host,
        port=settings.http_port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
