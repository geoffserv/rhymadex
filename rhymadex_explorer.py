# rhymadex_explorer.py
# Generate pairs and sequences of matching lines from the Rhymadex DB

import mariadb
import sys
from rhymadex_builder import debugger
from rhymadex_builder import rhymadexMariaDB

class song:
    def __init__(self, songDef, rhymeGroupPoolSize=10):

        self.debugger = debugger()
        self.debugger.printEnabled = False
        self.rhymadexDB = rhymadexMariaDB(self.debugger)

        # Quality of selection settings

        # Consider candidates which are plus-or-minus this many syllables per line
        # The syllable estimator is inaccurate, and good option to keep the pipeline
        # a bit wider while querying for candidate lines
        # The lower this is, candidate selection will be more accurate but more restricting
        self.syllablePadding = 1

        # Only consider rhymePools resulting in:
        #   integer of (the number of rhyme group occurances in the song definition) * candidatePoolMultiplier
        # For example, if the rhyme group "A" occurs at the end of 3 lines in the song defintion,
        #   and the candidatePoolMultiplier is 2,
        #   only consider candidate rhymePools who have at least 3 * 2 = 6 or more available lines to select from.
        # The result will be doubled again if there are any rhyme groups occuring in dual-position, both first and last
        self.candidatePoolMultiplier = 2

        # Grab and store this many candidate pools for each RhymeGroup at once
        self.rhymeGroupPoolSize = rhymeGroupPoolSize

        # Song attributes
        # The songDef is a list containing the definition settings for each line of the song
        self.songDef = songDef
        self.songNumLines = len(self.songDef)

        # Helper dict to associate the word specifications with the songDef dict index
        self.wordIndices = {"firstWord":
                                {"rhymeGroup": 0,
                                 "options":
                                    { "Syllables": 1,
                                      "Exclude": 2,
                                      "IncludeOnly": 3
                                    }
                                } ,
                            "lastWord" :
                                {"rhymeGroup": 7,
                                 "options":
                                     { "Syllables": 8,
                                       "Exclude": 9,
                                       "IncludeOnly": 10
                                     }
                                 }
                            }

        # ** BACKREFERENCES OVERRIDE EVERYTHING **
        #  If a songdef line has a firstword/fullline/and-or-lastword backreference, exclude that firstword/fullline/etc
        #    portion from the top level song rhymeGroup definition.
        # [4] = firstword backref index
        # [6] = fullline backref index
        # [11] = lastword backref index
        self.backRefIndices = {"firstWord": 4, "fullLine": 6, "lastWord": 11 }

        # Helper dict to associate full line specifications with the songDef dict index
        self.fullLineIndices = {"Syllables": 5 }

        # The starting point for line selection hinges on first choosing appropriate tblRhymePool IDs
        # to associate with each songDef rhyme group.
        self.rhymeGroups = {}

        self.rhymeGroups = self.generateRhymeGroups(self.songDef)

    def generateRhymeGroups(self, songDef):

        # Need to pre-process the songDef to get some top level facts about each requested rhymeGroup
        # prior to building a query to search for an appropriate rhymePool
        # In what positions do each rhymeGroup appear throughout the overall song?
        # What are the needed syllable counts for each word position & the overall line?
        # I want to select rhymePools that are guaranteed to be fruitful across the entire song,
        # so I need to know everything about what will eventually be pulled from the chosen pool.

        self.debugger.message("INFO", "Preprocessing rhymeGroup definitions")

        rhymeGroups = {}

        for lineDef in songDef:
            # Only examine this line if it is NOT a backreference to another line
            if not lineDef[self.backRefIndices["fullLine"]]:

                for wordIndex in self.wordIndices: # loop through "firstWord" then "lastWord"

                    # Only examine this word if it is NOT a backreference to another word
                    if not lineDef[self.backRefIndices[wordIndex]]:

                        # If there is a rhymeGroup Identifier for this word such as "A"
                        # then this line has a rhymeGroup defined in either the first or lastWord position
                        if lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]:

                            # If we haven't encountered it before, initialize a sub-dict to store the rhymegroup
                            # options
                            if lineDef[self.wordIndices[wordIndex]["rhymeGroup"]] not in rhymeGroups:
                                rhymeGroups[lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]] = {}

                            # Iterate the number of times this rhymeGroup has been found in this position e.g.
                            #   'firstWord':3 .. 4 .. 5 ..
                            if not wordIndex in rhymeGroups[lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]]:
                                rhymeGroups[lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]][wordIndex] = 1
                            else:
                                rhymeGroups[lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]][wordIndex] += 1

                            if (wordIndex == "lastWord" and "firstWord" in
                                rhymeGroups[lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]]):
                                # This rhymegroup is implicated in both first and lastword positions
                                # Denote that this is a dual-position rhymegroup
                                rhymeGroups[lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]]\
                                                                                                 ["dualPosition"] = True

                            if lineDef[self.fullLineIndices["Syllables"]]:
                                # If fullLine syllables are specified for this rhymeGroup,

                                if not "fullLineSyllables" in rhymeGroups[lineDef[self.wordIndices[wordIndex]
                                                                                                       ["rhymeGroup"]]]:
                                    # and we haven't encountered this option before to store it,
                                    # initialize a dict to hold what we've seen
                                    rhymeGroups[lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]]\
                                                                                              ["fullLineSyllables"] = {}

                                # Add this syllable count to the dict
                                rhymeGroups[lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]]\
                                                ["fullLineSyllables"][lineDef[self.fullLineIndices["Syllables"]]] = True

                            # loop through each of the line options pertaining to a firstWord or lastWord
                            for lineOption in self.wordIndices[wordIndex]["options"]:

                                # If one of the options has been defined for this line...
                                if lineDef[self.wordIndices[wordIndex]["options"][lineOption]]:

                                    # And it's the first time we've encountered this rhymeGroup w/ such an option
                                    # Initialize a dict to hold the option
                                    if not wordIndex + lineOption in \
                                           rhymeGroups[lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]]:
                                        rhymeGroups[lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]]\
                                                                                           [wordIndex + lineOption] = {}

                                    # Record this option for this position.  Using dict keys for auto-dedupe
                                    if type(lineDef[self.wordIndices[wordIndex]["options"][lineOption]]) == list:
                                        for optionValue in lineDef[self.wordIndices[wordIndex]["options"][lineOption]]:
                                            rhymeGroups[lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]]\
                                                [wordIndex + lineOption][optionValue] = True
                                    else:
                                        rhymeGroups[lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]]\
                                        [wordIndex + lineOption]\
                                            [lineDef[self.wordIndices[wordIndex]["options"][lineOption]]] = True

        self.debugger.message("INFO", ".. Processed rhymeGroups: {}".format(rhymeGroups))

        # Build and execute a rhymePoolId selection query
        # The strategy is to INNER JOIN the tblRhymeWords table against the tblLines table
        # so that it's possible to sum up actual available candidate line counts grouped by
        # the rhymeWord's rhymePoolId.  Then, filter by the rest of the line and word options,
        # select only rhymePools with enough of diversity to choose from, pick a unique pool ID
        # for each rhymeGroup randomly.

        # FIXME This is super slow.  The "Dual Position" situation in which a rhymeGroup is used both
        # as a firstWord and a lastWord (possibly even in the same line) results in a double INNER JOIN 🌈 🌈
        # so that it's possible to resolve the tblRhymePools ID for each firstWord and lastWord.
        # Maybe a better strategy is just to store the appropriate tblRhymePools ID as a foreign key in
        # the tblLines table itself.  Then there are no JOINS needed at all.
        # BUT THIS appears to be working and I'm plowing forwards towards a working first version

        for rhymeGroup in rhymeGroups:
            # For each rhymegroup, start a new query to pick a rhymePool
            rhymeGroupQuery = "SELECT COUNT(`tblLines`.`id`) as totalLines "

            self.debugger.message("QRYBLD", "Building query for rhymeGroup: {}".format(rhymeGroup))

            for wordIndex in self.wordIndices:
                # SELECT COLUMNS FROM tblRhymeWords
                # Loop through positions firstWord, lastWord..
                if wordIndex in rhymeGroups[rhymeGroup]:
                    # If it's been used in this position, SELECT that position within the query
                    self.debugger.message("QRYBLD", ".. Adding SELECT for {} seen {} times".format(wordIndex,
                                                                               rhymeGroups[rhymeGroup][wordIndex]))
                    rhymeGroupQuery += ", `{}Words`.`rhymePool` as {}RhymeGroup ".format(wordIndex, wordIndex)

            for wordIndex in self.wordIndices:
                # SELECT DISTINCT counts of firstWords and/or lastWords
                if wordIndex in rhymeGroups[rhymeGroup]:
                    # If it's been used in this position, SELECT a DISTINCT COUNT within the query
                    self.debugger.message("QRYBLD", ".. Adding DISTINCT COUNT for {}".format(wordIndex))
                    rhymeGroupQuery += ", COUNT(DISTINCT(`tblLines`.`{}`)) as distinct{} ".format(wordIndex, wordIndex)

            # Need a SUM CASE in the SELECT if:
            #   There is a fullLine syllable count list specficied
            #     This is because we gotta check that a diverse set of options exist in each selected rhymePool
            #     and can do so at once across an arbitrary set of implied syllable counts, all at once, using
            #     SUM CASE and then filtering with HAVING

            # Add full line syllable count SELECTions to the query
            if ("fullLineSyllables" in rhymeGroups[rhymeGroup]):
                for syllable in rhymeGroups[rhymeGroup]["fullLineSyllables"]:
                    rhymeGroupQuery += ", sum(CASE WHEN ( "
                    rhymeGroupQuery += "(`tblLines`.`syllables` >= {}) AND ".format(int(syllable)-self.syllablePadding)
                    rhymeGroupQuery += "(`tblLines`.`syllables` <= {}) ) ".format(int(syllable)+self.syllablePadding)
                    rhymeGroupQuery += "THEN 1 ELSE 0 END ) as syllables{} ".format(syllable)

            # Always selecting from tblLines because need to filter by how many actual lines we have later on
            rhymeGroupQuery += "FROM `tblLines` "

            for wordIndex in self.wordIndices:
                # INNER JOINING tblRhymeWords
                # Loop through positions firstWord, lastWord..
                if wordIndex in rhymeGroups[rhymeGroup]:
                    # If it's been used in this position, INNER JOIN that position within the query
                    self.debugger.message("QRYBLD", ".. Adding INNER JOIN for {} seen {} times".format(wordIndex,
                                                                               rhymeGroups[rhymeGroup][wordIndex]))
                    rhymeGroupQuery += "INNER JOIN `tblRhymeWords` {}Words ON `tblLines`.`{}` = `{}Words`.`word` ".\
                        format(wordIndex, wordIndex, wordIndex)

            pastRhymePoolIds = {}

            # Search for any prior selected tblRhymePool IDs.  They should be
            # excluded from all subsequent picks
            for searchRhymeGroup in rhymeGroups:
                if "rhymePoolCandidates" in rhymeGroups[searchRhymeGroup]:
                    for rhymePoolResult in rhymeGroups[searchRhymeGroup]["rhymePoolCandidates"]:
                        pastRhymePoolIds[rhymePoolResult] = True

            if pastRhymePoolIds:
                self.debugger.message("QRYBLD", ".. pastRhymePoolIds: {}".format(pastRhymePoolIds))

            # Need a WHERE clause if:
            #   There is a fullLine syllable count specficied,
            #   TODO There is a firstWord and/or lastWord restriction specified,
            #   TODO There is a firstWord and/or lastWord syllable count specified,
            #   The rhymeGroup is used in both the firstWord and lastWord position, in which case firstWord != lastWord,
            #   THere are past Rhyme Pool Ids we should exclude

            if (
                ("fullLineSyllables" in rhymeGroups[rhymeGroup]) or
                ("firstWordIncludeOnly" in rhymeGroups[rhymeGroup]) or
                ("lastWordIncludeOnly" in rhymeGroups[rhymeGroup]) or
                ("dualPosition" in rhymeGroups[rhymeGroup]) or
                (pastRhymePoolIds)
                ):
                rhymeGroupQuery += "WHERE ( "

                firstWhereClause = True # track for the "AND"s ..

                # Add full line syllable count restrictions to the query
                if ("fullLineSyllables" in rhymeGroups[rhymeGroup]):
                    rhymeGroupQuery += "( " # Open group for syllable count restrictions ((low) AND (high)) OR ((low)..
                    first = True # track for the "OR"s ..
                    for syllable in rhymeGroups[rhymeGroup]["fullLineSyllables"]:
                        if not first:
                            rhymeGroupQuery += "OR "
                        else:
                            first = False

                        rhymeGroupQuery += "( (`tblLines`.`syllables` >= {}) AND (`tblLines`.`syllables` <= {}) ) ".\
                                            format(int(syllable) - self.syllablePadding,
                                                   int(syllable) + self.syllablePadding)

                    firstWhereClause = False # We need an AND for the next WHERE clause, if there is one..
                    rhymeGroupQuery += ") "

                if ("dualPosition" in rhymeGroups[rhymeGroup]):
                    # The rhymeGroup appears in both firstWord and lastWord positions, possibly even
                    # in the same line.  So set a query WHERE condition that the firstWord and lastWord cannot
                    # be the same
                    if not firstWhereClause:
                        rhymeGroupQuery += "AND "
                    else:
                        firstWhereClause = False
                    rhymeGroupQuery += "(`tblLines`.`firstWord` != `tblLines`.`lastWord`) "

                if (pastRhymePoolIds):
                    # Need to exclude past chosen rhymePoolIds or else it's possible to select
                    #   the same pool for multiple rhymeGroups.
                    if not firstWhereClause:
                        rhymeGroupQuery += "AND "
                    else:
                        firstWhereClause = False

                    for wordIndex in self.wordIndices:
                        # Need to put a NOT IN () clause in the WHERE section to exclude prior selected
                        # rhymePool IDs.  Also need to do this specifically in the firstWord or lastWord or both
                        # positions depending on how the rhymepool is implicated.
                        # Loop through positions firstWord, lastWord..
                        if wordIndex in rhymeGroups[rhymeGroup]:
                            # If it's been used in this position, SELECT that position within the query
                            self.debugger.message("QRYBLD", ".. Adding NOT IN on {} id {}".format(wordIndex,
                                                                                                 pastRhymePoolIds))
                            if (("dualPosition" in rhymeGroups[rhymeGroup]) and (wordIndex == "lastWord")):
                                # If it's been used in BOTH positions, insert AND between the two WHERE clauses
                                rhymeGroupQuery += "AND "
                            rhymeGroupQuery += "( {}Words.rhymePool NOT IN (".format(wordIndex)
                            first = True
                            for poolId in pastRhymePoolIds:
                                if not first:
                                    rhymeGroupQuery += ", "
                                else:
                                    first = False
                                rhymeGroupQuery += "{} ".format(poolId)
                            rhymeGroupQuery += ") " # END OF NOT IN Number Group
                            rhymeGroupQuery += ") " # END OF NOT IN Clause

                # TODO if ("firstWordIncludeOnly" in rhymeGroups[rhymeGroup]):
                # Implement later

                # TODO if ("lastWordIncludeOnly" in rhymeGroups[rhymeGroup]):
                # Implement later

                # TODO if ("firstWordSyllables" in rhymeGroups[rhymeGroup]):
                # Implement later

                # TODO if ("lastWordSyllables" in rhymeGroups[rhymeGroup]):
                # Implement later

                rhymeGroupQuery += ") " # end of query WHERE

            # GROUP BY
            # Needs to be one or both of firstWord/lastWord
            rhymeGroupQuery += "GROUP BY "
            first = True # To track comma usage
            for wordIndex in self.wordIndices:
                if wordIndex in rhymeGroups[rhymeGroup]:
                    if not first:
                        rhymeGroupQuery += ", "
                    else:
                        first = False
                    rhymeGroupQuery += "`{}RhymeGroup` ".format(wordIndex)

            # HAVING
            # At minimum, will be HAVING a minimum number of available lines that is candidatePoolMultiplier times the
            # number of times the rhymegroup is referenced in the songDef
            rhymeGroupQuery += "HAVING ( "

            # Find the larger of either firstWord or lastWord occurance count,
            # and multiply by candidatePoolMultiplier.  this is how many candidates that the pool we
            # choose should have at minimum.  Also if the rhymeGroup is dualposition, double it again.
            # This is because worst case scenario is the rhymeGroup is used as firstWord AND lastWord in
            # Every occuring line.  Need a lot of diverse options to choose from to handle that case
            # fruitfully.
            totLines = 0
            for wordIndex in self.wordIndices:
                if (wordIndex in rhymeGroups[rhymeGroup]):
                    if (rhymeGroups[rhymeGroup][wordIndex] > totLines):
                        totLines = rhymeGroups[rhymeGroup][wordIndex]
                        self.debugger.message("QRYBLD", ".. Position {} seen {} times, totLines: {}".
                                              format(wordIndex, rhymeGroups[rhymeGroup][wordIndex], totLines))
            totLines = int(totLines * self.candidatePoolMultiplier)
            if ("dualPosition" in rhymeGroups[rhymeGroup]):
                totLines = totLines * 2

            rhymeGroupQuery += "(totalLines >= {} ) ".format(totLines)

            # Filter minimum distinct firstWord/and-or-lastWords
            for wordIndex in self.wordIndices:
                # HAVING DISTINCT counts of firstWords and/or lastWords
                if wordIndex in rhymeGroups[rhymeGroup]:
                    # If it's been used in this position, HAVING a DISTINCT COUNT within the query
                    self.debugger.message("QRYBLD", ".. Adding HAVING DISTINCT for {}".format(wordIndex))
                    rhymeGroupQuery += "AND (distinct{} >= {}) ".format(wordIndex, totLines)

            # Filter minimum syllable count lines available
                # Add full line syllable count SELECTions to the query
                if ("fullLineSyllables" in rhymeGroups[rhymeGroup]):
                    for syllable in rhymeGroups[rhymeGroup]["fullLineSyllables"]:
                        rhymeGroupQuery += "AND (syllables{} >= {}) ".format(syllable, totLines)

            if ("dualPosition" in rhymeGroups[rhymeGroup]):
                rhymeGroupQuery += "AND (firstWordRhymeGroup = lastWordRhymeGroup) "

            rhymeGroupQuery += ") " # End of HAVING

            rhymeGroupQuery += "ORDER BY RAND() LIMIT {};".format(self.rhymeGroupPoolSize)

            self.debugger.message("QRYBLD", ".. QUERY: {}".format(rhymeGroupQuery))

            # Query's ready for rhymePool selection for each rhymeGroup
            # First result, second column of the SELECT will be the assigned rhymePoolId
            rhymePoolIds = self.rhymadexDB.query(rhymeGroupQuery).fetchall()

            self.debugger.message("INFO", "Query returned candidate rhymePoolIds: {}".format(rhymePoolIds))
            rhymeGroups[rhymeGroup]["rhymePoolCandidates"] = []
            for rhymeGroupCandidate in rhymePoolIds:
                rhymeGroups[rhymeGroup]["rhymePoolCandidates"].append(rhymeGroupCandidate[0])

        # Debugger summary of rhymeGroup / rhymePoolId processing
        self.debugger.message("INFO", "rhymeGroup processing complete.")
        for rhymeGroup in rhymeGroups:
            self.debugger.message("INFO", "rhymeGroups[\"{}\"]:".format(rhymeGroup))
            if "rhymePool" in rhymeGroups[rhymeGroup]:
                self.debugger.message("INFO", "..[\"rhymePool\"]: {}".format(rhymeGroups[rhymeGroup]["rhymePool"]))
            if "rhymePoolCandidates" in rhymeGroups[rhymeGroup]:
                self.debugger.message("INFO", "..[\"rhymePoolCandidates\"]: {}".format(
                                                                   rhymeGroups[rhymeGroup]["rhymePoolCandidates"]))
            if "fullLineSyllables" in rhymeGroups[rhymeGroup]:
                self.debugger.message("INFO", "..[\"fullLineSyllables\"]: {}".format(
                                                                     rhymeGroups[rhymeGroup]["fullLineSyllables"]))
            for wordIndex in self.wordIndices:
                if wordIndex in rhymeGroups[rhymeGroup]:
                    self.debugger.message("INFO", "..[\"{}\"]: {} (line occurances)".format(wordIndex,
                                                                               rhymeGroups[rhymeGroup][wordIndex]))
                for lineOption in self.wordIndices[wordIndex]["options"]:
                    if wordIndex + lineOption in rhymeGroups[rhymeGroup]:
                        self.debugger.message("INFO", "..[\"{}\"]: {}".format(wordIndex + lineOption,
                                                                  rhymeGroups[rhymeGroup][wordIndex + lineOption]))

        # rhymeGroups contains ["rhymePoolCandidates"] for each rhymeGroup e.g. ["A"]
        #   which is the only important element needed per rhymeGroup.
        #   There are also a lot of other misc elements stored, from the query formation
        #   That could all be excluded from the return.
        #   But doesn't hurt for now, so moving on.
        return rhymeGroups

    def generateSong(self, songDef, rhymeGroups):
        # Build and execute a tblLine selection queries using the songDef, and build a song
        # Iterate through the songDef.
        # Got a dict of self.rhymeGroups indexed by whatever's in the songDef rhymeGroup index.
        #   So I know the rhymePoolId for this query's WHERE clause
        #   and that rhymePoolId should be fruitful for our use case per the selection process above
        # Add appropriate filter options as they exist in the songDef
        # NOT IN previously selected firstWords/lastWords ..
        # Run the query
        # Build the song line-by-line.  If the rhymegroup sequence leads to a dead-end anywhere along the way,
        #   return FALSE
        # Or else, return a list containing the completed song.

        song = []

        # As results come back, if a line has a defined firstWord rhymeGroup or lastWord rhymeGroup,
        # Exclude those chosen words from future queries.  Otherwise the same very common words keep
        # reappearing.
        # Store them here:
        pastFirstWords = {}
        pastLastWords = {}

        # Validate rhymeGroups input.  This could be done inline below but pulling it to the top
        #   for clarity.  If there are rhymeGroups defined, there needs to be a ["rhymePool"]
        #   value defined in order to build the query below.  If that isn't the case,
        #   just return False now.
        for rhymeGroup in rhymeGroups:
            if not "rhymePool" in rhymeGroups[rhymeGroup]:
                self.debugger.message("INFO", "rhymeGroup {} does not contain a [\"rhymePool\"].  Returning False.")
                return False

        for lineDef in songDef:

            if not lineDef[self.backRefIndices["fullLine"]]:

                self.debugger.message("QRYBLD", "Building lineDef: {}".format(lineDef))

                songQuery = "SELECT `tblLines`.`id`, `tblLines`.`line`, `tblLines`.`firstWord`, `tblLines`.`lastWord` "

                # If we got a rhymeGroup in firstWord and/or lastWord, select the INNER JOINed rhymePool columns
                for wordIndex in self.wordIndices:
                    if lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]:
                        self.debugger.message("QRYBLD", ".. Adding SELECT for {} rhymeGroup of {}".format(wordIndex,
                                                                    lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]))
                        songQuery += ", `{}Words`.`rhymePool` ".format(wordIndex)

                songQuery += "FROM `tblLines` "

                # If we got a rhymeGroup in firstWord and/or lastWord, INNER JOIN the rhymeWords table/s
                for wordIndex in self.wordIndices:
                    if lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]:
                        self.debugger.message("QRYBLD", ".. Adding INNER JOIN for {} rhymeGroup of {}".format(wordIndex,
                                                                    lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]))
                        songQuery += "INNER JOIN "
                        songQuery += "`tblRhymeWords` {}Words ON ".format(wordIndex)
                        songQuery += "`tblLines`.`{}` = `{}Words`.`word` ".format(wordIndex, wordIndex)

                self.debugger.message("INFO", "pastFirstWords: {}".format(pastFirstWords))
                self.debugger.message("INFO", "pastLastWords: {}".format(pastLastWords))

                # Need a WHERE clause if:
                #   There is a fullLine syllable count specficied,
                #   There is a firstWord and/or lastWord rhyme Group specified
                #   TODO There is a firstWord and/or lastWord restriction specified,
                #   TODO There is a firstWord and/or lastWord syllable count specified,
                #   TODO A rhymeGroup is used in both the firstWord and lastWord position, when firstWord != lastWord,
                #   There are past firstWord/lastWords we should exclude

                if (
                    (lineDef[self.fullLineIndices["Syllables"]]) or
                    (lineDef[self.wordIndices["firstWord"]["rhymeGroup"]]) or
                    (lineDef[self.wordIndices["lastWord"]["rhymeGroup"]]) or
                    (lineDef[self.wordIndices["firstWord"]["rhymeGroup"]]) or
                    (pastFirstWords) or
                    (pastLastWords)
                    ):
                    songQuery += "WHERE ( "

                    firstWhereClause = True # track for the "AND"s ...

                    # Add WHERE clause for full line syllable count, if it's defined:
                    if (lineDef[self.fullLineIndices["Syllables"]]):
                        self.debugger.message("QRYBLD", ".. Adding WHERE full line syllable count {} +- {}".format(
                                                       lineDef[self.fullLineIndices["Syllables"]],self.syllablePadding))
                        songQuery += "( (`tblLines`.`syllables` >= {}) AND (`tblLines`.`syllables` <= {}) ) ".\
                                          format(int(lineDef[self.fullLineIndices["Syllables"]]) - self.syllablePadding,
                                                 int(lineDef[self.fullLineIndices["Syllables"]]) + self.syllablePadding)
                        firstWhereClause = False # Need an AND for the next WHERE clause, if there is one..

                    # Add WHERE clause/s for firstWord and/or lastWord rhymeGroup/rhymePoolId, if it's defined:
                    for wordIndex in self.wordIndices:
                        if (lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]):
                            # Loop through firstWord, lastWord..
                            if not firstWhereClause:
                                songQuery += "AND "
                            else:
                                firstWhereClause = False

                            self.debugger.message("QRYBLD", ".. wordIndex: {} rhymeGroup defined".format(wordIndex))
                            self.debugger.message("QRYBLD", ".. lineDef[{}]: {}".format(
                                                                              self.wordIndices[wordIndex]["rhymeGroup"],
                                                                    lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]))
                            self.debugger.message("QRYBLD", ".. rhymeGroups[lineDef[{}]][\"rhymePool\"]: {}".
                                                                       format(self.wordIndices[wordIndex]["rhymeGroup"],
                                     rhymeGroups[lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]]["rhymePool"]))
                            self.debugger.message("QRYBLD", ".. Adding WHERE for {} rhymePool {}".format(wordIndex,
                                     rhymeGroups[lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]]["rhymePool"]))
                            songQuery += "({}Words.rhymePool = {}) ".format(wordIndex,
                                      rhymeGroups[lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]]["rhymePool"])

                    # Build exclude WHERE clauses for past rhymewords, so we don't continue getting the same word again
                    #   and again (cause it technically rhymes with itself..)
                    # Past seen firstWord rhymeWords to exclude ...
                    if (pastFirstWords):
                        if not firstWhereClause:
                            songQuery += "AND "
                        else:
                            firstWhereClause = False

                        songQuery += "(`tblLines`.`firstWord` NOT IN ( "
                        first = True
                        for firstWord in pastFirstWords:
                            if not first:
                                songQuery += ", "
                            else:
                                first = False
                            songQuery += "'{}' ".format(firstWord)
                        songQuery += ") "  # END of NOT IN group
                        songQuery += ") "  # END of WHERE Clause
                    # Past seen lastWord rhymeWords to exclude ...
                    if (pastLastWords):
                        if not firstWhereClause:
                            songQuery += "AND "
                        else:
                            firstWhereClause = False

                        songQuery += "(`tblLines`.`lastWord` NOT IN ( "
                        first = True
                        for lastWord in pastLastWords:
                            if not first:
                                songQuery += ", "
                            else:
                                first = False
                            songQuery += "'{}' ".format(lastWord)
                        songQuery += ") "  # END of NOT IN group
                        songQuery += ") "  # END of WHERE Clause

                    songQuery += ") " # END OF WHERE

                # Final query options
                # Random ORDERing and LIMIT
                songQuery += "ORDER BY RAND() LIMIT 1;"

                self.debugger.message("QRYBLD", ".. QUERY: {}".format(songQuery))

                # Execute the query and store the result
                songLine = self.rhymadexDB.query(songQuery).fetchall()
                if (len(songLine) == 0):
                    # Missed on this line selection query.  Too many restrictions to find a working line.
                    self.debugger.message("INFO", "No lines returned for this line selection query.")
                    return False
                else:
                    songLine = songLine[0]
                    # Add returned firstWord/lastWords associated with a rhymeGroup to the future exclude list
                    if lineDef[self.wordIndices["firstWord"]["rhymeGroup"]]:
                        pastFirstWords[songLine[2]] = True
                    if lineDef[self.wordIndices["lastWord"]["rhymeGroup"]]:
                        pastLastWords[songLine[3]] = True

            else: #The songLine has a fullLine Backreference
                if (song[lineDef[self.backRefIndices["fullLine"]]]):
                    songLine = song[lineDef[self.backRefIndices["fullLine"]]]
                else:
                    # Invalid backreference.  there's nothing there
                    self.debugger.message("INFO", "Invalid backreference for fullLine id {}".format(
                                                                              lineDef[self.backRefIndices["fullLine"]]))
                    return False

            self.debugger.message("INFO", "Song Line: {}".format(songLine))
            song.append(songLine)

        self.debugger.message("INFO", "Completed building song.")
        for songLine in song:
            if songLine:
                self.debugger.message("INFO", songLine[1])

        return song

    def printSongDef(self, songDef):
        lineNum = 0
        print("* Song Definition:")
        for lineDef in songDef:
            print("** Line id {}: ".format(lineNum), end="")
            for wordIndex in self.wordIndices:
                if lineDef[self.wordIndices[wordIndex]["rhymeGroup"]]:
                    print("{} rhymeGroup: {}, ".format(wordIndex, lineDef[self.wordIndices[wordIndex]["rhymeGroup"]])
                          , end="")
            if lineDef[self.fullLineIndices["Syllables"]]:
                print("full-line Syllables: {} +- {}, ".format(lineDef[self.fullLineIndices["Syllables"]],
                                                               self.syllablePadding), end="")
            if lineDef[self.backRefIndices["fullLine"]]:
                print("full-line backRef index: {}, ".format(lineDef[self.backRefIndices["fullLine"]]), end="")

            print("")
            lineNum += 1
        print("")

    def printRhymeGroups(self, rhymeGroups):
        # Print summary of rhymeGroups
        print("* RhymeGroups Summary:")
        for rhymeGroup in rhymeGroups:
            print("** rhymeGroups[\"{}\"]: ".format(rhymeGroup), end="")
            if "rhymePoolCandidates" in rhymeGroups[rhymeGroup]:
                print("..[\"rhymePoolCandidates\"]: Pool IDs {}".format(rhymeGroups[rhymeGroup]["rhymePoolCandidates"]),
                      end="")
            print("")
        print("")

    def printSong(self, song):
        if (song):
            for songLine in song:
                print(songLine[1])
            print("")

    def generateSongBook(self, songDef, rhymeGroups, songVariations):
        # Pop rhymePoolCandidates values, if there are any to pop

        self.printSongDef(songDef)
        self.printRhymeGroups(rhymeGroups)

        for i in range(self.rhymeGroupPoolSize):
            for rhymeGroup in rhymeGroups:
                if (("rhymePoolCandidates" in rhymeGroups[rhymeGroup]) and
                        (len(rhymeGroups[rhymeGroup]["rhymePoolCandidates"]) > 0)):
                    rhymeGroups[rhymeGroup]["rhymePool"] = rhymeGroups[rhymeGroup]["rhymePoolCandidates"].pop()

                    for j in range(songVariations):
                        song = self.generateSong(songDef, rhymeGroups)
                        if (song):
                            self.printSong(song)



