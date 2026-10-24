from importlib import import_module

import pytest


retention = import_module('02_HCM.pnl_retention')


def test_retention_policy_is_positive_and_preserves_safe_defaults():
    policy = retention.PNLRetentionPolicy()
    assert policy.telemetry_days == 30
    with pytest.raises(ValueError):
        retention.PNLRetentionPolicy(telemetry_days=0)


async def test_retention_dry_run_never_deletes():
    class Conn:
        def __init__(self): self.queries = []
        async def fetchval(self, query, *_args): self.queries.append(query); return 0
    conn = Conn()
    result = await retention.purge_pnl_data(conn)
    assert result['execute'] is False
    assert len(conn.queries) == 4
    assert all(query.lstrip().startswith('SELECT') for query in conn.queries)
