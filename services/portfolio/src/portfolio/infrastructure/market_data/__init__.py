"""Infrastructure adapters that talk to S3 (market-data) over REST.

R9: cross-service access is REST-only — never DB. The adapters in this
package are the ONLY path through which application use cases reach
S3 from S1.
"""
