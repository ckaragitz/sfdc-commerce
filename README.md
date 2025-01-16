# Salesforce Integration API

A FastAPI-based service that provides secure integration with Salesforce, handling authentication, account management, machine assets, orders, and carts.

## Features

- 🔐 **JWT Authentication**: Secure token-based authentication system
- 📊 **Account Management**: Salesforce account integration and mapping
- 🔄 **Cart Operations**: Full shopping cart functionality with Salesforce integration
- 📦 **Order Management**: Complete order processing system
- 🤖 **Machine Asset Tracking**: Asset management integrated with Salesforce
- 🔑 **Role-Based Access Control**: Security scopes and permission management
- 🗄️ **Database Integration**: PostgreSQL and Azure Cosmos DB support

## Technology Stack

- Python 3.10+
- FastAPI
- SQLAlchemy
- Azure Cosmos DB
- PostgreSQL
- Salesforce API
- JWT Authentication

## Project Structure

```
.
├── api/
│   ├── carts.py               # Cart management endpoints
│   ├── salesforce_account.py  # Account management endpoints
│   ├── salesforce_machines.py # Machine management endpoints
│   └── ...
├── utils/
│   ├── auth.py               # Authentication utilities
│   ├── db.py                 # Database connection handling
│   ├── salesforce.py         # Salesforce API integration
│   └── salesforce_orders.py  # Order processing utilities
├── models/                   # Pydantic classes - not in this Git repo
├── schemas/                  # Pydantic models - not in this Git repo
├── enums/                    # Enum definitions - not in this Git repo
├── exceptions/              # Custom exceptions - not in this Git repo
└── settings.py              # Application settings - not in this Git repo
```

## Prerequisites

- Python 3.10+
- PostgreSQL database
- Azure Cosmos DB account
- Salesforce developer account with API access
- Azure Key Vault access (for secrets management)

## Environment Variables

```env
# Database
PSQL_CONNECTION_STRING=

# Azure
AZURE_COSMOS_ENDPOINT=
AZURE_COSMOS_KEY=
AZURE_COSMOS_DATABASE=
AZURE_KEY_VAULT_URL=

# Salesforce
SFCC_CLIENT_ID=
SFCC_CLIENT_SECRET=
SFCC_ADMIN_USERNAME=
SFCC_ADMIN_PASSWORD=
SFCC_ADMIN_TOKEN=
SFCC_DOMAIN_NAME=
SFCC_NETWORK_NAME=
WEBSTORE_ID=

# JWT
JWT_PRIVATE_KEY_PATH=
JWT_PUBLIC_KEY_PATH=
JWT_ALGORITHM=
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=
```

## API Documentation

Once the application is running, you can access the API documentation at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### Main Endpoints

- **/carts/**: Shopping cart management
- **/salesforce_account/**: Account management and mapping
- **/salesforce_machines/**: Machine asset management
- **/salesforce_orders/**: Order processing and management

## Security

- JWT-based authentication
- Role-based access control using security scopes
- Encrypted communication with Salesforce
- Secure secret management using Azure Key Vault
- Token refresh mechanism
