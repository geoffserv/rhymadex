# rhymadex_builder.py
# Build Rhymadex database schema if it doesn't exist
# Upgrade Rhymadex database schema if needed
# Build or re-build source text data structure

from Phyme import Phyme
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
                user=self.username,
                password=self.password,
                host=self.host,
                port=int(self.port)
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
        if not self.query("SHOW DATABASES LIKE '{}'", None, self.database).fetchall():
            # TODO maybe a better way to check existence of a mariadb database?
            # Did not find the database, so create it
            print("INFO- Database not found.  Creating.")
            self.query("CREATE DATABASE `{}`", None, self.database)
            self.query("USE `{}`", None, self.database)

            print("INFO- Creating table tblSources")
            # tblSources holds info about each text data source
            self.query("CREATE TABLE `tblSources` \
                        (`id` INT AUTO_INCREMENT NOT NULL, \
                         `sourceName` VARCHAR(255) NOT NULL, \
                         `dtmInit` DATETIME NOT NULL, \
                         PRIMARY KEY (`id`))")

            print("INFO- Creating table tblVersion")
            # tblVersions stores the version of the overall database schema
            self.query("CREATE TABLE `tblVersion` \
                        (`versionNum` MEDIUMINT NOT NULL, \
                         `dtmInit` DATETIME NOT NULL, \
                         PRIMARY KEY (`versionNum`))")

            # The rhymadex database schema version itself
            self.query("INSERT INTO `tblVersion` (versionNum, dtmInit) VALUES (?, NOW())",
                       (self.schemaCurrentVersion,), "", True)

            print("INFO- Creating table tblLines")
            # Create tblLines to hold lyric lines
            # Use a surrogate PRIMARY KEY `id`
            # lastWord is VARCHAR(34) ("Supercalifragilisticexpialidocious")
            # line is VARCHAR(255), the longest lyric line we'll consider.  Make it unique
            self.query("CREATE TABLE `tblLines` \
                        (`id` INT NOT NULL AUTO_INCREMENT, \
                         `lastWord` VARCHAR(34) NOT NULL, \
                         `line` VARCHAR(255) NOT NULL, \
                         `syllables` SMALLINT NOT NULL, \
                         `source` INT NOT NULL, \
                         PRIMARY KEY (`id`), \
                         UNIQUE KEY (`line`), \
                         KEY (`lastWord`), \
                         CONSTRAINT `fk_line_source` FOREIGN KEY (`source`) REFERENCES `tblSources` (`id`) \
                         ON DELETE CASCADE \
                         ON UPDATE RESTRICT)")

            print("INFO- Creating table tblRhymes")
            # TODO Definitely a better way to handle this
            # other than duplicating the rhyme dictionary in to my own database
            # and this structure also will create duplicates (cat -> fat, fat -> cat)
            # But I want to avoid using a rhyme package during runtime later, on the 'net
            self.query("CREATE TABLE `tblRhymes` \
                        (`word` VARCHAR(34) NOT NULL, \
                         `rhyme` VARCHAR(34) NOT NULL, \
                         PRIMARY KEY (`word`, `rhyme`))")

        else:
            # The database exists.  Open it
            print("INFO- Database found.  Opening.")
            self.query("USE `{}`", None, self.database)

            # Check most recent schema version
            currentVersion = self.query("SELECT max(`versionNum`) AS `versionNum`, \
                                         `dtmInit` FROM `tblVersion`").fetchall()[0]
            print("INFO- Found rhymadex version", currentVersion[0], "created", currentVersion[1])

