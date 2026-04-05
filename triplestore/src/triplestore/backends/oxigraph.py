# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0


from pathlib import Path
from typing import Any

from pyoxigraph import DefaultGraph, NamedNode, Quad, QueryBoolean, QueryTriples, RdfFormat, Store

from triplestore.base import TriplestoreBackend
from triplestore.utils import (
    export_ask_result,
    export_rdf_result,
    export_select_results,
    get_sparql_query_type,
    resolve_export_format,
    validate_config,
)


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
        Load RDF triples from a Turtle (.ttl) file into the Oxigraph store.

        Parameters:
        filename : str
            Path to the Turtle (.ttl) file to be loaded.

        Raises
        ------
        FileNotFoundError
            If the input file does not exist.
        """
        path = Path(filename)
        if not path.exists():
            msg = f"[Oxigraph] File not found: {filename}"
            raise FileNotFoundError(msg)

        with Path(filename).open("rb") as f:
            if self.graph_uri:
                self.store.bulk_load(f, RdfFormat.TURTLE, to_graph=NamedNode(self.graph_uri))
            else:
                self.store.bulk_load(f, RdfFormat.TURTLE, to_graph=DefaultGraph())
        self.store.optimize()

    def add(self, subject: str, predicate: str, obj: str) -> None:
        """
        Add a triple to the Oxigraph store.

        Parameters:
        subject : str
            The subject URI of the triple.
        predicate : str
            The predicate URI of the triple.
        obj : str
            The object URI of the triple.
        """
        gterm = NamedNode(self.graph_uri) if self.graph_uri else DefaultGraph()
        quad = Quad(NamedNode(subject), NamedNode(predicate), NamedNode(obj), gterm)
        self.store.add(quad)

    def delete(self, subject: str, predicate: str, obj: str) -> None:
        """
        Delete a triple from the Oxigraph store.

        Parameters:
        subject : str
            The subject URI of the triple to remove.
        predicate : str
            The predicate URI of the triple to remove.
        obj : str
            The object URI of the triple to remove.
        """
        gterm = NamedNode(self.graph_uri) if self.graph_uri else DefaultGraph()
        quad = Quad(NamedNode(subject), NamedNode(predicate), NamedNode(obj), gterm)
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
