# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0

"""
Tests for the offline bulk loading of the GraphDB backend.

These tests use the GraphDB ImportRDF tool, so the server must be stopped
before import and started again afterwards.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
import requests
from triplestore import Triplestore
from triplestore.utils import detect_graphdb_url

BULK_SUBJECT = "http://example.org/bulk_s"
BULK_PREDICATE = "http://example.org/bulk_p"
BULK_OBJECT = "http://example.org/bulk_o"

GRAPHDB_BASE_URL = detect_graphdb_url()

GRAPHDB_HOME_ENV = os.environ.get("GRAPHDB_HOME")
GRAPHDB_HOME = Path(GRAPHDB_HOME_ENV).expanduser().resolve() if GRAPHDB_HOME_ENV else None
GRAPHDB_BIN = GRAPHDB_HOME / "bin" / "graphdb" if GRAPHDB_HOME else Path("/invalid/path")

config = {
    "name": f"testns-bulk-{int(time.time())}",
}


pytestmark = pytest.mark.skipif(
    not GRAPHDB_HOME or not GRAPHDB_BIN.exists(),
    reason=(
        "[GraphDB] Skipped because GraphDB is not properly configured.\n"
        "Expected environment variable GRAPHDB_HOME pointing to a valid installation.\n"
        "Required executable not found: $GRAPHDB_HOME/bin/graphdb"
    ),
)


def is_graphdb_available():
    """Return True if the GraphDB HTTP endpoint is reachable."""
    try:
        response = requests.get(f"{GRAPHDB_BASE_URL}/repositories", timeout=2)
    except requests.RequestException:
        return False
    else:
        return response.status_code in {200, 401, 403}


def wait_until_graphdb_is_up(timeout: int = 60) -> None:
    """Wait until GraphDB becomes reachable."""
    deadline = time.time() + timeout

    while time.time() < deadline:
        if is_graphdb_available():
            return
        time.sleep(1)

    msg = "GraphDB did not start in time."
    raise RuntimeError(msg)


def wait_until_graphdb_is_down(timeout: int = 30) -> None:
    """Wait until GraphDB becomes unreachable."""
    deadline = time.time() + timeout

    while time.time() < deadline:
        if not is_graphdb_available():
            return
        time.sleep(1)

    msg = "GraphDB did not stop in time."
    raise RuntimeError(msg)


def start_graphdb_server() -> None:
    """Start the local GraphDB server using GRAPHDB_HOME/bin/graphdb."""
    if is_graphdb_available():
        return

    subprocess.Popen([str(GRAPHDB_BIN)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, start_new_session=True)
    wait_until_graphdb_is_up()


def _find_graphdb_pids() -> list[int]:
    """Return the PIDs of processes listening on port 7200."""
    try:
        result = subprocess.run(["lsof", "-ti", ":7200"], check=False, capture_output=True, text=True)
    except FileNotFoundError as err:
        msg = "lsof is not available on this system."
        raise RuntimeError(msg) from err

    if result.returncode not in {0, 1}:
        msg = f"lsof failed: {result.stderr.strip()}"
        raise RuntimeError(msg)

    if result.returncode == 1 or not result.stdout.strip():
        return []

    return [int(pid) for pid in result.stdout.split()]


def stop_graphdb_server() -> None:
    """Stop the local GraphDB server."""
    pids = _find_graphdb_pids()

    if not pids:
        if not is_graphdb_available():
            return
        msg = "GraphDB is reachable, but no process listening on port 7200 was found."
        raise RuntimeError(msg)

    for pid in pids:
        subprocess.run(["kill", "-TERM", str(pid)], check=False)
    wait_until_graphdb_is_down()


def create_bulk_turtle_file() -> str:
    """Create a temporary Turtle file for bulk_load() tests."""
    turtle_data = f"<{BULK_SUBJECT}> <{BULK_PREDICATE}> <{BULK_OBJECT}> ."

    with tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".ttl", encoding="utf-8") as f:
        f.write(turtle_data)
        return f.name


def ask_bulk_triple(store: Triplestore) -> bool:
    """Return True if the expected triple exists in the store."""
    return store.execute(
        f"""
        ASK {{
            <{BULK_SUBJECT}> <{BULK_PREDICATE}> <{BULK_OBJECT}>
        }}
        """
    )


def test_bulk_load_rejects_invalid_mode():
    """Test that bulk_load() rejects unsupported mode values."""
    store = Triplestore("graphdb", config=config)

    with pytest.raises(ValueError, match="Supported modes are 'load' and 'preload'"):
        store.bulk_load("dummy.ttl", mode="invalid")


def test_bulk_load_rejects_empty_input():
    """Test that bulk_load() rejects empty input paths."""
    store = Triplestore("graphdb", config=config)

    with pytest.raises(ValueError, match="received no input paths"):
        store.bulk_load([], mode="load")


def test_bulk_load_rejects_missing_file():
    """Test that bulk_load() raises FileNotFoundError for a missing input path."""
    store = Triplestore("graphdb", config=config)

    with pytest.raises(FileNotFoundError, match="could not find the input path"):
        store.bulk_load("does_not_exist.ttl", mode="load")


def test_bulk_load_mode_load():
    """Test that bulk_load() in 'load' mode imports data correctly."""
    start_graphdb_server()
    store = Triplestore("graphdb", config=config)
    store.clear()

    tmp_path = create_bulk_turtle_file()

    try:
        stop_graphdb_server()
        store.bulk_load(tmp_path, mode="load")
        start_graphdb_server()
        assert ask_bulk_triple(store) is True
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        if is_graphdb_available():
            store.clear()
            stop_graphdb_server()


def test_bulk_load_mode_preload():
    """Test that bulk_load() in 'preload' mode imports data correctly."""
    start_graphdb_server()
    store = Triplestore("graphdb", config=config)
    store.clear()

    tmp_path = create_bulk_turtle_file()

    try:
        stop_graphdb_server()
        store.bulk_load(tmp_path, mode="preload")
        start_graphdb_server()
        assert ask_bulk_triple(store) is True
    finally:
        Path(tmp_path).unlink(missing_ok=True)
        if is_graphdb_available():
            store.clear()
            stop_graphdb_server()
