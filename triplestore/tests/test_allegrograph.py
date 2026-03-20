# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0

"""
Tests for the AllegroGraph backend of the triplestore abstraction layer.

All operations are scoped within the named graph 'http://example.org/test',
and use a local AllegroGraph instance with SPARQL HTTP API access.
"""

import tempfile
import time
from pathlib import Path

import pytest
import requests
from triplestore import Triplestore

# SPARQL Test Data
SUBJECT = "http://example.org/s"
PREDICATE = "http://example.org/p"
OBJECT = "http://example.org/o"
SPARQL_QUERY = "SELECT ?s ?p ?o WHERE { GRAPH <http://example.org/test> { ?s ?p ?o } }"

# Repository configuration
REPO_NAME = f"testns-{int(time.time())}"


# Connection configuration
config = {
    "base_url": "http://localhost:10035",
    "name": REPO_NAME,
    "graph": "http://example.org/test"
}


def is_allegrograph_available():
    try:
        url = config["base_url"]
        response = requests.get(url, timeout=2)
    except requests.RequestException:
        return False
    else:
        return response.status_code in {200, 401, 403}


pytestmark = pytest.mark.skipif(
    not is_allegrograph_available(),
    reason=f"AllegroGraph instance is not reachable at {config['base_url']}"
)


def test_add_and_query_triple():
    """Test adding a triple and retrieving it via SPARQL."""
    store = Triplestore("allegrograph", config=config)
    store.clear()
    store.add(SUBJECT, PREDICATE, OBJECT)
    results = store.query(SPARQL_QUERY)
    bindings = [str(binding) for binding in results]
    assert any(SUBJECT in b and PREDICATE in b and OBJECT in b for b in bindings)


def test_multiple_triples_query():
    """Test querying multiple triples with the same predicate-object pair."""
    store = Triplestore("allegrograph", config=config)
    store.clear()
    store.add("http://example.org/s1", PREDICATE, OBJECT)
    store.add("http://example.org/s2", PREDICATE, OBJECT)
    results = store.query("SELECT ?s WHERE { ?s <http://example.org/p> <http://example.org/o> }")
    subjects = [str(row["s"]).strip("<>") for row in results]
    assert "http://example.org/s1" in subjects
    assert "http://example.org/s2" in subjects
    assert len(subjects) == 2


def test_delete_triple():
    """Test that deleting a triple removes it from the store."""
    store = Triplestore("allegrograph", config=config)
    store.clear()
    store.add(SUBJECT, PREDICATE, OBJECT)
    assert len(store.query(SPARQL_QUERY)) == 1
    store.delete(SUBJECT, PREDICATE, OBJECT)
    results = store.query(SPARQL_QUERY)
    assert len(results) == 0


def test_query_roundtrip_add():
    """Test add-delete-add cycle to ensure consistent state after re-adding a triple."""
    store = Triplestore("allegrograph", config=config)
    store.clear()
    store.add(SUBJECT, PREDICATE, OBJECT)
    initial_results = store.query(SPARQL_QUERY)
    row = next(iter(initial_results))
    s = str(row["s"]).strip("<>")
    p = str(row["p"]).strip("<>")
    o = str(row["o"]).strip("<>")
    store.delete(s, p, o)
    after_delete = store.query(SPARQL_QUERY)
    assert not any(str(r["s"]).strip("<>") == s and str(r["p"]).strip("<>") == p and str(r["o"]).strip("<>") == o for r in after_delete)
    store.add(s, p, o)
    final_results = store.query(SPARQL_QUERY)
    count = sum(1 for r in final_results if str(r["s"]).strip("<>") == s and str(r["p"]).strip("<>") == p and str(r["o"]).strip("<>") == o)
    assert count == 1


def test_query_returns_empty_when_no_match():
    """Test that a SPARQL query returns no results when no match exists."""
    store = Triplestore("allegrograph", config=config)
    store.clear()
    store.add(SUBJECT, PREDICATE, OBJECT)
    results = store.query("SELECT ?s WHERE { <http://example.org/unknown> ?p ?o }")
    assert len(results) == 0


def test_load_from_turtle_file():
    """Test loading triples from a .ttl file into the store."""
    turtle_data = "<http://example.org/s> <http://example.org/p> <http://example.org/o> ."
    with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".ttl", encoding="utf-8") as f:
        f.write(turtle_data)
        tmp_path = f.name
    store = Triplestore("allegrograph", config=config)
    store.clear()
    store.load(tmp_path)
    results = store.query(SPARQL_QUERY)
    Path(tmp_path).unlink()
    bindings = [str(binding) for binding in results]
    assert any(SUBJECT in b and PREDICATE in b and OBJECT in b for b in bindings)


