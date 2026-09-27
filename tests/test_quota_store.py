"""SQLite quota stays fair under concurrency and survives reopening."""

from concurrent.futures import ThreadPoolExecutor

from nabiz.console.quota import Tier
from nabiz.console.quota_store import PersistentQuotaBook


def book(path):
    return PersistentQuotaBook(path, {"cihaz": Tier("cihaz", "Cihaz", 20, 60),
                                      "eposta": Tier("eposta", "Hesap", 60, 180),
                                      "ibb": Tier("ibb", "Örnek", 150, 450)})


def test_fifty_concurrent_admissions_and_reopen(tmp_path) -> None:
    path = tmp_path / "quota.sqlite"
    first = book(path)
    holder = first.holder(device="a" * 20, host="127.0.0.1")
    with ThreadPoolExecutor(max_workers=20) as pool:
        admitted = list(pool.map(lambda _: book(path).admit(holder), range(50)))
    assert sum(admitted) == 20
    reopened = book(path)
    assert reopened.holder(device="a" * 20, host="127.0.0.1").key == holder.key
    assert reopened.status(holder)["questions_left"] == 0


def test_neighbours_have_independent_limits_and_atomic_calls(tmp_path) -> None:
    store = book(tmp_path / "quota.sqlite")
    a = store.holder(device="a" * 20, host="192.0.2.1")
    b = store.holder(device="b" * 20, host="192.0.2.1")
    with ThreadPoolExecutor(max_workers=20) as pool:
        reserved = list(pool.map(lambda _: store.reserve_calls(a, 1), range(90)))
    assert sum(reserved) == 60
    assert store.calls_left(a) == 0 and store.calls_left(b) == 60
    assert store.admit(b) and store.status(b)["questions_left"] == 19
    store.refund_calls(a, 1)
    assert store.calls_left(a) == 1


def test_account_tiers_and_erasure(tmp_path) -> None:
    store = book(tmp_path / "quota.sqlite")
    account = store.holder(device=None, host=None, account_id="account-a", tier="eposta")
    other = store.holder(device=None, host=None, account_id="account-b", tier="eposta")
    assert store.status(account)["questions_limit"] == 60
    assert store.admit(account)
    assert store.status(other)["questions_left"] == 60
    assert store.erase_account("account-a") == 1
    assert store.status(account)["questions_left"] == 60


def test_fresh_device_ids_stay_under_the_address_cap(tmp_path) -> None:
    store = book(tmp_path / "quota.sqlite")
    admitted = sum(store.admit(store.holder(device=f"{n:020d}", host="192.0.2.7")) for n in range(120))
    assert admitted == 20 * 5, "a new device id per request must not mint new questions"
    assert store.admit(store.holder(device="c" * 20, host="192.0.2.8")), "another address is unaffected"
