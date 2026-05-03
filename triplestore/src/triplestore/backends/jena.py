# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0


import gzip
import shutil
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from triplestore.backends.jena_utils import add_graph_clause_if_needed, start_fuseki_server, stop_fuseki_server
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


class Jena(TriplestoreBackend):
    """
    A triplestore backend implementation for Apache Jena Fuseki using its HTTP REST API.
    """

    REQUIRED_KEYS = {"name"}
    OPTIONAL_DEFAULTS = {
        "base_url": "http://localhost:3030",
        "graph": None,
        "auth": None,
    }
    ALIASES = {
        "graph_uri": "graph",
        "dataset": "name",
    }

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Initialize the Jena backend with the given configuration.

        Parameters:
        config : dict
            A configuration dictionary containing connection parameters:
            - base_url (optional): The base URL of the Jena Fuseki server.
            - dataset : The name of the dataset to connect to.
            - auth (optional): Tuple (username, password) for HTTP Basic Auth.
            - graph (optional): Named graph URI for scoped operations.
        """
        configuration = validate_config(config, required_keys=self.REQUIRED_KEYS, optional_defaults=self.OPTIONAL_DEFAULTS,
                                        alias_map=self.ALIASES, backend_name="APACHE JENA")

        super().__init__(configuration)
        self.base_url = configuration["base_url"]
        self.dataset = configuration["name"]

        parsed = urlparse(self.base_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 3030

        start_fuseki_server(self.dataset, host, port)
        self.auth = configuration["auth"]
        self.graph_uri = configuration["graph"]
        if self.graph_uri:
            self._effective_graph = self.graph_uri
        else:
            self._effective_graph = "urn:app:default"

        self.load_url = f"{self.base_url}/{self.dataset}/data"
        self.query_url = f"{self.base_url}/{self.dataset}/query"
        self.update_url = f"{self.base_url}/{self.dataset}/update"

        self.headers_load = {"Content-Type": "text/turtle"}
        self.headers_query = {"Accept": "application/sparql-results+json"}
        self.headers_update = {"Content-Type": "application/sparql-update"}

        #self._ensure_dataset_exists()

    def load(self, filename: str) -> None:
        """
        Load RDF triples from a supported RDF file into the Jena dataset.

        If a named graph URI is provided in the configuration, data is loaded into that graph.

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
        path = Path(filename)
        if not path.exists():
            msg = f"[APACHE JENA] File not found: {filename}"
            raise FileNotFoundError(msg)
        
        content_type = get_rdf_content_type(filename, backend_name="APACHE JENA")

        params = {"graph": self._effective_graph}

        tmp_gz = tempfile.NamedTemporaryFile(prefix="rdf-", suffix=f"{path.suffix}.gz", delete=False)
        tmp_gz_path = Path(tmp_gz.name)
        try:
            with path.open("rb") as fin, gzip.open(tmp_gz, "wb", compresslevel=9) as fout:
                shutil.copyfileobj(fin, fout)
            tmp_gz.close()

            headers = {
                "Content-Type": content_type,
                "Content-Encoding": "gzip",
                "Connection": "keep-alive",
            }
            with tmp_gz_path.open("rb") as fz:
                response = requests.post(self.load_url, params=params, data=fz, headers=headers,
                                         auth=self.auth, timeout=(60, None))

            if response.status_code not in {200, 201, 204}:
                msg = f"[APACHE JENA] Import failed with status {response.status_code}:\n{response.text}"
                raise RuntimeError(msg)
        finally:
            try:
                tmp_gz_path.unlink(missing_ok=True)
            except Exception:
                pass

    def add(self, s: Any, p: Any, o: Any) -> None:
        """
        Add a triple to the Jena store.

        Parameters:
        s : Any
            The subject value of the triple. Must serialize to an RDF IRI or blank node.
        p : Any
            The predicate value of the triple. Must serialize to an RDF IRI.
        o : Any
            The object value of the triple. May serialize to an RDF IRI, blank node, or literal.
        """
        s_term = validate_rdf_term(s, "subject", "APACHE JENA")
        p_term = validate_rdf_term(p, "predicate", "APACHE JENA")
        o_term = validate_rdf_term(o, "object", "APACHE JENA")

        triple = f"{s_term} {p_term} {o_term} ."
        sparql = (
            f"INSERT DATA {{ GRAPH <{self._effective_graph}> {{ {triple} }} }}"
        )
        self._run_update(sparql)

    def delete(self, s: Any, p: Any, o: Any) -> None:
        """
        Delete a triple from the Jena store.

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
        s_term = validate_rdf_term(s, "subject", "APACHE JENA")
        p_term = validate_rdf_term(p, "predicate", "APACHE JENA")
        o_term = validate_rdf_term(o, "object", "APACHE JENA")

        if isinstance(s, str) and s.startswith("_:"):
            msg = (
                "[APACHE JENA] Cannot delete triples using a blank node as subject.\n\n"
                "Blank node identifiers (e.g. '_:b1') are local to a single SPARQL query "
                "or update and do not represent stable, reusable identifiers.\n"
                "Recommended alternatives:\n"
                " - Use a persistent IRI instead of a blank node if you need to delete the triple later.\n"
                " - Or delete using a pattern-based query (e.g. DELETE WHERE) that matches the triple.\n\n"
            )
            raise ValueError(msg)

        triple = f"{s_term} {p_term} {o_term} ."
        sparql = (
            f"DELETE DATA {{ GRAPH <{self._effective_graph}> {{ {triple} }} }}"
        )
        self._run_update(sparql)

    def query(self, sparql: str, *, export: bool = False, output_format: str = "json", filename: str | None = None, separator: str = ",") -> list[dict[str, str]]:
        """
        Execute a SPARQL SELECT query against the Jena dataset.

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
                f"[APACHE JENA] Unsupported query type '{query_type}' for query(). "
                "Only SELECT queries are supported. "
                "Use execute() for UPDATE queries or other query forms."
            )
            raise ValueError(msg)

        if export:
            chosen_format = resolve_export_format(query_type, export=export, output_format=output_format, backend_name="APACHE JENA")

        final_query = (
            add_graph_clause_if_needed(sparql, self._effective_graph)
            if getattr(self, "_effective_graph", None) == "urn:app:default"
            else sparql
        )

        response = requests.post(self.query_url, headers=self.headers_query, data={"query": final_query}, auth=self.auth, timeout=None)

        if response.status_code != 200:
            msg = f"[APACHE JENA] Query failed with status {response.status_code}:\n{response.text}"
            raise RuntimeError(msg)

        data = response.json()
        bindings = data.get("results", {}).get("bindings", [])
        results = [{k: v["value"] for k, v in row.items()} for row in bindings]

        if export:
            export_select_results(results, output_format=chosen_format, filename=filename, separator=separator, backend_name="APACHE JENA")

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
        chosen_format = resolve_export_format(query_type, export=export, output_format=output_format, backend_name="APACHE JENA")

        if query_type in {"SELECT", "ASK", "CONSTRUCT", "DESCRIBE"} and getattr(self, "_effective_graph", None) == "urn:app:default":
            final_query = add_graph_clause_if_needed(sparql, self._effective_graph)
        else:
            final_query = sparql

        # SELECT / ASK
        if query_type in {"SELECT", "ASK"}:
            response = requests.post(self.query_url, headers=self.headers_query, data={"query": final_query}, auth=self.auth, timeout=None)

            if response.status_code != 200:
                msg = f"[APACHE JENA] Query failed {response.status_code}:\n{response.text}"
                raise RuntimeError(msg)

            data = response.json()

            if query_type == "ASK":
                result = bool(data.get("boolean", False))
                if export:
                    export_ask_result(result, output_format=chosen_format, filename=filename, backend_name="APACHE JENA")
                return result

            bindings = data.get("results", {}).get("bindings", [])
            results = [{k: v["value"] for k, v in row.items()} for row in bindings]
            if export:
                export_select_results(results, output_format=chosen_format, filename=filename, separator=separator, backend_name="APACHE JENA")

            return results

        # CONSTRUCT / DESCRIBE
        if query_type in {"CONSTRUCT", "DESCRIBE"}:
            response = requests.post(self.query_url, headers={"Accept": "text/turtle"}, data={"query": final_query}, auth=self.auth, timeout=None)

            if response.status_code != 200:
                msg = f"[APACHE JENA] Query failed {response.status_code}:\n{response.text}"
                raise RuntimeError(msg)

            rdf_text = response.text
            if export:
                export_rdf_result(rdf_text, output_format=chosen_format, filename=filename, backend_name="APACHE JENA")

            return rdf_text

        # UPDATE family
        if query_type in {"WITH", "INSERT", "DELETE", "LOAD", "CLEAR", "CREATE", "DROP", "MOVE", "COPY", "ADD", "MODIFY"}:
            self._run_update(sparql)
            return None

        msg = f"[APACHE JENA] Unsupported SPARQL keyword: {query_type}"
        raise RuntimeError(msg)

    def clear(self) -> None:
        """
        Remove all triples from the dataset.

        If a named graph is specified, it is dropped silently (no error if it doesn't exist).
        Otherwise, the default graph is cleared.
        """
        sparql = f"DROP SILENT GRAPH <{self._effective_graph}>"

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
        response = requests.post(self.update_url, headers=self.headers_update, data=sparql, auth=self.auth, timeout=None)

        if response.status_code not in {200, 204}:
            msg = f"[APACHE JENA] Update failed with status {response.status_code}:\n{response.text}"
            raise RuntimeError(msg)

    def _ensure_dataset_exists(self) -> None:
        """
        Ensure that the configured dataset exists in Apache Jena Fuseki.
        If it does not, attempt to create it using the Admin REST API.

        Raises
        ------
        RuntimeError
            If unable to connect to the server or if dataset creation fails.
        """
        admin_url = f"{self.base_url}/$/datasets"

        try:
            response = requests.get(admin_url, auth=self.auth, timeout=60)
            if response.status_code not in {200, 401, 403}:
                msg = f"[APACHE JENA] Admin responded with unexpected status: {response.status_code}\n{response.text}"
                raise RuntimeError(msg)
        except requests.RequestException as e:
            msg = f"[APACHE JENA] Could not connect to Fuseki admin at {admin_url}: {e}"
            raise RuntimeError(msg) from e

        try:
            datasets = response.json().get("datasets", [])
        except ValueError:
            datasets = []

        existing_names = [ds.get("ds.name", "").lstrip("/") for ds in datasets]
        if self.dataset in existing_names:
            return

        db_type = "tdb2"
        db_path = getattr(self, "db_path", None)

        data = {"dbName": self.dataset, "dbType": db_type}
        if db_path:
            data["dbPath"] = db_path

        try:
            response = requests.post(admin_url, data=data, auth=self.auth, timeout=60)
        except requests.RequestException as err:
            msg = f"[APACHE JENA] Could not create dataset '{self.dataset}': {err}"
            raise RuntimeError(msg) from err

        if response.status_code != 200:
            if response.status_code in {401, 403}:
                msg = f"[APACHE JENA] Permission denied creating dataset '{self.dataset}'.\nAdmin credentials required.\nResponse: {response.text}"
                raise RuntimeError(msg)
            msg = f"[APACHE JENA] Failed to create dataset '{self.dataset}': {response.status_code}\n{response.text}"
            raise RuntimeError(msg)

    def stop_server(self) -> bool:
        """
        Stop running local Fuseki server processes.

        Returns
        -------
        bool
            True if at least one matching process was found, otherwise False.
        """
        return stop_fuseki_server()
