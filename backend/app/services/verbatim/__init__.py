"""Verbatim background tasks that need Kalshi and/or the Verbatim database.

These run on EC2, not the GPU box: the worker holds no Kalshi key and no database
credentials by design. See daemon.py for why they ship disabled.
"""
