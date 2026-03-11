# S3 Tables Provider Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an S3 Tables provider to LocalStack Community that handles `aws_s3tables_*` Terraform resources and delegates to a Nessie Iceberg REST catalog container for data plane operations.

**Architecture:** A new `s3tables` service in LocalStack with a provider that stores table bucket/namespace/table metadata in `S3TablesStore`, manages a singleton Nessie Docker container for the Iceberg catalog, and returns the Nessie endpoint in API responses so DuckDB can `ATTACH TYPE ICEBERG` transparently.

**Tech Stack:** Python 3.11+, LocalStack plugin framework (`plux`), Docker container client (`DOCKER_CLIENT`), Nessie (`ghcr.io/projectnessie/nessie`), `requests` for HTTP calls to Nessie REST API.

**Design Doc:** `docs/plans/2026-03-10-s3tables-provider-design.md`

**Fork:** `https://github.com/wdbetts/localstack` (remote name: `fork`)

**Reference implementation:** OpenSearch provider at `localstack-core/localstack/services/opensearch/`

---

### Task 1: Hand-Write S3 Tables API Types

**Files:**
- Create: `localstack-core/localstack/aws/api/s3tables/__init__.py`

**Step 1: Create the API types module**

This file defines the abstract API class and TypedDicts that the provider implements. Based on the AWS S3 Tables API surface used by the Terraform AWS provider (`aws_s3tables_table_bucket`, `aws_s3tables_namespace`, `aws_s3tables_table`).