class rhymadex:
    def __init__(self, rhymadexDB):
        print("INFO- Initializing Rhymadex")
        self.rhymadexDB = rhymadexDB

    def buildRhymadex(self, sourceFile):
        print("INFO- Opening file for processing:", sourceFile)

        try:
            sourceTextFile = open(sourceFile, 'r')
        except OSError as e:
            print("ERROR- OSError when opening file for reading:", sourceFile)
            print("ERROR- OSError:", e)
            print("Nothing more to do.  Exiting")
            exit()

        # TODO Brainstorm on the kinds of manipulation to perform on the input text

        # I consider a couple approaches:
        #   Load text in to the database relatively un-manipulated and intact, and perform
        #     sanitization during output, giving the user more control.  For example, maybe they
        #     really want there to be a lot of sentence-initial conjunctions.
        #     This also means that later decisions on what is "good" can be made without rebuilding
        #     the whole rhymadex database for potentially hundreds of source texts.
        #   vs.
        #   Thoroughly sanitize text before loading in to the database, so that hopefully all
        #     of the candidate sentences are stored in the cleanest and most useful way possible,
        #     as determined by me, now.

        # I'm going to attempt to sanitize pre-database for two related reasons:
        #   I don't want to be spending time on the front-end doing syllable calculations and don't
        #     want to make the webservers deal with a lot of memory load/processing.
        #   I'm hoping to leverage the DBMS for a lot of the lookup/join/sort load, so I'll be calculating
        #     syllable counts ahead of time and storing them in the database.  Leaving a lot of clutter in the
        #     rhymadex database means I'll have to post-process every line at runtime to scrub out the junk
        #     and then calculate syllables again, potentially millions+ of times for a single pageload

        # Brainstorm ruleset for input processing:

        # Remove newlines because they're irrelevant.
        #   Strip out all non-printable ANSI entirely
        #   Strip out all non-ANSI as well.  Not gunna try and rhyme asian language unicode for ex.
        #   Surprisingly, in testing I've found the rhyme dictionary producing matches for some non-English
        #     Latin language words, so maybe OK to leave accented Latin chars in the source "just in case".
        #     It will be discarded later if there are no rhymes anyway, and it could make for some
        #     interesting results if there are matchable rhymes.
        # Remove almost all non-grammatical punctuation
        #   ~ ` @ # ^ & * - _ = + [ ] { } | \ < > /
        #   What about punctuation that may indicate grammatical shorthand?
        #   @ & - + = ("at", "and", "minus", "plus", "equals" ...)
        #   Like "Meet me @ the coffee shop" or "This & that" or "RSVP for myself +1"
        #   Maybe I can detect this by checking for "(words)(space)&(space)(words)
        #     and determine whether it's just garbage/formatting vs. grammatical punctuation
        #     and then do word replacement so the rhyme+syllable calculations will work
        # What about numbers?  In testing, page numbers, verse numbers, etc get mixed up in the text
        #   Remove all non-words from the beginning of every line.
        #   Nothing useful will start with any of the above punctuation nor any grammatical punctuation
        #   Such as , . ; : ? !
        #   Valid lines may start with a number, but often in my testing it's part of a chapter number or
        #     page number like "1 It was the best of times" and that mucks up what could have been
        #     interesting output.  A valid case might be like "2 is company but 3 is a crowd", in which case
        #     stripping the sentence-initial digit mucks up the output.
        #     Maybe look for "(word)(grammatical punctuation)(space/s)(number)(space)(word)" as the only
        #     potentially valid sentence-initial number case
        # What about em dash? yen sign? And big weird variety of printable ANSI
        #   Maybe the best approach is to only consider what is useful and strip out everything else
        #   Ultimately if someone trys to stuff a bunch of non-language garbage in to the rhymadex
        #     the output will be a bunch of non-language garbage
        # Sentence-initial non-word exception cases: " ' ( $
        # Comma-conjunctions like ", and" ", but" ", because" ", so"
        #   Later I'll be splitting on commas, meaning a LOT of segments will begin with a conjunction
        #   Sometimes this is fruitful, but most of the time it means most/every line starts with "and"
        #   Poetically, I propose that removing sentence-initial conjunctions saves useful syllables and
        #     allows for a wider range of interpretability in many cases.

        sourceTextBlob = sourceTextFile.read().replace('\n', ' ')
        sourceTextFile.close()

        sourceSentences = re.split('[,.!]', sourceTextBlob)  # Break it apart at every comma,period,ep

        print("INFO- Deduplicating sentence list ...")

        debugTotalLinesSeen = len(sourceSentences)
        sourceSentences = list(dict.fromkeys(sourceSentences))
        debugTotalDiscardedLines = debugTotalLinesSeen - len(sourceSentences)

        print("INFO- Building lyric dictionary ...")

        # TODO continue work from here..
        # better input cleanup

if __name__ == "__main__":
    rhymadexDB = rhymadexMariaDB('mariadb.cfg')
    rhymadexDB.initSchema()
    rhymadex = rhymadex(rhymadexDB)
    rhymadex.buildRhymadex("something.txt")