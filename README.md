# Epicor Kinetic MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io/) server that lets AI agents on the
MSPbots Agent Platform read Epicor Kinetic (ERP) data. Epicor Kinetic publishes no single public
API specification -- each tenant's own instance hosts its own Help/API docs behind that tenant's
login -- so this server is a thin, stateless proxy to
[CData Connect AI](https://docs.cloud.cdata.com/en/API/MCP), which turns a tenant's existing Epicor
Kinetic connection into a generic, queryable SQL surface. All of the Epicor-specific login and data
model translation happens inside the tenant's own CData Connect AI account; this server holds no
Epicor-specific logic of its own.

It runs as a stateless HTTP service behind the MSPbots MCP gateway. The gateway sends each tenant's
CData Connect AI credentials as request headers on every call; the server keeps nothing between
requests.

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Credentials (request headers)

| Header | Required | Meaning | Where to get it |
|---|---|---|---|
| `X-Epicor-Email` | Yes | The email address used to sign in to your organization's CData Connect AI account | Your CData Connect AI account |
| `X-Epicor-Pat` | Yes | Personal Access Token generated on CData Connect AI's Personal Access Tokens page | CData Connect AI → Settings → Personal Access Tokens |
| `X-Epicor-Base-Url` | No | Override for CData Connect AI's MCP endpoint; default `https://mcp.cloud.cdata.com/mcp` | — (only needed for a non-default CData deployment) |

Requests are authenticated upstream with HTTP Basic `<email>:<PAT>`, matching CData Connect AI's own
documented auth model. Header names are case-insensitive. A request to `/mcp` missing
`X-Epicor-Email` or `X-Epicor-Pat` gets `401` with the list of missing headers before any upstream
call is made.

This connector does not provision or configure your CData Connect AI account or its Epicor Kinetic
connection -- that is set up directly with CData, the same way any CData-backed data source is
added to a Connect AI account. If that connection is missing or misconfigured, CData returns a
technically valid but empty response; this connector cannot tell that apart from "this tenant
genuinely has no tables," since it has no independent knowledge of what Epicor Kinetic should
contain.

## Tools

7 tools, all read-only (v1 does not write to Epicor Kinetic -- see "Why read-only" below):

| Tool | Proxies (CData tool) | Notes |
|---|---|---|
| `epicor_search_context(question)` | `search_context` | Natural-language dataset/field discovery |
| `epicor_list_catalogs()` | `getCatalogs` | |
| `epicor_list_schemas(catalog?)` | `getSchemas` | |
| `epicor_list_tables(catalog?, schema?)` | `getTables` | |
| `epicor_list_columns(table)` | `getColumns` | |
| `epicor_query_data(sql, limit?)` | `queryData` | `SELECT`-only (CData rejects anything else); `limit` default 50, hard max 200; responses over 20,000 characters are additionally truncated with `has_more` |
| `epicor_get_started()` | `getStarted` + `getInstructions` (combined) | Onboarding + connector-specific guidance |

Behaviour notes:

- Every tool returns a JSON string. Errors use one envelope:
  `{"error": {"code": "...", "message": "...", "retryable": false}}` with `code` one of
  `unauthorized`, `invalid_argument`, `rate_limited`, `upstream_error`.
- `epicor_query_data` returns `{"rows", "count", "limit", "has_more"}`; rows come back from CData as
  CSV and are converted to JSON objects keyed by column name.
- Discovery tools (`epicor_list_catalogs`/`schemas`/`tables`/`columns`) return
  `{"items": [{"name", "type"?, "parent"?}], "count"}`, trimmed from CData's own metadata response.
- Transient failures (`429`, `5xx`, timeouts) are retried with backoff, honouring `Retry-After`. One
  tool call stays under 100 seconds.

### Why read-only

v1 does not expose CData's `execute_insert`, `execute_update`, or `executeProcedure` tools. The
ticket this connector was built for did not name a specific write use case, and Epicor Kinetic
stored procedures in particular can post real financial/production transactions on multi-tenant
production ERP data -- not something to expose without an explicit, reviewed business need. If a
concrete write use case exists, it should be scoped and reviewed as its own change (new tools, new
tests, and its own destructive-tool review), not added silently to this read-only surface.

## Run locally

```bash
uv sync
uv run epicor-kinetic-mcp            # listens on 0.0.0.0:8080
curl -s http://127.0.0.1:8080/health
curl -s http://127.0.0.1:8080/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H 'X-Epicor-Email: you@example.com' -H 'X-Epicor-Pat: YOUR_PERSONAL_ACCESS_TOKEN' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Environment variables (all optional): `MCP_HTTP_HOST` (default `0.0.0.0`), `MCP_HTTP_PORT` (default
`8080`). Unknown variables are ignored. Credentials are never read from the environment.

## Docker

```bash
docker build -t epicor-kinetic-mcp .
docker run --rm -p 8080:8080 epicor-kinetic-mcp
```

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

Code is in `src/epicor_kinetic_mcp/` (one module per tool group under `tools/`), tests in `tests/`.
The implementation follows CData Connect AI's public MCP API documentation at
https://docs.cloud.cdata.com/en/API/MCP; the exact response shape of its discovery tools
(`getCatalogs`/`getSchemas`/`getTables`/`getColumns`) is not shown on that page, so
`tools/discovery.py` parses it defensively (see the comment at the top of that file) -- this is the
main thing to confirm once a real CData Connect AI + Epicor Kinetic account is available.

## License

Copyright 2026 MSPbots.ai. Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE)
and [NOTICE](NOTICE).

Epicor and Epicor Kinetic are trademarks of their owner; CData and CData Connect AI are trademarks
of their owner. This project is not affiliated with or endorsed by either.