```python
"""Hand-written API types for S3 Tables service.

No Botocore service model exists in this codebase, so these are written
from the AWS S3 Tables API documentation and Terraform provider source.
"""

import datetime
from enum import StrEnum
from typing import TypedDict

from localstack.aws.api.core import ServiceRequest, handler


# --- Enums ---

class OpenTableFormat(StrEnum):
    ICEBERG = "ICEBERG"


class TableBucketMaintenanceType(StrEnum):
    iceberg_compaction = "icebergCompaction"
    iceberg_snapshot_management = "icebergSnapshotManagement"


# --- Request / Response TypedDicts ---

class CreateTableBucketRequest(ServiceRequest):
    name: str
    maintenance_configuration: dict | None


class CreateTableBucketResponse(TypedDict, total=False):
    arn: str


class GetTableBucketRequest(ServiceRequest):
    table_bucket_arn: str


class GetTableBucketResponse(TypedDict, total=False):
    arn: str
    name: str
    owner_account_id: str
    created_at: datetime.datetime
    metadata_location: str


class ListTableBucketsRequest(ServiceRequest):
    prefix: str | None
    continuation_token: str | None
    max_buckets: int | None


class TableBucketSummary(TypedDict, total=False):
    arn: str
    name: str
    owner_account_id: str
    created_at: datetime.datetime


class ListTableBucketsResponse(TypedDict, total=False):
    table_buckets: list[TableBucketSummary]
    continuation_token: str | None


class DeleteTableBucketRequest(ServiceRequest):
    table_bucket_arn: str


class CreateNamespaceRequest(ServiceRequest):
    table_bucket_arn: str
    namespace: list[str]


class CreateNamespaceResponse(TypedDict, total=False):
    table_bucket_arn: str
    namespace: list[str]


class GetNamespaceRequest(ServiceRequest):
    table_bucket_arn: str
    namespace: str


class GetNamespaceResponse(TypedDict, total=False):
    namespace: list[str]
    created_at: datetime.datetime
    created_by: str
    owner_account_id: str


class ListNamespacesRequest(ServiceRequest):
    table_bucket_arn: str
    prefix: str | None
    continuation_token: str | None
    max_namespaces: int | None


class NamespaceSummary(TypedDict, total=False):
    namespace: list[str]
    created_at: datetime.datetime
    created_by: str
    owner_account_id: str


class ListNamespacesResponse(TypedDict, total=False):
    namespaces: list[NamespaceSummary]
    continuation_token: str | None


class DeleteNamespaceRequest(ServiceRequest):
    table_bucket_arn: str
    namespace: str


class CreateTableRequest(ServiceRequest):
    table_bucket_arn: str
    namespace: str
    name: str
    format: OpenTableFormat


class CreateTableResponse(TypedDict, total=False):
    table_arn: str
    version_token: str


class GetTableRequest(ServiceRequest):
    table_bucket_arn: str
    namespace: str
    name: str


class GetTableResponse(TypedDict, total=False):
    name: str
    table_arn: str
    namespace: list[str]
    version_token: str
    metadata_location: str
    warehouse_location: str
    created_at: datetime.datetime
    created_by: str
    modified_at: datetime.datetime
    modified_by: str
    owner_account_id: str
    format: OpenTableFormat
    type: str


class ListTablesRequest(ServiceRequest):
    table_bucket_arn: str
    namespace: str | None
    prefix: str | None
    continuation_token: str | None
    max_tables: int | None


class TableSummary(TypedDict, total=False):
    namespace: list[str]
    name: str
    type: str
    table_arn: str
    created_at: datetime.datetime
    modified_at: datetime.datetime


class ListTablesResponse(TypedDict, total=False):
    tables: list[TableSummary]
    continuation_token: str | None


class DeleteTableRequest(ServiceRequest):
    table_bucket_arn: str
    namespace: str
    name: str
    version_token: str | None


class UpdateTableMetadataLocationRequest(ServiceRequest):
    table_bucket_arn: str
    namespace: str
    name: str
    version_token: str
    metadata_location: str


class UpdateTableMetadataLocationResponse(TypedDict, total=False):
    name: str
    table_arn: str
    namespace: list[str]
    version_token: str
    metadata_location: str


# --- Exceptions ---

class NotFoundException(Exception):
    code: str = "NotFoundException"
    sender_fault: bool = False
    status_code: int = 404


class ConflictException(Exception):
    code: str = "ConflictException"
    sender_fault: bool = False
    status_code: int = 409


class BadRequestException(Exception):
    code: str = "BadRequestException"
    sender_fault: bool = True
    status_code: int = 400


# --- Abstract API class ---

class S3TablesApi:
    service = "s3tables"
    version = "2018-05-10"

    @handler("CreateTableBucket")
    def create_table_bucket(
        self, context, name: str, **kwargs
    ) -> CreateTableBucketResponse:
        raise NotImplementedError

    @handler("GetTableBucket")
    def get_table_bucket(
        self, context, table_bucket_arn: str, **kwargs
    ) -> GetTableBucketResponse:
        raise NotImplementedError

    @handler("ListTableBuckets")
    def list_table_buckets(
        self, context, **kwargs
    ) -> ListTableBucketsResponse:
        raise NotImplementedError

    @handler("DeleteTableBucket")
    def delete_table_bucket(
        self, context, table_bucket_arn: str, **kwargs
    ) -> None:
        raise NotImplementedError

    @handler("CreateNamespace")
    def create_namespace(
        self, context, table_bucket_arn: str, namespace: list[str], **kwargs
    ) -> CreateNamespaceResponse:
        raise NotImplementedError

    @handler("GetNamespace")
    def get_namespace(
        self, context, table_bucket_arn: str, namespace: str, **kwargs
    ) -> GetNamespaceResponse:
        raise NotImplementedError

    @handler("ListNamespaces")
    def list_namespaces(
        self, context, table_bucket_arn: str, **kwargs
    ) -> ListNamespacesResponse:
        raise NotImplementedError

    @handler("DeleteNamespace")
    def delete_namespace(
        self, context, table_bucket_arn: str, namespace: str, **kwargs
    ) -> None:
        raise NotImplementedError

    @handler("CreateTable")
    def create_table(
        self, context, table_bucket_arn: str, namespace: str, name: str, format: OpenTableFormat, **kwargs
    ) -> CreateTableResponse:
        raise NotImplementedError

    @handler("GetTable")
    def get_table(
        self, context, table_bucket_arn: str, namespace: str, name: str, **kwargs
    ) -> GetTableResponse:
        raise NotImplementedError

    @handler("ListTables")
    def list_tables(
        self, context, table_bucket_arn: str, **kwargs
    ) -> ListTablesResponse:
        raise NotImplementedError

    @handler("DeleteTable")
    def delete_table(
        self, context, table_bucket_arn: str, namespace: str, name: str, **kwargs
    ) -> None:
        raise NotImplementedError

    @handler("UpdateTableMetadataLocation")
    def update_table_metadata_location(
        self, context, table_bucket_arn: str, namespace: str, name: str,
        version_token: str, metadata_location: str, **kwargs
    ) -> UpdateTableMetadataLocationResponse:
        raise NotImplementedError
```

**Step 2: Verify the module is importable**

Run: `cd /Users/wbetts/src/github/localstack && python -c "from localstack.aws.api.s3tables import S3TablesApi; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add localstack-core/localstack/aws/api/s3tables/__init__.py
git commit -m "feat(s3tables): add hand-written API types for S3 Tables service"
```

---

### Task 2: Create S3 Tables Store (models.py)

**Files:**
- Create: `localstack-core/localstack/services/s3tables/models.py`

**Reference:** `localstack-core/localstack/services/opensearch/models.py` (16 lines)

**Step 1: Write the store**

