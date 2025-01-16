import json
import schemas
import logging
import requests
import collections
import fastapi as fapi
from datetime import datetime
from utils import (
    salesforce
)
from settings import settings
from schemas import order_quote
from functools import lru_cache


# this should return the salesforce po id to be used for the rest of order flow
def create_sf_po(
        uuid: str,
        owner_id: str,
        account_id: str,
        approver_email: str,
        approver_decision_date: datetime.date,
        purchase_order_number: str

) -> str:
    sf = salesforce.sf_client()
    try:
        po = sf.Purchase_Order__c.create({
            "UUID__c": uuid,
            "OwnerId": owner_id,
            "Account__c": account_id,
            "Approver_Email__c": approver_email,
            "Approval_Decision_Date__c": approver_decision_date,
            "Purchase_Order_Number__c": purchase_order_number,
            "Approval_Status__c": "Approval Pending"
        })
        return po["id"]
    except Exception as e:
        logging.error("Failure to create salesforce po for uuid: {}. Failure is: {}".format(uuid, e))


# helper function to get network ID
@lru_cache()
def get_network_id() -> str:
    try:
        sf = salesforce.sf_client()
        query = "SELECT Id FROM Network WHERE Name = '{}'".format(settings.sfcc_network_name)
        results = sf.query(query)
        if results['records']:
            return results['records'][0]['Id']
        else:
            raise Exception
    except Exception as e:
        logging.info("Failure to get network id: {}".format(e))


def attach_pdf_to_sf(
        sf_po_id: str,  # pdf content in SF linked to this
        pdf_byte_string: str,
        order_id: str,
        current_user: schemas.UserInDB,
        owner_id: str
):
    # currently requires you to pass the Account ID and Cart ID as a query parameter
    sf_username = current_user.sf_username

    # get the credentials and set initial headers
    sf = salesforce.prep_request(sf_username)
    instance_url = sf["instance_url"]
    headers = sf["headers"]

    url = instance_url + "/services/data/v53.0/sobjects/ContentVersion"
    current_date = datetime.today().strftime("%Y-%m-%d")
    current_date = current_date.replace("-", "/")
    filename = '{}/{}.pdf'.format(current_date, str(order_id))
    data = {
        'Title': filename,
        'PathOnClient': filename,
        'ContentLocation': "S",
        'VersionData': pdf_byte_string,
        'OwnerID': owner_id,
        'NetworkId': get_network_id()
    }

    # Create a content version
    content_version = requests.post(url, headers=headers, data=json.dumps(data))
    if content_version.ok is not True:
        raise fapi.HTTPException(
            status_code=content_version.status_code, detail=content_version.json()
        )
    content_version_id = content_version.json().get('id')

    # Get ContentDocument id
    url = instance_url + "/services/data/v53.0/sobjects/ContentVersion/%s" % content_version_id
    content_version = requests.get(url, headers=headers)
    content_document_id = content_version.json().get('ContentDocumentId')

    # Create a content document link
    url = instance_url + "/services/data/v53.0/sobjects/ContentDocumentLink"
    r = requests.post(url, headers=headers, data=json.dumps({
        'ContentDocumentId': content_document_id,
        'LinkedEntityId': sf_po_id,
        "Visibility": "AllUsers"
    }))


# returns dict["results"] which is a list of the orders' metatdata
def create_salesforce_order(
        account_id: str,
        cart_id: str,
        current_user: schemas.UserInDB,
        purchase_data: order_quote.OrderInput,
        sf_po_id: str,
        is_urgent: bool
) -> dict:
    """Create an Order (quote) in Salesforce with 'Draft' status"""
    # TODO: map logged in user's plant to Salesforce Account ID, fetching plant/product/pricing data dynamically
    # currently requires you to pass the Account ID and Cart ID as a query parameter
    sf_username = current_user.sf_username

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
                    "accountId": account_id,
                    # TODO: dynamic query of PB
                    "Pricebook2Id": pricebook,
                    "OrderItems": {"records": pricebook_map[pricebook]},
                    "OmniBlu__c": True,
                    "Approver__c": purchase_data.approver,
                    # TODO: fix bug on how to use compound field
                    # "BillingAddress": {
                    #     "city": purchase_data.bill_to.city,
                    #     "state": purchase_data.bill_to.state,
                    #     "postal_code": purchase_data.bill_to.postal_code,
                    #     "street_address": purchase_data.bill_to.street_address
                    # },
                    "Purchase_Order__c": sf_po_id,
                    "Urgent__c": is_urgent
                }
            ]
        }

        order_response = requests.post(
            url, headers=headers, data=json.dumps(payload)
        )
        if order_response.ok is not True:
            print(order_response.status_code, order_response.json())
            raise fapi.HTTPException(
                status_code=order_response.status_code,
                detail=order_response.json(),
            )
        else:
            order_responses["results"].append(order_response.json())

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
    # TODO: maybe parse this to only give the order IDs
    return order_responses


# this should return the salesforce po id to be used for the rest of order flow
def flip_sf_po(
        sf_po_id: str
) -> bool:
    sf = salesforce.sf_client()
    # use query to flip the value
    data = {
        "Approval_Status__c": "Approved"
    }
    try:
        sf.Purchase_Order__c.update(sf_po_id, data)
        return True
    except:
        return False
