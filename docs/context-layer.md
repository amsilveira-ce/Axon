# The context layer

A language model has no persistent memory. Every time the Principal Agent (PA)
calls the model, it must re-supply everything the model needs to know — who the
user is, what was said earlier, and which tools are available. The **context
layer** is the subsystem responsible for holding that information between calls
and assembling it into the next prompt.

Without it, every request starts from zero. With it, the PA can handle a
follow-up like *"send it to the same person as before"* and still know who
*"the same person"* is.

> **Architecture note:** The term *context layer* comes from the
> [DAWN architecture](https://arxiv.org/abs/2410.22339) that Axon is built on.
> This page documents what Axon implements today and how to work with it.

---

## How it works

When you send a query, three things happen before the model ever sees a single
token:

1. `ConversationHistory` retrieves the messages from the current session
2. `MemoryBank` retrieves any durable facts stored from past sessions
3. `PromptAssembler` combines both with the available resource list and your
   query into a single prompt

Each component has a distinct role. Together they make the PA feel stateful
even though the underlying model is not.

```
  your query
      │
      ▼
┌─────────────────────────────────────┐
│           PromptAssembler           │
│                                     │
│  ConversationHistory  MemoryBank    │
│  (this session)       (all sessions)│
│                                     │
│  Available resources                │
└──────────────────┬──────────────────┘
                   │
                   ▼
             model prompt
```

All three components live in `src/axon/pa/context/`.

---

## Component 1 — Conversation history

`ConversationHistory` is the PA's **short-term memory**: the record of
everything said in the current session.

### What it stores

Each message has three fields:

| Field | Description |
|-------|-------------|
| `role` | `user`, `assistant`, or `system` |
| `content` | the text of the message |
| `timestamp` | ISO-8601 UTC timestamp |

### Sessions

Every conversation is a *session* identified by a unique `session_id`. The
first query in a new conversation creates the session and writes it to:

```
.axon/pa/sessions/{session_id}.json
```

Passing that ID back to a future command restores the full conversation —
messages, summary, and config.

### The sliding window

Keeping every message forever would eventually overflow the model's context
window. `ConversationHistory` keeps only the most recent
`conversation.max_messages` turns (default: `10`). This is the *window*.

When the conversation grows past the window, the oldest messages are not
simply deleted — the LLM condenses them into a running `summary` that
preserves the key intents, decisions, and constraints. The summary is
never discarded, even as the window slides forward.

Here is what a session looks like on disk:

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
  "config": {
    "max_messages": 10,
    "max_tokens": null,
    "window_mode": "messages"
  },
  "created_at": "2026-05-21T17:05:02.432741Z",
  "updated_at": "2026-05-21T17:05:29.292691Z"
}
```

`summary` is empty here because this conversation has not yet grown past its
window. Once it does, the model writes a condensed summary into that field and
the oldest messages are removed from `messages`.

> **Tip:** You can inspect any session file directly to see exactly what the
> PA remembers. The file is plain JSON and human-readable.

---

## Component 2 — Memory bank

`MemoryBank` is the PA's **long-term memory**: facts and preferences that
persist across *all* conversations, not just the current one.

### What it stores

The memory bank is a flat list of key/value entries. Each entry records:

| Field | Description |
|-------|-------------|
| `key` | the name of the fact (e.g. `preferred_format`) |
| `value` | the stored value (e.g. `PDF`) |
| `source` | where it came from: `operator` or `learned` |
| `updated_at` | when it was last written |

The `source` field distinguishes between facts set deliberately by a human
(`operator`) and facts inferred automatically from past interactions
(`learned`).

Typical entries are stable user preferences and environment facts:

```
preferred_format  →  PDF
data_source       →  HStory EHR
language          →  Portuguese (Brazil)
```

### Why it matters

Memory bank entries let the PA stop asking the same questions. If
`preferred_format: PDF` is stored, the PA treats PDF as the default and
never asks *"which format?"* again — unless you ask it to change.

### Where it lives

The memory bank is stored at `.axon/pa/memory_bank.json`. A fresh workspace
starts empty:

```json
{
  "version": "0.1.0",
  "entries": []
}
```

With entries:

```json
{
  "version": "0.1.0",
  "entries": [
    {
      "key": "preferred_format",
      "value": "PDF",
      "source": "operator",
      "updated_at": "2026-05-21T17:05:14.258501Z"
    },
    {
      "key": "language",
      "value": "Portuguese (Brazil)",
      "source": "learned",
      "updated_at": "2026-05-21T17:10:03.112344Z"
    }
  ]
}
```

> **Note:** A dedicated `axon pa memory` command is planned. For now, edit
> `.axon/pa/memory_bank.json` directly. Keep the JSON valid — the PA picks
> up changes on the next start.

---

## Component 3 — Prompt assembler

`PromptAssembler` is **not** a memory. It is the component that builds the
actual context the model sees on every request.

On each call it gathers four pieces and lays them out in a fixed template:

```
--- Conversation History ---
{history}

