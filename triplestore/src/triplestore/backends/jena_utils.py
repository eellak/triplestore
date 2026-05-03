# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import psutil
import requests


def sanitize_fuseki_dataset_name(name: str) -> str:
    """
    Sanitize a dataset name so it can be safely used as a Fuseki service name.

    The function preserves only alphanumeric characters, underscores, and hyphens.
    Any consecutive run of unsupported characters is replaced with a single hyphen.
    If the resulting name is empty, the default value ``"ds"`` is returned.

    Parameters
    ----------
    name : str
        Raw dataset name provided by the user.

    Returns
    -------
    str
        A sanitized dataset name suitable for use in Fuseki service paths.
    """
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", name.strip())
    return cleaned.strip("-") or "ds"


def create_tdb2_location() -> Path:
    """
    Determine the directory where the local TDB2 dataset files will be stored.

    Rules:
    - If the environment variable ``FUSEKI_BASE`` is set, the TDB2 directory
      is created as a sibling folder named ``DB2`` next to it.
    - Otherwise, the default location ``~/fuseki/DB2`` is used.
    The directory is created automatically if it does not already exist.

    Returns
    -------
    str
        Path to the TDB2 storage directory.
    """
    fb = os.environ.get("FUSEKI_BASE")
    if fb:
        base = Path(fb).expanduser().resolve()
        tdb2 = base.parent / "DB2"
    else:
        tdb2 = Path.home() / "fuseki" / "DB2"
    tdb2.mkdir(parents=True, exist_ok=True)
    return tdb2


def find_fuseki_server() -> str:
    """
    Locate the 'fuseki-server' executable in the current environment.
    Search order:
    1) If the environment variable $FUSEKI_HOME is defined and, if so, looks for the executable inside that directory.
    2) PATH lookup via shutil.which('fuseki-server')

    Returns
    -------
    str
        Absolute path to the located `fuseki-server` executable.

    Raises:
    ------
    FileNotFoundError
        If the `fuseki-server` executable cannot be found in either `FUSEKI_HOME` or the system `PATH`.
    """
    fh = os.environ.get("FUSEKI_HOME")
    if fh:
        cand = str(Path(fh).expanduser().resolve() / "fuseki-server")
        if Path(cand).exists():
            return cand

    exe = shutil.which("fuseki-server")
    if exe:
        return exe

    msg = (
        "\n[APACHE JENA] "
        "Unable to locate the 'fuseki-server' executable.\n"
        "How to fix:\n"
        "  • Install Apache Jena Fuseki and set FUSEKI_HOME to its installation directory.\n OR\n"
        "  • Ensure the directory containing 'fuseki-server' is on your PATH.\n OR\n"
        "  • On Windows, the launcher may be 'fuseki-server.bat' or 'fuseki-server.cmd'.\n\n"
        "Examples (Linux/macOS):\n"
        '  export FUSEKI_HOME="/path/to/apache-jena-fuseki-<version>"\n'
        '  export PATH="$FUSEKI_HOME:$PATH"\n'
        "  command -v fuseki-server\n\n"
        "Examples (Windows PowerShell):\n"
        "  $env:FUSEKI_HOME='C:\\\\path\\\\to\\\\apache-jena-fuseki-<version>'\n"
        '  $env:Path="$env:FUSEKI_HOME;$env:Path"\n'
        "  where fuseki-server\n\n"
        "If the issue persists, verify that the file exists and is executable (Permissions)\n"
        "and that you have access rights to the directory."
    )

    raise FileNotFoundError(msg)


