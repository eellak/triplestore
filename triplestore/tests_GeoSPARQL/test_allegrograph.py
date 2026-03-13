# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0

"""
GeoSPARQL tests for the AllegroGraph backend of the triplestore abstraction layer.

All operations are scoped within the named graph 'http://example.org/test',
and use a local AllegroGraph instance with SPARQL HTTP API access.
"""

import tempfile
import time
from pathlib import Path

import pytest
import requests
from triplestore import Triplestore

SUBJECT = "http://example.org/featureA"
PREDICATE = "http://www.opengis.net/ont/geosparql#hasGeometry"
OBJECT = "http://example.org/geomA"

GRAPH = "http://example.org/test"
EX = "http://example.org/"
GEO = "http://www.opengis.net/ont/geosparql#"

POINT_A = "POINT(23.7275 37.9838)"
POINT_B = "POINT(23.7300 37.9845)"
POLYGON = "POLYGON((23.7200 37.9800, 23.7400 37.9800, 23.7400 37.9900, 23.7200 37.9900, 23.7200 37.9800))"

PREFIXES = """
PREFIX ex:   <http://example.org/>
PREFIX geo:  <http://www.opengis.net/ont/geosparql#>
PREFIX geof: <http://www.opengis.net/def/function/geosparql/>
PREFIX uom:  <http://www.opengis.net/def/uom/OGC/1.0/>
"""

SPARQL_QUERY = f"""
{PREFIXES}
SELECT ?feature ?geom ?wkt
WHERE {{
  GRAPH <{GRAPH}> {{
    ?feature geo:hasGeometry ?geom .
    ?geom geo:asWKT ?wkt .
  }}
}}
"""


REPO_NAME = f"testns-{int(time.time())}"

