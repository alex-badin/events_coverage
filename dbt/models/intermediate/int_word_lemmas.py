"""Grain: one distinct word of the matched posts, with the dictionary form it is counted under.

Russian changes a word's ending by case, number and person, so «война», «войны» and «войну» have
to be counted as one word. pymorphy3 looks each word up in the OpenCorpora dictionary of Russian
and returns its dictionary form: «войны» -> «война», «людей» -> «человек». It sees the word on
its own, without the sentence, so a word that can be read two ways gets the more common reading;
seeds/word_lemma_overrides.csv corrects the frequent misreadings («песков» is read as the plural
of «песок»).

A Python model because the dictionary is a Python library. It runs once per distinct word, about
380 thousand of them, not once per word use.
"""

import pymorphy3


def model(dbt, session):
    dbt.config(materialized="table")

    words = (
        dbt.ref("int_post_tokens")
        .filter("not is_stopword and not is_number and not is_source_name and length(word) >= 3")
        .project("word")
        .distinct()
        .df()
    )

    morph = pymorphy3.MorphAnalyzer()
    words["lemma"] = [morph.parse(word)[0].normal_form for word in words["word"]]
    words["lemma_source"] = "dictionary"

    overrides = dbt.ref("word_lemma_overrides").df().set_index("word")["lemma"]
    overridden = words["word"].isin(overrides.index)
    words.loc[overridden, "lemma"] = words.loc[overridden, "word"].map(overrides)
    words.loc[overridden, "lemma_source"] = "override"

    return words
