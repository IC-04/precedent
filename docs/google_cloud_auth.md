# Gemini authentication: Vertex AI + ADC

Gemini is accessed through Vertex AI using Application Default Credentials (ADC).
A Gemini API key is not required or used. Organization policies blocking API keys
remain in place. Google documents [ADC discovery](https://cloud.google.com/docs/authentication/application-default-credentials)
and the [Google Gen AI SDK](https://googleapis.github.io/python-genai/).

## Repository findings and migration

This is a Python 3.11+ application using uv, FastAPI, Jinja, Typer, Google ADK and
Playwright MCP. Node/npm installs only the pinned browser MCP server; there is no
JavaScript Gemini integration. The installed SDKs are google-adk 2.11.0,
google-genai 2.28.0 and google-auth 2.60.0. There is no obsolete
`google-generativeai` dependency. No Dockerfile, Compose, CI workflow, Terraform
or deployment manifest exists in this repository.

Previously, `cli.py` loaded `.env` with python-dotenv. The console passed its
inherited environment to worker subprocesses. `runner.make_model` constructed
`genai.Client` without explicit authentication settings, so the SDK discovered a
model key from the environment. The most recent configuration selected Vertex AI
API-key mode; before that it selected the Developer API. Goal preparation, the
action agent and every fallback used this one factory. The earlier key was stored
only in ignored `.env`, documented in `.env.example` and setup documentation;
there were no separate key checks, UI settings, Docker/CI injections or unrelated
Google API integrations to migrate. OpenAI/Anthropic example settings and the
scenario token are unrelated and preserved.

Current flow:

```text
Application / Google ADK
  → runner.make_model
  → VertexSettings (project + location)
  → google.auth.default (ADC + cloud-platform scope + configured quota project)
  → Google Gen AI SDK (vertexai=True, explicit credentials/project/location)
  → Vertex AI API
  → Gemini
```

Explicit ADC credentials prevent the installed SDK from selecting an ambient
model key. The factory does not remove or change global environment variables,
so unrelated applications are unaffected. There is no authentication fallback
to the Developer API or API-key mode, and the app never launches `gcloud auth`.
ADC discovery errors include actionable setup instructions and retain the
original cause. Inference errors from Google remain visible.

Changes are limited to `config.py`, the shared model factory, a small explicit
CLI smoke command, focused tests, dependency metadata, ignore rules and docs.
`google-auth` is now a direct dependency because the app imports it. The lockfile
retains all existing package versions. The local `.env` was given the user's
chosen project and `global`; its obsolete Gemini key and mode flag were removed,
while unrelated secrets and model selections were preserved. `.env` is ignored.

Prompts, structured goal schemas, tool/function calling, model names, temperature
for production calls, history, concurrency, token/time/step budgets, retry
settings and fallback order are unchanged. The existing two-attempt HTTP retry
with 2-second initial / 10-second maximum delay and model timeout remain intact.
The new smoke command's output limit and temperature apply only to its tiny test.

## Local Mac development

Install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install), then:

```sh
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable aiplatform.googleapis.com --project=YOUR_PROJECT_ID
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

`gcloud auth login` authenticates CLI operations. The application uses the
separate ADC login. These are developer setup commands, never application startup
commands. API enablement is performed once by an authorized administrator.

Configure `.env` or exported environment variables:

```sh
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=global
```

These are the only Cloud configuration variables required by the app.
`GOOGLE_GENAI_USE_VERTEXAI` is redundant: the factory explicitly sets Vertex mode.
No credential-file setting is needed for normal local ADC login. Exported values
retain precedence over `.env`, following the existing python-dotenv behavior.

After normal `make setup` installation, verify:

```sh
uv run precedent check-model
```

Expected final line: `Vertex ADC works`. This is a single small real inference
through the same ADK model factory used by the worker. It has a 60-second overall
limit, no company access and no browser work. It exits 1 if setup/authentication
or inference fails and retains Google's error details. To test another already
configured model explicitly: `uv run precedent check-model --model MODEL_ID`.

Normal workspace startup remains:

```sh
uv run precedent apps --seed 7 --port 8101
PRECEDENT_APPS_URL=http://localhost:8101 uv run precedent console --port 8000
```

Restart the console after changing `.env` so subsequent workers inherit current
settings. No company data needs to be regenerated for authentication changes.

## Google Cloud project and permissions

The chosen project must have billing enabled and `aiplatform.googleapis.com`
enabled. The runtime identity needs Gemini inference permission
`aiplatform.endpoints.predict`, normally supplied by `roles/aiplatform.user`.
See [Google's role reference](https://cloud.google.com/iam/docs/roles-permissions/aiplatform).
A custom role restricted to the application's required inference permission is
also possible; Owner and Editor are not needed.

The factory binds quota to the configured project. The identity therefore also
needs `serviceusage.services.use`, normally granted through
`roles/serviceusage.serviceUsageConsumer`; this may already be included in its
existing role grants. See [quota-project permissions](https://cloud.google.com/docs/quotas/set-quota-project).
API enablement needs `serviceusage.services.enable`, an administrator permission
that is not required by the inference runtime. No IAM or organization policy
changes were made by this migration.

Once CLI authentication exists, a read-only API status check is:

```sh
gcloud services list --enabled --project=YOUR_PROJECT_ID \
  --filter='config.name:aiplatform.googleapis.com' \
  --format='value(config.name)'
```

Expected: `aiplatform.googleapis.com`. The application smoke test additionally
checks whether the selected identity can perform inference; API status alone
cannot prove that permission.

## Model compatibility

Google's [model endpoint table](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/locations)
lists the following identifiers at the `global` endpoint:

| Use | Existing ID | Vertex ID | Change |
|---|---|---|---|
| Primary and goal model | `gemini-3.8-flash` | `gemini-3.8-flash` | None |
| First local fallback | `gemini-3.7-flash` | `gemini-3.7-flash` | None |
| Second local fallback | `gemini-3.6-flash` | `gemini-3.6-flash` | None |
| Additional example fallback | `gemini-3-flash-preview` | `gemini-3-flash-preview` | None |

The commented `gemini-3.1-pro-preview` example is also listed. No model upgrade or
downgrade was made. Other locations are accepted when explicitly configured,
but the chosen model must support them. Global is an endpoint selection, not a
guarantee of data residency; deployments with residency requirements should
choose a supported location under their own policy. Project access and quota
must still be confirmed by inference after ADC setup.

## Environment support

**Google Cloud production:** Cloud Run/GCE should use an attached service account;
GKE should use Workload Identity Federation for GKE. Give that effective runtime
identity the inference and quota permissions on the configured project. ADC
discovers the platform identity automatically. Do not ship developer ADC files
or create service-account private keys. For non-Google environments, use
Workload Identity Federation with a short-lived identity configuration.

**Local Docker:** no Docker image is currently defined. If one is added, keep ADC
out of the build context and image. For local testing only, mount the developer's
ADC file read-only at runtime, for example (adapt the image/command to its setup):

```sh
docker run --rm \
  --env GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID \
  --env GOOGLE_CLOUD_LOCATION=global \
  --env GOOGLE_APPLICATION_CREDENTIALS=/var/run/google/adc.json \
  --mount "type=bind,src=${HOME}/.config/gcloud/application_default_credentials.json,dst=/var/run/google/adc.json,readonly" \
  YOUR_PRECEDENT_IMAGE uv run precedent check-model
```

This mounts local user ADC, not a service-account private key, and is not the
production authentication method. The repository's ignore rules now cover common
ADC/federation credential filenames and private environment files. Any future
Docker build should exclude those files in its build context as well.

**CI/CD:** no pipeline exists to change. Offline tests use mocks and need no Cloud
secrets. A future real-inference job should obtain short-lived credentials through
OIDC + Workload Identity Federation, with permissions limited to its test project.
Google documents [deployment-pipeline federation](https://cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines).
Federation credential configuration files generated by the runner are ignored;
no long-lived credential secret is needed. Creating the federation trust and
impersonation grant is administrator setup, not application behavior.

## Validation — 8 October 2026

- `uv lock` and `uv sync --locked`: passed; all dependency versions retained.
  An initial offline resolution could not find registry metadata in the cache;
  normal resolution completed successfully.
- `make test`: **142 passed**, including nine focused ADC tests and the existing
  actual ADK/MCP browser tests with a scripted model. No tests call a real model.
- `make lint`: passed. Existing ADK experimental/deprecation warnings remain.
- The installed SDK transport test proves Vertex mode, the explicit project/
  location and credentials, no effective API key or `x-goog-api-key` header,
  and immunity to stale Developer-mode/key environment settings.
- Initial `uv run precedent check-model`: exited 1 with the expected actionable
  `DefaultCredentialsError` before local ADC was configured.
- Google Cloud CLI **588.0.0** was subsequently installed from Google's
  SHA-256-verified ARM64 archive at `~/google-cloud-sdk`. New login/interactive
  shells resolve `gcloud`; it uses the existing Python 3.12 installation.
- The developer completed both CLI sign-in and the separate ADC consent flow.
  ADC is stored by Google Cloud CLI outside the repository, with quota project
  `<your-project-id>`. No service-account private key was created.
- Live `uv run precedent check-model`: **passed (exit 0)**, returning exactly
  `Vertex ADC works` from `gemini-3.8-flash`, project
  `<your-project-id>`, location `global`, through the production ADK
  model factory and ADC. This verifies a real inference, not sustained capacity
  or completion of a full workspace task.
- Read-only Cloud checks confirmed billing enabled and
  `aiplatform.googleapis.com` already enabled. The signed-in identity already
  had project access; no IAM roles, billing settings or organization policies
  were changed.
- The second repository search finds no Gemini key loading or injection in
  application source. Remaining literal key names occur in negative regression
  tests, historical notes or this audit explanation, not the runtime auth path.
  OpenAI/Anthropic example keys and the app's scenario token are unrelated.
- Secret-pattern checks found no credential-shaped literals in tracked files.
  No credentials, ADC tokens or private keys were copied into, staged or
  committed to the repository. The existing `.env` remains ignored.

The earlier successful API-key run in `cloud_key_validation.md` is historical.
The live check above independently verifies the migrated ADC path end to end.

A subsequent [full live workspace task](vertex_adc_e2e_validation.md) also ran
through ADC without model/authentication errors, but failed to complete invoice
entry before its token limit. Authentication success is separate from task success.
