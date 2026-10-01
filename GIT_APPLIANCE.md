# Mac Brain as the LAN Git appliance

Mac Brain can act as the canonical Git storage unit for brain repositories without depending on GitHub after containment.

The design intentionally preserves Mac Brain's existing network boundary:

- Mac Brain does not initiate IP connections.
- The existing PF policy still admits SSH only from the one explicitly authorized controller computer.
- Git traffic rides over that already-authorized SSH session; no new Git daemon or HTTP listener is opened.
- Repository storage is local under `~/.macbrain/git/`.
- `macbrain git import-local` rejects URL and SCP-style network sources so it cannot be used to bypass containment.

## Repository commands

Create an empty canonical repository:

```bash
macbrain git create brain-clone0
```

List Mac Brain's repositories:

```bash
macbrain git list
```

Inspect one repository:

```bash
macbrain git info brain-clone0
```

Import/mirror a repository that is already physically present on Mac Brain:

```bash
macbrain git import-local brain-clone0 /path/to/local/brain-clone0
```

Network sources are deliberately invalid for `import-local`.

## Using a repository from the authorized controller

With `MAC_BRAIN_LAN_IP` and the normal Mac username substituted:

```bash
git clone USER@MAC_BRAIN_LAN_IP:.macbrain/git/brain-clone0.git
```

Or make Mac Brain an additional remote for an existing checkout:

```bash
git remote add macbrain USER@MAC_BRAIN_LAN_IP:.macbrain/git/brain-clone0.git
git push macbrain --all
git push macbrain --tags
```

All connection initiation comes from the authorized controller. Mac Brain merely services the SSH/Git request and returns packets belonging to that connection.

## What this means for the other brains

Mac Brain can be the canonical repository holder even when the working copies live elsewhere. Under the current one-controller security model, the controller is the gateway: it can pull a canonical brain from Mac Brain and copy/deploy it to another computer, or collect changes from another computer and push them back to Mac Brain.

Direct Git access from several peer computers would require changing the current "one exact controller IP" containment rule. That should be a separate explicit change, ideally to a small allowlist of exact LAN peer addresses rather than opening SSH to the entire subnet.

Mac Brain itself still does not need outbound access in either model.

## UI direction

The first UI is deliberately the `macbrain git` terminal interface. This keeps the old 2014 Mac lightweight and adds no listening service beyond SSH.

If a richer browser UI is later useful, run it bound to loopback only and reach it with an SSH tunnel from the authorized controller. Do not bind a Git web UI directly to the LAN while the current containment model is in force.

## Large `.brain` capsules

Git is excellent for code, manifests, prompts, configuration, and ordinary text history. Frequently changing compressed or encrypted `.brain` blobs are different: small logical changes can produce a nearly completely different binary file, so Git may retain substantial data for every version.

Before Mac Brain becomes the long-term archive for many large brain-capsule generations, add an explicit storage policy such as:

- keep Git metadata/manifests indefinitely;
- store large capsule objects by SHA-256 outside the normal Git object history;
- keep only selected checkpoint generations locally; and
- never delete a capsule automatically merely to reclaim space.

That storage policy should retain Mac Brain's existing rule that destructive cleanup requires explicit human approval.
