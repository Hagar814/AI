# ERP AI

An AI chat assistant embedded directly in **ERPNext / Frappe**, backed by **Claude** or **Gemini**. It lets users query, analyze, and manage ERP records in natural language (English and Arabic), while every action still passes through Frappe's normal permission system.

> Internal app name: `erp_ai` · Repository name: `AI` · Publisher: Shift

## Features

- **In-desk chat UI** — a bundled chat widget (`erp_ai.bundle.js/css`) served at a dedicated page, with conversation history stored per user.
- **Pluggable AI provider** — switch between **Claude** (via the official `anthropic` SDK) and **Gemini** from a single `AI Settings` doctype. No code changes needed to swap providers, models, temperature, or token limits.
- **Tool-calling over real ERP data** — the model can call registered tools to:
  - list/get/create/update/submit/cancel/delete documents (`documents.py`)
  - run aggregate analytics — counts, sums, averages, group-by breakdowns (`analytics.py`)
  - create saved Reports, Dashboard Charts, Number Cards, and Dashboards (`reports.py`)
  - check connectivity and the current user's roles (`system.py`)
- **Permission-safe by design** — the AI is treated as an *untrusted caller* acting on behalf of the logged-in user. Every tool validates doctype/field names against real metadata and calls `frappe.get_list()` / `frappe.has_permission()` so ERPNext's role, owner, and user-permission rules apply exactly as they would in the desk UI. No tool builds SQL from raw model-supplied strings.
- **Explicit confirmation for write actions** — before creating a Report or Dashboard, the assistant proposes what it's about to do and waits for a yes/no reply (in either language) before touching the database.
- **Bilingual** — auto-detects English vs. Arabic from the user's message and replies, including error messages, in kind.
- **File-aware chat** — users can attach a file; its content is inlined into the prompt alongside their question.
- **Conversation persistence** — every exchange is saved to `AI Conversation` / `AI Message` doctypes so users can revisit, rename, or delete past chats.

## Prerequisites

- A working [Frappe Bench](https://docs.frappe.io/framework/user/en/installation) with Frappe Framework v15
- Python ≥ 3.10
- An API key for whichever provider you plan to use:
  - **Claude**: an Anthropic API key (the app pins to `claude-sonnet-5` by default)
  - **Gemini**: a Google AI Studio / Gemini API key

## Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app erp_ai https://github.com/Hagar814/AI.git --branch develop
bench --site <your-site-name> install-app erp_ai
bench build --app erp_ai
bench restart
```

## Configuration

All configuration lives in the single doctype **AI Settings** (Desk → AI Settings):

| Field | Purpose |
|---|---|
| `enabled` | Master on/off switch — the assistant refuses to run when unchecked |
| `provider` | `Claude` or `Gemini` |
| `model` | Model name; defaults to `claude-sonnet-5` if left blank or invalid for Claude |
| `api_key` | Provider API key (stored as a Password field, never exposed to the client) |
| `temperature` / `max_tokens` | Standard generation parameters |
| `max_context_messages` | How much conversation history to keep in context (trimmed server-side) |
| `system_prompt` | Optional extra instructions appended for your organization |

Set `enabled` and supply an `api_key` before the chat widget will respond.

## How it works

```
Chat UI → erp_ai.api.ask() → erp_ai.ai.service.ask_ai()
                                     │
                     ┌───────────────┴───────────────┐
                 providers/claude.py            providers/gemini.py
                     │                                │
                     └──────────── executor.py ────────┘
                                     │
                          registry.py (tool lookup)
                                     │
                     tools/{documents,analytics,reports,system}.py
                                     │
                          tools/_security.py (validation +
                          frappe.has_permission enforcement)
```

- `erp_ai/api.py` exposes the whitelisted endpoints the chat UI calls (`ask`, `save_conversation`, `get_user_conversations`, `load_conversation`, `delete_conversation`), plus a lightweight intent classifier that detects explicit "create a report/dashboard" requests and routes them through a confirm-then-execute flow instead of calling straight through to the general-purpose assistant.
- `ai/service.py` dispatches to the configured provider.
- `ai/executor.py` is the single tool-dispatch entry point shared by both providers — it normalizes arguments, calls the registered tool function, and turns any exception into a clean `{"error": ...}` payload the model can read back to the user instead of a raw traceback.
- `ai/tools/_security.py` is the shared guardrail layer: every tool validates the doctype exists, validates every field/filter/order-by key against that doctype's real metadata, and calls `frappe.has_permission()` before touching data.

## Doctypes

| Doctype | Type | Purpose |
|---|---|---|
| `AI Settings` | Single | Provider, model, API key, and behavior configuration |
| `AI Conversation` | Regular | One record per chat thread (title, user, status, full message log as JSON) |
| `AI Message` | Regular | Individual message records (role, content, token count, timestamp) |

## Testing

CI (`.github/workflows/ci.yml`) spins up MariaDB + Redis, installs the app via `bench`, and runs:

```bash
bench --site <your-site-name> set-config allow_tests true
bench --site <your-site-name> run-tests --app erp_ai
```

A separate **Linters** workflow runs on every pull request:
- `pre-commit` (ruff lint + format, import sorting, prettier, eslint, plus standard hygiene hooks)
- [Frappe Semgrep Rules](https://github.com/frappe/semgrep-rules) for Frappe-specific static analysis
- `pip-audit` for known-vulnerable dependency checks

## Contributing

```bash
cd apps/erp_ai
pre-commit install
```

Pre-commit will then run ruff, eslint, prettier, and pyupgrade automatically on each commit. Open pull requests against `develop`.

## Security Notes

- Keep `AI Settings.api_key` set only via the doctype's Password field (or `site_config.json` if you prefer environment-level secrets) — never hardcode a provider API key in source.
- Because the assistant can create documents, reports, and dashboards on a user's behalf, `ignore_permissions=True` is used only for the app's own bookkeeping records (`AI Conversation`/`AI Message`, and the report/dashboard the user just explicitly confirmed) — data tools (`list_documents`, `create_document`, etc.) go through `frappe.has_permission()` and will refuse to bypass a user's actual ERPNext role restrictions.
- If you add new tools, follow the pattern in `tools/_security.py`: never use `frappe.db.sql()` with interpolated strings, never use `frappe.get_all()` (it skips permission checks), and validate every identifier against real DocType metadata before it reaches a query.

## License

MIT — see [license.txt](license.txt).


### License

mit
