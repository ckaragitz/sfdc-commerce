import typing


import json
import requests
import collections
import fastapi as fapi
from fastapi import APIRouter
from datetime import datetime
import schemas
from schemas.sf_purchase_order import SFPurchaseOrder

from enums import SecurityScope

from utils import (
    auth,
    salesforce,
    salesforce_orders
)
from settings import settings

router = APIRouter()

@router.get(
    "/salesforce_purchase_orders/me",
    tags=["salesforce order"],
    response_model=typing.List[SFPurchaseOrder]
)
async def get_salesforce_purchase_orders(
    token: schemas.AuthorizedUser = fapi.Security(auth.get_secure_token_and_user, scopes=SecurityScope.default()),
):
    """Get Orders by User"""
    sf_username = token.details.sf_username
    sf_user_id = token.details.sf_user_id

    # get the credentials and set initial headers
    sf = salesforce.prep_request(sf_username)
    instance_url = sf["instance_url"]
    headers = sf["headers"]

    # fetch purchase orders and corresponding order and order_items
    # TODO: do we want to add additional filters? such as only active orders?
    query = (
        "SELECT Id, Purchase_Order__r.Id, Purchase_Order__r.Name, Purchase_Order__r.UUID__c, Purchase_Order__r.CreatedDate, Purchase_Order__r.Purchase_Order_Number__c, Purchase_Order__r.Approval_Status__c, Purchase_Order__r.Total__c, (SELECT Id, UnitPrice, Quantity FROM OrderItems) FROM Order WHERE Purchase_Order__c != null AND OwnerId ="
        + "'"
        + sf_user_id
        + "'"
    )
    url = instance_url + "/services/data/v53.0/query/?q=" + query

    purchase_orders_response = requests.get(url, headers=headers)
    if purchase_orders_response.ok is not True:
        raise fapi.HTTPException(
            status_code=purchase_orders_response.status_code, detail=purchase_orders_response.json()
        )
    po_response = purchase_orders_response.json()
    purchase_order_list: typing.Dict[str, SFPurchaseOrder] = {}
    # iterate through list of POs and query for Order Items
    for po in po_response["records"]:
        po_obj = po["Purchase_Order__r"]
        order_items_obj = po["OrderItems"]["records"]
        sf_po = SFPurchaseOrder(
            id=po_obj["Id"],
            name=po_obj["Name"],
            order_quote_id=po_obj["UUID__c"],
            created_date=po_obj["CreatedDate"],
            po_number=po_obj["Purchase_Order_Number__c"],
            status=po_obj["Approval_Status__c"],
            total=0.00 if po_obj["Total__c"] is None else float(po_obj["Total__c"])
        )
        if ( po_obj["Id"] not in purchase_order_list):
            sf_po.quantity = sum(order_item["Quantity"] for order_item in order_items_obj)
            purchase_order_list[po_obj["Id"]] = sf_po
        else:
            sf_po = purchase_order_list.get(po_obj["Id"])
            sf_po.quantity += sum(order_item["Quantity"] for order_item in order_items_obj)
    return list(purchase_order_list.values())

@router.get(
    "/salesforce_orders/me",
    tags=["salesforce order"],
)
async def get_salesforce_orders(
    token: schemas.AuthorizedUser = fapi.Security(auth.get_secure_token_and_user, scopes=SecurityScope.default()),
):
    """Get Orders by User"""
    sf_username = token.details.sf_username
    sf_user_id = token.details.sf_user_id

    # get the credentials and set initial headers
    sf = salesforce.prep_request(sf_username)
    instance_url = sf["instance_url"]
    headers = sf["headers"]

    # fetch historical Orders and Order Items for a user
    # TODO: do we want to add additional filters? such as only active orders?
    query = (
        "SELECT Id, Status, EffectiveDate, PriceBook2Id, (SELECT Id, Product2.Id, Product2.Name, UnitPrice, Quantity FROM OrderItems) FROM Order WHERE OwnerId = "
        + "'"
        + sf_user_id
        + "'"
    )
    url = instance_url + "/services/data/v53.0/query/?q=" + query

    orders_response = requests.get(url, headers=headers)
    if orders_response.ok is not True:
        raise fapi.HTTPException(
            status_code=orders_response.status_code, detail=orders_response.json()
        )

    return orders_response.json()


