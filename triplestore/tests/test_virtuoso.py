# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0

"""
Tests for the Virtuoso backend of the triplestore abstraction layer.

All operations are scoped within a named graph, and use a local Virtuoso instance with SPARQL HTTP access.
"""
import csv
import json
import tempfile
import time
from pathlib import Path

import pytest
import requests
from triplestore import Triplestore

SUBJECT = "http://example.org/s"
PREDICATE = "http://example.org/p"
OBJECT = "http://example.org/o"

TEST_FILES_DIR = Path(__file__).parent / "tests_files"
TEST_FILES_DIR.mkdir(exist_ok=True)


def is_virtuoso_available():
    try:
        response = requests.get("http://localhost:8890/sparql", timeout=2)
    except requests.RequestException:
        return False
    else:
        return response.status_code in {200, 401, 403}


pytestmark = pytest.mark.skipif(
    not is_virtuoso_available(),
    reason="Virtuoso instance is not reachable at http://localhost:8890/sparql",
)


config = {
    "base_url": "http://localhost:8890",
    "graph": f"http://example.org/testns-{int(time.time())}",
}

SPARQL_QUERY = f"""
SELECT ?s ?p ?o WHERE {{
    GRAPH <{config['graph']}> {{
        ?s ?p ?o
    }}
}}
"""


def test_add_and_query_triple():
    """Test adding a triple and retrieving it via SPARQL."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    store.add(SUBJECT, PREDICATE, OBJECT)
    results = store.query(SPARQL_QUERY)

    bindings = [str(binding) for binding in results]
    assert {"s": SUBJECT, "p": PREDICATE, "o": OBJECT} in results


def test_multiple_triples_query():
    """Test querying multiple triples with the same predicate-object pair."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    store.add("http://example.org/s1", PREDICATE, OBJECT)
    store.add("http://example.org/s2", PREDICATE, OBJECT)

    results = store.query(
        f"SELECT ?s WHERE {{ GRAPH <{config['graph']}> {{ ?s <{PREDICATE}> <{OBJECT}> }} }}"
    )
    subjects = [str(row["s"]).strip("<>") for row in results]

    assert "http://example.org/s1" in subjects
    assert "http://example.org/s2" in subjects
    assert len(subjects) == 2


def test_delete_triple():
    """Test that deleting a triple removes it from the store."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    store.add(SUBJECT, PREDICATE, OBJECT)
    assert len(store.query(SPARQL_QUERY)) == 1

    store.delete(SUBJECT, PREDICATE, OBJECT)
    results = store.query(SPARQL_QUERY)
    assert len(results) == 0


def test_query_roundtrip_add():
    """Test add-delete-add cycle to ensure consistent state after re-adding a triple."""
    store = Triplestore("virtuoso", config=config)
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
        str(r["s"]).strip("<>") == s
        and str(r["p"]).strip("<>") == p
        and str(r["o"]).strip("<>") == o
        for r in after_delete
    )

    store.add(s, p, o)

    final_results = store.query(SPARQL_QUERY)
    count = sum(
        1
        for r in final_results
        if str(r["s"]).strip("<>") == s
        and str(r["p"]).strip("<>") == p
        and str(r["o"]).strip("<>") == o
    )
    assert count == 1


def test_query_returns_empty_when_no_match():
    """Test that a SPARQL query returns no results when no match exists."""
    store = Triplestore("virtuoso", config=config)
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

    store = Triplestore("virtuoso", config=config)
    store.clear()
    store.load(tmp_path)

    results = store.query(SPARQL_QUERY)
    Path(tmp_path).unlink()

    bindings = [str(binding) for binding in results]
    assert any(SUBJECT in b and PREDICATE in b and OBJECT in b for b in bindings)


def test_load_from_ntriples_file():
    """Test loading triples from a .nt file into the store."""
    ntriples_data = "<http://example.org/s> <http://example.org/p> <http://example.org/o> ."

    with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".nt", encoding="utf-8") as f:
        f.write(ntriples_data)
        tmp_path = f.name

    store = Triplestore("virtuoso", config=config)
    store.clear()
    store.load(tmp_path)

    results = store.query(SPARQL_QUERY)
    Path(tmp_path).unlink()

    bindings = [str(binding) for binding in results]
    assert any(SUBJECT in b and PREDICATE in b and OBJECT in b for b in bindings)


def test_load_rejects_unsupported_file_format():
    """Test that load() rejects unsupported RDF file formats."""
    invalid_data = "this is not rdf"

    with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".txt", encoding="utf-8") as f:
        f.write(invalid_data)
        tmp_path = f.name

    store = Triplestore("virtuoso", config=config)

    with pytest.raises(ValueError, match="Unsupported RDF file format"):
        store.load(tmp_path)

    Path(tmp_path).unlink()


def test_clear():
    """Test that clear() removes all triples from the store."""
    store = Triplestore("virtuoso", config=config)
    store.add(SUBJECT, PREDICATE, OBJECT)

    store.clear()
    results = store.query(SPARQL_QUERY)

    assert len(results) == 0


def test_clear_twice_is_safe():
    """Test that calling clear() multiple times doesn't raise or fail."""
    store = Triplestore("virtuoso", config=config)
    store.clear()
    store.clear()

    store.add(SUBJECT, PREDICATE, OBJECT)
    store.clear()
    results = store.query(SPARQL_QUERY)

    assert len(results) == 0


