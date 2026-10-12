import os
import tempfile

# Settings are read at import time, so set them before importing the app.
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["GEMINI_API_KEY"] = "dummy-key-for-tests"          # chatbot.py refuses to import without one
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.pop("FLASK_DEBUG", None)

import pytest

import app as app_module


@pytest.fixture()
def client(monkeypatch):
    calls = []

    def fake_gemini(message, history="", language="English"):
        calls.append({"message": message, "history": history, "language": language})
        return f"echo: {message}"

    monkeypatch.setattr(app_module, "ask_gemini", fake_gemini)
    c = app_module.app.test_client()
    c.calls = calls
    return c


def register(client, email="a@example.com", password="secret123"):
    return client.post("/api/register", json={"name": "Asha", "email": email, "password": password})
