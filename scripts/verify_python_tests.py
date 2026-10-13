"""Verify complete serial/parallel execution using pytest's native JUnit reports."""

from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import sys
from typing import Any
import xml.etree.ElementTree as ET


def verify(directory: Path) -> None:
    inventory: dict[str, Any] = json.loads(
        (directory / "inventory.json").read_text(encoding="utf-8")
    )
    collected = inventory["collected"]
    expected = {item["nodeid"]: item for item in collected}
    if not expected or len(expected) != len(collected) or not inventory["checkout_sha"]:
        message = "Empty, duplicated, or unidentified Python inventory"
        raise ValueError(message)
    for lane in ("serial", "parallel"):
        report = ET.parse(directory / f"junit-{lane}.xml")  # noqa: S314 - our pytest output
        cases = report.findall(".//testcase")
        wanted = {
            nodeid
            for nodeid, item in expected.items()
            if bool(item["serial_integration"]) == (lane == "serial")
        }
        actual: Counter[str] = Counter()
        for case in cases:
            properties = {
                prop.attrib["name"]: prop.attrib.get("value", "")
                for prop in case.findall("./properties/property")
            }
            nodeid = properties.get("relay_nodeid", "")
            actual[nodeid] += 1
            if properties.get("relay_checkout") != inventory["checkout_sha"]:
                message = f"JUnit checkout mismatch: {nodeid}"
                raise ValueError(message)
            if case.find("failure") is not None or case.find("error") is not None:
                message = f"Failed Python execution: {nodeid}"
                raise ValueError(message)
            if (skipped := case.find("skipped")) is not None:
                reason = skipped.attrib.get("message", "").removeprefix("Skipped: ")
                declared = expected.get(nodeid, {}).get("skip_reasons", [])
                platform_skip = reason.startswith("symlinks are unavailable here:") or reason == (
                    "Directory symlinks are unavailable for this test account"
                )
                local_node_skip = (
                    not os.environ.get("CI")
                    and nodeid.split("::")[0].endswith("test_actions_javascript.py")
                    and reason
                    in {
                        "Node.js 20 is not installed for this optional integration check.",
                        "Node.js 24 is not installed for this optional integration check.",
                    }
                )
                if reason not in declared and not platform_skip and not local_node_skip:
                    message = f"Unexplained Python skip: {nodeid}: {reason}"
                    raise ValueError(message)
        if actual != Counter(dict.fromkeys(wanted, 1)):
            message = f"Missing, duplicated, or unexpected tests in {lane} JUnit report"
            raise ValueError(message)
    print(f"Verified {len(expected)} Python tests across both lanes.")


def main() -> int:
    try:
        verify(Path(sys.argv[1]))
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
        print(f"Python completeness check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
