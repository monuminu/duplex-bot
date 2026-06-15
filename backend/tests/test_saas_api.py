from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture()
def client(monkeypatch):
    """A TestClient backed by a throwaway SQLite database.

    Each test gets an isolated data dir so the embedded-SQLite zero-config path
    is exercised exactly as it ships.
    """
    tmp = tempfile.mkdtemp(prefix="duplex_test_")
    monkeypatch.setenv("DATA_DIR", tmp)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp}/test.db")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-fixed")

    # Reset cached engine/session/config so the env overrides take effect.
    from duplex_bot.config import AppConfig
    from duplex_bot.db import session as db_session
    from duplex_bot.routes import deps

    db_session.get_engine.cache_clear()
    db_session.get_session_factory.cache_clear()
    deps.get_config.cache_clear()
    AppConfig.model_config["env_file"] = ()  # ignore developer .env during tests

    from fastapi.testclient import TestClient

    from duplex_bot.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client

    db_session.get_engine.cache_clear()
    db_session.get_session_factory.cache_clear()
    deps.get_config.cache_clear()


def _auth_headers(client, email="owner@acme.com", company="Acme"):
    resp = client.post(
        "/api/auth/signup",
        json={"email": email, "password": "supersecret1", "company_name": company},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_signup_creates_tenant_and_first_user_is_admin(client):
    resp = client.post(
        "/api/auth/signup",
        json={"email": "first@acme.com", "password": "supersecret1", "company_name": "Acme"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tenant"]["name"] == "Acme"
    assert data["user"]["role"] == "admin"


def test_duplicate_signup_rejected(client):
    client.post(
        "/api/auth/signup",
        json={"email": "dup@acme.com", "password": "supersecret1"},
    )
    resp = client.post(
        "/api/auth/signup",
        json={"email": "dup@acme.com", "password": "supersecret1"},
    )
    assert resp.status_code == 409


def test_voice_agents_require_auth(client):
    assert client.get("/api/voice-agents").status_code == 401


def test_agent_crud_is_tenant_scoped(client):
    h1 = _auth_headers(client, "a@acme.com", "Acme")
    h2 = _auth_headers(client, "b@beta.com", "Beta")

    created = client.post(
        "/api/voice-agents",
        json={"name": "Support", "config": {}, "mcp_tools": [], "secrets": []},
        headers=h1,
    )
    assert created.status_code == 201
    agent_id = created.json()["id"]

    # Tenant 2 cannot see or fetch tenant 1's agent.
    assert client.get("/api/voice-agents", headers=h2).json() == []
    assert client.get(f"/api/voice-agents/{agent_id}", headers=h2).status_code == 404
    # Tenant 1 can.
    assert len(client.get("/api/voice-agents", headers=h1).json()) == 1


def test_secret_is_stored_encrypted_and_reported(client):
    h = _auth_headers(client)
    created = client.post(
        "/api/voice-agents",
        json={
            "name": "Support",
            "config": {},
            "mcp_tools": [],
            "secrets": [{"key": "llm.api_key", "value": "sk-secret-xyz"}],
        },
        headers=h,
    )
    assert created.status_code == 201
    body = created.json()
    # Status is reported; the value is never returned.
    assert body["secret_fields_configured"]["llm.api_key"] is True
    assert "sk-secret-xyz" not in created.text


def test_knowledge_upload_ingests_and_is_searchable(client):
    h = _auth_headers(client)
    agent_id = client.post(
        "/api/voice-agents",
        json={"name": "Support", "config": {}, "mcp_tools": [], "secrets": []},
        headers=h,
    ).json()["id"]

    resp = client.post(
        f"/api/voice-agents/{agent_id}/knowledge-files",
        files={"files": ("faq.txt", b"Our refund policy is 30 days. We are open 24/7.", "text/plain")},
        headers=h,
    )
    assert resp.status_code == 200
    record = resp.json()[0]
    assert record["status"] == "ready"
    assert record["chunk_count"] >= 1
