"""Argon2id password hashing for the Identity service.

Hashing and verification are CPU- and memory-bound (about 64 MiB per call), so they
run on a small dedicated thread pool instead of the event loop or the default
executor. The pool size bounds peak memory: MAX_WORKERS * MEMORY_COST_KIB.

Password length rules (10-128 characters) belong to the request schema, not here.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Final

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError

# Parameters are pinned so that a library upgrade cannot silently change them.
# Changing any of them is an Identity decision; existing hashes keep working and are
# flagged by needs_rehash().
TIME_COST: Final = 3
MEMORY_COST_KIB: Final = 65_536
PARALLELISM: Final = 1
MAX_WORKERS: Final = 4

# Hash of a random password that was discarded right after hashing. Used only to make
# the "unknown email" login path cost the same as a real verification. It must be
# generated with the parameters above; tests fail if it drifts out of sync.
DUMMY_HASH: Final = (
    "$argon2id$v=19$m=65536,t=3,p=1$JBKjMSxM4IM9CA4XZPPnUA$"
    "lDW5TUiQWNNywi0VP85nh1vD3k+fpa7eG9opXV+tzSE"
)

_hasher = PasswordHasher(
    time_cost=TIME_COST,
    memory_cost=MEMORY_COST_KIB,
    parallelism=PARALLELISM,
    type=Type.ID,
)
_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="identity-argon2")


async def hash_password(password: str) -> str:
    """Return the Argon2id encoded hash of ``password`` (random salt per call)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, partial(_hasher.hash, password))


async def verify_password(*, password: str, password_hash: str) -> bool:
    """Return True if ``password`` matches ``password_hash``, False on mismatch.

    Keyword-only so the two strings cannot be swapped by accident. A malformed hash
    is corrupted data, not a wrong password: the argon2 error propagates.
    """
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            _executor, partial(_hasher.verify, password_hash, password)
        )
    except VerifyMismatchError:
        return False


async def verify_against_dummy(password: str) -> bool:
    """Spend one verification's worth of work and always return False.

    Call this when the email does not exist (or the account has no password) so the
    response time does not reveal which emails are registered.
    """
    await verify_password(password=password, password_hash=DUMMY_HASH)
    return False


def needs_rehash(password_hash: str) -> bool:
    """True if the hash was made with parameters other than the current ones."""
    return _hasher.check_needs_rehash(password_hash)
