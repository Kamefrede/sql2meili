# SQL2Meili

Installation
---
`$ pipenv install sql2meili`

By default sql2meili comes with database engines for both PostgreSQL, MySQL and SQLite

If you want to use any other database compatible with SQLAlchemy, just run
`$ pipenv install <database_engine>` or modify the Pipfile to add it there.

A list of engines and supported databases can be found here: https://docs.sqlalchemy.org/en/13/core/engines.html


Configuration
---
A configuration example can be found below or by looking at the `config_example.json` file

SQL2Meili validates the configuration file you provide it against the schema defined in `schema.json`

It is possible to provide your own schema via a config flag(check Usage tab below) but keep in mind that
you will probably need to make some changes to the script if you deviate too much from the default schema.

```json
{
  "database": {
    "adapter": "postgresql",
    "host": "localhost",
    "port": 5432,
    "username": "postgres",
    "password": "password",
    "database_name": "movies",
    "tables": ["movies"]
  },
  "meilisearch": {
    "host": "http://127.0.0.1:7700",
    "api_key": "verycoolapikey",
    "indexes": []
  }
}
```

Usage
---
To run an export with the default schema and a default chunk size of 5000 rows, you just need to supply the `--config` ( `-c` ) flag along with the file path
for the config file.

```bash
$ python3 sql2meili.py -h
usage: sql2meili.py [-h] -c FILE_PATH [-s SCHEMA_FILE_PATH] [-cs CHUNK_SIZE]

Exports tables from a database to a Meilisearch instance

required arguments:
  -c FILE_PATH, --config FILE_PATH
                        Specifies the path for the config file
optional arguments:
  -h, --help            show this help message and exit
  -s SCHEMA_FILE_PATH, --schema SCHEMA_FILE_PATH
                        Specifies the path for the schema file
  -cs CHUNK_SIZE, --chunk_size CHUNK_SIZE
                        Specifies the max number of rows to export in a single chunk
```

```
$ python3 sql2meili.py --config config_example.json
INFO:root:Connecting to SQL database...
INFO:root:Connected to database at Engine(postgresql://postgres:***@localhost:5432/movies)
INFO:root:Starting the export of table movies
INFO:root:Exported 5000 rows to Meilisearch index movies
INFO:root:Exported 5000 rows to Meilisearch index movies
INFO:root:Exported 5000 rows to Meilisearch index movies
INFO:root:Exported 4654 rows to Meilisearch index movies
INFO:root:Finished exporting table movies to index movies
INFO:root:Finished exporting all tables to Meilisearch
INFO:root:You can browse the exported data at http://127.0.0.1:7700
```

To select a custom schema you can use the `--schema` (`-s`) flag and the file path to the schema file.

Additionally, you can also define the chunk size (how many rows get exported at once) via the `--chunk_size`(`-cs`) flag

It is recommended that you lower the chunk size if you're dealing with tables that contain a large amount of data per row.

Here's the same export as earlier but with a bigger chunk size
```
$ python3 sql2meili.py --config config_example.json --chunk_size 10000
INFO:root:Connecting to SQL database...
INFO:root:Connected to database at Engine(postgresql://postgres:***@localhost:5432/movies)
INFO:root:Starting the export of table movies
INFO:root:Exported 10000 rows to Meilisearch index movies
INFO:root:Exported 9654 rows to Meilisearch index movies
INFO:root:Finished exporting table movies to index movies
INFO:root:Finished exporting all tables to Meilisearch
INFO:root:You can browse the exported data at http://127.0.0.1:7700
```