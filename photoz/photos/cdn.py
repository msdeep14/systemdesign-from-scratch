import logging
import time

import boto3
from botocore.exceptions import ClientError
from django.conf import settings

logger = logging.getLogger("bses")


def invalidate_cache(path):
    distribution_id = getattr(settings, "CLOUDFRONT_DISTRIBUTION_ID", None)
    if not distribution_id:
        return

    try:
        client = boto3.client("cloudfront")
        client.create_invalidation(
            DistributionId=distribution_id,
            InvalidationBatch={
                "Paths": {"Quantity": 1, "Items": [f"/{path}"]},
                "CallerReference": f"invalidate-{int(time.time())}",
            },
        )
        logger.info(f"CloudFront invalidation created for /{path}")
    except ClientError as e:
        logger.error(f"CloudFront invalidation failed for /{path}: {e}")
