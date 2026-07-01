# triplestore

> A backend-agnostic Python interface for loading, querying, and modifying [RDF](https://www.w3.org/RDF/) data across multiple triplestore implementations.

`triplestore` is a Python library that provides a unified API over multiple RDF triplestore backends. It lets users load RDF data, execute SPARQL queries and updates, and switch between supported backends without rewriting application code.

The library reduces the complexity of working with triplestores by hiding backend-specific configuration details behind a common Python interface. This makes it easier to load, query, and update RDF triples without having to learn the operational details of each individual backend. It also supports experimentation and benchmarking by allowing the same code to run against different triplestore implementations.

This repository hosts the work carried out as part of **Google Summer of Code 2025** under the mentorship of **GFOSS – Open Technologies Alliance**.

## Citation

The released version of this software has been archived on Zenodo and is available under the following DOI:

**DOI:** [10.5281/zenodo.20759436](https://doi.org/10.5281/zenodo.20759436)

## Features

- **Backend-agnostic API** for interacting with multiple RDF triplestores.
- **Pluggable backends** including Jena, GraphDB, Blazegraph, AllegroGraph, Oxigraph, QLever, RDF4J, and Virtuoso.
- **RDF data loading** from local files.
- **SPARQL query execution** for `SELECT`, `ASK`, `CONSTRUCT`, and `DESCRIBE`.
- **SPARQL updates and triple modification** through `add()`, `delete()`, `clear()`, and `execute()`.
- **Optional GeoSPARQL-related support** when provided by the selected backend.
- **Export support** for query results, including JSON, CSV, Turtle, and geospatial formats where applicable.

## Installation
Install all backend dependencies:
```bash
pip install triplestore[all]
```
Install a specific backend extra:
```bash
pip install triplestore[<backend>]
```
Install optional GeoSPARQL-related dependencies:
```bash
pip install triplestore[geo]
```

## Quick Start
```python
from triplestore import Triplestore

store = Triplestore("oxigraph", config={})

store.load("data.ttl")

results = store.query("SELECT ?s ?p ?o WHERE { ?s ?p ?o }")
print(results)

store.add("http://example.org/Alice", "http://example.org/age", 15)

store.clear()
```

## 📚 Documentation

- [REFERENCE.md](./triplestore/docs/REFERENCE.md): Detailed API reference
- [HOWTO.md](./triplestore/docs/HOWTO.md): Usage and configuration guide
- [alternatives.md](./alternatives.md): Candidate triplestores and their characteristics
- [GSoC.md](./docs/GSoC.md): Project Report
- [BENCHMARKING.md](./docs/BENCHMARKING.md): Benchmarking report

## Candidates

The set of triplestore implementations that might be handled
is listed in a separate [file](./alternatives.md).

## Project Background

**Organization**: GFOSS – Open Technologies Alliance

**Project**: Exploring and Abstracting Triplestore Alternatives

**Contributor**: [Maria-Malamati Papadopoulou(goes by Maira Papadopoulou)](https://github.com/mairacs)

**Mentor**: [Alexios Zavras](https://github.com/zvr)

## License

All code in this repository is licensed under the `Apache-2.0` license. See the [LICENSE](LICENSE) file for the full text.

### Notice

Some of the contents may have been developed with support from one or more generative Artificial Intelligence solutions.

