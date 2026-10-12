# Run Precedent locally

The public [README](../README.md) contains inline recordings and screenshots; no setup is needed to view them.
Running the autonomous worker on your own machine requires model access and the dependencies
below. The planned hosted worker is a separate deployment milestone; it is not available from the README.

## Requirements

- Python 3.11 or later, [uv](https://docs.astral.sh/uv/getting-started/installation/),
  Node 18 or later, npm and make.
- A Google Cloud project with billing, Vertex AI enabled and inference permissions.
- Chromium installed by setup. Native Google-site execution additionally uses macOS Chrome
  and an owner-signed-in profile. The generated-company demo does not require that profile.

```sh
git clone https://github.com/IC-04/precedent.git
cd precedent
make setup
```

`make setup` installs locked Python/Node dependencies and Chromium, creates `.env` if absent,
and replaces the default scenario token. Keep `.env` and credential files private.

## Model access

Install the Google Cloud CLI and authenticate:

```sh
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable aiplatform.googleapis.com --project=YOUR_PROJECT_ID
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

Set `GOOGLE_CLOUD_PROJECT` in `.env` and retain the configured global location/model defaults.
The runtime identity needs Vertex inference access and permission to use the project for
quota/billing; it does not need Owner. Then check with one small inference:

```sh
uv run precedent check-model
```

The expected message is `Vertex ADC works`. This does not access company records.
See [the authentication guide](google_cloud_auth.md) for IAM and workload authentication.

## Fresh company and visible execution

This command creates an isolated generated company without touching existing demo worlds:

```sh
uv run python scripts/demo.py --port 8000 --apps-port 8100
```

Open `http://localhost:8000/`. Choose an invoice or meeting task and assign it to Ava.
Bring the Chromium window forward to see the same browser Playwright controls. In this local
mode it uses real keystrokes and a separate Ava action cursor. `/guide`, `/mind` and `/teach`
provide the introduction, scoped learning and demonstration workflow. Company apps run at
`http://localhost:8100/`, including Mail, Drive, Books, Chat and Calendar.

Try: **“Enter the latest Figma invoice and route it for approval.”** The task requires Ava to
find the current invoice, infer applicable company rules, save the bill, request approval and
check the resulting state. Next try the meeting-preparation preset. The generated company has
its own displayed clock; “next week” follows that clock.

For a company you want to retain, give the first run a new world path:

```sh
uv run python scripts/demo.py --port 8000 --apps-port 8100 --world-root worlds/my-demo
```

After stopping, restart the same path with `--reuse`. Do not regenerate it: generation creates
a different company instance and intentionally changes the memory scope. Choose unused ports
if other servers are running.

## Independent review and learning

Run details show actions, cited decisions, checks, receipts and the Tribunal. Gemini powers
the worker; optional Bedrock jurors add a second model family. Configure the documented
Bedrock variables in `.env` and check with `uv run precedent check-bedrock`. Without that
configuration, a multi-family jury is not available; do not treat it as a passed jury.

For an exact/audit-only hearing on a retained run:

```sh
uv run precedent tribunal --run RUN_ID --no-jury
```

Company and run identity must match. The UI must have enough retained evidence for the requested
checks; missing proof remains unknown. Curated memory lives separately from company data.
Skill candidates require a real sandbox validation and explicit activation before reuse.

## Native Gmail and Calendar

This local prototype path is optional. Use a nonconfidential demonstration account/thread and
inspect [native guards](../src/precedent/worker/native.py) before enabling it.

1. Run `uv run precedent connected` and complete the configured Web OAuth consent flow for
   fresh read-only proof. Developer OAuth client setup is documented in the
   [Google milestone report](google_connected_worker_milestone.md).
2. Sign into the **same account** by hand in Ava's dedicated Chrome profile, then quit Chrome:

   ```sh
   open -na "Google Chrome" --args --user-data-dir="$HOME/.local/share/precedent/ava-chrome" --profile-directory=Default --no-first-run "https://accounts.google.com/ServiceLogin?continue=https://mail.google.com/mail/"
   ```

3. Start a fresh native demo:

   ```sh
   PRECEDENT_NATIVE_GOOGLE=1 uv run python scripts/demo.py --port 8041 --apps-port 8141 --world-root worlds/native-demo
   ```

   Use `--reuse` on later starts. Request an unsent briefing draft to an address you name and,
   if desired, an explicit owner-only Calendar hold. Sending, inviting, deleting and changing
   unrelated company records are refused. Never copy a signed-in browser profile to a public
   deployment. The OAuth/provider-backed connected worker is a distinct path; its pending
   acceptance is documented separately.

## Checks and troubleshooting

`make test` and `make lint` run the project checks. A `503` on the task home usually means the
matching company service is unavailable. Occupied ports require another console/apps pair.
Expired ADC requires reauthorization; model availability/quota can fail even when credentials
are valid. Preparation and execution are bounded and should surface the error. Stop the demo
process normally to close its managed services.

Local execution uses your cloud billing. A future hosted worker will use operator-funded
credentials, with no visitor API keys. Recorded demo playback incurs no model usage.

