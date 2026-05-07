"""AWS Price List API ラッパー。On-Demand 単価を取得."""

import json
import logging

import boto3
from botocore.config import Config

from src.cache import get_cached, set_cached

logger = logging.getLogger(__name__)

PRICING_CACHE_TTL_HOURS = 168  # 7 days

# リージョンコード → Price List API の location 名
REGION_LOCATION_MAP = {
    "us-east-1": "US East (N. Virginia)",
    "us-east-2": "US East (Ohio)",
    "us-west-1": "US West (N. California)",
    "us-west-2": "US West (Oregon)",
    "ap-northeast-1": "Asia Pacific (Tokyo)",
    "ap-northeast-2": "Asia Pacific (Seoul)",
    "ap-northeast-3": "Asia Pacific (Osaka)",
    "ap-southeast-1": "Asia Pacific (Singapore)",
    "ap-southeast-2": "Asia Pacific (Sydney)",
    "ap-south-1": "Asia Pacific (Mumbai)",
    "eu-west-1": "EU (Ireland)",
    "eu-west-2": "EU (London)",
    "eu-west-3": "EU (Paris)",
    "eu-central-1": "EU (Frankfurt)",
    "eu-north-1": "EU (Stockholm)",
    "sa-east-1": "South America (Sao Paulo)",
    "ca-central-1": "Canada (Central)",
}


_PRICING_CONFIG = Config(
    retries={"max_attempts": 5, "mode": "standard"},
    connect_timeout=10,
    read_timeout=30,
)


def _get_pricing_client(creds: dict):
    return boto3.client("pricing", region_name="us-east-1", config=_PRICING_CONFIG, **creds)


def _extract_ondemand_price(price_item: dict) -> float | None:
    """Price List の1アイテムから On-Demand USD 単価を抽出."""
    terms = price_item.get("terms", {}).get("OnDemand", {})
    for term in terms.values():
        for dim in term.get("priceDimensions", {}).values():
            usd = dim.get("pricePerUnit", {}).get("USD")
            if usd:
                price = float(usd)
                if price > 0:
                    return price
    return None


def _extract_price_unit(price_item: dict) -> str:
    """Price List の1アイテムから単位を抽出."""
    terms = price_item.get("terms", {}).get("OnDemand", {})
    for term in terms.values():
        for dim in term.get("priceDimensions", {}).values():
            return dim.get("unit", "Hrs")
    return "Hrs"


