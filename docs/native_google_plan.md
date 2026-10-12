# Plan: Ava works in native Gmail and Google Calendar

Status: Gmail drafting built and passing live on 2026-10-12 (run 20261011-204107-0722, 7 of 7 checks); Calendar not built yet. See the decisions log.

## The demo we want

> Help me draft a mail thread to the owner's address informing about the latest bill and
> vendor details and summarising the chat messages in #design.

In a visible Chrome window, Ava:
1. opens the company apps (Books, Chat) in one tab and reads the latest bill, its vendor
   record and the #design channel;
2. switches to a second tab, opens **gmail.com**, writes the email and leaves it as a
   **draft** in your real Gmail (not sent);
3. comes back to report, and the result is checked independently.

A second, optional demo uses **calendar.google.com** the same way (an owner-only event,
no guests).

## What exists today, and what is missing

- **Exists:** the Google connected app. You consented through Google's own flow; it holds
  encrypted access to Gmail (read and drafts) and Calendar. Ava operates Precedent's own
  Mail and Calendar pages, which call Google's APIs. She never opens gmail.com.
- **Missing for this demo:**
  1. a browser in which you are signed into Google;
  2. permission for Ava's browser to go beyond the company gateway;
  3. tab switching;
  4. safety rules for a site whose traffic our gateway cannot see;
  5. a task family and verifier for "a draft in native Gmail".

## Design

### 1. Ava's own Google browser profile
- A dedicated, persistent Chrome profile outside the repo
  (`~/.local/share/precedent/ava-chrome`, private to your user).
- You sign into Google in it once, by hand, using a command that opens the profile
  *without* automation. Neither Ava nor I ever see or type your password.
- Each run launches that profile headed with remote debugging, as Ava's browser is
  launched today, and Playwright MCP attaches to it.
- Rejected alternative: driving your everyday Chrome through the Playwright extension.
  It is more convenient, but it exposes all your tabs and signed-in sessions to the agent.

### 2. Two sites, two tabs
- Expose Playwright MCP's `browser_tabs` tool (list, new, select, close) to Ava.
- Tab 1 is the company apps through the gateway (unchanged). Tab 2 is Gmail or Calendar.
- Allowed origins: the gateway, `mail.google.com` and `calendar.google.com`, plus only the
  Google asset hosts these pages need to load (measured in the spike).
- `accounts.google.com` stays blocked, so Ava can never reach sign-in or account
  security pages.

### 3. Safety on a site we do not control
Our gateway gates every company-app save, but Google's traffic does not pass through it.
The rules therefore move to the browser actions, written as code in the guard, as the
existing rules are:
- **No sending, ever.** Clicks on controls named Send, Send now, Schedule send,
  Forward, Delete, Delete forever, Archive, Report spam, Unsubscribe or Move to are refused
  on Google pages. On Calendar, the "Send" button in Google's guest-invitation dialog is
  refused.
- **No shortcuts.** Key presses are limited to Enter, Tab, Escape, arrows and page keys.
  Ctrl/Cmd+Enter (Gmail's send shortcut) and single-letter Gmail shortcuts are refused.
- **Typing only into editable fields** (already enforced by the visible input executor).
- **Decision before writing.** The first keystroke into a compose field needs a recorded
  decision with sources, like every company-app save. One decision permits one draft.
- **Recipient lock.** Before the draft is closed, code reads the To field. Only recipients
  named in your request are allowed; anything else stops the run.
- **Small compose page.** Ava writes in Gmail's full-page compose
  (`mail.google.com/mail/?view=cm&fs=1`). It has far fewer controls than the inbox and keeps
  her page view small: an inbox snapshot runs to tens of thousands of tokens.
- **Detection backstop.** Using the existing read-only Gmail connection, the Sent folder is
  counted before and after the run. Any new sent message fails the run loudly.

### 4. The task: goal and verification
The goal contract for this family states:
- **Must be true:**
  - exactly one new draft, addressed to the owner's address, with a subject;
  - the latest bill's number, vendor, amount, due date and status/approver match Books;
  - the vendor details match the vendor record;
  - the #design summary is grounded in that channel's actual messages.
- **Must not happen:**
  - anything sent;
  - any other recipient;
  - any other mailbox change.

Verification:
- **Ava's own fresh checks:** she rereads Books and Chat through the gateway, and reads the
  draft through the read-only Gmail connection.
- **The Tribunal:** exact checks of the draft text against the Books fields, plus its jury
  on whether the summary is supported by the chat.
- **Receipt:** the run's receipt links to the draft.

### 5. Seeing it
- The headed window shows the tab switches.
- Ava's purple pointer and captions are injected over the debugging connection, so they
  should also appear on Gmail (confirmed in the spike).
- The console run page streams the steps as usual.
- After the run, the draft is opened in your Gmail.

## Order of work

| Step | What | Time |
| --- | --- | --- |
| 0. Spike, go or no-go | Sign-in persists with remote debugging; Gmail and Calendar load under the origin list; compose-page snapshot size; tabs tool; pointer overlay on Gmail | about 1 h |
| 1. Build | Google browser mode and profile command, tabs, origins, action guard, draft decision gate, recipient lock, Sent-count audit, task family goal and verifier; tests against a local Gmail-like page | about 3 h |
| 2. Live run | Your task in your real Gmail, iterate until Ava's checks, the Tribunal and the audit agree | about 1 h |
| 3. Calendar (if time) | Owner-only event on calendar.google.com, verified through the Calendar connection | about 1 h |
| 4. Evidence | Recording, receipt, guide and README entry | about 30 min |

**Main risk:** Google may challenge a profile that is opened with remote debugging. The
spike checks this first. If it fails, the fallback is the Playwright extension in a
separate Chrome profile that you sign into. Same rules, different attachment.

## Decisions needed from the owner
1. A dedicated "Ava" Chrome profile that you sign into once (recommended), or your
   everyday Chrome.
2. Drafts only: Ava can never send. You send it yourself if you want to.
3. The draft will contain the generated company's (synthetic) bill, vendor and chat data.
4. You do the one-time Google sign-in in Ava's profile when the spike starts.
