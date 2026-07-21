from pathlib import Path

from anime_rss.infrastructure.database import create_database_engine, create_session_factory
from anime_rss.infrastructure.events import EventDispatcher, RegisteredHandler, append_event
from anime_rss.infrastructure.migrations import run_migrations


def test_new_consumer_is_not_starved_by_old_deliveries(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'events.sqlite3'}"
    run_migrations(database_url)
    engine = create_database_engine(database_url)
    sessions = create_session_factory(engine)
    received_by_first: list[str] = []
    received_by_second: list[str] = []

    with sessions.begin() as session:
        for index in range(3):
            append_event(session, name="Example.v1", payload={"index": index})

    first = EventDispatcher(
        sessions,
        {
            "Example.v1": [
                RegisteredHandler(
                    consumer="first.v1",
                    handler=lambda event: received_by_first.append(event.id),
                )
            ]
        },
    )
    assert first.dispatch_until_idle(batch_size=1) == 3

    second = EventDispatcher(
        sessions,
        {
            "Example.v1": [
                RegisteredHandler(
                    consumer="second.v1",
                    handler=lambda event: received_by_second.append(event.id),
                )
            ]
        },
    )
    assert second.dispatch_pending(limit=1) == 1
    assert second.dispatch_until_idle(batch_size=1) == 2
    assert len(received_by_first) == 3
    assert len(received_by_second) == 3
    engine.dispose()
