import asyncio
import functools
import concurrent.futures
import logging
import multiprocessing as mp

# 3rd party libraries
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from azure.cosmos import CosmosClient

# Settings
from settings import settings

logger = logging.getLogger(__name__)

# psql connection string
connection_string = settings.psql_connection_string.get_secret_value()
engine = create_engine(connection_string, max_overflow=-1)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# cosmos connection
azure_cosmos_client = CosmosClient(
    settings.azure_cosmos_endpoint, settings.azure_cosmos_key
)
azure_cosmos_db_client = azure_cosmos_client.get_database_client(
    settings.azure_cosmos_database
)
azure_cosmos_container = azure_cosmos_db_client.get_container_client(
    settings.azure_cosmos_container
)
azure_cosmos_protein_container = azure_cosmos_db_client.get_container_client(
    settings.azure_cosmos_protein_container
)
azure_cosmos_protein_computed_container = azure_cosmos_db_client.get_container_client(
    settings.azure_cosmos_protein_computed_container
)
azure_cosmos_mv_protein_kpi_container = azure_cosmos_db_client.get_container_client(
    settings.azure_cosmos_mv_protein_kpi_container
)
azure_cosmos_aseptic_kpi_container = azure_cosmos_db_client.get_container_client(
    settings.azure_cosmos_aseptic_kpi_container
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_cosmos_container():
    try:
        yield azure_cosmos_container
    finally:
        return


def get_cosmos_protein_container():
    try:
        yield azure_cosmos_protein_container
    finally:
        return


def get_cosmos_protein_computed_container():
    try:
        yield azure_cosmos_protein_computed_container
    finally:
        return


def get_cosmos_mv_protein_kpi_container():
    try:
        yield azure_cosmos_mv_protein_kpi_container
    finally:
        return

def get_cosmos_aseptic_kpi_container():
    try:
        yield azure_cosmos_aseptic_kpi_container
    finally:
        return


def _cosmos_query(
    container: str,
    query_string: str,
    parameters: list,
    limit: int
) -> list:
    try:
        azure_cosmos_client = CosmosClient(
            settings.azure_cosmos_endpoint, settings.azure_cosmos_key
        )
        azure_cosmos_db_client = azure_cosmos_client.get_database_client(
            settings.azure_cosmos_database
        )
        azure_cosmos_container = azure_cosmos_db_client.get_container_client(
            container
        )
        events = azure_cosmos_container.query_items(
            query=query_string,
            parameters=parameters,
            max_item_count=limit,
            enable_cross_partition_query=True
        )
        events = list(events)
        return events
    except Exception as e:
        print(e)
        return []


class CosmosPool:

    def start_cosmos_process_pool(self):
        try:
            mp.set_start_method('spawn')
            logger.info("multiprocessing start method set to spawn")
        except RuntimeError:
            logger.warn(
                "failed to set multiprocessing start method to spawn, may already be set"
            )
        self.cosmos_process_pool = concurrent.futures.ProcessPoolExecutor()

    def shutdown_cosmos_process_pool(self):
        self.cosmos_process_pool.shutdown(wait=False)

    async def query_cosmos_in_separate_process(
        self,
        container: str,
        query_string: str,
        parameters: list,
        limit: int
    ) -> list:
        loop = asyncio.get_running_loop()
        try:
            events = list(await loop.run_in_executor(
                self.cosmos_process_pool, functools.partial(
                    _cosmos_query,
                    container=container,
                    query_string=query_string,
                    parameters=parameters,
                    limit=limit
                )
            ))
            return events
        except Exception as e:
            print(e)
            return []


# singleton
cosmos_pool = CosmosPool()
