# Mac Brain as a passive Git vault

Mac Brain is **not** the smart Git computer. It is old, slow, memory-constrained, and short on storage. Treat it as a passive vault that can hold a small, deliberately selected set of Git repositories for the other brains.

Anything complicated happens somewhere else. Another computer or AI prepares the repository, commit, brain capsule, manifest, or patch. Mac Brain's job is closer to copying and pasting bytes than understanding them.

The local Qwen model is **not part of the Git path**. It does not decide what to fetch, merge, retain, compress, clean up, or synchronize.

## Non-negotiable network boundary

After containment:

- Mac Brain initiates **no Internet connection**.
- Mac Brain initiates **no connection to another LAN computer**.
- It does not fetch or pull from GitHub, another Git server, another brain, a URL, an SSH host, or a LAN share.
- The existing PF policy still admits SSH only when the explicitly authorized controller initiates the connection to Mac Brain.
- Reply packets belonging to that inbound connection are allowed because TCP requires them.
- Git traffic uses that already-authorized inbound SSH path. No Git daemon, HTTP server, web UI, discovery service, or synchronization daemon is opened.
- If John wants to interact with Mac Brain without the inbound controller connection, he can use the physical Mac directly.

This feature must never become a workaround around containment. "Another brain should be copied to Mac Brain" means that another machine pushes or copies the prepared data **into** Mac Brain; it never means Mac Brain reaches out and retrieves it.

## Storage assumptions

Storage is scarce. Mac Brain is not an archival server and should not accumulate every historical brain capsule.

The first implementation therefore uses conservative deterministic guards:

- repositories are bare Git repositories under `~/.macbrain/git/`;
- a filesystem reserve is protected: at least **1 GiB free**, or **10% of the filesystem**, whichever is larger;
- a new receive is capped at **256 MiB**;
- automatic `git gc` and receive-time auto-GC are disabled so an inbound push cannot unexpectedly trigger an expensive repack on this slow Mac;
- `macbrain git list` returns repository names only and does not walk histories or recursively calculate sizes;
- repository inspection happens only when `macbrain git info NAME` is explicitly requested;
- Mac Brain never automatically deletes an old brain or repository to make room.

The numerical limits are intentionally conservative starting points. They can be changed deliberately at the physical machine later if real brain-capsule sizes show that another value is appropriate. They are not something the model may adjust on its own.

## Commands

Check whether the vault has room before sending anything:

```bash
macbrain git capacity
```

Create an empty receiving repository:

```bash
macbrain git create brain-clone0
```

Cheaply list repository names:

```bash
macbrain git list
```

Explicitly inspect one repository:

```bash
macbrain git info brain-clone0
```

There is deliberately no "fetch", "pull remote", "sync peers", or network-import command.

## Sending a brain inward

The controller prepares the data. Then, with `MAC_BRAIN_LAN_IP` and the Mac username substituted:

```bash
git remote add macbrain USER@MAC_BRAIN_LAN_IP:.macbrain/git/brain-clone0.git
git push macbrain main
```

Tags or additional branches should be sent only when they are actually wanted. Do **not** reflexively mirror every branch, tag, generated capsule, or old checkpoint to this storage-constrained machine.

For a `.brain` payload, the intended pattern is similarly selective: another machine decides which prepared checkpoint Mac Brain should have, then sends that checkpoint inward. Mac Brain stores what it was handed; it does not decide whether a better or newer brain exists somewhere else.

To read it back later, the controller initiates the connection again:

```bash
git clone USER@MAC_BRAIN_LAN_IP:.macbrain/git/brain-clone0.git
```

Mac Brain never initiates either operation.

## Other brain computers

Under the current containment design, other brain computers do not talk directly to Mac Brain unless one of them is explicitly chosen as the authorized controller. A controller can receive material from those machines by whatever policy applies to them, prepare it, and then push the selected result inward to Mac Brain.

Do not widen Mac Brain's firewall to the whole subnet merely for convenience. If direct inbound access from more than one machine is ever required, that should be a separate explicit security change using a small exact allowlist. Even then, Mac Brain still initiates nothing.

## Large `.brain` files

Frequently changing compressed or encrypted `.brain` files can be a poor fit for deep Git history because a small logical change may produce a largely different binary blob. On this Mac, that matters.

The practical assumption is:

- keep code, manifests, instructions, and compact history in Git;
- send only deliberately selected `.brain` checkpoints to Mac Brain;
- do not make Mac Brain the permanent archive of every generated capsule;
- do not make Mac Brain compute deltas, deduplicate a giant archive, or reason about which generations matter;
- if long-term capsule retention is needed, design that storage somewhere with more space and give Mac Brain only the subset it actually needs.

Mac Brain is the small passive copy, not the place where the hard storage problem is solved.
