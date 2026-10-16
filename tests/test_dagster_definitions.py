"""Fast structural tests for the Dagster graph; no pipeline data is rebuilt here."""

import dagster as dg

from events_coverage.definitions import defs


def test_definitions_are_loadable() -> None:
    dg.Definitions.validate_loadable(defs)


def test_static_graph_connects_sources_dbt_and_metabase() -> None:
    graph = defs.resolve_asset_graph()

    expected_keys = {
        dg.AssetKey(["source", "validated_static_inputs"]),
        dg.AssetKey(["raw", "fom_events"]),
        dg.AssetKey(["raw", "event_matches"]),
        dg.AssetKey("stg_events"),
        dg.AssetKey("event_overview"),
        dg.AssetKey(["reporting", "metabase_snapshot"]),
    }
    assert expected_keys <= graph.get_all_asset_keys()
    assert {
        dg.AssetKey(["reporting", "dashboard_data"]),
        dg.AssetKey(["reporting", "prototype_dashboard"]),
    }.isdisjoint(graph.get_all_asset_keys())

    assert dg.AssetKey(["raw", "fom_events"]) in graph.get(
        dg.AssetKey("stg_events")
    ).parent_keys
    assert dg.AssetKey("event_overview") in graph.get(
        dg.AssetKey(["reporting", "metabase_snapshot"])
    ).parent_keys


def test_every_dbt_data_test_is_an_asset_check() -> None:
    # dbt build runs 129 data tests. Each must surface as a Dagster asset check; tests on
    # sources and singular tests over several models drop silently to observations
    # unless the dbt translator and the test's meta say where to attach them.
    graph = defs.resolve_asset_graph()
    check_keys = graph.asset_check_keys

    assert len(check_keys) == 129
    assert dg.AssetCheckKey(
        dg.AssetKey(["raw", "media_groups"]), "source_unique_raw_media_groups_source"
    ) in check_keys
    assert dg.AssetCheckKey(
        dg.AssetKey("event_overview"), "assert_matched_posts_match_the_build_manifests"
    ) in check_keys