config = {
    "base_url": "http://localhost:10035",
    "name": REPO_NAME,
    "graph": GRAPH,
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
    """Test adding a geometry triple-pattern and retrieving it via GeoSPARQL/SPARQL."""
    store = Triplestore("allegrograph", config=config)
    store.clear()

    query = f"""
    {PREFIXES}
    INSERT DATA {{
      GRAPH <{GRAPH}> {{
        <{SUBJECT}> a ex:Feature ;
            <{PREDICATE}> <{OBJECT}> .

        <{OBJECT}> a geo:Geometry ;
            geo:asWKT "{POINT_A}"^^geo:wktLiteral .
      }}
    }}
    """
    store.execute(query)

    results = store.query(SPARQL_QUERY)
    bindings = [str(binding) for binding in results]

    assert any(SUBJECT in b and OBJECT in b and POINT_A in b for b in bindings)


def test_multiple_triples_query():
    """Test querying multiple geometries that are within the same polygon."""
    store = Triplestore("allegrograph", config=config)
    store.clear()

    query1 = f"""
    {PREFIXES}
    INSERT DATA {{
      GRAPH <{GRAPH}> {{
        ex:featureA a ex:Feature ;
            geo:hasGeometry ex:geomA .

        ex:geomA a geo:Geometry ;
            geo:asWKT "{POINT_A}"^^geo:wktLiteral .

        ex:featureB a ex:Feature ;
            geo:hasGeometry ex:geomB .

        ex:geomB a geo:Geometry ;
            geo:asWKT "{POINT_B}"^^geo:wktLiteral .

        ex:featureBox a ex:Feature ;
            geo:hasGeometry ex:geomBox .

        ex:geomBox a geo:Geometry ;
            geo:asWKT "{POLYGON}"^^geo:wktLiteral .
      }}
    }}
    """
    store.execute(query1)

    query2 = f"""
    {PREFIXES}
    SELECT ?feature
    WHERE {{
      GRAPH <{GRAPH}> {{
        ?feature geo:hasGeometry ?geom .
        ?geom geo:asWKT ?pointWKT .
        ex:geomBox geo:asWKT ?boxWKT .
        FILTER(geof:sfWithin(?pointWKT, ?boxWKT))
      }}
      FILTER(?feature != ex:featureBox)
    }}
    """
    results = store.query(query2)
    features = [str(row["feature"]).strip("<>") for row in results]

    assert f"{EX}featureA" in features
    assert f"{EX}featureB" in features
    assert len(features) == 2


def test_delete_triple():
    """Test that deleting a geometry relation removes it from the store."""
    store = Triplestore("allegrograph", config=config)
    store.clear()

    insert_q = f"""
    {PREFIXES}
    INSERT DATA {{
      GRAPH <{GRAPH}> {{
        <{SUBJECT}> a ex:Feature ;
            <{PREDICATE}> <{OBJECT}> .
        <{OBJECT}> a geo:Geometry ;
            geo:asWKT "{POINT_A}"^^geo:wktLiteral .
      }}
    }}
    """
    store.execute(insert_q)

    before = store.query(f"""
    {PREFIXES}
    SELECT ?geom WHERE {{
      GRAPH <{GRAPH}> {{
        <{SUBJECT}> geo:hasGeometry ?geom .
      }}
    }}
    """)
    assert len(before) == 1

    store.delete(SUBJECT, PREDICATE, OBJECT)

    after = store.query(f"""
    {PREFIXES}
    SELECT ?geom WHERE {{
      GRAPH <{GRAPH}> {{
        <{SUBJECT}> geo:hasGeometry ?geom .
      }}
    }}
    """)
    assert len(after) == 0


def test_query_roundtrip_add():
    """Test add-delete-add cycle for a geometry relation."""
    store = Triplestore("allegrograph", config=config)
    store.clear()

    insert_q = f"""
    {PREFIXES}
    INSERT DATA {{
      GRAPH <{GRAPH}> {{
        <{SUBJECT}> a ex:Feature ;
            <{PREDICATE}> <{OBJECT}> .
        <{OBJECT}> a geo:Geometry ;
            geo:asWKT "{POINT_A}"^^geo:wktLiteral .
      }}
    }}
    """
    store.execute(insert_q)

    initial_results = store.query(f"""
    {PREFIXES}
    SELECT ?feature ?geom
    WHERE {{
      GRAPH <{GRAPH}> {{
        ?feature geo:hasGeometry ?geom .
      }}
    }}
    """)
    row = next(iter(initial_results))
    s = str(row["feature"]).strip("<>")
    o = str(row["geom"]).strip("<>")

    store.delete(s, PREDICATE, o)

    after_delete = store.query(f"""
    {PREFIXES}
    SELECT ?feature ?geom
    WHERE {{
      GRAPH <{GRAPH}> {{
        ?feature geo:hasGeometry ?geom .
      }}
    }}
    """)
    assert not any(
        str(r["feature"]).strip("<>") == s and
        str(r["geom"]).strip("<>") == o
        for r in after_delete
    )

    store.add(s, PREDICATE, o)

    final_results = store.query(f"""
    {PREFIXES}
    SELECT ?feature ?geom
    WHERE {{
      GRAPH <{GRAPH}> {{
        ?feature geo:hasGeometry ?geom .
      }}
    }}
    """)
    count = sum(
        1 for r in final_results
        if str(r["feature"]).strip("<>") == s and
           str(r["geom"]).strip("<>") == o
    )
    assert count == 1


def test_query_returns_empty_when_no_match():
    """Test that a GeoSPARQL/SPARQL query returns no results when no match exists."""
    store = Triplestore("allegrograph", config=config)
    store.clear()

    q = f"""
    {PREFIXES}
    INSERT DATA {{
      GRAPH <{GRAPH}> {{
        ex:featureA a ex:Feature ;
            geo:hasGeometry ex:geomA .

        ex:geomA a geo:Geometry ;
            geo:asWKT "{POINT_A}"^^geo:wktLiteral .

        ex:featureB a ex:Feature ;
            geo:hasGeometry ex:geomB .

        ex:geomB a geo:Geometry ;
            geo:asWKT "{POINT_B}"^^geo:wktLiteral .

        ex:featureBox a ex:Feature ;
            geo:hasGeometry ex:geomBox .

        ex:geomBox a geo:Geometry ;
            geo:asWKT "{POLYGON}"^^geo:wktLiteral .
      }}
    }}
    """
    store.execute(q)

    results = store.query(f"""
    {PREFIXES}
    SELECT ?feature
    WHERE {{
      GRAPH <{GRAPH}> {{
        <http://example.org/unknown> geo:hasGeometry ?geom .
      }}
    }}
    """)
    assert len(results) == 0


def test_load_from_turtle_file():
    """Test loading GeoSPARQL triples from a .ttl file into the store."""
    turtle_data = f"""
    @prefix ex: <http://example.org/> .
    @prefix geo: <http://www.opengis.net/ont/geosparql#> .

    ex:featureA a ex:Feature ;
        geo:hasGeometry ex:geomA .

    ex:geomA a geo:Geometry ;
        geo:asWKT "{POINT_A}"^^geo:wktLiteral .
    """

    with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".ttl", encoding="utf-8") as f:
        f.write(turtle_data)
        tmp_path = f.name

    store = Triplestore("allegrograph", config=config)
    store.clear()
    store.load(tmp_path)

    results = store.query(SPARQL_QUERY)
    Path(tmp_path).unlink()

    bindings = [str(binding) for binding in results]
    assert any(SUBJECT in b and OBJECT in b and POINT_A in b for b in bindings)


