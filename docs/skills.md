# Skills and domains

Before the Principal Agent can do anything with a request, it has to
understand it. That first step is called **intent extraction**: turning a
sentence like *"summarize the Q3 sales report"* into a structured objective
the rest of the system can act on.

**Skills** are how you steer that step. A skill is a plain Markdown file of
instructions for the intent extractor. Editing a skill changes how the PA
interprets requests — no code, no redeploy.

This page explains the two kinds of skill and how to work with them. For the
exact command syntax, see [`axon pa skills`](cli.md#axon-pa-skills).

## Why skills exist

The intent extractor is driven by a language model, and a language model does
what its instructions tell it to. Hard-coding those instructions in Python
would mean every behavior change is a code change.

Instead, Axon keeps the instructions in editable Markdown files. You can make
the PA stricter about asking clarifying questions, teach it the vocabulary of
your field, or add safety rules — all by editing text.

## The two kinds of skill

### Base skill — always active

The **base skill** (`intent_extraction.md`) defines the PA's general
behavior: how it reasons about a request, what it must check before acting,
and when it should stop and ask a clarifying question instead of guessing.

There is exactly one base skill, and it is always in effect.

### Domain skills — optional, layered on top

A **domain skill** (`domains/<name>.md`) adds rules specific to a field of
work — for example clinical, finance, or legal. A domain skill is *layered on
top of* the base skill: the PA reads the base behavior first, then the domain
rules.

Only one domain can be active at a time, and domains are optional. With no
domain active, the PA runs on the base skill alone.

```text
            ┌─────────────────────┐
request ──► │  base skill         │  general behavior (always)
            ├─────────────────────┤
            │  domain skill       │  field-specific rules (optional)
            ├─────────────────────┤
            │  output contract    │  fixed — enforced by Axon
            └─────────────────────┘
                       │
                       ▼
              structured objective
```

A domain skill is good for things like:

- **Available data sources** — what the system can fetch on its own, so the PA
  does not ask the user for it ("patient records are available via
  `health_search`").
- **Required inputs** — what must always come from the user ("always confirm
  the patient name before executing").
- **Compliance rules** — actions that need human confirmation first
  ("prescription changes require clarification before proceeding").

## Where skill files live

Skill files are part of the Axon package source:

```text
src/axon/pa/skills/
├── intent_extraction.md     # the base skill
└── domains/
    ├── clinical.md          # a domain skill
    └── finance.md           # another domain skill
```

Run `axon pa skills` commands from your project root so they can find this
directory.

## The output contract

Every skill produces output in a fixed structure — the **output contract**.
It is the precise JSON shape that Axon's parser reads back. The contract is
enforced by Axon and is **not** something you should edit.

This matters when you customize a skill: change the *behavior* freely, but
leave the contract alone. If the contract is altered, the PA's output can no
longer be parsed.

Two commands keep you safe:

- `axon pa skills validate` — checks that the output contract is intact.
- `axon pa skills reset --contract-only` — repairs the contract while keeping
  your behavior edits.

## Common tasks

### See what skills exist

```bash
axon pa skills list
```

This shows the base skill, every domain, which domain is currently active, and
whether the output contract is intact.

### Read a skill

```bash
axon pa skills show                 # the base skill
axon pa skills show --domain clinical
```

### Create a domain

```bash
axon pa skills new --domain finance
```

This creates `src/axon/pa/skills/domains/finance.md` from a template with
sections for data sources, required inputs, and compliance rules. Open the
file in your editor and fill it in — the template comments explain what each
section is for.

### Activate a domain

Creating a domain file does not activate it. Activation is a configuration
change:

```bash
axon pa config --domain finance
```

To go back to the base skill only:

```bash
axon pa config --domain none
```

Changing the active domain takes effect on the next `axon pa run` or
`axon pa chat`.

### Customize the base skill

Edit `src/axon/pa/skills/intent_extraction.md` directly. Adjust the behavior —
how strict it is, what it checks for — but do not touch the output contract.
After editing, run:

```bash
axon pa skills validate
```

If you ever want a clean slate:

```bash
axon pa skills reset                  # restore the whole base skill
axon pa skills reset --contract-only  # restore only the output contract
```

## A typical workflow

```bash
# 1. create a domain for your field
axon pa skills new --domain finance

# 2. edit the file — add data sources, required inputs, compliance rules
#    (src/axon/pa/skills/domains/finance.md)

# 3. activate it
axon pa config --domain finance

# 4. confirm it is active
axon pa skills list

# 5. try a request and inspect how it was interpreted
axon pa run -q "reconcile the Q3 ledger" -v
```

The `-v` (verbose) flag prints the context and extraction details, which is
the fastest way to see whether your skill edits had the intended effect.

## See also

- [`axon pa skills`](cli.md#axon-pa-skills) — full command reference
- [Configuration](configuration.md#paintent_extractor) — the `intent_extractor.domain` setting
- [Architecture](architecture.md) — where intent extraction sits in the pipeline
