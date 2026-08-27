from __future__ import annotations

import sqlite3
from pathlib import Path

from data_source_harness.durability import DurableActionState, SQLiteActionJournal
from reference_labs.white_goods.phase4 import FIXED_TIME, service_action


def test_write_ahead_record_survives_reopen_and_tamper_breaks_chain(tmp_path: Path) -> None:
    path = tmp_path / "actions.sqlite3"
    action = service_action()
    journal = SQLiteActionJournal(path)
    journal.prepare(action, "decision-1", FIXED_TIME)
    record = journal.begin(action, FIXED_TIME)
    assert record.state is DurableActionState.EXECUTING
    assert record.attempts == 1
    reopened = SQLiteActionJournal(path)
    assert reopened.pending() == (record,)
    assert reopened.verify()

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE action_events SET attributes_json = ? WHERE sequence = 1", ('{"x":1}',)
        )
    assert not reopened.verify()
