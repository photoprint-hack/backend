from app.core import locks


def test_advisory_lock_keys_are_unique_and_stable():
    keys = [
        locks.RECALCULATION,
        locks.WORKFLOW_ACTION,
        locks.AI_ANALYSIS,
        locks.MARY_INGEST,
        locks.RESPONSIBILITY,
    ]
    assert len(set(keys)) == len(keys)
    assert keys == [178901234, 178901235, 178901236, 178901237, 178901238]
