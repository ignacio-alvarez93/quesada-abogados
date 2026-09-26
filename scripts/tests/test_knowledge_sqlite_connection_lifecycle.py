import sqlite3

import pytest

from backend.knowledge.sqlite_repository import (
    SQLiteKnowledgeRepository,
)


class TrackingConnection(
    sqlite3.Connection
):
    pass


class TrackingRepository(
    SQLiteKnowledgeRepository
):
    def __init__(
        self,
        db_path,
    ):
        super().__init__(
            db_path
        )
        self.connections = []

    def _connect(
        self,
    ):
        connection = sqlite3.connect(
            self.db_path,
            factory=TrackingConnection,
        )

        connection.row_factory = (
            sqlite3.Row
        )

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        self.connections.append(
            connection
        )

        return connection


def assert_connection_closed(
    connection,
):
    with pytest.raises(
        sqlite3.ProgrammingError,
    ):
        connection.execute(
            "SELECT 1"
        )


def test_repository_closes_every_sqlite_connection(
    tmp_path,
):
    db_path = (
        tmp_path
        / "knowledge_lifecycle.db"
    )

    repository = (
        TrackingRepository(
            db_path
        )
    )

    repository.initialize_schema()

    assert (
        repository.get_current(
            "BOE",
            "BOE-A-NOT-PRESENT",
        )
        is None
    )

    assert (
        repository.list_revisions(
            "BOE",
            "BOE-A-NOT-PRESENT",
        )
        == ()
    )

    assert (
        len(repository.connections)
        >= 3
    )

    for connection in (
        repository.connections
    ):
        assert_connection_closed(
            connection
        )

    # Importante especialmente en Windows:
    # el fichero debe poder borrarse mientras
    # el objeto repository sigue existiendo.
    db_path.unlink()

    assert not db_path.exists()
