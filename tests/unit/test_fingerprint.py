from app.domain.fingerprint import fingerprint, normalize_message


def test_volatile_tokens_are_normalized() -> None:
    a = normalize_message(
        "Pod api-7d9f8b6c5-x2k4p OOMKilled at 2026-11-24T10:00:00Z on 10.0.0.12 req 3f2a9c1e-1111-4abc-9def-0123456789ab"
    )
    b = normalize_message(
        "Pod api-5c4b3a2d1-q9w8e OOMKilled at 2026-11-25T11:30:15Z on 10.0.3.7 req 9b8a7c6d-2222-4abc-9def-abcdefabcdef"
    )
    assert a == b


def test_same_error_different_ids_share_fingerprint() -> None:
    assert fingerprint("checkout", "OOM", "killed after 512 MB at 10.1.1.1") == fingerprint(
        "checkout", "OOM", "killed after 1024 MB at 10.2.2.2"
    )


def test_service_and_title_are_part_of_fingerprint() -> None:
    base = fingerprint("checkout", "OOM", "killed")
    assert base != fingerprint("payments", "OOM", "killed")
    assert base != fingerprint("checkout", "Timeout", "killed")
    assert len(base) == 64
