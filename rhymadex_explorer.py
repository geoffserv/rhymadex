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

        # Consider candidates which are plus-or-minus this many syllables per line
        # The syllable estimator is inaccurate, and good option to keep the pipeline
        # a bit wider while querying for candidate lines
        self.syllablePadding = 1

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
        # Values are a list:
        # [0] = location of rhymeGroup identifier like "A", "B" ... in lineDef
        # [1] = location of syllable requirements ... in lineDef
        # [2] = location of include-only lists ... in lineDef
        # [3] = location of exclude lists ... in lineDef
        wordIndices = {"firstWord": {"rhymeGroup": 0, "options": { "Syllables": 1, "Exclude": 2, "IncludeOnly": 3 } } ,
                       "lastWord" : {"rhymeGroup": 7, "options": { "Syllables": 8, "Exclude": 9, "IncludeOnly": 10 } } }

        for lineDef in self.songDef:
            for wordIndex in wordIndices: # loop through "firstWord" then "lastWord"
                if lineDef[wordIndices[wordIndex]["rhymeGroup"]]: # If there is a rhymeGroup Identifier found like "A"
                    # This line has a rhymeGroup in either the first or lastWord position
                    if lineDef[wordIndices[wordIndex]["rhymeGroup"]] not in rhymeGroups:
                        # and we haven't encountered it before, so initialize a sub-dict
                        rhymeGroups[lineDef[wordIndices[wordIndex]["rhymeGroup"]]] = {}
                    # record the position it's been found in like 'firstWord':True
                    rhymeGroups[lineDef[wordIndices[wordIndex]["rhymeGroup"]]][wordIndex] = True

                    for lineOption in wordIndices[wordIndex]["options"]:
                        # loop through each of the line options pertaining to a firstWord or lastWord
                        if lineDef[wordIndices[wordIndex]["options"][lineOption]]:
                            # If one of the options has been defined for this line...
                            if not wordIndex + lineOption in rhymeGroups[lineDef[wordIndices[wordIndex]["rhymeGroup"]]]:
                                # And it's the first time we've encountered this rhymeGroup w/ such a restriction
                                # Initialize a list to hold the restriction
                                rhymeGroups[lineDef[wordIndices[wordIndex]["rhymeGroup"]]][wordIndex + lineOption] = []
                            # Record this restriction for this position

                            rhymeGroups[lineDef[wordIndices[wordIndex]["rhymeGroup"]]][wordIndex + lineOption].\
                              append(lineDef[wordIndices[wordIndex]["options"][lineOption]])

        self.debugger.message("INFO", rhymeGroups)

        for rhymeGroup in rhymeGroups:
            self.debugger.message("INFO", "Rhymegroup {}:".format(rhymeGroup))
            for wordIndex in wordIndices:
                if wordIndex in rhymeGroups[rhymeGroup]:
                    self.debugger.message("INFO", "   Used as a {}".format(wordIndex))
                for lineOption in wordIndices[wordIndex]["options"]:
                    if wordIndex + lineOption in rhymeGroups[rhymeGroup]:
                        self.debugger.message("INFO", "   {}: {}".
                                              format(wordIndex + lineOption,
                                                     rhymeGroups[rhymeGroup][wordIndex + lineOption]))

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
                [None, None, None, None,   None, 7,    None, "D", None, None, None, None],
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
    # [ ("FirstWord RhymeGroup" or None) ex "A",                   -> Lines w/same group have rhyming First Words
    #   (FirstWord SyllableCt or None) ex 3,                       -> Syllable count of first word in this line
    #   (["FirstWord ExcludeList"] or None) ex ["but", "or"],      -> Exclude lines with these First Words
    #   (["FirstWord IncludeOnlyList"] or None) ex ["that", "my"], -> Only choose a line with these First Words
    #   (FirstWord BackReference Index or None) ex 0,              -> Override and simply repeat the word from index n
    #   (FullLine SyllableCt or None) ex 9,                        -> Syllable count of the whole line
    #   (FullLine BackReference Index or None) ex 0,               -> Override and simply repeat the line from index n
    #   ("LastWord RhymeGroup" or None) ex "A",                    -> Lines w/same group have rhyming Last Words
    #   (LastWord SyllableCt or None) ex 3,                        -> Syllable count of last word in this line
    #   (["LastWord ExcludeList"] or None) ex ["years", "his"],    -> Exclude lines with these Last Words
    #   (["LastWord IncludeOnlyList"] or None) ex ["lot", "her"],  -> Only choose a line with these Last Words
    #   (LastWord BackReference Index or None) ex 0 ]              -> Override and simply repeat the word from index n

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
