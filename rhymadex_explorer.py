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

        self.songDef = songDef
        self.songNumLines = len(self.songDef)

        self.generateSong()

    def generateSong(self):
        # Tally up how many unique rhymegroups there are.  Initialize a dict to associate a rhymepool
        # with each rhymegroup
        rhymeGroups = { }

        for lineDef in self.songDef:
            # Check firstWord[0] and lastWord[7] rhymeGroups
            for wordIndex in [0, 7]:
                if lineDef[wordIndex] and lineDef[wordIndex] not in rhymeGroups:
                    # Pick out a rhymeGroup ID for this new rhymeGroup.
                    # Look for groups with more candidates than there are lines in this song,
                    # to assure some interesting results

                    # Build a HAVING clause as we go, to make sure every next choice is a new choice
                    havingClause = "((COUNT(`id`) > {} )".format(self.songNumLines)
                    if len(rhymeGroups) > 0:
                        # If this is our 2nd or more iteration, begin tagging on all previously chosen
                        # rhyme groups
                        havingClause += " AND (`rhymePool` not in ("
                        for excludeRhymeGroup in rhymeGroups:
                            # self.debugger.message("INFO", rhymeGroups[excludeRhymeGroup]["rhymePoolId"])
                            havingClause += str(rhymeGroups[excludeRhymeGroup]["rhymePoolId"]) + ","
                        # Strip the last comma.  This sucks but fine for POC
                        havingClause = havingClause.rstrip(',')
                        havingClause += "))"
                    havingClause += ")"

                    rhymeGroup = self.rhymadexDB.query("SELECT `rhymePool` FROM `tblRhymeWords` GROUP BY `rhymePool` \
                                                        HAVING {} ORDER BY RAND() LIMIT 1", None,
                                                       havingClause).fetchall()[0][0]
                    rhymeGroups[lineDef[wordIndex]] = { }
                    rhymeGroups[lineDef[wordIndex]]["rhymePoolId"] = rhymeGroup

        self.debugger.message("INFO", rhymeGroups)
            #candidateLines = self.rhymadexDB.query("SELECT `tblLines`.`line` FROM `tblLines` \
            #                                        WHERE (`tblLines`.`syllables` = ?

if __name__ == "__main__":
    songDef = [ [None, 1,    None, ["if"], None, 4,    None, "A", 1,    None, None, None],
                ["Q",  None, None, None,   None, 8,    None, "A", None, None, None, None],
                [None, None, None, None,   None, 3,    None, "B", None, None, None, None],
                [None, None, None, None,   None, 3,    None, "B", None, None, None, None],
                ["Q",  None, None, None,   None, 9,    None, "A", None, None, None, 1   ],
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
