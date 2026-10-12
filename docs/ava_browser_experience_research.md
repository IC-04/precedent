# Ava in the task tab: architecture and industry survey

Research date: 8 October 2026. This is an analysis of the current checkout,
existing run evidence and primary industry sources. No worker/UI behavior was
changed and no paid model run was started for this research.

Implementation update later on 8 October: the requested two-tab experience now
has a dedicated live-only viewer at `/runs/{run_id}/workspace`, reached from
`/watch`. The console proxies the actual managed browser stream through
`/runs/{run_id}/screen`. It reconnects on interruptions without falling back to
saved captures. A real Chromium/MCP test verified changing frames between tool
calls and browser cleanup; an in-app browser check received 589 frames and
visibly rendered motion. These checks used a clearly labelled local animation
fixture, without model calls or company writes. Nine focused tests passed.
The lifecycle and recommendations below describe the earlier research snapshot;
the stream route, dedicated labels and model-free streaming validation listed
as remaining work have now been implemented. Interactive takeover and general
multi-tab selection remain outside this change.

Subsequent clarification: the user wants to watch the actual native browser,
not an image transport. `console --headed` now forwards the existing worker
flag and opens the very Chromium session MCP controls. The local console on
8002 has this enabled. Native-window inspection verified the company workspace
and browser toolbar after MCP navigation, without model calls or writes;
17 console tests passed. This is a desktop window (Google Chrome for Testing
on this Mac), not an embedded native browser tab in Codex. The image viewer
remains available for remote observation but does not satisfy this clarified
request.

## Conclusion

Yes: the user can assign a task and watch Ava work continuously inside that same
browser tab. The strongest fit for this project is an embedded live view of the
actual browser Ava controls. A separate browser process underneath does not
require a separate window or tab in the demo.

Literal automation of the user's own tab is a different option. Playwright MCP
supports existing Chrome/Edge tabs through its extension; CDP can attach to an
existing Chromium browser. This needs browser integration and a design that
keeps task controls available when Ava navigates. An ordinary web page cannot
grant itself control of an arbitrary browser tab.

## Current implementation and lifecycle

The checkout contains newer code than the earlier failed ADC validation run.
It now has `worker/screen.py`, a CDP live stream and console rendering for it.
Three later retained runs contain `screen` startup events and no
`screen_unavailable` or screen-cleanup error events. These establish successful
startup, not a visually verified uninterrupted stream.

1. The console accepts the task, verifies company/seed identity and creates a
   run-specific directory. It starts the worker as a separate process and
   redirects the existing viewer tab to its run page. It does not need to open
   another viewer tab.
2. The worker starts the company gateway, which mediates its company requests
   and writes. With `PRECEDENT_SCREEN` enabled (the default), `AvaBrowser`
   launches Chromium with a temporary profile and remote-debugging endpoint.
   It is headless by default; headed mode opens a visible browser window.
3. Playwright MCP attaches to that exact browser through `--cdp-endpoint`.
   A separate observer also attaches and uses CDP `Page.startScreencast` to
   obtain JPEG frames. Those frames are served as a local MJPEG stream.
4. The task page displays the stream inside its browser area using an image
   element. Ava's clicks, forms, navigation and unsaved state are therefore in
   the displayed session. Model perception remains accessibility snapshots;
   the stream is for people. Captions come from real tool calls and an overlay
   responds to browser pointer/focus events.
5. Goal/context preparation precedes agent actions. Currently the initial
   browser page is `about:blank`, so starting the stream does not mean work has
   started. The UI should show the real preparation state and then transition
   to the actual company page.
6. On completion/error, the runner closes the MCP tools, stream observer/server,
   browser process and gateway, and removes the temporary profile. The final
   event clears the live URL. Saved captures and events remain for replay.
   Closing the viewer tab is separate from stopping the worker; console
   shutdown terminates managed worker process groups.

If screen startup fails, the worker falls back to MCP's isolated browser and
discrete captures. If the image stream fails, the frontend falls back to saved
captures. Neither fallback should be represented as continuous live viewing.

Core references in this repository:

- `console/server.py`: `RunManager.start` and `RunManager.close`.
- `worker/runner.py`: `browser_toolset`, `_open_screen`, `_act`, `_close`.
- `worker/screen.py`: `AvaBrowser` and `Screen`.
- `console/state.py`: reconstruction of `screen` events and run completion.
- `apps/static/console.js`: live-image rendering, failure fallback and replay.

