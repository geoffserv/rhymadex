# rhymadex_builder.py
# Build Rhymadex database instance if it doesn't exist
# Upgrade Rhymadex database if needed
# Build or re-build source text data structure

import configparser
import mariadb
import sys

class rhymadexMariaDB:
    def __init__(self, configfile):
        # Using configparser to read configfile for database credentials
        # Can refactor later to use env or flask or whatever.
        # __init__ get database credentials and connect
        dbConfig = configparser.ConfigParser()
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
            self.connection = mariadb.connect(
                user = self.username,
                password = self.password,
                host = self.host,
                port = int(self.port)
            )
        except mariadb.Error as e:
            print(f"MariaDB connection error: {e}")
            sys.exit("Database connection error.  Exiting.")

        self.cursor = self.connection.cursor()

    def query(self, query):
        try:
            self.cursor.execute(query)
            return(self.cursor)
        except mariadb.Error as e:
            # Stop immediately on an error
            print(f"MariaDB query error: {e}")
            print("  While executing query:", query)
            sys.exit("Database query error.  Exiting.")

if __name__ == "__main__":
    db = rhymadexMariaDB('mariadb.cfg')

