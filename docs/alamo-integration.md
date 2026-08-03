# ALAMO integration contract

The first integration can launch `zph watch` as a sidecar. That keeps networking,
authentication, retries, and protocol evolution outside the solver process.

When ALAMO receives `--post`, it should:

1. discover `zph` on `PATH` and start `zph watch OUTPUT_DIRECTORY --pid PID`;
2. continue the simulation even if the sidecar cannot start, while printing a
   clear warning;
3. write `metadata` and `thermo.dat` atomically or append-only as it does today;
4. wait briefly for the sidecar during a normal shutdown so it can post the
   terminal heartbeat.

For schedulers where `/proc/PID` is unavailable, run ALAMO through
`zph run -- alamo ...`; this preserves the child exit code and records
`completed`, `failed`, or `interrupted` accurately.

The sidecar performs no scientific calculation. It polls file changes at a
30-second default interval, sends only appended thermo rows, retries safely via
sequence numbers, and never reads credentials from the simulation directory.

Future direct C++ integration should implement the same `/api/v1` operations
behind a non-blocking queue with a bounded memory budget. It should not make
solver progress depend on network availability.
