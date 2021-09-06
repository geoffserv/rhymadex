# rhymadex_builder.py
# Build Rhymadex database schema if it doesn't exist
# Upgrade Rhymadex database schema if needed
# Build or re-build source text data structure

from Phyme import Phyme
import configparser
import mariadb
import sys
import re
import syllables
import time
import string

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
            except configparser.Error as e:
                print("ERROR- Configparser error:", e)
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
            print("ERROR- MariaDB connection error: ", e)
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
            return self.cursor
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
                         UNIQUE KEY (`sourceName`), \
                         PRIMARY KEY (`id`))")

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

            print("INFO- Creating table tblVersion")
            # tblVersions stores the version of the overall database schema
            self.query("CREATE TABLE `tblVersion` \
                        (`versionNum` MEDIUMINT NOT NULL, \
                         `dtmInit` DATETIME NOT NULL, \
                         PRIMARY KEY (`versionNum`))")

            # The rhymadex database schema version itself
            self.query("INSERT INTO `tblVersion` (versionNum, dtmInit) VALUES (?, NOW())",
                       (self.schemaCurrentVersion,), "", True)

        else:
            # The database exists.  Open it
            print("INFO- Database found.  Opening.")
            self.query("USE `{}`", None, self.database)

            # Check most recent schema version
            currentVersion = self.query("SELECT max(`versionNum`) AS `versionNum`, \
                                         `dtmInit` FROM `tblVersion`").fetchall()[0]
            print("INFO- Found rhymadex version", currentVersion[0], "created", currentVersion[1])

            if not int(currentVersion[0]) == int(self.schemaCurrentVersion):
                print("ERROR- Database schema version doesn't match expected version:", self.schemaCurrentVersion)
                exit("Won't continue with mismatching schema.  Exiting.")

            # At this point, found the database, the schema version table, and the reported schema
            #   version matches what I'm looking for.  Assuming now that everything in the database is
            #   where I expect and how I expect it.  If not.. well.. welcome to crash town.

