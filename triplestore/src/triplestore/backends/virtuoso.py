# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0

import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from requests.auth import HTTPDigestAuth

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

logger = logging.getLogger(__name__)


class Virtuoso(TriplestoreBackend):
    """
    A triplestore backend implementation for OpenLink Virtuoso using its HTTP SPARQL API.
    """

    REQUIRED_KEYS = {}
    OPTIONAL_DEFAULTS = {
        "base_url": "http://localhost:8890",
        "graph": None,
        "auth": None,
        "name": "test"
    }
    ALIASES = {
        "graph_uri": "graph",
        "repository": "name",
    }

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Initialize the Virtuoso backend with the given configuration.

        Parameters:
        ----------
        config : dict
            Connection settings for the Virtuoso instance. Supported keys:
            - base_url : str, optional
                Base URL of the Virtuoso server (default: http://localhost:8890).
            - name : str, optional
                Logical repository name used as a fallback graph identifier.
            - auth : tuple[str, str], optional
                Credentials in the form (username, password).
            - graph : str, optional
                Named graph URI for scoping SPARQL operations.

        Raises
        ------
        ValueError
            If the provided `auth` value is invalid or if no credentials are
            available via configuration or environment variables.
        RuntimeError
            If the Virtuoso SPARQL endpoint is unreachable.
        """
        configuration = validate_config(config, required_keys=self.REQUIRED_KEYS, optional_defaults=self.OPTIONAL_DEFAULTS,
                                        alias_map=self.ALIASES, backend_name="Virtuoso")

        super().__init__(configuration)
        self.base_url = self._normalize_base_url(configuration["base_url"])
        self.repository = configuration["name"]
        self.graph_uri = configuration["graph"] or self._default_graph_uri(self.repository)

        auth_cfg = configuration["auth"]
        username: str | None = None
        password: str | None = None

        if auth_cfg is not None:
            try:
                username, password = auth_cfg
            except Exception as e:
                msg = (
                    "[Virtuoso] Invalid value for 'auth' in config. "
                    "Expected a tuple of the form (username, password).\n"
                    'Example: auth=("dba", "dba")'
                )
                raise ValueError(msg) from e

        if not username or not password:
            env_user = os.getenv("VIRTUOSO_USERNAME")
            env_pass = os.getenv("VIRTUOSO_PASSWORD")
            if env_user and env_pass:
                username, password = env_user, env_pass

        if not username or not password:
            msg = (
                "[Virtuoso] No credentials found. "
                "Please provide login details either:\n"
                "  • in the config: auth=(username, password)\n"
                "  • or via environment variables: VIRTUOSO_USERNAME / VIRTUOSO_PASSWORD\n"
                "Without valid credentials, the connection to Virtuoso cannot be established."
            )
            raise ValueError(msg)
        self.auth = HTTPDigestAuth(username, password)

        self.query_url = f"{self.base_url}/sparql"
        self.update_url = f"{self.base_url}/sparql-auth"
        self.graph_store_url = f"{self.base_url}/sparql-graph-crud-auth"

        self.headers_query = {"Accept": "application/sparql-results+json"}
        self.headers_update = {"Content-Type": "application/sparql-update"}
        self.headers_load = {"Content-Type": "text/turtle"}

        self._ensure_endpoint_exists()

    def load(self, filename: str) -> None:
        """
        Load RDF triples from a supported RDF file into a Virtuoso named graph.

        Supported formats:
        - .ttl: Turtle
        - .nt: N-Triples

        Parameters:
        filename : str
            Path to the RDF file to load (.ttl or .nt).

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        RuntimeError
            If the server returns an error status during data loading.
        """
        if not Path(filename).exists():
            msg = f"[Virtuoso] File not found: {filename}"
            raise FileNotFoundError(msg)
        
        content_type = get_rdf_content_type(filename, backend_name="Virtuoso")
        headers = {"Content-Type": content_type}

        rdf_data = Path(filename).read_bytes()
        params = {"graph-uri": self.graph_uri} if self.graph_uri else {}
        response = requests.post(self.graph_store_url, headers=headers, params=params, data=rdf_data, auth=self.auth, timeout=None)

        if response.status_code not in {200, 201, 204}:
            msg = f"[Virtuoso] Load failed with status {response.status_code}:\n{response.text}"
            raise RuntimeError(msg)

    def add(self, s: Any, p: Any, o: Any) -> None:
        """
        Add a triple to the Virtuoso store.

        Parameters:
        s : Any
            The subject value of the triple. Must serialize to an RDF IRI or blank node.
        p : Any
            The predicate value of the triple. Must serialize to an RDF IRI.
        o : Any
            The object value of the triple. May serialize to an RDF IRI, blank node, or literal.
        """
        s_term = validate_rdf_term(s, "subject", "Virtuoso")
        p_term = validate_rdf_term(p, "predicate", "Virtuoso")
        o_term = validate_rdf_term(o, "object", "Virtuoso")

        triple = f"{s_term} {p_term} {o_term} ."
        sparql = (
            f"INSERT DATA {{ GRAPH <{self.graph_uri}> {{ {triple} }} }}"
            if self.graph_uri
            else f"INSERT DATA {{ {triple} }}"
        )
        self._run_update(sparql)

    def delete(self, s: Any, p: Any, o: Any) -> None:
        """
        Delete a triple from the Virtuoso store.

        Parameters:
        s : Any
            The subject value of the triple. Must serialize to an RDF IRI or blank node.
        p : Any
            The predicate value of the triple. Must serialize to an RDF IRI.
        o : Any
            The object value of the triple. May serialize to an RDF IRI, blank node, or literal.

        Raises
        ------
        ValueError
            If a blank node is provided as the subject.
        """
        s_term = validate_rdf_term(s, "subject", "Virtuoso")
        p_term = validate_rdf_term(p, "predicate", "Virtuoso")
        o_term = validate_rdf_term(o, "object", "Virtuoso")

        if isinstance(s, str) and s.startswith("_:"):
            msg = (
                "[Virtuoso] Cannot delete triples using a blank node as subject.\n\n"
                "Blank node identifiers (e.g. '_:b1') are local to a single SPARQL query "
                "or update and do not represent stable, reusable identifiers.\n"
                "Recommended alternatives:\n"
                " - Use a persistent IRI instead of a blank node if you need to delete the triple later.\n"
                " - Or delete using a pattern-based query (e.g. DELETE WHERE) that matches the triple.\n\n"
            )
            raise ValueError(msg)

        triple = f"{s_term} {p_term} {o_term} ."
        sparql = (
            f"DELETE DATA {{ GRAPH <{self.graph_uri}> {{ {triple} }} }}"
            if self.graph_uri
            else f"DELETE DATA {{ {triple} }}"
        )
        self._run_update(sparql)

    def query(self, sparql: str, *, export: bool = False, output_format: str = "json", filename: str | None = None, separator: str = ",") -> list[dict[str, str]]:
        """
        Execute a SPARQL SELECT query against the Virtuoso endpoint.

        Parameters
        ----------
        sparql : str
            The SPARQL query string.
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
            The list of query result bindings.

        Raises
        ------
        ValueError
            If query() is called with a non-SELECT query or with an unsupported export format.
        RuntimeError
            If the query fails or the server returns an error response.
        """
        query_type = get_sparql_query_type(sparql)

        if query_type != "SELECT":
            msg = (
                f"[Virtuoso] Unsupported query type '{query_type}' for query(). "
                "Only SELECT queries are supported. "
                "Use execute() for UPDATE queries or other query forms."
            )
            raise ValueError(msg)

        if export:
            chosen_format = resolve_export_format(query_type, export=export, output_format=output_format, backend_name="Virtuoso")

        response = requests.post(self.query_url, headers=self.headers_query, data={"query": sparql}, auth=self.auth, timeout=None)

        if response.status_code != 200:
            msg = f"[Virtuoso] SPARQL query failed: {response.status_code}\n{response.text}"
            raise RuntimeError(msg)

        data = response.json()
        bindings = data.get("results", {}).get("bindings", [])
        results = [{k: v["value"] for k, v in row.items()} for row in bindings]

        if export:
            export_select_results(results, output_format=chosen_format, filename=filename, separator=separator, backend_name="Virtuoso")

        return results

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
            - str (Turtle RDF) for CONSTRUCT/DESCRIBE
            - None for UPDATE operations

        Raises
        ------
        RuntimeError
            If the server responds with an error status.
        """
        query_type = get_sparql_query_type(sparql)
        chosen_format = resolve_export_format(query_type, export=export, output_format=output_format, backend_name="Virtuoso")

        # SELECT / ASK
        if query_type in {"SELECT", "ASK"}:
            response = requests.post(self.query_url, headers=self.headers_query, data={"query": sparql}, auth=self.auth, timeout=None)

            if response.status_code != 200:
                msg = f"[Virtuoso] Query failed {response.status_code}:\n{response.text}"
                raise RuntimeError(msg)

            data = response.json()

            if query_type == "ASK":
                result = bool(data.get("boolean", False))
                if export:
                    export_ask_result(result, output_format=chosen_format, filename=filename, backend_name="Virtuoso")
                return result

            bindings = data.get("results", {}).get("bindings", [])
            results = [{k: v["value"] for k, v in row.items()} for row in bindings]
            if export:
                export_select_results(results, output_format=chosen_format, filename=filename, separator=separator, backend_name="Virtuoso")

            return results

        # CONSTRUCT / DESCRIBE
        if query_type in {"CONSTRUCT", "DESCRIBE"}:
            response = requests.post(self.query_url, headers={"Accept": "text/turtle"}, data={"query": sparql}, auth=self.auth, timeout=None)

            if response.status_code != 200:
                msg = f"[Virtuoso] Query failed {response.status_code}:\n{response.text}"
                raise RuntimeError(msg)

            rdf_text = response.text
            if export:
                export_rdf_result(rdf_text, output_format=chosen_format, filename=filename, backend_name="Virtuoso")

            return rdf_text

        # UPDATE operations
        if query_type in {
            "WITH", "INSERT", "DELETE", "LOAD", "CLEAR", "CREATE", "DROP",
            "MOVE", "COPY", "ADD", "MODIFY",
        }:
            self._run_update(sparql)
            return None

        msg = f"[Virtuoso] Unsupported SPARQL keyword: {query_type}"
        raise RuntimeError(msg)

    def clear(self) -> None:
        """
        Remove all data from the configured Virtuoso graph.
        """
        sparql = (
            f"CLEAR GRAPH <{self.graph_uri}>"
            if getattr(self, "graph_uri", None)
            else "CLEAR DEFAULT"
        )
        self._run_update(sparql)

    def _run_update(self, sparql: str) -> None:
        """
        Execute a SPARQL update operation.

        Parameters:
        sparql : str
            The SPARQL update string to be sent to the server.

        Raises
        ------
        RuntimeError
            If the update operation fails with a non-success status code.
        """
        response = requests.post(self.update_url, headers=self.headers_update, data=sparql.encode("utf-8"), auth=self.auth, timeout=None)
        if response.status_code not in {200, 201, 204}:
            msg = f"[Virtuoso] SPARQL update failed: {response.status_code}\n{response.text}"
            raise RuntimeError(msg)

    def _ensure_endpoint_exists(self) -> None:
        """
        Ensure that the configured Virtuoso SPARQL endpoint is reachable.

        Raises
        ------
        RuntimeError
            If unable to connect to the server or if the endpoint is inaccessible.
        """
        try:
            response = requests.get(self.query_url, timeout=60, auth=self.auth)
        except requests.RequestException as e:
            msg = f"[Virtuoso] Could not connect to Virtuoso at {self.query_url}: {e}"
            raise RuntimeError(msg) from e

        if response.status_code in {200, 401, 403}:
            return

        msg = (
            f"[Virtuoso] SPARQL endpoint check failed at {self.query_url}: "
            f"HTTP {response.status_code}\n{response.text}"
        )
        raise RuntimeError(msg)

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        """
        Normalize the configured base URL by removing any trailing slashes
        and ensuring it does not end with a SPARQL-specific path (e.g. `/sparql`).

        Parameters
        ----------
        base_url : str
            The base URL of the Virtuoso server as provided in the configuration.

        Returns
        -------
        str
            The normalized base URL without trailing slashes or `/sparql` suffix.
        """
        return base_url.rstrip("/").removesuffix("/sparql")

    @staticmethod
    def _default_graph_uri(name: str) -> str:
        """
        Construct a default graph URI based on the provided repository name.

        If the given name is already a valid absolute URI, it is returned as-is.
        Otherwise, a fallback URI is generated under the `http://example.org/` namespace.

        Parameters
        ----------
        name : str
            The logical name of the repository or graph.

        Returns
        -------
        str
            A valid graph URI derived from the given name.
        """
        parsed = urlparse(name)
        if parsed.scheme and parsed.netloc:
            return name
        return f"http://example.org/{name}"
