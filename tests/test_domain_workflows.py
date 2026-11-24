import pytest

from examples.workflow import CASES, FAULTS, run_case


@pytest.mark.parametrize("case", CASES)
async def test_each_domain_executes_real_a2a_chain_and_shared_context(case):
    result = await run_case(case)
    assert result["status"] == "completed"
    assert result["cut"]["verified"]
    assert result["duplicate_effects"] == result["uncompleted_effects"] == 0
    assert len(result["counts"]) == 3 and all(c["effects"] == 1 for c in result["counts"].values())
    events = result["context"]["updates"]
    assert {e["org"] for e in events} == set(result["counts"])
    assert len({e["spec_hash"] for e in events}) == 1
    assert result["context_updates_verified"]
    assert [e["version"] for e in events] == list(range(2, len(events) + 2))
    assert all(
        m["messages"] > 0 and m["recovery_bytes"] > 0 for m in result["wire_metrics"].values()
    )


@pytest.mark.parametrize("fault", FAULTS[1:])
async def test_real_http_faults_recover_or_fail_closed(fault):
    result = await run_case("commerce", fault)
    expected = (
        "compensated"
        if fault == "upstream_abort"
        else "quarantine"
        if fault in ("permanent_partition", "forged_receipt", "changed_action")
        else "completed"
    )
    assert result["status"] == expected
    assert result["duplicate_effects"] == 0
    assert result["uncompleted_effects"] == 0
    if expected == "completed":
        assert result["cut"]["verified"]
    if expected == "compensated":
        assert all(v["compensated"] == 1 for v in result["counts"].values())
        assert len(result["compensation_receipts"]) == 3


async def test_common_spec_can_forbid_unsupported_compensation():
    from examples.workflow import fixture

    spec = fixture("commerce")["specification"]
    spec["allow_compensation"] = False
    result = await run_case("commerce", "upstream_abort", specification=spec)
    assert result["status"] == "quarantine"
    assert all(v["compensated"] == 0 for v in result["counts"].values())


def test_all_replica_ports_are_reserved_and_distinct_before_start():
    import socket

    from examples.workflow import Workflow

    workflow = Workflow("commerce")
    try:
        assert len(set(workflow.ports.values())) == 6
        for port in workflow.ports.values():
            with socket.socket() as probe, pytest.raises(OSError):
                probe.bind(("127.0.0.1", port))
    finally:
        workflow.close()
