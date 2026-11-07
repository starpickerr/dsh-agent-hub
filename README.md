# dsh-agent-hub

A collection of Python business plugins for a compatible plugin host. This repository contains the existing plugin packages and their catalog, including an Agent Hub package for configured external-agent collaboration. It is not a standalone desktop application or an independently runnable DSH native plugin bundle; the host supplies the plugin runtime, service interfaces, permissions and process management.

| Package | Service contract | Purpose |
| --- | --- | --- |
| `plugins/agent-hub` | `stella.agent-hub@1` | Submit tasks to configured external agents, inspect progress and request cancellation |
| `plugins/bills` | `stella.bills@1` | Income and expense records and summaries |
| `plugins/calendar` | `stella.calendar@1` | Events, categories and recurring schedules |
| `plugins/tasks` | `stella.tasks@1` | Tasks, subtasks and completion status |
| `plugins/briefing` | `stella.briefing@1` | Briefing rules, snapshots and sources supplied by the host |
| `plugins/automation` | `stella.automation@1` | Scheduled rules and reminders; dispatch is supplied by the host |
| `plugins/knowledge` | `stella.knowledge@1` | Knowledge documents |
| `plugins/memory` | `stella.memory@1` | Long-term memory |

The `stella.*` identifiers are existing compatibility contracts, not installation package names. Each package's `plugin.json` is the authority for its runtime, host API version, permissions, service contributions and description. For example, `agent-hub` declares Python ABI `cp312` and host API `^1.0.0`. Installing a package does not configure external agents or grant access to their resources.

## Installation and use

Obtain this repository and use a host that implements the manifest and catalog contracts. `catalog/official.json` lists the packages, versions and SHA256 digests; its paths are relative to the catalog file. Follow that host's catalog installation and permission configuration instructions, then configure the desired package and its connections in the host. This repository does not include a host or a general-purpose command for launching these plugins by themselves. Do not install it as a DSH native bundle without a verified compatible distribution.

## Maintaining packages

Each `plugin.json` owns its public `description`; an optional package README can provide details. After a metadata or package change, update the package version and its catalog version and digest together. `catalog/release.example.json` is a release-catalog template. `scripts/build_release_catalog.py` builds ZIPs under `dist/signed/` and writes `catalog/release.json`; it requires `STELLA_PLUGIN_SIGNING_SECRET`. Keep signing secrets and machine-specific absolute paths out of Git.

Tests are in `tests/`. Some integration tests require the compatible host source and dependencies; passing package-only checks does not verify installation in a desktop client.
