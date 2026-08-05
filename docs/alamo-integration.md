# Alamo integration contract

Alamo launches `zph watch` as a sidecar. That keeps networking, authentication,
retries, and protocol evolution outside the solver process.

When Alamo receives `--post`, it:

1. discovers `zph` on `PATH` and starts `zph watch OUTPUT_DIRECTORY --pid PID`;
2. continues the simulation even if the sidecar cannot start, while printing a
   clear warning;
3. writes `metadata` and `thermo.dat` atomically or append-only as before;
4. waits briefly for the sidecar during a normal shutdown so it can post the
   terminal heartbeat.

Authentication is a configuration step, separate from simulation execution:

```console
./configure --zephyr https://zephyr.solids.group
```

`configure` invokes `zph login`, which prints and opens a short-lived browser
link and waits for Google login to complete. `zph` stores the resulting
credential in the user's normal configuration directory. The Alamo executable
accepts no Zephyr URL or credential; `--post` is strictly a boolean switch.

For schedulers where `/proc/PID` is unavailable, run Alamo through
`zph run -- alamo ...`; this preserves the child exit code and records
`completed`, `failed`, or `interrupted` accurately.

The sidecar performs no scientific calculation. It polls file changes at a
30-second default interval, sends only appended thermo rows, retries safely via
sequence numbers, and never reads credentials from the simulation directory.

Future direct C++ integration should implement the same `/api/v1` operations
behind a non-blocking queue with a bounded memory budget. It should not make
solver progress depend on network availability.
