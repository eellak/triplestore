# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0

import logging
import subprocess
import time
from pathlib import Path
from typing import Any

import requests

from triplestore.base import TriplestoreBackend
from triplestore.utils import validate_config

logger = logging.getLogger(__name__)


class QLever(TriplestoreBackend):
    """
    A triplestore backend implementation for QLever using its HTTP REST API.
    """

    REQUIRED_KEYS = {"dataset", "working_directory"}
    OPTIONAL_DEFAULTS = {
        "base_url": "http://localhost:7019",
        "graph": None,
    }
    ALIASES = {
        "graph_uri": "graph",
        "url": "base_url",
        "endpoint": "base_url",
    }

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Initialize the QLever backend with the given configuration.

        Parameters:
        config : dict
            A configuration dictionary containing connection parameters:
            - dataset : The name of the QLever dataset.
            - working_directory : Directory where QLever configuration and index files are stored.
            - base_url (optional): The base URL of the QLever HTTP endpoint.
            - graph (optional): Named graph URI for scoped operations.
        """

        configuration = validate_config(config, required_keys=self.REQUIRED_KEYS, optional_defaults=self.OPTIONAL_DEFAULTS,
                                        alias_map=self.ALIASES, backend_name="QLever")

        super().__init__(configuration)
        self.base_url = configuration["base_url"]
        self.graph_uri = configuration["graph"]

        self.query_url = self.base_url
        self.update_url = self.base_url

        self.headers_query = {"Accept": "application/sparql-results+json"}
        self.headers_update = {"Content-Type": "application/sparql-update"}
        self.headers_load = {"Content-Type": "text/turtle"}

        self.dataset = configuration["dataset"]
        self.working_directory = Path(configuration["working_directory"]).expanduser().resolve()
        self.container_name = f"qlever.server.{self.dataset}"

        self.start_server()
        self.access_token = self._read_access_token()

    def load(self, filename: str) -> None:
        """
        Load RDF triples from a Turtle (.ttl) file into QLever.

        Parameters:
        filename : str
            Path to the Turtle (.ttl) file to be loaded.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        RuntimeError
            If the server responds with an error during data loading.
        """
        if not Path(filename).exists():
            msg = f"[QLever] File not found: {filename}"
            raise FileNotFoundError(msg)

        rdf_data = Path(filename).read_bytes()
        params = {}

        if self.graph_uri:
            params["graph"] = self.graph_uri

        if self.access_token:
            params["access-token"] = self.access_token

        response = requests.post(self.update_url, headers=self.headers_load, data=rdf_data, params=params, timeout=None)
        if response.status_code not in {200, 204, 201}:
            msg = f"[QLever] Load failed with status: {response.status_code}\n{response.text}"
            raise RuntimeError(msg)

    def add(self, s: str, p: str, o: str) -> None:
        """
        Add a triple to the QLever store.

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
        Delete a triple from the QLever store.

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

    def query(self, sparql: str) -> list[dict[str, str]]:
        """
        Execute a SPARQL SELECT query against QLever.

        Parameters:
        sparql : str
            The SPARQL query string.

        Returns:
        list of dict
            A list of bindings from the query results.

        Raises
        ------
        RuntimeError
            If the query fails or the server returns an error response.
        """
        response = requests.post(self.query_url, headers=self.headers_query, data={"query": sparql}, timeout=None)
        if response.status_code != 200:
            msg = f"[QLever] SPARQL query failed: {response.status_code}\n{response.text}"
            raise RuntimeError(msg)

        data = response.json()
        bindings = data.get("results", {}).get("bindings", [])
        return [{k: v["value"] for k, v in row.items()} for row in bindings]

    def execute(self, sparql: str) -> Any:
        """
        Execute any SPARQL query (SELECT, ASK, CONSTRUCT, DESCRIBE, UPDATE).

        Parameters:
        ----------
        sparql : str
            The SPARQL query or update string.

        Returns:
        ----------
        Any
            - list of dict for SELECT
            - bool for ASK
            - str (RDF serialization) for CONSTRUCT/DESCRIBE
            - None for UPDATE operations

        Raises
        ------
        RuntimeError
            If the server responds with an error status.
        """
        lines = [line.strip() for line in sparql.strip().splitlines() if line.strip()]

        query_type = ""
        for line in lines:
            upper = line.upper()
            if upper.startswith(("PREFIX ", "BASE ")):
                continue
            query_type = line.split(None, 1)[0].upper()
            break

        # SELECT / ASK
        if query_type in {"SELECT", "ASK"}:
            response = requests.post(self.query_url, headers=self.headers_query, data={"query": sparql}, timeout=None)
            if response.status_code != 200:
                msg = f"[QLever] Query failed {response.status_code}:\n{response.text}"
                raise RuntimeError(msg)
            data = response.json()
            if query_type == "ASK":
                return bool(data.get("boolean", False))
            bindings = data.get("results", {}).get("bindings", [])
            return [{k: v["value"] for k, v in row.items()} for row in bindings]

        # CONSTRUCT / DESCRIBE
        if query_type in {"CONSTRUCT", "DESCRIBE"}:
            response = requests.post(self.query_url, headers={"Accept": "text/turtle"}, data={"query": sparql}, timeout=None)
            if response.status_code != 200:
                msg = f"[QLever] SPARQL query failed: {response.status_code}\n{response.text}"
                raise RuntimeError(msg)
            return response.text

        # UPDATE family
        if query_type in {
            "WITH", "INSERT", "DELETE", "LOAD", "CLEAR", "CREATE", "DROP",
            "MOVE", "COPY", "ADD", "MODIFY"
        }:
            self._run_update(sparql)
            return None

        msg = f"[QLever] Unsupported SPARQL keyword: {query_type}"
        raise RuntimeError(msg)

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
            If the update operation fails with a non-success HTTP status code.
        """
        params = {}
        if self.access_token:
            params["access-token"] = self.access_token

        response = requests.post(self.update_url, headers=self.headers_update, params=params, data=sparql, timeout=None)
        if response.status_code not in {200, 204, 201}:
            msg = f"[QLever] SPARQL update failed: {response.status_code}\n{response.text}"
            raise RuntimeError(msg)

    def start_server(self) -> None:
        """
        Start or initialize a QLever server for the configured dataset.

        This method ensures that the QLever environment for the dataset is
        properly prepared. If a container already exists, it will simply be
        started. Otherwise the method performs the full initialization:

        1. Create the working directory if it does not exist.
        2. Generate the QLever configuration file (Qleverfile).
        3. Download the dataset if it is not already present.
        4. Build the QLever index.
        5. Start the QLever server.

        Raises
        ------
        ValueError
        If the dataset name or working directory configuration is missing or invalid.
        RuntimeError
            If the QLever server fails to start or does not become ready.
        """

        if self.working_directory.exists() and not self.working_directory.is_dir():
            msg = (
                f"[QLever] Invalid working_directory: '{self.working_directory}' exists "
                "but is not a directory. Please provide a valid directory path."
            )
            raise ValueError(msg)

        self.working_directory.mkdir(parents=True, exist_ok=True)

        if self._container_exists():
            logger.info("QLever container '%s' already exists. Starting existing server...", self.container_name)

            subprocess.run(["docker", "start", self.container_name], check=True)

            self._wait_until_ready()
            return

        logger.info("Initializing QLever dataset '%s' in %s", self.dataset, self.working_directory)

        qleverfile = self.working_directory / "Qleverfile"
        if not qleverfile.exists():
            subprocess.run(["qlever", "setup-config", self.dataset], cwd=self.working_directory, check=True)

        data_file = self.working_directory / f"{self.dataset}.nt"
        if not data_file.exists():
            subprocess.run(["qlever", "get-data"], cwd=self.working_directory, check=True)

        index_file = self.working_directory / f"{self.dataset}.index.pso"
        if not index_file.exists():
            subprocess.run(["qlever", "index"], cwd=self.working_directory, check=True)

        subprocess.run(["qlever", "start"], cwd=self.working_directory, check=True)

        self._wait_until_ready()

    def stop_server(self) -> None:
        """
        Stop the QLever Docker container associated with this dataset.

        Raises
        ------
        RuntimeError
            If the Docker command fails or the container cannot be stopped.
        """

        logger.info("Stopping QLever container '%s'", self.container_name)

        try:
            subprocess.run(["docker", "stop", self.container_name], check=True)
        except subprocess.CalledProcessError as exc:
            msg = (
                f"[QLever] Failed to stop container '{self.container_name}'. "
                "Please check that Docker is running and the container exists."
            )
            raise RuntimeError(msg) from exc

    def _read_access_token(self) -> str:
        """
        Read the QLever access token from the dataset Qleverfile.
        The access token is required for authenticated update operations.

        Returns
        -------
        str
            The resolved access token for the current dataset.

        Raises
        ------
        RuntimeError
            If the Qleverfile does not exist or if the ACCESS_TOKEN entry cannot be found in the file.
        """
        qleverfile = self.working_directory / "Qleverfile"

        if not qleverfile.exists():
            msg = (
                f"[QLever] Qleverfile not found in working directory: "
                f"{self.working_directory}. "
                "Make sure the dataset has been initialized with "
                "'qlever setup-config'."
            )
            raise RuntimeError(msg)

        with qleverfile.open(encoding="utf-8") as file_obj:
            for raw_line in file_obj:
                stripped_line = raw_line.strip()

                if stripped_line.startswith("ACCESS_TOKEN"):
                    _, value = stripped_line.split("=", 1)
                    return value.strip().replace("${data:NAME}", self.dataset)

        msg = ("[QLever] ACCESS_TOKEN not found in Qleverfile. "
            "The dataset configuration may be incomplete."
        )
        raise RuntimeError(msg)

    def _container_exists(self) -> bool:
        """
        Check whether the QLever Docker container already exists.

        Returns
        -------
        bool
            True if a container with the expected name exists, otherwise False.

        Raises
        ------
        RuntimeError
            If the Docker command cannot be executed.
        """
        try:
            result = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{.Names}}"],
                capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as exc:
            msg = (
                "[QLever] Failed to check existing Docker containers. "
                "Please ensure Docker is installed and running."
            )
            raise RuntimeError(msg) from exc

        return self.container_name in result.stdout.splitlines()

    def _wait_until_ready(self, timeout: int = 30) -> None:
        """
        Wait until the QLever server becomes available.

        Parameters
        ----------
        timeout : int, optional
            Maximum number of seconds to wait for the server to become ready.
            Default is 30 seconds.

        Raises
        ------
        RuntimeError
            If the server does not respond successfully within the timeout.
        """

        deadline = time.time() + timeout
        last_error = None

        while time.time() < deadline:
            try:
                response = requests.get(f"{self.base_url}/?cmd=stats", timeout=2)
                if response.status_code == 200:
                    return
            except requests.RequestException as e:
                last_error = e

            time.sleep(1)

        msg = (
            f"[QLever] Server did not become ready at {self.base_url} "
            f"within {timeout} seconds. Please check that the server started "
            "correctly and that the endpoint is reachable."
        )
        raise RuntimeError(msg) from last_error
