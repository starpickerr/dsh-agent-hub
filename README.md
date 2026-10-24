# Stella-Plugins

First-party business plugins for [Stella](https://github.com/starpickerr/Stella). Core ships the runtime (`core.plugins` + `stella-plugin-runner`); this repository ships the default business packages.

| Plugin | Contract | Notes |
| --- | --- | --- |
| `plugins/bills` | `stella.bills@1` | Ledger, statements, idempotent receipts |
| `plugins/calendar` | `stella.calendar@1` | Events/categories; Apple sync stays in Core |
| `plugins/tasks` | `stella.tasks@1` | Todos/reminders; host reconciles scheduler links |
| `plugins/briefing` | `stella.briefing@1` | Rules, snapshots, outbox; sources via Core directory |
| `plugins/automation` | `stella.automation@1` | Rules/mutations; Core keeps lease/dispatch |

Packages must not import Stella `agent.*`.

Each plugin owns its public introduction in `plugin.json` under `description` (a string or a `{"zh": "…", "en": "…"}` object). Core reads the installed manifest; an optional package `README.md` supplies the detailed overview. Keep these descriptions with the plugin rather than duplicating business copy in Core. Metadata changes advance the package patch version and require refreshing `catalog/official.json` versions and SHA256 digests; installed older packages obtain the introduction through the normal update flow.

- `catalog/official.json` — checkout installs; each `path` is relative to the catalog file (for example `../plugins/tasks`).
- `catalog/release.example.json` — template for GitHub Release `url` + `sha256`.
- `scripts/build_release_catalog.py` — builds signed ZIPs under `dist/signed/` and writes local `catalog/release.json` with relative `url`s (requires `STELLA_PLUGIN_SIGNING_SECRET`). Do not commit machine-local absolute paths.

Email and eLearning are independent local MCP servers under the workspace MCP directory; their business code is no longer shipped as Stella plugins.
