# GSoC 2025 Project: Exploring and Abstracting Triplestore Alternatives

This repository hosts the work carried out as part of **Google Summer of Code 2025** under the mentorship of **GFOSS – Open Technologies Alliance**.
The goal of the project is to **explore, test, benchmark, and abstract multiple RDF triplestore implementations** into a unified Python interface.

## Project Overview

**Organization**: GFOSS – Open Technologies Alliance

**Project**: Exploring and Abstracting Triplestore Alternatives

**Contributor**: [Maria-Malamati Papadopoulou(goes by Maira Papadopoulou)](https://github.com/mairacs)

**Mentor**: [Alexios Zavras](https://github.com/zvr)

## Citation

The released version of this software has been archived on Zenodo and is available under the following DOI:

**DOI:** [10.5281/zenodo.20759436](https://doi.org/10.5281/zenodo.20759436)

## The Problem

RDF triplestores are essential for managing linked data and semantic web applications.
However, the current ecosystem suffers from:

- **Fragmentation**: many triplestore implementations, each with its own API and quirks
- **Steep learning curve**: developers must repeatedly adapt to different query/load interfaces
- **Limited abstraction**: no unified layer to seamlessly switch between backends

This makes experimentation and adoption harder for developers, researchers, and organizations working with RDF data.

## The Solution

**Triplestore Abstraction Library**: a Python package providing a **unified API** across multiple triplestores.

### Core Components Delivered

**Unified Python API**: Consistent interface for loading RDF, querying with SPARQL, and modifying triples

**Backend Implementations**: Connectors for Jena, GraphDB, Blazegraph, AllegroGraph,and Oxigraph

**Comprehensive Documentation**: `HOWTO.md`, `REFERENCE.md`, and backend-specific configuration guides

**Testing Framework**: Automated pytest suite for backend validation

## Project Characteristics
### Implemented Features

- **Unified Python API**: Provides a single interface to interact with multiple triplestore backends.
- **RDF Data Loading**: 
  - Supports loading data **exclusively in Turtle (`.ttl`) format.**
  - Large files can be ingested, with some backends offering streaming upload.
- **SPARQL Query Execution**:
  - Full support for all query forms: `SELECT`, `ASK`, `CONSTRUCT`, `DESCRIBE`.
  - Query results returned in Python-native structures (lists/dicts).
- **Data Modification**: `add()`, `delete()`, and `clear()` supported in all backends.
- **Multiple Backends**: Ready-to-use connectors for **Jena**, **GraphDB**, **Blazegraph**, **AllegroGraph**, **Oxigraph**.
- **Error Handling**: Consistent exception system for backend discovery, configuration errors, and runtime issues.
- **Testing & Benchmarking**:
  - Pytest-based test suite for all backends.
  - Benchmarking tools for comparing performance.

### Optional / Backend-Specific Features
- **Reasoning**: Available only in backends that support inference (e.g., GraphDB, AllegroGraph).

## 📚 Documentation

- [REFERENCE.md](./triplestore/docs/REFERENCE.md): Detailed API reference
- [HOWTO.md](./triplestore/docs/HOWTO.md): Usage and configuration guide
- [alternatives.md](./alternatives.md): Candidate triplestores and their characteristics
- [GSoC.md](./docs/GSoC.md): Project Report
- [BENCHMARKING.md](./docs/BENCHMARKING.md): Benchmarking report

## Candidates

The set of triplestore implementations that might be handled
is listed in a separate [file](./alternatives.md).


## License

All code in this repository is licensed under the `Apache-2.0` license.

### Notice

Some of the contents may have been developed with support
from one or more generative Artificial Intelligence solutions.

