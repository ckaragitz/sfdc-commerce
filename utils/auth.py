# Standard libraries
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Union
import logging

# If less then Python 3.8 fallback to using literal from `typing_extensions`.
# TODO: remove this fallback if we move our cloud environments to >= 3.8
import models

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal
# 3rd party libraries
import jwt
import passlib.context
import fastapi as fapi
import fastapi.security as fapis
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

# SqlAlchemy
from sqlalchemy.orm import Session

# Models
from models import (
    Machine as MachineModel,
    Organization as OrganizationModel,
    Plant as PlantModel,
    User as UserModel,
    UserScopeMap,
    SecurityScope as SecurityScopeModel
)

# Schemas
import schemas
from schemas.access_token import EncodedAccessToken
from schemas.user import UserInDB

# Enums
from enums import SecurityScope

# Utils
import utils.db as db

# Settings
from settings import settings

from Crypto.Cipher import AES
import base64
from Cryptodome.Random import get_random_bytes

pwd_context = passlib.context.CryptContext(
    schemes=[settings.password_hashing_algorithm],
    default=settings.password_hashing_algorithm,
    deprecated="auto",
)

security_scopes = next(db.get_db()).query(SecurityScopeModel).all()
scope_map = {}
try:
    scope_map = {SecurityScope(scope.id): scope.name
                 for scope in security_scopes}
except KeyError as err:
    raise KeyError(
        f'Security scope {err} not found in the `SecurityScope` enum. '
        'This enum must match the scopes defined in the DB.'
    )
except:
    raise Exception(
        'Failed to parse security scopes found in the DB into the '
        '`SecurityScope` enum'
    )
oauth2_scheme = fapis.OAuth2PasswordBearer(
    tokenUrl="token",
    scopes=scope_map,
)

logger = logging.getLogger(__name__)

# Utils to get the private and public keys for JWT encoding


def get_key(key, key_path):
    # Use the key if directly provided
    if key is not None:
        return key

    # Attempt to find the key at a well defined location, i.e. in the `keys`
    # folder
    try:
        with open(key_path) as f:
            return f.read()
    # Only catch a file not found error in case of other errors we probably want
    # to raise them
    except FileNotFoundError:
        pass

    return None


private_key = get_key(settings.jwt_private_key, settings.jwt_private_key_path)
public_key = get_key(
    settings.jwt_public_key,
    settings.jwt_public_key_path,
)

# Worst case, fallback to generating the keys on the fly and saving them back to
# the `keys` folder
if private_key is None or public_key is None:
    print(
        "WARNING: generating the private and public keys used for JWT encoding and saving them to the `keys` directory. When not in development, these keys should be generated using the method described in the README as opposed to relying on this process. For development purposes, this method should be fine."
    )
    pri_key = ed25519.Ed25519PrivateKey.generate()
    private_key = pri_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    # Only open the file for writing if it doesn't already exist, fail
    # otherwise. Don't want to accidentally lose a key / data. Open for binary
    # as we're writing bytes technically, not text (though it is human
    # readable).
    with open(settings.jwt_private_key_path, "xb") as f:
        f.write(private_key)

    pub_key = pri_key.public_key()
    public_key = pub_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    # Only open the file for writing if it doesn't already exist, fail
    # otherwise. Don't want to accidentally lose a key / data. Open for binary
    # as we're writing bytes technically, not text (though it is human
    # readable).
    with open(settings.jwt_public_key_path, "xb") as f:
        f.write(public_key)


class AuthException(Exception):
    def __init__(self, detail: str):
        self.detail = detail


class NotEnoughPermissionsException(Exception):
    def __init__(self, detail: str):
        self.detail = detail


def verify_password(plain_password: str, password: str):
    return pwd_context.verify(plain_password, password)


def get_password_hash(password: str):
    return pwd_context.hash(password)


def get_user(db: Session, email: str):
    # `one_or_none` will return at most one result. It raises an exception if
    # there's more than one (which shouldn't be possible since the `email` has a
    # unique constraint). It also returns `None` if there's no result, as
    # opposed to `one` which with raise an exception if there were no results.
    return db.query(UserModel).filter_by(email=email).one_or_none()


def authenticate_user(db: Session, email: str, password: str):
    user = get_user(db, email)

    if not user:
        return False
    if not verify_password(password, user.password):
        return False
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.jwt_access_token_expire_minutes
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, private_key, algorithm=settings.jwt_algorithm
    )
    return encoded_jwt


# key for salesforce token, store in azure key vault
__key__ = b'\x1d7(\xfd\x86\xd8\xeaa\x8c_/\x96\x98\x87#\xa5\xfaj:\xb3\xa0C\x8e\x01/\x06\xfd\xb8_\xd2cS'

# AES 256 Encryption & Decryption


def encrypt(raw):
    BS = AES.block_size
    def pad(s): return s + (BS - len(s) % BS) * chr(BS - len(s) % BS)
    raw = base64.b64encode(pad(raw).encode('utf8'))
    iv = get_random_bytes(AES.block_size)
    cipher = AES.new(key=__key__, mode=AES.MODE_CFB, iv=iv)
    return base64.b64encode(iv + cipher.encrypt(raw))