def test_execute():
    """End-to-end test for execute(): INSERT/DELETE/CLEAR + ASK/SELECT/DESCRIBE/CONSTRUCT."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    graph = config["graph"]

    q = f"INSERT DATA {{ GRAPH <{graph}> {{ <{SUBJECT}> <{PREDICATE}> <{OBJECT}> }} }}"
    out = store.execute(q)
    assert out is None

    ask_q = f"ASK WHERE {{ GRAPH <{graph}> {{ <{SUBJECT}> <{PREDICATE}> <{OBJECT}> }} }}"
    ask_res = store.execute(ask_q)
    assert isinstance(ask_res, bool)
    assert ask_res is True

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
    q = f"""
        DESCRIBE <{SUBJECT}>
        FROM <{graph}>
    """
    desc = store.execute(q)
    assert isinstance(desc, str)
    assert "s" in desc
    assert "p" in desc
    assert "o" in desc

    q = f"""
        CONSTRUCT {{ ?s ?p ?o }}
        WHERE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}
    """
    cons = store.execute(q)
    assert isinstance(cons, str)
    assert "s" in cons
    assert "p" in cons
    assert "o" in cons
    assert "@prefix" in desc or "http://example.org/" in cons

    q = f"DELETE DATA {{ GRAPH <{graph}> {{ <{SUBJECT}> <{PREDICATE}> <{OBJECT}> }} }}"
    del_out = store.execute(q)
    assert del_out is None
    assert store.execute(ask_q) is False

    store.execute(
        f"""
        INSERT DATA {{
            GRAPH <{graph}> {{
                <{SUBJECT}> <{PREDICATE}> <{OBJECT}> .
                <{SUBJECT}> <{PREDICATE}> <{OBJECT}> .
            }}
        }}
        """
    )
    q = f"CLEAR GRAPH <{graph}>"
    clr_out = store.execute(q)
    assert clr_out is None
    assert store.execute(f"ASK WHERE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}") is False


def test_select_star():
    """Test SELECT *: verifies correct binding, completeness, and result integrity."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    triples = [
        ("http://example.org/s1", "http://example.org/p1", "http://example.org/o1"),
        ("http://example.org/s2", "http://example.org/p2", "http://example.org/o2"),
        ("http://example.org/s3", "http://example.org/p3", "http://example.org/o3"),
    ]

    for s, p, o in triples:
        store.add(s, p, o)

    results = store.query(
        f"""
        SELECT * WHERE {{
            GRAPH <{config["graph"]}> {{
                ?s ?p ?o
            }}
        }}
        """
    )

    assert len(results) == len(triples)

    expected_rows = [{"s": s, "p": p, "o": o} for s, p, o in triples]

    for row in results:
        assert set(row.keys()) == {"s", "p", "o"}

    for row in results:
        for v in row.values():
            assert isinstance(v, str)
            assert v is not None

    assert {tuple(sorted(r.items())) for r in results} == {
        tuple(sorted(r.items())) for r in expected_rows
    }

    assert len(results) == len({tuple(sorted(r.items())) for r in results})


