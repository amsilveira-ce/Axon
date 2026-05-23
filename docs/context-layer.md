# The context layer

A language model has no memory of its own. Every time the Principal Agent
calls the model, it has to *re-supply* everything the model should know — who
the user is, what was said earlier, what tools are available. The **context
layer** is the part of the PA that holds that information between calls and
assembles it into the prompt.

Without it, every request would start from zero. With it, the PA can say
*"the report we discussed"* and still know which report you mean.

> The term *context layer* comes from the [DAWN architecture](https://arxiv.org/abs/2410.22339)
> that Axon is built on. This page documents what Axon implements today.

## The two memories of the Principal Agent

The PA keeps two distinct kinds of memory. They differ in **scope** (one
conversation vs. all conversations) and in **lifetime** (how long they last).

| | Conversation history | Memory bank |
|---|---|---|
| Holds | the running dialogue | durable facts and preferences |
| Scope | one session | all sessions |
| Lifetime | the life of that session | indefinite |
| Analogy | short-term memory | long-term memory |

A third component, the **prompt assembler**, is not a memory — it is the part
that pulls both memories together into the final prompt. All three live in
`src/axon/pa/context/`.

### Conversation history

`ConversationHistory` is the PA's short-term memory: the record of one
back-and-forth conversation between you and the agent.

**What it holds.** An ordered list of messages, each with a `role`
(`user`, `assistant`, or `system`), the `content`, and a `timestamp`.

**Sessions.** Each conversation is a *session* with a unique `session_id`. A
session is created the first time you run a query and is saved to disk at
`.axon/pa/sessions/{session_id}.json`. Resuming that ID later restores the
whole conversation.

**The sliding window.** Keeping every message forever would eventually
overflow the model's context. So the history keeps only the most recent
`conversation.max_messages` turns (default: `10`). This is the *window*.

**Summarization.** When a conversation grows past the window, the oldest
messages do not just disappear — they are condensed by the LLM into a running
`summary` field that preserves the key intents, constraints, and decisions.
The window stays small, but nothing important is lost. The summary itself is
never discarded.

On disk, a session looks like this:

```json
{
  "session_id": "0e2499f7-c35b-40b2-919d-5af7588b498d",
  "messages": [
    {
      "role": "user",
      "content": "send an email about my party to Francisco",
      "timestamp": "2026-05-21T17:05:14.258501Z"
    },
    {
      "role": "assistant",
      "content": "goal: send an email about the party to Francisco ...",
      "timestamp": "2026-05-21T17:05:29.292674Z"
    }
  ],
  "summary": "",
  "config": { "max_messages": 10, "max_tokens": null, "window_mode": "messages" },
  "created_at": "2026-05-21T17:05:02.432741Z",
  "updated_at": "2026-05-21T17:05:29.292691Z"
}
```

`summary` is empty here because this conversation has not yet outgrown its
window.

### Memory bank

`MemoryBank` is the PA's long-term memory: facts that should hold across
*every* conversation, not just the current one.

**What it holds.** A flat list of key/value entries. Each entry has a `key`, a
`value`, a `source`, and an `updated_at` timestamp. The `source` records where
the entry came from:

- `operator` — set deliberately by a human
- `learned` — inferred by the system from past interactions

Typical entries are stable preferences and environment facts:

```text
preferred_format: PDF
data_source:      HStory EHR
language:         Portuguese (Brazil)
```

**Why it matters.** Memory bank entries let the PA stop asking the same
questions. If `preferred_format: PDF` is stored, the PA does not need to ask
*"which format?"* every time — it treats PDF as the default.

It is stored at `.axon/pa/memory_bank.json`. A fresh workspace starts empty:

```json
{
  "version": "0.1.0",
  "entries": []
}
```

With entries, each one is a full record:

```json
{
  "version": "0.1.0",
  "entries": [
    {
      "key": "preferred_format",
      "value": "PDF",
      "source": "operator",
      "updated_at": "2026-05-21T17:05:14.258501Z"
    }
  ]
}
```

### Prompt assembler

`PromptAssembler` is not a memory — it is the component that builds the actual
context the model sees. On every request it gathers four pieces:

1. **Conversation history** — from `ConversationHistory`
2. **User memory** — from `MemoryBank`
3. **Available resources** — the capability tags of the registered tools
4. **The user query** — the new request itself

and lays them out in a fixed template:

```text
--- Conversation History ---
{history}

--- User Memory ---
{memory}

--- Available Resources ---
{resources}

--- User Query ---
{query}
```

## The token budget

The model's context window is finite, so the assembler works within a **token
budget** (`conversation.max_tokens`). When the assembled context would be too
large, it trims — but not at random. It drops the least important pieces
first:

```text
1. Available resources   ← dropped first
2. User memory
3. Old history messages  ← summary is always kept
4. User query            ← never dropped
```

Two things are protected: the **user query** (the request itself) and the
**conversation summary** (the condensed past). The PA would rather forget
which tools exist than forget what you just asked.

If `conversation.max_tokens` is `null` (the default), no trimming happens —
the full context is always sent.

## Component summary

| Component | Class | Scope | Stored at | Tune with |
|---|---|---|---|---|
| Conversation history | `ConversationHistory` | One session | `.axon/pa/sessions/{id}.json` | `axon pa config --conversation-max-messages` |
| Memory bank | `MemoryBank` | All sessions | `.axon/pa/memory_bank.json` | edit the file (see below) |
| Prompt assembler | `PromptAssembler` | Per request | — (in memory) | `axon pa config --conversation-max-tokens` |

## Working with the context layer

### Resume a conversation

Every run prints its `session_id`. Pass it back to continue where you left
off — the history, including any summary, is restored:

```bash
axon pa chat --session 0e2499f7-c35b-40b2-919d-5af7588b498d
```

### Tune the window and budget

```bash
# keep more turns in the active window
axon pa config --conversation-max-messages 20

# cap the assembled context at 8000 tokens
axon pa config --conversation-max-tokens 8000
```

See [Configuration](configuration.md#paconversation) for every conversation
setting.

### Edit the memory bank

The memory bank is currently managed by editing `.axon/pa/memory_bank.json`
directly. Add an entry, keep the JSON valid, and the PA picks it up the next
time it starts. (A dedicated `axon pa memory` command is planned.)

### Inspect what the model actually saw

The `--verbose` flag on `axon pa run` and `axon pa chat` prints the fully
assembled context — history, memory, and resources — exactly as it was sent to
the model. This is the most reliable way to see what the PA remembered:

```bash
axon pa run -q "and send it to the same person as before" -v
```

## See also

- [Architecture](architecture.md) — where the context layer sits in the pipeline
- [Configuration](configuration.md#paconversation) — the `conversation` settings
- [Skills](skills.md) — how the assembled context is interpreted during intent extraction
