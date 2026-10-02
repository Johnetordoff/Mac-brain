# Mac Brain agent rules

These instructions apply to every AI or automation working in this repository.

## Hard no-Node rule

Do not use, install, invoke, recommend, or add Node.js or any Node package ecosystem tool.
That includes `node`, `nodejs`, `npm`, `npx`, `yarn`, `pnpm`, Node-based CLIs,
bridges, agents, package managers, build systems, or helper services.

When an integration or development task appears to require Node, redesign it using Python
3.14 standard library, supported macOS system tools invoked from Python, or an external
non-Node controller. Do not present Node as a fallback.

Browser JavaScript is allowed only under the repository's explicit browser/web source
exception; that exception does not permit a Node runtime or package toolchain.

The rest of the repository's Python-only, containment, lifecycle, and safety policies
remain authoritative.
