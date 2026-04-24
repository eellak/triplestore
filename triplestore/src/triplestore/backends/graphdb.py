# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import requests

from triplestore.base import TriplestoreBackend
from triplestore.utils import (
    detect_graphdb_url,
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


class GraphDB(TriplestoreBackend):
    """
    A triplestore backend implementation for Ontotext GraphDB using its HTTP REST API.
    """

    REQUIRED_KEYS = {"name"}
    OPTIONAL_DEFAULTS = {
        "base_url": detect_graphdb_url(),
        "graph": None,
        "auth": None,
    }
    ALIASES = {
        "graph_uri": "graph",
        "repository": "name"
    }

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Initialize the GraphDB backend with the given configuration.

        Parameters:
        config : dict
            A configuration dictionary containing connection parameters:
            - base_url (optional): The base URL of the GraphDB instance.
            - repository : The name of the target repository.
            - auth (optional): Tuple (username, password) for HTTP Basic Auth.
            - graph (optional): Named graph URI for scoped operations.

        Raises
        ------
        ValueError
            If the 'repository' key is missing from the configuration.
        RuntimeError
            If the repository does not exist and cannot be created.
        """
        configuration = validate_config(config, required_keys=self.REQUIRED_KEYS, optional_defaults=self.OPTIONAL_DEFAULTS,
                                        alias_map=self.ALIASES, backend_name="GraphDB")

        super().__init__(configuration)
        self.base_url = configuration["base_url"]
        self.repository = configuration["name"]
        self.auth = configuration["auth"]
        self.graph_uri = configuration["graph"]

        self.query_url = f"{self.base_url}/repositories/{self.repository}"
        self.update_url = f"{self.query_url}/statements"

        self.headers_query = {"Accept": "application/sparql-results+json"}
        self.headers_update = {"Content-Type": "application/sparql-update"}
        self.headers_load = {"Content-Type": "text/turtle"}

    def load(self, filename: str) -> None:
        """
        Load RDF triples from a supported RDF file into the GraphDB repository.

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
        RuntimeError
            If the server returns an error status during data loading.
        """
        if not Path(filename).exists():
            msg = f"[GraphDB] File not found: {filename}"
            raise FileNotFoundError(msg)

        content_type = get_rdf_content_type(filename, backend_name="GraphDB")
        headers = {"Content-Type": content_type}

        self._ensure_repository_exists()

        rdf_data = Path(filename).read_bytes()
        params = {}
        if self.graph_uri:
            params["context"] = f"<{self.graph_uri}>"
        response = requests.post(self.update_url, headers=headers, params=params, data=rdf_data, auth=self.auth, timeout=None)

        if response.status_code not in {200, 204, 201}:
            msg = f"[GraphDB] Load failed with status {response.status_code}:\n{response.text}"
            raise RuntimeError(msg)

    def bulk_load(self, filenames: str | list[str], mode: str = "load", repository_id: str | None = None) -> None:
        """
        Bulk-load RDF data into GraphDB using the offline ImportRDF tool.

        Parameters
        ----------
        filenames : str or list[str]
            One or more local RDF files or directories to import.
        mode : str, default="load"
            Import mode. Must be either "load" or "preload".
        repository_id : str, optional
            Repository ID to import into. If omitted, the configured backend repository name is used.

        Raises
        ------
        ValueError
            If `mode` is invalid or no input files are provided.
        FileNotFoundError
            If one of the input paths does not exist, or if the ImportRDF executable cannot be found.
        RuntimeError
            If the GraphDB server appears to be running or if the import fails.
        """
        if mode not in {"load", "preload"}:
            msg = (
                f"[GraphDB] bulk_load() received an invalid mode: '{mode}'. "
                "Supported modes are 'load' and 'preload'. "
                "Use 'load' for standard import or 'preload' for optimized bulk loading."
            )
            raise ValueError(msg)

        paths = [filenames] if isinstance(filenames, (str, os.PathLike)) else filenames
        if not paths or (len(paths) == 1 and not paths[0]):
            msg = (
                "[GraphDB] bulk_load() received no input paths. "
                "Expected a file path or a list of paths to RDF files or directories.\n"
                "Example: bulk_load('data.ttl')"
            )
            raise ValueError(msg)

        normalized_paths: list[str] = []
        for item in paths:
            path = Path(item)
            if not path.exists():
                msg = (
                    f"[GraphDB] bulk_load() could not find the input path: '{path}'. "
                    "Please ensure that the file or directory exists and the path is correct.\n"
                    "Example: bulk_load('data.ttl') or bulk_load(['/path/to/data.ttl'])"
                )
                raise FileNotFoundError(msg)
            normalized_paths.append(str(path.resolve()))

        repo_id = repository_id or self.repository

        graphdb_home = os.environ.get("GRAPHDB_HOME")
        if graphdb_home:
            importrdf = Path(graphdb_home).expanduser().resolve() / "bin" / "importrdf"
            if not importrdf.exists():
                msg = (
                    f"[GraphDB] 'GRAPHDB_HOME' is set to '{graphdb_home}', but the 'importrdf' "
                    f"executable was not found at: {importrdf}.\n"
                    "Ensure that GRAPHDB_HOME points to a valid GraphDB installation directory "
                    "containing 'bin/importrdf'."
                )
                raise FileNotFoundError(msg)
            importrdf_path = str(importrdf)
        else:
            importrdf_path = shutil.which("importrdf")
            if not importrdf_path:
                msg = (
                    "[GraphDB] Unable to locate the 'importrdf' executable.\n"
                    "Set the 'GRAPHDB_HOME' environment variable to your GraphDB installation directory "
                    "or ensure that 'importrdf' is available on your system PATH."
                )
                raise FileNotFoundError(msg)

        try:
            response = requests.get(self.base_url, timeout=3, auth=self.auth)
            if response.ok:
                msg = (
                    f"[GraphDB] bulk_load() cannot run while the GraphDB server is active at '{self.base_url}'. "
                    "The ImportRDF tool requires the server to be fully stopped before execution.\n"
                    "Please stop the GraphDB server and try again."
                )
                raise RuntimeError(msg)
        except requests.RequestException:
            pass

        command = [importrdf_path, mode, "-f", "-i", repo_id]
        if mode == "load":
            command.extend(["-m", "parallel"])
        command.extend(normalized_paths)

        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else ""
            stdout = exc.stdout.strip() if exc.stdout else ""
            details = stderr or stdout or str(exc)
            msg = f"[GraphDB] Bulk Load failed:\n{details}"
            raise RuntimeError(msg) from exc

    def add(self, s: Any, p: Any, o: Any) -> None:
        """
        Add a triple to the GraphDB store.

        Parameters:
        s : Any
            The subject value of the triple. Must serialize to an RDF IRI or blank node.
        p : Any
            The predicate value of the triple. Must serialize to an RDF IRI.
        o : Any
            The object value of the triple. May serialize to an RDF IRI, blank node, or literal.
        """
        s_term = validate_rdf_term(s, "subject", "GraphDB")
        p_term = validate_rdf_term(p, "predicate", "GraphDB")
        o_term = validate_rdf_term(o, "object", "GraphDB")

        triple = f"{s_term} {p_term} {o_term} ."
        sparql = (
            f"INSERT DATA {{ GRAPH <{self.graph_uri}> {{ {triple} }} }}"
            if self.graph_uri else
            f"INSERT DATA {{ {triple} }}"
        )
        self._run_update(sparql)

    def delete(self, s: Any, p: Any, o: Any) -> None:
        """
        Delete a triple from the GraphDB store.

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
        s_term = validate_rdf_term(s, "subject", "GraphDB")
        p_term = validate_rdf_term(p, "predicate", "GraphDB")
        o_term = validate_rdf_term(o, "object", "GraphDB")

        if isinstance(s, str) and s.startswith("_:"):
            msg = (
                "[GraphDB] Cannot delete triples using a blank node as subject.\n\n"
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
        Execute a SPARQL query against the GraphDB repository.

        Parameters:
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

        Returns:
        list of dict
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
            msg = (f"[GraphDB] Unsupported query type '{query_type}' for query(). "
                "Only SELECT queries are supported. "
                "Use execute() for UPDATE queries or other query forms."
            )
            raise ValueError(msg)

        if export:
            chosen_format = resolve_export_format(query_type, export=export, output_format=output_format, backend_name="GraphDB")

        self._ensure_repository_exists()

        response = requests.post(self.query_url, headers=self.headers_query, data={"query": sparql}, auth=self.auth, timeout=None)

        if response.status_code != 200:
            msg = f"[GraphDB] SPARQL query failed: {response.status_code}\n{response.text}"
            raise RuntimeError(msg)

        data = response.json()
        bindings = data.get("results", {}).get("bindings", [])
        results = [{k: v["value"] for k, v in row.items()} for row in bindings]

        if export:
            export_select_results(results, output_format=chosen_format, filename=filename, separator=separator, backend_name="GraphDB")

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
        chosen_format = resolve_export_format(query_type, export=export, output_format=output_format, backend_name="GraphDB")

        self._ensure_repository_exists()

        # SELECT / ASK
        if query_type in {"SELECT", "ASK"}:
            response = requests.post(self.query_url, headers=self.headers_query, data={"query": sparql}, auth=self.auth, timeout=None)

            if response.status_code != 200:
                msg = f"[GraphDB] Query failed {response.status_code}:\n{response.text}"
                raise RuntimeError(msg)

            data = response.json()

            if query_type == "ASK":
                result = bool(data.get("boolean", False))
                if export:
                    export_ask_result(result, output_format=chosen_format, filename=filename, backend_name="GraphDB")
                return result

            bindings = data.get("results", {}).get("bindings", [])
            results = [{k: v["value"] for k, v in row.items()} for row in bindings]
            if export:
                export_select_results(results, output_format=chosen_format, filename=filename, separator=separator, backend_name="GraphDB")

            return results

        # CONSTRUCT / DESCRIBE
        if query_type in {"CONSTRUCT", "DESCRIBE"}:
            response = requests.post(self.query_url, headers={"Accept": "text/turtle"}, data={"query": sparql}, auth=self.auth, timeout=None)

            if response.status_code != 200:
                msg = f"[GraphDB] Query failed {response.status_code}:\n{response.text}"
                raise RuntimeError(msg)

            rdf_text = response.text

            if export:
                export_rdf_result(rdf_text, output_format=chosen_format, filename=filename, backend_name="GraphDB")

            return rdf_text

        #  UPDATE operations (INSERT, DELETE, CLEAR, DROP, LOAD, CREATE, etc.)
        if query_type in {
            "WITH", "INSERT", "DELETE", "LOAD", "CLEAR", "CREATE", "DROP",
            "MOVE", "COPY", "ADD", "MODIFY"
        }:
            self._run_update(sparql)
            return None

        msg = f"[GraphDB] Unsupported SPARQL keyword: {query_type}"
        raise RuntimeError(msg)

    def clear(self) -> None:
        """
        Remove all data from the GraphDB repository (default and named graphs).
        """
        sparql = f"CLEAR GRAPH <{self.graph_uri}>" if getattr(self, "graph_uri", None) else "CLEAR DEFAULT"
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
        self._ensure_repository_exists()

        response = requests.post(self.update_url, headers=self.headers_update, data=sparql, auth=self.auth, timeout=None)
        if response.status_code not in {200, 204, 201}:
            msg = f"[GraphDB] SPARQL update failed: {response.status_code}\n{response.text}"
            raise RuntimeError(msg)

    def _ensure_repository_exists(self):
        """
        Ensure that the configured repository exists in GraphDB.
        If it does not, attempt to create it using the REST API.

        Raises
        ------
        RuntimeError
            If unable to connect to the server or if repository creation fails.
        """
        check_url = f"{self.base_url}/rest/repositories/{self.repository}"

        try:
            response = requests.get(check_url, timeout=300, auth=self.auth)
            if response.status_code == 200:
                return
            if response.status_code in {401, 403}:
                logger.warning(
                    "[GraphDB] Access denied when checking repository '%s' at %s "
                    "(HTTP %s). The repository may exist but you don't have permission "
                    "to access it. If you're using GraphDB Desktop, REST admin ops may "
                    "be disabled. Consider creating the repository from the UI or using "
                    "server mode with admin REST enabled.",
                    self.repository, check_url, response.status_code,
                )
                msg = (f"[GraphDB] Access denied while checking repository '{self.repository}' "
                      f"(HTTP {response.status_code}). The repository may exist but is not "
                      f"accessible with the provided credentials/instance settings.")
                raise RuntimeError(msg)
        except requests.RequestException as e:
            msg = f"[GraphDB] Could not connect to GraphDB at {check_url}: {e}"
            raise RuntimeError(msg) from e

        create_url = f"{self.base_url}/rest/repositories"

        body = f"""@prefix st: <http://www.openrdf.org/config/repository#> .
    @prefix sr: <http://www.openrdf.org/config/repository/sail#> .
    @prefix sail: <http://www.openrdf.org/config/sail#> .
    @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
    @prefix graphdb: <http://www.ontotext.com/config/graphdb#> .

    [] a st:Repository ;
    st:repositoryID "{self.repository}" ;
    st:repositoryImpl [
        st:repositoryType "graphdb:SailRepository" ;
        sr:sailImpl [
            sail:sailType "graphdb:Sail" ;
            graphdb:ruleset "rdfsplus-optimized" ;
            graphdb:enable-context-index "true"^^xsd:boolean ;
            graphdb:enable-predicate-list "true"^^xsd:boolean ;
            graphdb:in-memory-literal-properties "false"^^xsd:boolean ;
            graphdb:enable-literal-index "true"^^xsd:boolean ;
            graphdb:enable-geo-spatial "true"^^xsd:boolean ;
            graphdb:enable-full-text-search "false"^^xsd:boolean ;
            graphdb:fts-index-policy "ALL" ;
            graphdb:strict-parsing "true"^^xsd:boolean ;
            graphdb:enable-query-logging "false"^^xsd:boolean
        ]
    ] .
    """

        files = {"config": ("repo-config.ttl", body, "application/x-turtle")}

        resp = requests.post(create_url, files=files, timeout=60, auth=self.auth)

        if resp.status_code in {200, 201}:
            try:
                verify_url = f"{self.base_url}/rest/repositories/{self.repository}"
                verify = requests.get(verify_url, timeout=60, auth=self.auth)
            except requests.RequestException as e:
                msg = f"[GraphDB] Repository '{self.repository}' created, but verification GET failed: {e}"
                raise RuntimeError(msg) from e
            if verify.status_code in {200, 201}:
                return

        if resp.status_code == 403:
            msg = (
                f"[GraphDB] Cannot create repository '{self.repository}' — permission denied (403).\n"
                f"Hint: You are likely using GraphDB Desktop which restricts repository creation via REST.\n"
                f"Either:\n"
                f"  • Create it manually at http://localhost:7200\n"
                f"  • Or run GraphDB in server mode with admin REST enabled.\n\n"
                f"Response: {resp.text}"
            )
            raise RuntimeError(msg)

        msg = (
            f"[GraphDB] Failed to create repo '{self.repository}': "
            f"{resp.status_code} {resp.text}"
        )
        raise RuntimeError(msg)
