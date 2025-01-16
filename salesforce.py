import jwt
import requests
import datetime
import os.path
from simple_salesforce import Salesforce
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

from settings import settings

from models import User as user_model
from utils import auth
from utils import db as database

# SFCC connection details
#TODO: reminder to create new connected app and certificate/keys for Salesforce production org
#TODO: move these values to AZ Key Vault
client_id = settings.sfcc_client_id
client_secret = settings.sfcc_client_secret.get_secret_value()
sfcc_admin_username = settings.sfcc_admin_username
sfcc_admin_password = settings.sfcc_admin_password.get_secret_value()
sfcc_admin_token = settings.sfcc_admin_token

def sf_client():
    return Salesforce(
        username=sfcc_admin_username,
        password=sfcc_admin_password,
        security_token=sfcc_admin_token,
        domain=settings.sfcc_domain_name
    )

def prep_request(sf_username):
    """ Prepare the Salesforce API requests by fetching new access tokens and setting headers """
    
    #TODO: reminder to change Production URLs
    creds = jwt_login(client_id, sf_username)
    access_token = creds["access_token"]
    instance_url = creds["instance_url"]

    headers = {
        "Authorization": "Bearer " + access_token,
        "Content-Type": "application/json",
        "Accept": "*/*"
    }
    return {"instance_url": instance_url, "headers": headers}

def get_key_from_azure():
    """ Fetch the SFCC private_key from Azure Key Vault """

    credential = DefaultAzureCredential(exclude_visual_studio_code_credential=True)
    secret_client = SecretClient(vault_url=settings.azure_key_vault_url, credential=credential)
    certificate = secret_client.get_secret(settings.sfcc_jwt_cert_name)

    # both the public and private keys within a PEM
    pem_pair = certificate.value

    # process to build the private key
    begin = "-----BEGIN PRIVATE KEY-----"
    end = "-----END PRIVATE KEY-----"
    header_start = pem_pair.index(begin)
    footer_start = pem_pair.index(end)
    # TODO: THERE HAS GOT TO BE A BETTER WAY TO DO THIS
    pk_string = pem_pair[header_start : footer_start + 25]

    # TODO: store key paths in Azure Key Vault?
    # TODO: add try/catch logic
    if os.path.exists("keys/sfcc_private_key.pem"):
        with open("keys/sfcc_private_key.pem") as pk_out:
            private_key = pk_out.read()
    else:
        with open("keys/sfcc_private_key.pem", "xb") as pk_in:
            pk_in.write(pk_string.encode())

        with open("keys/sfcc_private_key.pem") as pk_out:
            private_key = pk_out.read()

    return private_key

def jwt_login(client_id, sf_username):
    """ Sign a JWT and send to Salesforce in exchange for an access token
        Leverages the logged-in user's sf_username """

    # TODO: may want to add try/catch logic

    # Initialize db session
    db = next(database.get_db())
    # try to fetch token from db
    db_token = (
        db.query(user_model.sf_access_token)
        .filter(user_model.sf_username == sf_username).first()
    )
     
    # fetch expiration time from db
    db_expiration_time = (
        db.query(user_model.sf_token_expiration)
        .filter(user_model.sf_username == sf_username).first()
    )

    # check the database to see if there is a token and if it has not expired
    if db_token and db_expiration_time[0] >= datetime.datetime.utcnow():
        return {"access_token": auth.decrypt(db_token[0]), "instance_url": settings.sfcc_storefront_base_endpoint}

    # fetch private_key for encrypting JWT from Azure Key Vault
    private_key = get_key_from_azure()

    # this endpoint is for external users
    # TODO: reminder to flip to Production URL
    endpoint = settings.sfcc_storefront_base_endpoint

    # define claims and encode JWT
    jwt_payload = jwt.encode(
        { 
            'exp': datetime.datetime.utcnow() + datetime.timedelta(seconds=30),
            'iss': client_id,
            'aud': endpoint,
            'sub': sf_username
        },
        private_key,
        algorithm='RS256'
    )

    # submit JWT to Salesforce in exchange for an access_token
    response = requests.post(
        endpoint + '/services/oauth2/token',
        data={
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
            'assertion': jwt_payload
        }
    )

    # response from Salesforce with access_token and instance_url
    body = response.json()

    if response.status_code != 200:
        return {"error": body['error'], "message": body['error_description']}
    else:
        # set access token details
        access_token = body["access_token"]
        instance_url = body["instance_url"]
        expiration = datetime.datetime.utcnow() + datetime.timedelta(minutes=1)
        
        # if there is no token in the database, or expiration time for token is expired
        if not db_token[0] or db_expiration_time[0] < datetime.datetime.utcnow():
            # store in db 
            db.query(user_model).filter(user_model.sf_username == sf_username).update({"sf_access_token": auth.encrypt(access_token), "sf_token_expiration": expiration}, synchronize_session=False)
            db.commit()
        return {"access_token": access_token, "instance_url": instance_url}