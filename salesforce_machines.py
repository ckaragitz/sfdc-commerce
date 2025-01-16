import json
import requests
import collections
import fastapi as fapi
from fastapi import APIRouter
from datetime import datetime
import schemas
from enums import SecurityScope
from schemas import salesforce_machine
from utils import (
    auth,
    salesforce,
)
from settings import settings
from exceptions.data_exception import DataException
from crud import salesforce_machines

router = APIRouter()



@router.get(
    "/salesforce_machines/{org_id}",
    tags=["salesforce machines"],
)
async def get_salesforce_machines_by_org_id(
    org_id: str,
    token: schemas.AuthorizedUser = fapi.Security(auth.get_secure_token_and_user, scopes=SecurityScope.default()),
):
    """Gets Machines (Assets) that belong to an Org ID"""   
    
    machines = salesforce_machines.get_salesforce_machines(token, org_id)

    # will return all of the results found 
    return machines
