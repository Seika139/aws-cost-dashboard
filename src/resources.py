"""AWS リソース情報の取得。各アカウントの EC2 / ECS / RDS / S3 / ElastiCache を取得."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from src.auth import get_role_credentials
from src.cache import get_cached, get_resource_snapshot, set_cached, set_resource_snapshot
from src.cost import _pick_cost_role, get_account_cost
from src.pricing import enrich_resources_with_pricing

logger = logging.getLogger(__name__)

RESOURCE_SERVICES = {
    "Amazon Elastic Compute Cloud - Compute": "ec2",
    "Amazon Elastic Container Service": "ecs",
    "Amazon Relational Database Service": "rds",
    "Amazon Simple Storage Service": "s3",
    "Amazon ElastiCache": "elasticache",
}


def _make_client(service_name: str, creds: dict, region: str):
    return boto3.client(service_name, region_name=region, **creds)


# ============================================================
# リージョン判定
# ============================================================


def get_active_regions(account_id: str) -> list[str]:
    """Cost Explorer の REGION グルーピングでコスト実績のあるリージョンを返す."""
    today = date.today()
    start = today.replace(day=1).isoformat()
    if today.month == 12:
        end = date(today.year + 1, 1, 1).isoformat()
    else:
        end = date(today.year, today.month + 1, 1).isoformat()

    cost_data = get_account_cost(account_id, start, end, granularity="MONTHLY", group_by="REGION")
    if cost_data is None:
        return []

    regions = set()
    for period in cost_data.get("results", []):
        for group in period.get("Groups", []):
            region = group["Keys"][0]
            if not region or region in ("global", "NoRegion") or region.startswith("No "):
                continue
            metrics = group.get("Metrics", {})
            amount = float(metrics.get("UnblendedCost", {}).get("Amount", "0"))
            if amount > 0:
                regions.add(region)
    return sorted(regions)


# ============================================================
# 各サービスの fetcher
# ============================================================


def _fetch_ec2(creds: dict, region: str) -> list[dict]:
    ec2 = _make_client("ec2", creds, region)
    instances = []
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate():
        for res in page["Reservations"]:
            for i in res["Instances"]:
                name = ""
                for tag in i.get("Tags", []):
                    if tag["Key"] == "Name":
                        name = tag["Value"]
                        break
                instances.append(
                    {
                        "instanceId": i["InstanceId"],
                        "instanceType": i["InstanceType"],
                        "state": i["State"]["Name"],
                        "name": name,
                        "launchTime": i.get("LaunchTime", "").isoformat() if i.get("LaunchTime") else "",
                        "privateIp": i.get("PrivateIpAddress", ""),
                        "platform": i.get("PlatformDetails", ""),
                        "region": region,
                    }
                )
    return instances


def _fetch_ecs(creds: dict, region: str) -> list[dict]:
    ecs = _make_client("ecs", creds, region)
    cluster_arns = []
    paginator = ecs.get_paginator("list_clusters")
    for page in paginator.paginate():
        cluster_arns.extend(page["clusterArns"])
    if not cluster_arns:
        return []

    services = []
    clusters = ecs.describe_clusters(clusters=cluster_arns)["clusters"]
    for cluster in clusters:
        cluster_name = cluster["clusterName"]
        svc_arns = []
        svc_pager = ecs.get_paginator("list_services")
        for page in svc_pager.paginate(cluster=cluster_name):
            svc_arns.extend(page["serviceArns"])
        if not svc_arns:
            continue
        for i in range(0, len(svc_arns), 10):
            batch = svc_arns[i : i + 10]
            desc = ecs.describe_services(cluster=cluster_name, services=batch)
            for svc in desc["services"]:
                services.append(
                    {
                        "clusterName": cluster_name,
                        "serviceName": svc["serviceName"],
                        "runningCount": svc.get("runningCount", 0),
                        "desiredCount": svc.get("desiredCount", 0),
                        "launchType": svc.get("launchType", ""),
                        "status": svc.get("status", ""),
                        "region": region,
                    }
                )
    return services


def _fetch_rds(creds: dict, region: str) -> list[dict]:
    rds = _make_client("rds", creds, region)
    instances = []
    paginator = rds.get_paginator("describe_db_instances")
    for page in paginator.paginate():
        for db in page["DBInstances"]:
            instances.append(
                {
                    "dbInstanceId": db["DBInstanceIdentifier"],
                    "engine": db["Engine"],
                    "engineVersion": db.get("EngineVersion", ""),
                    "instanceClass": db["DBInstanceClass"],
                    "status": db["DBInstanceStatus"],
                    "multiAz": db.get("MultiAZ", False),
                    "storageGb": db.get("AllocatedStorage", 0),
                    "region": region,
                }
            )
    return instances


def _fetch_s3(creds: dict) -> list[dict]:
    s3 = _make_client("s3", creds, "us-east-1")
    resp = s3.list_buckets()
    buckets = []
    for b in resp.get("Buckets", []):
        bucket_name = b["Name"]
        try:
            loc = s3.get_bucket_location(Bucket=bucket_name)
            region = loc.get("LocationConstraint") or "us-east-1"
        except ClientError:
            region = "unknown"
        buckets.append(
            {
                "bucketName": bucket_name,
                "creationDate": b.get("CreationDate", "").isoformat() if b.get("CreationDate") else "",
                "region": region,
            }
        )
    return buckets


def _fetch_elasticache(creds: dict, region: str) -> list[dict]:
    ec = _make_client("elasticache", creds, region)
    clusters = []
    paginator = ec.get_paginator("describe_cache_clusters")
    for page in paginator.paginate():
        for c in page["CacheClusters"]:
            clusters.append(
                {
                    "clusterId": c["CacheClusterId"],
                    "engine": c.get("Engine", ""),
                    "engineVersion": c.get("EngineVersion", ""),
                    "nodeType": c.get("CacheNodeType", ""),
                    "numNodes": c.get("NumCacheNodes", 0),
                    "status": c.get("CacheClusterStatus", ""),
                    "region": region,
                }
            )
    return clusters


_FETCHERS = {
    "ec2": _fetch_ec2,
    "ecs": _fetch_ecs,
    "rds": _fetch_rds,
    "elasticache": _fetch_elasticache,
}

_GLOBAL_FETCHERS = {
    "s3": _fetch_s3,
}

_MAX_REGION_WORKERS = 8


def _fetch_regions_parallel(fetcher, creds: dict, regions: list[str], account_id: str, svc: str) -> list[dict]:
    """複数リージョンを並列に取得する."""
    if not regions:
        return []
    results = []
    with ThreadPoolExecutor(max_workers=min(_MAX_REGION_WORKERS, len(regions))) as pool:
        future_to_region = {pool.submit(fetcher, creds, r): r for r in regions}
        for future in as_completed(future_to_region):
            region = future_to_region[future]
            try:
                results.extend(future.result())
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code", "")
                if code in (
                    "AccessDeniedException",
                    "UnauthorizedAccess",
                    "AccessDenied",
                    "AuthFailure",
                    "InvalidClientTokenId",
                ):
                    logger.info("Access denied for %s/%s in %s — skipping", account_id, svc, region)
                else:
                    logger.warning("Error fetching %s for %s in %s: %s", svc, account_id, region, e)
    return results


# ============================================================
# オーケストレーション
# ============================================================


RESOURCE_ID_PREFIX_MAP = {
    "i-": "ec2",
    "arn:aws:ecs:": "ecs",
    "arn:aws:rds:": "rds",
    "arn:aws:s3": "s3",
    "arn:aws:elasticache:": "elasticache",
}


def _get_actual_costs(account_id: str, role_name: str) -> dict[str, float]:
    """GetCostAndUsageWithResources でリソース別コストを一括取得。

    API は最大14日間の制約があるため、月初 or 14日前の近い方を起点にする。
    Returns: { resource_id: total_cost_usd }
    """
    today = date.today()
    month_start = today.replace(day=1)
    max_lookback = today - timedelta(days=14)
    start = max(month_start, max_lookback).isoformat()
    end = today.isoformat()

    cache_key = f"actual_cost:{account_id}:{start}:{end}"
    cached = get_cached(cache_key, max_age_hours=24)
    if cached is not None:
        return cached

    try:
        creds = get_role_credentials(account_id, role_name)
        ce = boto3.client("ce", region_name="us-east-1", **creds)
        results = []
        kwargs = {
            "TimePeriod": {"Start": start, "End": end},
            "Granularity": "DAILY",
            "Metrics": ["UnblendedCost"],
            "GroupBy": [{"Type": "DIMENSION", "Key": "RESOURCE_ID"}],
            "Filter": {
                "Dimensions": {
                    "Key": "SERVICE",
                    "Values": list(RESOURCE_SERVICES.keys()),
                }
            },
        }
        while True:
            resp = ce.get_cost_and_usage_with_resources(**kwargs)
            results.extend(resp.get("ResultsByTime", []))
            if "NextPageToken" in resp:
                kwargs["NextPageToken"] = resp["NextPageToken"]
            else:
                break

        cost_map = {}
        for period in results:
            for group in period.get("Groups", []):
                resource_id = group["Keys"][0]
                amount = float(group.get("Metrics", {}).get("UnblendedCost", {}).get("Amount", "0"))
                cost_map[resource_id] = cost_map.get(resource_id, 0) + amount

        set_cached(cache_key, cost_map)
        return cost_map
    except Exception:
        logger.exception("Failed to get actual costs for account %s", account_id)
        return {}


def _match_resource_cost(resource: dict, service: str, cost_map: dict[str, float]) -> float | None:
    """リソースに対応する Actual Cost を cost_map から検索."""
    id_keys = {
        "ec2": "instanceId",
        "rds": "dbInstanceId",
        "elasticache": "clusterId",
        "s3": "bucketName",
        "ecs": "serviceName",
    }
    key_field = id_keys.get(service)
    if not key_field:
        return None
    resource_id = resource.get(key_field, "")
    if not resource_id:
        return None

    if resource_id in cost_map:
        return cost_map[resource_id]

    for cost_key, cost_val in cost_map.items():
        if resource_id in cost_key:
            return cost_val
    return None


def _enrich_with_actual_costs(service: str, resources: list[dict], cost_map: dict[str, float]) -> None:
    """リソース一覧に Actual MTD コストを付与."""
    for r in resources:
        actual = _match_resource_cost(r, service, cost_map)
        r["actualCost"] = round(actual, 2) if actual is not None else None


def get_account_resources(account_id: str, service: str | None = None) -> dict:
    """アカウントのリソース情報を取得。日次スナップショットとしてキャッシュする."""
    today = date.today().isoformat()

    target_services = [service] if service else list(RESOURCE_SERVICES.values())
    result = {"accountId": account_id, "services": {}, "fetchedAt": datetime.now(timezone.utc).isoformat()}

    role_name = _pick_cost_role(account_id)
    if role_name is None:
        logger.warning("No role available for account %s", account_id)
        return result

    try:
        creds = get_role_credentials(account_id, role_name)
    except Exception:
        logger.exception("Failed to get credentials for account %s", account_id)
        return result

    regions = get_active_regions(account_id)
    cost_map = _get_actual_costs(account_id, role_name)

    for svc in target_services:
        from_cache = False
        cached = get_resource_snapshot(account_id, svc, today)
        if cached is not None:
            resources = cached
            from_cache = True
        else:
            resources = []
            try:
                if svc in _GLOBAL_FETCHERS:
                    resources = _GLOBAL_FETCHERS[svc](creds)
                elif svc in _FETCHERS:
                    resources = _fetch_regions_parallel(_FETCHERS[svc], creds, regions, account_id, svc)
            except Exception:
                logger.exception("Failed to fetch %s for account %s", svc, account_id)
            set_resource_snapshot(account_id, svc, today, resources)

        if resources and svc in ("ec2", "rds", "elasticache"):
            enrich_resources_with_pricing(svc, resources, creds)
        if resources:
            _enrich_with_actual_costs(svc, resources, cost_map)

        result["services"][svc] = {"resources": resources, "count": len(resources), "fromCache": from_cache}

    return result
