"""expenseTracker core: capture expenses and hand them to the `finance` node.

Pure pipeline pieces (importers, classifier, reconciler, writer). Nothing in
this package talks to a database or to the network directly: the ledger and
the merchant store are Protocols, wired by `expense_tracker_backend`.
"""
