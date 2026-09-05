# Copyright (C) 2026 Saksham
# SPDX-License-Identifier: Apache-2.0

from types import SimpleNamespace
from unittest.mock import Mock

from triplestore import utils


def test_detect_host_url_uses_resolved_ip_command(monkeypatch):
    monkeypatch.setattr(utils.platform, "uname", lambda: SimpleNamespace(release="microsoft-standard-WSL2"))
    monkeypatch.setattr(utils.shutil, "which", Mock(return_value="/usr/sbin/ip"))
    check_output = Mock(return_value=b"default via 172.20.0.1 dev eth0\n")
    monkeypatch.setattr(utils.subprocess, "check_output", check_output)

    result = utils.detect_host_url(7200, path="/repositories")

    assert result == "http://172.20.0.1:7200/repositories"
    check_output.assert_called_once_with(["/usr/sbin/ip", "route"])


def test_detect_host_url_falls_back_when_ip_command_is_unavailable(monkeypatch):
    monkeypatch.setattr(utils.platform, "uname", lambda: SimpleNamespace(release="microsoft-standard-WSL2"))
    monkeypatch.setattr(utils.shutil, "which", Mock(return_value=None))

    result = utils.detect_host_url(7200, fallback="http://fallback:7200")

    assert result == "http://fallback:7200"
