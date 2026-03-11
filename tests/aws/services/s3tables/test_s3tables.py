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
