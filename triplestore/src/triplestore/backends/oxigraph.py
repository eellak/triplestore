# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0


from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pyoxigraph import BlankNode, DefaultGraph, Literal, NamedNode, Quad, QueryBoolean, QueryTriples, RdfFormat, Store

from triplestore.base import TriplestoreBackend
from triplestore.utils import (
    export_ask_result,
    export_rdf_result,
    export_select_results,
    get_rdf_content_type,
    get_sparql_query_type,
    resolve_export_format,
    validate_config,
    validate_rdf_term,
)


OXIGRAPH_RDF_FORMATS = {
    "text/turtle": RdfFormat.TURTLE,
    "application/n-triples": RdfFormat.N_TRIPLES,
}


class Oxigraph(TriplestoreBackend):
    """
    A triplestore backend implementation for Oxigraph using the pyoxigraph API.

    """
    REQUIRED_KEYS = set()
    OPTIONAL_DEFAULTS = {
        "graph": None,
    }
    ALIASES = {
        "graph_uri": "graph",
    }

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Initialize the Oxigraph backend with the given configuration.

        Parameters:
        config : dict
            Expected keys (optional):
              - "graph": str -> default named graph to use (if provided).
        """
        configuration = validate_config(config, required_keys=self.REQUIRED_KEYS, optional_defaults=self.OPTIONAL_DEFAULTS,
                                        alias_map=self.ALIASES, backend_name="Oxigraph")

        super().__init__(configuration)
        self.store = Store()
        self.graph_uri: str | None = configuration["graph"]
        if self.graph_uri:
            self.store.add_graph(NamedNode(self.graph_uri))

    def load(self, filename: str) -> None:
        """
        Load RDF triples from a supported RDF file into the Oxigraph store.

        Supported formats:
        - .ttl: Turtle
        - .nt: N-Triples

        Parameters:
        filename : str
            Path to the RDF file to load (.ttl or .nt).


        Raises
        ------
        FileNotFoundError
            If the input file does not exist.
        """
        path = Path(filename)
        if not path.exists():
            msg = f"[Oxigraph] File not found: {filename}"
            raise FileNotFoundError(msg)
        
        content_type = get_rdf_content_type(filename, backend_name="Oxigraph")
        rdf_format = OXIGRAPH_RDF_FORMATS[content_type]

        with Path(filename).open("rb") as f:
            if self.graph_uri:
                self.store.bulk_load(f, rdf_format, to_graph=NamedNode(self.graph_uri))
            else:
                self.store.bulk_load(f, rdf_format, to_graph=DefaultGraph())
        self.store.optimize()

    def add(self, subject: Any, predicate: Any, obj: Any) -> None:
        """
        Add a triple to the Oxigraph store.

        Parameters
        ----------
        subject : Any
            The subject value of the triple. Must serialize to an RDF IRI or blank node.
        predicate : Any
            The predicate value of the triple. Must serialize to an RDF IRI.
        obj : Any
            The object value of the triple. May serialize to an RDF IRI, blank node, or literal.
        """
        graph_term = NamedNode(self.graph_uri) if self.graph_uri else DefaultGraph()
        quad = Quad(
            _to_oxigraph_term(subject, "subject", "Oxigraph"),
            _to_oxigraph_term(predicate, "predicate", "Oxigraph"),
            _to_oxigraph_term(obj, "object", "Oxigraph"),
            graph_term,
        )
        self.store.add(quad)

    def delete(self, subject: Any, predicate: Any, obj: Any) -> None:
        """
        Delete a triple from the Oxigraph store.

        Parameters
        ----------
        subject : Any
            The subject value of the triple. Must serialize to an RDF IRI or blank node.
        predicate : Any
            The predicate value of the triple. Must serialize to an RDF IRI.
        obj : Any
            The object value of the triple. May serialize to an RDF IRI, blank node, or literal.
        """
        graph_term = NamedNode(self.graph_uri) if self.graph_uri else DefaultGraph()

        quad = Quad(
            _to_oxigraph_term(subject, "subject", "Oxigraph"),
            _to_oxigraph_term(predicate, "predicate", "Oxigraph"),
            _to_oxigraph_term(obj, "object", "Oxigraph"),
            graph_term,
        )
        self.store.remove(quad)

    def query(self, sparql: str, *, export: bool = False, output_format: str = "json", filename: str | None = None, separator: str = ",") -> list[dict[str, str]]:
        """
        Execute a SPARQL SELECT query against the Oxigraph store.

        Parameters
        ----------
        sparql : str
            A valid SPARQL query string.
        export : bool, optional
            If True, also save the query results to a local file.
        output_format : str, optional
            Export format for saved results. Supported: 'json', 'csv'.
        filename : str, optional
            Output filename for exported results. The file extension is determined automatically from the requested export format.
        separator : str, optional
            Column separator to use when exporting CSV files. Defaults to ",".

        Returns
        -------
        list[dict[str, str]]
            A list of solution mappings.

        Raises
        ------
        ValueError
            If query() is called with a non-SELECT query or with an unsupported export format.
        TypeError
            If the query result is not a valid SELECT result or if the returned result is not iterable.
        """
        query_type = get_sparql_query_type(sparql)

        if query_type != "SELECT":
            msg = (
                f"[Oxigraph] Unsupported query type '{query_type}' for query(). "
                "Only SELECT queries are supported. "
                "Use execute() for UPDATE queries or other query forms."
            )
            raise ValueError(msg)

        if export:
            chosen_format = resolve_export_format(query_type, export=export, output_format=output_format, backend_name="Oxigraph")

        result = self.store.query(sparql)

        if isinstance(result, (QueryBoolean, QueryTriples)):
            msg = "[Oxigraph] query() expected a SELECT result but received a different query result type."
            raise TypeError(msg)

        try:
            iter(result)
        except TypeError as e:
            msg = "[Oxigraph] query() expected iterable SELECT bindings but got a non-iterable result."
            raise TypeError(msg) from e

        variable_names = [var.value for var in result.variables]
        solutions: list[dict[str, str]] = []
        for solution in result:
            binding: dict[str, str] = {}
            for var_name in variable_names:
                try:
                    term = solution[var_name]
                except KeyError:
                    continue
                term_value = getattr(term, "value", None)
                binding[var_name] = term_value if term_value is not None else str(term)
            solutions.append(binding)

        if export:
            export_select_results(solutions, output_format=chosen_format, filename=filename, separator=separator, backend_name="Oxigraph")

        return solutions

    def execute(self, sparql: str, *, export: bool = False, output_format: str | None = None, filename: str | None = None, separator: str = ",") -> Any:
        """
        Execute any SPARQL operation.

        Parameters
        ----------
        sparql : str
            A valid SPARQL query or update string.
        export : bool, optional
            If True, also save the query result to a local file.
        output_format : str, optional
            Export format for saved results. If omitted and export=True, a default format is chosen based on the query type.
        filename : str, optional
            Output filename for exported results. The file extension is determined automatically from the requested export format.
        separator : str, optional
            Column separator to use when exporting CSV files. Defaults to ",".

        Returns
        -------
        Any
            - list of dict for SELECT
            - bool for ASK
            - str (RDF serialization) for CONSTRUCT/DESCRIBE
            - None for UPDATE operations
        """
        query_type = get_sparql_query_type(sparql)
        chosen_format = resolve_export_format(query_type, export=export, output_format=output_format, backend_name="Oxigraph")

        #  UPDATE operations (INSERT, DELETE, CLEAR, DROP, LOAD, CREATE, etc.)
        if query_type in {
            "WITH", "INSERT", "DELETE", "LOAD", "CLEAR", "CREATE", "DROP",
            "MOVE", "COPY", "ADD", "MODIFY"
        }:
            self.store.update(sparql)
            return None

        result = self.store.query(sparql)

        # ASK
        if isinstance(result, QueryBoolean):
            boolean_result = bool(result)
            if export:
                export_ask_result(boolean_result, output_format=chosen_format, filename=filename, backend_name="Oxigraph")
            return boolean_result

        # CONSTRUCT / DESCRIBE
        if isinstance(result, QueryTriples):
            rdf_text = result.serialize(format=RdfFormat.TURTLE).decode("utf-8")
            if export:
                export_rdf_result(rdf_text, output_format=chosen_format, filename=filename, backend_name="Oxigraph")
            return rdf_text

        try:
            iter(result)
        except TypeError:
            return result

        # SELECT
        variable_names = [var.value for var in result.variables]
        solutions: list[dict[str, str]] = []
        for solution in result:
            binding: dict[str, str] = {}
            for var_name in variable_names:
                try:
                    term = solution[var_name]
                except KeyError:
                    continue
                term_value = getattr(term, "value", None)
                binding[var_name] = term_value if term_value is not None else str(term)
            solutions.append(binding)

        if export:
            export_select_results(solutions, output_format=chosen_format, filename=filename, separator=separator, backend_name="Oxigraph")

        return solutions

    def clear(self) -> None:
        """
        Remove all triples from the store.

        Notes
        -----
        - If a named graph URI is configured, only that graph is cleared.
        - Otherwise, the default graph is cleared.
        """
        if self.graph_uri:
            self.store.clear_graph(NamedNode(self.graph_uri))
        else:
            self.store.clear_graph(DefaultGraph())


def _to_oxigraph_term(term: Any, position: str, backend_name: str = "Oxigraph"):
    """
    Convert a Python value into a corresponding Oxigraph RDF term.

    Parameters
    ----------
    term : Any
        The Python value to convert.
    position : str
        The RDF triple position: 'subject', 'predicate', or 'object'.
    backend_name : str, default="Oxigraph"
        Backend name used in error messages.

    Returns
    -------
    NamedNode | BlankNode | Literal
        The corresponding Oxigraph RDF term.

    Raises
    ------
    ValueError
        If any triple component is invalid for its RDF position or cannot be converted into a supported Oxigraph RDF term.
    """
    validate_rdf_term(term, position, backend_name)

    # Blank node (allowed only for subject and object)
    if position in {"subject", "object"} and isinstance(term, str) and term.startswith("_:"):
        return BlankNode(term[2:])

    # IRI or plain string literal
    if isinstance(term, str):
        if term.startswith(("http://", "https://")):
            return NamedNode(term)
        return Literal(term)

    # Primitive literals
    if isinstance(term, (bool, int, float)):
        return Literal(term)

    # Mapping-based literals (typed or language-tagged)
    if isinstance(term, Mapping):
        value = term["value"]
        datatype = term.get("datatype")
        lang = term.get("lang")

        if datatype is not None:
            return Literal(str(value), datatype=NamedNode(datatype))

        if lang is not None:
            return Literal(str(value), language=lang)

        return Literal(str(value))

    # Unsupported type
    msg = (
        f"[{backend_name}] Unsupported RDF term: {term!r}\n"
        "Expected an IRI string, blank node identifier, Python literal, "
        "or literal mapping."
    )
    raise ValueError(msg)