## Industry survey

| Product / technology | Documented approach | Relevance |
|---|---|---|
| [Browserbase live view](https://docs.browserbase.com/platform/browser/observability/session-live-view) | Embeds a live browser session in an iframe, with viewing and interaction examples; supports individual browser-page views. | A separate browser session can appear as part of one application page. |
| [Browser Use live preview](https://docs.browser-use.com/cloud/browser/live-preview) | A browser-ready event supplies a live URL which the app embeds; supports viewing restrictions and takeover through the viewer. | Request, browser readiness and browser viewing belong in one continuous workflow. |
| [AWS AgentCore Live View](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-dcv-integration.html) | A dedicated browser session streams through DCV into an application component using a signed URL. | Automation and the human viewing channel can be separate while showing the same session. |
| [Microsoft Magentic-UI, original research prototype](https://www.microsoft.com/en-us/research/blog/magentic-ui-an-experimental-human-centered-web-agent/) | A sandboxed browser is exposed through the collaborative UI; users can pause and take control. | The embedded browser is the work surface, with task/control information alongside it. The current upstream main branch has since evolved into MagenticLite. |
| [Playwright MCP](https://github.com/microsoft/playwright-mcp) | Supports isolated browsers, CDP attachment and an extension for existing Chrome/Edge tabs. The installed 0.0.83 CLI also exposes both attachment options. | Literal existing-tab automation is technically available, but differs from embedded viewing. |

These examples support the architectural recommendation; they do not establish
Precedent's task reliability or justify replacing Google ADK/Playwright MCP.

## Options for Precedent

| Option | Feasibility | Tradeoff |
|---|---|---|
| Actual browser streamed into the task page | Already partly implemented; recommended | Keeps task/evidence visible and preserves the worker gateway; current stream is view-only. |
| Ava controls the user's selected browser tab | Possible through extension or a managed CDP browser | Requires setup, explicit tab/session ownership and preserving task controls during navigation. Human and agent input need coordination. |
| A company application embedded as a DOM iframe and automated inside the user's tab | Possible for these owned apps, with a redesigned shell and frame-aware automation | A normal iframe alone creates another page/session and does not mirror Ava. Requires routing, frame targeting and controller changes. |

[Playwright documents](https://playwright.dev/docs/api/class-browsertype#browser-type-connect-over-cdp)
that CDP attachment supports Chromium and has lower fidelity than its native
protocol. [Chrome's debugging policy](https://developer.chrome.com/blog/remote-debugging-port?hl=en)
also requires a non-default data directory for debugging from Chrome 136.
[Browser same-origin rules](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Same-origin_policy)
limit ordinary page scripts; loading an app in an iframe does not give the
console unrestricted control over other browser tabs or origins.

## Recommended demo experience and remaining work

Keep one stable task tab: task entry transitions to a large live browser area,
with preparation/current-action status and compact evidence beside it. Display
the actual company starting page while preparation runs; show real actions only
after they occur. Keep the same view through reading, typing, saving, approval
routing and final outcome. On finish, clearly switch to recorded evidence.

Build on the existing live-view implementation rather than changing agent
frameworks or buying a hosted browser service just for the demo. It still needs:

- A run-specific stream route through the console. The current direct
  `127.0.0.1:<random-port>` URL assumes viewer and worker are on the same
  machine and is not a hosted-demo transport.
- Verified frame freshness, disconnect/reconnect behavior, navigation and
  alignment with the precise page MCP is controlling. The current observer
  follows the newest page, which is not a general active-tab guarantee.
- Accurate live-versus-capture labels; the connection text currently still
  refers to discrete captures in parts of the live path.
- A clear input-ownership protocol before implementing interactive takeover.
  The current MJPEG image supports watching only.
- A model-free end-to-end streaming test, followed by a real demo walkthrough.
  Existing screen tests cover captions, frame storage, state transitions and
  shutdown before startup; all four passed here after permitting local port
  binding. They do not verify complete streaming or task execution.

The technical answer is yes. The immediate opportunity is to finish and validate
the already-started same-tab viewing experience, independently of work needed
to make autonomous invoice completion reliable.
