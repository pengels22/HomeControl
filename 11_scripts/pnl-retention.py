#!/usr/bin/env python3
"""Print a dry-run PNL retention plan; execution requires an explicit wrapper."""
from importlib import import_module

policy = import_module('01_HCM.pnl_retention').PNLRetentionPolicy()
print('PNL retention dry-run policy:', policy)
print('No database changes are made by this command.')
