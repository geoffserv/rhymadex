# rhymadex_explorer.py
# Generate pairs and sequences of matching lines from the Rhymadex DB

import mariadb
import sys
from rhymadex_builder import debugger
from rhymadex_builder import rhymadexMariaDB

class song:
    def __init__(self, songDef):
        self.debugger = debugger()
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

        self.songDef = songDef
        self.songNumLines = len(self.songDef)

        self.generateSong()

    def generateSong(self):
        # The starting point for line selection hinges on first choosing appropriate tblRhymePool IDs
        # to associate with each songDef rhyme group.
        rhymeGroups = { }

        # Need to pre-process the songDef to get some top level facts about each requested rhymeGroup
        # prior to building a query to search for an appropriate rhymePool
        # In what positions do each rhymeGroup appear throughout the overall song?
        # What are the needed syllable counts for each word position & the overall line?
        # I want to select rhymePools that are guaranteed to be fruitful across the entire song,
        # so I need to know everything about what will eventually be pulled from the chosen pool.

        # Helper dict to associate the word specifications with the songDef dict index
        wordIndices = {"firstWord": {"rhymeGroup": 0, "options": { "Syllables": 1, "Exclude": 2, "IncludeOnly": 3 } } ,
                       "lastWord" : {"rhymeGroup": 7, "options": { "Syllables": 8, "Exclude": 9, "IncludeOnly": 10 } } }

        # ** BACKREFERENCES OVERRIDE EVERYTHING **
        #  If a songdef line has a firstword/fullline/and-or-lastword backreference, exclude that firstword/fullline/etc
        #    portion from the top level song rhymeGroup definition.
        # [4] = firstword backref index
        # [6] = fullline backref index
        # [11] = lastword backref index
        backRefIndices = {"firstWord": 4, "fullLine": 6, "lastWord": 11 }

        # Helper dict to associate full line specifications with the songDef dict index
        fullLineIndices = {"Syllables": 5 }

        self.debugger.message("INFO", "Preprocessing rhymeGroup definitions")

        for lineDef in self.songDef:
            # Only examine this line if it is NOT a backreference to another line
            if not lineDef[backRefIndices["fullLine"]]:

                for wordIndex in wordIndices: # loop through "firstWord" then "lastWord"

                    # Only examine this word if it is NOT a backreference to another word
                    if not lineDef[backRefIndices[wordIndex]]:

                        # If there is a rhymeGroup Identifier for this word such as "A"
                        # then this line has a rhymeGroup defined in either the first or lastWord position
                        if lineDef[wordIndices[wordIndex]["rhymeGroup"]]:

                            # If we haven't encountered it before, initialize a sub-dict to store the rhymegroup
                            # options
                            if lineDef[wordIndices[wordIndex]["rhymeGroup"]] not in rhymeGroups:
                                rhymeGroups[lineDef[wordIndices[wordIndex]["rhymeGroup"]]] = {}

                            # Iterate the number of times this rhymeGroup has been found in this position e.g.
                            #   'firstWord':3 .. 4 .. 5 ..
                            if not wordIndex in rhymeGroups[lineDef[wordIndices[wordIndex]["rhymeGroup"]]]:
                                rhymeGroups[lineDef[wordIndices[wordIndex]["rhymeGroup"]]][wordIndex] = 1
                            else:
                                rhymeGroups[lineDef[wordIndices[wordIndex]["rhymeGroup"]]][wordIndex] += 1

                            if (wordIndex == "lastWord" and "firstWord" in
                                rhymeGroups[lineDef[wordIndices[wordIndex]["rhymeGroup"]]]):
                                # This rhymegroup is implicated in both first and lastword positions
                                # Denote that this is a dual-position rhymegroup
                                rhymeGroups[lineDef[wordIndices[wordIndex]["rhymeGroup"]]] \
                                    ["dualPosition"] = True

                            if lineDef[fullLineIndices["Syllables"]]:
                                # If fullLine syllables are specified for this rhymeGroup,

                                if not "fullLineSyllables" in rhymeGroups[lineDef[wordIndices[wordIndex]
                                                                                             ["rhymeGroup"]]]:
                                    # and we haven't encountered this option before to store it,
                                    # initialize a dict to hold what we've seen
                                    rhymeGroups[lineDef[wordIndices[wordIndex]["rhymeGroup"]]]["fullLineSyllables"] = {}

                                # Add this syllable count to the dict
                                rhymeGroups[lineDef[wordIndices[wordIndex]["rhymeGroup"]]]["fullLineSyllables"]\
                                    [lineDef[fullLineIndices["Syllables"]]] = True

                            # loop through each of the line options pertaining to a firstWord or lastWord
                            for lineOption in wordIndices[wordIndex]["options"]:

                                # If one of the options has been defined for this line...
                                if lineDef[wordIndices[wordIndex]["options"][lineOption]]:

                                    # And it's the first time we've encountered this rhymeGroup w/ such an option
                                    # Initialize a dict to hold the option
                                    if not wordIndex + lineOption in \
                                           rhymeGroups[lineDef[wordIndices[wordIndex]["rhymeGroup"]]]:
                                        rhymeGroups[lineDef[wordIndices[wordIndex]["rhymeGroup"]]] \
                                            [wordIndex + lineOption] = {}

                                    # Record this option for this position.  Using dict keys for auto-dedupe
                                    if type(lineDef[wordIndices[wordIndex]["options"][lineOption]]) == list:
                                        for optionValue in lineDef[wordIndices[wordIndex]["options"][lineOption]]:
                                            rhymeGroups[lineDef[wordIndices[wordIndex]["rhymeGroup"]]]\
                                                [wordIndex + lineOption][optionValue] = True
                                    else:
                                        rhymeGroups[lineDef[wordIndices[wordIndex]["rhymeGroup"]]]\
                                        [wordIndex + lineOption]\
                                            [lineDef[wordIndices[wordIndex]["options"][lineOption]]] = True

        self.debugger.message("INFO", "Processed rhymeGroups: {}".format(rhymeGroups))

        # Build and execute a rhymePoolId selection query
        # The strategy is to INNER JOIN the tblRhymeWords table against the tblLines table
        # so that it's possible to sum up actual available candidate line counts grouped by
        # the rhymeWord's rhymePoolId.  Then, filter by the rest of the line and word options,
        # select only rhymePools with enough of diversity to choose from, pick a unique pool ID
        # for each rhymeGroup randomly.

        # FIXME This is super slow.  The "Dual Position" situation in which a rhymeGroup is used both
        # as a firstWord and a lastWord (possibly even in the same line) results in a double INNER JOIN
        # so that it's possible to resolve the tblRhymePools ID for each firstWord and lastWord.
        # Maybe a better strategy is just to store the appropriate tblRhymePools ID as a foreign key in
        # the tblLines table itself.  Then there are no JOINS needed at all.
        # BUT THIS appears to be working and I'm plowing forwards towards a working first version

        for rhymeGroup in rhymeGroups:
            # For each rhymegroup, start a new query to pick a rhymePool
            rhymeGroupQuery = "SELECT COUNT(`tblLines`.`id`) as totalLines, "

            self.debugger.message("QRYBLD", "rhymeGroup: {}".format(rhymeGroup))

            for wordIndex in wordIndices:
                # SELECT COLUMNS FROM tblRhymeWords
                # Loop through positions firstWord, lastWord..
                if wordIndex in rhymeGroups[rhymeGroup]:
                    # If it's been used in this position, SELECT that position within the query
                    self.debugger.message("QRYBLD", "    Adding SELECT for {} seen {} times".format(wordIndex,
                                                                                    rhymeGroups[rhymeGroup][wordIndex]))
                    if (("dualPosition" in rhymeGroups[rhymeGroup]) and (wordIndex == "lastWord")):
                        # If it's been used in BOTH positions, insert the comma between the firstWord
                        rhymeGroupQuery += ", "
                    rhymeGroupQuery += "`{}Words`.`rhymePool` as {}RhymeGroup ".format(wordIndex, wordIndex)

            # Always selecting from tblLines because need to filter by how many actual lines we have later on
            rhymeGroupQuery += "FROM `tblLines` "

            for wordIndex in wordIndices:
                # INNER JOINING tblRhymeWords
                # Loop through positions firstWord, lastWord..
                if wordIndex in rhymeGroups[rhymeGroup]:
                    # If it's been used in this position, INNER JOIN that position within the query
                    self.debugger.message("QRYBLD", "    Adding INNER JOIN for {} seen {} times".format(wordIndex,
                                                                                    rhymeGroups[rhymeGroup][wordIndex]))
                    rhymeGroupQuery += "INNER JOIN `tblRhymeWords` {}Words ON `tblLines`.`{}` = `{}Words`.`word` ".\
                        format(wordIndex, wordIndex, wordIndex)

            pastRhymePoolIds = {}

            # Search for any prior selected tblRhymePool IDs.  They should be
            # excluded from all subsequent picks
            for searchRhymeGroup in rhymeGroups:
                if "rhymePool" in rhymeGroups[searchRhymeGroup]:
                    pastRhymePoolIds[rhymeGroups[searchRhymeGroup]["rhymePool"]] = True

            if pastRhymePoolIds:
                self.debugger.message("QRYBLD", "    pastRhymePoolIds: {}".format(pastRhymePoolIds))

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

                whereNextAnd = False # track for the "AND"s ..

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

                    whereNextAnd = True # We need an AND for the next WHERE clause, if there is one..
                    rhymeGroupQuery += ") "

                if ("dualPosition" in rhymeGroups[rhymeGroup]):
                    # The rhymeGroup appears in both firstWord and lastWord positions, possibly even
                    # in the same line.  So set a query WHERE condition that the firstWord and lastWord cannot
                    # be the same
                    if whereNextAnd:
                        rhymeGroupQuery += "AND "
                    else:
                        whereNextAnd = True
                    rhymeGroupQuery += "(`tblLines`.`firstWord` != `tblLines`.`lastWord`) "

                if (pastRhymePoolIds):
                    # Need to exclude past chosen rhymePoolIds or else it's possible to select
                    #   the same pool for multiple rhymeGroups.
                    if whereNextAnd:
                        rhymeGroupQuery += "AND "
                    else:
                        whereNextAnd = True

                    for wordIndex in wordIndices:
                        # Need to put a NOT IN () clause in the WHERE section to exclude prior selected
                        # rhymePool IDs.  Also need to do this specifically in the firstWord or lastWord or both
                        # positions depending on how the rhymepool is implicated.
                        # Loop through positions firstWord, lastWord..
                        if wordIndex in rhymeGroups[rhymeGroup]:
                            # If it's been used in this position, SELECT that position within the query
                            self.debugger.message("QRYBLD", "    Adding NOT IN on {} pos {} IDs".format(wordIndex,
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
            for wordIndex in wordIndices:
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
            for wordIndex in wordIndices:
                if (wordIndex in rhymeGroups[rhymeGroup]):
                    if (rhymeGroups[rhymeGroup][wordIndex] > totLines):
                        totLines = rhymeGroups[rhymeGroup][wordIndex]
                        self.debugger.message("QRYBLD", "    Position {} seen {} times, totLines: {}".
                                              format(wordIndex, rhymeGroups[rhymeGroup][wordIndex], totLines))
            totLines = int(totLines * self.candidatePoolMultiplier)
            if ("dualPosition" in rhymeGroups[rhymeGroup]):
                totLines = totLines * 2

            rhymeGroupQuery += "(totalLines >= {}) ".format(totLines)

            if ("dualPosition" in rhymeGroups[rhymeGroup]):
                rhymeGroupQuery += "AND (firstWordRhymeGroup = lastWordRhymeGroup) "

            rhymeGroupQuery += ") " # End of HAVING

            rhymeGroupQuery += "ORDER BY RAND() LIMIT 1;"

            self.debugger.message("QRYBLD", "    QUERY: {}".format(rhymeGroupQuery))

            # Query's ready for rhymePool selection for each rhymeGroup
            # First result, second column of the SELECT will be the assigned rhymePoolId
            rhymePoolId = self.rhymadexDB.query(rhymeGroupQuery).fetchall()[0][1]

            self.debugger.message("INFO", "Query returned candidate rhymePoolId: {}".format(rhymePoolId))
            rhymeGroups[rhymeGroup]["rhymePool"] = rhymePoolId

        # Debugger summary of rhymeGroup / rhymePoolId processing
        self.debugger.message("INFO", "rhymeGroup processing complete.")
        for rhymeGroup in rhymeGroups:
            self.debugger.message("INFO", "rhymeGroups[\"{}\"]:".format(rhymeGroup))
            if "rhymePool" in rhymeGroups[rhymeGroup]:
                self.debugger.message("INFO", "..[\"rhymePool\"]: {}".format(
                                                                        rhymeGroups[rhymeGroup]["rhymePool"]))
            if "fullLineSyllables" in rhymeGroups[rhymeGroup]:
                self.debugger.message("INFO", "..[\"fullLineSyllables\"]: {}".format(
                                                                         rhymeGroups[rhymeGroup]["fullLineSyllables"]))
            for wordIndex in wordIndices:
                if wordIndex in rhymeGroups[rhymeGroup]:
                    self.debugger.message("INFO", "..[\"{}\"]: {} (line occurances)".format(wordIndex,
                                                                                    rhymeGroups[rhymeGroup][wordIndex]))
                for lineOption in wordIndices[wordIndex]["options"]:
                    if wordIndex + lineOption in rhymeGroups[rhymeGroup]:
                        self.debugger.message("INFO", "..[\"{}\"]: {}".format(wordIndex + lineOption,
                                                     rhymeGroups[rhymeGroup][wordIndex + lineOption]))

        # Build and execute a tblLine selection query
        # In progress thinking:
        # IDEA: I could potentially capture multiple candidate rhymePoolIds at once during the queries
        # above.  So for each rhymeGroup there could be dozens, hundreds of candidate rhymePoolIds stored
        # as a list in the rhymeGroup dict.  Then during song formulation below, choose randomly from that pool.
        # I can retroactively wire that in by continuing to use the same dict index e.g.
        # rhymeGroups["A"]["rhymePool"] as the "chosen" rhymePool for the query, and add a new index like
        # rhymeGroups["A"]["rhymePoolCandidates"] which is a list of all candidates returned from the query above,
        # and add a block later that populates ["rhymePool"] with a randomly chosen but unique-across-the-song
        # candidate ID just prior to the line selection query building.
        # So yeah,
        # Iterate through the songDef.
        # Got a dict of rhymeGroups indexed by whatever's in the songDef rhymeGroup index.
        #   So I know the rhymePoolId for this query's WHERE clause
        #   and that rhymePoolId should be fruitful for our use case per the selection process above
        # Add appropriate filter options as they exist in the songDef
        # Run the query
        # Store and display the result
        # TODO Alright go



        # if lineDef[wordIndices[wordIndex][1]]: # If there is a syllable count restriction for this word
        #     if not wordIndex+"Syllables" in rhymeGroups[lineDef[wordIndices[wordIndex][0]]]:
        #         # And it's the first time we've encountered this rhymeGroup w/ a syllable restriction
        #         # Initialize a list to hold syllable restrictions for this position
        #         rhymeGroups[lineDef[wordIndices[wordIndex][0]]][wordIndex + "Syllables"] = []
        #     # record this syllable restrction for this position
        #     rhymeGroups[lineDef[wordIndices[wordIndex][0]]][wordIndex + "Syllables"].\
        #         append(lineDef[wordIndices[wordIndex][1]])

        # for lineDef in self.songDef:
        #     # If the line has ANY attribute specification, we need a WHERE clause
        #     # So for example if the lineDef is completely empty, the query produces a totally random result
        #     # That might be something that someone actually wants.
        #     someAttributeExists = False
        #     for attribute in lineDef:
        #         if (attribute): someAttributeExists = True

            # # Check firstWord (songDef index[0]) and lastWord (songDef index[7]) rhymeGroups
            # for wordIndex in wordIndices:
            #     if lineDef[wordIndices[wordIndex]] and lineDef[wordIndices[wordIndex]] not in rhymeGroups:
            #         # This line has a rhymeGroup in either the first or lastWord position
            #         # and we haven't encountered it before, so need to search to find an appropriate
            #         # rhymePool to assign to that group
            #         rhymeGroups[lineDef[wordIndices[wordIndex]]] = {}
            #         rhymeGroups[lineDef[wordIndices[wordIndex]]]["wordPosition"] = wordIndex
            #
            #         # Pick out a rhymePool ID for this new rhymeGroup.
            #         # Query for a rhymePool ID which is referenced by 2* numLines in this song
            #         #   by either the first or lastword with the proper line syllable count+-padding
            #         #   so there is a good diversity of lines to choose from when building the song
            #         # TODO exclude previously chosen rhymePools so don't accidentally pick the same multiple times
            #         # TODO maybe a NOT IN string builder method?
            #
            #         rhymePoolQuery = "SELECT COUNT(`tblLines`.`id`) AS candidateLineCount, \
            #                           `lastRhymeWords`.`rhymePool` AS lastWordRhymeGroup \
            #                           FROM `tblLines` \
            #                           INNER JOIN `tblRhymeWords` lastRhymeWords \
            #                           ON `tblLines`.`{}` = `lastRhymeWords`.`word` \
            #                           WHERE ((`tblLines`.`syllables` >= {}) \
            #                           AND    (`tblLines`.`syllables` <= {})) \
            #                           GROUP BY `lastWordRhymeGroup` \
            #                           HAVING `candidateLineCount` > {} \
            #                           ORDER BY RAND() LIMIT 1;".format(wordIndex,
            #                                                            lineDef[5] - self.syllablePadding,
            #                                                            lineDef[5] + self.syllablePadding,
            #                                                            str(2 * self.songNumLines))
            #
            #         rhymePool = self.rhymadexDB.query(rhymePoolQuery).fetchall()[0][0]
            #         rhymeGroups[lineDef[wordIndices[wordIndex]]]["rhymePoolId"] = rhymePool

                # Build a line query to pick out this line

                # lineQuery = "SELECT `tblLines`.`line` AS line, \
                #              `tblLines`.`syllables` as lineSyllables, \
                #              `tblLines`.`firstWord` AS firstWord, \
                #              `firstRhymeWords`.`syllables` AS firstWordSyllables, \
                #              `firstRhymeWords`.`rhymePool` AS firstWordRhymeGroup, \
                #              `tblLines`.`lastWord` AS lastWord, \
                #              `lastRhymeWords`.`syllables` AS lastWordSyllables, \
                #              `lastRhymeWords`.`rhymePool` AS lastWordRhymeGroup \
                #              FROM `tblLines` \
                #              INNER JOIN `tblRhymeWords` firstRhymeWords \
                #              ON `tblLines`.`firstWord` = `firstRhymeWords`.`word` \
                #              INNER JOIN `tblRhymeWords` lastRhymeWords \
                #              ON `tblLines`.`lastWord` = `lastRhymeWords`.`word`"

                # if someAttributeExists then build a where clause

                             # WHERE (`tblLines`.`syllables` = 8 \
                             # AND `lastRhymeWords`.`rhymePool` = 42) \
                             # AND `tblLines`.`lastWord` NOT IN ("line","signs") \
                             # limit 10;"

                    # I have a better idea than this, but this is still interesting and I might use
                    # this kind of code for something later.
                    # # Build a HAVING clause as we go, to make sure every next choice is a new choice
                    # havingClause = "((COUNT(`id`) > {} )".format(self.songNumLines)
                    # if len(rhymeGroups) > 0:
                    #     # If this is our 2nd or more iteration, begin tagging on all previously chosen
                    #     # rhyme groups
                    #     havingClause += " AND (`rhymePool` not in ("
                    #     for excludeRhymeGroup in rhymeGroups:
                    #         # self.debugger.message("INFO", rhymeGroups[excludeRhymeGroup]["rhymePoolId"])
                    #         havingClause += str(rhymeGroups[excludeRhymeGroup]["rhymePoolId"]) + ","
                    #     # Strip the last comma.  This sucks but fine for POC
                    #     havingClause = havingClause.rstrip(',')
                    #     havingClause += "))"
                    # havingClause += ")"

                    # rhymeGroup = self.rhymadexDB.query("SELECT `rhymePool` FROM `tblRhymeWords` GROUP BY `rhymePool` \
                    #                                     HAVING {} ORDER BY RAND() LIMIT 1", None,
                    #                                    havingClause).fetchall()[0][0]

                    # rhymeGroups[lineDef[wordIndex]]["rhymePoolId"] = rhymeGroup

        # Joining and selection


#SELECT
#   count(tblLines.id),
#   lastRhymeWords.rhymePool as lastWordRhymeGroup FROM
#   tblLines
#INNER JOIN tblRhymeWords lastRhymeWords ON tblLines.lastWord = lastRhymeWords.word
#where ((tblLines.syllables >= 3) and (tblLines.syllables <=5))
#group by lastWordRhymeGroup having count(tblLines.id) > 12 order by rand() limit 10;

if __name__ == "__main__":
    songDef = [ [None, 1,    None, ["if"], None, 4,    None, "A", 1,    None, None, None],
                ["A",  2,    None, ["if", "with"],   None, 8,    None, "A", 5,    None, None, None],
                [None, None, None, None,   None, 3,    None, "B", None, None, None, None],
                [None, None, None, None,   None, 3,    None, "B", None, None, None, None],
                ["A",  3,    None, None,   None, 9,    None, "A", None, None, None, 1   ],
                [None, None, None, None,   1,    6,    None, "C", None, None, None, None],
                [None, None, None, None,   None, None, 5,   None, None, None, None, None],
                [None, 3,    None, None,   None, 6,    None, "D", None, None, None, None],
                [None, None, None, None,   None, None, None, "D", None, None, None, None],
                [None, None, None, None,   None, 2,    None, "E", None, None, None, None],
                [None, None, None, None,   None, 3,    None, "E", None, None, None, None],
                [None, None, None, None,   None, 9,    None, "D", None, None, None, None],
                [None, None, None, None,   None, None, 5,   None, None, None, None, None],
                [None, None, None, None,   None, None, 5,   None, None, None, None, None] ]

    song = song(songDef)

    # Propose a data structure to represent the song lyric composure
    # SongDef = { "settings": { "sources": [ [source 1], [source 2], ... ] },
    #             "linedef" : [ [line 0 def], [line 1 def], [line 2 def], [line 3 def], ... ] }

    # LineDef =
    #0[ ("FirstWord RhymeGroup" or None) ex "A",                   -> Lines w/same group have rhyming First Words
    #1  (FirstWord SyllableCt or None) ex 3,                       -> Syllable count of first word in this line
    #2  (["FirstWord ExcludeList"] or None) ex ["but", "or"],      -> Exclude lines with these First Words
    #3  (["FirstWord IncludeOnlyList"] or None) ex ["that", "my"], -> Only choose a line with these First Words
    #4  (FirstWord BackReference Index or None) ex 0,              -> Override and simply repeat the word from index n
    #5  (FullLine SyllableCt or None) ex 9,                        -> Syllable count of the whole line
    #6  (FullLine BackReference Index or None) ex 0,               -> Override and simply repeat the line from index n
    #7  ("LastWord RhymeGroup" or None) ex "A",                    -> Lines w/same group have rhyming Last Words
    #8  (LastWord SyllableCt or None) ex 3,                        -> Syllable count of last word in this line
    #9  (["LastWord ExcludeList"] or None) ex ["years", "his"],    -> Exclude lines with these Last Words
    #10 (["LastWord IncludeOnlyList"] or None) ex ["lot", "her"],  -> Only choose a line with these Last Words
    #11 (LastWord BackReference Index or None) ex 0 ]              -> Override and simply repeat the word from index n

    #                                         FirstWord                       FullLine    LastWord
    #                                         RG    SC    Exl   Inc     BR    SC    BR    RG   SC    Exl   Inc   BR
    # If I should stay                     [ [None, 1,    None, ["if"], None, 4,    None, "A", 1,    None, None, None],
    #                                        1 syllable first word, (but overridden by) first word include group "if",
    #                                          4 syllable overall line, last word rhyme group A, 1 syllable last word,
    #
    # I would only be in your way            ["Q",  None, None, None,   None, 8,    None, "A", None, None, None, None],
    #                                        First word rhyme group Q, 8 syllable overall line,
    #                                          Last word rhyme group A,
    #
    # So Ill go,                             [None, None, None, None,   None, 3,    None, "B", None, None, None, None],
    #                                        3 syllable overall line, last word rhyme group B,
    #
    # but I know                             [None, None, None, None,   None, 3,    None, "B", None, None, None, None],
    #                                        3 syllable overall line, last word rhyme group B,
    #
    # Ill think of you each step of the way  ["Q",  None, None, None,   None, 9,    None, "A", None, None, None, 1   ],
    #                                        First word rhyme group Q, 9 syllable overall line,
    #                                        Last word rhyme group A, (but overridden by) last word backreference to
    #                                        line index [1] "way",
    #
    # I will always love you                 [None, None, None, None,   1,    6,    None, "C", None, None, None, None],
    #                                        First word backreference to line index [1] "you",
    #                                        6 syallable overall line, last word rhyme group C,
    #
    # I will always love you                 [None, None, None, None,   None, None, 5,   None, None, None, None, None],
    #                                        Full line backreference to line [5] "I will always love you" ...
    #
    # Bittersweet memories                   [None, 3,    None, None,   None, 6,    None, "D", None, None, None, None],
    # That's all Im taking with me           [None, None, None, None,   None, 7,    None, "D", None, None, None, None],
    # Goodbye,                               [None, None, None, None,   None, 2,    None, "E", None, None, None, None],
    # please dont cry                        [None, None, None, None,   None, 3,    None, "E", None, None, None, None],
    # We both know that Im not what you need [None, None, None, None,   None, 9,    None, "D", None, None, None, None],
    #
    # I will always love you                 [None, None, None, None,   None, None, 5,   None, None, None, None, None],
    # I will always love you                 [None, None, None, None,   None, None, 5,   None, None, None, None, None]]
