# Precedent

An autonomous AI worker that learns how a company operates from its own records, does the company's work in its real applications, and proves what it did.

> Work in progress for the CentrAlign AI engineering take-home. The full README follows `docs/briefs/WS7_submission.md`.

## Quick start

```
make setup            # uv sync, npm ci (Playwright MCP; needs Node 18+), Chromium, .env
make world SEED=7     # generate the Northwind company
make apps SEED=7      # Mail, Books, Drive, Chat on http://localhost:8100
make console          # product screen on http://localhost:8000
```

See `docs/00_kickoff_brief.md` for scope and `docs/01_architecture.md` for the design.
