import sqlite3


def test_turn_persists_and_loads(store_cls, tmp_path) -> None:
    db_path = tmp_path / "chat.db"
    store = store_cls(db_path, max_turns=30)
    store.add_turn("1:2", "你好", "你好呀")
    store.close()

    loaded = store_cls(db_path, max_turns=30)
    assert loaded.build_messages("1:2") == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好呀"},
    ]
    loaded.close()


def test_each_turn_writes_two_rows(store_cls, tmp_path) -> None:
    db_path = tmp_path / "chat.db"
    store = store_cls(db_path, max_turns=30)
    store.add_turn("1:2", "q1", "a1")
    store.add_turn("1:2", "q2", "a2")
    store.close()

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT role, content, compressed FROM messages ORDER BY id"
        ).fetchall()

    assert rows == [
        ("user", "q1", 0),
        ("assistant", "a1", 0),
        ("user", "q2", 0),
        ("assistant", "a2", 0),
    ]


def test_compression_marks_messages_and_saves_summary(
    store_cls, tmp_path
) -> None:
    db_path = tmp_path / "chat.db"
    store = store_cls(
        db_path,
        max_turns=30,
        trigger_turns=2,
        batch_messages=4,
    )
    store.add_turn("1:2", "q1", "a1")
    store.add_turn("1:2", "q2", "a2")
    store.add_turn("1:2", "q3", "a3")

    assert store.needs_compression("1:2")
    batch = store.get_compression_batch("1:2")
    assert [message["content"] for message in batch] == ["q1", "a1", "q2", "a2"]

    store.apply_compression("1:2", 4, "前两轮的摘要")
    assert store.needs_compression("1:2") is False
    assert store.get_summary("1:2") == "前两轮的摘要"
    assert store.build_messages("1:2") == [
        {"role": "user", "content": "q3"},
        {"role": "assistant", "content": "a3"},
    ]
    store.close()

    loaded = store_cls(
        db_path,
        max_turns=30,
        trigger_turns=2,
        batch_messages=4,
    )
    assert loaded.get_summary("1:2") == "前两轮的摘要"
    assert loaded.build_messages("1:2") == [
        {"role": "user", "content": "q3"},
        {"role": "assistant", "content": "a3"},
    ]
    loaded.close()

    with sqlite3.connect(db_path) as conn:
        compressed = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE compressed = 1"
        ).fetchone()[0]
    assert compressed == 4


def test_compression_updates_existing_summary(store_cls, tmp_path) -> None:
    store = store_cls(
        tmp_path / "chat.db",
        max_turns=30,
        trigger_turns=1,
        batch_messages=2,
    )
    store.add_turn("1:2", "q1", "a1")
    store.add_turn("1:2", "q2", "a2")

    store.apply_compression("1:2", 2, "第一版摘要")
    store.add_turn("1:2", "q3", "a3")
    assert store.needs_compression("1:2")
    store.apply_compression("1:2", 2, "第二版摘要")

    assert store.get_summary("1:2") == "第二版摘要"
    assert store.build_messages("1:2") == [
        {"role": "user", "content": "q3"},
        {"role": "assistant", "content": "a3"},
    ]
    store.close()


def test_clear_deletes_messages_and_summary(store_cls, tmp_path) -> None:
    db_path = tmp_path / "chat.db"
    store = store_cls(db_path, max_turns=30)
    store.add_turn("1:2", "q1", "a1")
    store.apply_compression("1:2", 2, "摘要")
    store.clear("1:2")
    store.close()

    loaded = store_cls(db_path, max_turns=30)
    assert loaded.build_messages("1:2") == []
    assert loaded.get_summary("1:2") == ""
    loaded.close()

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0] == 0


def test_trigger_zero_disables_compression(store_cls, tmp_path) -> None:
    store = store_cls(
        tmp_path / "chat.db",
        max_turns=30,
        trigger_turns=0,
        batch_messages=2,
    )
    for index in range(40):
        store.add_turn("1:2", f"q{index}", f"a{index}")

    assert store.needs_compression("1:2") is False
    store.close()


def test_database_parent_directory_is_created(store_cls, tmp_path) -> None:
    db_path = tmp_path / "nested" / "data" / "chat.db"
    store = store_cls(db_path, max_turns=30)
    store.add_turn("1:2", "q", "a")
    store.close()

    assert db_path.exists()


def test_build_messages_returns_a_copy(store_cls) -> None:
    store = store_cls(max_turns=30)
    store.add_turn("1:2", "q", "a")

    messages = store.build_messages("1:2")
    messages[0]["content"] = "被修改"

    assert store.build_messages("1:2")[0]["content"] == "q"
    store.close()
