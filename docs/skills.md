# Skills and Domains

Every request the Principal Agent (PA) receives passes through **intent extraction** — the step that turns a natural-language sentence like *"summarize the Q3 sales report"* into a structured objective the rest of the system can act on.

**Skills** are how you control that step. A skill is a plain Markdown file of instructions for the intent extractor. Editing a skill changes how the PA interprets requests — no code changes, no redeploy required.

This guide explains what skills are, how they compose, and how to create and manage them. For the complete command reference, see [`axon pa skills`](cli.md#axon-pa-skills).

---

## Overview

The intent extractor is powered by a language model. Rather than hard-coding behavior in Python — where every change requires a code commit — Axon stores the extractor's instructions in editable Markdown files called **skills**.

This design gives you full control over how the PA behaves without touching application code. You can:

- Make the PA stricter about asking clarifying questions before acting.
- Teach it the vocabulary and data sources specific to your field.
- Add compliance rules that require human confirmation before certain actions.

---

## Core concepts

### The two kinds of skill

Axon uses two kinds of skill that layer on top of each other.

**Base skill** (`intent_extraction.md`) defines the PA's general behavior: how it reasons about a request, what it must verify before acting, and when it should pause and ask a clarifying question rather than guess. There is exactly one base skill, and it is always active.

**Domain skills** (`domains/<name>.md`) add rules specific to a field of work — for example `clinical`, `finance`, or `legal`. A domain skill layers on top of the base skill: the PA reads the base behavior first, then the domain rules. Only one domain can be active at a time, and domains are entirely optional. With no domain active, the PA runs on the base skill alone.

### How skills compose

```text
            ┌─────────────────────┐
request ──► │  base skill         │  general behavior (always active)
            ├─────────────────────┤
            │  domain skill       │  field-specific rules (optional)
            ├─────────────────────┤
            │  output contract    │  fixed structure — enforced by Axon
            └─────────────────────┘
                       │
                       ▼
              structured objective
```

The **output contract** at the bottom is the precise JSON shape that Axon's parser reads from the extractor's response. It is fixed and enforced by Axon — it is not part of what you customize.

### What domain skills are good for

Domain skills are well-suited to three categories of rules:

- **Available data sources** — what the system can fetch on its own, so the PA does not prompt the user for information it can retrieve automatically (e.g., *"patient records are available via `health_search`"*).
- **Required inputs** — what must always come from the user and can never be assumed (e.g., *"always confirm the patient name before executing"*).
- **Compliance rules** — actions that require explicit human confirmation before the PA proceeds (e.g., *"prescription changes require clarification before proceeding"*).

---

## File layout

Skill files are part of the Axon package source. All `axon pa skills` commands expect to be run from your project root.

```text
src/axon/pa/skills/
├── intent_extraction.md     # base skill — always active
└── domains/
    ├── clinical.md          # example domain skill
    └── finance.md           # example domain skill
```

> **Note:** Run `axon pa skills` commands from your project root. The CLI resolves skill paths relative to the package source from that location.

---

## The output contract

Every skill, regardless of its content, must produce output in a fixed structure called the **output contract**. This contract is the JSON schema that Axon's parser reads after each extraction. It is enforced by Axon and is not something you should modify.

When customizing a skill, change the *behavior* sections freely — but leave the contract section untouched. If the contract is altered, the PA's output will fail to parse.

Two commands help you stay safe:

| Command | Purpose |
|---|---|
| `axon pa skills validate` | Checks that the output contract is still intact. |
| `axon pa skills reset --contract-only` | Restores the output contract while preserving your behavior edits. |

> **Warning:** If you edit a skill and the PA starts producing unexpected output or errors, run `axon pa skills validate` first. A broken output contract is the most common cause.

---

## How-to guides

### List all skills

To see what skills exist, which domain is currently active, and whether the output contract is intact, run:

```bash
axon pa skills list
```

Example output:

```
base skill       intent_extraction.md   contract: ok
domain (active)  domains/finance.md     contract: ok
domain           domains/clinical.md    contract: ok
```

### Inspect a skill's content

To read the base skill:

```bash
axon pa skills show
```

To read a specific domain skill:

```bash
axon pa skills show --domain clinical
```

### Create a new domain skill

To scaffold a new domain skill, run:

```bash
axon pa skills new --domain finance
```

This creates `src/axon/pa/skills/domains/finance.md` from a template. The template includes commented sections for data sources, required inputs, and compliance rules. Open the file in your editor and replace the placeholder comments with your rules.

> **Tip:** The template comments are guides for what each section expects. Read them before filling in the file — they clarify what the intent extractor will do with each type of rule.

### Activate a domain skill

Creating a domain file does not activate it automatically. Activation is a separate configuration step:

```bash
axon pa config --domain finance
```

The change takes effect on the next `axon pa run` or `axon pa chat` invocation — no restart is needed for already-running sessions.

To deactivate all domains and return to the base skill only:

```bash
axon pa config --domain none
```

> **Note:** Only one domain can be active at a time. Activating a new domain automatically deactivates the previous one.

### Customize the base skill

Open `src/axon/pa/skills/intent_extraction.md` in your editor and adjust the behavior sections — how strict the PA is, what it checks for, what vocabulary it recognizes. Do not modify the output contract section.

After editing, validate your changes:

```bash
axon pa skills validate
```

If validation passes, your changes are ready. If you need to restore a clean baseline:

```bash
axon pa skills reset                  # restore the entire base skill to defaults
axon pa skills reset --contract-only  # restore only the output contract
```

> **Warning:** `axon pa skills reset` without `--contract-only` overwrites all your behavior edits. Use `--contract-only` if you only need to fix a broken contract while keeping your customizations.

---

## End-to-end example: adding a finance domain

This walkthrough shows the full lifecycle of creating a domain skill for a financial analysis workflow, activating it, and confirming that it shapes the PA's behavior as expected.

**Step 1: Scaffold the domain**

```bash
axon pa skills new --domain finance
```

This creates the file `src/axon/pa/skills/domains/finance.md`. You should see:

```
Created: src/axon/pa/skills/domains/finance.md
```

**Step 2: Edit the domain file**

Open the file in your editor. Fill in the three template sections:

- Under *Available data sources*, add the tools the system can call on its own — for example, a `ledger_search` tool that retrieves GL entries without prompting the user.
- Under *Required inputs*, list what must always come from the user — for example, the fiscal period must always be confirmed before any reconciliation runs.
- Under *Compliance rules*, add any approval gates — for example, journal entries above a threshold require a second confirmation.

**Step 3: Validate the skill**

Before activating, verify that your edits left the output contract intact:

```bash
axon pa skills validate
```

Expected output:

```
base skill:    contract ok
domain finance: contract ok
```

**Step 4: Activate the domain**

```bash
axon pa config --domain finance
```

**Step 5: Confirm the active state**

```bash
axon pa skills list
```

The `finance` domain should now appear as `(active)`.

**Step 6: Test with a real request**

```bash
axon pa run -q "reconcile the Q3 ledger" -v
```

The `-v` flag prints the full extraction context, including which skills were loaded and how the request was parsed into a structured objective. This is the fastest way to verify that your domain rules had the intended effect.

---

## See also

- [`axon pa skills`](cli.md#axon-pa-skills) — full command reference for all skill subcommands
- [Configuration](configuration.md#paintent_extractor) — the `intent_extractor.domain` setting and other PA configuration options
- [Architecture](architecture.md) — where intent extraction fits in the overall pipeline