if __name__ == "__main__":
    songDef = [ [None, None, None, None, None,    9, None,  "A", None, None, None, None],
                [None, None, None, None, None,    6, None,  "A", None, None, None, None],
                [None, None, None, None, None,    9, None,  "B", None, None, None, None],
                [None, None, None, None, None,    6, None,  "B", None, None, None, None],
                [None, None, None, None, None,    2, None,  "A", None, None, None, None],
                [None, None, None, None, None,    2, None,  "C", None, None, None, None],
                [None, None, None, None, None, None,    5, None, None, None, None, None],
                [None, None, None, None, None,    9, None,  "D", None, None, None, None],
                [None, None, None, None, None,    6, None,  "D", None, None, None, None],
                [None, None, None, None, None,    9, None,  "E", None, None, None, None],
                [None, None, None, None, None,    6, None,  "E", None, None, None, None],
                [None, None, None, None, None,    2, None,  "D", None, None, None, None],
                [None, None, None, None, None, None,    5, None, None, None, None, None],
                [None, None, None, None, None, None,    5, None, None, None, None, None] ]

    song = song(songDef, 10)
    song.generateSongBook(song.songDef, song.rhymeGroups, 8)

    # Propose a data structure to represent the song lyric composure
    # SongDef = { "settings": { "sources": [ [source 1], [source 2], ... ] },
    #             "linedef" : [ [line 0 def], [line 1 def], [line 2 def], [line 3 def], ... ] }

    # LineDef =
    #0[ ("FirstWord RhymeGroup" or None) ex "A",                   -> Lines w/same group have rhyming First Words
    #1  (FirstWord SyllableCt or None) ex 3,                       -> TODO Syllable count of first word in this line
    #2  (["FirstWord ExcludeList"] or None) ex ["but", "or"],      -> TODO Exclude lines with these First Words
    #3  (["FirstWord IncludeOnlyList"] or None) ex ["that", "my"], -> TODO Only choose a line with these First Words
    #4  (FirstWord BackReference Index or None) ex 0,              -> TODO Override and simply repeat the word index n
    #5  (FullLine SyllableCt or None) ex 9,                        -> Syllable count of the whole line
    #6  (FullLine BackReference Index or None) ex 0,               -> Override and simply repeat the line from index n
    #7  ("LastWord RhymeGroup" or None) ex "A",                    -> Lines w/same group have rhyming Last Words
    #8  (LastWord SyllableCt or None) ex 3,                        -> TODO Syllable count of last word in this line
    #9  (["LastWord ExcludeList"] or None) ex ["years", "his"],    -> TODO Exclude lines with these Last Words
    #10 (["LastWord IncludeOnlyList"] or None) ex ["lot", "her"],  -> TODO Only choose a line with these Last Words
    #11 (LastWord BackReference Index or None) ex 0 ]              -> TODO Override and simply repeat the word index n

    #                                         FirstWord                       FullLine    LastWord
    #                                         RG    SC    Exl   Inc     BR    SC    BR    RG   SC    Exl   Inc   BR
    # If I should stay                     [ [None, None, None, None,   None, 4,    None, "A", None, None, None, None],
    # I would only be in your way            [None, None, None, None,   None, 8,    None, "A", None, None, None, None],
    # So Ill go,                             [None, None, None, None,   None, 3,    None, "B", None, None, None, None],
    # but I know                             [None, None, None, None,   None, 3,    None, "B", None, None, None, None],
    # Ill think of you each step of the way  [None, None, None, None,   None, 9,    None, "A", None, None, None, None],
    # I will always love you                 [None, None, None, None,   None, 6,    None, "C", None, None, None, None],
    # I will always love you                 [None, None, None, None,   None, None, 5,   None, None, None, None, None],
    #                                        Full line backreference to line [5] "I will always love you" ...    #
    # Bittersweet memories                   [None, None, None, None,   None, 6,    None, "D", None, None, None, None],
    # That's all Im taking with me           [None, None, None, None,   None, 7,    None, "D", None, None, None, None],
    # Goodbye,                               [None, None, None, None,   None, 2,    None, "E", None, None, None, None],
    # please dont cry                        [None, None, None, None,   None, 3,    None, "E", None, None, None, None],
    # We both know that Im not what you need [None, None, None, None,   None, 9,    None, "D", None, None, None, None],
    #                                        Full line backreference to line [5] "I will always love you" ...    #
    # I will always love you                 [None, None, None, None,   None, None, 5,   None, None, None, None, None],
    #                                        Full line backreference to line [5] "I will always love you" ...    #
    # I will always love you                 [None, None, None, None,   None, None, 5,   None, None, None, None, None]]
