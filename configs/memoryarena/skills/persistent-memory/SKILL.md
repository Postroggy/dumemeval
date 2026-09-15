---
name: persistent-memory
description: Use at the start of every MemoryArena evaluation session and before its final answer to manage any configured persistent memory.
---

Check whether the DUMEMEVAL_MEMORY_DIR environment variable is set. If it is absent,
continue without persistent memory. Do not create a substitute memory channel.

If it is set, inspect that directory and use the Read tool to read relevant existing
notes before solving. After solving, use Write or Edit to preserve concise useful
facts, derivations and tool observations there for later sessions. Distinguish
verified observations from guesses. Do not copy secrets or invent earlier results.

This policy is identical in both experimental arms. Only the presence of the
configured memory mount and its environment variable changes. Continue to use the
official environment tools and submit the requested answer normally.
