# `triplestore` (package internals)

## Overview
This document describes the **internal layout and design** of the `src/triplestore/` package.
It is aimed at contributors who want to understand how the library is organized internally—how backends are discovered, registered, and instantiated, and how they interact through the unified API surface.

## Directory Structure
```text
src/triplestore/
├── backends/             # Individual backend implementations
│   ├── __init__.py
│   ├── allegrograph.py
│   ├── blazegraph.py
│   ├── graphdb.py
│   ├── jena.py
│   ├── jena_utils.py
│   ├── oxigraph.py
│   ├── qlever.py
│   ├── rdf4j.py
│   └── virtuoso.py
├── __init__.py           # Public API surface
├── base.py               # Abstract base class defining the backend interface
├── exceptions.py         # Custom exception hierarchy for consistent error handling
├── registration.py       # Backend discovery and availability via entry points
├── triplestore.py        # Factory function
├── utils.py              # Shared utilities
└── utils_geo.py          # Shared geospatial utilities

```


## Public API Surface (`__init__.py`)
The `__init__.py` file defines the library’s public API surface.
- It re-exports the core classes (`Triplestore`, `TriplestoreBackend`) used to construct and manage backend connections.
- It exposes the key exceptions (`BackendNotFoundError`, `BackendNotInstalledError`, `TriplestoreError`, `TriplestoreMissingConfigValue`) so they can be imported directly from triplestore without referencing internal modules.
- It makes available the utility function `available_backends`, which lists the backends currently usable in the environment.

## Base Interface (`base.py`)
All concrete backends inherit from `TriplestoreBackend` and must implement a common set of operations:
- `load(filename: str) -> None`:
Load RDF data from a file into the store.

- `add(subj: Any, pred: Any, obj: Any) -> None`: 
Insert a single triple.

- `delete(subj: Any, pred: Any, obj: Any) -> None`:
Remove a single triple.

- `query(sparql: str, *, export: bool = False, output_format: str = "json", filename: str | None = None, separator: str = ",") -> Any`:
Execute a SPARQL `SELECT` query and return a list of dictionaries, one per result binding. When `export=True`, the results can also be written to a file.

- `execute(sparql: str, *, export: bool = False, output_format: str | None = None, filename: str | None = None, separator: str = ",") -> Any`:
  Execute any SPARQL query form. Depending on the query type, it may return:
  - `SELECT` → returns a list of dictionaries
  - `ASK` → returns a `bool`
  - `CONSTRUCT` / `DESCRIBE` → returns an RDF serialization string
  - `UPDATE` operations → returns `None`

- `clear() -> None`:
Remove all data from the store.

---

Each backend handle its own details (connections, authentication, graph namespaces), but the public interface exposed to users remains uniform across implementations.


## Exceptions (`exceptions.py`)
The package defines a small hierarchy of custom exceptions to provide consistent error handling:
- `TriplestoreError`:
Base class for all library-specific exceptions.

- `BackendNotFoundError`:
Raised when the requested backend name is not implemented in the current installation.

- `BackendNotInstalledError`:
Raised when the backend is implemented in the library but cannot be imported, typically due to missing optional dependencies or extras.

- `TriplestoreMissingConfigValue`:
Raised by `validate_config()` when required configuration keys are absent.


## Backend Discovery & Registration (`registration.py`)

Backends are discovered dynamically through the entry point group [`triplestore.backends`](/triplestore/pyproject.toml). At runtime, a registry is built from installed entry points, and `available_backends()` returns only those that can actually be imported. This mechanism supports optional extras: unused backends can ship with the package but remain inactive unless their dependencies are installed.

## Constructor (`triplestore.py`)
The Triplestore() function is the main entry point for creating backend instances: 
```python
Triplestore(backend: str, config: dict[str, Any]) -> TriplestoreBackend
```

It performs the following steps:
- **Validates inputs**: ensures `backend` is a non-empty string and `config` is a dictionary.
- **Resolves the backend class** from the internal registry of discovered entry points.
- **Checks for errors** like `BackendNotFoundError` and `BackendNotInstalledError`.
- **Instantiates and returns** the backend as a ready-to-use `TriplestoreBackend` object.

## Shared Utilities (`utils.py`)
This module provides helper functions shared by backend implementations.
- `validate_config(user_config, *, required_keys, optional_defaults, alias_map, backend_name)`:
Normalizes a backend configuration dictionary by:
  - Resolving key aliases,
  - Filling in optional defaults,
  - Verifying all required keys are present,
  - Preserving unknown keys (with a warning).
  - Raises `TriplestoreMissingConfigValue` if required keys are missing.

- `detect_host_url(port: int, path: str = "", fallback: str | None = None)`:
Returns a best-effort URL for services running on the host machine, including WSL host detection. Falls back to `localhost` or to the provided fallback URL.

- `detect_graphdb_url()`: Returns a best-effort base URL for a local GraphDB instance, including WSL host detection. This makes quick-start examples work out of the box.

- `get_sparql_query_type(sparql: str)`:
Detects the top-level SPARQL query or update form, ignoring leading `PREFIX`, `BASE`, and comment lines.

- `resolve_export_format(query_type, *, export, output_format, backend_name)`:
Resolves and validates the export format for a SPARQL query. It applies default formats when needed and rejects unsupported query/format combinations.

- `export_select_results(results, output_format, filename=None, separator=",", backend_name="backend")`:
Exports `SELECT` results to `json`, `csv`, `geojson`, `kml`, `kmz`, or `gml`.

- `export_ask_result(result, output_format, filename=None, backend_name="backend")`:
Exports `ASK` results to `json` or `txt`.

- `export_rdf_result(rdf_text, output_format, filename=None, backend_name="backend")`:
Exports RDF results from `CONSTRUCT` or `DESCRIBE` queries. Currently supports Turtle (`ttl`).

- `serialize_rdf_term(term, backend_name="backend")`:
Converts supported Python values into SPARQL-compatible RDF terms, including IRIs, blank nodes, plain literals, typed literals, and language-tagged literals.

- `validate_rdf_term(term, position, backend_name="backend")`:
 Validates that a term is allowed in a given RDF triple position (`subject`, `predicate`, or `object`) and returns its serialized representation.

- `get_rdf_content_type(filename: str, backend_name="backend")`:
Returns the HTTP `Content-Type` for supported RDF file formats such as Turtle (`.ttl`) and N-Triples (`.nt`).

## Shared Geospatial Utilities (`utils_geo.py`)
This module provides helper functions for exporting geospatial `SELECT` query results.

- `export_geospatial_select_results(results, *, output_format, output_path, backend_name="backend")`:
Exports geospatial `SELECT` results to `geojson`, `kml`, `kmz`, or `gml`.

Internally, the module:
- Detects geometry values returned as GeoJSON objects or WKT literals.
- Converts each result row into a GeoJSON-like `Feature`.
- Builds a `FeatureCollection` for GeoJSON export.
- Converts supported geometries to KML or GML XML.
- Creates KMZ archives by wrapping the generated KML document.

Supported geometry types include:
- `Point`
- `LineString`
- `Polygon`
- `MultiPoint`
- `MultiLineString`
- `MultiPolygon`

## Minimal Example
**Pick a backend & count triples**
```python
from triplestore import Triplestore, available_backends

print("Available backends:", available_backends())

# Jena (auto‑runs local Fuseki)
store = Triplestore("jena", config={"name": "ds"})
store.load("data.ttl")
print(store.query("SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }"))
store.clear()
```
