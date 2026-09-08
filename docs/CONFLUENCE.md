# Confluence pages

Space `~luhl@sea.com` on https://confluence.garenanow.com. All four pages were
refreshed 2026-09-08 to match the manifest-based onboarding and the two-dashboard
layout.

| Page | ID | Covers |
|---|---|---|
| Build Guide (Zabbix + Grafana) | 270633960 | parent index: full build from scratch, routine ops, troubleshooting |
| Add a New Region (Step-by-Step) | 270650415 | onboarding a region, script by script, with test-alert instructions |
| SeaTalk Alert Setup Guide | 270650478 | the scopes model, adding a destination, verifying delivery |
| Roadmap & Pending Work | 270649652 | what is live, what is left |

## Updating them

The MCP page-update tool fails against this server; the raw REST API works and
keeps the page ID:

```python
# GET  /rest/api/content/<id>?expand=version,space,body.storage
# PUT  /rest/api/content/<id>   with version.number + 1
#      body.storage.representation = "storage", Authorization: Bearer <token>
```

The token lives in the `confluence` MCP server entry in `~/.claude.json` — read
it from there, keep it in memory, never write it to a file.

Gotchas: no 4-byte emoji in page bodies; put code inside the `code` macro with a
CDATA body to avoid escaping; the MCP itself runs in podman, so `-32000` on
connect usually means `podman machine start`.
