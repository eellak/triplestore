# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0

import logging
from pathlib import Path
from typing import Any

import requests

from triplestore.base import TriplestoreBackend
from triplestore.utils import (
    export_ask_result,
    export_rdf_result,
    export_select_results,
    get_sparql_query_type,
    resolve_export_format,
    validate_config,
)

logger = logging.getLogger(__name__)


class Blazegraph(TriplestoreBackend):
    """
    A triplestore backend implementation for Blazegraph using its HTTP REST API.
    """

    REQUIRED_KEYS = {"name"}
    OPTIONAL_DEFAULTS = {
        "base_url": "http://172.27.148.51:9999/blazegraph",
        "graph": None,
    }
    ALIASES = {
        "graph_uri": "graph",
        "namespace": "name",
    }

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Initialize the Blazegraph backend with the given configuration.

        Parameters:
        config : dict
            A configuration dictionary containing:
            - base_url (optional): The base URL of the Blazegraph instance.
            - namespace : The namespace to use.
            - graph (optional): Named graph URI for scoped operations.
        """

        configuration = validate_config(config, required_keys=self.REQUIRED_KEYS, optional_defaults=self.OPTIONAL_DEFAULTS,
                                        alias_map=self.ALIASES, backend_name="Blazegraph")

        super().__init__(configuration)
        self.base_url = configuration["base_url"]
        self.namespace = configuration["name"]
        self.graph_uri = configuration["graph"]

        self.update_url = f"{self.base_url}/namespace/{self.namespace}/sparql"
        self.query_url = self.update_url

        self.headers_query = {"Accept": "application/sparql-results+json"}
        self.headers_update = {"Content-Type": "application/sparql-update"}
        self.headers_load = {"Content-Type": "text/turtle"}

        self._ensure_namespace_exists()

    def load(self, filename: str) -> None:
        """
        Load RDF triples from a Turtle (.ttl) file into Blazegraph.

        Parameters:
        filename : str
            Path to the Turtle file.

        Raises
        ------
        FileNotFoundError
            If the file does not exist
        RuntimeError
            If the server responds with an error during loading.
        """
        if not Path(filename).exists():
            msg = f"[Blazegraph] File not found: {filename}"
            raise FileNotFoundError(msg)

        data = Path(filename).read_bytes()
        params = {"context-uri": self.graph_uri} if self.graph_uri else {}
        response = requests.post(self.update_url, headers=self.headers_load, data=data, params=params, timeout=None)
        if response.status_code not in {200, 204, 201}:
            msg = f"[Blazegraph] Load failed: {response.status_code}\n{response.text}"
            raise RuntimeError(msg)

    def add(self, s: str, p: str, o: str) -> None:
        """
        Add a triple to the Blazegraph store.

        Parameters:
        s : str
            Subject URI.
        p : str
            Predicate URI.
        o : str
            Object URI.
        """
        triple = f"<{s}> <{p}> <{o}> ."
        sparql = (
            f"INSERT DATA {{ GRAPH <{self.graph_uri}> {{ {triple} }} }}"
            if self.graph_uri else
            f"INSERT DATA {{ {triple} }}"
        )
        self._run_update(sparql)

    def delete(self, s: str, p: str, o: str) -> None:
        """
        Delete a triple from the Blazegraph store.

        Parameters:
        s : str
            Subject URI.
        p : str
            Predicate URI.
        o : str
            Object URI.
        """
        triple = f"<{s}> <{p}> <{o}> ."
        sparql = (
            f"DELETE DATA {{ GRAPH <{self.graph_uri}> {{ {triple} }} }}"
            if self.graph_uri else
            f"DELETE DATA {{ {triple} }}"
        )
        self._run_update(sparql)

    def execute(self, sparql: str, *, export: bool = False, output_format: str | None = None, filename: str | None = None, separator: str = ",") -> Any:
        """
        Execute any SPARQL query (SELECT, ASK, CONSTRUCT, DESCRIBE, UPDATE).

        Parameters
        ----------
        sparql : str
            The SPARQL query or update string.
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

        Raises
        ------
        RuntimeError
            If the server responds with an error.
        """
        query_type = get_sparql_query_type(sparql)
        chosen_format = resolve_export_format(query_type, export=export, output_format=output_format, backend_name="Blazegraph")

        # SELECT / ASK
        if query_type in {"SELECT", "ASK"}:
            response = requests.post(self.query_url, headers=self.headers_query, data={"query": sparql}, timeout=None)
            if response.status_code != 200:
                msg = f"[Blazegraph] Query failed {response.status_code}:\n{response.text}"
                raise RuntimeError(msg)

            data = response.json()

            if query_type == "ASK":
                result = bool(data.get("boolean", False))
                if export:
                    export_ask_result(result, output_format=chosen_format, filename=filename, backend_name="Blazegraph")
                return result

            bindings = data.get("results", {}).get("bindings", [])
            results = [{k: v["value"] for k, v in row.items()} for row in bindings]

            if export:
                export_select_results(results, output_format=chosen_format, filename=filename, separator=separator, backend_name="Blazegraph")

            return results

        # CONSTRUCT / DESCRIBE
        if query_type in {"CONSTRUCT", "DESCRIBE"}:
            response = requests.post(self.query_url, headers={"Accept": "text/turtle"}, data={"query": sparql}, timeout=None)
            if response.status_code != 200:
                msg = f"[Blazegraph] SPARQL query failed: {response.status_code}\n{response.text}"
                raise RuntimeError(msg)

            rdf_text = response.text

            if export:
                export_rdf_result(rdf_text, output_format=chosen_format, filename=filename, backend_name="Blazegraph")

            return rdf_text

        # UPDATE family
        if query_type in {
            "WITH", "INSERT", "DELETE", "LOAD", "CLEAR", "CREATE", "DROP",
            "MOVE", "COPY", "ADD", "MODIFY"
        }:
            self._run_update(sparql)
            return None

        msg = f"[Blazegraph] Unsupported SPARQL keyword: {query_type}"
        raise RuntimeError(msg)

    def query(self, sparql: str, *, export: bool = False, output_format: str = "json", filename: str | None = None, separator: str = ",") -> list[dict[str, str]]:
        """
        Execute a SPARQL SELECT query against Blazegraph.

        Parameters
        ----------
        sparql : str
            The SPARQL query string.
        export : bool, optional
            If True, also save the query results to a local file.
        output_format : str, optional
            Export format for saved results. Supported: 'json', 'csv'.
        filename : str, optional
            Output filename for exported results. The file extension is determined automatically
            from the requested export format.
        separator : str, optional
            Column separator to use when exporting CSV files. Defaults to ",".

        Returns
        -------
        list[dict[str, str]]
            A list of bindings from the query results.

        Raises
        ------
        ValueError
            If query() is called with a non-SELECT query or with an unsupported export format.
        RuntimeError
            If the query fails or the response is invalid.
        """
        query_type = get_sparql_query_type(sparql)

        if query_type != "SELECT":
            msg = (
                f"[Blazegraph] Unsupported query type '{query_type}' for query(). "
                "Only SELECT queries are supported. "
                "Use execute() for UPDATE queries or other query forms."
            )
            raise ValueError(msg)

        if export:
            chosen_format = resolve_export_format(query_type, export=export, output_format=output_format, backend_name="Blazegraph")

        response = requests.post(self.query_url, headers=self.headers_query, data={"query": sparql}, timeout=None)
        if response.status_code != 200:
            msg = f"[Blazegraph] SPARQL query failed: {response.status_code}\n{response.text}"
            raise RuntimeError(msg)

        data = response.json()
        bindings = data.get("results", {}).get("bindings", [])
        results = [{k: v["value"] for k, v in row.items()} for row in bindings]

        if export:
            export_select_results(results, output_format=chosen_format, filename=filename, separator=separator, backend_name="Blazegraph")

        return results

    def clear(self) -> None:
        """
        Clear all triples from the target graph or the default graph.
        """
        sparql = (
            f"CLEAR GRAPH <{self.graph_uri}>"
            if self.graph_uri else
            "CLEAR DEFAULT"
        )
        self._run_update(sparql)

    def _run_update(self, sparql: str) -> None:
        """
        Execute a SPARQL update request.

        Parameters:
        sparql : str
            The SPARQL update string.

        Raises
        ------
        RuntimeError
            If the update fails with a non-success HTTP status.
        """
        response = requests.post(self.update_url, headers=self.headers_update, data=sparql, timeout=None)
        if response.status_code not in {200, 204, 201}:
            msg = f"[Blazegraph] SPARQL update failed: {response.status_code}\n{response.text}"
            raise RuntimeError(msg)

    def _ensure_namespace_exists(self) -> None:
        """Ensure the Blazegraph namespace exists; recreate it in quad mode if needed."""
        namespace_admin_url = f"{self.base_url}/namespace"
        headers_admin = {"Content-Type": "text/plain; charset=UTF-8"}

        try:
            res = requests.get(namespace_admin_url, timeout=60)
        except requests.RequestException as err:
            msg = f"[Blazegraph] Could not connect to server: {err}"
            raise RuntimeError(msg) from err

        if self.namespace in res.text:
            return

        ns = self.namespace
        config = f"""
            com.bigdata.rdf.sail.namespace={ns}
            com.bigdata.rdf.sail.class=com.bigdata.rdf.sail.BigdataSail
            com.bigdata.rdf.sail.truthMaintenance=false
            com.bigdata.rdf.sail.isolatableIndices=false

            com.bigdata.rdf.store.AbstractTripleStore.quads=true
            com.bigdata.rdf.store.AbstractTripleStore.axiomsClass=com.bigdata.rdf.axioms.NoAxioms
            com.bigdata.rdf.store.AbstractTripleStore.textIndex=false
            com.bigdata.rdf.store.AbstractTripleStore.geoSpatial=false
            com.bigdata.rdf.store.AbstractTripleStore.justify=false
            com.bigdata.rdf.store.AbstractTripleStore.statementIdentifiers=false

            com.bigdata.namespace.{ns}.spo.com.bigdata.btree.BTree.branchingFactor=1024
            com.bigdata.namespace.{ns}.lex.com.bigdata.btree.BTree.branchingFactor=400
            """.strip()

        resp = requests.post(namespace_admin_url, headers=headers_admin, data=config, timeout=60)
        if resp.status_code not in {200, 201}:
            msg = f"[Blazegraph] Failed to create namespace '{self.namespace}': {resp.status_code}\n{resp.text}"
            raise RuntimeError(msg)
