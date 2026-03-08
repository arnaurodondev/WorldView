"""Schema version constants.

Bump the version BEFORE changing the corresponding dataclass shape.
Consumers use this to decide if they can handle the payload.
"""

OHLCV_SCHEMA_VERSION: int = 1
MARKET_DATASET_FETCHED_SCHEMA_VERSION: int = 1
QUOTE_SCHEMA_VERSION: int = 1
FUNDAMENTAL_SCHEMA_VERSION: int = 1
ARTICLE_SCHEMA_VERSION: int = 1
ENTITY_SCHEMA_VERSION: int = 1
SENTIMENT_SCHEMA_VERSION: int = 1
