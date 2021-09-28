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

class debugger:
    def __init__(self):
        self.stats = {}
        self.messages = []
        self.printEnabled = True

    def logStat(self, statistic, increment, value=0):
        if not increment:
            increment = 0 # In case None gets pushed through
        if not statistic in self.stats:
            self.stats[statistic] = int(increment) or int(value)
        else:
            self.stats[statistic] += int(increment)

    def getStat(self, statistic):
        if not statistic in self.stats:
            return 0
        else:
            return int(self.stats[statistic])

    def message(self, severity, message):
        messageString = "{}- {}".format(severity, message)
        self.messages.append({"message": messageString, "timestamp": time.time()})
        if self.printEnabled:
            print(messageString)

    def summary(self):
        for stat in self.stats:
            self.message("DEBUG SUMMARY", "{}: {}".format(stat, self.stats[stat]))
        self.message("DEBUG SUMMARY", "Runtime: {} seconds".format((self.messages[-1]["timestamp"] -
                                                                    self.messages[0]["timestamp"])))

    def progress(self, processed, total):
        if self.printEnabled:
            if ((processed == 1) or (processed % 1000 == 0)):
                percentComplete = int((processed/total)*100)
                print("\r", end="")
                print("PROGRESS- Estimated build progress:", percentComplete, "%", end="")
            if (processed == total):
                print(" ... Done.")

class rhymadexMariaDB:
    def __init__(self, debugger, configfile="mariadb.cfg"):
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

        self.debugger = debugger

        if dbConfig.read(configfile):
            try:
                self.username = dbConfig['mariadb']['username']
                self.password = dbConfig['mariadb']['password']
                self.host = dbConfig['mariadb']['host']
                self.database = dbConfig['mariadb']['database']
                self.port = dbConfig['mariadb']['port']
            except configparser.Error as e:
                self.debugger.message("ERROR", "Configparser error: {}".format(e))
                sys.exit("Could not find database credential attributes in configfile.  Exiting.")
        else:
            sys.exit("Could not open configfile to read database credentials.  Exiting.")

        try:
            # Connect but don't open a database yet
            self.debugger.message("INFO",
                                  "Connecting to MariaDB server: {} port {} as {}".format(self.host,
                                                                                          self.port, self.username))
            self.connection = mariadb.connect(
                user=self.username,
                password=self.password,
                host=self.host,
                port=int(self.port)
            )
        except mariadb.Error as e:
            self.debugger.message("ERROR", "MariaDB Connection error: {}".format(e))
            sys.exit("Database connection error.  Exiting.")

        self.cursor = self.connection.cursor()

        if not self.initSchema():
            self.debugger.message("ERROR", "Unexpected error while initiailizing DB schema")
            sys.exit("Could not initialize DB.  Exiting.")

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
        #   db.query("INSERT INTO `{}` (`someCol`) VALUES (?)", (someColValue,), someTableNameIdentifier, True)
        #   But what can I do?  Hard-coding the dbname/etc feels icky.
        #   The queryIdentifier gets escape_string'ed so that's at least better than nothing.
        #   Also be careful to wrap the identifiers in backticks, at least for mariaDB etc.  Although that's not
        #   valid standard SQL I guess.
        #   If you have a good suggestion here please give me a PR!!
        # For values (field values in SELECT / INSERT / UPDATES etc) use the queryParams.
        # If you wanna just commit after a batch of un-committed queries, send nothing as the query for ex.
        #   db.query(None, None, "", True)
        try:
            if query: self.cursor.execute(query.format(self.connection.escape_string(str(queryIdentifier))),
                                          queryParams)
            if commitNow: self.connection.commit() # Gotta commit after INSERTs, etc.  Or, DIY
            return self.cursor
        except mariadb.Error as e:
            # Stop immediately on an error
            self.debugger.message("ERROR", "MariaDB error: {}\n Query: {}\n Parameters: {}".format(e,
                                                                                                   query, queryParams))
            sys.exit("Database query error.  Exiting.")

    def initSchema(self):
        # Check if the target database already exists
        self.debugger.message("INFO", "Checking for database {}".format(self.database))
        if not self.query("SHOW DATABASES LIKE '{}'", None, self.database).fetchall():

            # Did not find the database, so create it
            self.debugger.message("INFO", "Database not found.  Creating.")
            self.query("CREATE DATABASE `{}`", None, self.database)
            self.query("USE `{}`", None, self.database)

            # rhymadex DB schema v1

            # tblSources holds info about each text data source
            self.query("CREATE TABLE `tblSources` \
                        (`id` INT AUTO_INCREMENT NOT NULL, \
                         `sourceName` VARCHAR(255) NOT NULL, \
                         `dtmInit` DATETIME NOT NULL, \
                         UNIQUE KEY (`sourceName`), \
                         PRIMARY KEY (`id`))")

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
            return True

        else:
            # The database exists.  Open it
            self.debugger.message("INFO", "Database found.  Opening.")
            self.query("USE `{}`", None, self.database)

            # Check most recent schema version
            currentVersion = self.query("SELECT max(`versionNum`) AS `versionNum`, \
                                         `dtmInit` FROM `tblVersion`").fetchall()[0]
            self.debugger.message("INFO", "Found rhymadex version {} created {}".format(currentVersion[0],
                                                                                   currentVersion[1]))

            if not int(currentVersion[0]) == int(self.schemaCurrentVersion):
                self.debugger.message("ERROR",
                                 "Schema version doesn't match expected version: {}".format(self.schemaCurrentVersion))
                exit("Won't continue with mismatching schema.  Exiting.")
            # At this point, found the database, the schema version table, and the reported schema
            #   version matches what I'm looking for.  Assuming now that everything in the database is
            #   where I expect and how I expect it.
            return True

        # Should never reach this point of execution.  If so, something unexpected has happened.
        return False

