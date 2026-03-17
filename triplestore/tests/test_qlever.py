# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0

"""
Tests for the QLever backend of the triplestore abstraction layer.

All operations are scoped within the named graph 'http://example.org/test',
and use a local QLever instance with HTTP API access.
"""

import tempfile
from pathlib import Path

import pytest
import requests
from triplestore import Triplestore

SUBJECT = "http://example.org/s"
PREDICATE = "http://example.org/p"
OBJECT = "http://example.org/o"

GRAPH = "http://example.org/test"
EX = "http://example.org/"

PREFIXES = """
PREFIX ex: <http://example.org/>
"""
SPARQL_QUERY = "SELECT ?s ?p ?o WHERE { GRAPH <http://example.org/test> { ?s ?p ?o } }"

WORKDIR = (Path(__file__).resolve().parent / "qlever-test-demo").resolve()

config = {
    "base_url": "http://localhost:7019",
    "graph": GRAPH,
    "dataset": "olympics",
    "working_directory": str(WORKDIR),
}


def test_initialize_server():
    store = Triplestore("qlever", config=config)

    response = requests.get(config["base_url"], timeout=5)
    assert response.status_code in {200, 400, 404, 405}


def test_add_and_query_triple():
    """Test adding a triple and retrieving it via SPARQL."""
    store = Triplestore("qlever", config=config)
    store.clear()

    store.add(SUBJECT, PREDICATE, OBJECT)
    results = store.query(SPARQL_QUERY)

    assert any(
        str(row["s"]).strip("<>") == SUBJECT and
        str(row["p"]).strip("<>") == PREDICATE and
        str(row["o"]).strip("<>") == OBJECT
        for row in results
    )


def test_multiple_triples_query():
    """Test querying multiple triples with the same predicate-object pair."""
    store = Triplestore("qlever", config=config)
    store.clear()

    store.add("http://example.org/s1", PREDICATE, OBJECT)
    store.add("http://example.org/s2", PREDICATE, OBJECT)

    query = f"""
    {PREFIXES}
    SELECT ?s
    WHERE {{
      GRAPH <{GRAPH}> {{
        ?s <{PREDICATE}> <{OBJECT}> .
      }}
    }}
    """
    results = store.query(query)
    subjects = [str(row["s"]).strip("<>") for row in results]

    assert "http://example.org/s1" in subjects
    assert "http://example.org/s2" in subjects
    assert len(subjects) == 2


def test_delete_triple():
    """Test that deleting a triple removes it from the store."""
    store = Triplestore("qlever", config=config)
    store.clear()

    store.add(SUBJECT, PREDICATE, OBJECT)

    before = store.query(f"""
    {PREFIXES}
    SELECT ?o WHERE {{
      GRAPH <{GRAPH}> {{
        <{SUBJECT}> <{PREDICATE}> ?o .
      }}
    }}
    """)
    assert len(before) == 1

    store.delete(SUBJECT, PREDICATE, OBJECT)

    after = store.query(f"""
    {PREFIXES}
    SELECT ?o WHERE {{
      GRAPH <{GRAPH}> {{
        <{SUBJECT}> <{PREDICATE}> ?o .
      }}
    }}
    """)
    assert len(after) == 0


def test_query_roundtrip_add():
    """Test add-delete-add cycle for a triple."""
    store = Triplestore("qlever", config=config)
    store.clear()

    store.add(SUBJECT, PREDICATE, OBJECT)

    initial_results = store.query(SPARQL_QUERY)
    row = next(iter(initial_results))
    s = str(row["s"]).strip("<>")
    p = str(row["p"]).strip("<>")
    o = str(row["o"]).strip("<>")

    store.delete(s, p, o)

    after_delete = store.query(SPARQL_QUERY)
    assert not any(
        str(r["s"]).strip("<>") == s and
        str(r["p"]).strip("<>") == p and
        str(r["o"]).strip("<>") == o
        for r in after_delete
    )

    store.add(s, p, o)

    final_results = store.query(SPARQL_QUERY)
    count = sum(
        1 for r in final_results
        if str(r["s"]).strip("<>") == s and
           str(r["p"]).strip("<>") == p and
           str(r["o"]).strip("<>") == o
    )
    assert count == 1


def test_query_returns_empty_when_no_match():
    """Test that a SPARQL query returns no results when no match exists."""
    store = Triplestore("qlever", config=config)
    store.clear()

    store.add(SUBJECT, PREDICATE, OBJECT)

    results = store.query(f"""
    {PREFIXES}
    SELECT ?s
    WHERE {{
      GRAPH <{GRAPH}> {{
        <http://example.org/unknown> ?p ?o .
      }}
    }}
    """)
    assert len(results) == 0


def test_load_from_turtle_file():
    """Test loading triples from a .ttl file into the store."""
    turtle_data = f"""
    <{SUBJECT}> <{PREDICATE}> <{OBJECT}> .
    """

    with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".ttl", encoding="utf-8") as f:
        f.write(turtle_data)
        tmp_path = f.name

    store = Triplestore("qlever", config=config)
    store.clear()
    store.load(tmp_path)

    results = store.query(SPARQL_QUERY)
    Path(tmp_path).unlink()

    assert any(
        str(row["s"]).strip("<>") == SUBJECT and
        str(row["p"]).strip("<>") == PREDICATE and
        str(row["o"]).strip("<>") == OBJECT
        for row in results
    )