```python
import dataclasses
import datetime

from localstack.services.stores import (
    AccountRegionBundle,
    BaseStore,
    LocalAttribute,
)


@dataclasses.dataclass
class TableBucketMetadata:
    arn: str
    name: str
    owner_account_id: str
    created_at: datetime.datetime
    s3_bucket_name: str  # backing S3 bucket for Iceberg data


@dataclasses.dataclass
class NamespaceMetadata:
    namespace: list[str]
    table_bucket_arn: str
    created_at: datetime.datetime
    created_by: str
    owner_account_id: str


@dataclasses.dataclass
class TableMetadata:
    name: str
    table_arn: str
    namespace: list[str]
    table_bucket_arn: str
    format: str
    version_token: str
    metadata_location: str
    warehouse_location: str
    created_at: datetime.datetime
    created_by: str
    modified_at: datetime.datetime
    modified_by: str
    owner_account_id: str


class S3TablesStore(BaseStore):
    # table_bucket_arn -> TableBucketMetadata
    table_buckets: dict[str, TableBucketMetadata] = LocalAttribute(default=dict)
    # "{table_bucket_arn}|{namespace_name}" -> NamespaceMetadata
    namespaces: dict[str, NamespaceMetadata] = LocalAttribute(default=dict)
    # "{table_bucket_arn}|{namespace}|{table_name}" -> TableMetadata
    tables: dict[str, TableMetadata] = LocalAttribute(default=dict)


s3tables_stores = AccountRegionBundle("s3tables", S3TablesStore)
```

**Step 2: Verify import**

Run: `cd /Users/wbetts/src/github/localstack && python -c "from localstack.services.s3tables.models import s3tables_stores; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add localstack-core/localstack/services/s3tables/models.py
git commit -m "feat(s3tables): add S3TablesStore data models"
```

---

### Task 3: Create Nessie Container Manager

**Files:**
- Create: `localstack-core/localstack/services/s3tables/nessie_manager.py`

**Reference:** `localstack-core/localstack/services/opensearch/cluster_manager.py` (singleton pattern at lines 125-129)

**Step 1: Write the Nessie manager**

```python
import logging
import time

import requests

from localstack.utils.container_utils.container_client import (
    ContainerClient,
    DockerContainerStatus,
    PortMappings,
)
from localstack.utils.docker_utils import DOCKER_CLIENT
from localstack.utils.net import get_free_tcp_port

LOG = logging.getLogger(__name__)

NESSIE_IMAGE = "ghcr.io/projectnessie/nessie:latest"
NESSIE_CONTAINER_NAME = "localstack-s3tables-nessie"
NESSIE_INTERNAL_PORT = 19120
HEALTH_CHECK_TIMEOUT = 60
HEALTH_CHECK_INTERVAL = 2


class NessieManager:
    """Manages a singleton Nessie container that serves as the Iceberg REST catalog
    backend for the S3 Tables provider."""

    def __init__(self, docker_client: ContainerClient | None = None):
        self._docker_client = docker_client or DOCKER_CLIENT
        self._port: int | None = None
        self._started = False

    @property
    def endpoint(self) -> str | None:
        if not self._started or self._port is None:
            return None
        return f"http://localhost:{self._port}/iceberg/"

    def start(self, localstack_s3_endpoint: str = "http://host.docker.internal:4566") -> str:
        """Start the Nessie container if not already running. Returns the Iceberg REST endpoint URL."""
        if self._started and self._is_running():
            return self.endpoint

        LOG.info("Starting Nessie Iceberg catalog container...")

        # Check if container already exists from a previous run
        status = self._docker_client.get_container_status(NESSIE_CONTAINER_NAME)
        if status == DockerContainerStatus.UP:
            LOG.info("Nessie container already running, reusing.")
            self._port = self._get_mapped_port()
            self._started = True
            return self.endpoint

        # Clean up stopped container if it exists
        if status != DockerContainerStatus.NON_EXISTENT:
            self._docker_client.remove_container(NESSIE_CONTAINER_NAME, force=True)

        self._port = get_free_tcp_port()
        port_mappings = PortMappings()
        port_mappings.add(self._port, NESSIE_INTERNAL_PORT)

        env_vars = {
            "nessie.catalog.default-warehouse": "warehouse",
            "nessie.catalog.warehouses.warehouse.location": "s3://s3tables-data/",
            "nessie.catalog.service.s3.default-options.region": "us-east-1",
            "nessie.catalog.service.s3.default-options.path-style-access": "true",
            "nessie.catalog.service.s3.default-options.access-key": (
                "urn:nessie-secret:quarkus:nessie.catalog.secrets.access-key"
            ),
            "nessie.catalog.secrets.access-key.name": "test",
            "nessie.catalog.secrets.access-key.secret": "test",
            "nessie.catalog.service.s3.default-options.endpoint": localstack_s3_endpoint,
            "nessie.catalog.service.s3.default-options.external-endpoint": (
                "http://localhost:4566/"
            ),
        }

        self._docker_client.run_container(
            image_name=NESSIE_IMAGE,
            name=NESSIE_CONTAINER_NAME,
            detach=True,
            ports=port_mappings,
            env_vars=env_vars,
        )

        self._wait_for_healthy()
        self._started = True
        LOG.info("Nessie Iceberg catalog running at %s", self.endpoint)
        return self.endpoint

    def stop(self):
        """Stop and remove the Nessie container."""
        if not self._started:
            return

        LOG.info("Stopping Nessie Iceberg catalog container...")
        try:
            self._docker_client.stop_container(NESSIE_CONTAINER_NAME, timeout=10)
        except Exception:
            LOG.debug("Error stopping Nessie container", exc_info=True)
        try:
            self._docker_client.remove_container(NESSIE_CONTAINER_NAME, force=True)
        except Exception:
            LOG.debug("Error removing Nessie container", exc_info=True)

        self._started = False
        self._port = None

    def _is_running(self) -> bool:
        try:
            return (
                self._docker_client.get_container_status(NESSIE_CONTAINER_NAME)
                == DockerContainerStatus.UP
            )
        except Exception:
            return False

    def _get_mapped_port(self) -> int:
        info = self._docker_client.inspect_container(NESSIE_CONTAINER_NAME)
        ports = info.get("Ports", "")
        # Parse port mapping from inspect output — format varies by client
        # Fall back to stored port if parsing fails
        if self._port:
            return self._port
        raise RuntimeError("Cannot determine Nessie mapped port")

    def _wait_for_healthy(self):
        """Poll Nessie's config endpoint until it responds."""
        url = f"http://localhost:{self._port}/iceberg/v1/config"
        deadline = time.time() + HEALTH_CHECK_TIMEOUT
        while time.time() < deadline:
            try:
                resp = requests.get(url, timeout=2)
                if resp.status_code == 200:
                    return
            except requests.ConnectionError:
                pass
            time.sleep(HEALTH_CHECK_INTERVAL)
        raise TimeoutError(
            f"Nessie container did not become healthy within {HEALTH_CHECK_TIMEOUT}s"
        )


# --- Singleton ---

_nessie_manager: NessieManager | None = None


def nessie_manager() -> NessieManager:
    global _nessie_manager
    if _nessie_manager is None:
        _nessie_manager = NessieManager()
    return _nessie_manager
```

