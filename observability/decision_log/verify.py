"""Journal verification command: `python -m observability.decision_log.verify <root> <run_id>`.

Exit 0 = chain verified; exit 1 = problems reported (corruption, sequence gaps, hash mismatch, duplicate ids,
truncation). Read-only: never repairs or rewrites the journal."""

from __future__ import annotations

import sys

from observability.decision_log.events import JournalError
from observability.decision_log.journal import journal_path, read_journal_file


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m observability.decision_log.verify <journal_root> <run_id>")
        return 2
    try:
        _, rep = read_journal_file(journal_path(argv[0], argv[1]))
    except JournalError as e:
        print(f"FAILED {e}")
        return 1
    print(f"events={rep.event_count} head_hash={rep.head_hash} content_digest={rep.content_digest}")
    for code, detail in rep.errors:
        print(f"  {code}: {detail}")
    print("OK" if rep.ok else "FAILED")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
