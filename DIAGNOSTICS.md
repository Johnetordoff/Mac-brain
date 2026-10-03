# Mac Brain Performance Diagnostics

Mac Brain's diagnostic job is to answer a concrete question from local evidence:

> What is making this Mac slow, and what evidence should an external engineer act on?

The diagnostic layer is intentionally separate from cleanup or process control. It measures,
remembers, attributes, and produces engineering requests. It does not decide that a process
or file is unnecessary merely because it is expensive.

## Evidence loop

1. Sample load, disk, swap, memory, thermal/power state, and top processes.
2. Accumulate per-command CPU/RAM history so recurring offenders can be distinguished from
   one-time spikes.
3. Continue the persistent filesystem inventory and retain file sizes/classifications.
4. Detect evidence-backed bottlenecks such as sustained CPU pressure, memory/swap pressure,
   disk pressure, recurring high-resource processes, and ReportCrash/crash-loop signals.
5. Optionally perform deeper attribution to launch items/listeners.
6. Emit a deterministic engineering packet for a human or external coding agent.
7. After a code/configuration change is pushed inward, repeat diagnostics and compare the
   measurements rather than assuming the change helped.

## Commands

Human-readable diagnosis:

```text
macbrain diagnose
```

Include launch-item/listener attribution:

```text
macbrain diagnose --deep
```

Machine-readable handoff for an external engineer/agent:

```text
macbrain diagnose --json
```

Persistent process history:

```text
macbrain process-inventory
```

Record a human necessity judgment without stopping anything:

```text
macbrain classify-process "/path/to/executable" probably_unnecessary --evidence "Not needed for the dedicated MacBrain role"
```

The remote SSH protocol also exposes the read-only `diagnostics` operation so an authorized
external controller can retrieve the packet directly.

## Safety boundary

Diagnostics never delete files, terminate processes, disable services, alter networking,
or approve a destructive action. Those remain separate explicit operations. MacBrain's
job is to make the machine's bottlenecks legible enough that the next engineering change can
be precise and measurable.
