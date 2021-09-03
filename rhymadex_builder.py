# rhymadex_builder.py
# Build Rhymadex database schema if it doesn't exist
# Upgrade Rhymadex database schema if needed
# Build or re-build source text data structure

import configparser
import mariadb
import sys

class rhymadexMariaDB:
    def __init__(self, configfile):
        # Using configparser to read configfile for database credentials
        # Can refactor later to use env or flask or whatever.
        # __init__ get database credentials and connect

        # By default this expects mariadb.cfg in the same directory as this script
        # In the format:
        #
        # [mariadb]
        # username = mariadb_username
        # password = mariadb_password
        # host = mariadb_host
        # database = rhymadex
        # port = mariadb_port (typically 3306)

        dbConfig = configparser.ConfigParser()

        # Track the rhymadexMariaDB schema in a simple way: an int incrementing from 1
        # Use this to track whether the target database schema matches what I expect as
        #   I add changes, features, and whatnot
        self.schemaCurrentVersion = 1

        if dbConfig.read(configfile):
            try:
                self.username = dbConfig['mariadb']['username']
                self.password = dbConfig['mariadb']['password']
                self.host = dbConfig['mariadb']['host']
                self.database = dbConfig['mariadb']['database']
                self.port = dbConfig['mariadb']['port']
            except:
                sys.exit("Could not find database credential attributes in configfile.  Exiting.")
        else:
            sys.exit("Could not open configfile to read database credentials.  Exiting.")

        try:
            # Connect but don't open a database yet
            print("INFO- Connecting to database server:", self.host, "port", self.port, "as", self.username)
            self.connection = mariadb.connect(
                user = self.username,
                password = self.password,
                host = self.host,
                port = int(self.port)
            )
        except mariadb.Error as e:
            print("MariaDB connection error: ", e)
            sys.exit("Database connection error.  Exiting.")

        self.cursor = self.connection.cursor()

    def query(self, query, queryParams=None, queryIdentifier="", commitNow=False):
        # My little query wrapper method.
        # I want to wrap my queries with a db class method so I'm not directly using any particular DB's
        #   methods directly in my code.  This way I can more easily change DB technology later.
        # Query parameterization CAN NOT BE USED with identifiers like table names, field names, database names.
        #   Which is a monster headache.  Nobody seems to have a good answer.
        # So, for inserting user-specified identifiers like dbname (gathered from the script config file),
        #   I guess just use for ex.
        #   db.query("SHOW DATABASES LIKE '{}'".format(db.escape_string(dbname))")
        #   But what can I do?  Hard-coding the dbname/etc feels icky.
        # For values (field values in SELECT / INSERT / UPDATES etc) use the queryParams.

        try:
            self.cursor.execute(query.format(self.connection.escape_string(queryIdentifier)), queryParams)
            if commitNow: self.connection.commit() # Gotta commit after INSERTs, etc.  Or, DIY
            return(self.cursor)
        except mariadb.Error as e:
            # Stop immediately on an error
            print("MariaDB query error: ", e)
            print("  While executing query:", query)
            print("  With paramaters:", queryParams)
            sys.exit("Database query error.  Exiting.")

    def initSchema(self):
        # Check if the target database already exists
        print("INFO- Checking for database", self.database)
        if len(self.query("SHOW DATABASES LIKE '{}'", None, self.database).fetchall()) == 0:
            # TODO maybe a better way to check existence of a mariadb database?
            # Did not find the database, so create it
            print("INFO- Database not found.  Creating.")
            self.query("CREATE DATABASE `{}`", None, self.database)
            self.query("USE `{}`", None, self.database)

            # Create schema table to track schema version
            self.query("CREATE TABLE tblSchemaVersion (versionNum mediumint primary key, dtmInit datetime)")
            self.query("INSERT INTO tblSchemaVersion (versionNum, dtmInit) values (?, now())",
                       (self.schemaCurrentVersion,), "", True)

        else:
            # The database exists.  Open it
            print("INFO- Database found.  Opening.")
            self.query("USE `{}`", None, self.database)

            # Check most recent schema version
            currentVersion = self.query("SELECT max(versionNum) AS versionNum, dtmInit FROM tblSchemaVersion").fetchall()[0]
            print(currentVersion)



if __name__ == "__main__":
    db = rhymadexMariaDB('mariadb.cfg')
    db.initSchema()