class rhymadex:
    def __init__(self, rhymadexDB):
        print("INFO- Initializing Rhymadex")
        self.rhymadexDB = rhymadexDB

        self.rhyme = Phyme()

        self.debugTotalLinesProcessed = 0  # Including garbage lines discarded during processing
        self.debugTotalWordsProcessed = 0
        self.debugTotalSyllablesSeen = 0  # Total count of every syllable of every word we've seen
        self.debugTotalDiscardedLines = 0  # Discarded dupes, unrhymables, out of meter, etc.  All discarded lines
        self.debugTotalUniqueLines = 0  # Unique lines we've seen
        self.debugTotalUnrhymable = 0  # LastWords encountered which have no data in the rhyme dictionary
        self.debugTotalOutOfMeter = 0  # Lines that don't match our desired meter
        self.debugWontFitLines = 0 # Under 1 or over 256 char lines, won't fit in the DB
        self.debugProcStartTime = 0  # Clocks for tracking execution time
        self.debugProcEndTime = 0

    def lineCleaner(self, line):
        # Clean up a line of text before inserting it to the database
        # Return a nice, clean line

        # Only deal in printables.
        line = "".join(aChar for aChar in line if aChar in string.printable)

        # Only deal in lowers.
        line = line.lower()

        # Starts with a letter, then whatever, then ends in a "word character" (including digits)
        # Truncates all non-letter junk at the start and end, including punctuation
        line = "".join(re.findall(r"[a-z]+.*\w+", line))

        # Remove almost all non-grammatical punctuation
        line = re.sub(r"[~`#^*_\[\]{}|\\<>/]+", "", line)
        line = re.sub(r"@", "at", line)
        line = re.sub(r"&", "and", line)
        line = re.sub(r"=", "equals", line)
        line = re.sub(r"\+", "plus", line)

        if line:
            return line
        else:
            return None

    def buildRhymadex(self, sourceFile):

        self.debugProcStartTime = time.time()

        print("INFO- Opening file for processing:", sourceFile)

        try:
            # TODO could actually do some kind of sane and safe handling of file encoding
            sourceTextFile = open(sourceFile, 'r', encoding = "ISO-8859-1")
            sourceTextBlob = sourceTextFile.read().replace('\n', ' ')
            sourceTextFile.close()
        except OSError as e:
            print("ERROR- OSError when opening file for reading:", sourceFile)
            print("ERROR- OSError:", e)
            exit("Nothing more to do.  Exiting.")

        # Capture the data source and get the source primary key ID from the database
        sourceId = self.rhymadexDB.query("INSERT INTO `tblSources` \
                              (`sourceName`, `dtmInit`) \
                              VALUES \
                              (?, now()) \
                              ON DUPLICATE KEY UPDATE \
                              `dtmInit`=now()", (sourceFile,), "", True).lastrowid

        # Break sentences apart on: , . ! ? ; : tabspace
        sourceSentences = re.split('[,.!?;:\t]', sourceTextBlob)

        print("INFO- Deduplicating sentence list ...")

        self.debugTotalLinesSeen = len(sourceSentences)
        sourceSentences = list(dict.fromkeys(sourceSentences))
        self.debugTotalDiscardedLines = self.debugTotalLinesSeen - len(sourceSentences)

        print("INFO- Building lyric dictionary ...")
        print("INFO- Entries found:", len(sourceSentences))

        for sourceSentence in sourceSentences:

            self.debugTotalLinesProcessed += 1

            sourceSentence = self.lineCleaner(sourceSentence)

            if (sourceSentence and (len(sourceSentence) < 256)):

                sourceSentenceWords = sourceSentence.split()
                if not sourceSentenceWords: continue  # Lil' hack for now, TODO refactor input checking
                lastWord = sourceSentenceWords[-1]

                self.debugTotalWordsProcessed += len(sourceSentenceWords)

                # Sentence Syllable Estimation
                # Can only estimate syllable count per-word, so run the estimator on every word in the sentence and accumulate
                sourceSentenceSyllables = 0
                for sourceSentenceWord in sourceSentenceWords:
                    sourceSentenceSyllables += syllables.estimate(sourceSentenceWord)
                    self.debugTotalSyllablesSeen += sourceSentenceSyllables

                try:
                    # What comes back is a dictionary of syllable counts with corresponding lists of rhyme words.
                    # Kinda don't care about rhyme word syllable counts right now, so just collapse this to values() only
                    sourceSentenceRhymeList = self.rhyme.get_perfect_rhymes(lastWord).values()
                    # Now this is a list of lists, better to collapse to a single list of all the words
                    sourceSentenceRhymeList = [item for sublist in sourceSentenceRhymeList for item in sublist]
                # Maybe someday do fancy things with lastWord syllable count ...
                except KeyError:
                    # Can't find any rhyming words in the dictionary, so just discard this entirely and move along
                    self.debugTotalUnrhymable += 1
                    self.debugTotalDiscardedLines += 1
                    continue  # Move along.  Nothing to see here.

                # Insert lyrics, rhymes and syllables here
                self.rhymadexDB.query("INSERT INTO tblLines \
                                      (lastWord, line, syllables, source) \
                                      VALUES (?, ?, ?, ?) \
                                      ON DUPLICATE KEY UPDATE `line` = ?",
                                      (lastWord, sourceSentence, int(sourceSentenceSyllables), int(sourceId), sourceSentence), "", True)
                self.debugTotalUniqueLines += 1

                if ((self.debugTotalUniqueLines == 1) or (self.debugTotalUniqueLines % 10000) == 0):
                    print("")
                    print("INFO- Processed: ", end="")
                if ((self.debugTotalUniqueLines == 1) or self.debugTotalUniqueLines % 1000 == 0):
                    print(self.debugTotalUniqueLines, ".. ", end="")
            else:
                self.debugWontFitLines += 1
                self.debugTotalDiscardedLines += 1

        print("Done.")
        self.debugProcEndTime = time.time()

        print("INFO- Completed building lyric dictionary in", self.debugProcEndTime - self.debugProcStartTime, "seconds")
        print("INFO- Total Lines Processed:", self.debugTotalLinesProcessed)
        print("INFO- Total Words Processed:", self.debugTotalWordsProcessed)
        print("INFO- Total Syllables seen:", self.debugTotalSyllablesSeen)
        print("INFO- Total Discarded lines:", self.debugTotalDiscardedLines)
        print("INFO- Total Un-Rhymable words:", self.debugTotalUnrhymable)
        print("INFO- Total Out-Of-Meter lines:", self.debugTotalOutOfMeter)
        print("INFO- Total Won't-Fit-in-DB lines:", self.debugWontFitLines)
        print("INFO- Total Unique lyric lines available:", self.debugTotalUniqueLines)
        print("INFO- Lyric Dictionary is ready!")

if __name__ == "__main__":
    rhymadexDB = rhymadexMariaDB('mariadb.cfg')
    rhymadexDB.initSchema()
    rhymadex = rhymadex(rhymadexDB)
    rhymadex.buildRhymadex("textsources/bible/bible.txt")