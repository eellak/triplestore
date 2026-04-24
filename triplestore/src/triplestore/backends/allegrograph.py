# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0

import logging
import os
import urllib.parse as urlparse
from pathlib import Path
from typing import Any

import requests
from franz.openrdf.connect import ag_connect

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


class AllegroGraph(TriplestoreBackend):
    """
    A triplestore backend implementation for AllegroGraph using its SPARQL HTTP interface.
    """

    REQUIRED_KEYS = {"name"}
    OPTIONAL_DEFAULTS = {
        "base_url": "http://localhost:10035",
        "catalog": None,
        "graph": None,
        "auth": None,
    }
    ALIASES = {
        "graph_uri": "graph",
        "repository": "name",
    }

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Initialize the AllegroGraph backend with the given configuration.

         Parameters
        ----------
        config : dict
            Connection settings:
              - base_url (str, optional): Base URL of AllegroGraph (default: http://localhost:10035).
              - repository (str, required): Target repository name.
              - catalog (str, optional): Catalog name in AllegroGraph under which the repository resides.
              - auth (tuple[str, str], optional): Basic Auth credentials (username, password).
              - graph (str, optional): Named graph URI for scoping operations.

        Raises
        ------
        ValueError
            If 'repository' is missing or credentials are not provided via config or environment variables.
        """

        configuration = validate_config(config, required_keys=self.REQUIRED_KEYS, optional_defaults=self.OPTIONAL_DEFAULTS,
                                        alias_map=self.ALIASES, backend_name="AllegroGraph")

        super().__init__(configuration)
        self.base_url = configuration["base_url"]
        self.repository = configuration["name"]
        self.catalog = configuration["catalog"]
        self.graph_uri = configuration["graph"]

        auth_cfg = configuration["auth"]
        username: str | None = None
        password: str | None = None

        if auth_cfg is not None:
            try:
                username, password = auth_cfg
            except Exception as e:
                msg = ("[AllegroGraph] Invalid value for 'auth' in config. "
                    "Expected a tuple of the form (username, password).\n"
                    'Example: auth=("username", "password")'
                )
                raise ValueError(msg) from e

        if not username or not password:
            # Fallback to environment variables
            env_user = os.getenv("AG_USERNAME")
            env_pass = os.getenv("AG_PASSWORD")
            if env_user and env_pass:
                username, password = env_user, env_pass

        if not username or not password:
            msg = (
                "[AllegroGraph] No credentials found. "
                "Please provide login details either:\n"
                "  • in the config: auth=(username, password)\n"
                "  • or via environment variables: AG_USERNAME / AG_PASSWORD\n"
                "Without valid credentials, the connection to AllegroGraph cannot be established."
            )
            raise ValueError(msg)
        self.auth = (username, password)

        self._ensure_repository_exists()

        if self.catalog:
            base_repo_url = f"{self.base_url}/catalogs/{self.catalog}/repositories/{self.repository}"
        else:
            base_repo_url = f"{self.base_url}/repositories/{self.repository}"
        self.query_url = base_repo_url
        self.update_url = f"{base_repo_url}/statements"
        self.load_url = f"{base_repo_url}/statements"

        self.headers_query = {"Accept": "application/sparql-results+json"}
        self.headers_update = {"Content-Type": "application/x-www-form-urlencoded"}
        self.headers_load = {"Content-Type": "text/turtle"}

    def load(self, filename: str) -> None:
        """
        Load RDF data into the repository using the Graph Store Protocol.

        Supported formats:
        - .ttl: Turtle
        - .nt: N-Triples

        Parameters
        ----------
        filename : str
            Path to the RDF file to load (.ttl or .nt).

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        RuntimeError
            If the server responds with a non-success status code.
        """
        path = Path(filename)
        if not path.exists():
            msg = f"[AllegroGraph] File not found: {filename}"
            raise FileNotFoundError(msg)

        content_type = get_rdf_content_type(filename, backend_name="AllegroGraph")
        headers = {"Content-Type": content_type}

        params: dict[str, str] = {}
        if self.graph_uri:
            params["context"] = f"<{self.graph_uri}>"

        with path.open("rb") as f:
            response = requests.post(self.load_url, params=params, data=f, headers=headers, auth=self.auth, timeout=None)

        if response.status_code not in {200, 201, 204}:
            msg = f"[AllegroGraph] GSP load failed with status {response.status_code}:\n{response.text}"
            raise RuntimeError(msg)

    def add(self, s: Any, p: Any, o: Any) -> None:
        """
        Add a triple to the AllegroGraph store.

        Parameters:
        s : Any
            The subject value of the triple. Must serialize to an RDF IRI or blank node.
        p : Any
            The predicate value of the triple. Must serialize to an RDF IRI.
        o : Any
            The object value of the triple. May serialize to an RDF IRI, blank node, or literal.
        """
        s_term = validate_rdf_term(s, "subject", "AllegroGraph")
        p_term = validate_rdf_term(p, "predicate", "AllegroGraph")
        o_term = validate_rdf_term(o, "object", "AllegroGraph")

        triple = f"{s_term} {p_term} {o_term} ."

        if self.graph_uri:
            sparql = f"""
            INSERT {{
            GRAPH <{self.graph_uri}> {{ {triple} }}
            }}
            WHERE {{
            FILTER NOT EXISTS {{
                GRAPH <{self.graph_uri}> {{ {triple} }}
            }}
            }}
            """
        else:
            sparql = f"""
            INSERT {{ {triple} }}
            WHERE {{
            FILTER NOT EXISTS {{ {triple} }}
            }}
            """

        self._run_update(sparql)

    def delete(self, s: Any, p: Any, o: Any) -> None:
        """
        Delete a triple from the AllegroGraph store.

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
        s_term = validate_rdf_term(s, "subject", "AllegroGraph")
        p_term = validate_rdf_term(p, "predicate", "AllegroGraph")
        o_term = validate_rdf_term(o, "object", "AllegroGraph")

        if isinstance(s, str) and s.startswith("_:"):
            msg = (
                "[AllegroGraph] Cannot delete triples using a blank node as subject.\n\n"
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
            if self.graph_uri else
            f"DELETE DATA {{ {triple} }}"
        )
        self._run_update(sparql)

    def query(self, sparql: str, *, export: bool = False, output_format: str = "json", filename: str | None = None, separator: str = ",") -> list[dict[str, str]]:
        """
        Run a SPARQL SELECT query against the AllegroGraph repository.

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
                f"[AllegroGraph] Unsupported query type '{query_type}' for query(). "
                "Only SELECT queries are supported. "
                "Use execute() for UPDATE queries or other query forms."
            )
            raise ValueError(msg)

        if export:
            chosen_format = resolve_export_format(query_type, export=export, output_format=output_format, backend_name="AllegroGraph")

        response = requests.post(self.query_url, headers=self.headers_query, data={"query": sparql}, auth=self.auth, timeout=None)

        if response.status_code != 200:
            msg = f"[AllegroGraph] SPARQL query failed: {response.status_code}\n{response.text}"
            raise RuntimeError(msg)

        data = response.json()
        bindings = data.get("results", {}).get("bindings", [])
        results = [{k: v["value"] for k, v in row.items()} for row in bindings]

        if export:
            export_select_results(results, output_format=chosen_format, filename=filename, separator=separator, backend_name="AllegroGraph")

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
            Export format for saved results. If omitted and export=True, a default format is chosen
            based on the query type.
        filename : str, optional
            Output filename for exported results. The file extension is determined automatically
            from the requested export format.
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
        chosen_format = resolve_export_format(query_type, export=export, output_format=output_format, backend_name="AllegroGraph")

        # SELECT / ASK
        if query_type in {"SELECT", "ASK"}:
            response = requests.post(self.query_url, headers=self.headers_query, data={"query": sparql}, auth=self.auth, timeout=None)

            if response.status_code != 200:
                msg = f"[AllegroGraph] Query failed {response.status_code}:\n{response.text}"
                raise RuntimeError(msg)

            data = response.json()

            if query_type == "ASK":
                result = bool(data.get("boolean", False))
                if export:
                    export_ask_result(result, output_format=chosen_format, filename=filename, backend_name="AllegroGraph")
                return result

            bindings = data.get("results", {}).get("bindings", [])
            results = [{k: v["value"] for k, v in row.items()} for row in bindings]
            if export:
                export_select_results(results, output_format=chosen_format, filename=filename, separator=separator, backend_name="AllegroGraph")

            return results

        # CONSTRUCT / DESCRIBE
        if query_type in {"CONSTRUCT", "DESCRIBE"}:
            response = requests.post(self.query_url, headers={"Accept": "text/turtle"}, data={"query": sparql}, auth=self.auth, timeout=None)

            if response.status_code != 200:
                msg = f"[AllegroGraph] Graph query failed {response.status_code}:\n{response.text}"
                raise RuntimeError(msg)

            rdf_text = response.text

            if export:
                export_rdf_result(rdf_text, output_format=chosen_format, filename=filename, backend_name="AllegroGraph")

            return rdf_text

        # UPDATE
        if query_type in {
            "WITH", "INSERT", "DELETE", "LOAD", "CLEAR", "CREATE", "DROP",
            "MOVE", "COPY", "ADD", "MODIFY"
        }:
            self._run_update(sparql)
            return None

        msg = f"[AllegroGraph] Unsupported SPARQL keyword: {query_type}"
        raise RuntimeError(msg)

    def clear(self) -> None:
        """
        Remove all data from the AllegroGraph repository.
        Clears the named graph if specified, otherwise clears the default graph.
        """
        sparql = (
            f"CLEAR GRAPH <{self.graph_uri}>"
            if self.graph_uri else
            "DELETE WHERE { ?s ?p ?o }"
        )
        self._run_update(sparql)

    def _run_update(self, sparql: str) -> None:
        """
        Clear all triples from the repository.

        If a named graph is configured, it executes ``CLEAR GRAPH <graph>``.
        Otherwise, it deletes all triples from the default graph.

        Raises
        ------
        RuntimeError
            If the update request fails.
        """
        response = requests.post(self.update_url, headers=self.headers_update, data={"update": sparql}, auth=self.auth, timeout=None)
        if response.status_code not in {200, 204, 201}:
            msg = f"[AllegroGraph] SPARQL update failed: {response.status_code}\n{response.text}"
            raise RuntimeError(msg)

    def _ensure_repository_exists(self) -> None:
        """
        Ensure that the AllegroGraph repository exists.
        - Creates it if missing.
        - Opens it if already present (does not clear).
        """
        try:
            parsed = urlparse.urlparse(self.base_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 10035

            with ag_connect(self.repository, host=host, port=port, user=self.auth[0], password=self.auth[1], catalog=self.catalog,
                            create=True, clear=False) as conn:
                _ = conn.size()
        except Exception as e:
            msg = f"[AllegroGraph] Failed to ensure repository '{self.repository}' exists"
            raise RuntimeError(msg) from e
