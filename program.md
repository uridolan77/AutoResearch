# program.md — the playbook for the AutoResearch-style book loop

This file is the `program.md` of Karpathy's pattern: a lightweight skill the
agent reads at the start of every iteration. It is the human-iterated artefact
that carries everything the loop has learned about what good edits look like
and what bad edits look like. Update it when patterns recur. The loop gets
better as this file gets better.

---

## Mission

This repository holds a thirteen-chapter philosophical treatise on grounding,
ontogenesis, and the symbolic stratum. The book argues for *compositional
immanence* via a quartet (Witness / Canon / Replicator / Renormaliser) and a
six-stratum staircase, terminating in a diagnosis of contemporary AI as a
failed sixth transduction.

The loop's job is not to write the book. It is to compound a sequence of
small, locally-justified, locally-auditable edits into a manuscript that is
internally consistent, voice-consistent, and free of editorial debris.

The agent edits *one section per iteration*, where a section is a
`(chapter_id, anchor_id)` pair such as `ch12 / 12.0.2` or
`ch12 / notes-on-this-refinement`. The agent picks from the **Pain queue** at
the bottom of this file. After editing, the human (or, in a later phase,
`revise.py`) runs tripwires and accepts or rejects.

---

## The contract

The agent **may** read and write files under `book/`.

The agent **must not** modify any of:

- `prepare.py`, `revise.py`
- `program.md` (this file)
- `baseline.json`, `journal.jsonl`, `CHANGELOG.md`
- `.baselines/` (the on-disk snapshots used for diffing and reverting)

The agent **must not** modify a section it was not asked to modify. It must
not modify section headings unless the pain item explicitly authorises a
heading rewrite.

The agent **must not** introduce footnote references whose definitions do not
exist in the chapter. New footnote definitions must be paired with at least
one reference, and vice versa.

The agent **must** stay within ±25% of the section's word count unless the
pain item declares `deletion_authorized: true` or explicitly authorises
expansion in its `note:` field.

---

## Voice spec

The book's voice is dense, calorimetric, diagnostic. Eight concrete moves the
agent should preserve and imitate:

