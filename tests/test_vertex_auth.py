"""Authentication boundary checks with no real credentials or model calls."""

import os
from types import SimpleNamespace

import pytest
from google.auth.credentials import AnonymousCredentials
from google.auth.exceptions import DefaultCredentialsError
from google.genai import types
from typer.testing import CliRunner

from precedent.cli import app
from precedent.config import VertexSettings
from precedent.worker import runner


def test_cloud_configuration_requires_project_even_if_legacy_key_exists(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "obsolete-test-key")
    with pytest.raises(ValueError, match="GOOGLE_CLOUD_PROJECT"):
        runner.make_model("gemini-3.8-flash")


def test_cloud_configuration_defaults_to_supported_global_endpoint(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", " test-project ")
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
    assert VertexSettings.from_env() == VertexSettings("test-project", "global")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", " ")
    with pytest.raises(ValueError, match="must not be empty"):
        VertexSettings.from_env()


@pytest.mark.parametrize("name", ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash"])
def test_all_model_factories_pass_adc_project_location_and_preserve_http_options(monkeypatch, name):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    credentials = AnonymousCredentials()
    calls = []

    def adc(**kwargs):
        calls.append(kwargs)
        return credentials, "different-discovered-project"

    kwargs = {}
    sentinel = object()

    def client(**values):
        kwargs.update(values)
        return sentinel

    monkeypatch.setattr(runner.google.auth, "default", adc)
    monkeypatch.setattr(runner.genai, "Client", client)
    monkeypatch.setattr(runner, "Gemini", lambda **values: values)
    model = runner.make_model(name)
    assert calls == [
        {
            "scopes": ["https://www.googleapis.com/auth/cloud-platform"],
            "quota_project_id": "test-project",
        }
    ]
    assert model == {"model": name, "client": sentinel}
    assert kwargs["credentials"] is credentials
    assert kwargs["vertexai"] is True
    assert kwargs["project"] == "test-project"
    assert kwargs["location"] == "us-central1"
    assert "api_key" not in kwargs
    assert kwargs["http_options"].timeout == runner.MODEL_TIMEOUT_MS
    retry = kwargs["http_options"].retry_options
    assert (retry.attempts, retry.initial_delay, retry.max_delay) == (2, 2, 10)


def test_installed_sdk_ignores_stale_api_keys_and_developer_mode(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")
    monkeypatch.setenv("GEMINI_API_KEY", "obsolete-test-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "unrelated-test-key")
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "false")
    monkeypatch.setenv("GOOGLE_GENAI_USE_ENTERPRISE", "false")
    credentials = AnonymousCredentials()
    monkeypatch.setattr(runner.google.auth, "default", lambda **_: (credentials, None))
    model = runner.make_model("gemini-3.8-flash")
    client = model.client
    try:
        assert client.vertexai is True
        # Inspect the actual installed SDK transport, not only our factory arguments.
        transport = client._api_client
        assert transport.api_key is None
        assert transport._credentials is credentials
        assert transport.project == "test-project" and transport.location == "global"
        assert transport._http_options.base_url == "https://aiplatform.googleapis.com/"
        assert "x-goog-api-key" not in transport._http_options.headers
        assert "GEMINI_API_KEY" in os.environ  # no global environment mutation
    finally:
        client.close()


def test_missing_adc_is_actionable_and_does_not_fall_back_to_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GEMINI_API_KEY", "obsolete-test-key")

    def missing(**_):
        raise DefaultCredentialsError("No identity available")

    monkeypatch.setattr(runner.google.auth, "default", missing)
    with pytest.raises(
        DefaultCredentialsError, match="gcloud auth application-default login"
    ) as exc:
        runner.make_model("gemini-3.8-flash")
    assert isinstance(exc.value.__cause__, DefaultCredentialsError)
    assert "No identity available" in str(exc.value)


def test_adc_cli_smoke_uses_factory_and_closes_clients(monkeypatch):
    calls, closed = [], []

    async def close_async():
        closed.append("async")

    class Model:
        client = SimpleNamespace(
            aio=SimpleNamespace(aclose=close_async), close=lambda: closed.append("sync")
        )

        async def generate_content_async(self, request):
            calls.append(request)
            yield SimpleNamespace(
                content=types.Content(parts=[types.Part(text="Vertex ADC works")])
            )

    names = []

    def make(name):
        names.append(name)
        return Model()

    monkeypatch.setattr(runner, "make_model", make)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("PRECEDENT_MODEL", "gemini-3.8-flash")
    result = CliRunner().invoke(app, ["check-model"])
    assert result.exit_code == 0 and "Vertex ADC works" in result.output
    assert names == ["gemini-3.8-flash"] and len(calls) == 1
    assert calls[0].contents[0].parts[0].text == 'Reply exactly with "Vertex ADC works".'
    assert closed == ["async", "sync"]


def test_auth_check_keeps_google_error_visible(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")

    def fail(_):
        raise DefaultCredentialsError("Run gcloud auth application-default login")

    monkeypatch.setattr(runner, "check_model", fail)
    result = CliRunner().invoke(app, ["check-model"])
    assert result.exit_code == 1
    assert "DefaultCredentialsError" in result.output
    assert "gcloud auth application-default login" in result.output
