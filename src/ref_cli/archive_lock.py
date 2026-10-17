"""Process-local lock serializing ``references.md`` read/modify/write transactions.

``references.md`` is mutated by several paths — appends (``append_to_file``),
whole-file read-modify-write (``update_reference_entry``,
``update_transcript``), and whole-file rewrites driven by enrichment
(``references_format.apply_row_updates``). All of these must commit their
*read/decide/write* section under ONE shared lock so that a concurrent
append/rewrite is never silently lost, while slow network/provider work stays
outside the lock.

This is a **process-local** lock (a ``threading.RLock``). It serializes threads
within a single process (the ``ref-api`` host, which runs the show-note worker
and every request). It does **not** coordinate independent OS processes — e.g. a
``ref`` CLI command running directly against the same archive in another process
is not serialized by this lock. That cross-process limitation is a pre-existing
property of the single-writer-on-the-API-host deployment model and is not
changed here.
"""

from __future__ import annotations

import threading

archive_lock = threading.RLock()
