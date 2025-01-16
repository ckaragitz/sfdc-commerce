import fastapi as fapi
from fastapi import APIRouter
import schemas
from enums import SecurityScope


from utils import (
    auth,
)

from crud import salesforce_account



router = APIRouter()



@router.get(
    "/salesforce_account/{org_name}",
    tags=["salesforce account"],
)

async def get_salesforce_account(
    org_name: str,
    token: schemas.AuthorizedUser = fapi.Security(auth.get_secure_token_and_user, scopes=SecurityScope.default()),
):
    """Gets account associated to Organization Name"""
    
    accounts = salesforce_account.get_salesforce_accounts(token=token, org_name=org_name)
    #will return all of the results found
    return accounts
