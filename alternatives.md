# Triplestore implementations

A variety of triplestore implementations were evaluated during the development of this library.  
They are categorized below into **implemented backends** and **evaluated but not implemented**, with justifications provided.

---

## Implemented Backends

The following triplestores have been successfully integrated into this library:

### AllegroGraph 
  - **License**: Commercial (free tier available for datasets up to 8M triples)  
  - **Deployment**: distributed as a `.tar.gz` server package  

### Apache Jena
  - **License**: Apache-2.0  
  - **Deployment**: distributed as a standalone JAR file  

### Blazegraph  
  - **License**: GPLv2  
  - **Deployment**: distributed as a standalone JAR file

### GraphDB  
  - **License:** commercial (GraphDB Free provides a single-core license with support for up to 1.8M triples)  
  - **Deployment**: distributed as a `.tar.gz` server package    

### Oxigraph 
  - **License**: MIT  
  - **Deployment**: provided as a native Rust binary with Python bindings available  

### QLever
  - **License**: Apache-2.0
  - **Deployment**: managed through the `qlever` command-line tool; requires Docker running in the background

### RDF4J
  - **License**: Eclipse Distribution License (EDL) v1.0
  - **Deployment**: distributed as a Docker image

### Virtuoso
  - **License**: GPL-2.0 
  - **Deployment**: provided as a native server binary; can be run with a system-installed or locally built configuration 

---

## Evaluated but Not Implemented

The following triplestores were examined but could not be integrated, for the reasons outlined below:

### KùzuDB
  - **License**: MIT  
  - **Limitation**: Does not support SPARQL and lacks the ability to ingest Turtle (`.ttl`) files — both are essential requirements for this library. 

### MillenniumDB 
  - **License**: GPLv3  
  - **Limitation**: According to the [official repository](https://github.com/MillenniumDB/MillenniumDB):  
    *“This project is still in active development and is not production ready yet, some functionality is missing and there may be bugs.”*  

### AnzoGraph
  - **License**: commercial  
  - **Limitation**: The product is no longer actively offered or maintained.  

### Stardog 
  - **License**: commercial  
  - **Limitation**: Only available as a paid product; no adequate free tier exists to enable integration within this project.  

---