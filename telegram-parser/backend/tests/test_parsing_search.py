from app.tasks.parsing import _expand_chat_search_queries


def test_expand_russian_chat_search_query():
    queries = _expand_chat_search_queries("  Ресницы  ")

    assert queries[0] == "ресницы"
    assert "ресницы чат" in queries
    assert "ресницы канал" in queries
    assert "ресницы сообщество" in queries
    assert "ресницы студия" in queries
    assert "ресницы отзывы" in queries
    assert "чат ресницы" in queries
    assert len(queries) == len(set(queries))
    assert len(queries) == 23


def test_chat_search_query_expansion_can_be_disabled():
    assert _expand_chat_search_queries("Beauty master", enabled=False) == [
        "Beauty master"
    ]