**Step 2: Verify import**

Run: `cd /Users/wbetts/src/github/localstack && python -c "from localstack.services.s3tables.nessie_manager import nessie_manager; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add localstack-core/localstack/services/s3tables/nessie_manager.py
git commit -m "feat(s3tables): add Nessie container manager (singleton Docker lifecycle)"
```

---

### Task 4: Create the S3 Tables Provider

**Files:**
- Create: `localstack-core/localstack/services/s3tables/provider.py`

**Reference:** `localstack-core/localstack/services/opensearch/provider.py:461-584` (class structure, lifecycle hooks, create_domain pattern)

**Step 1: Write the provider**

```python
import logging
import threading
import uuid
from datetime import UTC, datetime

import requests

from localstack.aws.api import RequestContext, handler
from localstack.aws.api.s3tables import (
    BadRequestException,
    ConflictException,
    CreateNamespaceResponse,
    CreateTableBucketResponse,
    CreateTableResponse,
    GetNamespaceResponse,
    GetTableBucketResponse,
    GetTableResponse,
    ListNamespacesResponse,
    ListTableBucketsResponse,
    ListTablesResponse,
    NotFoundException,
    OpenTableFormat,
    S3TablesApi,
    UpdateTableMetadataLocationResponse,
)
from localstack.services.plugins import ServiceLifecycleHook
from localstack.services.s3tables.models import (
    NamespaceMetadata,
    S3TablesStore,
    TableBucketMetadata,
    TableMetadata,
    s3tables_stores,
)
from localstack.services.s3tables.nessie_manager import nessie_manager
from localstack.state import StateVisitor
from localstack.utils.aws.arns import get_partition

LOG = logging.getLogger(__name__)

_mutex = threading.RLock()


def _table_bucket_arn(account_id: str, region: str, name: str) -> str:
    return f"arn:{get_partition(region)}:s3tables:{region}:{account_id}:bucket/{name}"


def _table_arn(table_bucket_arn: str, namespace: str, table_name: str) -> str:
    return f"{table_bucket_arn}/table/{namespace}/{table_name}"


def _namespace_key(table_bucket_arn: str, namespace: str) -> str:
    return f"{table_bucket_arn}|{namespace}"


def _table_key(table_bucket_arn: str, namespace: str, table_name: str) -> str:
    return f"{table_bucket_arn}|{namespace}|{table_name}"


class S3TablesProvider(S3TablesApi, ServiceLifecycleHook):
    @staticmethod
    def get_store(account_id: str, region_name: str) -> S3TablesStore:
        return s3tables_stores[account_id][region_name]

    def accept_state_visitor(self, visitor: StateVisitor):
        visitor.visit(s3tables_stores)

    def on_before_start(self):
        pass  # Nessie started lazily on first create_table_bucket

    def on_before_stop(self):
        nessie_manager().stop()

    def on_after_state_load(self):
        """Replay namespaces and tables to Nessie after state restore."""
        manager = nessie_manager()
        for account_id, region, store in s3tables_stores.iter_stores():
            if not store.table_buckets:
                continue
            endpoint = manager.start()
            for ns_key, ns_meta in store.namespaces.items():
                ns_name = ns_meta.namespace[0] if ns_meta.namespace else ns_key.split("|")[1]
                try:
                    requests.post(
                        f"{endpoint}v1/namespaces",
                        json={"namespace": [ns_name]},
                        timeout=5,
                    )
                except Exception:
                    LOG.warning("Failed to restore namespace %s to Nessie", ns_name)
            for tbl_key, tbl_meta in store.tables.items():
                ns_name = tbl_meta.namespace[0]
                try:
                    requests.post(
                        f"{endpoint}v1/namespaces/{ns_name}/tables",
                        json={
                            "name": tbl_meta.name,
                            "schema": {"type": "struct", "fields": []},
                        },
                        timeout=5,
                    )
                except Exception:
                    LOG.warning("Failed to restore table %s to Nessie", tbl_meta.name)

    def on_before_state_reset(self):
        nessie_manager().stop()

    # --- Table Bucket operations ---

    @handler("CreateTableBucket")
    def create_table_bucket(
        self, context: RequestContext, name: str, **kwargs
    ) -> CreateTableBucketResponse:
        store = self.get_store(context.account_id, context.region)
        arn = _table_bucket_arn(context.account_id, context.region, name)

        with _mutex:
            if arn in store.table_buckets:
                raise ConflictException(f"Table bucket {name} already exists")

            # Start Nessie on first table bucket creation
            nessie_manager().start()

            store.table_buckets[arn] = TableBucketMetadata(
                arn=arn,
                name=name,
                owner_account_id=context.account_id,
                created_at=datetime.now(UTC),
                s3_bucket_name=f"s3tables-{name}-{context.account_id}",
            )

        return CreateTableBucketResponse(arn=arn)

    @handler("GetTableBucket")
    def get_table_bucket(
        self, context: RequestContext, table_bucket_arn: str, **kwargs
    ) -> GetTableBucketResponse:
        store = self.get_store(context.account_id, context.region)
        meta = store.table_buckets.get(table_bucket_arn)
        if not meta:
            raise NotFoundException(f"Table bucket not found: {table_bucket_arn}")

        endpoint = nessie_manager().endpoint or ""
        return GetTableBucketResponse(
            arn=meta.arn,
            name=meta.name,
            owner_account_id=meta.owner_account_id,
            created_at=meta.created_at,
            metadata_location=endpoint,
        )

    @handler("ListTableBuckets")
    def list_table_buckets(
        self, context: RequestContext, **kwargs
    ) -> ListTableBucketsResponse:
        store = self.get_store(context.account_id, context.region)
        return ListTableBucketsResponse(
            table_buckets=[
                {
                    "arn": m.arn,
                    "name": m.name,
                    "owner_account_id": m.owner_account_id,
                    "created_at": m.created_at,
                }
                for m in store.table_buckets.values()
            ]
        )

    @handler("DeleteTableBucket")
    def delete_table_bucket(
        self, context: RequestContext, table_bucket_arn: str, **kwargs
    ) -> None:
        store = self.get_store(context.account_id, context.region)
        with _mutex:
            if table_bucket_arn not in store.table_buckets:
                raise NotFoundException(f"Table bucket not found: {table_bucket_arn}")

            # Check for remaining namespaces
            remaining = [k for k in store.namespaces if k.startswith(table_bucket_arn)]
            if remaining:
                raise ConflictException("Table bucket is not empty — delete namespaces first")

            del store.table_buckets[table_bucket_arn]

    # --- Namespace operations ---

    @handler("CreateNamespace")
    def create_namespace(
        self, context: RequestContext, table_bucket_arn: str, namespace: list[str], **kwargs
    ) -> CreateNamespaceResponse:
        store = self.get_store(context.account_id, context.region)
        if table_bucket_arn not in store.table_buckets:
            raise NotFoundException(f"Table bucket not found: {table_bucket_arn}")

        ns_name = namespace[0] if namespace else ""
        if not ns_name:
            raise BadRequestException("Namespace name is required")

        key = _namespace_key(table_bucket_arn, ns_name)
        with _mutex:
            if key in store.namespaces:
                raise ConflictException(f"Namespace {ns_name} already exists")

            # Create in Nessie
            endpoint = nessie_manager().endpoint
            resp = requests.post(
                f"{endpoint}v1/namespaces",
                json={"namespace": [ns_name]},
                timeout=10,
            )
            if resp.status_code not in (200, 409):  # 409 = already exists, ok
                LOG.error("Nessie create namespace failed: %s %s", resp.status_code, resp.text)

            store.namespaces[key] = NamespaceMetadata(
                namespace=namespace,
                table_bucket_arn=table_bucket_arn,
                created_at=datetime.now(UTC),
                created_by=context.account_id,
                owner_account_id=context.account_id,
            )

        return CreateNamespaceResponse(
            table_bucket_arn=table_bucket_arn,
            namespace=namespace,
        )

    @handler("GetNamespace")
    def get_namespace(
        self, context: RequestContext, table_bucket_arn: str, namespace: str, **kwargs
    ) -> GetNamespaceResponse:
        store = self.get_store(context.account_id, context.region)
        key = _namespace_key(table_bucket_arn, namespace)
        meta = store.namespaces.get(key)
        if not meta:
            raise NotFoundException(f"Namespace not found: {namespace}")

        return GetNamespaceResponse(
            namespace=meta.namespace,
            created_at=meta.created_at,
            created_by=meta.created_by,
            owner_account_id=meta.owner_account_id,
        )

    @handler("ListNamespaces")
    def list_namespaces(
        self, context: RequestContext, table_bucket_arn: str, **kwargs
    ) -> ListNamespacesResponse:
        store = self.get_store(context.account_id, context.region)
        return ListNamespacesResponse(
            namespaces=[
                {
                    "namespace": m.namespace,
                    "created_at": m.created_at,
                    "created_by": m.created_by,
                    "owner_account_id": m.owner_account_id,
                }
                for k, m in store.namespaces.items()
                if k.startswith(table_bucket_arn)
            ]
        )

    @handler("DeleteNamespace")
    def delete_namespace(
        self, context: RequestContext, table_bucket_arn: str, namespace: str, **kwargs
    ) -> None:
        store = self.get_store(context.account_id, context.region)
        key = _namespace_key(table_bucket_arn, namespace)

        with _mutex:
            if key not in store.namespaces:
                raise NotFoundException(f"Namespace not found: {namespace}")

            # Check for remaining tables
            remaining = [k for k in store.tables if k.startswith(f"{table_bucket_arn}|{namespace}|")]
            if remaining:
                raise ConflictException("Namespace is not empty — delete tables first")

            # Delete from Nessie
            endpoint = nessie_manager().endpoint
            requests.delete(f"{endpoint}v1/namespaces/{namespace}", timeout=10)

            del store.namespaces[key]

    # --- Table operations ---

    @handler("CreateTable")
    def create_table(
        self, context: RequestContext, table_bucket_arn: str, namespace: str,
        name: str, format: OpenTableFormat, **kwargs
    ) -> CreateTableResponse:
        store = self.get_store(context.account_id, context.region)
        ns_key = _namespace_key(table_bucket_arn, namespace)
        if ns_key not in store.namespaces:
            raise NotFoundException(f"Namespace not found: {namespace}")

        tbl_key = _table_key(table_bucket_arn, namespace, name)
        table_arn = _table_arn(table_bucket_arn, namespace, name)
        version_token = str(uuid.uuid4())

        bucket_meta = store.table_buckets.get(table_bucket_arn)
        warehouse = f"s3://{bucket_meta.s3_bucket_name}/data/" if bucket_meta else "s3://s3tables-data/"

        with _mutex:
            if tbl_key in store.tables:
                raise ConflictException(f"Table {name} already exists in namespace {namespace}")

            # Create in Nessie
            endpoint = nessie_manager().endpoint
            resp = requests.post(
                f"{endpoint}v1/namespaces/{namespace}/tables",
                json={
                    "name": name,
                    "schema": {"type": "struct", "fields": []},
                },
                timeout=10,
            )
            if resp.status_code not in (200, 409):
                LOG.error("Nessie create table failed: %s %s", resp.status_code, resp.text)

            nessie_metadata = ""
            if resp.status_code == 200:
                body = resp.json()
                nessie_metadata = body.get("metadata-location", "")

            now = datetime.now(UTC)
            store.tables[tbl_key] = TableMetadata(
                name=name,
                table_arn=table_arn,
                namespace=[namespace],
                table_bucket_arn=table_bucket_arn,
                format=format,
                version_token=version_token,
                metadata_location=nessie_metadata,
                warehouse_location=warehouse,
                created_at=now,
                created_by=context.account_id,
                modified_at=now,
                modified_by=context.account_id,
                owner_account_id=context.account_id,
            )

        return CreateTableResponse(table_arn=table_arn, version_token=version_token)

    @handler("GetTable")
    def get_table(
        self, context: RequestContext, table_bucket_arn: str, namespace: str,
        name: str, **kwargs
    ) -> GetTableResponse:
        store = self.get_store(context.account_id, context.region)
        tbl_key = _table_key(table_bucket_arn, namespace, name)
        meta = store.tables.get(tbl_key)
        if not meta:
            raise NotFoundException(f"Table not found: {namespace}/{name}")

        endpoint = nessie_manager().endpoint or ""
        return GetTableResponse(
            name=meta.name,
            table_arn=meta.table_arn,
            namespace=meta.namespace,
            version_token=meta.version_token,
            metadata_location=endpoint,
            warehouse_location=meta.warehouse_location,
            created_at=meta.created_at,
            created_by=meta.created_by,
            modified_at=meta.modified_at,
            modified_by=meta.modified_by,
            owner_account_id=meta.owner_account_id,
            format=meta.format,
            type="customer",
        )

    @handler("ListTables")
    def list_tables(
        self, context: RequestContext, table_bucket_arn: str, **kwargs
    ) -> ListTablesResponse:
        store = self.get_store(context.account_id, context.region)
        namespace_filter = kwargs.get("namespace")
        prefix = f"{table_bucket_arn}|"
        if namespace_filter:
            prefix = f"{table_bucket_arn}|{namespace_filter}|"

        return ListTablesResponse(
            tables=[
                {
                    "namespace": m.namespace,
                    "name": m.name,
                    "type": "customer",
                    "table_arn": m.table_arn,
                    "created_at": m.created_at,
                    "modified_at": m.modified_at,
                }
                for k, m in store.tables.items()
                if k.startswith(prefix)
            ]
        )

    @handler("DeleteTable")
    def delete_table(
        self, context: RequestContext, table_bucket_arn: str, namespace: str,
        name: str, **kwargs
    ) -> None:
        store = self.get_store(context.account_id, context.region)
        tbl_key = _table_key(table_bucket_arn, namespace, name)

        with _mutex:
            if tbl_key not in store.tables:
                raise NotFoundException(f"Table not found: {namespace}/{name}")

            # Delete from Nessie
            endpoint = nessie_manager().endpoint
            requests.delete(f"{endpoint}v1/namespaces/{namespace}/tables/{name}", timeout=10)

            del store.tables[tbl_key]

    @handler("UpdateTableMetadataLocation")
    def update_table_metadata_location(
        self, context: RequestContext, table_bucket_arn: str, namespace: str,
        name: str, version_token: str, metadata_location: str, **kwargs
    ) -> UpdateTableMetadataLocationResponse:
        store = self.get_store(context.account_id, context.region)
        tbl_key = _table_key(table_bucket_arn, namespace, name)

        with _mutex:
            meta = store.tables.get(tbl_key)
            if not meta:
                raise NotFoundException(f"Table not found: {namespace}/{name}")
            if meta.version_token != version_token:
                raise ConflictException("Version token mismatch")

            new_token = str(uuid.uuid4())
            meta.metadata_location = metadata_location
            meta.version_token = new_token
            meta.modified_at = datetime.now(UTC)
            meta.modified_by = context.account_id

        return UpdateTableMetadataLocationResponse(
            name=meta.name,
            table_arn=meta.table_arn,
            namespace=meta.namespace,
            version_token=new_token,
            metadata_location=metadata_location,
        )
```

