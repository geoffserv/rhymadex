# rhymadex

```
he went to the couch on which he slept
the man of god wept
describe landscapes with the wind
the treaty was signed
they kept
of the earth
of the earth
day that these things shall be performed
i am well informed
i saw an angel come down from heaven
she hath hewn out her seven
they formed
of the earth
of the earth
```

(Interesting, it rhymed "wind" as in "wind a clock" instead of "wind" as in "wind from the north")

rhymadex is a database of sentence fragments which are stored alongside metadata (such as fullLine syllable count) and
firstWord/lastWord "rhyme Pool ID".  The rhyme Pool ID groups clusters of words which mutually rhyme.  As a result, it
is possible to select lines from the rhymadex database which fit in to the rhyme and rhythm structure of some
specified verse.

### `songwriter` proof of concept

The [songwriter](https://github.com/geoffserv/songwriter) is a simple and quick implementation of this concept. It
earned further exploration of the idea by delighting us with cute and silly poems composed of lines gleaned from various
source texts.  However, it processes one text at a time, has a hard-coded verse structure, does everything in-memory,
etc.  `rhymadex` is a first attempt at re-writing the idea to be more flexible, database driven, multi-source capable,
and so on.

## Building the rhymadex database

This is built on MariaDB currently.  So fire up your MariaDB and then add a file alongside these scripts,

`mariadb.cfg`:
```
[mariadb]
username = ...
password = ...
host = ...
database = rhymadex
port = 3306
```
Pick some texts to feed the rhymadex.  It's going to try and open the txt file as ISO-8859-1.

For example, adding Homer's Odyssey to the rhymadex:

```python
if __name__ == "__main__":
    rhymadex = rhymadex("textsources/odyssey/odyssey.txt")
```

Running the builder:

```
INFO- Connecting to MariaDB server: (redacted)
INFO- Checking for database rhymadex
INFO- Database found.  Opening.
INFO- Found rhymadex version 1 created 2021-09-23 16:19:17
INFO- Initializing Rhymer
INFO- seenRhymeWords pulled from DB: 91804
INFO- Opening file for processing: textsources/odyssey/odyssey.txt
INFO- Line entries found: 21097
PROGRESS- Estimated build progress: 99 % ... Done.
DEBUG SUMMARY- SeenRhymeWords: 91804
DEBUG SUMMARY- TotalLinesSeen: 21097
DEBUG SUMMARY- TotalDiscardedLines: 187
DEBUG SUMMARY- TotalLinesProcessed: 21097
DEBUG SUMMARY- WontFitLines: 187
DEBUG SUMMARY- TotalWordsProcessed: 125140
DEBUG SUMMARY- TotalSyllablesSeen: 173725
DEBUG SUMMARY- DbInsertsLines: 18758
DEBUG SUMMARY- TotalUnrhymable: 896
DEBUG SUMMARY- DbInsertsRhymeWords: 196
DEBUG SUMMARY- Runtime: 45.18288588523865 seconds

Process finished with exit code 0
```

The `rhymadex_builder.py` script:
* Connects to the DB, searches for an existing rhymadex DB, creates one if not there, sets up the schema
* Splits the entire input text by any of the punctuation: `,`, `.`, `!`, `?`, `;`, `:`, `\t`, `\n`
* Runs each sentence fragment through a line cleaner method which tries to filter out clutter, formatting chars, etc.
* The resulting sentence fragments are saved to the rhymadex.
* The firstWord and lastWord of each fragment are referenced against a rhyme dictionary, if they haven't been 
encountered by the rhymadex ever before.
* The words are saved to the rhymadex and grouped by an internal rhymePoolId which is meant to associate all words
together which mutually rhyme.

Processing a source text is **very slow**.  Processing the Odyssey took just over 45 seconds for 21097 line fragments. 
That resulted in 18758 new lines inserted to the rhymadex database, 196 new words seen and queried against the rhyme 
dictionary and also saved to the rhymadex (augmenting the 91804 already-seen and already-grouped rhymewords in my 
rhymadex instance.  I've been adding a lot of source texts for testing.)

Each line is run through a syllable estimator.  **The syllable estimator is inaccurate**.

Run this once per source text.  The idea is to add *a lot* of source texts.  Get lots and lots of different words,
sentence fragments, line lengths, rhymePools and so on indexed in the database.

If you **re-run** the `rhymadex_builder.py` against an already-indexed text source, it will drop all previously stored
lines which were gleaned from that text, but *leave the rhymeWords in place* (because they may be implicated in other
subsequent texts).  Then it will re-process each line and store it again.  So you can re-run texts through the 
`rhymadex_builder.py` if there has been some source text clean-up or changes to the line cleaner code, etc and get
fresh, clean new results in tblLines.

## Building verses

With a sufficiently-primed rhymadex database, specify a song structure.  As an example, think about Dolly Parton's
"I Will Always Love You":

```
# If I should stay
# I would only be in your way
# So Ill go,
# but I know
# Ill think of you each step of the way
# I will always love you
# I will always love you
# Bittersweet memories
# That's all Im taking with me
# Goodbye,
# please dont cry
# We both know that Im not what you need
# I will always love you
# I will always love you
```

I can roughly represent this verse structure in the `rhymadex_explorer.py` data structure `songDef`.  It is a list with 
each list element being a line of the song.  Each line is also a list, with the following attributes:
```python
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
```
Presently, only `0`, `5`, `6`, and `11` are implemented, that is, firstWord rhymeGroup, fullLine syllables, fullLine
backReference, and lastWord rhymeGroup.

So I can roughly represent the song above as:
```python
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
```

That is:
* Line 0 is 9 syllables, the last word in Rhyme Group "A"
* Line 1 is 6 syllables, the last word in Rhyme Group "A"
* Line 2 is 9 syllables, the last word in Rhyme Group "B"
* [...]
* Line 5 is 2 syllables, the last word in Rhyme Group "C"
* Line 6 is a backReference to line 5, so just repeat line 5
* Line 7 is 9 syllables, the last word in Rhyme Group "D"
* [...]
* Line 12 is a backReference to line 5, so just repeat line 5
* Line 13 is a backReference to line 5, so just repeat line 5

The `rhymadex_explorer.py` script:
* Tries to pre-process the songDef and collect facts about each implicated rhymeGroup.  Where is it used?  How often?
Etc.  Then, tries to build a query to search for rhymeGroups that should satisfy that use case.  The idea is to get a 
list of compatible rhymePoolIDs for the verse line queries coming up later.
* Run the rhymePoolID search queries and store a list of potential matches.  Currently they're ordered by rand() so 
each run is a bag of surprises.
* Then try to build and run a line selection query for each line of the verse.  Exclude previously-seen words in the 
rhymeGroups as we go.
* Hopefully the rhymePoolID candidate selection queries have resulted in rhymePools with enough of each line length and 
enough diversity of word options to build whole verses.  This is the idea.

**Because the syllable estimator is inaccurate,** there is a setting in the `song` class to specify a syllablePadding
value, default reasonably being,
```python
self.syllablePadding = 1
```
Which will mean that if you specify a line length of 9 syllables, the `rhymadex_explorer.py` will search for lines which
are 9 +- 1 syllables.  Casting a larger net.  It's up to the viewers to decide how to use the output.

Then I can tell it, for example, have the rhymeGroup search look for 1 candidate groupset, and try to build me 1 song
per candidate group pairing:

```python
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

    song = song(songDef, 1)
    song.generateSongBook(song.songDef, song.rhymeGroups, 1)
```

And run it:
```
* Song Definition:
** Line id 0: lastWord rhymeGroup: A, full-line Syllables: 9 +- 1, 
** Line id 1: lastWord rhymeGroup: A, full-line Syllables: 6 +- 1, 
** Line id 2: lastWord rhymeGroup: B, full-line Syllables: 9 +- 1, 
** Line id 3: lastWord rhymeGroup: B, full-line Syllables: 6 +- 1, 
** Line id 4: lastWord rhymeGroup: A, full-line Syllables: 2 +- 1, 
** Line id 5: lastWord rhymeGroup: C, full-line Syllables: 2 +- 1, 
** Line id 6: full-line backRef index: 5, 
** Line id 7: lastWord rhymeGroup: D, full-line Syllables: 9 +- 1, 
** Line id 8: lastWord rhymeGroup: D, full-line Syllables: 6 +- 1, 
** Line id 9: lastWord rhymeGroup: E, full-line Syllables: 9 +- 1, 
** Line id 10: lastWord rhymeGroup: E, full-line Syllables: 6 +- 1, 
** Line id 11: lastWord rhymeGroup: D, full-line Syllables: 2 +- 1, 
** Line id 12: full-line backRef index: 5, 
** Line id 13: full-line backRef index: 5, 

* RhymeGroups Summary:
** rhymeGroups["A"]: ..["rhymePoolCandidates"]: Pool IDs [150]
** rhymeGroups["B"]: ..["rhymePoolCandidates"]: Pool IDs [177]
** rhymeGroups["C"]: ..["rhymePoolCandidates"]: Pool IDs [2]
** rhymeGroups["D"]: ..["rhymePoolCandidates"]: Pool IDs [94]
** rhymeGroups["E"]: ..["rhymePoolCandidates"]: Pool IDs [458]

had been inherited by his son
there's nothing to be done
wherein he hath made us accepted
orion only excepted
the big gun
all the earth
all the earth
many there be which say of my soul
negative pole
thus shalt thou say to the prophet
what doth it profit
as whole
all the earth
all the earth


Process finished with exit code 0
```

In practice I might specify 10 rhymePool candidate groupsets, and 8 verses per groupset, and get a big variety of
weird candidate verses, by doing like:
```python
    song = song(songDef, 10)
    song.generateSongBook(song.songDef, song.rhymeGroups, 8)
```

## Next steps

* Deploy the `rhymadex_explorer.py` classes as part of a MVP webapp.
* I think I've already learned that firstWord rhyming doesn't matter much for the massive complexity it introduces.
    * Possibly deploy on lastWord rhyming only.  lastWord is the "most interesting" word position to rhyme against IMO.
    * In so much as firstWord is interesting to specify in a verse rhyme structure, any word position is interesting.
    * So, kick that can down the road.  Maybe revisit later with an experimental implementation that can track and
rhyme any word position anywhere in the verse.
* Syllable estimator is inaccurate, that can be improved.
* RhymeGroup selection queries are definitely inaccurate.  These need to be refactored.
* Database schema can probably be optimized by including the rhymePoolID as a column in tblLines itself.
* RhymeGroup queries are definitely the most slow, dangerously slow for web deployment.  So think about that.
* Probs a better DBMS than MariaDB for this use case.