"""
This module provides a way to export SQL tables to a Meilisearch
instance in an easy and fast way.
"""

import argparse
import json
import logging
from math import ceil
from os.path import isfile
from sys import exit as sys_exit
from typing import List, Dict

import jsonschema
import meilisearch
from jsonschema import validate
from sqlalchemy import engine, create_engine, MetaData, func, select

Json = Dict


class DatabaseConn:
    """
    Class that holds all the data and
    relevant methods pertaining to the
    database
    """

    database_url: str
    tables: List[str]
    database_engine: engine
    metadata: MetaData

    def __init__(
        self,
        adapter: str,
        host: str,
        port: int,
        username: str,
        password: str,
        database_name: str,
        tables: List[str],
    ) -> None:
        self.tables = tables
        self.database_url = (
            f"{adapter}://{username}:{password}@{host}:{port}/{database_name}")

    def create_engine(self) -> None:
        """
        Creates an engine that's used to connect to the database
        and introspects the database
        """
        self.database_engine = create_engine(self.database_url)
        self.metadata = MetaData()
        self.metadata.reflect(bind=self.database_engine)

    def validate_tables(self) -> None:
        """Checks if all the tables defined in the config file
        exist in the database
        """
        tables_not_present: List = list(
            filter(lambda tab: tab not in self.metadata.tables, self.tables))
        if len(tables_not_present) > 0:
            raise KeyError(
                f"The following tables do not exist in the database: {tables_not_present}"
            )

    def get_primary_key_name(self, table_name: str):
        """Gets the name of the first primary key of a given table
        As far as I know, MeiliSearch only supports one primary key
        Will be updated to support more than one if needed
        """
        return next(
            map(
                lambda tab: tab.primary_key.columns.values()[0].name,
                filter(lambda tb: tb.name == table_name,
                       self.metadata.sorted_tables),
            ))


class MeilisearchConn:
    """
    Class that holds all the data and
    relevant methods pertaining to the
    Meilisearch connection
    """

    indexes: List[str]
    meilisearch_client: meilisearch.Client

    def __init__(self, host: str, api_key: str, indexes: List[str]) -> None:
        self.indexes = indexes
        self.meilisearch_client = meilisearch.Client(host, api_key)

    def upload_data_to_index(self, index: str, data: List[Dict],
                             primary_key: str):
        """
        Uploads a list to an index
        :param index: Name of the index to upload the table to
        :param data: List of dicts containing the data to be uploaded
        :param primary_key: Primary key of the index
        """
        self.meilisearch_client.get_index(index).update_documents(
            data, primary_key=primary_key)
        logging.info("Exported %d rows to Meilisearch index %s", len(data),
                     index)

    def validate_indexes(self, db_con: DatabaseConn):
        """
        Checks if all the indexes specified in the config file
        exist in the given Meilisearch instance
        Also checks if the number of tables is mismatched and
        if so raises an exception.
        This script assumes that if there are more specified
        tables than there are indexes, that the corresponding indexes
        share the same name
        """
        diff: int = len(db_con.tables) - len(self.indexes)
        if diff == 0:
            return
        if diff < 0:
            raise jsonschema.exceptions.ValidationError(
                "There cannot be more indexes than tables defined.")
        if diff > 0:
            for table in db_con.tables[len(db_con.tables) - diff:]:
                self.indexes.append(table)

        indexes_not_present: List = list(
            filter(
                lambda idx: idx not in list(
                    map(
                        lambda index: index["uid"],
                        self.meilisearch_client.get_indexes(),
                    )),
                self.indexes,
            ))
        if len(indexes_not_present) > 0:
            raise KeyError(
                f"The following indexes are not present in Meilisearch: {indexes_not_present}"
            )


def create_connection_from_dict(
        json_data: Json, schema_path: str) -> (DatabaseConn, MeilisearchConn):
    """
    This function validates the configuration data against a schema
    and if it is successful, instantiates a DatabaseConn and a
    MeilisearchConn class.
    It also proceeds to create a connection to the database and also
    validates both the indexes and tables of the instantiated objects
    """
    validate_json(json_data, schema_path)
    database: DatabaseConn = DatabaseConn(**json_data["database"])
    meili: MeilisearchConn = MeilisearchConn(**json_data["meilisearch"])
    database.create_engine()
    meili.validate_indexes(database)
    database.validate_tables()
    return database, meili


