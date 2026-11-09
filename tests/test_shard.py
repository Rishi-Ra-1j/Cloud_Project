"""Unit tests for worker/worker.py sharding: partition, no overlap, union."""
import os
import sys
from pathlib import Path

os.environ.setdefault("SHARD_INDEX", "0")
os.environ.setdefault("SHARD_COUNT", "2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from worker import shard_commands


def test_shards_partition_the_commands():
    cmds = [{"id": f"C{i:04d}"} for i in range(6)]
    shard0 = shard_commands(cmds)
    assert [c["id"] for c in shard0] == ["C0000", "C0002", "C0004"]


def test_shards_do_not_overlap_and_cover_everything():
    cmds = [{"id": f"C{i:04d}"} for i in range(10)]
    # shard 1 is the complement: line numbers 1, 3, 5, 7, 9
    import worker as w
    w.SHARD_INDEX = 1
    shard1 = w.shard_commands(cmds)
    w.SHARD_INDEX = 0
    shard0 = w.shard_commands(cmds)
    assert {c["id"] for c in shard0} & {c["id"] for c in shard1} == set()
    assert len(shard0) + len(shard1) == 10
