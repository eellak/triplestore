# Triplestore

## Overview
A unified Python abstraction layer over multiple RDF triplestores, with optional GeoSPARQL-related support when provided by the selected backend.

Currently supported backends:
- AllegroGraph
- Apache Jena
- Blazegraph
- GraphDB
- Oxigraph
- QLever
- RDF4J
- Virtuoso

This package provides a consistent interface for loading data, executing SPARQL queries, and managing graphs across different triplestore engines.

## Prerequisites
- **Python**: version >=3.10 <br>
- **Backend requirements**: Each backend has its own prerequisites (e.g., running server, repository configuration). Refer to the official backend documentation for details.

## Installation

You can install the library along with **all supported backends** using:

```bash
pip install triplestore[all]
```

Alternatively, you can install the library with a **specific backend** only:
```bash
pip install triplestore[<backend>]
```
For example:
```bash
pip install triplestore[oxigraph]
```

GeoSPARQL-related dependencies are optional and can be installed separately with:
```bash
pip install triplestore[geo]
```

## How-To

### Load a RDF File
The `load()` method imports RDF data from a file into the triplestore.
- If a **named graph** is specified in the configuration, the data is loaded into that graph.
- If no graph is specified, the data is loaded into the **default graph**.
```python
from triplestore import Triplestore

store = Triplestore(backend, config)
store.load(file)
```

### Add a triple to triplestore
The `add()` method inserts a triple into the triplestore.

- If a **named graph** is specified in the configuration, the triple is added to that graph.
- If no graph is specified, the triple is added to the **default graph**.
```python
from triplestore import Triplestore

store = Triplestore(backend, config)

subject = "http://example.org/Alice"
predicate = "http://example.org/age"
obj = 15

store.add(subject, predicate, obj)
```

### Delete a triple from a triplestore
The `delete()` method removes a triple from the triplestore.

- If a **named graph** is specified in the configuration, the triple is removed from that graph.
- If no graph is specified, the triple is removed from the **default graph**.

```python
from triplestore import Triplestore

store = Triplestore(backend, config)

subject = "http://example.org/Alice"
predicate = "http://example.org/age"
obj = 15

store.delete(subject, predicate, obj)
```

### Query a triplestore
The library provides two methods for running SPARQL queries:
- query(): specifically designed for `SELECT` queries. It returns a list of dictionaries, where each dictionary represents one result binding.
- execute(): a generic method for running any SPARQL query (e.g. `SELECT`, `ASK`, `CONSTRUCT`, `INSERT`, `DELETE`, `UPDATE`). Although `execute()` may also be used for SELECT, query() is the recommended convenience method.
```python
from triplestore import Triplestore

store = Triplestore(backend, config)

# SELECT example
sparql_query = "SELECT ?s ?p ?o WHERE { ?s ?p ?o }"
results = store.query(sparql_query)
print(results)  # {'s': '...','p':'...','o':'...'}

# SELECT with export
store.query(sparql_query, export=True, output_format="json", filename="results")

# INSERT example
subject = "http://example.org/s"
predicate = "http://example.org/p"
obj = "http://example.org/o"
update = f"INSERT DATA {{ <{subject}> <{predicate}> <{obj}> . }}"

store.execute(update)  # returns None
```

### Clear a triplestore
WARNING: If you declared a graph in the configuration, clear() will clear only that named graph.
Otherwise, it clears the default graph.
```python
from triplestore import Triplestore

store = Triplestore(backend, config)

store.load(file)

store.clear()
```

### Basic Usage
A complete example showing the main operations:
```python
from triplestore import Triplestore

store = Triplestore(backend="oxigraph", config={"graph": None})

file = "data.ttl"
store.load(file)

subject = "http://example.org/s"
predicate = "http://example.org/p"
obj = "http://example.org/o"
store.add(subject, predicate, obj)

sparql_query = "SELECT ?s ?p ?o WHERE { ?s ?p ?o }"
results = store.query(sparql_query) 

print(results)
# Example output:
# {'s': 'http://example.org/s', 'p': 'http://example.org/p', 'o': 'http://example.org/o'}
```