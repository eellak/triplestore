# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0

"""
GeoSPARQL tests for the RDF4J backend of the triplestore abstraction layer.

All operations are scoped within the named graph 'http://example.org/test',
and use a local RDF4J instance with REST API access.
"""

import csv
import json
import tempfile
import time
import zipfile
from pathlib import Path

import pytest
import requests
from triplestore import Triplestore

BASE_URL = "http://localhost:8080/rdf4j-server"

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

TEST_FILES_DIR = Path(__file__).parent / "tests_files"
TEST_FILES_DIR.mkdir(exist_ok=True)


def is_rdf4j_available() -> bool:
    try:
        response = requests.get(f"{BASE_URL}/repositories", timeout=2)
    except requests.RequestException:
        return False
    else:
        return response.status_code == 200


pytestmark = pytest.mark.skipif(
    not is_rdf4j_available(),
    reason="RDF4J instance is not reachable at the configured base_url",
)


config = {
    "name": f"testns-{int(time.time())}",
    "base_url": BASE_URL,
    "auth": None,
    "graph": GRAPH,
    "store_type": "native",
}


def test_add_and_query_triple():
    """Test adding a geometry triple-pattern and retrieving it via GeoSPARQL/SPARQL."""
    store = Triplestore("rdf4j", config=config)
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
    store = Triplestore("rdf4j", config=config)
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
    store = Triplestore("rdf4j", config=config)
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
    store = Triplestore("rdf4j", config=config)
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
    store = Triplestore("rdf4j", config=config)
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

    try:
        store = Triplestore("rdf4j", config=config)
        store.clear()
        store.load(tmp_path)

        results = store.query(SPARQL_QUERY)
        bindings = [str(binding) for binding in results]
        assert any(SUBJECT in b and OBJECT in b and POINT_A in b for b in bindings)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_clear():
    """Test that clear() removes all geometries from the store."""
    store = Triplestore("rdf4j", config=config)
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
    store = Triplestore("rdf4j", config=config)
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
    store = Triplestore("rdf4j", config=config)
    store.clear()

    graph = config["graph"]

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

    q = f"DESCRIBE <{SUBJECT}>"
    desc = store.execute(q)
    assert isinstance(desc, str)
    assert SUBJECT in desc

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
    assert "featureA" in cons
    assert "geomA" in cons

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
    SELECT ?dist
    WHERE {{
      GRAPH <{graph}> {{
        <{OBJECT}> geo:asWKT ?a .
        ex:geomB geo:asWKT ?b .
        BIND(geof:distance(?a, ?b, uom:metre) AS ?dist)
      }}
    }}
    """
    geo_res = store.execute(geo_q)
    assert isinstance(geo_res, list)
    assert len(geo_res) == 1
    assert float(geo_res[0]["dist"]) > 0.0

    q = f"DELETE DATA {{ GRAPH <{graph}> {{ <{SUBJECT}> <{PREDICATE}> <{OBJECT}> }} }}"
    del_out = store.execute(q)
    assert del_out is None
    assert store.execute(ask_q) is False

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
    store = Triplestore("rdf4j", config=config)
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
    store = Triplestore("rdf4j", config=config)
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
        "http://example.org/nonexistentGeom",
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
    store = Triplestore("rdf4j", config=config)
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


def test_select_star():
    """Test SELECT * for GeoSPARQL data: verifies bindings for feature, geometry, and WKT."""
    store = Triplestore("rdf4j", config=config)
    store.clear()

    insert_q = f"""
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
    store.execute(insert_q)

    results = store.query(f"""
    {PREFIXES}
    SELECT * WHERE {{
      GRAPH <{GRAPH}> {{
        ?feature geo:hasGeometry ?geom .
        ?geom geo:asWKT ?wkt .
        ex:geomBox geo:asWKT ?boxWKT .
        FILTER(geof:sfWithin(?wkt, ?boxWKT))
      }}
      FILTER(?feature != ex:featureBox)
    }}
    """)

    assert len(results) == 2

    expected_rows = [
        {
            "feature": f"{EX}featureA",
            "geom": f"{EX}geomA",
            "wkt": POINT_A,
            "boxWKT": POLYGON,
        },
        {
            "feature": f"{EX}featureB",
            "geom": f"{EX}geomB",
            "wkt": POINT_B,
            "boxWKT": POLYGON,
        },
    ]

    for row in results:
        assert set(row.keys()) == {"feature", "geom", "wkt", "boxWKT"}

    for row in results:
        for v in row.values():
            assert isinstance(v, str)
            assert v is not None

    normalized_results = [
        {
            "feature": str(r["feature"]).strip("<>"),
            "geom": str(r["geom"]).strip("<>"),
            "wkt": str(r["wkt"]),
            "boxWKT": str(r["boxWKT"]),
        }
        for r in results
    ]

    assert {tuple(sorted(r.items())) for r in normalized_results} == {
        tuple(sorted(r.items())) for r in expected_rows
    }

    assert len(results) == len({tuple(sorted(r.items())) for r in normalized_results})


