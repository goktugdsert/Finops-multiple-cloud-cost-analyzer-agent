"""Synthetic AWS Cost Explorer provider (demo data, no AWS account required).

Generates Cost Explorer-shaped `GetCostAndUsage` responses built from realistic AWS
us-east-1 on-demand rates x modeled usage, plus RI/Savings-Plan amortization, credits,
and tax. It feeds the SAME `flatten_response -> normalize_records -> warehouse` pipeline
as the real AWS path, so nothing here is throwaway.

This is clearly-labeled SYNTHETIC data: it validates the plumbing, the cost math, and the
FOCUS mapping's shape. It does NOT prove our metric mapping matches a real Cost Explorer
console — that reconciliation still requires a live account (see normalize.py).
"""
