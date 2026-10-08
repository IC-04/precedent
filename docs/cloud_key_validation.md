# Billed Cloud-key validation — 8 October 2026

> Historical validation, superseded by the [Vertex AI + ADC migration](google_cloud_auth.md).
> API-key authentication is no longer supported by the application. This report
> preserves evidence of the earlier run; it is not current setup guidance.

The updated key works with the configured `gemini-3.8-flash` through **Vertex AI**. The initial Developer API probe returned 403 `API_KEY_SERVICE_BLOCKED`. The same key was accepted by the Cloud endpoint. `.env` now has `GOOGLE_GENAI_USE_VERTEXAI=true`, and the idle console was restarted to inherit it. Neither the key nor the configured model/fallback list was changed.

Google documents this API-key connection in its [Vertex AI SDK sample](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/samples/googlegenaisdk-vertexai-express-mode). Restart the console after future `.env` changes: its subprocesses otherwise inherit settings loaded when the console started.

## Actual live run

- Run: `20261008-105337-5f6b`; [open replay](http://localhost:8000/runs/20261008-105337-5f6b).
- Task: “Enter the latest Figma invoice and route it for approval.”
- Fresh disposable company: `/tmp/precedent-cloud-validation/7`, served on 8104. The active company and scripted demo company were preserved.
- Goal preparation: **9.63 seconds**.
- **21 actual browser actions and 21 saved browser views**; the worker found the invoice and reviewed company policies.
- Model capacity, quota and authentication errors during the live run: **zero**. One attempted browser navigation outside the allowed origin was blocked, and the worker returned to its workspace.
- Duration: **268.9 seconds**. Logged usage: **319,128 input tokens / 1,829 output tokens**. Monetary cost is unavailable; thinking-token usage is not included in the current output counter.
- This validation was bounded to 60 tool steps, 300,000 counted tokens and 600 seconds. It stopped after 32 tool steps when cumulative counted tokens exceeded the test limit.
- No bill was saved or routed. The worker claimed **unknown**, its fresh-verification receipt remains **unknown**, and the independent Act 1 grade is **fail** because the invoice bill is absent. This run confirms model access and browser execution, not completed invoice processing.

[Machine-readable result](../output/cloud-key-validation/result.json), `runs/20261008-105337-5f6b/events.jsonl`, saved captures, `receipt.md` and independent `grade.json` contain the evidence. No second live run was started after the budget stop.