def test_execute_geosparql():
    """End-to-end test for execute() using several GeoSPARQL spatial functions."""
    store = Triplestore("rdf4j", config=config)
    store.clear()

    graph = config["graph"]

    point_outside = "POINT(23.7600 38.0100)"
    polygon_overlap = (
        "POLYGON((23.7350 37.9850, 23.7500 37.9850, "
        "23.7500 37.9950, 23.7350 37.9950, 23.7350 37.9850))"
    )

    insert_q = f"""
    {PREFIXES}
    INSERT DATA {{
      GRAPH <{graph}> {{
        ex:featureA a ex:Feature ;
            geo:hasGeometry ex:geomA .
        ex:geomA a geo:Geometry ;
            geo:asWKT "{POINT_A}"^^geo:wktLiteral .

        ex:featureB a ex:Feature ;
            geo:hasGeometry ex:geomB .
        ex:geomB a geo:Geometry ;
            geo:asWKT "{POINT_B}"^^geo:wktLiteral .

        ex:featureOutside a ex:Feature ;
            geo:hasGeometry ex:geomOutside .
        ex:geomOutside a geo:Geometry ;
            geo:asWKT "{point_outside}"^^geo:wktLiteral .

        ex:featureBox a ex:Feature ;
            geo:hasGeometry ex:geomBox .
        ex:geomBox a geo:Geometry ;
            geo:asWKT "{POLYGON}"^^geo:wktLiteral .

        ex:featureOverlap a ex:Feature ;
            geo:hasGeometry ex:geomOverlap .
        ex:geomOverlap a geo:Geometry ;
            geo:asWKT "{polygon_overlap}"^^geo:wktLiteral .
      }}
    }}
    """
    out = store.execute(insert_q)
    assert out is None

    ask_q = f"""
    {PREFIXES}
    ASK WHERE {{
      GRAPH <{graph}> {{
        ex:featureA geo:hasGeometry ex:geomA .
      }}
    }}
    """
    ask_res = store.execute(ask_q)
    assert isinstance(ask_res, bool)
    assert ask_res is True

    within_q = f"""
    {PREFIXES}
    SELECT ?feature
    WHERE {{
      GRAPH <{graph}> {{
        ?feature geo:hasGeometry ?geom .
        ?geom geo:asWKT ?pointWKT .
        ex:geomBox geo:asWKT ?boxWKT .
        FILTER(geof:sfWithin(?pointWKT, ?boxWKT))
      }}
      FILTER(?feature NOT IN (ex:featureBox, ex:featureOverlap, ex:featureOutside))
    }}
    """
    within_res = store.execute(within_q)
    assert isinstance(within_res, list)
    within_features = {str(r["feature"]).strip("<>") for r in within_res}
    assert within_features == {
        f"{EX}featureA",
        f"{EX}featureB",
    }

    contains_q = f"""
    {PREFIXES}
    ASK WHERE {{
      GRAPH <{graph}> {{
        ex:geomBox geo:asWKT ?boxWKT .
        ex:geomA geo:asWKT ?pointWKT .
        FILTER(geof:sfContains(?boxWKT, ?pointWKT))
      }}
    }}
    """
    contains_res = store.execute(contains_q)
    assert isinstance(contains_res, bool)
    assert contains_res is True

    intersects_q = f"""
    {PREFIXES}
    ASK WHERE {{
      GRAPH <{graph}> {{
        ex:geomBox geo:asWKT ?boxWKT .
        ex:geomOverlap geo:asWKT ?overlapWKT .
        FILTER(geof:sfIntersects(?boxWKT, ?overlapWKT))
      }}
    }}
    """
    intersects_res = store.execute(intersects_q)
    assert isinstance(intersects_res, bool)
    assert intersects_res is True

    disjoint_q = f"""
    {PREFIXES}
    ASK WHERE {{
      GRAPH <{graph}> {{
        ex:geomOutside geo:asWKT ?outsideWKT .
        ex:geomBox geo:asWKT ?boxWKT .
        FILTER(geof:sfDisjoint(?outsideWKT, ?boxWKT))
      }}
    }}
    """
    disjoint_res = store.execute(disjoint_q)
    assert isinstance(disjoint_res, bool)
    assert disjoint_res is True

    equals_q = f"""
    {PREFIXES}
    ASK WHERE {{
      GRAPH <{graph}> {{
        ex:geomBox geo:asWKT ?boxWKT .
        FILTER(geof:sfEquals(?boxWKT, ?boxWKT))
      }}
    }}
    """
    equals_res = store.execute(equals_q)
    assert isinstance(equals_res, bool)
    assert equals_res is True

    distance_q = f"""
    {PREFIXES}
    SELECT ?dist
    WHERE {{
      GRAPH <{graph}> {{
        ex:geomA geo:asWKT ?a .
        ex:geomB geo:asWKT ?b .
        BIND(geof:distance(?a, ?b, uom:metre) AS ?dist)
      }}
    }}
    """
    distance_res = store.execute(distance_q)
    assert isinstance(distance_res, list)
    assert len(distance_res) == 1
    assert "dist" in distance_res[0]
    assert float(str(distance_res[0]["dist"])) > 0

    construct_q = f"""
    {PREFIXES}
    CONSTRUCT {{ ?feature geo:hasGeometry ?geom }}
    WHERE {{
      GRAPH <{graph}> {{
        ?feature geo:hasGeometry ?geom .
      }}
    }}
    """
    cons = store.execute(construct_q)
    assert isinstance(cons, str)
    assert "featureA" in cons
    assert "geomA" in cons
    assert "featureBox" in cons
    assert "geomBox" in cons

    delete_q = f"DELETE DATA {{ GRAPH <{graph}> {{ <{EX}featureA> <{PREDICATE}> <{EX}geomA> }} }}"
    del_out = store.execute(delete_q)
    assert del_out is None

    verify_delete_q = f"""
    {PREFIXES}
    ASK WHERE {{
      GRAPH <{graph}> {{
        ex:featureA geo:hasGeometry ex:geomA .
      }}
    }}
    """
    assert store.execute(verify_delete_q) is False

    clear_q = f"CLEAR GRAPH <{graph}>"
    clr_out = store.execute(clear_q)
    assert clr_out is None
    assert store.execute(f"ASK WHERE {{ GRAPH <{graph}> {{ ?s ?p ?o }} }}") is False