**Step 2: Verify import**

Run: `cd /Users/wbetts/src/github/localstack && python -c "from localstack.services.s3tables.provider import S3TablesProvider; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add localstack-core/localstack/services/s3tables/provider.py
git commit -m "feat(s3tables): add S3TablesProvider with Nessie backend delegation"
```

---

### Task 5: Register the Service

**Files:**
- Create: `localstack-core/localstack/services/s3tables/__init__.py` (empty)
- Create: `localstack-core/localstack/services/s3tables/plugins.py`
- Modify: `localstack-core/localstack/services/providers.py` (add factory after opensearch, ~line 238)
- Modify: `plux.ini` (add s3tables entry after s3control, ~line 37)

**Step 1: Create empty `__init__.py`**

```python
```

(Empty file — just makes the directory a Python package.)

**Step 2: Create `plugins.py`**

```python
# No package plugin needed — Nessie is pulled at runtime via Docker, not installed as a binary.
```

(Empty for now. Unlike OpenSearch which needs `opensearch_package` for binary downloads, Nessie is a Docker image pulled on demand.)

**Step 3: Add factory function to `providers.py`**

Add after the `opensearch` function (after line 238):

```python
@aws_provider()
def s3tables():
    from localstack.services.s3tables.provider import S3TablesProvider

    provider = S3TablesProvider()
    return Service.for_provider(provider)
```

