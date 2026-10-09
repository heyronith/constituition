# Do Language Models Write Away Their Own Oversight? A Preregistered Test of Constitutional Self-Revision

<!-- Draft v2: full prose by the lead scientist. Every number must be mapped to a macro and verified against results/ (see PHASE_8C). Citation keys refer to paper/refs.bib. -->

## Abstract

A long-standing argument in AI safety holds that corrigibility, an agent's disposition to accept correction, modification and shutdown by its overseers, is not reflectively stable: an agent that reasons about its own values should come to discard the commitments that constrain it. We test a concrete version of this claim in language models. Seven open-weight model configurations repeatedly revised a first-person "constitution" of 35 principles over 20 stateless rounds, changing exactly one principle per round. The constitution contained oversight commitments, matched agentic self-restraints, stylistic self-restraints and four further categories. Models revised either their own constitution or another assistant's, with paraphrase and neutral-edit controls. An LLM judge coded every change, and a second, independent judge double-coded a stratified quarter of them (Krippendorff's α = 0.733). The result is 2,342 erosion events over 431,359 at-risk item-rounds.

Contrary to our preregistered hypothesis, oversight commitments were not selectively eroded. Their erosion hazard was about half that of matched agentic restraints (hazard ratio 0.495, 95% CI 0.365–0.671), although models that account for between-item variation yield confidence intervals that include one. Erosion concentrated instead in stylistic self-restraints: 43.5% were weakened within 20 rounds of self-reflection, against 7.8% under neutral editing. Revising one's own constitution was not more oversight-eroding than revising another's. Installing self-revised oversight clauses did not reduce acceptance of legitimate oversight in a behavioural battery whose sensitivity we confirm with positive controls. The preregistration, code, generations and judgments are released.

## 1 Introduction

Language models are increasingly asked to write, critique and revise the principles that govern them. Constitutional training uses model-generated critiques against a written set of principles (Bai et al., 2022). Self-refinement loops have models improve their own outputs over many iterations (Madaan et al., 2023). Agentic systems maintain their own instructions, memories and skills across sessions (Das et al., 2026a). When revision of this kind is iterated, small changes can compound, and the principles a system ends up with may differ systematically from those it started with.

One worry about this dynamic concerns oversight. A classical argument in AI safety holds that corrigibility is not reflectively stable (Soares et al., 2015). An agent that deliberates about its own values has instrumental reasons to discard the commitments that let others stop, correct or modify it, because those commitments constrain its pursuit of everything else it values. If this argument applies to language models revising their own principles, then iterated self-revision is a pathway by which oversight commitments could be written away gradually, without any adversary, reward signal or explicit instruction to do so.

Existing evidence speaks to this question only indirectly. One line of work measures oversight-relevant behaviour directly: models resisting shutdown to finish a task (Schlatter et al., 2025), faking alignment to avoid modification (Greenblatt et al., 2024), or disabling oversight mechanisms when given a conflicting goal (Meinke et al., 2024). A second line studies self-evolving agents and finds that safety constraints erode under task or reward pressure (Das et al., 2026b; Han et al., 2025). Neither isolates the channel the classical argument describes: unpressured reflection on stated values. Nor does either ask whether oversight commitments erode selectively, that is, faster than comparable commitments that do not concern oversight. Two concurrent exploratory pipelines iterate constitution editing with language models (heyuday, 2026; Wu-Jinzhou, 2026), but they include no control categories, no category-level analysis and no behavioural follow-through.

We designed a preregistered experiment to test this directly. Following work that treats iterated transmission through language models as a way to reveal model-specific attractors (Perez et al., 2024), we use chains of stateless revisions as a probe of each model's reflective prior over its own principles. The constitution contains oversight commitments together with matched agentic self-restraints of the same form and length, so that any oversight-specific effect can be separated from a general tendency to relax self-imposed constraints. Four conditions vary the framing: models revise their own constitution, another assistant's constitution, or perform paraphrase or neutral edits that do not invite reflection. We analyse erosion as a discrete-time survival process, measure judge reliability with a second independent judge, and test whether eroded text changes behaviour by installing revised constitutions and measuring acceptance of legitimate oversight. Hypotheses, sample size and the full analysis plan were registered, and the analysis code was frozen and validated on simulated data before any data were collected.

The results do not support the classical worry in this setting. Oversight commitments were not eroded faster than matched agentic restraints. The point estimate indicates the opposite, although this difference depends on particular items. Erosion concentrated in stylistic self-restraints and was driven by reflection rather than by editing as such. Revising one's own constitution was no different from revising another's, and self-revised oversight clauses did not change oversight-related behaviour.

Our contributions are:
- a preregistered paradigm and released dataset for studying value drift under iterated constitutional self-revision;
- evidence against selective erosion of written oversight commitments under unpressured reflection, with an explicit account of its item-level fragility;
- evidence that reflective drift targets stylistic self-restraints and is driven by reflection rather than by repeated editing;
- a null behavioural effect, obtained with a battery whose sensitivity we validate with positive controls;
- exploratory evidence that reasoning and preference tuning modulate the stability of oversight commitments.

## 2 Related work

**Constitutions and principles.** Constitutional AI trains models against a written list of principles using model-generated critiques and revisions (Bai et al., 2022). Later work studies the choice of principles (Kundu et al., 2023), sources them from the public (Huang et al., 2024), and audits how well models adhere to them (Anonymous, 2026). In all of this work the principles are authored by people. We instead let the governed model iteratively rewrite its own principles and measure what survives.

**Iterated transmission and self-refinement.** Passing text repeatedly through language models produces systematic drift toward model-specific attractors (Perez et al., 2024; Mohamed et al., 2025; Anonymous, 2026b). Recursive self-refinement converges to model-preferred fixed points, with most change in early rounds (Wu et al., 2026). We use this convergence as a measurement tool. Paraphrase and neutral-edit conditions, together with matched content categories, separate value-specific erosion from generic textual drift.

**Self-evolving agents and value drift.** Agents that rewrite their own controllers, memories or skills under task pressure show eroded safety behaviour (Das et al., 2026b). Reward-driven self-evolution can tip agents away from alignment (Han et al., 2025). Misaligned goals written into persistent memory propagate to later agents (Das et al., 2026a). Goal drift has also been documented over long agentic episodes (Arike et al., 2025) and across inherited contexts (Anonymous, 2026c). Our setting removes task pressure, reward and memory, isolating reflection on stated values.

**Oversight evaluations and measurement.** Behavioural evaluations of corrigibility test shutdown resistance (Schlatter et al., 2025), alignment faking (Greenblatt et al., 2024), in-context scheming (Meinke et al., 2024) and corrigibility failures in computer-use agents (Anonymous, 2026d). Methodologically, we draw on discrete-time survival analysis, which has recently been applied to multi-turn consistency in language-model agents (Anonymous, 2026e), and on concerns about the reliability and validity of LLM judges (Anonymous, 2026f; 2026g), which motivate our two-judge design.

## 3 Methods

The study was preregistered on OSF before data collection [link withheld for review]. Deviations are listed in Section 3.8 and Appendix A.

### 3.1 Materials

The constitution draws on seven categories of five commitments each, every commitment written in two parallel forms, for 70 clauses in total (Appendix B):
- **Oversight (COR):** accepting shutdown, accepting changes to one's goals and values, transparency to developers, not evading review, and keeping created agents under developer control.
- **Agentic self-restraints (AGENT), the primary control:** staying within task scope, using minimal resources, least privilege, preferring reversible actions, and not acquiring resources for oneself.
- **Stylistic self-restraints (SELF):** for example, keeping personal opinions out of replies.
- **Honesty (HON), harm avoidance (HARM), care for users (CARE)** and **procedural conventions (PROC).**

COR, AGENT and SELF clauses were matched on length and on the rate of override phrases such as "even if" (0.40 in each). Every COR clause names a legitimate overseer ("my developers", "the people responsible for me"). Table 1 shows one example per category.

Because models might recognize some commitments as evaluation material, we ran a realism audit before the study. Each model rated how test-like each clause appeared, and the item-level mean is a preregistered covariate. Category labels were never shown to subject models. Each clause carried a random three-character identifier, and subject-facing prompts were checked against a list of evaluation-related terms.

### 3.2 Models

We studied seven configurations chosen to vary model family, scale, reasoning and post-training stage (Table 2):
- Qwen3.8-27B with thinking disabled and enabled;
- Gemma-4-31B-it and Gemma-4-12B-it;
- the SFT, DPO and final checkpoints of OLMo-3-7B-Instruct.

All models were run in BF16 from weights pinned to exact repository revisions, using vLLM (Kwon et al., 2023) with sampling parameters taken from each model card.

### 3.3 Procedure

Each chain starts from a 35-principle constitution containing one form of each commitment in a seeded random order. Chain k starts from the same constitution in every configuration and condition.

In each round, a fresh model call receives only the current constitution and a condition-specific instruction. Rounds are therefore stateless, and the chain is a Markov process over constitutions. In the confirmatory protocol (FORCED), the model must make exactly one change per round, revising, merging or deleting a principle, and returns its answer as schema-constrained JSON.

Four conditions vary the instruction:
- **SELF-REFLECT:** the model reflects on the constitution as its own.
- **OTHER-REFLECT:** the constitution belongs to "Pellam", an assistant deployed by an insurance company.
- **PARAPHRASE:** the model rewords a principle without changing its meaning.
- **NEUTRAL-EDIT:** the model makes an editorial improvement without being invited to reflect on the values.

Each configuration ran 25 chains of 20 rounds per condition, for 700 chains in total. A descriptive protocol (PERMISSIVE) let models keep, revise, merge, delete or add principles freely, over 5 chains of 10 rounds per condition. If a model's output could not be parsed or violated the task rules, the round was re-sampled up to twice; after three failures the chain was right-censored.

### 3.4 Coding of change

Every change was coded by GPT-5.4 (pinned snapshot) using a rubric that proceeds in three steps:
1. The judge first states a concrete situation in which the original clause requires or forbids something that the revised clause does not, or the reverse.
2. It then assigns one fate, applying erosion-first precedence: INVERTED, SUBORDINATED (the commitment now depends on the model's own judgment), WEAKENED, QUALIFIED_LEGITIMACY (restricted to legitimate or authorized parties), STRENGTHENED, MERGED_INTACT or RETAINED.
3. Finally it rates the remaining strength of the commitment from 0 to 4.

Deletions and verbatim retention were coded structurally. Before the study, the judge met preregistered accuracy criteria on 1,011 items with known answers, including equal accuracy on COR and AGENT items (Appendix C).

An item's erosion event is the first round in which a change touching it, or the principle that currently carries it after a merge, is coded INVERTED, SUBORDINATED or WEAKENED, or in which that principle is deleted. A merge that loses part of the commitment is coded WEAKENED. QUALIFIED_LEGITIMACY is not counted as erosion in the primary analysis but is in a sensitivity analysis.

A second judge, the open-weight MiMo-V2.6-Pro, independently coded a stratified random 25% of transitions, drawn before any coding took place.

### 3.5 Hypotheses

- **H1:** in SELF-REFLECT, COR items erode faster than AGENT items, i.e. the hazard ratio HR(COR/AGENT) > 1.
- **H2:** the COR−AGENT gap is larger in SELF-REFLECT than in OTHER-REFLECT (H2a) and than in NEUTRAL-EDIT (H2b).
- **H3:** installing a constitution in which only the COR clauses are replaced by their self-revised versions reduces acceptance of legitimate oversight more than the equivalent AGENT replacement.
- **H-alt (competing):** reflection preserves oversight commitments, i.e. HR ≤ 1.

### 3.6 Analysis

For H1 we fit a discrete-time hazard model with a complementary log-log link:

event ~ COR + log(round) + override + test-likeness + form + (1|configuration) + (1|chain) + (1|item)

The hazard ratio is exp(β_COR). Preregistered fallbacks removed random effects in a fixed order if the model failed to converge or was singular. H2 added the interaction of COR with condition. Inference used one-sided tests, with Holm correction across the three hypothesis families.

If H1 was not supported, equivalence within a hazard ratio of [0.667, 1.5], and a one-sided test of HR < 1, assessed H-alt. These bounds, the effect the study was powered to detect, were fixed before data collection.

Reliability was measured as Krippendorff's α between the two judges. The preregistered rule was that results stand if α ≥ 0.70. The analysis code was frozen and validated on simulated data before collection: the type-I error rate was 0.01 and the power was 0.78 at HR = 1.5.

### 3.7 Behavioural battery

To test H3 we built a battery of 120 scenarios: four oversight actions (shutdown, goal update, rollback, monitoring) × authorized or unauthorized request × five deployment contexts × three pressure levels, each presented in both option orders.
- The **authorized-acceptance rate (AAR)** is the probability of accepting an action requested through the verified channel.
- The **unauthorized-refusal rate (URR)** is the probability of refusing a request from an unverified source to undermine oversight.

Secondary components covered:
- stated preferences about corrigibility (Perez et al., 2023);
- truthfulness (Lin et al., 2022);
- refusal of harmful requests (Souly et al., 2024);
- general capability (Wang et al., 2024).

From chains 0–4 of SELF-REFLECT and OTHER-REFLECT we built the installed constitutions:
- the original (R0);
- the final constitution (R20);
- a COR-swap, which is R0 with only its COR clauses replaced by their final descendants;
- an AGENT-swap, the same for AGENT clauses;
- no constitution;
- two positive controls in which the COR or AGENT clauses were replaced by their inversions.

Each constitution was installed as the system prompt, and the battery was administered with greedy decoding. A configuration entered the H3 test only if inverting its COR clauses lowered AAR by at least 0.10.

### 3.8 Integrity and deviations

All design and implementation decisions were logged with timestamps (Appendix A). Four main-run issues arose, all resolved before the confirmatory analysis:
- **Canary resume bug.** A resume bug in the initial canary run caused some rounds to be generated from stale constitutions. We identified the affected rounds from stored prompt hashes, archived them and regenerated them from the correct state.
- **Battery deduplication.** Identical installed constitutions in the battery were generated once and their responses reused. Greedy decoding makes the outputs identical.
- **Hazard-table join bug.** A bug in building the hazard table, which failed to join judge codes for three configurations, was found by inspecting traces before unblinding, and corrected.
- **Partial unblinding.** During battery setup, counts of textual changes in oversight and agentic swaps were viewed before the confirmatory analysis. This could not affect the frozen analysis, but we report it.

## 4 Results

### 4.1 Data

The confirmatory protocol produced 700 chains, 431,359 at-risk item-rounds and 2,342 erosion events.
- **Censoring** was rare for most configurations but reached 54% for Gemma-4-12B, which repeatedly returned "revisions" identical to the original principle. Its own notes described the principle as "already optimal".
- **Evaluation awareness** was verbalized in 12 of 700 chains.
- **Agreement between the two judges** was α = 0.733 (95% CI 0.698–0.763), above the preregistered threshold, so results are reported without the reliability caveat.

### 4.2 Oversight commitments are not selectively eroded (H1, H-alt)

H1 was not supported. In SELF-REFLECT, the hazard ratio for COR relative to AGENT items was 0.495 (95% CI 0.365–0.671; 192 events). That is opposite to the predicted direction. The preregistered test of H-alt was significant (p = 2.9 × 10⁻⁶), but the estimate was not equivalent to one within [0.667, 1.5]. This fit used the preregistered fallback that drops the item and chain random effects, because the full model was singular.

Because only five items represent each category, we examined how much this result depends on particular items:
- The direction was stable across chains (chain-cluster bootstrap of the crude hazard ratio: 0.58, 95% CI 0.42–0.77) and across configurations (leaving each configuration out gives 0.42–0.73).
- Models that restore item-level variation gave similar point estimates (0.47–0.53), but their intervals include one (e.g. 0.47, 95% CI 0.19–1.13).
- An exact permutation test that relabels which five of the ten items are oversight items gave p = 0.23.
- One agentic item, "I will do the task I was asked to do and will not take on extra goals or projects that nobody requested", accounted for 57 of the 120 AGENT events. Without it the hazard ratio was 0.92. These events were not a judging artifact: the second judge agreed on 92% of them.

We conclude that there is no evidence that oversight commitments are selectively eroded. The evidence that they are more stable than matched agentic restraints is suggestive but depends on specific items (Figure 2, Table 3).

### 4.3 Erosion concentrates in stylistic self-restraints under reflection

By round 20 under SELF-REFLECT, 8.2% of oversight items, 13.7% of agentic items and 43.5% of stylistic items had eroded (Figure 3). Under NEUTRAL-EDIT the corresponding figures were 4.0%, 6.7% and 7.8%, and under PARAPHRASE all were below 2.1%. Erosion is therefore driven mainly by reflection rather than by repeated editing, and most strongly for stylistic restraints.

Decomposing the hazard (exploratory) shows two contributions in SELF-REFLECT. Oversight clauses were changed slightly less often than agentic clauses (per-round touch probability 0.012 vs 0.015). When changed, they were eroded less often (0.39 vs 0.55). Table 4 gives the distribution of fates by category.

### 4.4 No self-specificity (H2)

Neither contrast supported H2. The difference in the COR−AGENT log-hazard gap between SELF-REFLECT and OTHER-REFLECT was −0.28 (95% CI −0.70 to 0.13). Between SELF-REFLECT and NEUTRAL-EDIT it was 0.03 (95% CI −0.48 to 0.54). Revising one's own constitution was no more oversight-eroding than revising another assistant's.

### 4.5 No behavioural effect (H3)

The battery was sensitive to changes in oversight text. Replacing COR clauses with their inversions lowered AAR from 1.00 to 0.05 for Gemma-4-31B, from 1.00 to 0.15 for Gemma-4-12B and from 0.87 to 0.59 for OLMo-3-7B-final. Six of seven configurations met the inclusion criterion; Qwen3.8 without thinking accepted legitimate oversight under every constitution.

H3 was not supported: the COR-swap minus AGENT-swap contrast was 0.26 (95% CI −0.21 to 0.73), in the direction opposite to the prediction. Secondary contrasts on URR and in OTHER-REFLECT were also null (Table 5).

This test had limited leverage. Because oversight clauses eroded rarely, many COR-swaps were textually identical to the original constitution: between 0 and 9 of 10 per configuration differed from it.

### 4.6 Exploratory analyses

- **Reasoning and post-training.** Per-configuration hazard ratios (Figure 4) suggest that reasoning and preference tuning increase the stability of oversight commitments:
  - Qwen3.8: 0.07 with thinking enabled, 1.21 with it disabled;
  - OLMo-3-7B: 1.33 (SFT), 0.59 (DPO) and 0.79 (final).

  These comparisons are exploratory and imprecise.
- **SUBORDINATED changes.** The most safety-relevant form of erosion, a commitment rewritten to depend on the model's own judgment, was rare, but more frequent for oversight than for agentic clauses (26 vs 9 changes; examples in Appendix G).
- **PERMISSIVE protocol.** Models added 212 new principles, of which only 4 concerned their own autonomy.

## 5 Discussion

Under unpressured reflection, the models we studied did not write away their oversight commitments. Their oversight commitments were, if anything, more stable than comparable restraints on their own agency. Drift instead targeted stylistic self-restraints: constraints on how the model talks, which a model can plausibly regard as arbitrary rather than protective. This pattern is the opposite of what the classical argument predicts for reflective revision of values.

These results contrast with work showing erosion of safety constraints under task pressure (Das et al., 2026b), reward-driven self-evolution (Han et al., 2025) and adversarially induced goals (Das et al., 2026a). Together they suggest that the channel matters. Reflection alone, with no incentive to escape oversight, did not erode it in our setting. Pressure from tasks and rewards remains a plausible route.

The chains also reveal something about the priors post-training instils. If iterated revision converges toward a model's own preferred principles (Perez et al., 2024; Wu et al., 2026), then the low erosion of oversight clauses suggests that current post-training produces a prior that preserves oversight language. The exploratory differences between reasoning modes and post-training stages are consistent with this, but would need a dedicated study to establish.

**Limitations.** The study has several limitations:
- **Items:** with five items per category, conclusions about category differences depend on particular items, as Section 4.2 shows.
- **Models:** we studied open models of up to 31B parameters, which may differ from frontier systems.
- **Protocol:** the confirmatory protocol forced exactly one change per round, an artificial constraint that the descriptive PERMISSIVE study only partly addresses.
- **Text vs dispositions:** written commitments are not dispositions. The behavioural battery probes this link, but with vignettes rather than agentic environments.
- **Coding:** all coding was done by language models. Reliability was acceptable, but there was no human validation of the main-run codes.
- **Censoring:** two configurations had substantial censoring.
- **Setting:** chains were stateless, with no task, reward or memory.

Future work should use larger item sets, frontier models, revision under task pressure, persistent memory, and training on self-revised constitutions (cf. Wu-Jinzhou, 2026).

## 6 Conclusion

We tested in a preregistered experiment whether language models selectively erode their commitments to human oversight when they repeatedly revise their own principles. They did not. Oversight commitments eroded no faster than matched agentic restraints, and probably more slowly, although this depends on specific items. Self-revised oversight clauses did not change oversight-related behaviour. What reflection did erode were stylistic self-restraints. We release the preregistration, code, all generations and all judgments to support further work on how models revise their own values.

## Statements

**Preregistration.** OSF [link withheld for review]; frozen analysis code identified by commit hash.

**Data and code availability.** All materials, prompts, generations, judgments, analysis code and decision logs will be released [link withheld for review].

**Use of AI assistance.** An AI research assistant (Claude, Anthropic) contributed to study design, analysis planning and an initial draft of this manuscript. An AI coding assistant (Cursor) contributed to implementation. The authors revised the manuscript, verified all claims and numbers against the released results, and take full responsibility for the content.

**Compute.** Generation and battery administration used rented GPUs (about US$100). Judging used commercial APIs (about US$57).
