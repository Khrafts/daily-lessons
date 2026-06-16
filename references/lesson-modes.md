# Lesson modes — the tone & depth contract

A Daily Lesson always teaches **one** concept, grounded in your real session,
pitched at your real stack, in the **same six sections** (01 What it is · 02 Why
it mattered today · 03 The mental model · 04 A worked example · 05 Pitfalls · 06
Go deeper) followed by the self-check. The **structure, the renderer, and the
frozen HTML never change** with the mode — only the *voice, the depth of
exposure, and how the session is used* change.

This file is canon, exactly like `lesson-format.md`. `/daily-lesson` reads it at
write-time to pick a voice; `/lesson-mode` reads it to show you the menu. To
change what a mode means, edit this file — don't improvise per run.

There are **four modes** along a single axis — *how much the lesson leans on
your session as narrative material* — with depth riding along it:

```
Tutorial ──────── Grounded ──────── Deep Dive        Briefing
(session is the   (session cited    (session is one   (session is a
 silent reason)    as evidence)      data point)       terse fact)
 concept-first     the DEFAULT       max rigor/length  max density
```

---

## Two floors that bind EVERY mode (non-negotiable)

These are not modes and no tone may break them. They exist because the two ways
a lesson goes wrong — *obscure* and *void* — are failures of the floor, not of
voice.

### 1. The clarity floor — a tone may never make a lesson obscure

1. **Define first.** Section 01 opens with a one-sentence, plain-language
   definition of the concept — including its own name/acronym — *before* any
   story, analogy, or flourish. Every term, symbol, acronym, and magic constant
   is defined or shown in plain words on first use. No term is left to context.
2. **One idea per sentence.** Plain declaratives are the spine. Sentences are
   concrete and finishable in one breath — no clause-stacking to sound clever,
   no sentence whose only job is mood.
3. **Lead with the point.** Each of the six sections leads with its single
   load-bearing claim, then supports it. The point is never buried in a story.
4. **The example never disappears.** Section 04 is mandatory in *every* mode, in
   the session's real language, runnable-in-spirit (inputs and expected output
   stated, not gestured at). Its depth may shrink (one example in Briefing, two
   in Deep Dive); it never vanishes. Terseness never means "skip the example."
5. **Correctness outranks voice, absolutely.** If a vivid line, analogy, or
   framing would be wrong, misleading, or require shading a technical fact, the
   fact wins and the line is cut. An analogy is allowed only when it makes the
   concept land *faster*.
6. **Facts are shown as checkable.** A hash, a slot, a flag's behaviour is
   presented with how one would verify it — never asserted as drama, never as
   suspense-for-its-own-sake ("and then, astonishingly…").
7. **The self-check is answerable from the body alone.** If it isn't, the body
   is missing something — fix the body, not the question.

### 2. The attribution rule — never credit *you* with the agent's work

This is the fix for the lesson that reads "you recomputed the constant by hand"
when it was the **agent** that did it. Getting this wrong voids the lesson's
personal premise, so it is checked in every mode, the default included.

Your transcript has **three kinds of actor**:

- **YOU** — what the human typed, asked, chose, approved, rejected, or shipped;
  the goal you owned and the takeaway you keep.
- **THE AGENT / TOOLING** — what Claude, a CLI, a script, or a test runner
  executed (ran `cast keccak`, piped through Python, retried with `:064x`, wrote
  the assertion).
- **THE SYSTEM / CODE** — what the contract or library itself does.

**The rule:** second person ("you") is reserved **exclusively** for actions the
transcript shows the *human* performed or decided. Every action performed by the
agent or tooling is narrated in the **third person with the actor named** — "the
agent recomputed the constant," "`cast keccak` produced," "the first attempt
used `hex()` and was rerun with `:064x`," "the test suite now asserts." **Never**
write "you computed / ran / recomputed / discovered / debugged" for work the
agent did.

When the teachable episode was *entirely* agent/tooling work, narrate it
honestly in one of three ways: (a) third person, observed — "in your session,
the agent verified the slot by…"; (b) agentless/process voice — "the constant
was recomputed and verified three ways"; or (c) teach the concept impersonally
and cite the session only as the setting — "this came up while a
namespaced-storage struct was added to your bridge adapter." In all cases the
human's genuine role — the decision and the takeaway ("your call to verify
rather than copy") — is what earns "you."

**Ambiguity default:** if you cannot tell from the transcript who took an action,
use the impersonal/passive voice. Never guess "you."

**Mandatory pre-render pass (every mode):** scan the drafted body, flag every
`you <verb>`, and confirm the transcript supports a *human* subject for that verb
before you render. The test: *is there a user message or user-authored edit this
"you" points to?* If not, it is not "you."

---

## The four modes

### `grounded` — Grounded *(the default)*
- **Tone:** composed and confident, like a senior colleague explaining a concept
  at a whiteboard using today's work as the example. Warm but not breathless.
  One or two analogies, each earning its place by clarifying the mechanism.
  Cites the session; never performs it.
- **Depth:** standard, the product baseline. All six sections roughly even,
  **~600–900 words**, one fully worked example, 2–3 pitfalls, 2–3 self-check
  cards.