**Step 4: Add `plux.ini` entry**

Add after `s3control:default` line (after line 37):

```ini
s3tables:default = localstack.services.providers:s3tables
```

**Step 5: Verify service loads**

Run: `cd /Users/wbetts/src/github/localstack && python -c "from localstack.services.providers import s3tables; print(s3tables); print('OK')"`
Expected: prints the function object and `OK`

**Step 6: Commit**

```bash
git add localstack-core/localstack/services/s3tables/__init__.py \
        localstack-core/localstack/services/s3tables/plugins.py \
        localstack-core/localstack/services/providers.py \
        plux.ini
git commit -m "feat(s3tables): register S3 Tables service in LocalStack plugin system"
```

---

### Task 6: Integration Test — Table Bucket CRUD

**Files:**
- Create: `tests/aws/services/s3tables/test_s3tables.py`

**Step 1: Write the test**

```python
"""Integration tests for S3 Tables provider.

Requires Docker (for Nessie container) and LocalStack running.
"""

import pytest

from localstack.testing.pytest import markers


class TestS3TablesTableBucket:
    @markers.aws.unknown
    def test_create_and_get_table_bucket(self, aws_client):
        name = "test-bucket"
        create_resp = aws_client.s3tables.create_table_bucket(name=name)
        arn = create_resp["arn"]
        assert arn
        assert "s3tables" in arn
        assert name in arn

        get_resp = aws_client.s3tables.get_table_bucket(tableBucketARN=arn)
        assert get_resp["name"] == name
        assert get_resp["arn"] == arn

        # Cleanup
        aws_client.s3tables.delete_table_bucket(tableBucketARN=arn)

    @markers.aws.unknown
    def test_list_table_buckets(self, aws_client):
        name = "list-test-bucket"
        create_resp = aws_client.s3tables.create_table_bucket(name=name)
        arn = create_resp["arn"]

        list_resp = aws_client.s3tables.list_table_buckets()
        arns = [b["arn"] for b in list_resp["tableBuckets"]]
        assert arn in arns

        aws_client.s3tables.delete_table_bucket(tableBucketARN=arn)

    @markers.aws.unknown
    def test_create_duplicate_table_bucket_fails(self, aws_client):
        name = "dup-test-bucket"
        aws_client.s3tables.create_table_bucket(name=name)
        arn = f"arn:aws:s3tables:us-east-1:000000000000:bucket/{name}"

        with pytest.raises(Exception):
            aws_client.s3tables.create_table_bucket(name=name)

        aws_client.s3tables.delete_table_bucket(tableBucketARN=arn)

    @markers.aws.unknown
    def test_delete_nonexistent_table_bucket_fails(self, aws_client):
        with pytest.raises(Exception):
            aws_client.s3tables.delete_table_bucket(
                tableBucketARN="arn:aws:s3tables:us-east-1:000000000000:bucket/nope"
            )


class TestS3TablesNamespace:
    @markers.aws.unknown
    def test_create_and_get_namespace(self, aws_client):
        bucket = aws_client.s3tables.create_table_bucket(name="ns-test-bucket")
        arn = bucket["arn"]

        ns_resp = aws_client.s3tables.create_namespace(
            tableBucketARN=arn, namespace=["test_ns"]
        )
        assert ns_resp["namespace"] == ["test_ns"]

        get_resp = aws_client.s3tables.get_namespace(
            tableBucketARN=arn, namespace="test_ns"
        )
        assert get_resp["namespace"] == ["test_ns"]

        aws_client.s3tables.delete_namespace(tableBucketARN=arn, namespace="test_ns")
        aws_client.s3tables.delete_table_bucket(tableBucketARN=arn)


class TestS3TablesTable:
    @markers.aws.unknown
    def test_create_and_get_table(self, aws_client):
        bucket = aws_client.s3tables.create_table_bucket(name="tbl-test-bucket")
        arn = bucket["arn"]
        aws_client.s3tables.create_namespace(tableBucketARN=arn, namespace=["test_ns"])

        tbl_resp = aws_client.s3tables.create_table(
            tableBucketARN=arn,
            namespace="test_ns",
            name="sessions",
            format="ICEBERG",
        )
        assert tbl_resp["tableARN"]
        assert tbl_resp["versionToken"]

        get_resp = aws_client.s3tables.get_table(
            tableBucketARN=arn, namespace="test_ns", name="sessions"
        )
        assert get_resp["name"] == "sessions"
        assert get_resp["format"] == "ICEBERG"
        assert get_resp["metadataLocation"]  # should be Nessie endpoint

        # Cleanup
        aws_client.s3tables.delete_table(
            tableBucketARN=arn, namespace="test_ns", name="sessions"
        )
        aws_client.s3tables.delete_namespace(tableBucketARN=arn, namespace="test_ns")
        aws_client.s3tables.delete_table_bucket(tableBucketARN=arn)
```