class rhymer:
    def __init__(self, rhymadexDB, debugger):
        self.debugger = debugger
        self.debugger.message("INFO", "Initializing Rhymer")

        self.rhymadexDB = rhymadexDB
        self.rhyme = Phyme()

        # Keep a new list of words we couldn't rhyme on this run to minimize redundant lookups during this execution.
        # This means that on subsequent executions on the same sourceTxt, these words will be re-looked-up.
        # But that's good in case the rhyme dictionary or word filtering logic has been updated since the last run
        #   and we some new matches.
        self.seenUnrhymableWords = []

        # Pull all currently-known rhymewords from the DB to minimize redundant lookups and INSERTs between executions.
        self.seenRhymeWords = [list(result) for result in
                               self.rhymadexDB.query("SELECT `word` FROM `tblRhymeWords`").fetchall()]
        # Collapse to a single list of results
        self.seenRhymeWords = [result for list in self.seenRhymeWords for result in list]
        self.debugger.logStat("SeenRhymeWords", len(self.seenRhymeWords))
        self.debugger.message("INFO",
                              "seenRhymeWords pulled from DB: {}".format(self.debugger.getStat("SeenRhymeWords")))

    def findRhymes(self, rhymeTarget):
        if (rhymeTarget not in self.seenRhymeWords):
            if (rhymeTarget not in self.seenUnrhymableWords):
                # Haven't found this word to be rhymable in the past (seenRhymeWords) and
                # haven't found this word to be unrhymable during this execution (seenUnrhymableWords),
                # so give it a try:
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
                    rhymeTargetRhymeList = self.rhyme.get_perfect_rhymes(rhymeTarget).values() # Type 1 rhymes
                    # KeyError exception will come up if this is empty, caught below.
                    # rhymeTargetRhymeList is a list of lists, collapse to a single list of all the words
                    rhymeTargetRhymeList = [result for list in rhymeTargetRhymeList for result in list]

                    # And append it to the rhymeTargetRhymeList so it, itself, is added to the rhyme pool with all
                    #   of its friends and will be excluded automatically in the next run as well.
                    rhymeTargetRhymeList.append(rhymeTarget)

                    # The rhymeHint is a right-handish segment of the word.
                    #   Optional-vowel-optional-const-required-vowel-optional-const-end-anchor.
                    #   This is a dumb chunky approach, but just for fun..
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

                    for rhymeResult in rhymeTargetRhymeList:
                        # Iterate through each rhymeResult

                        # Strip out non-characters.  Some of the returned results from Phyme have (1) and other crap
                        rhymeResult = re.findall("[a-z]*", rhymeResult.lower())[0]

                        if (rhymeResult and rhymeResult not in self.seenRhymeWords):
                            # Check that each cleaned result from Phyme hasn't been seen yet, and
                            # record that we've seen it so we don't re-calculate rhymes on this again later
                            self.seenRhymeWords.append(rhymeResult)

                            # Estimate syllables
                            rhymeResultSyllables = syllables.estimate(rhymeResult)
                            # And insert to our rhymeList
                            self.rhymadexDB.query("INSERT INTO `tblRhymeWords` \
                                                   (`word`, `syllables`, `rhymeType`, `rhymePool`) VALUES \
                                                   (?, ?, 1, ?) \
                                                   ON DUPLICATE KEY UPDATE `word` = ?",
                                                  (rhymeResult, rhymeResultSyllables, rhymePoolId,
                                                   rhymeResult), "", True)
                            self.debugger.logStat("DbInsertsRhymeWords", 1)

                    # It was rhymable, it's been recorded along with its friends.  It's good to go.
                    return True
                except KeyError:
                    # This word isn't rhymable, e.g.
                    #   can't find any rhyming words in the dictionary for this word,
                    #   so just discard this line entirely and move along.
                    self.debugger.logStat("TotalUnrhymable", 1)
                    self.seenUnrhymableWords.append(rhymeTarget)
                    return False
            else:
                # rhymeTarget is in seenUnrhymableWords, so we've seen it before and it was not rhymable.
                # It is not good to go.
                return False
        else:
            # rhymeTarget is in seenRhymeWords, so we've seen it before and it was rhymable. It's good to go.
            return True

        # Should never reach this point of execution.  If so, something unexpected has happened.
        return False