def get_schema(schema_path: str) -> Json:
    """Loads the schema from a file and returns it"""
    with open(schema_path, "r") as schema_file:
        schema: Json = json.load(schema_file)
    if not schema:
        raise ValueError("Schema file was empty or failed to open.")
    return schema


def validate_json(json_data: Json, schema_path: str) -> None:
    """Validates a Json dict against the schema"""
    script_schema: Json = get_schema(schema_path)
    try:
        validate(instance=json_data, schema=script_schema)
    except jsonschema.exceptions.ValidationError as error:
        logging.critical(error)


def export_tables(db_con: DatabaseConn, meili: MeilisearchConn,
                  max_chunk_size: int) -> None:
    """Exports all the tables to their respective MeiliSearch indexes in chunks of
    5000 elements at a time"""
    for idx, table_name in enumerate(db_con.tables):
        logging.info("Starting the export of table %s", table_name)
        primary_key_name: str = db_con.get_primary_key_name(table_name)
        meili_index: str = meili.indexes[idx]
        total_size: int = db_con.database_engine.execute(
            select([func.count()]).select_from(
                db_con.metadata.tables[table_name])).scalar()
        if total_size < max_chunk_size:
            values: List = [
                dict(row) for row in db_con.database_engine.execute(
                    db_con.metadata.tables[table_name].select())
            ]
            meili.upload_data_to_index(meili_index, values, primary_key_name)
        else:
            chunks: int = ceil(total_size / max_chunk_size)
            for chunk in range(chunks):
                values: List = [
                    dict(row) for row in db_con.database_engine.execute(
                        select(["*"]).select_from(
                            db_con.metadata.tables[table_name]).offset(
                                chunk * max_chunk_size).limit(max_chunk_size))
                ]
                meili.upload_data_to_index(meili_index, values,
                                           primary_key_name)
        logging.info("Finished exporting table %s to index %s", table_name,
                     meili_index)


def run_with_config_file(file_path: str, schema_path: str,
                         max_chunk_size: int):
    """Loads the configuration from a given path,
    and runs the export process
    """
    with open(file_path) as json_file:
        data: Json = json.load(json_file)
        db_conn, meili_conn = create_connection_from_dict(data, schema_path)
        export_tables(db_conn, meili_conn, max_chunk_size)
    logging.info("Finished exporting all tables to Meilisearch")


def main():
    """
    Parses the command line arguments to ensure that a valid
    config file is passed
    """
    logging.getLogger().setLevel(logging.INFO)
    parser = argparse.ArgumentParser(
        description="Exports tables from a database to a Meilisearch instance")
    parser.add_argument(
        "-c",
        "--config",
        dest="path",
        metavar="FILE_PATH",
        action="store",
        help="Specifies the path for the config file",
        required=True,
        type=str,
    )
    parser.add_argument(
        "-s",
        "--schema",
        dest="schema",
        metavar="SCHEMA_FILE_PATH",
        action="store",
        help="Specifies the path for the schema file",
        required=False,
        type=str,
    )
    parser.add_argument(
        "-cs",
        "--chunk_size",
        dest="chunk_size",
        metavar="CHUNK_SIZE",
        action="store",
        help="Specifies the max number of rows to export in a single chunk",
        required=False,
        type=int,
    )
    args = parser.parse_args()
    file_path: str = args.path
    schema_path: str = "schema.json"
    max_chunk_size: int = 5000

    if args.chunk_size:
        max_chunk_size = args.chunk_size
    if args.schema:
        schema_path = args.schema

    if not isfile(schema_path):
        logging.critical("Specified schema file path is not a valid file!")
        sys_exit(2)

    if not isfile(file_path):
        logging.critical("Specified config file path is not a valid file!")
        sys_exit(2)

    run_with_config_file(file_path, schema_path, max_chunk_size)


if __name__ == "__main__":
    main()