def get_ec2_ondemand_price(instance_type: str, region: str, platform: str = "Linux", *, creds: dict) -> dict | None:
    """EC2 インスタンスの On-Demand 時間単価を取得."""
    cache_key = f"pricing:ec2:{instance_type}:{region}:{platform}"
    cached = get_cached(cache_key, max_age_hours=PRICING_CACHE_TTL_HOURS)
    if cached is not None:
        return cached

    location = REGION_LOCATION_MAP.get(region)
    if not location:
        return None

    os_map = {"Linux": "Linux", "Windows": "Windows", "linux": "Linux", "windows": "Windows"}
    os_filter = os_map.get(platform, "Linux")
    if "linux" in platform.lower():
        os_filter = "Linux"
    elif "windows" in platform.lower():
        os_filter = "Windows"

    try:
        client = _get_pricing_client(creds)
        resp = client.get_products(
            ServiceCode="AmazonEC2",
            Filters=[
                {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
                {"Type": "TERM_MATCH", "Field": "location", "Value": location},
                {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": os_filter},
                {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
                {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
                {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
            ],
            MaxResults=1,
        )
        if not resp.get("PriceList"):
            return None
        item = json.loads(resp["PriceList"][0])
        price = _extract_ondemand_price(item)
        if price is None:
            return None
        result = {"price": price, "unit": "Hrs", "currency": "USD"}
        set_cached(cache_key, result)
        return result
    except Exception:
        logger.exception("Failed to get EC2 pricing for %s in %s", instance_type, region)
        return None


def get_rds_ondemand_price(instance_class: str, engine: str, region: str, *, creds: dict) -> dict | None:
    """RDS インスタンスの On-Demand 時間単価を取得."""
    cache_key = f"pricing:rds:{instance_class}:{engine}:{region}"
    cached = get_cached(cache_key, max_age_hours=PRICING_CACHE_TTL_HOURS)
    if cached is not None:
        return cached

    location = REGION_LOCATION_MAP.get(region)
    if not location:
        return None

    engine_map = {
        "mysql": "MySQL",
        "postgres": "PostgreSQL",
        "mariadb": "MariaDB",
        "oracle-ee": "Oracle",
        "oracle-se2": "Oracle",
        "sqlserver-ee": "SQL Server",
        "sqlserver-se": "SQL Server",
        "sqlserver-ex": "SQL Server",
        "sqlserver-web": "SQL Server",
        "aurora-mysql": "Aurora MySQL",
        "aurora-postgresql": "Aurora PostgreSQL",
    }
    db_engine = engine_map.get(engine.lower(), engine)

    try:
        client = _get_pricing_client(creds)
        resp = client.get_products(
            ServiceCode="AmazonRDS",
            Filters=[
                {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_class},
                {"Type": "TERM_MATCH", "Field": "location", "Value": location},
                {"Type": "TERM_MATCH", "Field": "databaseEngine", "Value": db_engine},
                {"Type": "TERM_MATCH", "Field": "deploymentOption", "Value": "Single-AZ"},
            ],
            MaxResults=1,
        )
        if not resp.get("PriceList"):
            return None
        item = json.loads(resp["PriceList"][0])
        price = _extract_ondemand_price(item)
        if price is None:
            return None
        result = {"price": price, "unit": "Hrs", "currency": "USD"}
        set_cached(cache_key, result)
        return result
    except Exception:
        logger.exception("Failed to get RDS pricing for %s (%s) in %s", instance_class, engine, region)
        return None


def get_elasticache_ondemand_price(node_type: str, engine: str, region: str, *, creds: dict) -> dict | None:
    """ElastiCache ノードの On-Demand 時間単価を取得."""
    cache_key = f"pricing:elasticache:{node_type}:{engine}:{region}"
    cached = get_cached(cache_key, max_age_hours=PRICING_CACHE_TTL_HOURS)
    if cached is not None:
        return cached

    location = REGION_LOCATION_MAP.get(region)
    if not location:
        return None

    try:
        client = _get_pricing_client(creds)
        resp = client.get_products(
            ServiceCode="AmazonElastiCache",
            Filters=[
                {"Type": "TERM_MATCH", "Field": "instanceType", "Value": node_type},
                {"Type": "TERM_MATCH", "Field": "location", "Value": location},
                {"Type": "TERM_MATCH", "Field": "cacheEngine", "Value": engine.capitalize()},
            ],
            MaxResults=1,
        )
        if not resp.get("PriceList"):
            return None
        item = json.loads(resp["PriceList"][0])
        price = _extract_ondemand_price(item)
        if price is None:
            return None
        result = {"price": price, "unit": "Hrs", "currency": "USD"}
        set_cached(cache_key, result)
        return result
    except Exception:
        logger.exception("Failed to get ElastiCache pricing for %s (%s) in %s", node_type, engine, region)
        return None


def enrich_resources_with_pricing(service: str, resources: list[dict], creds: dict) -> list[dict]:
    """リソース一覧に On-Demand 単価を付与する."""
    for r in resources:
        r["onDemandPrice"] = None
        r["onDemandUnit"] = None

        if service == "ec2":
            platform = "Windows" if "windows" in (r.get("platform") or "").lower() else "Linux"
            pricing = get_ec2_ondemand_price(r.get("instanceType", ""), r.get("region", ""), platform, creds=creds)
            if pricing:
                r["onDemandPrice"] = pricing["price"]
                r["onDemandUnit"] = pricing["unit"]

        elif service == "rds":
            pricing = get_rds_ondemand_price(
                r.get("instanceClass", ""), r.get("engine", ""), r.get("region", ""), creds=creds
            )
            if pricing:
                r["onDemandPrice"] = pricing["price"]
                r["onDemandUnit"] = pricing["unit"]

        elif service == "elasticache":
            pricing = get_elasticache_ondemand_price(
                r.get("nodeType", ""), r.get("engine", ""), r.get("region", ""), creds=creds
            )
            if pricing:
                r["onDemandPrice"] = pricing["price"]
                r["onDemandUnit"] = pricing["unit"]

    return resources
