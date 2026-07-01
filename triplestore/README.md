# Triplestore Abstraction Library

This library provides a unified interface for interacting
with various RDF and GeoSPARQL triplestore backends.
It allows developers to write code that is agnostic
to the underlying triplestore implementation.

## Features

- Common API for multiple triplestore backends
- Easy integration and backend switching
- Support for basic CRUD operations on triples
- GeoSPARQL support when provided by the selected backend
- Extensible for new triplestore implementations

## Supported Backends

The library provides a unified abstraction layer for multiple triplestores.  
Currently supported backends (alphabetically):

- AllegroGraph
- Apache Jena
- Blazegraph
- GraphDB
- Oxigraph
- QLever
- RDF4J
- Virtuoso

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

## Usage

```python
from triplestore import Triplestore

# Initialize with desired backend
store = Triplestore(backend="jena", config={...})

# Load triples
store.load(data_filename)

# Add a triple
store.add(subject, predicate, obj)

# Query triples
results = store.query("SELECT ?s ?p ?o WHERE { ?s ?p ?o }")
```
