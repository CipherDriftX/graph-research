from __future__ import annotations

import psycopg
import pytest
from psycopg_pool import ConnectionPool

import src.db.connection as db_conn
from src.db.connection import (
    close_pools,
    get_connection,
    get_pool,
    put_connection,
)


@pytest.fixture(autouse=True)
def _reset_pools():
    close_pools()
    yield
    close_pools()


class TestConnectionPool:
    def test_get_pool_creates_singleton(self, mocker):
        mock_pool = mocker.MagicMock(spec=ConnectionPool)
        mocker.patch("src.db.connection.ConnectionPool", return_value=mock_pool)

        p1 = get_pool()
        p2 = get_pool()

        assert p1 is p2
        assert p1 is mock_pool

    def test_get_pool_passes_config(self, mocker):
        mock_pool = mocker.MagicMock(spec=ConnectionPool)
        mock_constructor = mocker.patch(
            "src.db.connection.ConnectionPool", return_value=mock_pool
        )

        get_pool()

        mock_constructor.assert_called_once()
        _, kwargs = mock_constructor.call_args
        assert kwargs["min_size"] == 2
        assert kwargs["max_size"] == 10
        assert kwargs["timeout"] == 8.0

    def test_get_pool_construction_never_blocks(self, mocker):
        """Regression: `open=True` makes the ConnectionPool constructor itself
        call open(wait=True) and block up to `timeout` — and if that raises,
        `_pool` is never assigned, so the *next* call reconstructs from
        scratch and blocks again. Every request against an unreachable store
        paid that wait independently, forever. Construction must be
        non-blocking (`open=False` + an explicit `open(wait=False)`), so the
        pool object is memoized on the first call regardless of whether
        Postgres is reachable yet."""
        mock_pool = mocker.MagicMock(spec=ConnectionPool)
        mock_constructor = mocker.patch(
            "src.db.connection.ConnectionPool", return_value=mock_pool
        )

        get_pool()

        _, kwargs = mock_constructor.call_args
        assert kwargs["open"] is False
        mock_pool.open.assert_called_once_with(wait=False)

    def test_get_pool_reused_even_after_a_failed_open(self, mocker):
        """The pool object must stay memoized so its background reconnect
        workers keep retrying across requests, instead of every request
        constructing (and blocking on) a brand-new pool."""
        mock_pool = mocker.MagicMock(spec=ConnectionPool)
        mocker.patch("src.db.connection.ConnectionPool", return_value=mock_pool)

        p1 = get_pool()
        mock_pool.getconn.side_effect = TimeoutError("store unreachable")
        with pytest.raises(TimeoutError):
            get_connection()

        p2 = get_pool()
        assert p1 is p2

    def test_get_connection_delegates_to_pool(self, mocker):
        mock_pool = mocker.MagicMock(spec=ConnectionPool)
        mock_conn = mocker.MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mocker.patch("src.db.connection.ConnectionPool", return_value=mock_pool)

        conn = get_connection()

        assert conn is mock_conn
        mock_pool.getconn.assert_called_once()

    def test_put_connection_returns_to_pool(self, mocker):
        mock_pool = mocker.MagicMock(spec=ConnectionPool)
        mock_conn = mocker.MagicMock()
        mocker.patch("src.db.connection.ConnectionPool", return_value=mock_pool)

        put_connection(mock_conn)

        mock_pool.putconn.assert_called_once_with(mock_conn)

    def test_get_connection_delegates_sync(self, mocker):
        mock_pool = mocker.MagicMock(spec=ConnectionPool)
        mock_conn = mocker.MagicMock()
        mock_pool.getconn.return_value = mock_conn
        mocker.patch("src.db.connection.ConnectionPool", return_value=mock_pool)

        conn = get_connection()

        assert conn is mock_conn
        mock_pool.getconn.assert_called_once()

    def test_close_pools_cleans_up(self, mocker):
        mock_sync = mocker.MagicMock(spec=ConnectionPool)
        mocker.patch("src.db.connection.ConnectionPool", return_value=mock_sync)

        get_pool()
        assert db_conn._pool is not None

        close_pools()

        mock_sync.close.assert_called_once()
        assert db_conn._pool is None


class TestCheckpointer:
    @pytest.fixture(autouse=True)
    def _reset_setup_memo(self, mocker):
        """Table creation is memoized per process; unset it so each test sees
        the first-call behaviour."""
        import src.db.checkpointer as cp

        mocker.patch.object(cp, "_tables_ready", False)

    def test_sync_saver_is_built_on_the_project_pool(self, mocker):
        import src.db.checkpointer as cp

        mock_pool = mocker.MagicMock(spec=ConnectionPool)
        mocker.patch.object(cp, "get_pool", return_value=mock_pool)
        mocker.patch.object(cp, "_ensure_checkpoint_tables")
        mock_saver_cls = mocker.patch.object(cp, "PostgresSaver")

        result = cp.get_checkpointer()

        mock_saver_cls.assert_called_once_with(mock_pool)
        assert result is mock_saver_cls.return_value

    def test_setup_runs_on_a_dedicated_autocommit_connection(self, mocker):
        """PostgresSaver.setup() issues CREATE INDEX CONCURRENTLY, which
        Postgres refuses inside a transaction block. Pool connections are not
        autocommit — deliberately, since the store depends on explicit
        commit/rollback — so setup gets its own connection."""
        import src.db.checkpointer as cp

        mock_connect = mocker.patch.object(cp.psycopg, "connect")
        mocker.patch.object(cp, "PostgresSaver")

        cp._ensure_checkpoint_tables()

        assert mock_connect.call_args.kwargs["autocommit"] is True

    def test_table_setup_is_memoized(self, mocker):
        import src.db.checkpointer as cp

        mock_connect = mocker.patch.object(cp.psycopg, "connect")
        mocker.patch.object(cp, "PostgresSaver")

        cp._ensure_checkpoint_tables()
        cp._ensure_checkpoint_tables()

        assert mock_connect.call_count == 1

    @pytest.mark.asyncio
    async def test_pipeline_gets_the_async_saver(self, mocker):
        """run_pipeline drives the graph with ainvoke, so LangGraph calls
        aget_tuple/aput. PostgresSaver inherits those as
        `raise NotImplementedError` — a run with the sync saver dies on the
        first superstep, before any node executes."""
        import src.db.checkpointer as cp

        mock_pool = mocker.MagicMock()
        mocker.patch.object(cp, "get_async_pool", new=mocker.AsyncMock(return_value=mock_pool))
        mocker.patch.object(cp, "_ensure_checkpoint_tables")
        mock_async_cls = mocker.patch.object(cp, "AsyncPostgresSaver")

        result = await cp.get_async_checkpointer()

        mock_async_cls.assert_called_once_with(mock_pool)
        assert result is mock_async_cls.return_value