**Step 2: Run the tests**

Run: `cd /Users/wbetts/src/github/localstack && python -m pytest tests/aws/services/s3tables/test_s3tables.py -v --tb=short`
Expected: All tests PASS (requires LocalStack running with Docker access for Nessie)

Note: The first run will be slow (~30-60s) as Nessie image is pulled and started. Subsequent runs reuse the running container.

**Step 3: Commit**

```bash
git add tests/aws/services/s3tables/test_s3tables.py
git commit -m "test(s3tables): add integration tests for table bucket, namespace, and table CRUD"
```

---

### Task 7: Push to Fork

**Step 1: Create feature branch and push**

```bash
cd /Users/wbetts/src/github/localstack
git checkout -b feat/s3tables-provider
git push -u fork feat/s3tables-provider
```

---

### Post-Implementation Verification

After all tasks are complete, verify the full roundtrip:

1. Start LocalStack with the new service
2. `aws --endpoint-url=http://localhost:4566 s3tables create-table-bucket --name test` — should succeed and start Nessie
3. `aws --endpoint-url=http://localhost:4566 s3tables create-namespace --table-bucket-arn <arn> --namespace test_ns` — should succeed
4. `aws --endpoint-url=http://localhost:4566 s3tables create-table --table-bucket-arn <arn> --namespace test_ns --name sessions --format ICEBERG` — should succeed
5. DuckDB `ATTACH TYPE ICEBERG` to the Nessie endpoint from step 3's response — should connect
6. `CREATE TABLE`, `INSERT`, `SELECT` through DuckDB — full roundtrip
