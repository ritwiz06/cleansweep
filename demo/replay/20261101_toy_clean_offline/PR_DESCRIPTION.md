Cleanup by CleanSweep (safe mode): 7 edits, 44 lines and 3 files removed. Result: everything runs.

- P1: Remove 1 unused import in shopcart/cart.py (kept)
- P2: Remove 1 unused import in shopcart/commands.py (kept)
- P3: Remove 1 leftover file in debug_cart.py (kept)
- P4: Remove 1 leftover file in reproduce_bug.py (kept)
- P5: Remove 1 unused dependency in requirements.txt (kept)
- P6: Remove 1 leftover file in shopcart/pricing_old.py (kept)
- P10: Remove 1 unused function or class in shopcart/utils.py (kept)

Tests: baseline 15 passing; after 15 passing; new failures: 0.
Every package was tested and checked before it was kept; see CLEANUP_REPORT.md.
