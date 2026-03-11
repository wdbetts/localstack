import logging
import threading
import uuid
from datetime import UTC, datetime

import requests

from localstack.aws.api import RequestContext, handler
from localstack.aws.api.s3tables import (
    BadRequestException,
    ConflictException,
    NotFoundException,
    OpenTableFormat,
    S3TablesApi,
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


def _iso(dt: datetime) -> str:
    return dt.isoformat() if dt else ""


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
    def create_table_bucket(self, context: RequestContext, name: str, **kwargs):
        store = self.get_store(context.account_id, context.region)
        arn = _table_bucket_arn(context.account_id, context.region, name)

        with _mutex:
            if arn in store.table_buckets:
                raise ConflictException(f"Table bucket {name} already exists")

            nessie_manager().start()

            store.table_buckets[arn] = TableBucketMetadata(
                arn=arn,
                name=name,
                owner_account_id=context.account_id,
                created_at=datetime.now(UTC),
                s3_bucket_name=f"s3tables-{name}-{context.account_id}",
            )

        return {"arn": arn}

    @handler("GetTableBucket")
    def get_table_bucket(self, context: RequestContext, table_bucket_arn: str, **kwargs):
        store = self.get_store(context.account_id, context.region)
        meta = store.table_buckets.get(table_bucket_arn)
        if not meta:
            raise NotFoundException(f"Table bucket not found: {table_bucket_arn}")

        return {
            "arn": meta.arn,
            "name": meta.name,
            "ownerAccountId": meta.owner_account_id,
            "createdAt": meta.created_at,
        }

    @handler("ListTableBuckets")
    def list_table_buckets(self, context: RequestContext, **kwargs):
        store = self.get_store(context.account_id, context.region)
        return {
            "tableBuckets": [
                {
                    "arn": m.arn,
                    "name": m.name,
                    "ownerAccountId": m.owner_account_id,
                    "createdAt": m.created_at,
                }
                for m in store.table_buckets.values()
            ]
        }

    @handler("DeleteTableBucket")
    def delete_table_bucket(self, context: RequestContext, table_bucket_arn: str, **kwargs):
        store = self.get_store(context.account_id, context.region)
        with _mutex:
            if table_bucket_arn not in store.table_buckets:
                raise NotFoundException(f"Table bucket not found: {table_bucket_arn}")

            remaining = [k for k in store.namespaces if k.startswith(table_bucket_arn)]
            if remaining:
                raise ConflictException("Table bucket is not empty — delete namespaces first")

            del store.table_buckets[table_bucket_arn]

    # --- Namespace operations ---

    @handler("CreateNamespace")
    def create_namespace(
        self, context: RequestContext, table_bucket_arn: str, namespace: list[str], **kwargs
    ):
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

            endpoint = nessie_manager().endpoint
            resp = requests.post(
                f"{endpoint}v1/namespaces",
                json={"namespace": [ns_name]},
                timeout=10,
            )
            if resp.status_code not in (200, 409):
                LOG.error("Nessie create namespace failed: %s %s", resp.status_code, resp.text)

            store.namespaces[key] = NamespaceMetadata(
                namespace=namespace,
                table_bucket_arn=table_bucket_arn,
                created_at=datetime.now(UTC),
                created_by=context.account_id,
                owner_account_id=context.account_id,
            )

        return {
            "tableBucketARN": table_bucket_arn,
            "namespace": namespace,
        }

    @handler("GetNamespace")
    def get_namespace(
        self, context: RequestContext, table_bucket_arn: str, namespace: str, **kwargs
    ):
        store = self.get_store(context.account_id, context.region)
        key = _namespace_key(table_bucket_arn, namespace)
        meta = store.namespaces.get(key)
        if not meta:
            raise NotFoundException(f"Namespace not found: {namespace}")

        return {
            "namespace": meta.namespace,
            "createdAt": meta.created_at,
            "createdBy": meta.created_by,
            "ownerAccountId": meta.owner_account_id,
        }

    @handler("ListNamespaces")
    def list_namespaces(self, context: RequestContext, table_bucket_arn: str, **kwargs):
        store = self.get_store(context.account_id, context.region)
        return {
            "namespaces": [
                {
                    "namespace": m.namespace,
                    "createdAt": m.created_at,
                    "createdBy": m.created_by,
                    "ownerAccountId": m.owner_account_id,
                }
                for k, m in store.namespaces.items()
                if k.startswith(table_bucket_arn)
            ]
        }

    @handler("DeleteNamespace")
    def delete_namespace(
        self, context: RequestContext, table_bucket_arn: str, namespace: str, **kwargs
    ):
        store = self.get_store(context.account_id, context.region)
        key = _namespace_key(table_bucket_arn, namespace)

        with _mutex:
            if key not in store.namespaces:
                raise NotFoundException(f"Namespace not found: {namespace}")

            remaining = [k for k in store.tables if k.startswith(f"{table_bucket_arn}|{namespace}|")]
            if remaining:
                raise ConflictException("Namespace is not empty — delete tables first")

            endpoint = nessie_manager().endpoint
            requests.delete(f"{endpoint}v1/namespaces/{namespace}", timeout=10)

            del store.namespaces[key]

    # --- Table operations ---

    @handler("CreateTable")
    def create_table(
        self, context: RequestContext, table_bucket_arn: str, namespace: str,
        name: str, format: OpenTableFormat, **kwargs
    ):
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

        return {"tableARN": table_arn, "versionToken": version_token}

    @handler("GetTable")
    def get_table(
        self, context: RequestContext, table_bucket_arn: str, namespace: str,
        name: str, **kwargs
    ):
        store = self.get_store(context.account_id, context.region)
        tbl_key = _table_key(table_bucket_arn, namespace, name)
        meta = store.tables.get(tbl_key)
        if not meta:
            raise NotFoundException(f"Table not found: {namespace}/{name}")

        return {
            "name": meta.name,
            "type": "customer",
            "tableARN": meta.table_arn,
            "namespace": meta.namespace,
            "versionToken": meta.version_token,
            "metadataLocation": meta.metadata_location or "",
            "warehouseLocation": meta.warehouse_location,
            "createdAt": meta.created_at,
            "createdBy": meta.created_by,
            "modifiedAt": meta.modified_at,
            "modifiedBy": meta.modified_by,
            "ownerAccountId": meta.owner_account_id,
            "format": meta.format,
        }

    @handler("ListTables")
    def list_tables(self, context: RequestContext, table_bucket_arn: str, **kwargs):
        store = self.get_store(context.account_id, context.region)
        namespace_filter = kwargs.get("namespace")
        prefix = f"{table_bucket_arn}|"
        if namespace_filter:
            prefix = f"{table_bucket_arn}|{namespace_filter}|"

        return {
            "tables": [
                {
                    "namespace": m.namespace,
                    "name": m.name,
                    "type": "customer",
                    "tableARN": m.table_arn,
                    "createdAt": m.created_at,
                    "modifiedAt": m.modified_at,
                }
                for k, m in store.tables.items()
                if k.startswith(prefix)
            ]
        }

    @handler("DeleteTable")
    def delete_table(
        self, context: RequestContext, table_bucket_arn: str, namespace: str,
        name: str, **kwargs
    ):
        store = self.get_store(context.account_id, context.region)
        tbl_key = _table_key(table_bucket_arn, namespace, name)

        with _mutex:
            if tbl_key not in store.tables:
                raise NotFoundException(f"Table not found: {namespace}/{name}")

            endpoint = nessie_manager().endpoint
            requests.delete(f"{endpoint}v1/namespaces/{namespace}/tables/{name}", timeout=10)

            del store.tables[tbl_key]

    @handler("UpdateTableMetadataLocation")
    def update_table_metadata_location(
        self, context: RequestContext, table_bucket_arn: str, namespace: str,
        name: str, version_token: str, metadata_location: str, **kwargs
    ):
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

        return {
            "name": meta.name,
            "tableARN": meta.table_arn,
            "namespace": meta.namespace,
            "versionToken": new_token,
            "metadataLocation": metadata_location,
        }

    # --- Configuration read operations (required by Terraform) ---

    @handler("GetTableBucketMaintenanceConfiguration")
    def get_table_bucket_maintenance_configuration(
        self, context: RequestContext, table_bucket_arn: str, **kwargs
    ):
        store = self.get_store(context.account_id, context.region)
        if table_bucket_arn not in store.table_buckets:
            raise NotFoundException(f"Table bucket not found: {table_bucket_arn}")
        return {
            "tableBucketARN": table_bucket_arn,
            "configuration": {
                "icebergUnreferencedFileRemoval": {
                    "status": "enabled",
                    "settings": {
                        "icebergUnreferencedFileRemoval": {
                            "unreferencedDays": 30,
                            "nonCurrentDays": 30,
                        }
                    },
                },
            },
        }

    @handler("GetTableBucketEncryption")
    def get_table_bucket_encryption(
        self, context: RequestContext, table_bucket_arn: str, **kwargs
    ):
        store = self.get_store(context.account_id, context.region)
        if table_bucket_arn not in store.table_buckets:
            raise NotFoundException(f"Table bucket not found: {table_bucket_arn}")
        return {
            "encryptionConfiguration": {
                "sseAlgorithm": "AES256",
            },
        }

    @handler("GetTableMaintenanceConfiguration")
    def get_table_maintenance_configuration(
        self, context: RequestContext, table_bucket_arn: str, namespace: str, name: str, **kwargs
    ):
        store = self.get_store(context.account_id, context.region)
        tbl_key = _table_key(table_bucket_arn, namespace, name)
        meta = store.tables.get(tbl_key)
        if not meta:
            raise NotFoundException(f"Table not found: {namespace}/{name}")
        return {
            "tableARN": meta.table_arn,
            "configuration": {
                "icebergCompaction": {
                    "status": "enabled",
                    "settings": {
                        "icebergCompaction": {
                            "targetFileSizeMB": 512,
                            "strategy": "binpack",
                        }
                    },
                },
                "icebergSnapshotManagement": {
                    "status": "enabled",
                    "settings": {
                        "icebergSnapshotManagement": {
                            "minSnapshotsToKeep": 1,
                            "maxSnapshotAgeHours": 72,
                        }
                    },
                },
            },
        }

    @handler("GetTableMaintenanceJobStatus")
    def get_table_maintenance_job_status(
        self, context: RequestContext, table_bucket_arn: str, namespace: str, name: str, **kwargs
    ):
        store = self.get_store(context.account_id, context.region)
        tbl_key = _table_key(table_bucket_arn, namespace, name)
        meta = store.tables.get(tbl_key)
        if not meta:
            raise NotFoundException(f"Table not found: {namespace}/{name}")
        return {
            "tableARN": meta.table_arn,
            "status": {},
        }

    @handler("GetTableEncryption")
    def get_table_encryption(
        self, context: RequestContext, table_bucket_arn: str, namespace: str, name: str, **kwargs
    ):
        store = self.get_store(context.account_id, context.region)
        tbl_key = _table_key(table_bucket_arn, namespace, name)
        meta = store.tables.get(tbl_key)
        if not meta:
            raise NotFoundException(f"Table not found: {namespace}/{name}")
        return {
            "encryptionConfiguration": {
                "sseAlgorithm": "AES256",
            },
        }

    @handler("ListTagsForResource")
    def list_tags_for_resource(self, context: RequestContext, resource_arn: str, **kwargs):
        return {"tags": {}}

    @handler("GetTableMetadataLocation")
    def get_table_metadata_location(
        self, context: RequestContext, table_bucket_arn: str, namespace: str, name: str, **kwargs
    ):
        store = self.get_store(context.account_id, context.region)
        tbl_key = _table_key(table_bucket_arn, namespace, name)
        meta = store.tables.get(tbl_key)
        if not meta:
            raise NotFoundException(f"Table not found: {namespace}/{name}")
        return {
            "versionToken": meta.version_token,
            "metadataLocation": meta.metadata_location or "",
            "warehouseLocation": meta.warehouse_location,
        }
