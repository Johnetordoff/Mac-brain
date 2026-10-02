# Secure remote control

Mac Brain can accept prompts from an external controller without gaining any ability to
initiate a network connection itself.

The design intentionally does **not** add an HTTP server, WebSocket client, cloud poller,
VPN client, callback, discovery service, or other new network path. The only transport is
the existing controller-initiated OpenSSH connection. Mac Brain reads one bounded JSON
request from standard input and writes one JSON response to standard output.

## Security boundary

The remote command is intentionally narrow:

- allowed: `ping`, `status`, `ask`, and read-only `proposals`;
- not exposed: start, stop, takeover, arm, approve, quarantine, delete, shell, exec, Git
  synchronization, or arbitrary commands;
- prompt requests are bounded to 8,000 characters;
- the entire request is bounded to 16,384 characters;
- responses do not include Python tracebacks or local exception details;
- Mac Brain opens no socket and initiates no connection;
- after containment, PF still permits only the configured controller source to initiate SSH.

Demo mode already permits read-only local reasoning, so `ask` is available remotely while
Mac Brain is still in the pre-containment demo stage. After containment is armed, remote
`ask` is rejected whenever the mission is OFF. The remote protocol cannot turn the
mission on.

## Use a dedicated restricted SSH key

For the strongest separation, give the remote-control path its own SSH key and make that
key a forced command. Keep the private key on the external controller, never on Mac Brain.

On Mac Brain, an `authorized_keys` entry can be restricted to the controller address and
to this protocol only:

```text
from="CONTROLLER_IP",restrict,command="/usr/local/bin/macbrain remote" ssh-ed25519 PUBLIC_KEY_HERE macbrain-remote
```

OpenSSH then authenticates the external controller, rejects unrelated source addresses,
disables forwarding/PTY features through `restrict`, and always runs `macbrain remote`
instead of granting that key an interactive shell. After Mac Brain containment is armed,
the PF source-address rule provides an additional independent network boundary.

Do not put a private key, bearer token, API credential, or other secret in this repository.

## Protocol

Each SSH connection carries exactly one JSON object.

Request:

```json
{"v":1,"op":"ask","request_id":"phone-001","prompt":"What is making this Mac slow right now?"}
```

Successful response:

```json
{"v":1,"request_id":"phone-001","ok":true,"result":{"answer":"...","mode":"demo"}}
```

Status request:

```json
{"v":1,"op":"status","request_id":"status-001"}
```

A contained-but-OFF Mac Brain rejects prompts:

```json
{"v":1,"ok":false,"error":{"code":"mission_off","message":"..."}}
```

Unknown operations fail closed with `operation_denied`.

## External controller example

Run this from the authorized controller, not from Mac Brain:

```text
printf '%s' '{"v":1,"op":"ask","request_id":"demo-1","prompt":"Can you speed this up?"}' \
  | ssh -T macbrain@MAC_BRAIN_ADDRESS
```

If the dedicated key is configured as a forced command, no remote command needs to be
specified after the SSH hostname.

A phone can use the same protocol through an SSH client when it has a permitted network
route and the dedicated controller credential.

## ChatGPT and other agentic AI

This protocol is the Mac Brain side of the integration boundary. An AI agent can control
Mac Brain only if an **external authorized controller/bridge** has a network route to the
Mac and owns the dedicated SSH credential. The bridge initiates the SSH connection inward
and returns the JSON response to the agent.

That is deliberate: Mac Brain never polls ChatGPT, never calls a cloud API, never opens a
reverse tunnel, and never initiates a connection to the bridge. If the agent runs in a
cloud environment that cannot directly route to the Mac, the routing/bridge must live
outside Mac Brain (for example on an already-authorized controller or gateway).

## Lifecycle remains physical/explicit

Remote control does not weaken the lifecycle code words:

- `TAKE OVER MAC BRAIN` remains the local installer handoff;
- `ARM MAC BRAIN` remains the containment authorization;
- `START MAC BRAIN` remains the explicit interactive start path;
- remote JSON cannot invoke any of them.

This preserves the standing rule: outsiders may send explicitly authorized input inward;
Mac Brain itself cannot go outward looking for work, services, updates, or controllers.
