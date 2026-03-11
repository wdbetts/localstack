"""Hand-written API types for S3 Tables service.

No Botocore service model exists in this codebase, so these are written
from the AWS S3 Tables API documentation and Terraform provider source.
"""

import datetime
from enum import StrEnum
from typing import TypedDict

from localstack.aws.api import RequestContext, ServiceException, ServiceRequest, handler


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

class NotFoundException(ServiceException):
    code: str = "NotFoundException"
    sender_fault: bool = False
    status_code: int = 404


class ConflictException(ServiceException):
    code: str = "ConflictException"
    sender_fault: bool = False
    status_code: int = 409


class BadRequestException(ServiceException):
    code: str = "BadRequestException"
    sender_fault: bool = True
    status_code: int = 400


# --- Abstract API class ---

class S3TablesApi:
    service = "s3tables"
    version = "2018-05-10"

    @handler("CreateTableBucket")
    def create_table_bucket(
        self, context: RequestContext, name: str, **kwargs
    ) -> CreateTableBucketResponse:
        raise NotImplementedError

    @handler("GetTableBucket")
    def get_table_bucket(
        self, context: RequestContext, table_bucket_arn: str, **kwargs
    ) -> GetTableBucketResponse:
        raise NotImplementedError

    @handler("ListTableBuckets")
    def list_table_buckets(
        self, context: RequestContext, **kwargs
    ) -> ListTableBucketsResponse:
        raise NotImplementedError

    @handler("DeleteTableBucket")
    def delete_table_bucket(
        self, context: RequestContext, table_bucket_arn: str, **kwargs
    ) -> None:
        raise NotImplementedError

    @handler("CreateNamespace")
    def create_namespace(
        self, context: RequestContext, table_bucket_arn: str, namespace: list[str], **kwargs
    ) -> CreateNamespaceResponse:
        raise NotImplementedError

    @handler("GetNamespace")
    def get_namespace(
        self, context: RequestContext, table_bucket_arn: str, namespace: str, **kwargs
    ) -> GetNamespaceResponse:
        raise NotImplementedError

    @handler("ListNamespaces")
    def list_namespaces(
        self, context: RequestContext, table_bucket_arn: str, **kwargs
    ) -> ListNamespacesResponse:
        raise NotImplementedError

    @handler("DeleteNamespace")
    def delete_namespace(
        self, context: RequestContext, table_bucket_arn: str, namespace: str, **kwargs
    ) -> None:
        raise NotImplementedError

    @handler("CreateTable")
    def create_table(
        self, context: RequestContext, table_bucket_arn: str, namespace: str, name: str, format: OpenTableFormat, **kwargs
    ) -> CreateTableResponse:
        raise NotImplementedError

    @handler("GetTable")
    def get_table(
        self, context: RequestContext, table_bucket_arn: str, namespace: str, name: str, **kwargs
    ) -> GetTableResponse:
        raise NotImplementedError

    @handler("ListTables")
    def list_tables(
        self, context: RequestContext, table_bucket_arn: str, **kwargs
    ) -> ListTablesResponse:
        raise NotImplementedError

    @handler("DeleteTable")
    def delete_table(
        self, context: RequestContext, table_bucket_arn: str, namespace: str, name: str, **kwargs
    ) -> None:
        raise NotImplementedError

    @handler("UpdateTableMetadataLocation")
    def update_table_metadata_location(
        self, context: RequestContext, table_bucket_arn: str, namespace: str, name: str,
        version_token: str, metadata_location: str, **kwargs
    ) -> UpdateTableMetadataLocationResponse:
        raise NotImplementedError
