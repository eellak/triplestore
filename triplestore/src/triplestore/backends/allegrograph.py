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
from triplestore.utils import validate_config

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

        Parameters
        ----------
        filename : str
            Path to the RDF file to load (e.g. Turtle).

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

        params: dict[str, str] = {}
        if self.graph_uri:
            params["context"] = f"<{self.graph_uri}>"

        with path.open("rb") as f:
            response = requests.post(self.load_url, params=params, data=f, headers=self.headers_load, auth=self.auth, timeout=None)

        if response.status_code not in {200, 201, 204}:
            msg = f"[AllegroGraph] GSP load failed with status {response.status_code}:\n{response.text}"
            raise RuntimeError(msg)

    def add(self, s: str, p: str, o: str) -> None:
        """
        Add a triple to the AllegroGraph store.

        Parameters:
        s : str
            The subject URI of the triple.
        p : str
            The predicate URI of the triple.
        o : str
            The object URI of the triple.
        """
        # triple = f"<{s}> <{p}> <{o}> ."
        # sparql = (
        #     f"INSERT DATA {{ GRAPH <{self.graph_uri}> {{ {triple} }} }}"
        #     if self.graph_uri else
        #     f"INSERT DATA {{ {triple} }}"
        # )
        # self._run_update(sparql)

        triple = f"<{s}> <{p}> <{o}> ."

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


    def delete(self, s: str, p: str, o: str) -> None:
        """
        Delete a triple from the AllegroGraph store.

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
        Run a SPARQL SELECT query against the AllegroGraph repository.

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
            msg = f"[AllegroGraph] SPARQL query failed: {response.status_code}\n{response.text}"
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
        qstrip = sparql.lstrip()
        query_type = qstrip.split(None, 1)[0].upper() if qstrip else ""
        if not query_type:
            msg = "[AllegroGraph] Could not detect SPARQL keyword."
            raise RuntimeError(msg)

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
                msg = f"[AllegroGraph] Query failed {response.status_code}:\n{response.text}"
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
                msg = f"[AllegroGraph] Graph query failed {response.status_code}:\n{response.text}"
                raise RuntimeError(msg)
            return response.text

        # UPDATE
        if query_type in {"WITH", "INSERT", "DELETE", "LOAD", "CLEAR", "CREATE", "DROP",
                "MOVE", "COPY", "ADD", "MODIFY"}:
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
