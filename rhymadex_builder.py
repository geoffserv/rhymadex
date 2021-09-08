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
        # I want to wrap my queries with a db class method so I'm not using any particular DB's
        #   methods directly in my code.  This way I can more easily change DB technology later.
        # Query parameterization CAN NOT BE USED with identifiers like table names, field names, database names.
        #   Which is a monster headache.  Nobody seems to have a good answer.
        # So, for inserting user-specified identifiers like dbname (gathered from the script config file),
        #   I guess just use for ex.
        #   db.query("SHOW DATABASES LIKE '{}'", None, self.someIdentifier)
        #   and it will be string-format substituted in.  Can mix-and-match with queryParams too for ex.
        #   db.query("INSERT INTO `{}` (`someCol`) VALUES (?)", (someColValue,), someIdentifier, True)
        #   But what can I do?  Hard-coding the dbname/etc feels icky.
        #   The queryIdentifier gets escape_string'ed so that's at least better than nothing.
        #   If you have a good suggestion here please give me a PR!!
        # For values (field values in SELECT / INSERT / UPDATES etc) use the queryParams.
        # If you wanna just commit after a batch of un-committed queries, send nothing as the query for ex.
        #   db.query(None, None, "", True)

        try:
            if query: self.cursor.execute(query.format(self.connection.escape_string(queryIdentifier)), queryParams)
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
            #   The largest English "word" I'd ever expect to encounter and store ..
            # line is VARCHAR(255), the longest lyric line we'll consider.  Make it unique.
            self.query("CREATE TABLE `tblLines` \
                        (`id` INT NOT NULL AUTO_INCREMENT, \
                         `firstWord` VARCHAR(34) NOT NULL, \
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

            print("INFO- Creating table tblRhymePools")
            # RhymePools provides a unique ID used to group RhymeWords in to "pools" of rhyme-ability
            # `rhymeHint` contains a right-hand portion of the word:
            #   (optional vowel(s), optional const(s), required vowel(s), optional const(s), EndOfWord)
            #   just kinda for fun and to see what the results look like
            # `seedWord` is the first word encountered that generated this pool, also just for fun.
            self.query("CREATE TABLE `tblRhymePools` \
                        (`id` INT AUTO_INCREMENT NOT NULL, \
                         `rhymeHint` VARCHAR(34), \
                         `seedWord` VARCHAR(34), \
                         PRIMARY KEY (`id`))")

            print("INFO- Creating table tblRhymeWords")
            # RhymeWords stores each unique word+rhymeType and links to a rhymePool
            # My idea is that words are part of pools wherein all words in a pool rhyme with each-other
            # I have no proof that the idea proves always true but it will be a good starting point.
            self.query("CREATE TABLE `tblRhymeWords` \
                        (`id` INT AUTO_INCREMENT NOT NULL, \
                         `word` VARCHAR(34) NOT NULL, \
                         `syllables` INT NOT NULL, \
                         `rhymeType` INT NOT NULL, \
                         `rhymePool` INT NOT NULL, \
                         PRIMARY KEY (`id`), \
                         UNIQUE KEY (`word`, `rhymeType`), \
                         CONSTRAINT `fk_rhyme_pool` FOREIGN KEY (`rhymePool`) REFERENCES `tblRhymePools` (`id`) \
                         ON UPDATE RESTRICT)")

            print("INFO- Creating table tblVersion")
            # tblVersions stores the version of the overall database schema
            # If we've made it this far, ostensibly the database schema is set up and ready to go
            #   I'm so optimistic that I'll use a MEDIUMINT
            # Later, check to see what this version is and compare with the global self.schemaCurrentVersion
            #   If that matches up, assume everything is correct & where it should be.
            #   If it matches up but something is broken/wrong with the schema, welcome to crash town.
            self.query("CREATE TABLE `tblVersion` \
                        (`versionNum` MEDIUMINT NOT NULL, \
                         `dtmInit` DATETIME NOT NULL, \
                         PRIMARY KEY (`versionNum`))")

            # Record the rhymadex database schema version
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

        self.debug = {}

        self.debug['TotalLinesProcessed'] = 0  # Including garbage lines discarded during processing
        self.debug['TotalWordsProcessed'] = 0
        self.debug['TotalSyllablesSeen'] = 0  # Total count of every syllable of every word we've seen
        self.debug['TotalDiscardedLines'] = 0  # Discarded dupes, unrhymables, out of meter, etc.  All discarded lines
        self.debug['TotalUniqueLines'] = 0  # Unique lines we've seen
        self.debug['TotalUnrhymable'] = 0  # LastWords encountered which have no data in the rhyme dictionary
        self.debug['WontFitLines'] = 0 # Under 1 or over 256 char lines, won't fit in the DB
        self.debug['ProcStartTime'] = 0  # Clocks for tracking execution time
        self.debug['ProcEndTime'] = 0
        self.debug['DbInsertsLines'] = 0 # Number of tblLines DB INSERTS
        self.debug['DbInsertsRhymeWords'] = 0 # Number of tblRhymeWords DB INSERTS
        self.debug['NewSourceRhymeWords'] = 0 # New source (from lines) rhyme words found on this run

    def lineCleaner(self, line):
        # Clean up a line of text before inserting it to the database
        # Return a nice, clean line

        # Only deal in printables.
        line = "".join(aChar for aChar in line if aChar in string.printable)

        # Only deal in lowers.
        line = line.lower()

        # Starts with a letter, then whatever, then ends in a letter
        # Truncates all non-letter junk at the start and end, including punctuation
        line = "".join(re.findall(r"[a-z]+.*[a-z]+", line))

        # Remove almost all non-grammatical punctuation
        line = re.sub(r"[~`#^*_\[\]{}|\\<>/()]+", "", line)
        line = re.sub(r"@", "at", line)
        line = re.sub(r"&", "and", line)
        line = re.sub(r"=", "equals", line)
        line = re.sub(r"\+", "plus", line)

        if line:
            return line
        else:
            return None

    def buildRhymadex(self, sourceFile):

        self.debug['ProcStartTime'] = time.time()

        print("INFO- Opening file for processing:", sourceFile)

        try:
            # TODO could actually do some kind of sane and safe handling of file encoding
            sourceTextFile = open(sourceFile, 'r', encoding = "ISO-8859-1")
            # sourceTextBlob = sourceTextFile.read().replace('\n', ' ')
            sourceTextBlob = sourceTextFile.read()
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

        # Remove any existing source lines 'cause we're gunna rebuild them now
        deletedLines = self.rhymadexDB.query("DELETE FROM `tblLines` \
                               WHERE (`source`=?)", (sourceId,), "", True).rowcount
        if deletedLines:
            print("INFO- Deleted", deletedLines, "existing source lines from DB before beginning this build.")

        # Break Lines apart on: , . ! ? ; : tabspace
        #   IMO some of the most interesting magic happens on the comma split because it results in
        #   poetic sentence fragments
        sourceLines = re.split('[,.!?;:\t\n]', sourceTextBlob)

        print("INFO- Deduplicating Line list ...")
        # Do that little to-dict and back to-list trick to dedupe all the list items
        self.debug['TotalLinesSeen'] = len(sourceLines)
        sourceLines = list(dict.fromkeys(sourceLines))
        self.debug['TotalDiscardedLines'] = self.debug['TotalLinesSeen'] - len(sourceLines)

        print("INFO- Building lyric dictionary ...")
        print("INFO- Entries found:", len(sourceLines))

        # Keep track of which RhymeWords have been encountered during Rhymadex building
        #   so we don't do a ton of redundant lookups and database writes
        seenRhymeWords = [list(result) for result in
                          self.rhymadexDB.query("SELECT `word` FROM `tblRhymeWords`").fetchall()]
        seenRhymeWords = [item for sublist in seenRhymeWords for item in sublist]

        print("INFO- seenRhymeWords pulled from DB:", len(seenRhymeWords))

        for sourceLine in sourceLines:

            self.debug['TotalLinesProcessed'] += 1

            # Use the lineCleaner on each line first.
            # What comes back will be only printable ANSI with the ends trimmed, everything lowered,
            #   and some common punctuation-to-text replacements done
            sourceLine = self.lineCleaner(sourceLine)

            # Anything longer than 255 won't fit in the DB with this schema.
            #   255's enough for anyone, anyway.  Right?  ... right?
            if (sourceLine and (len(sourceLine) < 256)):

                sourceLineWords = sourceLine.split()
                firstWord = sourceLineWords[0]
                lastWord = sourceLineWords[-1]

                self.debug['TotalWordsProcessed'] += len(sourceLineWords)

                if ((len(firstWord) <= 34) and (len(lastWord) <= 34)):

                    # Line Syllable Estimation
                    # Can only estimate syllable count per-word, so run the estimator on every word in
                    #   the Line and accumulate.  The estimator is really inaccurate but good for POC
                    sourceLineSyllables = 0
                    for sourceLineWord in sourceLineWords:
                        sourceLineSyllables += syllables.estimate(sourceLineWord)
                        self.debug['TotalSyllablesSeen'] += sourceLineSyllables

                    # Assume both the first and last word are rhyme-able unless proven otherwise.
                    # If either are NOT rhyme-able, discard the line entirely.
                    rhymable = True

                    # Look up rhymes for the firstWord and the lastWord
                    for rhymeTarget in [firstWord, lastWord]:
                        # But only if:
                        #   - we haven't encountered an unrhymable in this line so far,
                        #   - AND haven't seen this word before
                        if (rhymable) and (rhymeTarget not in seenRhymeWords):
                            # Record the fact that we've seen it now.
                            seenRhymeWords.append(rhymeTarget)
                            self.debug['NewSourceRhymeWords'] += 1
                            try:
                                # RhymeTypes:
                                #   1 = same vowels and consonants of the same type regardless of voicing (HAWK, DOG)
                                #   2 = same vowels and consonants as well as any extra consonants (DUDES, DUES)
                                #   3 = same vowels and a subset of the same consonants (DUDE, DO)
                                #   4 = same vowels and some of the same consonants,
                                #       with some swapped for other consonants (FACTOR, FASTER)
                                #   5 = same vowels and arbitrary consonants (CASH, CATS)
                                #   6 = not the same vowels but the same consonants (CAT, BOT)
                                # What comes back is a dictionary of syllable counts with
                                #   corresponding lists of rhyme words.
                                rhymeTargetRhymeList = self.rhyme.get_perfect_rhymes(lastWord).values()

                                # The rhymeHint is the segment of the word from the leftmost vowel to the end
                                #   This is a dumb chunky approach but just for fun..
                                #   Might not be unique, might not be anything at all.  Just a hint.  Something to
                                #   look at when browsing the pool.
                                #   It's really only the rhymePool id that matters to me.
                                rhymeHint = (re.findall(
                                             "[aeiou]*[qwrtypsdfghjklzxcvbnm]*[aeiouy]+[qwrtypsdfghjklzxcvbnm]*$",
                                             rhymeTarget) or ["Unknown"])[0]
                                # Establish a new RhymePool for our words to chill out in
                                rhymePoolId = self.rhymadexDB.query("INSERT INTO `tblRhymePools` \
                                                                     (`rhymeHint`, `seedWord`) VALUES \
                                                                     (?, ?)", (rhymeHint, rhymeTarget), "", True).lastrowid
                                # rhymeTargetRhymeList is a list of lists, collapse to a single list of all the words
                                rhymeTargetRhymeList = [item for sublist in rhymeTargetRhymeList for item in sublist]
                                # Add the rhymeTarget to the rhymeTargetRhymeList too so it all gets added
                                #   to the rhymePool together
                                rhymeTargetRhymeList.append(rhymeTarget)
                                for rhymeResult in rhymeTargetRhymeList:
                                    # Iterate through each rhymeResult
                                    # Record that we've seen it so we don't re-calculate rhymes on this again later
                                    seenRhymeWords.append(rhymeResult)
                                    # Strip out non-characters.  Some of the returned results have (1) and other crap
                                    rhymeResult = re.findall("[a-z]*", rhymeResult)[0]
                                    # Estimate syllables
                                    rhymeResultSyllables = syllables.estimate(rhymeResult)
                                    # And insert to our rhymeList
                                    self.rhymadexDB.query("INSERT INTO `tblRhymeWords` \
                                                           (`word`, `syllables`, `rhymeType`, `rhymePool`) VALUES \
                                                           (?, ?, 1, ?) \
                                                           ON DUPLICATE KEY UPDATE `word` = ?",
                                                           (rhymeResult, rhymeResultSyllables, rhymePoolId,
                                                            rhymeResult), "", True)
                                    self.debug['DbInsertsRhymeWords'] += 1

                            except KeyError:
                                # This word isn't rhymable, e.g.
                                #   can't find any rhyming words in the dictionary for this word,
                                #   so just discard this line entirely and move along.
                                # set rhymable as False so we skip the db insert later
                                self.debug['TotalUnrhymable'] += 1
                                rhymable = False
                else:
                    # firstWord or lastWord is over 34 chars long, probably some trash.  Forget it.
                    self.debug['TotalUnrhymable'] += 1
                    rhymable = False

                # If everything came out rhymable, insert the line
                if rhymable:
                    self.rhymadexDB.query("INSERT INTO `tblLines` \
                                          (`firstWord`, `lastWord`, `line`, `syllables`, `source`) \
                                          VALUES (?, ?, ?, ?, ?) \
                                          ON DUPLICATE KEY UPDATE `line` = ?",
                                          (firstWord, lastWord, sourceLine, int(sourceLineSyllables),
                                           int(sourceId), sourceLine), "", True)
                    self.debug['TotalUniqueLines'] += 1
                    self.debug['DbInsertsLines'] += 1
                else:
                    self.debug['TotalDiscardedLines'] += 1

                if ((self.debug['TotalLinesProcessed'] == 1) or self.debug['TotalLinesProcessed'] % 1000 == 0):
                    percentComplete = int((int(self.debug['TotalLinesProcessed'])/int(len(sourceLines))) * 100)
                    print("\r", end="")
                    print("INFO- Estimated build progress:", percentComplete, "%", end="")
            else:
                self.debug['WontFitLines'] += 1
                self.debug['TotalDiscardedLines'] += 1

        print(" ... Done.")
        self.debug['ProcEndTime'] = time.time()

        # Because I'm depending on DUPLICATE KEY UPDATE logic, on a re-run we'll still see some
        #   DB Inserts reported.  They're DUPLICATE and the row counts should still be identical
        #   before and after re-runs.
        print("INFO- Completed building lyric dictionary in",
              self.debug['ProcEndTime'] - self.debug['ProcStartTime'], "seconds")
        print("INFO- Total Lines Processed:", self.debug['TotalLinesProcessed'])
        print("INFO- Total Words Processed:", self.debug['TotalWordsProcessed'])
        print("INFO- Total Syllables seen:", self.debug['TotalSyllablesSeen'])
        print("INFO- Total Discarded lines:", self.debug['TotalDiscardedLines'])
        print("INFO- Total Un-Rhymable words:", self.debug['TotalUnrhymable'])
        print("INFO- Total Won't-Fit-in-DB lines:", self.debug['WontFitLines'])
        print("INFO- Total Unique lyric lines available:", self.debug['TotalUniqueLines'])
        print("INFO- DB tblLines INSERTS:", self.debug['DbInsertsLines'])
        print("INFO- DB tblRhymeWords INSERTS:", self.debug['DbInsertsRhymeWords'])
        print("INFO- seenRhymeWords post-processing:", len(seenRhymeWords))
        print("INFO- Lyric Dictionary is ready!")

if __name__ == "__main__":
    rhymadexDB = rhymadexMariaDB('mariadb.cfg')
    rhymadexDB.initSchema()
    rhymadex = rhymadex(rhymadexDB)
    rhymadex.buildRhymadex("textsources/bible/bible.txt")