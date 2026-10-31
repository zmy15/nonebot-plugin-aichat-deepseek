def test_build_messages_keeps_recent_turns(store_cls) -> None:
    store = store_cls(max_turns=2)
    store.add_turn("u1", "q1", "a1")
    store.add_turn("u1", "q2", "a2")
    store.add_turn("u1", "q3", "a3")

    assert store.build_messages("u1") == [
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "q3"},
        {"role": "assistant", "content": "a3"},
    ]


def test_sessions_are_isolated(store_cls) -> None:
    store = store_cls(max_turns=5)
    store.add_turn("u1", "q1", "a1")
    store.add_turn("u2", "q2", "a2")

    assert store.build_messages("u1") == [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
    ]
    assert store.build_messages("u2") == [
        {"role": "user", "content": "q2"},
        {"role": "assistant", "content": "a2"},
    ]
    assert store.build_messages("missing") == []


def test_zero_turns_disables_history(store_cls) -> None:
    store = store_cls(max_turns=0)
    store.add_turn("u1", "q1", "a1")
    assert store.build_messages("u1") == []


def test_clear_removes_history(store_cls) -> None:
    store = store_cls(max_turns=5)
    store.add_turn("u1", "q1", "a1")
    store.clear("u1")
    assert store.build_messages("u1") == []


def test_lock_is_stable_per_session(store_cls) -> None:
    store = store_cls()
    assert store.lock("u1") is store.lock("u1")
    assert store.lock("u1") is not store.lock("u2")