def test_clear():
    """Test that clear() removes all triples from the store."""
    store = Triplestore("qlever", config=config)
    store.clear()

    store.add(SUBJECT, PREDICATE, OBJECT)
    store.add("http://example.org/s2", PREDICATE, "http://example.org/o2")

    store.clear()
    results = store.query(SPARQL_QUERY)

    assert len(results) == 0


def test_clear_twice_is_safe():
    """Test that calling clear() multiple times doesn't raise or fail."""
    store = Triplestore("qlever", config=config)
    store.clear()
    store.clear()

    store.add(SUBJECT, PREDICATE, OBJECT)
    store.clear()
    results = store.query(SPARQL_QUERY)

    assert len(results) == 0


def test_execute():
    """End-to-end test for execute() using standard SPARQL queries."""
    store = Triplestore("qlever", config=config)
    store.clear()

    graph = config["graph"]

    # INSERT DATA
    q = f"""
    INSERT DATA {{
      GRAPH <{graph}> {{
        <{SUBJECT}> <{PREDICATE}> <{OBJECT}> .
      }}
    }}
    """
    out = store.execute(q)
    assert out is None

    # ASK
    ask_q = f"""
    ASK WHERE {{
      GRAPH <{graph}> {{
        <{SUBJECT}> <{PREDICATE}> <{OBJECT}> .
      }}
    }}
    """
    ask_res = store.execute(ask_q)
    assert isinstance(ask_res, bool)
    assert ask_res is True

    # SELECT
    q = f"""
    SELECT ?s
    WHERE {{
      GRAPH <{graph}> {{
        ?s <{PREDICATE}> <{OBJECT}> .
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
    WHERE {{
      GRAPH <{graph}> {{
        ?s ?p ?o .
      }}
    }}
    """
    cons = store.execute(q)
    assert isinstance(cons, str)
    assert SUBJECT in cons
    assert PREDICATE in cons
    assert OBJECT in cons

    # DELETE DATA
    q = f"""
    DELETE DATA {{
      GRAPH <{graph}> {{
        <{SUBJECT}> <{PREDICATE}> <{OBJECT}> .
      }}
    }}
    """
    del_out = store.execute(q)
    assert del_out is None
    assert store.execute(ask_q) is False

    # Re-insert and CLEAR GRAPH
    store.execute(f"""
    INSERT DATA {{
      GRAPH <{graph}> {{
        <{SUBJECT}> <{PREDICATE}> <{OBJECT}> .
      }}
    }}
    """)
    q = f"CLEAR GRAPH <{graph}>"
    clr_out = store.execute(q)
    assert clr_out is None
    assert store.execute(f"ASK WHERE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}") is False


def test_add_duplicate_triple():
    """Test that adding the same triple twice does not create duplicate query results."""
    store = Triplestore("qlever", config=config)
    store.clear()

    store.add(SUBJECT, PREDICATE, OBJECT)
    store.add(SUBJECT, PREDICATE, OBJECT)

    results = store.query(SPARQL_QUERY)

    count = sum(
        1 for r in results
        if str(r["s"]).strip("<>") == SUBJECT and
           str(r["p"]).strip("<>") == PREDICATE and
           str(r["o"]).strip("<>") == OBJECT
    )
    assert count == 1


def test_delete_nonexistent_triple():
    """Test that deleting a triple that does not exist does not raise or affect existing data."""
    store = Triplestore("qlever", config=config)
    store.clear()

    store.add(SUBJECT, PREDICATE, OBJECT)

    store.delete(
        "http://example.org/nonexistentS",
        PREDICATE,
        "http://example.org/nonexistentO",
    )

    results = store.query(f"""
    {PREFIXES}
    SELECT ?o
    WHERE {{
      GRAPH <{GRAPH}> {{
        <{SUBJECT}> <{PREDICATE}> ?o .
      }}
    }}
    """)

    assert len(results) == 1
    assert str(results[0]["o"]).strip("<>") == OBJECT


def test_named_graph():
    """Test that queries scoped to the configured graph do not see triples from another named graph."""
    store = Triplestore("qlever", config=config)
    store.clear()

    other_graph = "http://example.org/other"

    q = f"""
    INSERT DATA {{
      GRAPH <{other_graph}> {{
        <{SUBJECT}> <{PREDICATE}> <{OBJECT}> .
      }}
    }}
    """
    store.execute(q)

    results_in_test_graph = store.query(f"""
    {PREFIXES}
    SELECT ?s ?p ?o
    WHERE {{
      GRAPH <{GRAPH}> {{
        ?s ?p ?o .
      }}
    }}
    """)

    assert len(results_in_test_graph) == 0

    results_in_other_graph = store.query(f"""
    {PREFIXES}
    SELECT ?s ?p ?o
    WHERE {{
      GRAPH <{other_graph}> {{
        ?s ?p ?o .
      }}
    }}
    """)

    assert len(results_in_other_graph) == 1
    row = results_in_other_graph[0]
    assert str(row["s"]).strip("<>") == SUBJECT
    assert str(row["p"]).strip("<>") == PREDICATE
    assert str(row["o"]).strip("<>") == OBJECT


def test_stop_server():
    store = Triplestore("qlever", config=config)
    store.stop_server()

    with pytest.raises(requests.RequestException):
        requests.get(config["base_url"], timeout=2)