def find_jena_geosparql_jar() -> str:
    """
    Locate the `jena-fuseki-geosparql` jar file in the current environment.
    Search order:
    1) If the environment variable $JENA_GEOSPARQL_JAR is defined and points to an existing jar file.
    2) If $FUSEKI_HOME/lib/jena-fuseki-geosparql-*.jar exists.
    3) Attempts to locate the `fuseki-server` executable and then looks for the jar inside the adjacent `lib` directory.

    Returns
    -------
    str
        Absolute path to the located `jena-fuseki-geosparql` jar file.

    Raises
    ------
    FileNotFoundError
        If the jar file cannot be found, or if `JENA_GEOSPARQL_JAR` is set but points to a non-existent file.
    """
    env_jar = os.environ.get("JENA_GEOSPARQL_JAR")
    if env_jar:
        p = Path(env_jar).expanduser().resolve()
        if p.exists():
            return str(p)
        msg = (
            "\n[APACHE JENA] "
            "The environment variable 'JENA_GEOSPARQL_JAR' is set, but the file it points to was not found.\n\n"
            f"Current value:\n  {p}\n\n"
            "What this means:\n"
            "  The library tried to use the path from 'JENA_GEOSPARQL_JAR', but no jar file exists there.\n\n"
            "How to fix:\n"
            "  • Check that the path is correct and that the jar file really exists there.\n OR\n"
            "  • Update JENA_GEOSPARQL_JAR so it points to the correct 'jena-fuseki-geosparql-<version>.jar' file.\n OR\n"
            "  • Remove JENA_GEOSPARQL_JAR and place the jar under '$FUSEKI_HOME/lib/' instead.\n\n"
            "Examples (Linux/macOS):\n"
            '  export JENA_GEOSPARQL_JAR="/path/to/jena-fuseki-geosparql-<version>.jar"\n'
            '  ls -l "$JENA_GEOSPARQL_JAR"\n\n'
            "Examples (Windows PowerShell):\n"
            "  $env:JENA_GEOSPARQL_JAR='C:\\\\path\\\\to\\\\jena-fuseki-geosparql-<version>.jar'\n"
            "  Get-Item $env:JENA_GEOSPARQL_JAR\n"
        )
        raise FileNotFoundError(msg)

    candidates: list[Path] = []

    fh = os.environ.get("FUSEKI_HOME")
    if fh:
        candidates.extend(sorted((Path(fh).expanduser().resolve() / "lib").glob("jena-fuseki-geosparql-*.jar")))

    try:
        fuseki = Path(find_fuseki_server()).expanduser().resolve()
        candidates.extend(sorted((fuseki.parent / "lib").glob("jena-fuseki-geosparql-*.jar")))
    except FileNotFoundError:
        pass

    for cand in candidates:
        if cand.exists():
            return str(cand)

    msg = (
    "\n[APACHE JENA] "
    "Unable to locate the 'jena-fuseki-geosparql' jar file.\n"
    "How to fix:\n"
    "  • Set JENA_GEOSPARQL_JAR to the full path of the jar file.\n OR\n"
    "  • Ensure the jar exists under $FUSEKI_HOME/lib/.\n OR\n"
    "  • Ensure the jar is installed under the lib/ directory next to the 'fuseki-server' executable.\n\n"
    "Expected jar name:\n"
    "  jena-fuseki-geosparql-<version>.jar\n\n"
    "Examples (Linux/macOS):\n"
    '  export JENA_GEOSPARQL_JAR="/path/to/jena-fuseki-geosparql-<version>.jar"\n'
    '  export FUSEKI_HOME="/path/to/apache-jena-fuseki-<version>"\n'
    '  ls "$FUSEKI_HOME/lib" | grep jena-fuseki-geosparql\n\n'
    "Examples (Windows PowerShell):\n"
    "  $env:JENA_GEOSPARQL_JAR='C:\\\\path\\\\to\\\\jena-fuseki-geosparql-<version>.jar'\n"
    "  $env:FUSEKI_HOME='C:\\\\path\\\\to\\\\apache-jena-fuseki-<version>'\n"
    '  Get-ChildItem "$env:FUSEKI_HOME\\lib" | Select-String jena-fuseki-geosparql\n\n'
    "If the issue persists, verify that the jar file exists, that the path is correct, "
    "and that you have permission to access the file and its directory."
    )
    raise FileNotFoundError(msg)