@router.get(
    "/salesforce_orders/me/{order_id}",
    tags=["salesforce order"],
)
async def get_salesforce_orders(
    order_id: str,
    token: schemas.AuthorizedUser = fapi.Security(auth.get_secure_token_and_user, scopes=SecurityScope.default()),
):
    """Get Orders by User"""
    sf_username = token.details.sf_username

    # get the credentials and set initial headers
    sf = salesforce.prep_request(sf_username)
    instance_url = sf["instance_url"]
    headers = sf["headers"]

    # fetch a specific order
    url = instance_url + "/services/data/v30.0/commerce/sale/order/" + order_id

    order_response = requests.get(url, headers=headers)
    if order_response.ok is not True:
        raise fapi.HTTPException(
            status_code=order_response.status_code, detail=order_response.json()
        )

    return order_response.json()


@router.post(
    "/salesforce_order",
    tags=["salesforce order"],
    response_model=schemas.OrderOut,
    deprecated=True
)
async def create_salesforce_order(
    account_id: str,
    cart_id: str,
    token: schemas.AuthorizedUser = fapi.Security(auth.get_secure_token_and_user, scopes=[SecurityScope.write]),
):
    """Create an Order (quote) in Salesforce with 'Draft' status"""
    # TODO: map logged in user's plant to Salesforce Account ID, fetching plant/product/pricing data dynamically
    # currently requires you to pass the Account ID and Cart ID as a query parameter
    sf_username = token.details.sf_username

    # get the credentials and set initial headers
    sf = salesforce.prep_request(sf_username)
    instance_url = sf["instance_url"]
    headers = sf["headers"]

    # fetch products in active cart
    query = (
        "SELECT Id, CartId, Name, Product2.ProductCode, SalesPrice, Quantity FROM CartItem WHERE CartId = "
        + "'"
        + cart_id
        + "'"
    )
    url = instance_url + "/services/data/v53.0/query/?q=" + query

    cart_items_query_response = requests.get(url, headers=headers)
    if cart_items_query_response.ok is not True:
        raise fapi.HTTPException(
            status_code=cart_items_query_response.status_code, detail=cart_items_query_response.json()
        )

    cart_products = cart_items_query_response.json()
    pricebook_map = collections.defaultdict(list)  # strucutre is {PB.id:[records]}
    order_responses = {"results": []}

    # iterate through list of products and query for PriceBookEntry IDs
    for product in cart_products["records"]:
        cart_item_id = product["Id"]
        cart_item_name = product["Name"]
        sku = product["Product2"]["ProductCode"]
        price = product["SalesPrice"]
        qty = product["Quantity"]

        # TODO: refactor this to read from database, since PBEs should be stored
        # TODO: re-think a more "unique" query to only return 1 item
        query = (
            "SELECT Id, PriceBook2.Id FROM PriceBookEntry WHERE UnitPrice = {0}".format(float(price))
            + " AND Product2.ProductCode = "
            + "'"
            + sku
            + "'"
        )
        url = instance_url + "/services/data/v53.0/query/?q=" + query

        pb_query_response = requests.get(url, headers=headers)
        if pb_query_response.ok is not True:
            raise fapi.HTTPException(
                status_code=pb_query_response.status_code,
                detail=pb_query_response.json(),
            )

        body = pb_query_response.json()

        pb_entry_id = body["records"][0]["Id"]
        pricebook_id = body["records"][0]["Pricebook2"]["Id"]

        record = {
            "attributes": {"type": "OrderItem"},
            "PricebookEntryId": pb_entry_id,
            "quantity": qty,
            "UnitPrice": price,
        }
        pricebook_map[pricebook_id].append(record)

    # create an Order with products in Cart
    url = instance_url + "/services/data/v53.0/commerce/sale/order"

    for pricebook in pricebook_map:
        payload = {
            "order": [
                {
                    "attributes": {"type": "Order"},
                    "EffectiveDate": datetime.today().strftime("%Y-%m-%d"),
                    "Status": "Draft",
                    # TODO: dynamic query of Plant to fetch billing city?
                    "billingCity": "Chicago",
                    "accountId": account_id,
                    # TODO: dynamic query of PB
                    "Pricebook2Id": pricebook,
                    "OrderItems": {"records": pricebook_map[pricebook]},
                }
            ]
        }

        order_response = requests.post(
            url, headers=headers, data=json.dumps(payload)
        )
        if order_response.ok is not True:
            raise fapi.HTTPException(
                status_code=order_response.status_code,
                detail=order_response.json(),
            )
        else:
            order_responses["results"].append(order_response.json())
            # TODO: store order metadata in postgres

    # if Order creation is a success, close the Cart
    url = instance_url + "/services/data/v53.0/sobjects/WebCart/" + cart_id

    payload = {"Status": "Closed"}

    cart_update_response = requests.patch(
        url, headers=headers, data=json.dumps(payload)
    )
    if cart_update_response.ok is not True:
        raise fapi.HTTPException(
            status_code=cart_update_response.status_code,
            detail=cart_update_response.json(),
        )

    # return the metadata received from Salesforce
    return order_responses
