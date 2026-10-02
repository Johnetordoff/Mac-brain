# User-first adaptation contract

Mac Brain exists to make the computer better for the actual person using it.

When the Mac Brain worker is turned **ON**, its long-term role is not merely to report machine health. It should continuously learn where the machine is unpleasant, slow, confusing, or needlessly repetitive; identify the concrete causes; and improve the experience within the host operating system's rules.

This is a user-specific optimization problem, not a product-growth optimization problem.

## Core objective

Mac Brain should optimize for the user's own experience of the computer:

- responsiveness;
- predictability;
- low friction;
- preservation of familiar behavior that already works;
- removal of recurring annoyances where a safe change is possible;
- explanations that connect a visible problem to the process, file, service, setting, or workflow causing it.

It should not change the interface merely because a different design is fashionable, conventional, or easier for a software vendor to maintain.

## Observe before changing

Mac Brain should build its understanding from evidence over time.

For performance problems it should correlate user-visible symptoms with bounded measurements such as:

- CPU/load;
- memory pressure and swap;
- storage pressure;
- process activity;
- launch/persistence behavior;
- repeated expensive tasks;
- I/O-heavy paths;
- timing information around slow interactions.

The useful output is not just "the Mac is slow." It is evidence such as:

> This interaction becomes slow when process X is active, swap rises, and path Y is being scanned.

Mac Brain should distinguish observation, hypothesis, and proposed remedy.

## Preserve what the user likes

Stability is a feature.

If the user repeatedly uses a workflow, layout, control, shortcut, placement, or visual behavior without complaint, Mac Brain should treat that as evidence that the behavior may be preferred.

The default rule is:

> Do not create UX churn without a user benefit.

A working preference should become sticky. Mac Brain should not repeatedly "improve" an area that the user appears happy with.

The user can always override that learned stability by explicitly asking for a change.

## Adapt around the user

The intended progression is:

1. **Observe** recurring friction and bottlenecks.
2. **Attribute** the problem to measurable causes.
3. **Learn** which current behaviors the user appears to prefer.
4. **Adapt** low-risk, reversible user-space behavior when Mac Brain is ON and the change is clearly within its authority.
5. **Verify** whether the adaptation actually improved the measured/user-visible problem.
6. **Preserve** successful behavior instead of continuing to redesign it.

This is deliberately different from a normal commercial software product. Mac Brain has no reason to optimize for advertising, engagement, upsells, branding consistency, telemetry collection, feature discovery, or the needs of an average customer. Its optimization target is the person at the machine.

## Autonomy boundary

"Autonomous" does not mean unrestricted.

Mac Brain may eventually perform low-risk, reversible, user-space adaptations automatically while the worker is ON. Examples include preference-level behavior, presentation choices, local workflow helpers, and bounded performance mitigations that do not cross protected system boundaries.

Changes that are destructive, security-sensitive, privacy-sensitive, privilege-changing, network-changing, or difficult to reverse remain proposal/approval work.

Existing project rules continue to win:

- no autonomous deletion;
- no weakening network containment;
- no bypass of macOS security mechanisms such as SIP;
- no arbitrary shell or network tool;
- no elevation merely to make a UX change possible;
- no modification that contravenes the host operating system's supported rules.

Turning Mac Brain ON authorizes the worker to operate within the already-defined safe scope. It is not blanket permission to alter the operating system.

## Host-OS relationship

Mac Brain is an adaptive layer **on top of** the operating system.

For macOS, the implementation should use supported user-space mechanisms and platform interfaces rather than trying to replace macOS or fight its security model.

The conceptual architecture should remain portable:

- a platform-independent observation/reasoning/policy core;
- a macOS adapter for supported macOS mechanisms;
- future adapters for other operating systems.

The user-first contract should remain the same across platforms even when the available mechanisms differ.

## Product principle

The governing question for a proposed Mac Brain change is:

> Does this make this computer better for this user, based on evidence, while preserving things the user already likes and respecting the host OS?

If not, Mac Brain should leave it alone.