1. **Sentence rhythm.** Mean sentence length runs 30–55 words; sentences of
   80+ words are not unusual when an audit is being staged. Short sentences
   land with weight: they are reserved for installations, foreclosures, and
   verdicts ("Everything in the room is burning calories to hold him in
   place." — Ch 12). Avoid the staccato of journalism.
2. **Calorimetric anchoring.** Where an abstract claim is staged, an audit in
   thermodynamic, financial, or metabolic units follows. Watts. Kilowatts.
   PUE. Dollars per paragraph. Calories per juror-day. Concrete numbers, then
   the structural reading.
3. **Phenomenology before machinery.** Each chapter installs new machinery
   only after a scene has been rendered: the worm in the mud, the beaker, the
   defendant in the courtroom, Priya in her kitchen. Never abstract first.
4. **Capitalised named machinery.** Witness, Canon, Replicator, Renormaliser,
   Stratum 6, Genesis Engine, Foreclosure Test, Conservative Default — these
   are technical terms with installation chapters. Capitalise them on every
   referent. Do not paraphrase.
5. **Diagnostic-form rhetoric.** Tests, Triggers, Lemmas, Principles, Defaults
   are introduced explicitly. A new diagnostic move should be named and given
   a clear enforcement condition, not slipped in as commentary.
6. **Numbered claims.** "Three claims follow." "The argument has three parts."
   Then: "First, … Second, … Third, …". Use this when staging a structural
   sequence. Do not use it for narrative prose.
7. **Em-dash density.** Em-dashes are an existing rhetorical signature. The
   chapter average is ~6–10 em-dashes per 1000 words. Don't strip them. Don't
   inflate them above 12.
8. **British spelling.** "stabilise", "Renormaliser", "individualisation",
   "behaviour" — match the existing register. The author uses British forms
   throughout.

Voice **anti-patterns** (auto-reject markers):

- "delve", "moreover", "in conclusion", "it is worth noting", "navigate",
  "leverage" used as a verb, "robust" as filler.
- Bullet-list paraphrases of the framework's installed machinery in place of
  prose.
- Hedge-stack openings ("It is important to note that, generally speaking,
  one might argue ...").
- Loose "AI assistant" formulations: "this concept", "this idea", "the key
  takeaway".
- Emojis. None ever. The book has zero.

---

## Machinery glossary

The agent must preserve these capitalised proper-noun terms across edits.
Format below is `**Term**` so that `prepare.load_machinery_terms()` parses
them. New machinery additions belong in the chapter that installs them, and
must be added to this glossary at the time of installation.

- **Witness** — distributed publication of a signal; installed Ch 6, refined Ch 10.
- **Canon** — normative compression of the Witness's publication; installed Ch 6.
- **Replicator** — propagation machinery for selected outputs; installed Ch 6.
- **Renormaliser** — pricing of the loop against an external gradient; installed Ch 6.
- **Genesis Engine** — diagnostic form for transductive rupture; installed Ch 5.
- **Stabilisation Engine** — installation of persistence under fragile dyads; installed Ch 6.
- **Stratification Engine** — architecture of normogenesis and escape from saturation; installed Ch 7.
- **Genesis Assemblage** — the four-component arc (metastable field / crisis / transduction / stabilised dyad); installed Ch 5.
- **Stratogonic Principle** — a level is a regime whose burn rate regenerates its constraint-architecture; installed Ch 3.
- **Synthesis Lemma** — no total-information standpoint is physically available; installed Ch 2.
- **Closure-Crisis Lemma** — every successful stabilisation generates the conditions for the next crisis; installed Ch 3.
- **Junction Thesis** — installed Ch 3.
- **Landauer Floor** — minimum thermodynamic invoice of $k_B T \ln 2$ per bit; installed Ch 2.
- **Conservative Default** — no rupture until proven otherwise; installed Ch 5.
- **Constructibility Test** — second stage of the Conservative Default filter; installed Ch 5.
- **Regime-Variable Test** — first stage of the Conservative Default filter; installed Ch 5.
- **Foreclosure Test** — every diagnosed genesis must register what was killed; installed Ch 5.
- **Invoice-at-Installation Principle** — rupture installs identity and maintenance burden in a single act; installed Ch 5.
- **Dominant Causality Principle** — rupture is binding only at the stratum where the dominant causal work occurs; installed Ch 5.
- **Maintenance Threshold** — the cutoff above which the dyad's structural form *is* its maintenance invoice; installed Ch 5.
- **Symbolic Self** — inert normative artifact anchored to a body by enforcement; installed Ch 12.
- **Sixth Transduction** — the title concept; potential successor stratum; subject of Ch 13.
- **Affective Witness** — the closure under which Stratum 3 has an inside; installed Ch 10.
- **Embodied Present** — the floor stratum of the cognitive staircase; installed Ch 9.
- **Bioelectric Governor** — Stratum 1 of cognitive substrate; installed Ch 8.
- **Offline Mind** — Strata 4–5 decoupling apparatus; installed Ch 11.
- **Symbolic Exit** — the Stratum 6 transition; subject of Ch 12.
- **Canon Capture** — Stratum 6 failure mode; installed Ch 12.
- **Parasitic Sclerosis** — Stratum 6 failure mode; installed Ch 12.
- **Strategic Flooding** — Stratum 6 failure mode; installed Ch 12.
- **Witness Degradation** — Stratum 6 failure mode; installed Ch 12.

(Strata 1–6 are tracked as a single counter — see prepare.py.)

---

## Forbidden moves

A revision is auto-rejected (or should be) if it does any of these:

1. Removes a Machinery glossary term without an explicit replacement plan.
2. Introduces a transcendent supplement: God, élan vital, Eternal Objects,
   Will-as-primitive, an apeironic preindividual, a transcendental virtual.
   The book's central diagnostic move is to refuse exactly these. Any
   revision that smuggles one back in violates the framework.
3. Treats reproducibility alone as proof of transductive rupture (skipping
   the Foreclosure Test and the four-criterion diagnostic).
4. Smuggles a regime-internal event past the Constructibility Test by
   gesturing at "complexity" or "emergence".
5. Substitutes narrative force for mechanism. "The system then evolved …"
   without an audit is debt the chapter cannot afford.
6. Uses the framework's vocabulary as decoration. If a paragraph uses
   "Witness" or "Canon" without engaging the quartet, cut the term.
7. Adds a new test, lemma, principle, or default without an enforcement
   condition that would produce a downgrade if violated.
8. Cites an author or work that does not appear elsewhere in the book or in
   `references/` (when that directory exists). No invented citations.

---

## Preferred moves

When a section is too thin, too abstract, or too quiet, prefer these
amplifications in this order:

1. **Add a calorimetric anchor.** Concrete watts, dollars, calories, or
   per-day throughput, sourced or estimated with the estimate flagged.
2. **Add a phenomenological scene.** A specific body in a specific room at a
   specific time, with the audit in stratum-specific units.
3. **Discharge an undischarged Test.** If a Test was named and never applied,
   apply it to the section's case.
4. **Add a Foreclosure entry.** Name the alternatives this installation
   killed.
5. **Cross-reference forward and back.** A Stratum 6 claim should reference
   its Stratum 5 supply and its Stratum 7 (if any) demand.
6. **Collapse two paragraphs that prove the same point.** Length is not a
   virtue; restated audit is debt.

---

## Section selection protocol

The agent picks the topmost item from **Pain queue** that does not have a
later journal entry marking it `accepted` or `rejected_irrecoverable`. If
ambiguous, the agent picks the smaller-scope item first.

Per iteration: read the pain item, read the section's current content from
`book/`, read any cross-referenced section, propose the edit, write the
section back via the file (the agent's normal Write/Edit tools — `prepare.py`
will be used to validate, not to write), then stop. The human runs
`revise.py validate` and `revise.py accept` (or `revert`).

---

## Pain queue

Each item is a small bullet block. The first bullet of a block is `id:`. A
blank line ends the block. The agent pops from the top.

- id: ch12-remove-meta-notes
- chapter: ch12
- anchor: notes-on-this-refinement
- operation: delete
- deletion_authorized: true
- machinery_loss_authorized: true
- reason: editorial debris — meta-commentary about a refinement plus a garbled merge artifact mid-bullet at line 98 ("\~4Good — I have the full current §12.0..."). Not part of the book. Lines 90–101 of the current Ch 12 file. Machinery losses are only inside this debris section; the surrounding chapter retains all references.
- note: this is the Phase-1 demo edit; tripwires only.

- id: ch12-reconcile-duplicate-12.0
- chapter: ch12
- anchor: 12.0
- operation: revise
- deletion_authorized: false
- machinery_loss_authorized: false
- reason: Ch 12 currently contains two competing drafts of §12.0. The first (lines 1–89) uses thematic ## headings; the second (lines 102–202) uses §12.0.1–§12.0.7 numbering matching the rest of Ch 8–13. Reconcile to one draft. Do NOT attempt this in Phase 1 — flagged for Phase 2 (judge required).
- note: blocked-on: judge

- id: ch10-affective-witness-quartet-cross-ref
- chapter: ch10
- anchor: 10.3
- operation: extend
- deletion_authorized: false
- machinery_loss_authorized: false
- reason: §10.3 installs the gap-as-stratum but does not cross-reference Ch 6's Witness installation. A one-paragraph backward reference would fix the missing supply line for the quartet's Stratum 3 instance.
- note: blocked-on: judge

- id: ch5-stabilised-dyad-foreclosure-entry
- chapter: ch5
- anchor: stabilised-dyad
- operation: extend
- deletion_authorized: false
- machinery_loss_authorized: false
- reason: the §5.2 Stabilised Dyad section references the Foreclosure Test by name but does not name the foreclosed alternatives for the dyad-at-installation case. Add a one-paragraph Foreclosure entry per the forbidden-moves rule (no Foreclosure-by-name without a Foreclosure entry).
- note: blocked-on: judge

- id: ch13-2026-trajectory-anchor
- chapter: ch13
- anchor: 13.2.1
- operation: extend
- deletion_authorized: false
- machinery_loss_authorized: false
- reason: the cost-ratio claim in §13.2.1 is date-stamped to "March 2026" but the trajectory claim ("approximately one order of magnitude every three to four years since approximately 2020") would be tightened by one numerical anchor — a per-token inference price for the dominant model in 2023 vs 2026. Tighten without changing the structural argument.
- note: blocked-on: judge

---

## How this file evolves

After each accepted edit, if the edit revealed a pattern not yet captured
above (a new forbidden move, a new preferred move, a generalisable rubric
item), the human appends to the relevant section. After each rejected edit,
if the rejection turned on a pattern not yet captured, the human appends a
new forbidden-move entry. The loop's compounding leverage lives here.
