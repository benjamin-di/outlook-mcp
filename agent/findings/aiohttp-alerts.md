# aiohttp Dependabot alerts — 2026-10-21

The push on 2026-10-21 reported open Dependabot alerts. Read-only investigation; nothing in
`pyproject.toml` or `uv.lock` was changed.

## The alerts (VERIFIED: `gh api repos/mpalermiti/outlook-mcp/dependabot/alerts`, 2026-10-21)

| # | Advisory | Severity | Summary (from the public advisory) | Vulnerable | Patched |
|---|---|---|---|---|---|
| 4 | GHSA-2g87-pp6c-29x5 | high | Multiple instances of excessive or unbounded memory/CPU use | <= 3.14.3 | 3.14.4 |
| 3 | GHSA-5wr8-gcqf-gqf3 | high | aiohttp server lacks an initial request/header timeout | <= 3.14.3 | 3.14.4 |
| 2 | GHSA-494j-54xm-rwp3 | low | Secure attribute not enforced for shared cookie | <= 3.14.3 | 3.14.4 |

All three: manifest `uv.lock`, relationship `transitive`, scope `runtime`, created 2026-10-20.

## Who is exposed

**Users: no.** Three independent reasons, each enough on its own:

1. **aiohttp never loads.** VERIFIED: importing `outlook_mcp.server`, `.graph`, `.auth`, `.cli`,
   every module in `outlook_mcp.tools`, `msgraph`, kiota's Azure auth provider and kiota's httpx
   adapter leaves no `aiohttp*` module in `sys.modules`. The only importers of aiohttp in the
   environment are `azure/core/pipeline/transport/_aiohttp.py` and `azure/core/rest/_aiohttp.py`
   (grep of site-packages), azure-core's *async* transport. `auth.py` uses the sync
   `azure.identity` credentials (`DeviceCodeCredential`), and Graph traffic goes through
   kiota's httpx adapter. `grep -rn aiohttp src/` → nothing.
2. **Nothing here runs an aiohttp server**, so the header-timeout advisory (#3) cannot apply.
   The cookie and memory advisories need aiohttp to send or parse traffic, which per (1) it doesn't.
3. **A fresh install already gets the fix.** aiohttp reaches us only through
   `microsoft-kiota-authentication-azure`, which requires `aiohttp>=3.8.0` (VERIFIED, its
   METADATA); `pyproject.toml` does not mention aiohttp. PyPI's latest is 3.14.5; 3.14.4 was
   uploaded 2026-10-05 (VERIFIED, PyPI JSON). The published wheel carries no lock, so
   `pip install outlook-graph-mcp` resolves the patched version (the PyPI distribution is
   `outlook-graph-mcp`; `outlook-mcp` on PyPI is an unrelated project). ASSUMED, not checked: an *existing*
   environment upgraded with `pip install -U outlook-graph-mcp` keeps its old aiohttp (pip's default
   `only-if-needed` strategy), but per (1) it is never loaded.

**The repo: only the lock.** `uv.lock` pins aiohttp 3.14.3, so `uv sync` (the CI `test` job,
contributors) installs it. Per (1) it still never loads, so this is alert noise, not exposure.

## The smallest fix (needs Michael: it is a dependency change)

`uv lock --upgrade-package aiohttp`, generated and then reverted on 2026-10-21:

```
Updated aiohttp v3.14.3 -> v3.14.5
Updated yarl v1.24.5 -> v1.25.1
 uv.lock | 530 +++++++++++++++++++++++++++++++++++++---------------------------
```

Pinning to `aiohttp==3.14.4` moves the same two packages (yarl too), so there is no smaller
diff. Lock only: `pyproject.toml` unchanged, no floor. A floor (`aiohttp>=3.14.4`) is not
worth adding. We don't depend on aiohttp directly or ever load it, and fresh installs
already resolve past the fix.

Not run: the suite against the refreshed lock (doing so would re-sync `.venv`). Expected
green, since nothing imports aiohttp, but a worker doing the refresh runs it.

Other option instead of the refresh: dismiss the three alerts on GitHub as "vulnerable code
is not actually used". Only Michael can do that.

**When the alerts close.** Dependabot reads the default branch, so a refreshed lock on
`agent/work` closes nothing until the rolling PR merges into `main`. VERIFIED: alert #1
(multidict) was fixed automatically at 2026-10-08T02:11:44Z, after `main` moved multidict
6.8.0 → 6.9.1 (`gh api .../dependabot/alerts`). Dismissing clears them the same day; the
refresh clears them on merge, for good.
