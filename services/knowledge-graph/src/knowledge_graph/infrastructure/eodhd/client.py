# THIS FILE HAS BEEN DELETED.
# Workers 13D-6, 13D-7, 13D-8 have been migrated from direct EODHD API calls
# to Kafka consumers that read from market.dataset.fetched (produced by S2).
# The EodhDClient is no longer used in S7.
raise ImportError(
    "knowledge_graph.infrastructure.eodhd.client has been removed. "
    "Use the Kafka consumers in knowledge_graph.infrastructure.messaging.consumers "
    "instead: EconomicEventsDatasetConsumer, MacroIndicatorDatasetConsumer, "
    "InsiderTransactionsDatasetConsumer.",
)
