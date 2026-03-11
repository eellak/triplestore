# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0

import logging
from pathlib import Path
from typing import Any

import requests

from triplestore.base import TriplestoreBackend
from triplestore.utils import detect_graphdb_url, validate_config

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

        self._ensure_repository_exists()

    def load(self, filename: str) -> None:
        """
        Load RDF triples from a Turtle (.ttl) file into the GraphDB repository.

        Parameters:
        filename : str
            Path to the Turtle (.ttl) file to be loaded.

        Raises
        ------
        RuntimeError
            If the server returns an error status during data loading.
        """
        if not Path(filename).exists():
            msg = f"[GraphDB] File not found: {filename}"
            raise FileNotFoundError(msg)

        rdf_data = Path(filename).read_bytes()
        params = {}
        if self.graph_uri:
            params["context"] = f"<{self.graph_uri}>"
        response = requests.post(self.update_url, headers=self.headers_load, params=params, data=rdf_data, auth=self.auth, timeout=None)

        if response.status_code not in {200, 204, 201}:
            msg = f"[GraphDB] Load failed with status {response.status_code}:\n{response.text}"
            raise RuntimeError(msg)

    def add(self, s: str, p: str, o: str) -> None:
        """
        Add a triple to the GraphDB store.

        Parameters:
        s : str
            The subject URI of the triple.
        p : str
            The predicate URI of the triple.
        o : str
            The object URI of the triple.
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
        Delete a triple from the GraphDB store.

        Parameters:
        s : str
            The subject URI of the triple to remove.
        p : str
            The predicate URI of the triple to remove.
        o : str
            The object URI of the triple to remove.
        """
        triple = f"<{s}> <{p}> <{o}> ."
        sparql = (
            f"DELETE DATA {{ GRAPH <{self.graph_uri}> {{ {triple} }} }}"
            if self.graph_uri else
            f"DELETE DATA {{ {triple} }}"
        )
        self._run_update(sparql)

    def query(self, sparql: str) -> list[dict[str, str]]:
        """
        Execute a SPARQL query against the GraphDB repository.

        Parameters:
        sparql : str
            The SPARQL query string.

        Returns:
        list of dict
            The list of query result bindings.

        Raises
        ------
        RuntimeError
            If the query fails or the server returns an error response.
        """
        response = requests.post(self.query_url, headers=self.headers_query, data={"query": sparql}, auth=self.auth, timeout=None)

        if response.status_code != 200:
            msg = f"[GraphDB] SPARQL query failed: {response.status_code}\n{response.text}"
            raise RuntimeError(msg)

        data = response.json()
        bindings = data.get("results", {}).get("bindings", [])
        return [{k: v["value"] for k, v in row.items()} for row in bindings]

    def execute(self, sparql: str) -> Any:
        """
        Execute any SPARQL query (SELECT, ASK, CONSTRUCT, DESCRIBE, UPDATE).

        Parameters
        ----------
        sparql : str
            The SPARQL query or update string.

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
        # qstrip = sparql.lstrip()
        # query_type = qstrip.split(None, 1)[0].upper() if qstrip else ""

        lines = [line.strip() for line in sparql.strip().splitlines() if line.strip()]

        query_type = ""
        for line in lines:
            upper = line.upper()
            if upper.startswith("PREFIX ") or upper.startswith("BASE "):
                continue
            query_type = line.split(None, 1)[0].upper()
            break

        # SELECT / ASK
        if query_type in {"SELECT", "ASK"}:
            response = requests.post(self.query_url, headers=self.headers_query, data={"query": sparql}, auth=self.auth, timeout=None)
            if response.status_code != 200:
                msg = f"[GraphDB] Query failed {response.status_code}:\n{response.text}"
                raise RuntimeError(msg)
            data = response.json()
            if query_type == "ASK":
                return bool(data.get("boolean", False))
            bindings = data.get("results", {}).get("bindings", [])
            return [{k: v["value"] for k, v in row.items()} for row in bindings]

        # CONSTRUCT / DESCRIBE
        if query_type in {"CONSTRUCT", "DESCRIBE"}:
            response = requests.post(self.query_url, headers={"Accept": "text/turtle"}, data={"query": sparql}, auth=self.auth, timeout=None)
            if response.status_code != 200:
                msg = f"[GraphDB] Query failed {response.status_code}:\n{response.text}"
                raise RuntimeError(msg)
            return response.text

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
        if getattr(self, "graph_uri", None):
            sparql = f"CLEAR GRAPH <{self.graph_uri}>"
        else:
            sparql = "CLEAR DEFAULT"
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
        check_url = f"{self.base_url}/repositories/{self.repository}"

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

        try:
            delete_url = f"{self.base_url}/repositories/{self.repository}"
            requests.delete(delete_url, timeout=300, auth=self.auth)
        except requests.RequestException as err:
            msg = f"[GraphDB] Failed to delete repo {self.repository} silently: {err}"
            logger.debug(msg)

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
