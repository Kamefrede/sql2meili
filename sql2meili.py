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

max_chunk_size: int = 5000
logging.getLogger().setLevel(logging.INFO)


class DatabaseConn:
    database_url: str
    tables: List[str]
    database_engine: engine
    metadata: MetaData

    def __init__(self, adapter: str, host: str, port: int, username: str,
                 password: str, database_name: str, tables: List[str]) -> None:
        self.tables = tables
        self.database_url = f"{adapter}://{username}:{password}@{host}:{port}/{database_name}"
        self.database_engine = create_engine(self.database_url)
        self.metadata = MetaData()
        self.metadata.reflect(bind=self.database_engine)

    def get_engine(self) -> engine:
        return self.database_engine

    def get_tables(self) -> List[str]:
        return self.tables

    def get_tables_size(self) -> int:
        return len(self.tables)


class MeilisearchConn:
    indexes: List[str]
    meilisearch_client: meilisearch.Client

    def __init__(self, host: str, api_key: str, indexes: List[str]) -> None:
        self.indexes = indexes
        self.meilisearch_client = meilisearch.Client(host, api_key)

    def get_indexes(self) -> List[str]:
        return self.indexes

    def get_client(self) -> meilisearch.Client:
        return self.meilisearch_client

    def get_indexes_size(self) -> int:
        return len(self.indexes)


def create_connection_from_dict(
        json_data: Json) -> (DatabaseConn, MeilisearchConn):
    validate_json(json_data)
    database = DatabaseConn(**json_data['database'])
    meili = MeilisearchConn(**json_data['meilisearch'])
    validate_indexes(database, meili)
    validate_tables(database)
    return database, meili


def get_schema() -> Json:
    with open('schema.json', 'r') as schema_file:
        schema = json.load(schema_file)
    if not schema:
        raise ValueError("Schema file was empty or failed to open.")
    return schema


def validate_json(json_data: Json) -> None:
    script_schema = get_schema()
    try:
        validate(instance=json_data, schema=script_schema)
    except jsonschema.exceptions.ValidationError as error:
        logging.critical(error)


def validate_indexes(db: DatabaseConn, meili: MeilisearchConn) -> None:
    diff: int = db.get_tables_size() - meili.get_indexes_size()
    if diff == 0:
        return
    if diff < 0:
        raise jsonschema.exceptions.ValidationError(
            "There cannot be more indexes than tables defined.")
    else:
        for table in db.get_tables()[db.get_tables_size() - diff:]:
            meili.get_indexes().append(table)

    indexes_not_present = list(
        filter(
            lambda idx: idx not in list(
                map(lambda index: index['uid'],
                    meili.get_client().get_indexes())), meili.get_indexes()))
    if len(indexes_not_present) > 0:
        raise KeyError(
            f"The following indexes defined in the config file are not present: {indexes_not_present}"
        )


def validate_tables(db: DatabaseConn) -> None:
    tables_not_present = list(
        filter(lambda tab: tab not in db.metadata.tables, db.get_tables()))
    if len(tables_not_present) > 0:
        raise KeyError(
            f"The following tables defined in the config file are not present: {tables_not_present}"
        )


def push_table_to_meili(meili: MeilisearchConn, index: str, data: List,
                        primary_key: str):
    meili.get_client().get_index(index).update_documents(
        data, primary_key=primary_key)
    logging.info(f"Exported {len(data)} rows to Meilisearch index {index}")
    return


def export_tables(db: DatabaseConn, meili: MeilisearchConn) -> None:
    for idx, table_name in enumerate(db.get_tables()):
        logging.info(f"Starting the export of table {table_name}")
        primary_key_name: str = get_primary_key_name(db, table_name)
        meili_index: str = meili.get_indexes()[idx]
        total_size: int = db.get_engine().execute(
            select([func.count()
                    ]).select_from(db.metadata.tables[table_name])).scalar()
        if total_size < max_chunk_size:
            values: List = [
                dict(row) for row in db.get_engine().execute(
                    db.metadata.tables[table_name].select())
            ]
            push_table_to_meili(meili, meili_index, values, primary_key_name)
        else:
            chunks: int = ceil(total_size / max_chunk_size)
            for chunk in range(chunks):
                values: List = [
                    dict(row) for row in db.get_engine().execute(
                        select(["*"]).select_from(
                            db.metadata.tables[table_name]).offset(
                                chunk * max_chunk_size).limit(max_chunk_size))
                ]
                push_table_to_meili(meili, meili_index, values,
                                    primary_key_name)
        logging.info(
            f"Finished exporting table {table_name} to index {meili_index}")
    return


def get_primary_key_name(db: DatabaseConn, table_name: str):
    return next(
        map(
            lambda tab: tab.primary_key.columns.values()[0].name,
            filter(lambda tb: tb.name == table_name,
                   db.metadata.sorted_tables)))


def print_usage():
    print("Incorrect options.")
    print("The usage is:")
    print("python sql2meili.py --config <filename>")
    print("python sql2meili.py -c <filename>")
    print("python sql2meili.py --help")
    print("python sql2meili.py -h")


def run_with_config_file(file_path: str):
    with open(file_path) as json_file:
        data: Json = json.load(json_file)
        db_conn, meili_conn = create_connection_from_dict(data)
        export_tables(db_conn, meili_conn)
    logging.info("Finished exporting all tables to Meilisearch")


def main():
    parser = argparse.ArgumentParser(
        description="Exports tables from a database to a Meilisearch instance")
    parser.add_argument('-c',
                        '--config',
                        dest="path",
                        metavar="FILE_PATH",
                        action="store",
                        help='Specifies the path for the config file',
                        required=True)
    args = parser.parse_args()

    file_path = args.path
    if not isfile(file_path):
        logging.critical("Specified path is not a valid file!")
        sys_exit(2)
    run_with_config_file(file_path)


if __name__ == '__main__':
    main()
