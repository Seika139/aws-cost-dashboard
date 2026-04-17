"""アカウント一覧取得と、各アカウントのロール情報を含む拡張データの組み立て."""

from src.auth import list_account_roles, list_accounts


def get_accounts_with_roles() -> list[dict]:
    """全アカウントと、各アカウントで利用可能なロール一覧を返す."""
    accounts = list_accounts()
    result = []
    for acct in accounts:
        roles = list_account_roles(acct["accountId"])
        result.append(
            {
                "accountId": acct["accountId"],
                "accountName": acct["accountName"],
                "emailAddress": acct["emailAddress"],
                "roles": [r["roleName"] for r in roles],
            }
        )
    return result
