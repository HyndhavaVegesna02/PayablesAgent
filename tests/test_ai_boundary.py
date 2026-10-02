"""Two boundaries around Gemini (batch 2 plan, CHG-004 AC8 and AC9):
- app/ai/client.py is the only module that imports google.genai. This is an
  AST scan rather than an import-linter contract, because import-linter
  squashes external packages to their top-level name ("google"), which would
  also catch google-auth (Gmail, CHG-009).
- No test opens a network connection (tests/conftest.py)."""

import ast
import socket
from pathlib import Path

import pytest

from tests.conftest import NetworkBlocked

APP = Path(__file__).resolve().parent.parent / "app"
CLIENT = APP / "ai" / "client.py"


def genai_imports(source: str) -> list[int]:
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(a.name == "google.genai" or a.name.startswith("google.genai.") for a in node.names):
                lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == "google.genai" or node.module.startswith("google.genai."):
                lines.append(node.lineno)
            elif node.module == "google" and any(a.name == "genai" for a in node.names):
                lines.append(node.lineno)
    return lines


def test_only_ai_client_imports_google_genai():
    found = [
        f"{p.relative_to(APP.parent).as_posix()}:{n}"
        for p in sorted(APP.rglob("*.py")) if p.resolve() != CLIENT.resolve()
        for n in genai_imports(p.read_text(encoding="utf-8"))
    ]
    assert found == [], "only app/ai/client.py may import google.genai: " + ", ".join(found)


def test_ai_client_does_import_it():
    assert genai_imports(CLIENT.read_text(encoding="utf-8"))  # else the scan above proves nothing


@pytest.mark.parametrize("src", [
    "import google.genai", "import google.genai.types as t", "from google import genai",
    "from google.genai import types", "from google.genai.errors import APIError",
    "def f():\n    from google import genai\n",
])
def test_the_scan_sees_every_import_form(src):
    assert genai_imports(src)


@pytest.mark.parametrize("src", ["import google.auth", "from google.oauth2 import credentials",
                                 "from . import genai", "x = 'from google import genai'"])
def test_the_scan_ignores_other_google_packages_and_strings(src):
    assert genai_imports(src) == []


def test_a_test_cannot_reach_the_network():
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("192.0.2.1", 443), timeout=1)  # TEST-NET-1, never routed
    with pytest.raises(NetworkBlocked):
        socket.getaddrinfo("generativelanguage.googleapis.com", 443)


def test_loopback_is_still_allowed():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    try:
        client = socket.create_connection(server.getsockname(), timeout=1)
        client.close()
    finally:
        server.close()