--- User Memory ---
{memory}

--- Available Resources ---
{resources}

--- User Query ---
{query}
```

The four pieces are:

| Piece | Source |
|-------|--------|
| Conversation history | `ConversationHistory` — the messages in the current window, plus the summary if one exists |
| User memory | `MemoryBank` — all stored key/value entries |
| Available resources | the capability tags of every resource registered in the active GA context |
| User query | the new request from the user |

The model receives this assembled prompt. It never calls `ConversationHistory`
or `MemoryBank` directly — those are the PA's internal bookkeeping, invisible
to the model.

---

## The token budget

The model's context window is finite. When the assembled prompt would exceed
`conversation.max_tokens`, the assembler trims — but it does not trim at
random. It drops pieces in priority order, least important first:

```
1. Available resources    ← dropped first (can be re-fetched)
2. User memory            ← dropped next
3. Old history messages   ← summary is always kept, even as messages are removed
4. User query             ← never dropped
```

Two things are always protected: the **user query** (what you just asked) and
the **conversation summary** (the condensed history). The PA would rather
lose the list of available tools than lose the thread of the conversation.

> **Note:** If `conversation.max_tokens` is `null` (the default), no trimming
> happens — the full assembled context is always sent. Set it only if you are
> hitting model context limits or managing API costs.

---

## Component summary

| Component | Class | Scope | Stored at | Tune with |
|-----------|-------|-------|-----------|-----------|
| Conversation history | `ConversationHistory` | One session | `.axon/pa/sessions/{id}.json` | `axon pa config --conversation-max-messages` |
| Memory bank | `MemoryBank` | All sessions | `.axon/pa/memory_bank.json` | edit the file directly |
| Prompt assembler | `PromptAssembler` | Per request | in memory only | `axon pa config --conversation-max-tokens` |

---

## Tutorials

### Resume a conversation

Every run prints its `session_id`. Pass it back with `--session` to continue
where you left off:

```bash
# start a new conversation
axon pa chat
# Session: 0e2499f7-c35b-40b2-919d-5af7588b498d

# resume it later
axon pa chat --session 0e2499f7-c35b-40b2-919d-5af7588b498d
```

The full history — messages and summary — is restored exactly as it was.

---

### Tune the sliding window

The window controls how many recent messages stay in the active context.
Increase it when conversations are long and you need more history; decrease
it to reduce token usage.

```bash
# keep the last 20 turns instead of the default 10
axon pa config --conversation-max-messages 20
```

When the window is full, the oldest messages are summarized automatically.
You do not lose context — you trade detailed verbatim history for a compact
summary.

---

### Cap the token budget

If you are hitting model context limits or want to control API costs, set a
hard token cap on the assembled prompt:

```bash
# cap the assembled context at 8 000 tokens
axon pa config --conversation-max-tokens 8000
```

When the assembled prompt would exceed this limit, the assembler drops pieces
in priority order (see [The token budget](#the-token-budget) above). The user
query and conversation summary are always preserved.

> **Tip:** Start without a cap and only add one if you observe context-window
> errors or unexpectedly high token usage. The default (`null`) sends the full
> context every time.

---

### Add a persistent fact to the memory bank

To teach the PA a preference that should apply to every future conversation,
add an entry to `.axon/pa/memory_bank.json`:

```json
{
  "version": "0.1.0",
  "entries": [
    {
      "key": "preferred_format",
      "value": "PDF",
      "source": "operator",
      "updated_at": "2026-06-10T09:00:00.000000Z"
    }
  ]
}
```

The PA picks this up the next time it starts. From that point on, it treats
`PDF` as the default format without being asked.

To remove a preference, delete the entry and save the file.

---

### Inspect what the model actually saw

The `--verbose` flag on `axon pa run` and `axon pa chat` prints the fully
assembled prompt — history, memory, resources, and query — exactly as it was
sent to the model. This is the most reliable way to understand what the PA
remembered and what it did not:

```bash
axon pa run -q "and send it to the same person as before" --verbose
```

Expected output includes a block like:

```
--- Conversation History ---
[user] send an email about my party to Francisco
[assistant] goal: send an email about the party to Francisco ...

--- User Memory ---
preferred_format: PDF
language: Portuguese (Brazil)

--- Available Resources ---
resend (email): send_email, list_emails
...

--- User Query ---
and send it to the same person as before
```

If a piece you expected is missing, it was trimmed by the token budget, or
it was never stored. `--verbose` is the fastest way to diagnose both.

---

## See also

- [Architecture](architecture.md) — where the context layer sits in the full PA pipeline
- [Configuration](configuration.md#paconversation) — all `conversation.*` settings and their defaults
- [Skills](skills.md) — how the assembled context is interpreted during intent extraction