def test_query_export_json():
    """Test that query() exports SELECT results to a JSON file correctly."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    store.add(SUBJECT, PREDICATE, OBJECT)

    output_file = TEST_FILES_DIR / "virtuoso_results1"
    results = store.query(SPARQL_QUERY, export=True, output_format="json", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "virtuoso_results1.json"

    assert exported_path.exists()
    assert isinstance(results, list)
    assert len(results) == 1

    data = json.loads(exported_path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == 1
    assert data == results

    row = data[0]
    assert row["s"] == SUBJECT
    assert row["p"] == PREDICATE
    assert row["o"] == OBJECT


def test_query_export_csv():
    """Test that query() exports SELECT results to a CSV file correctly."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    store.add(SUBJECT, PREDICATE, OBJECT)

    output_file = TEST_FILES_DIR / "virtuoso_results2"
    results = store.query(SPARQL_QUERY, export=True, output_format="csv", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "virtuoso_results2.csv"

    assert exported_path.exists()
    assert isinstance(results, list)
    assert len(results) == 1

    with exported_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["s"] == SUBJECT
    assert rows[0]["p"] == PREDICATE
    assert rows[0]["o"] == OBJECT


def test_export_csv_with_custom_separator():
    """Test that query() exports SELECT results to CSV using a custom separator."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    store.add(SUBJECT, PREDICATE, OBJECT)

    output_file = TEST_FILES_DIR / "custom_separator"
    results = store.query(SPARQL_QUERY, export=True, output_format="csv", filename=str(output_file), separator=";")

    exported_path = TEST_FILES_DIR / "custom_separator.csv"

    assert exported_path.exists()
    assert isinstance(results, list)
    assert len(results) == 1

    content = exported_path.read_text()
    assert ";" in content

    with exported_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["s"] == SUBJECT
    assert rows[0]["p"] == PREDICATE
    assert rows[0]["o"] == OBJECT


def test_query_export_json_with_existing_extension():
    """Test that query() respects an already-correct filename extension."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    store.add(SUBJECT, PREDICATE, OBJECT)

    output_file = TEST_FILES_DIR / "already_json.json"
    store.query(SPARQL_QUERY, export=True, output_format="json", filename=str(output_file))

    assert output_file.exists()
    assert not (TEST_FILES_DIR / "already_json.json.json").exists()


def test_query_export_replaces_wrong_extension():
    """Test that query() replaces a wrong filename extension with the requested one."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    store.add(SUBJECT, PREDICATE, OBJECT)

    output_file = TEST_FILES_DIR / "results.txt"
    store.query(SPARQL_QUERY, export=True, output_format="csv", filename=str(output_file))

    assert not output_file.exists()
    assert (TEST_FILES_DIR / "results.csv").exists()


def test_query_export_empty_results_json():
    """Test exporting an empty SELECT result set to JSON."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    output_file = TEST_FILES_DIR / "empty_results"
    results = store.query(
        f"""
        SELECT ?s WHERE {{
            GRAPH <{config["graph"]}> {{
                <http://example.org/does-not-exist> ?p ?o
            }}
        }}
        """,
        export=True,
        output_format="json",
        filename=str(output_file),
    )

    exported_path = TEST_FILES_DIR / "empty_results.json"

    assert results == []
    assert exported_path.exists()

    data = json.loads(exported_path.read_text(encoding="utf-8"))
    assert data == []


def test_query_export_empty_results_csv():
    """Test exporting an empty SELECT result set to CSV still creates a valid file."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    output_file = TEST_FILES_DIR / "empty_results"
    results = store.query(
        f"""
        SELECT ?s WHERE {{
            GRAPH <{config["graph"]}> {{
                <http://example.org/does-not-exist> ?p ?o
            }}
        }}
        """,
        export=True,
        output_format="csv",
        filename=str(output_file),
    )

    exported_path = TEST_FILES_DIR / "empty_results.csv"

    assert results == []
    assert exported_path.exists()

    with exported_path.open("r", encoding="utf-8", newline="") as f:
        content = f.read()

    assert not content.strip()


def test_query_rejects_non_select_query():
    """Test that query() rejects non-SELECT SPARQL queries."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    with pytest.raises(ValueError, match=r"Only SELECT queries are supported"):
        store.query(f"ASK WHERE {{ GRAPH <{config['graph']}> {{ ?s ?p ?o }} }}")


def test_query_rejects_unsupported_export_format():
    """Test that query() rejects unsupported export formats for SELECT queries."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    with pytest.raises(ValueError, match="Unsupported export format"):
        store.query(SPARQL_QUERY, export=True, output_format="ttl", filename="bad_output")


def test_query_no_export_does_not_create_file():
    """Test that query() does not create any file when export=False."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    store.add(SUBJECT, PREDICATE, OBJECT)

    output_file = TEST_FILES_DIR / "should_not_exist.json"
    results = store.query(SPARQL_QUERY, export=False, output_format="json", filename=str(output_file))

    assert len(results) == 1
    assert not output_file.exists()


def test_query_accepts_prefixed_select_with_export():
    """Test that query() correctly detects SELECT when PREFIX declarations precede it."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    store.add(SUBJECT, PREDICATE, OBJECT)

    sparql = f"""
        PREFIX ex: <http://example.org/>
        SELECT ?s ?p ?o
        WHERE {{
            GRAPH <{config["graph"]}> {{
                ?s ?p ?o
            }}
        }}
    """

    output_file = TEST_FILES_DIR / "prefixed"
    results = store.query(sparql, export=True, output_format="json", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "prefixed.json"

    assert exported_path.exists()
    assert len(results) == 1
    assert results[0]["s"] == SUBJECT
    assert results[0]["p"] == PREDICATE
    assert results[0]["o"] == OBJECT


def test_execute_export_select_json():
    """Test that execute() exports SELECT results to JSON correctly."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    graph = config["graph"]
    store.execute(f"""
        INSERT DATA {{
            GRAPH <{graph}> {{
                <{SUBJECT}> <{PREDICATE}> <{OBJECT}> .
            }}
        }}
    """)

    output_file = TEST_FILES_DIR / "execute_select_json"
    sparql = f"""
        SELECT ?s ?p ?o
        WHERE {{
            GRAPH <{graph}> {{
                ?s ?p ?o
            }}
        }}
    """

    results = store.execute(sparql, export=True, output_format="json", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "execute_select_json.json"

    assert exported_path.exists()
    assert isinstance(results, list)
    assert len(results) == 1

    data = json.loads(exported_path.read_text(encoding="utf-8"))
    assert data == results
    assert data[0]["s"] == SUBJECT
    assert data[0]["p"] == PREDICATE
    assert data[0]["o"] == OBJECT


def test_execute_export_select_csv():
    """Test that execute() exports SELECT results to CSV correctly."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    graph = config["graph"]
    store.execute(f"""
        INSERT DATA {{
            GRAPH <{graph}> {{
                <{SUBJECT}> <{PREDICATE}> <{OBJECT}> .
            }}
        }}
    """)

    output_file = TEST_FILES_DIR / "execute_select_csv"
    sparql = f"""
        SELECT ?s ?p ?o
        WHERE {{
            GRAPH <{graph}> {{
                ?s ?p ?o
            }}
        }}
    """

    results = store.execute(sparql, export=True, output_format="csv", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "execute_select_csv.csv"

    assert exported_path.exists()
    assert isinstance(results, list)
    assert len(results) == 1

    with exported_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["s"] == SUBJECT
    assert rows[0]["p"] == PREDICATE
    assert rows[0]["o"] == OBJECT


def test_execute_export_ask_json():
    """Test that execute() exports ASK results to JSON correctly."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    graph = config["graph"]
    store.execute(f"""
        INSERT DATA {{
            GRAPH <{graph}> {{
                <{SUBJECT}> <{PREDICATE}> <{OBJECT}> .
            }}
        }}
    """)

    output_file = TEST_FILES_DIR / "execute_ask_json"
    sparql = f"ASK WHERE {{ GRAPH <{graph}> {{ <{SUBJECT}> <{PREDICATE}> <{OBJECT}> }} }}"

    result = store.execute(sparql, export=True, output_format="json", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "execute_ask_json.json"

    assert exported_path.exists()
    assert result is True

    data = json.loads(exported_path.read_text(encoding="utf-8"))
    assert data == {"boolean": True}


def test_execute_export_ask_txt():
    """Test that execute() exports ASK results to TXT correctly."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    graph = config["graph"]
    store.execute(f"""
        INSERT DATA {{
            GRAPH <{graph}> {{
                <{SUBJECT}> <{PREDICATE}> <{OBJECT}> .
            }}
        }}
    """)

    output_file = TEST_FILES_DIR / "execute_ask_txt"
    sparql = f"ASK WHERE {{ GRAPH <{graph}> {{ <{SUBJECT}> <{PREDICATE}> <{OBJECT}> }} }}"

    result = store.execute(sparql, export=True, output_format="txt", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "execute_ask_txt.txt"

    assert exported_path.exists()
    assert result is True
    assert exported_path.read_text(encoding="utf-8").strip() == "true"


def test_execute_export_construct_ttl():
    """Test that execute() exports CONSTRUCT results to Turtle correctly."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    graph = config["graph"]
    store.execute(f"""
        INSERT DATA {{
            GRAPH <{graph}> {{
                <{SUBJECT}> <{PREDICATE}> <{OBJECT}> .
            }}
        }}
    """)

    output_file = TEST_FILES_DIR / "execute_construct"
    sparql = f"""
        CONSTRUCT {{ ?s ?p ?o }}
        WHERE {{
            GRAPH <{graph}> {{
                ?s ?p ?o
            }}
        }}
    """

    result = store.execute(sparql, export=True, output_format="ttl", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "execute_construct.ttl"

    assert exported_path.exists()
    assert isinstance(result, str)

    content = exported_path.read_text(encoding="utf-8")
    assert content.splitlines() == result.splitlines()
    assert "s" in content
    assert "p" in content
    assert "o" in content


def test_execute_export_describe_ttl():
    """Test that execute() exports DESCRIBE results to Turtle correctly."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    graph = config["graph"]
    store.execute(f"""
        INSERT DATA {{
            GRAPH <{graph}> {{
                <{SUBJECT}> <{PREDICATE}> <{OBJECT}> .
            }}
        }}
    """)

    output_file = TEST_FILES_DIR / "execute_describe"
    sparql = f"""
        DESCRIBE <{SUBJECT}>
        FROM <{graph}>
    """

    result = store.execute(sparql, export=True, output_format="ttl", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "execute_describe.ttl"

    assert exported_path.exists()
    assert isinstance(result, str)

    content = exported_path.read_text(encoding="utf-8")
    assert content.splitlines() == result.splitlines()
    assert "s" in content


def test_execute_export_uses_default_format_for_ask():
    """Test that execute() uses the default export format for ASK when output_format is omitted."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    graph = config["graph"]
    store.execute(f"""
        INSERT DATA {{
            GRAPH <{graph}> {{
                <{SUBJECT}> <{PREDICATE}> <{OBJECT}> .
            }}
        }}
    """)

    output_file = TEST_FILES_DIR / "execute_ask_default"
    sparql = f"ASK WHERE {{ GRAPH <{graph}> {{ <{SUBJECT}> <{PREDICATE}> <{OBJECT}> }} }}"

    result = store.execute(sparql, export=True, filename=str(output_file))

    exported_path = TEST_FILES_DIR / "execute_ask_default.json"

    assert result is True
    assert exported_path.exists()

    data = json.loads(exported_path.read_text(encoding="utf-8"))
    assert data == {"boolean": True}


def test_execute_export_uses_default_format_for_construct():
    """Test that execute() uses the default export format for CONSTRUCT when output_format is omitted."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    graph = config["graph"]
    store.execute(f"""
        INSERT DATA {{
            GRAPH <{graph}> {{
                <{SUBJECT}> <{PREDICATE}> <{OBJECT}> .
            }}
        }}
    """)

    output_file = TEST_FILES_DIR / "execute_construct_default"
    sparql = f"""
        CONSTRUCT {{ ?s ?p ?o }}
        WHERE {{
            GRAPH <{graph}> {{
                ?s ?p ?o
            }}
        }}
    """

    result = store.execute(sparql, export=True, filename=str(output_file))

    exported_path = TEST_FILES_DIR / "execute_construct_default.ttl"

    assert isinstance(result, str)
    assert exported_path.exists()
    assert exported_path.read_text(encoding="utf-8").splitlines() == result.splitlines()


def test_execute_rejects_unsupported_export_format_for_ask():
    """Test that execute() rejects unsupported export formats for ASK queries."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    graph = config["graph"]
    sparql = f"ASK WHERE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}"

    with pytest.raises(ValueError, match="Unsupported export format"):
        store.execute(sparql, export=True, output_format="csv", filename=str(TEST_FILES_DIR / "bad_ask"))


def test_execute_rejects_export_for_update_operations():
    """Test that execute() rejects export for SPARQL update operations."""
    store = Triplestore("virtuoso", config=config)
    store.clear()

    graph = config["graph"]
    sparql = f"""
        INSERT DATA {{
            GRAPH <{graph}> {{
                <{SUBJECT}> <{PREDICATE}> <{OBJECT}> .
            }}
        }}
    """

    with pytest.raises(ValueError, match="Unsupported export format"):
        store.execute(sparql, export=True, output_format="json", filename=str(TEST_FILES_DIR / "bad_update"))
