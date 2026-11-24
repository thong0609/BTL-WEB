import asyncio
import threading
import time

import pytest
from argon2 import PasswordHasher, Type, extract_parameters
from argon2.exceptions import InvalidHashError

from commerce_identity import passwords

PASSWORD = "correct horse battery staple"


def test_hash_is_argon2id_with_pinned_parameters() -> None:
    encoded = asyncio.run(passwords.hash_password(PASSWORD))

    assert encoded.startswith("$argon2id$")
    parameters = extract_parameters(encoded)
    assert parameters.type is Type.ID
    assert parameters.time_cost == passwords.TIME_COST == 3
    assert parameters.memory_cost == passwords.MEMORY_COST_KIB == 65_536
    assert parameters.parallelism == passwords.PARALLELISM == 1


def test_verify_accepts_correct_and_rejects_wrong_password() -> None:
    async def scenario() -> tuple[bool, bool, bool]:
        encoded = await passwords.hash_password(PASSWORD)
        return (
            await passwords.verify_password(password=PASSWORD, password_hash=encoded),
            await passwords.verify_password(password=PASSWORD + "x", password_hash=encoded),
            await passwords.verify_password(password=PASSWORD.upper(), password_hash=encoded),
        )

    assert asyncio.run(scenario()) == (True, False, False)


def test_each_hash_uses_a_fresh_salt() -> None:
    async def scenario() -> tuple[str, str]:
        return await passwords.hash_password(PASSWORD), await passwords.hash_password(PASSWORD)

    first, second = asyncio.run(scenario())

    assert first != second


@pytest.mark.parametrize("password", ["x" * 128, "mật khẩu mạnh 🔐 đây"])
def test_long_and_unicode_passwords_round_trip(password: str) -> None:
    async def scenario() -> tuple[bool, bool]:
        encoded = await passwords.hash_password(password)
        return (
            await passwords.verify_password(password=password, password_hash=encoded),
            await passwords.verify_password(password=password[:-1], password_hash=encoded),
        )

    assert asyncio.run(scenario()) == (True, False)


def test_malformed_hash_raises_instead_of_reporting_a_wrong_password() -> None:
    with pytest.raises(InvalidHashError):
        asyncio.run(passwords.verify_password(password=PASSWORD, password_hash="not-a-hash"))


def test_needs_rehash_flags_only_hashes_with_other_parameters() -> None:
    current = PasswordHasher(
        time_cost=passwords.TIME_COST,
        memory_cost=passwords.MEMORY_COST_KIB,
        parallelism=passwords.PARALLELISM,
        type=Type.ID,
    ).hash(PASSWORD)
    weaker = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1, type=Type.ID).hash(PASSWORD)

    assert passwords.needs_rehash(current) is False
    assert passwords.needs_rehash(weaker) is True


def test_dummy_hash_is_valid_and_uses_current_parameters() -> None:
    assert passwords.needs_rehash(passwords.DUMMY_HASH) is False
    assert asyncio.run(passwords.verify_against_dummy(PASSWORD)) is False


class _RecordingHasher:
    """Stands in for the real hasher to observe where and how often work runs."""

    def __init__(self) -> None:
        self.threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._running = 0
        self.peak = 0

    def _work(self) -> None:
        with self._lock:
            self.threads.append(threading.current_thread())
            self._running += 1
            self.peak = max(self.peak, self._running)
        time.sleep(0.05)
        with self._lock:
            self._running -= 1

    def hash(self, password: str) -> str:
        self._work()
        return "hashed"

    def verify(self, password_hash: str, password: str) -> bool:
        self._work()
        return True


def test_work_runs_off_the_event_loop_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _RecordingHasher()
    monkeypatch.setattr(passwords, "_hasher", recorder)

    async def scenario() -> int:
        await passwords.hash_password(PASSWORD)
        await passwords.verify_password(password=PASSWORD, password_hash="hashed")
        return threading.get_ident()

    loop_thread = asyncio.run(scenario())

    assert len(recorder.threads) == 2
    assert all(thread.ident != loop_thread for thread in recorder.threads)
    assert all(thread.name.startswith("identity-argon2") for thread in recorder.threads)


def test_dummy_verification_performs_real_work_and_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _RecordingHasher()
    monkeypatch.setattr(passwords, "_hasher", recorder)

    # The recorder's verify() answers True, so a False result also proves the
    # dummy path never lets a match through.
    assert asyncio.run(passwords.verify_against_dummy(PASSWORD)) is False
    assert len(recorder.threads) == 1


def test_concurrent_work_is_bounded_by_max_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _RecordingHasher()
    monkeypatch.setattr(passwords, "_hasher", recorder)

    async def scenario() -> None:
        await asyncio.gather(*(passwords.hash_password(PASSWORD) for _ in range(12)))

    asyncio.run(scenario())

    assert len(recorder.threads) == 12
    assert recorder.peak <= passwords.MAX_WORKERS