def test_clear():
    """Test that clear() removes all geometries from the store."""
    store = Triplestore("allegrograph", config=config)
    store.clear()

    q = f"""
    {PREFIXES}
    INSERT DATA {{
      GRAPH <{GRAPH}> {{
        ex:featureA a ex:Feature ;
            geo:hasGeometry ex:geomA .

        ex:geomA a geo:Geometry ;
            geo:asWKT "{POINT_A}"^^geo:wktLiteral .

        ex:featureB a ex:Feature ;
            geo:hasGeometry ex:geomB .

        ex:geomB a geo:Geometry ;
            geo:asWKT "{POINT_B}"^^geo:wktLiteral .

        ex:featureBox a ex:Feature ;
            geo:hasGeometry ex:geomBox .

        ex:geomBox a geo:Geometry ;
            geo:asWKT "{POLYGON}"^^geo:wktLiteral .
      }}
    }}
    """
    store.execute(q)

    store.clear()
    results = store.query(SPARQL_QUERY)

    assert len(results) == 0


def test_clear_twice_is_safe():
    """Test that calling clear() multiple times doesn't raise or fail."""
    store = Triplestore("allegrograph", config=config)
    store.clear()
    store.clear()

    q = f"""
    {PREFIXES}
    INSERT DATA {{
      GRAPH <{GRAPH}> {{
        ex:featureA a ex:Feature ;
            geo:hasGeometry ex:geomA .

        ex:geomA a geo:Geometry ;
            geo:asWKT "{POINT_A}"^^geo:wktLiteral .

        ex:featureB a ex:Feature ;
            geo:hasGeometry ex:geomB .

        ex:geomB a geo:Geometry ;
            geo:asWKT "{POINT_B}"^^geo:wktLiteral .

        ex:featureBox a ex:Feature ;
            geo:hasGeometry ex:geomBox .

        ex:geomBox a geo:Geometry ;
            geo:asWKT "{POLYGON}"^^geo:wktLiteral .
      }}
    }}
    """
    store.execute(q)
    store.clear()
    results = store.query(SPARQL_QUERY)

    assert len(results) == 0


def test_execute():
    """End-to-end test for execute() using GeoSPARQL-aware data and queries."""
    store = Triplestore("allegrograph", config=config)
    store.clear()

    graph = config["graph"]

    # INSERT DATA
    q = f"""
    {PREFIXES}
    INSERT DATA {{
      GRAPH <{graph}> {{
        <{SUBJECT}> a ex:Feature ;
            geo:hasGeometry <{OBJECT}> .
        <{OBJECT}> a geo:Geometry ;
            geo:asWKT "{POINT_A}"^^geo:wktLiteral .
      }}
    }}
    """
    out = store.execute(q)
    assert out is None

    # ASK
    ask_q = f"""
    {PREFIXES}
    ASK WHERE {{
      GRAPH <{graph}> {{
        <{SUBJECT}> geo:hasGeometry <{OBJECT}> .
      }}
    }}
    """
    ask_res = store.execute(ask_q)
    assert isinstance(ask_res, bool)
    assert ask_res is True

    # SELECT
    q = f"""
    {PREFIXES}
    SELECT ?feature WHERE {{
      GRAPH <{graph}> {{
        ?feature geo:hasGeometry <{OBJECT}> .
      }}
    }}
    """
    sel = store.execute(q)
    assert isinstance(sel, list)
    assert len(sel) == 1
    subjects = [str(r["feature"]).strip("<>") for r in sel]
    assert SUBJECT in subjects

    # DESCRIBE
    q = f"DESCRIBE <{SUBJECT}>"
    desc = store.execute(q)
    assert isinstance(desc, str)
    assert SUBJECT in desc

    # CONSTRUCT
    q = f"""
    {PREFIXES}
    CONSTRUCT {{ ?feature ?p ?o }}
    WHERE {{
      GRAPH <{graph}> {{
        ?feature ?p ?o .
      }}
    }}
    """
    cons = store.execute(q)
    assert isinstance(cons, str)
    assert "ex:featureA" in cons
    assert "ex:geomA" in cons

    # GeoSPARQL SELECT with distance
    store.execute(f"""
    {PREFIXES}
    INSERT DATA {{
      GRAPH <{graph}> {{
        ex:featureB a ex:Feature ;
            geo:hasGeometry ex:geomB .
        ex:geomB a geo:Geometry ;
            geo:asWKT "{POINT_B}"^^geo:wktLiteral .
      }}
    }}
    """)

    geo_q = f"""
    {PREFIXES}
    SELECT ?geom ?wkt
    WHERE {{
      GRAPH <{graph}> {{
        ?feature geo:hasGeometry ?geom .
        ?geom geo:asWKT ?wkt .
        FILTER(?geom = ex:geomB)
      }}
    }}
    """
    geo_res = store.execute(geo_q)
    assert isinstance(geo_res, list)
    assert len(geo_res) == 1
    assert str(geo_res[0]["geom"]).strip("<>") == f"{EX}geomB"
    assert POINT_B in str(geo_res[0]["wkt"])

    # DELETE DATA
    q = f"DELETE DATA {{ GRAPH <{graph}> {{ <{SUBJECT}> <{PREDICATE}> <{OBJECT}> }} }}"
    del_out = store.execute(q)
    assert del_out is None
    assert store.execute(ask_q) is False

    # Re-insert and CLEAR GRAPH
    store.execute(f"""
    {PREFIXES}
    INSERT DATA {{
      GRAPH <{graph}> {{
        <{SUBJECT}> a ex:Feature ;
            geo:hasGeometry <{OBJECT}> .
        <{OBJECT}> a geo:Geometry ;
            geo:asWKT "{POINT_A}"^^geo:wktLiteral .
      }}
    }}
    """)
    q = f"CLEAR GRAPH <{graph}>"
    clr_out = store.execute(q)
    assert clr_out is None
    assert store.execute(f"ASK WHERE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}") is False


