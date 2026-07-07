"""Azure ingestion + normalization (Cost Management, read-only).

Second cloud, built against the SAME FOCUS mapping proven on AWS: Azure Cost Management
Query results are normalized into the same `FocusRecord`s and land in the same warehouse,
so a dollar means the same thing across clouds.
"""
