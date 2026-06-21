"""Longshot-short paper-trading harness.

Sells overpriced 1-12c Kalshi longshots near settlement, paper mode, against the
live order book. A loop writes file-state to a host bind-mount; the api
container serves it read-only at /api/v1/longshot/status.
"""
