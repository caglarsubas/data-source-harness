#!/usr/bin/env python3
"""Fail when executable automation can provision cloud or cluster resources."""

from pathlib import Path

from data_source_harness.local_only import assert_local_only_automation


def main() -> int:
    assert_local_only_automation(Path(__file__).resolve().parents[1])
    print("local-only automation guard: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
