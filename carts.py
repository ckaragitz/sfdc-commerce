import json
import schemas
import requests
import fastapi as fapi
from fastapi import APIRouter
from settings import settings
from sqlalchemy.orm import Session
from enums import SecurityScope

from utils import (
    auth,
    salesforce,
    db
)
from models import SfCarts as sf_carts_model
from sqlalchemy.dialects.postgresql import insert

router = APIRouter()


@router.get("/carts/me", tags=["carts"], response_model=schemas.Cart
)
async def get_cart(
    account_id: str,
    token: schemas.AuthorizedUser = fapi.Security(auth.get_secure_token_and_user, scopes=SecurityScope.default()),
):
    """Get cart details"""
    # TODO: map logged in user's org to Salesforce Account ID
    # currently requires you to pass the Account ID as a query parameter
    sf_username = token.details.sf_username

    # get the credentials and set initial headers
    sf = salesforce.prep_request(sf_username)
    instance_url = sf["instance_url"]
    headers = sf["headers"]

    url = (
        instance_url
        + "/services/data/v53.0/commerce/webstores/"
        + settings.webstore_id
        + "/carts/active?effectiveAccountId="
        + account_id
    )

    response = requests.get(url, headers=headers)
    if response.ok is not True:
        raise fapi.HTTPException(
            status_code=response.status_code, detail=response.json()
        )

    # return the metadata received from Salesforce
    return response.json()


@router.get(
    "/carts/me/products", tags=["carts"]
)
async def get_cart_products(
    account_id: str,
    token: schemas.AuthorizedUser = fapi.Security(auth.get_secure_token_and_user, scopes=SecurityScope.default()),
):
    """Get product details from a cart with corresponding SFCC IDs"""
    # TODO: map logged in user's plant to Salesforce Account ID, dynamically fetch "active" Carts for user via CartId
    # currently requires you to pass the Account ID as a query parameter
    # TODO: create request Schema for Out ->
    sf_username = token.details.sf_username

    # get the credentials and set initial headers
    sf = salesforce.prep_request(sf_username)
    instance_url = sf["instance_url"]
    headers = sf["headers"]

    url = (
        instance_url
        + "/services/data/v53.0/commerce/webstores/"
        + settings.webstore_id
        + "/carts/active/cart-items?effectiveAccountId"
        + account_id
    )

    response = requests.get(url, headers=headers)
    if response.ok is not True:
        raise fapi.HTTPException(
            status_code=response.status_code, detail=response.json()
        )

    # return the metadata received from Salesforce
    return response.json()


@router.post("/carts/me/products", tags=["carts"])
async def add_product_to_cart(
    account_id: str,
    request: schemas.CartProductIn,
    token: schemas.AuthorizedUser = fapi.Security(auth.get_secure_token_and_user, scopes=[SecurityScope.write]),
    db: Session = fapi.Depends(db.get_db),
):
    """Add a product to a cart (create the cart if none exists)"""
    # TODO: map logged in user's org to Salesforce Account ID
    # currently requires you to pass the Account ID as a query parameter
    sf_username = token.details.sf_username

    # get the credentials and set initial headers
    sf = salesforce.prep_request(sf_username)
    instance_url = sf["instance_url"]
    headers = sf["headers"]

    # add item to cart, create one if none exists
    url = (
        instance_url
        + "/services/data/v53.0/commerce/webstores/"
        + settings.webstore_id
        + "/carts/active/cart-items?effectiveAccountId="
        + account_id
    )

    payload = {
        "productId": request.productId,
        "quantity": request.quantity,
        "type": "product",
    }

    response = requests.post(url, headers=headers, data=json.dumps(payload))
    if response.ok is not True:
        raise fapi.HTTPException(
            status_code=response.status_code, detail=response.json()
        )
    output = response.json()

    # write to postgres
    insert_stmt = insert(sf_carts_model).values(
        sf_cart_id=output['cartId'],
        sf_cart_item_id=output["cartItemId"],
        sf_account_id=account_id,
        sf_product_id=output["productId"],
        quantity=request.quantity
    )
    do_update_stmt = insert_stmt.on_conflict_do_update(
        index_elements=['sf_cart_id', 'sf_cart_item_id'],
        set_=dict(quantity=insert_stmt.excluded.quantity+sf_carts_model.quantity)
    )
    db.execute(do_update_stmt)
    db.commit()

    # return the metadata received from Salesforce
    return output


@router.put("/carts/me/products/{cart_item_id}", tags=["carts"], status_code=204)
async def update_cart_product(
    cart_item_id: str,
    request: schemas.CartProductPut,
    token: schemas.AuthorizedUser = fapi.Security(auth.get_secure_token_and_user, scopes=[SecurityScope.write]),
    db: Session = fapi.Depends(db.get_db),
):
    """Update the quantity of a product in a cart"""
    # TODO: cart item id will exist in a reference table for Salesforce
    # currently requires you to pass the Salesforce CartItem ID as a query parameter
    sf_username = token.details.sf_username

    # get the credentials and set initial headers
    sf = salesforce.prep_request(sf_username)
    instance_url = sf["instance_url"]
    headers = sf["headers"]

    url = (
        instance_url + "/services/data/v53.0/sobjects/CartItem/" + cart_item_id
    )

    payload = {
        "quantity": request.quantity,
    }

    response = requests.patch(url, headers=headers, data=json.dumps(payload))
    if response.ok is not True:
        raise fapi.HTTPException(
            status_code=response.status_code, detail=response.json()
        )

    # update in postgres
    db.query(sf_carts_model)\
        .filter_by(sf_cart_item_id=cart_item_id)\
        .update({"quantity": request.quantity}, synchronize_session=False,)
    db.commit()

    # return the metadata received from Salesforce (none)
    return response.text


@router.delete(
    "/carts/me/products/{cart_item_id}", tags=["carts"], status_code=204
)
async def delete_cart_product(
    cart_item_id: str,
    token: schemas.AuthorizedUser = fapi.Security(auth.get_secure_token_and_user, scopes=[SecurityScope.write]),
    db: Session = fapi.Depends(db.get_db),
):
    """Remove a product from a cart"""
    # TODO: cart item id will exist in a reference table for Salesforce
    # currently requires you to pass the Salesforce CartItem ID as a query parameter
    sf_username = token.details.sf_username

    # get the credentials and set initial headers
    sf = salesforce.prep_request(sf_username)
    instance_url = sf["instance_url"]
    headers = sf["headers"]

    url = (
        instance_url + "/services/data/v53.0/sobjects/CartItem/" + cart_item_id
    )

    response = requests.delete(url, headers=headers)
    if response.ok is not True:
        raise fapi.HTTPException(
            status_code=response.status_code, detail=response.json()
        )

    # remove from postgres
    db.query(sf_carts_model).filter_by(sf_cart_item_id=cart_item_id).delete()
    db.commit()

    # return the metadata received from Salesforce (none)
    return response.text
