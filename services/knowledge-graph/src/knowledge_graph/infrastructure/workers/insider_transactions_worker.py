# THIS FILE HAS BEEN REMOVED.
# Worker 13D-8 (InsiderTransactionsWorker) has been replaced by the Kafka consumer
# InsiderTransactionsDatasetConsumer in:
#   knowledge_graph.infrastructure.messaging.consumers.insider_transactions_dataset_consumer
raise ImportError(
    "knowledge_graph.infrastructure.workers.insider_transactions_worker has been removed. "
    "Use InsiderTransactionsDatasetConsumer from "
    "knowledge_graph.infrastructure.messaging.consumers.insider_transactions_dataset_consumer instead."
)