def test_add_duplicate_triple():
    """Test that adding the same triple twice does not create duplicate query results."""
    store = Triplestore("allegrograph", config=config)
    store.clear()

    insert_q = f"""
    {PREFIXES}
    INSERT DATA {{
      GRAPH <{GRAPH}> {{
        <{SUBJECT}> a ex:Feature ;
            <{PREDICATE}> <{OBJECT}> .
        <{OBJECT}> a geo:Geometry ;
            geo:asWKT "{POINT_A}"^^geo:wktLiteral .
      }}
    }}
    """
    store.execute(insert_q)

    store.add(SUBJECT, PREDICATE, OBJECT)

    results = store.query(f"""
    {PREFIXES}
    SELECT ?feature ?geom
    WHERE {{
      GRAPH <{GRAPH}> {{
        ?feature geo:hasGeometry ?geom .
      }}
    }}
    """)

    count = sum(
        1 for r in results
        if str(r["feature"]).strip("<>") == SUBJECT and
           str(r["geom"]).strip("<>") == OBJECT
    )
    assert count == 1


def test_delete_nonexistent_triple():
    """Test that deleting a triple that does not exist does not raise or affect existing data."""
    store = Triplestore("allegrograph", config=config)
    store.clear()

    insert_q = f"""
    {PREFIXES}
    INSERT DATA {{
      GRAPH <{GRAPH}> {{
        <{SUBJECT}> a ex:Feature ;
            <{PREDICATE}> <{OBJECT}> .
        <{OBJECT}> a geo:Geometry ;
            geo:asWKT "{POINT_A}"^^geo:wktLiteral .
      }}
    }}
    """
    store.execute(insert_q)

    store.delete(
        "http://example.org/nonexistentFeature",
        PREDICATE,
        "http://example.org/nonexistentGeom"
    )

    results = store.query(f"""
    {PREFIXES}
    SELECT ?geom
    WHERE {{
      GRAPH <{GRAPH}> {{
        <{SUBJECT}> geo:hasGeometry ?geom .
      }}
    }}
    """)

    assert len(results) == 1
    assert str(results[0]["geom"]).strip("<>") == OBJECT


def test_named_graph():
    """Test that queries scoped to the configured graph do not see triples from another named graph."""
    store = Triplestore("allegrograph", config=config)
    store.clear()

    other_graph = "http://example.org/other"

    q = f"""
    {PREFIXES}
    INSERT DATA {{
      GRAPH <{other_graph}> {{
        <{SUBJECT}> a ex:Feature ;
            <{PREDICATE}> <{OBJECT}> .
        <{OBJECT}> a geo:Geometry ;
            geo:asWKT "{POINT_A}"^^geo:wktLiteral .
      }}
    }}
    """
    store.execute(q)

    results_in_test_graph = store.query(f"""
    {PREFIXES}
    SELECT ?feature ?geom
    WHERE {{
      GRAPH <{GRAPH}> {{
        ?feature geo:hasGeometry ?geom .
      }}
    }}
    """)

    assert len(results_in_test_graph) == 0

    results_in_other_graph = store.query(f"""
    {PREFIXES}
    SELECT ?feature ?geom
    WHERE {{
      GRAPH <{other_graph}> {{
        ?feature geo:hasGeometry ?geom .
      }}
    }}
    """)

    assert len(results_in_other_graph) == 1
    row = results_in_other_graph[0]
    assert str(row["feature"]).strip("<>") == SUBJECT
    assert str(row["geom"]).strip("<>") == OBJECT
