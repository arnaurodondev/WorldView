# THIS FILE HAS BEEN REMOVED.
# Worker 13D-6 (EconomicEventsWorker) has been replaced by the Kafka consumer
# EconomicEventsDatasetConsumer in:
#   knowledge_graph.infrastructure.messaging.consumers.economic_events_dataset_consumer
raise ImportError(
    "knowledge_graph.infrastructure.workers.economic_events_worker has been removed. "
    "Use EconomicEventsDatasetConsumer from "
    "knowledge_graph.infrastructure.messaging.consumers.economic_events_dataset_consumer instead."
)
