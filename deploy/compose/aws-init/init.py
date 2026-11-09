"""Create local S3 bucket and SQS queues (with DLQs) in moto. Idempotent."""

from __future__ import annotations

import contextlib
import json
import os

import boto3

REGION = os.environ.get("BOMAGENT_AWS_REGION", "eu-central-1")
ENDPOINT = os.environ["BOMAGENT_AWS_ENDPOINT_URL"]
BUCKETS = ["bomagent-local-files", "langfuse"]
QUEUES = ["ingest", "runs", "kb"]


def main() -> None:
    s3 = boto3.client("s3", region_name=REGION, endpoint_url=ENDPOINT)
    for bucket in BUCKETS:
        with contextlib.suppress(s3.exceptions.BucketAlreadyOwnedByYou):
            s3.create_bucket(
                Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": REGION}
            )
    sqs = boto3.client("sqs", region_name=REGION, endpoint_url=ENDPOINT)
    for name in QUEUES:
        dlq_url = sqs.create_queue(QueueName=f"{name}-dlq")["QueueUrl"]
        dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])[
            "Attributes"
        ]["QueueArn"]
        sqs.create_queue(
            QueueName=name,
            Attributes={
                "VisibilityTimeout": "900",
                "RedrivePolicy": json.dumps(
                    {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "3"}
                ),
            },
        )
    print("aws-init: buckets and queues ready")  # noqa: T201


if __name__ == "__main__":
    main()
