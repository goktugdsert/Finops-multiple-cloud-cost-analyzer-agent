"""GCP ingestion + normalization (BigQuery billing export, read-only).

Third cloud, same FOCUS mapping. GCP cost data comes from the standard BigQuery billing
export; its rows are normalized into the same `FocusRecord`s and land in the same
warehouse, so spend is directly comparable across AWS/Azure/GCP.
"""
