# Copyright (C) 2025 Maira Papadopoulou
# SPDX-License-Identifier: Apache-2.0


from abc import ABC, abstractmethod
from typing import Any


class TriplestoreBackend(ABC):
    """
    Abstract base class for all triplestore backends.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    @abstractmethod
    def load(self, filename: str) -> None:
        """
        Load RDF triples from a file into the triplestore.
        """

    @abstractmethod
    def add(self, subj: Any, pred: Any, obj: Any) -> None:
        """
        Add a single RDF triple to the store.
        """

    @abstractmethod
    def delete(self, subj: Any, pred: Any, obj: Any) -> None:
        """
        Delete a single RDF triple from the store.
        """

    @abstractmethod
    def query(self, sparql: str) -> Any:
        """
        Execute a SPARQL *SELECT* query and return results.

        - SELECT -> typically returns a list of dicts with variable bindings
        """

    @abstractmethod
    def execute(self, sparql: str) -> Any:
        """
        Execute any SPARQL query (SELECT, ASK, CONSTRUCT, DESCRIBE, UPDATE).

        Returns
        -------
        Any
            - list of dict for SELECT queries
            - bool for ASK queries
            - str (RDF in Turtle) for CONSTRUCT/DESCRIBE
            - None for UPDATE operations
        """

    @abstractmethod
    def clear(self) -> None:
        """
        Remove all triples from the triplestore.
        """
