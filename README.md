# Precedent

An AI accounts-payable workspace: Ava reads company records and operates real applications through Google ADK and Playwright MCP. Company-context induction and fresh worker verification remain work in progress.

> Work in progress for the CentrAlign AI engineering take-home. The full README follows `docs/briefs/WS7_submission.md`.

## Google Cloud authentication

Gemini is accessed through Vertex AI using Application Default Credentials (ADC).
A Gemini API key is not required. Goal preparation, actions and fallbacks all use
the same ADC model factory. The configured model names are unchanged.

Install the [Google Cloud CLI](https://cloud.google.com/sdk/docs/install), then run:

```sh
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable aiplatform.googleapis.com --project=YOUR_PROJECT_ID
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

Set these values in `.env` (or export them in your environment):

```sh
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=global
```

The runtime identity needs Vertex AI inference access, normally `roles/aiplatform.user`,
and permission to use the configured project for quota/billing
(`serviceusage.services.use`, normally `roles/serviceusage.serviceUsageConsumer`).
An administrator can enable the API and grant these permissions; runtime identities
do not need Owner or Editor.

Verify with one small model request:

```sh
uv run precedent check-model
```

Expected response: `Vertex ADC works`. No company records are accessed or changed.
Restart the console after changing `.env`. Production should use an attached
service identity or Workload Identity, rather than a developer's local ADC file.
See the [authentication guide](docs/google_cloud_auth.md) for Docker, CI, model
compatibility, IAM and the migration validation results.

## Open the delivered workspace

With the existing seed-7 company, use two terminals:

```sh
uv run precedent apps --seed 7 --port 8101
```

```sh
PRECEDENT_APPS_URL=http://localhost:8101 uv run precedent console --port 8000
```

Open [the company workspace](http://localhost:8101/) or [Ava's task inbox](http://localhost:8000/).
The console supports one active worker and actual isolated-browser captures. Starting a task
uses the configured model. Context induction, fresh verification and eval orchestration
remain unfinished. The [live ADC workspace validation](docs/vertex_adc_e2e_validation.md)
confirmed model access and browser execution, but the task failed to complete
before its token limit. The scripted replay is labelled separately.

See [the delivery guide](docs/workspace_implementation.md) for exact desktop launch
settings, the labelled scripted replay, before/after screenshots, 133 passing tests,
lint results, the Act 1 walkthrough and remaining limits.

## First installation

```
make setup            # uv sync, npm ci (Playwright MCP; needs Node 18+), Chromium, .env
make world SEED=7     # first generation only; overwrites that world's existing data
make apps SEED=7      # Mail, Books, Drive, Chat on http://localhost:8100
make console          # product screen on http://localhost:8000
```

See `docs/00_kickoff_brief.md` for scope and `docs/01_architecture.md` for the design.
