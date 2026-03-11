# S3 Tables Provider for LocalStack Community

**Date:** 2026-03-10
**Status:** Approved
**Author:** David Betts

---

## Problem

S3 Tables (`aws_s3tables_*` Terraform resources + Iceberg REST catalog) is absent on ALL LocalStack tiers — Community, Base, and Ultimate. This blocks local development for any service using DuckDB → S3 Tables → Iceberg, starting with session-exchange-api in developer-productivity-domain.

The CND S3 Tables Terraform module (PR #616) is landing, and consumer repos need to `terraform apply` locally against LocalStack. DuckDB 1.4.4+ supports `ATTACH TYPE ICEBERG` to connect to an Iceberg REST catalog, but LocalStack has no catalog endpoint.

## Spike Findings (Inputs to This Design)

A spike (`developer-productivity-domain/docs/plans/2026-03-10-duckdb-s3-iceberg-spike-findings.md`) validated:

- **Nessie works end-to-end**: ATTACH, CREATE SCHEMA, CREATE TABLE, INSERT, SELECT — full roundtrip with data landing in LocalStack S3 as proper Iceberg format.
- **Polaris does NOT work**: Its credential vending overrides `s3.endpoint`, breaking LocalStack S3 compatibility. Eliminated.
- **DuckDB 1.4.4** (via `duckdb-go/v2`) has full Iceberg REST catalog support.
- **Same code path**: `ATTACH TYPE ICEBERG` works identically against Nessie (local) and S3 Tables (production).

## Design Decision

**Approach: LocalStack S3 Tables provider that delegates to Nessie as the Iceberg catalog backend.**

Alternatives considered:

| Approach | Verdict |
|---|---|
| Provider + Nessie backend | **Selected** — proven in spike, high fidelity, same DuckDB code path |
| Pure in-process mock (reimplement Iceberg REST catalog) | Rejected — too complex, lower fidelity, weeks of work |
| Provider + Polaris backend | Eliminated — credential vending breaks LocalStack S3 |
| Nessie only, no LocalStack provider | Insufficient — need `aws_s3tables_*` Terraform resources |

## Architecture

```
Terraform (aws_s3tables_*)          DuckDB (ATTACH TYPE ICEBERG)
        │                                    │
        ▼                                    │
┌─ LocalStack :4566 ──────────┐              │
│                              │              │
│  S3TablesProvider            │              │
│  ├─ create_table_bucket()    │              │
│  ├─ create_namespace()  ──────── creates in Nessie ──┐
│  ├─ create_table()      ──────── creates in Nessie ──┤
│  ├─ get_table()              │              │        │
│  └─ delete_table()      ──────── deletes in Nessie ──┤
│                              │              │        │
│  S3 (existing)               │              │        │
│  └─ stores Iceberg data files│              │        │
└──────────────────────────────┘              │        │
                                              ▼        ▼
                                    ┌─ Nessie :19120 ──────┐
                                    │ Iceberg REST catalog  │
                                    │ /iceberg/v1/...       │
                                    │ → metadata in-memory  │
                                    │ → data files → LS S3  │
                                    └───────────────────────┘
```

### Key Design Decisions

1. **Table buckets are LocalStack-only state.** No Nessie equivalent. They are a namespace container with an ARN, stored in `S3TablesStore`. Creating a table bucket also creates a backing S3 bucket for Iceberg data files.

2. **Namespaces and tables are dual-written.** `create_namespace()` stores metadata in `S3TablesStore` AND calls Nessie's Iceberg REST API. This keeps the S3 Tables control plane (Terraform) and the Iceberg data plane (DuckDB) in sync.

3. **DuckDB talks directly to Nessie**, not through LocalStack. The provider does not proxy Iceberg REST traffic. This matches the spike findings — Nessie handles the catalog protocol, LocalStack handles the AWS API surface.

4. **Nessie is an implementation detail.** Developers interact only with `localhost:4566` for Terraform. The Iceberg catalog endpoint (Nessie's address) is returned in API responses (e.g., `GetTable` → `metadata_location`). Apps read this from Terraform output, same pattern as production where it would be `https://s3tables.{region}.amazonaws.com`.

5. **Nessie lifecycle managed by LocalStack.** Follows the OpenSearch singleton pattern — one Nessie container started automatically on first use or service startup, stopped on LocalStack shutdown.

6. **Singleton container.** One Nessie instance serves all table buckets, namespaces, and tables. No per-resource containers. Net resource cost: +1 container.

## Developer Experience

### Terraform

```hcl
resource "aws_s3tables_table_bucket" "main" {
  name = "session-exchange"
}

resource "aws_s3tables_namespace" "ns" {
  table_bucket_arn = aws_s3tables_table_bucket.main.arn
  namespace        = ["session_exchange"]
}

resource "aws_s3tables_table" "sessions" {
  table_bucket_arn = aws_s3tables_table_bucket.main.arn
  namespace        = aws_s3tables_namespace.ns.namespace
  name             = "sessions"
  format           = "ICEBERG"
}

output "iceberg_catalog_endpoint" {
  value = aws_s3tables_table_bucket.main.iceberg_catalog_endpoint
}
```

### Application Code

```go
// Same code path for local and production.
// Endpoint comes from Terraform output or env var.
db.Exec(`ATTACH ? AS ice (TYPE ICEBERG, ENDPOINT ?, AUTHORIZATION_TYPE 'none')`,
    warehouse, icebergEndpoint)
db.Exec(`CREATE TABLE ice.session_exchange.sessions (id INT, title VARCHAR)`)
db.Exec(`INSERT INTO ice.session_exchange.sessions VALUES (1, 'hello')`)
```

## Components

### File Structure

```
localstack-core/localstack/services/s3tables/
├── provider.py          # S3TablesProvider — handles aws_s3tables_* API
├── models.py            # S3TablesStore — table bucket, namespace, table metadata
├── nessie_manager.py    # Singleton Nessie container lifecycle
└── plugins.py           # Service registration

localstack-core/localstack/aws/api/s3tables/
└── __init__.py          # Hand-written API types (no Botocore model exists)
```

Registration touchpoints:
- `plux.ini` — `s3tables:default = localstack.services.providers:s3tables`
- `providers.py` — factory function returning `Service.for_provider(S3TablesProvider())`

### provider.py (~200-300 lines)

`S3TablesProvider(S3TablesApi, ServiceLifecycleHook)`

Lifecycle:
- `on_before_start()` — starts Nessie container via `nessie_manager`
- `on_before_stop()` — stops Nessie container
- `accept_state_visitor()` — registers `s3tables_stores` for persistence

Operations:
- `create_table_bucket()` — stores metadata in `S3TablesStore`, creates backing S3 bucket (`s3tables-{name}-{account}`) for Iceberg data files
- `create_namespace()` — stores in `S3TablesStore`, calls `POST /iceberg/v1/namespaces` on Nessie
- `create_table()` — stores in `S3TablesStore`, calls `POST /iceberg/v1/namespaces/{ns}/tables` on Nessie with Iceberg schema
- `get_table()` — reads from store, includes Nessie endpoint URL in `metadata_location` response field
- `get_table_bucket()` — reads from store, includes Nessie endpoint URL
- `list_*()` — reads from store
- `delete_table()` — removes from store, calls `DELETE` on Nessie
- `delete_namespace()` — removes from store, calls `DELETE` on Nessie
- `delete_table_bucket()` — removes from store, optionally cleans up S3 bucket

### models.py (~50-80 lines)

```python
class S3TablesStore(BaseStore):
    table_buckets: dict[str, TableBucketMetadata] = LocalAttribute(default=dict)
    namespaces: dict[str, NamespaceMetadata] = LocalAttribute(default=dict)
    tables: dict[str, TableMetadata] = LocalAttribute(default=dict)

s3tables_stores = AccountRegionBundle("s3tables", S3TablesStore)
```

### nessie_manager.py (~150-200 lines)

Singleton pattern following OpenSearch's `cluster_manager.py`:

- `start()` — pulls `ghcr.io/projectnessie/nessie:latest`, runs container with:
  - Warehouse location pointing at LocalStack S3: `s3://s3tables-data/`
  - S3 endpoint: `http://host.docker.internal:4566/` (or container network alias)
  - Path-style access enabled
  - Credentials: static test/test (LocalStack doesn't enforce)
- `stop()` — stops and removes container
- `health_check()` — `GET /iceberg/v1/config` returns 200
- `get_endpoint()` — returns `http://localhost:19120/iceberg/` (or configured port)
- Port allocation via LocalStack's `external_service_ports.reserve_port()`

### s3tables API types (~150-200 lines)

Hand-written from AWS docs and Terraform provider source. No Botocore s3tables model exists in this codebase.

Operations (~12):
- `CreateTableBucket` / `DeleteTableBucket` / `GetTableBucket` / `ListTableBuckets`
- `CreateNamespace` / `DeleteNamespace` / `GetNamespace` / `ListNamespaces`
- `CreateTable` / `DeleteTable` / `GetTable` / `ListTables` / `UpdateTable`

TypedDicts for request/response shapes matching the AWS API surface that the Terraform provider expects.

## Persistence

- `S3TablesStore` metadata persists through LocalStack's `accept_state_visitor()` pattern.
- Nessie catalog state is in-memory. On LocalStack restart with persistence enabled, `on_after_state_load()` replays `create_namespace` / `create_table` calls to Nessie to reconstruct the catalog.
- Iceberg data files in LocalStack S3 persist if S3 persistence is enabled (separate concern — see gap analysis for S3 persistence approach).

## Estimated Effort

| Component | Effort |
|---|---|
| Hand-write API types (`aws/api/s3tables/__init__.py`) | 0.5 day |
| `models.py` + `provider.py` | 1 day |
| `nessie_manager.py` (Docker lifecycle) | 1 day |
| Registration (`plux.ini`, `providers.py`, `plugins.py`) | 0.5 day |
| Integration testing (Terraform + DuckDB roundtrip) | 1 day |
| **Total** | **3-4 days** |

## Resource Impact

+1 Docker container (Nessie). Singleton — one instance serves all table buckets, namespaces, and tables regardless of how many Terraform resources are created. Nessie's memory footprint is ~200-400MB (JVM-based).

This follows the project-wide rule: container-backed services default to singleton mode. No per-resource container spawning.

## Out of Scope

- Iceberg REST catalog proxy through LocalStack (DuckDB talks directly to Nessie)
- Table bucket policies (`aws_s3tables_table_bucket_policy`, `aws_s3tables_table_policy`) — can be added later as CRUD-only store operations
- S3 Tables maintenance jobs (compaction, snapshot management)
- CloudFormation resource providers for S3 Tables (Terraform-only for now)