def test_clear():
    """Test that clear() removes all triples from the store."""
    store = Triplestore("allegrograph", config=config)
    store.add(SUBJECT, PREDICATE, OBJECT)
    store.clear()
    results = store.query(SPARQL_QUERY)
    assert len(results) == 0


def test_clear_twice_is_safe():
    """Test that calling clear() multiple times doesn't raise or fail."""
    store = Triplestore("allegrograph", config=config)
    store.clear()
    store.clear()
    store.add(SUBJECT, PREDICATE, OBJECT)
    store.clear()
    results = store.query(SPARQL_QUERY)
    assert len(results) == 0


def test_execute():
    """End-to-end test for execute(): INSERT/DELETE/CLEAR + ASK/SELECT/DESCRIBE/CONSTRUCT."""
    store = Triplestore("allegrograph", config=config)
    store.clear()

    graph = config["graph"]

    # INSERT DATA
    q = f"INSERT DATA {{ GRAPH <{graph}> {{ <{SUBJECT}> <{PREDICATE}> <{OBJECT}> }} }}"
    out = store.execute(q)
    assert out is None

    # ASK
    ask_q = q = f"ASK WHERE {{ GRAPH <{graph}> {{ <{SUBJECT}> <{PREDICATE}> <{OBJECT}> }} }}"
    ask_res = store.execute(q)
    assert isinstance(ask_res, bool)
    assert ask_res is True

    # SELECT
    q = f"""
        SELECT ?s WHERE {{
            GRAPH <{graph}> {{
                ?s <{PREDICATE}> <{OBJECT}>
            }}
        }}
    """
    sel = store.execute(q)
    assert isinstance(sel, list)
    assert len(sel) == 1
    subjects = [str(r["s"]).strip("<>") for r in sel]
    assert SUBJECT in subjects

    # DESCRIBE
    q = f"DESCRIBE <{SUBJECT}>"
    desc = store.execute(q)
    assert isinstance(desc, str)
    assert SUBJECT in desc

    # CONSTRUCT
    q = f"""
        CONSTRUCT {{ ?s ?p ?o }}
        WHERE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}
    """
    cons = store.execute(q)
    assert isinstance(cons, str)
    assert SUBJECT in cons
    assert PREDICATE in cons
    assert OBJECT in cons

    # DELETE DATA
    q = f"DELETE DATA {{ GRAPH <{graph}> {{ <{SUBJECT}> <{PREDICATE}> <{OBJECT}> }} }}"
    del_out = store.execute(q)
    assert del_out is None
    assert store.execute(ask_q) is False

    # Re-insert duplicates and CLEAR GRAPH
    store.execute(f"""
        INSERT DATA {{
            GRAPH <{graph}> {{
                <{SUBJECT}> <{PREDICATE}> <{OBJECT}> .
                <{SUBJECT}> <{PREDICATE}> <{OBJECT}> .
            }}
        }}
    """)
    q = f"CLEAR GRAPH <{graph}>"
    clr_out = store.execute(q)
    assert clr_out is None
    assert store.execute(f"ASK WHERE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}") is False


def test_select_star_returns_all_bound_variables_for_multiple_triples():
    """Test SELECT *: verifies correct binding, completeness, and result integrity."""
    store = Triplestore("allegrograph", config=config)
    store.clear()

    # Insert multiple triples
    triples = [
        ("http://example.org/s1", "http://example.org/p1", "http://example.org/o1"),
        ("http://example.org/s2", "http://example.org/p2", "http://example.org/o2"),
        ("http://example.org/s3", "http://example.org/p3", "http://example.org/o3"),
    ]

    for s, p, o in triples:
        store.add(s, p, o)

    # SELECT * query
    results = store.query(
        f"""
        SELECT * WHERE {{
            GRAPH <{config["graph"]}> {{
                ?s ?p ?o
            }}
        }}
        """
    )

    # Check number of results
    assert len(results) == len(triples)

    expected_rows = [{"s": s, "p": p, "o": o} for s, p, o in triples]

    # Check that all variables are present in each row
    for row in results:
        assert set(row.keys()) == {"s", "p", "o"}

    # Check that all values are valid (strings and not None)
    for row in results:
        for v in row.values():
            assert isinstance(v, str)
            assert v is not None

    # Check exact match between expected and actual results (order-independent)
    assert {tuple(sorted(r.items())) for r in results} == \
           {tuple(sorted(r.items())) for r in expected_rows}

    # Ensure no duplicate rows are returned
    assert len(results) == len({tuple(sorted(r.items())) for r in results})
