# PRD-21335 · Code review

## Round 1 · 2026-11-05 · reviewed dev/PRD-21335 @ 084d54f (base main @ 07468bd)

Verdict: approved

### Scope

Diff `07468bd...084d54f` in `MSPbotsAIFramework/epicor-kinetic-mcp` — the entire implementation (new repo, first version): `src/epicor_kinetic_mcp/**`, `tests/**`, `Dockerfile`, `docker-compose.yml`, `pyproject.toml`/`uv.lock`, `README.md`, `docs/tickets/PRD-21335.md` + `.ac.json`.

### Verification performed (commands re-run independently, not re-stated from the [DEV] stub)

- `uv sync --frozen` on this worktree: resolved/installed clean.
- `uv run pytest -q`: **25 passed**, matches the [DEV] stub's claim.
- `uv run ruff check .`: all checks passed. `uv run ruff format --check .`: 17 files already formatted.
- `grep -rnP '[\x{4e00}-\x{9fff}]'` (excluding `.git`/`.venv`): no output — no Chinese text.
- Manual secret scan (`grep` for key/secret/password/token literals outside tests): no hits.
- Live smoke test: started the server locally, `GET /health` → `200 {"status":"ok"}`; `/mcp` `tools/list` with no credential headers → `401`; with placeholder headers → `200` with exactly the 7 `epicor_`-prefixed tools (`epicor_search_context`, `epicor_list_catalogs`, `epicor_list_schemas`, `epicor_list_tables`, `epicor_list_columns`, `epicor_query_data`, `epicor_get_started`), no insert/update/procedure tool present — confirms AC1/TC-EPICOR-001 independently of the dev leg's own run.
- Diffed `README.md`'s "MSPbots Connector" block (lines 16–86) byte-for-byte against `~/.claude/skills/vendor-mcp-development/reference/readme-connector-section.md` — identical, correctly placed before the Header credentials table.

### Findings

1. [suggestion] `docs/tickets/PRD-21335.md:76` — the tech design's `api_client.py` bullet says "a single httpx.AsyncClient is reused for connection pooling since the base url is shared and auth travels per-call, not baked into client state." The actual implementation (`src/epicor_kinetic_mcp/api_client.py:132-149`, `CDataClient.__init__`) constructs a new `httpx.AsyncClient` per tool call with the `Authorization` header baked into that client's default headers, and closes it at the end of the call (`tools/_common.py:43`, `async with CDataClient(creds, settings) as client`) — there is no cross-call client reuse. This is stricter tenant isolation than the design text describes (no shared transport state at all, not just no baked-in auth), and `test_concurrent_requests_keep_credentials_isolated` already exercises it correctly, so there is no behavior to fix. Worth a one-line correction to the tech design text for future readers, not a code change.

No must-fix findings. Checked against `references/REVIEW.md` §2 and `references/mcp-track.md` §4.3:
- Credentials: read only from `X-Epicor-Email`/`X-Epicor-Pat` headers (`credentials.py:58-64`), never logged (no header values in any `log.*` call), isolated per request via `ContextVar` reset in `finally` (`credentials.py:66-76`), and verified concurrently safe by test and by design (see Finding 1 — the per-call client makes this even stronger than required).
- Tool names/params/errors match the tech design's contract table exactly (7 tools, `epicor_` prefix, error envelope `{code, message, retryable}` with the 4-value vocabulary).
- README's "MSPbots Connector" section is verbatim and correctly placed (see Verification above).
- No DB/migration in this service (stateless proxy) — not applicable.
- No cross-repo header/field compatibility concern — single repo, no other service depends on it yet.
- SOP §14 checklist: reviewed item-by-item against the code (`/health`, `0.0.0.0:8080`, `extra="ignore"`, no credential env fallback, 401 on missing headers, ContextVar isolation, DNS-rebinding protection disabled with the reason commented, MCP app lifespan forwarded, structured errors, timeouts + bounded retry with `Retry-After`, one shared client per call, multi-stage Docker build with non-root user + `curl` + `HEALTHCHECK`, lockfile committed, Header table + Connector section present, repo content all English) — all satisfied. The two "needs a real vendor account" test cases (TC-EPICOR-006/008) and the best-effort discovery field-name mapping (`tools/discovery.py:24-36`) are pre-existing, explicitly documented risks from the design leg (`docs/tickets/PRD-21335.md` "Risks & dependencies", `Handoff`), not new findings — per `references/mcp-track.md` §2.5/§3, the missing vendor account does not block this ticket.

### Next

Approved → merge `dev/PRD-21335` into `main`, delete the work branch, register the new vendor (`epicor`) via `mbp.py mcppub register` (INT does not know this vendor yet), publish to INT, then check/write the connector wiki page (`references/mcp-track.md` §4.4/§4.5). `Release order: any` (single MCP repo, no platform side).

Status: frozen @ 084d54f
