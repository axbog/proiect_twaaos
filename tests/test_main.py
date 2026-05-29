import os
import sys

from fastapi.testclient import TestClient

# Ensure project root is on sys.path so tests can import `main`.
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from main import app


def test_root():
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "activ"
