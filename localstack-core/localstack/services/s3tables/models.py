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


s3tables_stores = AccountRegionBundle("s3tables", S3TablesStore, validate=False)
