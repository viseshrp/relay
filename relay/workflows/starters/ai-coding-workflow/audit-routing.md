# Relay audit routing

In the existing Disposition section of TEST_AUDIT.md, include
exactly one standalone routing line:
Next phase: done
Next phase: tests
Next phase: human

Use done only if every success criterion passes and both
issue sections contain None. Use tests only when every
remaining actionable finding is test-only and can be
addressed within phase 09. Use human for production or
documentation changes, unresolved decisions, or blockers.
This routing line does not replace the complete audit.
Change no file other than TEST_AUDIT.md and do not commit it.
