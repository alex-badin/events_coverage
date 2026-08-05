{#
  Cut the grammatical ending off a Russian word so that different forms of the same word
  count as one.

  Why this is needed: Russian nouns, adjectives and verbs change their ending by case,
  number, gender and person. Without this, "Суджа", "Суджи" and "Судже" would be counted
  as three separate words and none of them would look frequent enough to notice.

  What it does: removes one ending from the end of the word, longest ending first. This is
  a rough version of the standard Russian stemmer — it is not a dictionary, so it will
  occasionally cut the wrong thing. Two guards keep the damage small: words shorter than
  six letters are left alone, and a word is never cut below four letters.

  Because the cut word is often not a real word, the models keep the most common full
  spelling alongside it and that is what the dashboard displays.
#}

{% macro russian_stem(column) %}
    case
        when length({{ column }}) < 6 then {{ column }}
        else
            case
                when length(regexp_replace(
                        {{ column }},
                        '(иями|ями|ами|ого|его|ому|ему|ыми|ими|ыхся|ился|илась|ались|'
                        || 'ает|ают|ять|ить|еть|ать|ешь|ишь|ится|ется|ются|атся|ился|'
                        || 'ая|яя|ое|ее|ые|ие|ый|ий|ой|ей|ам|ям|ах|ях|ов|ев|ью|ия|ие|'
                        || 'ем|ом|ла|ло|ли|ль|ит|ат|ят|ут|ют|ся|сь|'
                        || 'а|я|о|е|у|ю|ы|и|й|ь)$',
                        '')) >= 4
                then regexp_replace(
                        {{ column }},
                        '(иями|ями|ами|ого|его|ому|ему|ыми|ими|ыхся|ился|илась|ались|'
                        || 'ает|ают|ять|ить|еть|ать|ешь|ишь|ится|ется|ются|атся|ился|'
                        || 'ая|яя|ое|ее|ые|ие|ый|ий|ой|ей|ам|ям|ах|ях|ов|ев|ью|ия|ие|'
                        || 'ем|ом|ла|ло|ли|ль|ит|ат|ят|ут|ют|ся|сь|'
                        || 'а|я|о|е|у|ю|ы|и|й|ь)$',
                        '')
                else {{ column }}
            end
    end
{% endmacro %}
