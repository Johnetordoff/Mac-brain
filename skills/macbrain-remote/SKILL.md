# Mac Brain remote agent skill

Use this skill only from an **authorized external controller** that can initiate SSH to
Mac Brain. Never run the controller-side SSH client from Mac Brain itself.

## Goal

Talk to Mac Brain synchronously: send exactly one request, wait for Mac Brain to finish
local reasoning, receive exactly one JSON response, then continue the agent workflow.

## Required behavior

1. Use the dedicated restricted SSH identity configured for Mac Brain remote control.
2. Send one protocol request at a time.
3. Wait for the SSH process to exit and parse the JSON response before issuing another
   prompt. Do not use fire-and-forget behavior.
4. Preserve and log the request_id when coordinating multi-step work.
5. Treat a timeout or broken SSH session as **unknown completion state**. Do not silently
   retry an `ask` request as if the first attempt definitely failed.
6. Treat `ok:false` as a Mac Brain response, not as a transport failure.
7. Never attempt lifecycle/destructive operations through this interface. Remote control
   is limited to `ping`, `status`, `proposals`, and `ask`.
8. Do not weaken Mac Brain's network boundary, open a reverse tunnel, or add an outbound
   callback in order to make the skill work.
9. Do not use or recommend Node.js, npm, npx, yarn, pnpm, or any Node-based bridge. Use Python or non-Node infrastructure only.

## Preferred client

From the external controller, use:

```text
python3 controller/macbrain_remote.py \
  --host MAC_BRAIN_ADDRESS \
  --user MAC_USER \
  --identity ~/.ssh/macbrain_remote \
  ask "YOUR PROMPT"
```

The client blocks until Mac Brain replies or the timeout is reached.

For machine-to-machine use, consume its JSON output. A successful answer has the form:

```json
{
  "v": 1,
  "request_id": "...",
  "ok": true,
  "result": {
    "answer": "...",
    "mode": "demo"
  }
}
```

## Conversation loop

For each user turn that should be delegated to Mac Brain:

1. formulate one concise prompt;
2. invoke the controller client synchronously;
3. wait for Mac Brain's response;
4. return or summarize the answer;
5. only then decide whether another Mac Brain request is needed.

Do not send multiple concurrent prompts to the old Mac. Its local model is intentionally
small and slow, and the protocol is designed for serialized interaction.

## ChatGPT/mobile note

This skill defines **how an agent must talk to Mac Brain once the agent has an authorized
controller path**. A ChatGPT/mobile client that cannot itself route to the Mac's SSH
listener still needs an external controller/connector that can. That controller initiates
the SSH connection inward; Mac Brain never initiates a connection to ChatGPT or the cloud.
