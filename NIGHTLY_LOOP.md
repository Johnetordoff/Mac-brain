# Nightly Mac Brain Improvement Loop

Mac Brain improves by measurement, not by assuming that a new change is better.

## Nightly cycle

While the mission is already active and the Mac is on AC power, the background worker runs
one nightly self-review in the four-hour window beginning at the configured local
`nightly_hour` (default midnight). This does not activate Mac Brain after a reboot and does
not weaken the explicit `START MAC BRAIN` lifecycle rule.

A nightly run:

1. records the current repository commit;
2. runs the same repeatable benchmark suite;
3. compares that run with the previous benchmark record;
4. advances the persistent filesystem crawl for a longer bounded window;
5. builds a deep diagnostic packet with process/launch-item attribution;
6. asks the local model for a self-review and next engineering ideas;
7. writes dated JSON and text handoffs under `~/.macbrain/handoff/`;
8. exposes the latest stored handoff to the authorized external controller.

The default crawl budget is 45 minutes. That limit protects the old Mac from an accidentally
unbounded filesystem pass; it is configurable independently of the benchmark definitions.

## Benchmark rule

Every performance change must be checked against repeatable measurements.

The first suite records:

- fixed CPU-workload duration;
- bounded sequential local disk write/read throughput;
- fixed local-model response latency when the inference runtime is available;
- free disk space;
- swap in use;
- current load-per-CPU as environmental context.

Each benchmark record includes the local Git commit that produced it.

Comparison states are deliberately non-celebratory:

- `baseline` — first comparable run;
- `improved` — measured changes are favorable beyond tolerance with no measured regression;
- `regressed` — measured changes are unfavorable beyond tolerance with no measured improvement;
- `mixed` — some measurements improved and others regressed;
- `stable` — no measured change exceeded the noise tolerance.

A PR is not successful merely because it merged or ran without error. A change can still be
kept as diagnostic/preparatory work if it makes the next problem more legible, but that must
be stated explicitly rather than calling it a speed improvement.

## Commands

Run only the repeatable benchmark:

```text
macbrain benchmark
```

Inspect history:

```text
macbrain benchmark-history
```

Run the entire nightly loop manually:

```text
macbrain nightly
```

Read the latest handoff:

```text
macbrain nightly-latest
```

The remote controller can retrieve the same stored handoff with the read-only `nightly`
operation.

## External engineering loop

The intended division of labor is:

```text
Mac hardware
  -> Mac Brain measurement + nightly diagnosis
  -> stored engineering handoff
  -> authorized external controller
  -> stronger external coding/reasoning agent
  -> reviewed PR
  -> approved change pushed inward
  -> next Mac Brain benchmark
  -> keep investigating until measurements support the result
```

Mac Brain does not fetch GitHub, create a cloud PR, or hold cloud credentials. The external
controller initiates every network interaction inward.