class rhymadex:
    def __init__(self, sourceFile):
        self.sourceFile = sourceFile
        self.debugger = debugger()
        self.rhymadexDB = rhymadexMariaDB(self.debugger)
        self.rhymer = rhymer(self.rhymadexDB, self.debugger)
        self.buildRhymadex()

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
        line = re.sub(r"[~`#^*_\[\]{}|\\<>/()$€ƒ„…†‡ˆ‰‹Œ‘’“”•˜™›¢£¤¥¦§¨©ª«¬®¯°±²³´µ¶·¸¹º»¿×÷]+", "", line)

        # The "and" coordinating conjunction at the beginning of a line is redundant in my opinion,
        #   resulting from the comma-split logic.  There are an enormous amount of lines with "and"
        #   as the first word.  Lets just remove them to make for more intesting output.  Some day,
        #   if this is calculating every rhymepool for every word in a line, could make "and" optional.
        #   Other coordinating conjunctions like but, for, or, nor etc imply "non-additive" logic.
        #   Leave those in for now.
        line = re.sub(r"^and ", "", line)

        # Pretty up with some substitutions
        line = re.sub(r"--", " ", line)
        line = re.sub(r"–", " ", line)
        line = re.sub(r"—", " ", line)
        line = re.sub(r"@", "at", line)
        line = re.sub(r"&", "and", line)
        line = re.sub(r"=", "equals", line)
        line = re.sub(r"%", "percent", line)
        line = re.sub(r"¼", "one quarter", line)
        line = re.sub(r"½", "one half", line)
        line = re.sub(r"¾", "three quarters", line)
        line = re.sub(r"\+", "plus", line)

        return line or None

    def buildRhymadex(self):
        self.debugger.message("INFO", "Opening file for processing: {}".format(self.sourceFile))
        try:
            sourceTextFile = open(self.sourceFile, 'r', encoding = "ISO-8859-1")
            # sourceTextBlob = sourceTextFile.read().replace('\n', ' ')
            sourceTextBlob = sourceTextFile.read()
            sourceTextFile.close()
        except OSError as e:
            self.debugger.message("ERROR", "OSError when opening file for reading: {}\nOSError: {}".format(
                                                                                                    self.sourceFile, e))
            exit("Nothing more to do.  Exiting.")

        # Capture the data source and get the source primary key ID from the database
        self.rhymadexDB.query("INSERT INTO `tblSources` \
                              (`sourceName`, `dtmInit`) \
                              VALUES \
                              (?, now()) \
                              ON DUPLICATE KEY UPDATE \
                              `dtmInit` = now()", (self.sourceFile,), "", True)

        # Re-query to capture the sourceId.  Could potentially do it all-at-once above, but the DUPLICATE KEY UPDATE
        #   makes the behavior less clear and less easy for me to understand.  I think this is more clear and not too
        #   expensive.
        sourceId = self.rhymadexDB.query("SELECT `id` FROM `tblSources` \
                                          WHERE \
                                          (`sourceName` = ?) \
                                          LIMIT 1", (self.sourceFile,)).fetchall()[0][0]

        # Remove any existing source lines 'cause we're gunna rebuild them now
        deletedLines = self.rhymadexDB.query("DELETE FROM `tblLines` \
                                              WHERE (`source` = ?)", (sourceId,), "", True).rowcount
        if deletedLines:
            self.debugger.message("INFO", "Deleted {} existing source lines from tblLines.".format(deletedLines))

        # Break Lines apart on: , . ! ? ; : tabspace newline
        #   IMO some of the most interesting magic happens on the comma split because it results in
        #   poetic sentence fragments
        sourceLines = re.split('[,.!?;:\t\n]', sourceTextBlob)

        # Do that little to-dict and back to-list trick to dedupe all the list items
        sourceLines = list(dict.fromkeys(sourceLines))
        self.debugger.logStat("TotalLinesSeen", None, len(sourceLines))
        self.debugger.logStat("TotalDiscardedLines",
                              (self.debugger.getStat("TotalLinesSeen")-self.debugger.getStat("TotalLinesSeen")))
        self.debugger.message("INFO", "Line entries found: {}".format(self.debugger.getStat("TotalLinesSeen")))

        for sourceLine in sourceLines:
            self.debugger.logStat("TotalLinesProcessed", 1)

            # Use the lineCleaner on each line first.
            # What comes back will be only printable ANSI with the ends trimmed, everything lowered,
            #   and some common punctuation-to-text replacements done
            sourceLine = self.lineCleaner(sourceLine)

            # Anything longer than 255 won't fit in the DB with this schema.
            if (sourceLine and (len(sourceLine) < 256)):
                sourceLineWords = sourceLine.split()
                self.debugger.logStat("TotalWordsProcessed", len(sourceLineWords))
                firstWord = sourceLineWords[0]
                lastWord = sourceLineWords[-1]

                if (len(firstWord) and len(lastWord) and (len(firstWord) <= 34) and (len(lastWord) <= 34)):
                    # Line Syllable Estimation
                    # Can only estimate syllable count per-word, so run the estimator on every word in
                    #   the line and accumulate.  The estimator is really inaccurate but good for POC
                    sourceLineSyllables = 0
                    for sourceLineWord in sourceLineWords:
                        sourceLineSyllables += syllables.estimate(sourceLineWord)

                    self.debugger.logStat("TotalSyllablesSeen", sourceLineSyllables)

                    # Look up rhymes for the firstWord and the lastWord
                    if (self.rhymer.findRhymes(firstWord) and self.rhymer.findRhymes(lastWord)):
                        # If everything came out rhymable, insert the line
                        self.rhymadexDB.query("INSERT INTO `tblLines` \
                                                (`firstWord`, `lastWord`, `line`, `syllables`, `source`) \
                                                VALUES (?, ?, ?, ?, ?) \
                                                ON DUPLICATE KEY UPDATE `line` = ?",
                                              (firstWord, lastWord, sourceLine, int(sourceLineSyllables),
                                               int(sourceId), sourceLine), "", True)
                        self.debugger.logStat("DbInsertsLines", 1)
                else:
                    # firstWord or lastWord is under 1 or over 34 chars long, so pass it by and nothing happens.
                    self.debugger.logStat("TotalDiscardedLines", 1)
            else:
                # Line is less than 1 or greater than 255, so pass it by and nothing happens.
                self.debugger.logStat("WontFitLines", 1)
                self.debugger.logStat("TotalDiscardedLines", 1)

            self.debugger.progress(self.debugger.getStat("TotalLinesProcessed"),
                                   self.debugger.getStat("TotalLinesSeen"))

        self.debugger.summary()

if __name__ == "__main__":
    rhymadex = rhymadex("textsources/bible/bible.txt")