def _load_basic_geosparql_dataset(store: Triplestore) -> None:
    """Load a small GeoSPARQL dataset used by export-oriented tests."""
    store.clear()
    store.execute(f"""
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
    """)


def test_query_export_json_geosparql():
    """Test that query() exports GeoSPARQL SELECT results to JSON correctly."""
    store = Triplestore("rdf4j", config=config)
    _load_basic_geosparql_dataset(store)

    output_file = TEST_FILES_DIR / "rdf4j_geosparql_results_json"
    results = store.query(SPARQL_QUERY, export=True, output_format="json", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "rdf4j_geosparql_results_json.json"

    assert exported_path.exists()
    assert isinstance(results, list)
    assert len(results) == 3

    data = json.loads(exported_path.read_text(encoding="utf-8"))
    assert data == results

    normalized_rows = [
        {
            "feature": row["feature"].strip("<>"),
            "geom": row["geom"].strip("<>"),
            "wkt": row["wkt"],
        }
        for row in data
    ]

    expected_rows = [
        {"feature": f"{EX}featureA", "geom": f"{EX}geomA", "wkt": POINT_A},
        {"feature": f"{EX}featureB", "geom": f"{EX}geomB", "wkt": POINT_B},
        {"feature": f"{EX}featureBox", "geom": f"{EX}geomBox", "wkt": POLYGON},
    ]

    assert {tuple(sorted(r.items())) for r in normalized_rows} == {
        tuple(sorted(r.items())) for r in expected_rows
    }


def test_query_export_csv_geosparql():
    """Test that query() exports GeoSPARQL SELECT results to CSV correctly."""
    store = Triplestore("rdf4j", config=config)
    _load_basic_geosparql_dataset(store)

    output_file = TEST_FILES_DIR / "rdf4j_geosparql_results_csv"
    results = store.query(SPARQL_QUERY, export=True, output_format="csv", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "rdf4j_geosparql_results_csv.csv"

    assert exported_path.exists()
    assert isinstance(results, list)
    assert len(results) == 3

    with exported_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 3

    normalized_rows = [
        {
            "feature": row["feature"].strip("<>"),
            "geom": row["geom"].strip("<>"),
            "wkt": row["wkt"],
        }
        for row in rows
    ]

    expected_rows = [
        {"feature": f"{EX}featureA", "geom": f"{EX}geomA", "wkt": POINT_A},
        {"feature": f"{EX}featureB", "geom": f"{EX}geomB", "wkt": POINT_B},
        {"feature": f"{EX}featureBox", "geom": f"{EX}geomBox", "wkt": POLYGON},
    ]

    assert {tuple(sorted(r.items())) for r in normalized_rows} == {
        tuple(sorted(r.items())) for r in expected_rows
    }


def test_query_export_csv_with_custom_separator_geosparql():
    """Test that query() exports GeoSPARQL SELECT results to CSV using a custom separator."""
    store = Triplestore("rdf4j", config=config)
    _load_basic_geosparql_dataset(store)

    output_file = TEST_FILES_DIR / "rdf4j_geosparql_custom_separator"
    results = store.query(SPARQL_QUERY, export=True, output_format="csv", filename=str(output_file), separator=";")

    exported_path = TEST_FILES_DIR / "rdf4j_geosparql_custom_separator.csv"

    assert exported_path.exists()
    assert isinstance(results, list)
    assert len(results) == 3

    content = exported_path.read_text(encoding="utf-8")
    assert ";" in content

    with exported_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        rows = list(reader)

    assert len(rows) == 3
    assert set(rows[0].keys()) == {"feature", "geom", "wkt"}


def test_query_export_empty_results_json_geosparql():
    """Test exporting an empty GeoSPARQL SELECT result set to JSON."""
    store = Triplestore("rdf4j", config=config)
    store.clear()

    output_file = TEST_FILES_DIR / "rdf4j_geosparql_empty_json"
    results = store.query(
        f"""
        {PREFIXES}
        SELECT ?feature ?geom ?wkt
        WHERE {{
          GRAPH <{GRAPH}> {{
            <http://example.org/unknown> geo:hasGeometry ?geom .
            ?geom geo:asWKT ?wkt .
            BIND(<http://example.org/unknown> AS ?feature)
          }}
        }}
        """,
        export=True, output_format="json", filename=str(output_file),
    )

    exported_path = TEST_FILES_DIR / "rdf4j_geosparql_empty_json.json"

    assert results == []
    assert exported_path.exists()

    data = json.loads(exported_path.read_text(encoding="utf-8"))
    assert data == []


def test_query_rejects_non_select_geosparql():
    """Test that query() rejects non-SELECT GeoSPARQL/SPARQL queries."""
    store = Triplestore("rdf4j", config=config)
    store.clear()

    with pytest.raises(ValueError, match=r"Only SELECT queries are supported"):
        store.query(f"""
        {PREFIXES}
        ASK WHERE {{
          GRAPH <{GRAPH}> {{
            ?feature geo:hasGeometry ?geom .
          }}
        }}
        """)


def test_query_rejects_unsupported_export_format_geosparql():
    """Test that query() rejects unsupported export formats for GeoSPARQL SELECT queries."""
    store = Triplestore("rdf4j", config=config)
    store.clear()

    with pytest.raises(ValueError, match="Unsupported export format"):
        store.query(SPARQL_QUERY, export=True, output_format="ttl", filename=str(TEST_FILES_DIR / "bad_geo_output"))


def test_execute_export_select_json_geosparql():
    """Test that execute() exports GeoSPARQL SELECT results to JSON correctly."""
    store = Triplestore("rdf4j", config=config)
    _load_basic_geosparql_dataset(store)

    output_file = TEST_FILES_DIR / "execute_geosparql_select_json"
    results = store.execute(SPARQL_QUERY, export=True, output_format="json", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "execute_geosparql_select_json.json"

    assert exported_path.exists()
    assert isinstance(results, list)
    assert len(results) == 3

    data = json.loads(exported_path.read_text(encoding="utf-8"))
    assert data == results


def test_execute_export_select_csv_geosparql():
    """Test that execute() exports GeoSPARQL SELECT results to CSV correctly."""
    store = Triplestore("rdf4j", config=config)
    _load_basic_geosparql_dataset(store)

    output_file = TEST_FILES_DIR / "execute_geosparql_select_csv"
    results = store.execute(SPARQL_QUERY, export=True, output_format="csv", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "execute_geosparql_select_csv.csv"

    assert exported_path.exists()
    assert isinstance(results, list)
    assert len(results) == 3

    with exported_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 3
    assert set(rows[0].keys()) == {"feature", "geom", "wkt"}


def test_execute_export_ask_json_geosparql():
    """Test that execute() exports GeoSPARQL ASK results to JSON correctly."""
    store = Triplestore("rdf4j", config=config)
    _load_basic_geosparql_dataset(store)

    output_file = TEST_FILES_DIR / "execute_geosparql_ask_json"
    sparql = f"""
    {PREFIXES}
    ASK WHERE {{
      GRAPH <{GRAPH}> {{
        ex:featureA geo:hasGeometry ex:geomA .
      }}
    }}
    """

    result = store.execute(sparql, export=True, output_format="json", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "execute_geosparql_ask_json.json"

    assert exported_path.exists()
    assert result is True

    data = json.loads(exported_path.read_text(encoding="utf-8"))
    assert data == {"boolean": True}


def test_execute_export_ask_txt_geosparql():
    """Test that execute() exports GeoSPARQL ASK results to TXT correctly."""
    store = Triplestore("rdf4j", config=config)
    _load_basic_geosparql_dataset(store)

    output_file = TEST_FILES_DIR / "execute_geosparql_ask_txt"
    sparql = f"""
    {PREFIXES}
    ASK WHERE {{
      GRAPH <{GRAPH}> {{
        ex:featureA geo:hasGeometry ex:geomA .
      }}
    }}
    """

    result = store.execute(sparql, export=True, output_format="txt", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "execute_geosparql_ask_txt.txt"

    assert exported_path.exists()
    assert result is True
    assert exported_path.read_text(encoding="utf-8").strip() == "true"


def test_execute_export_construct_ttl_geosparql():
    """Test that execute() exports GeoSPARQL CONSTRUCT results to Turtle correctly."""
    store = Triplestore("rdf4j", config=config)
    _load_basic_geosparql_dataset(store)

    output_file = TEST_FILES_DIR / "execute_geosparql_construct"
    sparql = f"""
    {PREFIXES}
    CONSTRUCT {{ ?feature geo:hasGeometry ?geom }}
    WHERE {{
      GRAPH <{GRAPH}> {{
        ?feature geo:hasGeometry ?geom .
      }}
    }}
    """

    result = store.execute(sparql, export=True, output_format="ttl", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "execute_geosparql_construct.ttl"

    assert exported_path.exists()
    assert isinstance(result, str)

    content = exported_path.read_text(encoding="utf-8")
    assert content.splitlines() == result.splitlines()
    assert "featureA" in content
    assert "geomA" in content


def test_execute_export_describe_ttl_geosparql():
    """Test that execute() exports GeoSPARQL DESCRIBE results to Turtle correctly."""
    store = Triplestore("rdf4j", config=config)
    _load_basic_geosparql_dataset(store)

    output_file = TEST_FILES_DIR / "execute_geosparql_describe"
    sparql = f"DESCRIBE <{SUBJECT}>"

    result = store.execute(sparql, export=True, output_format="ttl", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "execute_geosparql_describe.ttl"

    assert exported_path.exists()
    assert isinstance(result, str)

    content = exported_path.read_text(encoding="utf-8")
    assert content.splitlines() == result.splitlines()
    assert SUBJECT in content


def test_execute_rejects_unsupported_export_format_for_ask_geosparql():
    """Test that execute() rejects unsupported export formats for GeoSPARQL ASK queries."""
    store = Triplestore("rdf4j", config=config)
    store.clear()

    sparql = f"""
    {PREFIXES}
    ASK WHERE {{
      GRAPH <{GRAPH}> {{
        ?feature geo:hasGeometry ?geom .
      }}
    }}
    """

    with pytest.raises(ValueError, match="Unsupported export format"):
        store.execute(sparql, export=True, output_format="csv", filename=str(TEST_FILES_DIR / "bad_geosparql_ask"))


def test_execute_rejects_export_for_update_operations_geosparql():
    """Test that execute() rejects export for GeoSPARQL update operations."""
    store = Triplestore("rdf4j", config=config)
    store.clear()

    sparql = f"""
    {PREFIXES}
    INSERT DATA {{
      GRAPH <{GRAPH}> {{
        ex:featureA a ex:Feature ;
            geo:hasGeometry ex:geomA .
        ex:geomA a geo:Geometry ;
            geo:asWKT "{POINT_A}"^^geo:wktLiteral .
      }}
    }}
    """

    with pytest.raises(ValueError, match="Unsupported export format"):
        store.execute(sparql, export=True, output_format="json", filename=str(TEST_FILES_DIR / "bad_geosparql_update"))


def test_query_export_geojson_geosparql():
    """Test that query() exports GeoSPARQL SELECT results to GeoJSON correctly."""
    store = Triplestore("rdf4j", config=config)
    _load_basic_geosparql_dataset(store)

    output_file = TEST_FILES_DIR / "rdf4j_geosparql_results_geojson"
    results = store.query(SPARQL_QUERY, export=True, output_format="geojson", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "rdf4j_geosparql_results_geojson.geojson"

    assert exported_path.exists()
    assert isinstance(results, list)
    assert len(results) == 3

    data = json.loads(exported_path.read_text(encoding="utf-8"))
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 3

    returned_features = {
        feature["properties"]["feature"].strip("<>")
        for feature in data["features"]
    }
    assert returned_features == {
        f"{EX}featureA",
        f"{EX}featureB",
        f"{EX}featureBox",
    }

    for feature in data["features"]:
        assert feature["type"] == "Feature"
        assert "geometry" in feature
        assert "properties" in feature
        assert feature["geometry"]["type"] in {"Point", "Polygon"}


def test_execute_export_geojson_geosparql():
    """Test that execute() exports GeoSPARQL SELECT results to GeoJSON correctly."""
    store = Triplestore("rdf4j", config=config)
    _load_basic_geosparql_dataset(store)

    output_file = TEST_FILES_DIR / "execute_geosparql_select_geojson"
    results = store.execute(SPARQL_QUERY, export=True, output_format="geojson", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "execute_geosparql_select_geojson.geojson"

    assert exported_path.exists()
    assert isinstance(results, list)
    assert len(results) == 3

    data = json.loads(exported_path.read_text(encoding="utf-8"))
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 3


def test_query_export_geojson_rejects_non_geojson_values():
    """Test that GeoJSON export fails when the SELECT results contain neither GeoJSON nor WKT."""
    store = Triplestore("rdf4j", config=config)
    _load_basic_geosparql_dataset(store)

    sparql = f"""
    {PREFIXES}
    SELECT ?feature ?geom
    WHERE {{
      GRAPH <{GRAPH}> {{
        ?feature geo:hasGeometry ?geom .
      }}
    }}
    """

    with pytest.raises(ValueError, match="Cannot export SELECT results as geospatial data"):
        store.query(sparql, export=True, output_format="geojson", filename=str(TEST_FILES_DIR / "bad_geosparql_geojson"))


def test_query_export_empty_results_geojson():
    """Test exporting an empty GeoSPARQL SELECT result set to GeoJSON."""
    store = Triplestore("rdf4j", config=config)
    store.clear()

    sparql = f"""
    {PREFIXES}
    SELECT ?feature ?wkt
    WHERE {{
      GRAPH <{GRAPH}> {{
        <http://example.org/unknown> geo:hasGeometry ?geom .
        ?geom geo:asWKT ?wkt .
        BIND(<http://example.org/unknown> AS ?feature)
      }}
    }}
    """

    output_file = TEST_FILES_DIR / "rdf4j_geosparql_empty_geojson"
    results = store.query(sparql, export=True, output_format="geojson", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "rdf4j_geosparql_empty_geojson.geojson"

    assert results == []
    assert exported_path.exists()

    data = json.loads(exported_path.read_text(encoding="utf-8"))
    assert data == {"type": "FeatureCollection", "features": []}


def test_query_export_kml_geosparql():
    """Test that query() exports GeoSPARQL SELECT results to KML correctly."""
    store = Triplestore("rdf4j", config=config)
    _load_basic_geosparql_dataset(store)

    output_file = TEST_FILES_DIR / "rdf4j_geosparql_results_kml"
    results = store.query(SPARQL_QUERY, export=True, output_format="kml", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "rdf4j_geosparql_results_kml.kml"

    assert exported_path.exists()
    assert len(results) == 3

    content = exported_path.read_text(encoding="utf-8")
    assert "<kml" in content
    assert "<Placemark>" in content
    assert "<Point>" in content or "<Polygon>" in content


def test_query_export_kmz_geosparql():
    """Test that query() exports GeoSPARQL SELECT results to KMZ correctly."""
    store = Triplestore("rdf4j", config=config)
    _load_basic_geosparql_dataset(store)

    output_file = TEST_FILES_DIR / "rdf4j_geosparql_results_kmz"
    results = store.query(SPARQL_QUERY, export=True, output_format="kmz", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "rdf4j_geosparql_results_kmz.kmz"

    assert exported_path.exists()
    assert isinstance(results, list)
    assert len(results) == 3

    with zipfile.ZipFile(exported_path, "r") as kmz_file:
        names = kmz_file.namelist()
        assert "doc.kml" in names

        kml_content = kmz_file.read("doc.kml").decode("utf-8")
        assert "<kml" in kml_content
        assert "<Placemark>" in kml_content


def test_execute_export_kmz_geosparql():
    """Test that execute() exports GeoSPARQL SELECT results to KMZ correctly."""
    store = Triplestore("rdf4j", config=config)
    _load_basic_geosparql_dataset(store)

    output_file = TEST_FILES_DIR / "execute_geosparql_select_kmz"
    results = store.execute(SPARQL_QUERY, export=True, output_format="kmz", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "execute_geosparql_select_kmz.kmz"

    assert exported_path.exists()
    assert isinstance(results, list)
    assert len(results) == 3

    with zipfile.ZipFile(exported_path, "r") as kmz_file:
        names = kmz_file.namelist()
        assert "doc.kml" in names

        kml_content = kmz_file.read("doc.kml").decode("utf-8")
        assert "<kml" in kml_content
        assert "<Placemark>" in kml_content


def test_query_export_gml_geosparql():
    """Test that query() exports GeoSPARQL SELECT results to GML correctly."""
    store = Triplestore("rdf4j", config=config)
    _load_basic_geosparql_dataset(store)

    output_file = TEST_FILES_DIR / "rdf4j_geosparql_results_gml"
    results = store.query(SPARQL_QUERY, export=True, output_format="gml", filename=str(output_file))

    exported_path = TEST_FILES_DIR / "rdf4j_geosparql_results_gml.gml"

    assert exported_path.exists()
    assert len(results) == 3

    content = exported_path.read_text(encoding="utf-8")
    assert "FeatureCollection" in content
    assert "featureMember" in content
    assert "Point" in content or "Polygon" in content
