# Copyright (C) 2026 Saksham
# SPDX-License-Identifier: Apache-2.0

import pytest

from triplestore.utils import validate_rdf_term


def test_validate_rdf_term_rejects_unknown_position():
    with pytest.raises(ValueError, match="Invalid RDF position"):
        validate_rdf_term("http://example.org/resource", "subjectx")


def test_validate_rdf_term_accepts_supported_positions():
    assert validate_rdf_term("http://example.org/resource", "subject") == "<http://example.org/resource>"
    assert validate_rdf_term("http://example.org/knows", "predicate") == "<http://example.org/knows>"
    assert validate_rdf_term("Alice", "object") == '"Alice"'