def start_fuseki_server(dataset_name: str, host: str = "localhost", port: int = 3030, *, show_server_logs: bool = False) -> Path:
    """
    Start a local SPARQL/GeoSPARQL-enabled Fuseki server backed by a TDB2 dataset directory.

    Parameters:
    -------
    dataset_name: str
        Name of the dataset/service to be created. The value is sanitized before being used in the Fuseki service path.
    host : str, default="localhost"
        Host used to build the readiness-check query endpoint.
    port : int, default=3030
        Port on which the Fuseki server should listen.
    show_server_logs: bool, default=False
        If True, forward server stdout/stderr to the terminal.
        If False (default), silence server output.

    Returns:
    -------
    str
        Path to the TDB2 dataset directory used by the server.

    Raises:
    -------
    RuntimeError
        If the server does not become ready within the startup timeout.
    """
    service = sanitize_fuseki_dataset_name(dataset_name)
    tdb2_loc = create_tdb2_location()
    dataset_dir = tdb2_loc / service
    dataset_dir.mkdir(parents=True, exist_ok=True)

    geosparql_jar = find_jena_geosparql_jar()

    env = os.environ.copy()
    env.setdefault("JAVA_TOOL_OPTIONS", "-Xms4g -Xmx8g")
    env.setdefault("FUSEKI_BASE", str(Path.home() / "fuseki" / "base"))
    Path(env["FUSEKI_BASE"]).mkdir(parents=True, exist_ok=True)

    cmd = ["java", "-jar", geosparql_jar, "-p", str(port), "-d", service, "-u", "-t2", "-t", str(dataset_dir), "-i"]

    if show_server_logs:
        subprocess.Popen(cmd, env=env)
    else:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)

    query_url = f"http://{host}:{port}/{service}/query"
    timeout = 20
    start_time = time.time()
    while True:
        try:
            response = requests.post(query_url, data={"query": "ASK {}"}, timeout=2)
            if response.status_code == 200:
                print(f"[APACHE JENA] Server is up after {time.time() - start_time:.1f}s.")
                break
        except requests.RequestException:
            pass
        if time.time() - start_time > timeout:
            msg = f"[APACHE JENA] Server did not start within {timeout}s on {host}:{port}."
            raise RuntimeError(msg)
        time.sleep(1)

    return dataset_dir


def stop_fuseki_server(timeout: int = 5) -> bool:
    """
    Stop running Fuseki-related server processes on the current machine.

    The function scans active system processes and looks for command lines that
    appear to belong to Apache Jena Fuseki or the GeoSPARQL-enabled Fuseki
    runtime. Matching processes are first asked to terminate gracefully. If a
    process does not exit within the given timeout, it is forcefully killed.

    Parameters:
    ----------
    timeout: int
        Number of seconds to wait for graceful termination before forcefully killing a process.

    Returns:
    ----------
        True if at least one process was stopped, False if none was found.
    """
    found = False
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            joined = " ".join(cmdline).lower()
            if ("fuseki-server" in joined or "jena-fuseki-geosparql" in joined or "org.apache.jena.fuseki" in joined):
                found = True
                proc.terminate()
                try:
                    proc.wait(timeout=timeout)
                except psutil.TimeoutExpired:
                    proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return found


def add_graph_clause_if_needed(q: str, graph: str) -> str:
    lower = q.lower()
    where_idx = lower.find(" where ")
    if where_idx == -1 or "select" not in lower[:where_idx]:
        return q
    try:
        open_idx = q.index("{", where_idx)
    except ValueError:
        return q

    if "graph" in q[open_idx: open_idx + len(q)].lower():
        return q

    depth, close_idx = 0, -1
    for i in range(open_idx, len(q)):
        ch = q[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                close_idx = i
                break
    if close_idx == -1:
        return q

    return (
        q[:open_idx + 1]
        + f" GRAPH <{graph}> {{"
        + q[open_idx + 1:close_idx]
        + " }"
        + q[close_idx:]
    )