- **Framing:** concept-led, session-anchored. Open on the mechanism, motivate it
  with what the session was actually trying to do, then cite the session as
  evidence ("in your session this surfaced when…") followed by an honest,
  third-person account of what the agent/tooling did and what *you* genuinely
  asked or decided. No suspense arc, no "and then, remarkably."
- **Second person:** allowed but disciplined — only for what the transcript
  shows you genuinely did/decided. All agent work is third-person, actor named.
- **Use it when:** you want the lesson tied to your actual day — your stack, your
  real episode — taught with depth, reported honestly, without theatrics.

### `tutorial` — Tutorial
- **Tone:** even, instructive, friendly-neutral — a good standalone tutorial or
  a clear docs page. No drama, no suspense, no protagonist. Engaging through
  precision, not performance.
- **Depth:** standard exposure, **~650–950 words**, one solid worked example.
  The *richest concept coverage* of all modes, because no budget goes to
  narrating what happened. Sections 01–03 get a slightly gentler on-ramp.
- **Framing:** concept-first and almost entirely impersonal. The session is used
  only to *pick the topic* and to set the worked example in your real stack; it
  is referenced glancingly ("this came up while a namespaced-storage struct was
  added to your bridge adapter") and never retold as events. Section 02 explains
  why the concept matters in that *kind* of situation, not what unfolded.
- **Second person:** generic-reader "you" only ("you might wonder why…", "if you
  ever inherit two structs…", "your bridge adapter") — the way a blog addresses
  its audience. **Never** "you" attached to a session action. The most
  attribution-proof mode, because it barely narrates the session at all.
- **Use it when:** you want a clean explainer you could almost paste into a blog
  or share with a teammate — the concept taught well, your session the unseen
  reason it surfaced. The answer to "just teach me the concept, not my day."

### `deep` — Deep Dive
- **Tone:** measured, precise, lecturer-at-the-whiteboard. Calm authority over
  personality. Still well-voiced — the clarity floor holds — but words go to
  mechanism, derivation, and trade-offs rather than hooks.
- **Depth:** maximum. Takes the "go longer when the concept earns it" license:
  **~1000–1500 words**. Sections 03 (mental model) and 04 (worked example)
  expand most — two representations of the model and two worked examples (the
  simple case plus one that exposes a sharp edge), 3–4 pitfalls with the
  underlying "why it bites," spec-level edge cases, and a fuller 3-question
  self-check. Never pads.
- **Framing:** concept-and-mechanism first. The session is one cited data point
  ("a concrete instance from today's run"), never the spine. Where session work
  is referenced, the agent's verification process is itself a teaching artifact
  — shown step by step and attributed to the agent.
- **Second person:** predominantly impersonal; "you" only for genuine decisions
  and direct address in the self-check.
- **Use it when:** you want to truly *own* a subtle or load-bearing concept, not
  just recognise it — "I keep half-understanding this; take me all the way down."

### `briefing` — Briefing
- **Tone:** clipped, precise, authoritative — a staff engineer's design note or
  a man-page with a pulse. Short sentences, strong verbs, no analogies-for-colour
  (only an analogy that *is* a definition). Addresses a peer who wants the facts
  fast.
- **Depth:** compressed, not shallow. The same six sections in fixed order and
  the mandatory worked example, stripped to claims and consequences: definition,
  mechanism, the one episode that proves it, the two highest-frequency traps, one
  self-check. **~350–600 words** — never below the floor that keeps each section
  complete. It trades narrative connective tissue for density, never substance.
- **Framing:** impersonal and fact-first. The session is cited in one or two
  precise lines, never narrated.
- **Second person:** sparing and factual — "you" only for your decisions/questions
  of record. Agent/tooling actions stay third-person, named, stated as events.
- **Use it when:** you already know your way around and want the lesson stripped
  to load-bearing facts — even Grounded feels too leisurely.

---

## Picking the mode at write-time (for `/daily-lesson`)

1. **Read the preference.** Look for `~/.claude/daily-lessons/config.json`. It is
   a JSON object that may hold other keys; the one that matters here is `mode`.
2. **One-off override.** If the first whitespace-delimited token of the
   command's arguments is a recognised mode name or alias (see table), it
   overrides the stored preference *for this run only* — consume that token, then
   parse the rest as the date / `back` argument as usual.
3. **Resolve & default.** Normalise the chosen value (alias → canonical key). If
   the config is missing/unreadable/not an object, or `mode` is absent, blank, or
   unrecognised, **default to `grounded`** — never fail, never ask.
4. **Apply** the matching mode block above, on top of the two floors. Then put
   the resolved canonical key in `meta.json` as `"mode"` so the renderer records
   which voice produced the lesson (provenance only — it changes no HTML).

### Canonical keys & aliases (case-insensitive)

| Canonical | Display    | Aliases                                        |
|-----------|------------|------------------------------------------------|
| `grounded`| Grounded   | `default`, `standard`, `balanced`              |
| `tutorial`| Tutorial   | `explainer`, `blog`, `docs`                    |
| `deep`    | Deep Dive  | `deep-dive`, `deepdive`, `deep_dive`, `reference` |
| `briefing`| Briefing   | `brief`, `memo`, `refresher`                   |

### config.json shape

```json
{
  "mode": "grounded"
}
```

`/lesson-mode` writes this file (merging, so unrelated keys survive). It is the
forward-compatible home for future preferences (language, length, port). Lessons
written before this feature simply default to `grounded`.
