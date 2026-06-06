# Methodology Notes

The project should compare coverage of the same public events across media groups over time.

## Unit of Analysis

The starting event unit is one row in:

```text
fom_events/processed_events/events_table.csv
```

Each event has:

- FOM year and week
- event name
- respondent quote examples
- FOM percentage, when available

The starting media unit is one row in:

```text
news_data/ask_media_unified_messages_20260604.db
```

The main news table is `unified_messages`.

## Event Windows

The FOM event table stores year and week. For analysis, create explicit dates:

- `week_start`
- `week_end`
- `match_start`
- `match_end`

A good default first pass is 3 days before the week and 10 days after the week. This can catch early coverage and delayed recap coverage. For fast-moving events, use a tighter window after manual review.

## Matching News to Events

Start with transparent matching:

1. Use event names and FOM quote examples to build keywords.
2. Search `summary` and, when useful, `original_message`.
3. Keep the exact matched terms and matched text fields.
4. Sample matches and misses before trusting counts.

Later matching can add:

- embeddings, where available
- manually curated aliases
- event-specific exclusion terms
- model-assisted relevance labels

Do not present keyword matches as final truth without manual spot checks.

## Core Metrics

Recommended first dashboard metrics:

- `message_count`: number of matched messages.
- `source_count`: number of sources that covered the event.
- `share_of_voice`: group message count divided by all matched messages for the event.
- `coverage_presence`: whether a group had any matched coverage.
- `first_seen_at`: first matched message date by group.
- `coverage_lag_hours`: lag from event window start to first matched message.
- `views_total`: sum of views where available.
- `forwards_total`: sum of forwards where available.
- `top_terms`: repeated words or phrases by group after basic cleanup.

## Framing Comparison

Framing should be treated as a measured text pattern, not as a vague impression.

Good first-pass framing signals:

- repeated verbs and nouns
- named actors
- blame or responsibility terms
- conflict, threat, loss, success, corruption, or stability frames
- quotes or slogans repeated by one group more than others
- topics present in one group and absent in another

Always show example messages behind frame claims.

## Dashboard Shape

A useful first dashboard should let the reader:

- choose an event or week
- see FOM public-attention percentage
- compare media groups by coverage volume
- inspect first mention timing
- see group-specific words and example messages
- find groups with low or no coverage

The dashboard should not require daily refreshing. It should make historical comparison easy.