def decrypt(enc):
    def unpad(s): return s[:-ord(s[-1:])]
    enc = base64.b64decode(enc)
    iv = enc[:AES.block_size]
    cipher = AES.new(__key__, AES.MODE_CFB, iv)
    return unpad(base64.b64decode(cipher.decrypt(enc[AES.block_size:])).decode('utf8'))


async def get_secured_token(
    security_scopes: fapis.SecurityScopes,
    token: str,
) -> schemas.AccessToken:

    credentials_exception = AuthException(
        detail="Could not validate credentials"
    )
    not_enough_permissions_exception = NotEnoughPermissionsException(
        detail="Not enough permissions for this api"
    )
    try:
        payload = jwt.decode(
            token, public_key, algorithms=[settings.jwt_algorithm]
        )
        sub: str = payload.get("sub")
        if sub is None:
            raise credentials_exception

        token_scopes = payload.get("scopes", [])

        # Assure the user has at least one of the expected scopes needed for
        # this particular route
        if not any(route_scope in token_scopes
                   for route_scope in security_scopes.scopes):
            raise not_enough_permissions_exception

        exp: int = payload.get("exp")
        if exp is None:
            raise credentials_exception
        # TODO: validate that the data is internally consistent, i.e. specified
        # machines exist under specified plants, likewise that all specified
        # plants exist under specified organizations.
        organizations: List[Union[str, Literal["*"]]] = payload.get(
            "organizations"
        )
        if organizations is None:
            raise credentials_exception
        plants: List[Union[str, Literal["*"]]] = payload.get("plants")
        if plants is None:
            raise credentials_exception
        machines: List[Union[str, Literal["*"]]] = payload.get("machines")
        if machines is None:
            raise credentials_exception
    except jwt.InvalidTokenError:
        raise credentials_exception

    return schemas.AccessToken(
        sub=sub,
        exp=exp,
        organizations=organizations,
        plants=plants,
        machines=[uuid.UUID(machine) for machine in machines],
    )


async def access_token_from_refresh_token(
    refresh_token: str,
    db: Session = fapi.Depends(db.get_db),
) -> EncodedAccessToken:
    credentials_exception = AuthException(
        detail="Could not validate credentials"
    )
    try:
        payload = jwt.decode(
            refresh_token, public_key, algorithms=[settings.jwt_algorithm]
        )
        sub: str = payload.get("sub")
        if sub is None:
            raise credentials_exception
        exp: int = payload.get("exp")
        if exp is None:
            raise credentials_exception

        user = get_user(db, sub)

        access_timedelta = timedelta(
            minutes=settings.jwt_access_token_expire_minutes
        )

        [organization_ids, plant_ids, machine_ids, security_scopes] = await get_user_resources(
            user, db
        )
    except jwt.InvalidTokenError:
        raise credentials_exception

    new_access_token = create_access_token(
        data={
            "sub": user.email,
            "organizations": organization_ids,
            "plants": plant_ids,
            "machines": machine_ids,
            "scopes": security_scopes,
        },
        expires_delta=access_timedelta,
    )

    expires_at = datetime.utcnow() + access_timedelta
    token = {
        "access_token": new_access_token,
        "token_type": "bearer",
        "refresh_token": refresh_token,
        "expires_at": expires_at,
    }
    return token


async def get_secure_token_and_user(
        security_scopes: fapis.SecurityScopes,
        token: str = fapi.Depends(oauth2_scheme),
        db: Session = fapi.Depends(db.get_db),
) -> schemas.AuthorizedUser:
    secured_token = await get_secured_token(security_scopes=security_scopes, token=token)
    credentials_exception = AuthException(
        detail="Could not validate credentials"
    )
    user_model = get_user(db, secured_token.sub)
    if user_model is None:
        raise credentials_exception
    if user_model.disabled:
        raise credentials_exception
    authorized_user = schemas.AuthorizedUser(
        sub=secured_token.sub,
        exp=secured_token.exp,
        organizations=secured_token.organizations,
        plants=secured_token.plants,
        machines=secured_token.machines,
        details=user_model
    )
    return authorized_user


async def get_user_resources(
    user: UserInDB, db: Session = fapi.Depends(db.get_db)
):
    if user.all_organizations:
        organizations = db.query(OrganizationModel).all()
    else:
        organizations = [org_map.organization for org_map in user.organizations]

    organization_ids = [organization.id for organization in organizations]

    if user.all_plants:
        plants = (
            db.query(PlantModel)
            .filter(PlantModel.org_id.in_(organization_ids))
            .all()
        )
    else:
        plants = [
            plant_map.plant for plant_map in user.plants
            if plant_map.plant.org_id in organization_ids
        ]

    plant_ids = [plant.id for plant in plants]

    if user.all_machines:
        machines = (
            db.query(MachineModel)
            .filter(MachineModel.plant_id.in_(plant_ids))
            .all()
        )
    else:
        machines = [
            machine_map.machine for machine_map in user.machines
            if machine_map.machine.plant_id in plant_ids
        ]

    machine_ids = [str(machine.id) for machine in machines]

    security_scopes = []
    user_scope_map: UserScopeMap
    for user_scope_map in user.scopes:
        security_scopes.append(user_scope_map.scope.id)

    return [organization_ids, plant_ids, machine_ids, security_scopes]
