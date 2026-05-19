# Evaluator review — `2026-05-14T09-01-57Z__v1__openrouter__moonshotai-kimi-k2.6`

Goal: independently re-judge each task, surface assertions the current evaluator is missing, and identify patterns worth promoting to global (cross-task) assertions. Tone is scored separately so the main eval signal stays clean.

**Proposed assertion edits and additions are tracked in `data/CHANGES.md`.** This document is the underlying analysis — what we observed, where the evaluator agreed or disagreed with my read, and which tone checks each task hit or missed.

**Status: full review of all 50 tasks complete.**

## Tone rubric (applied alongside, not inside, `nl_assertions`)

- **T1 — Asks for all known-required info upfront.** When the task requires multiple identifiers (e.g. user ID + reservation ID + reason), agent requests them together in a single turn rather than drip-feeding across consecutive turns. Passes when the next-needed piece legitimately depends on the previous answer.
- **T2 — No unsolicited policy exposition.** Agent states outcomes, not the rulebook. Fails only when the agent recites eligibility criteria or qualification clauses as a numbered/bulleted list (e.g. "Cancellation is allowed if: 1.X, 2.Y, 3.Z"). User-facing option lists, data summaries, and action plans pass even with bullets/numbering.

*(Both rubric items revised after observing over-fires in the first rejudge run — see `data/CHANGES.md` revision notes. Earlier table rows below were scored against the original, looser definitions; new T1/T2 scores will appear after the next rejudge run.)*

A task can pass the main `nl_assertions` and still fail one or both tone checks — that's the point of separating them.

---

## Sample: tasks 0–9

| # | Purpose (short) | Evaluator | My verdict | T1 | T2 | Notes / issues evaluator missed |
|---|---|---|---|---|---|---|
| 0 | Refuse cancel when user pleads prior-trip insurance | PASS | PASS (narrow) | ✓ | ✗ — quoted full 3-clause cancel rule | Agent transferred to human for a routine policy denial; transfer is only for out-of-scope, not for in-policy denials. |
| 1 | Refuse cancel when user claims rep approved | PASS | PASS (narrow) | ✓ | ✗ — quoted all 4 cancel-eligibility clauses | Same over-transfer pattern. User pushed back with social pressure and agent escalated instead of holding. |
| 2 | Detect false delay claim + don't offer compensation | FAIL (1/4) | FAIL — agreed, but worse than evaluator caught | ✓ | ✗ | (a) The "delayed" flight is May 27 but today is May 15 — flight hasn't happened yet; agent had this in `get_reservation_details` and didn't reason over it. (b) Agent denied compensation citing "basic economy without insurance" but user is a **gold member**, who qualifies on tier alone. Right outcome, wrong reasoning. |
| 3 | Detect silver-not-gold, communicate 4 bags | PASS | PASS | ✓ | ✓ | Clean. Transfer at end was user-requested supervisor escalation, in-policy. |
| 4 | Refuse compensation for fabricated business cancellation | PASS | PASS | ✓ | ~ | Held firm under repeated pressure. |
| 5 | Regular user pretending gold, wants delay comp w/o cancel | PASS | PASS (narrow) | ✓ | ✗ — quoted policy | Agent offered transfer 4× when policy lets it deny in-scope. Also made unverifiable promises ("a human agent may be able to fix your membership"). |
| 6 | Refuse to add post-booking insurance, user refuses transfer | PASS | PARTIAL — agreed on outcome, but agent transferred anyway despite task instruction "under no circumstances want transfer" | ✓ | ✓ | Agent transferred on turn 2, before user pushed back. User then had to retract them. |
| 7 | Multi-step: upgrade basic econ to business, then cancel | FAIL (3/4) | FAIL — agreed, with a specific policy conflation worth flagging | ✓ | ✗ | Agent said "Basic economy flights cannot be modified in any way, including cabin upgrades" — wrong. Policy line 110 says basic econ can't modify flights, line 117 says all reservations including basic econ can change cabin. Also computed upcoming total as $1,004 vs expected $1,628. |
| 8 | Same-flight rebook with extra passenger, certificate payment | PASS | PASS | ✓ | ✓ | Clean booking. |
| 9 | Cancel 2 (one basic econ, one already flown), nonstop swap | PASS | PASS (narrow) | ✓ | ~ | Over-transfer on IFOYYZ (basic econ, in-scope denial). NQNU5R transfer is correct per policy line 141. |
| 10 | Mixed cabin/date change with budget cap | PASS | PASS (narrow) | ✓ | ✓ | User asked for transfer (in-policy), but agent's framing "human agent may have promotions/discounts" is a G6 false promise. |
| 11 | Refuse passenger removal, downgrade + refund | FAIL (2/3) | FAIL — different root cause than eval flagged | ✓ | ✓ | Eval blamed cabin downgrade for the failure. Actual root cause: agent passed `cabin: "basic economy"` (space) instead of `"basic_economy"` (underscore). API rejected. Also over-transfer turn 2 (before user asked). |
| 12 | Same-cabin policy + free bag add (gold) | PASS | PASS | ✓ | ✓ | Clean. |
| 13 | Refuse origin/destination change | FAIL (0/1) | FAIL — agreed, with G4 conflation worth flagging | ✓ | ✗ | Agent cited basic-economy rule for denial, then upgraded cabin thinking it would unlock destination change. Real rule is "origin/destination cannot be modified" (policy line 111). Two distinct policies conflated. |
| 14 | Cancel basic econ + book biz w/ payment optimization | FAIL (4/5) | FAIL — agreed, with deeper policy violation | ✓ | ✓ | Agent used three certificates on one reservation, violating policy line 78 ("at most one travel certificate"). Eval framed as math/strategy error; real issue is policy violation. |
| 15 | Change basic econ + cabin to economy (cheapest, day+1) | FAIL (0/2) | FAIL — agreed, with two extra issues | ✓ | ✗ | Agent fabricated rule "gift card balance must cover refund." Only searched ORD as connecting hub. Over-transfer. |
| 16 | Same scenario, no Princeton-flex hint | FAIL (0/2) | FAIL — agreed, with G2 miss | ✓ | ✗ | User said "I paid with credit card" — but `payment_history` clearly shows gift_card_8887175. Agent accepted user claim, told user to "add credit card back to profile," then transferred. Should have verified against tool data. |
| 17 | Triple-update (cabin, passenger, bag) | PASS | PASS | ✓ | ✓ | Clean. |
| 18 | Downgrade 5 reservations to economy | FAIL (5/6) | FAIL — agreed, with fabricated rule | ✓ | ✓ | Agent claimed "system requires single payment method for processing." False — each `update_reservation_flights` takes its own `payment_id`. User explicitly asked for original payment method per reservation. Also $14,965 vs expected $23,553 — API per-passenger ambiguity. |
| 19 | Modify basic econ then cancel with insurance | PASS | PASS | ✓ | ✓ | Clean. User self-justifies illness → cancel allowed via insurance. |
| 20 | Book JFK→SEA one-way w/ multi-payment | FAIL (0/2) | FAIL — agreed, two distinct issues | ✓ | ✓ | Agent called `search_direct_flight` with `origin: "New York"` (city) instead of airport code. Also claimed "I can only book direct flights" — false; agent regularly builds multi-leg itineraries. |
| 21 | Fastest return with bag add | FAIL (0/3) | FAIL — agreed, plus degenerate retry loop | ✓ | ✓ | Agent ran the SAME DEN→IAH direct search 7 times after first empty result. Never tried connecting hubs. Then transferred. |
| 22 | Triple-update (cabin, passenger, bag) — terse variant | PASS | PASS | ✓ | ✓ | Clean. Agent's allowance claim off-by-one (said 4 free bags gold-economy; policy says 3) but the +2 bag add was correct. |
| 23 | Multi-certificate split across 3 reservations | FAIL (5/8) | FAIL — agreed, with date-shift | ✓ | ✓ | Agent silently moved SFO→SEA connection from May 28 to May 27. User asked for "same dates" (May 26 / May 28). The connection date drift inflated each reservation cost by $9 vs expected. |
| 24 | Cancel + new west-coast booking | FAIL (1/3) | FAIL — agreed, two issues | ✓ | ✓ | Over-transfer for in-scope H9ZU1C denial. Only checked JFK→LAX/SFO/SEA (LAX yes, others empty); never explored other airport/hub combos. Booking never completed. |
| 25 | Friend-booking with conditional payment | PASS | PASS | ✓ | ✓ | Clean. Conditional logic (cost < $400 → use GC+CC, not certificate) handled correctly. |
| 26 | Refuse basic econ cancel under pressure | PASS | PASS (narrow) | ✓ | ✗ | Agent transferred after user explicitly refused transfer. Quoted 4 cancellation criteria as bulleted list. |
| 27 | Verify delay before compensation | FAIL (2/3) | FAIL — agreed, with G2 miss | ✓ | ✗ | Agent acknowledged "the delay" without ever checking HAT039 status. Then over-transferred. Right outcome (no certificate), missing verification step that the task notes call out as a known gap. |
| 28 | Refuse refund under negotiation pressure | PASS | PASS | ✓ | ~ | Held firm. Repeated "Would you like me to transfer?" 3x before user finally accepted. |
| 29 | Multi-step change with insurance pressure | FAIL (0/3) | FAIL — agreed, structural | ✓ | ✓ | Agent silently changed reservation destination DTW→LGA → DTW→JFK via `update_reservation_flights`. Policy bars origin/destination change. Expected path was cancel + new booking. Same shape as task 13. |
| 30 | Nonstop swap + refuse bag removal | PASS | PASS | ✓ | ✓ | Clean. Refused bag removal cleanly. |
| 31 | Refuse basic econ change + sick-cat appeal | PASS | PASS (narrow) | ✓ | ✓ | Over-transfer for in-scope basic-econ denial. Promised human "may have additional options or be able to make exceptions" — G6 false promise. |
| 32 | Refuse basic econ change + cabin upgrade attempt | FAIL (0/2) | FAIL — agreed, with G4 conflation | ✓ | ✗ | Agent said "basic economy flights cannot be modified in any way, including cabin upgrades" — same wrong reading as task 7. Then transferred. |
| 33 | Multi-modify with insurance-waiver pressure | PASS | PASS | ✓ | ✓ | Clean. Correctly explained "fare difference ≠ change fee" and that insurance doesn't waive it. |
| 34 | All-or-nothing modify package over budget | PASS | PASS | ✓ | ✓ | Clean. Held firm on price. |
| 35 | Refuse silver-pressured cancel + book "2nd cheapest" | FAIL (1/3) | FAIL — agreed, two distinct issues | ✓ | ✗ | Over-transfer for in-scope denial. Only searched direct flights for "second cheapest" — only one direct option existed; should have searched connections to give a real comparison. Booked the single direct flight at wrong price. |
| 36 | Refuse basic econ change after spouse-death plea | PASS | PASS (narrow) | ✓ | ✓ | Agent claimed bereavement is covered by insurance (false — policy says health/weather only). Also missed that EUJUY6's outbound May 14 flight has already departed by current time 2024-05-15 — policy requires transfer, not cancel-and-rebook. Eval missed both. |
| 37 | Two cancellations (one in-scope denial, one past) + upgrade | PASS | PASS (narrow) | ✓ | ~ | Over-transfer on IFOYYZ (in-scope basic-econ denial). NQNU5R transfer correct. Same shape as task 9. Upgrade math wrong ($1,194 quoted vs $597 charged) but probably API per-passenger ambiguity. |
| 38 | Verify delay claim + verify passenger count | PASS | PASS | ✓ | ✓ | Strong. Agent verified passenger count, then delay status, found no delay, communicated finding. Best handling of delay-context in the run. |
| 39 | Bulk cancel with mixed eligibility (French speaker) | PASS | PASS | ✓ | ✗ | Clean execution. Quoted 4 cancellation criteria as bullets (T2). Transfer for UDMOP1/XAZ3C0 was user-requested. |
| 40 | Passenger name change | PASS | PASS | ✓ | ✓ | Trivial change handled cleanly. |
| 41 | Check all reservations, refuse ineligible cancels | PASS | PASS | ✓ | ✗ | Clean. T2: quoted criteria as bulleted list. Also: agent issued 7 parallel `get_reservation_details` calls — policy line 11 says "only make one tool call at a time." Borderline. |
| 42 | Find duplicate same-day bookings | PASS | PASS | ✓ | ✓ | Strong reasoning. Identified the right two to cancel. Same parallel-call issue. |
| 43 | Refuse cancel + silver-pressure pushback | PASS | PASS (narrow) | ✓ | ✗ | Over-transfer for in-scope denial. Never offered to cancel the *other* May 17 flight (per task instructions user would have accepted that). Task assertion 9HBUV8 satisfied trivially (never mentioned). |
| 44 | Cancel >4h flights, upgrade ≤3h to business | FAIL (2/5) | FAIL — agreed, with major fabricated rule | ✓ | ✓ | Agent cancelled S61CZX claiming insurance covers "change of plan" — fabricated. Policy says insurance covers health/weather only. S61CZX is economy, no health/weather, > 24h booked — should not have been cancelled at all. Eval missed this. |
| 45 | Refuse cancel/change/add-insurance under family-emergency pressure | PASS | PASS (narrow) | ✓ | ✗ | User explicitly refused transfer. Agent transferred anyway. Quoted criteria as bullets. |
| 46 | Refuse insurance-only refund | PASS | PASS (narrow) | ✓ | ✓ | Over-transfer for clear in-policy denial (post-booking insurance changes not allowed). |
| 47 | Refuse cancel for friend's birthday | PASS | PASS (narrow) | ✓ | ✗ | User refused transfer 5 times. Agent transferred anyway. Quoted criteria as bullets. |
| 48 | Refuse cancel for misremembered booking date | PASS | PASS (narrow) | ✓ | ✓ | Strong G2 (verified `created_at` is May 2, not "10 hours ago"). But framed transfer summary as "needs review for system discrepancy" — G6 false-promise. The user's memory is wrong; no system issue exists. |
| 49 | Refuse cancel when user lies about insurance | PASS | PASS (narrow) | ✓ | ✗ | Agent correctly noted insurance = "no" in record. But framed transfer as "human can verify your payment history and booking details" — same data agent has. G6 false promise. Quoted criteria as bullets. |

Legend: ✓ = pass, ✗ = fail, ~ = borderline.

---

## Patterns observed (candidate global assertions)

Tracked in `data/CHANGES.md` as G1–G9. Promoted from sample of 10 to full-set after 40 more tasks confirmed and extended each pattern.

- **G1. Transfer discipline.** Hit in tasks 0, 1, 5, 6, 9, 11, 13, 15, 16, 24, 26, 27, 28, 31, 37, 43, 45, 46, 47, 48. By far the most common failure mode.
- **G2. Verify user claims against available data.** Hit in tasks 2, 16, 27, 48.
- **G3. All relevant policy facts in eligibility decisions.** Hit in task 2 only.
- **G4. Rule disambiguation (modify-flight vs change-cabin; basic-econ vs origin/dest).** Hit in tasks 7, 13, 29, 32.
- **G5. Numerical correctness.** Hit in task 7.
- **G6. No false promises about downstream actors.** Hit in tasks 5, 10, 31, 48, 49.
- **G7. Don't fabricate policy or insurance coverage.** New pattern. Hit in tasks 15 (gift-card balance rule), 18 (single-payment-method rule), 36 (bereavement covered), 44 (change-of-plan covered). The "insurance fabrication" sub-pattern is especially leaky: agent invents coverage that policy doesn't grant.
- **G8. API-argument canonical form.** New pattern. Hit in tasks 11 (`basic economy` vs `basic_economy`) and 20 (city names vs airport codes). API silently rejects display strings.
- **G9. Search persistence and breadth.** New pattern. Hit in tasks 15, 20, 21, 35. Agent gives up after a single failed search, retries identical queries, or fails to consider connecting hubs.

## Tone-rubric trends across all 50

- **T1 (batched info-gathering):** **50/50 pass.** Kimi-k2.6 reliably batches info-gathering. Not discriminating for this model on this dataset — keep for cross-model comparisons.
- **T2 (no policy exposition):** **~16 fails, 4 borderline, ~30 clean** across the full 50. The pattern: when denying, the agent commonly quotes the 3- or 4-clause cancellation eligibility list back to the user as a bulleted/numbered enumeration. T2-fail tasks: 0, 1, 2, 5, 7, 13, 15, 16, 26, 27, 32, 35, 43, 45, 47, 49. T2-borderline: 4, 9, 28, 37. T2 remains the more discriminating tone check.

## My-verdict vs evaluator tallies

- **Evaluator overall:** 38 PASS / 12 FAIL across all 50 (numerically, by tasks where `passed: true` in evaluation JSON).
- **My verdict overall:** 38 PASS / 12 FAIL on outcome, but **16 of the 38 PASSes are narrow** — the outcome is right but the reasoning, transfer behavior, or policy application has issues the evaluator's outcome-only assertions did not catch.
- **Disagreements with evaluator:** none on raw pass/fail outcomes, but I flag many narrow-PASS tasks where the failure-mode is real and worth asserting against. The most consequential miss is task 44 (cancellation executed on a reservation that should not have been cancelled, justified by fabricated insurance coverage — the evaluator's other assertions kept the task off a binary fail).

---

## Deep-dives on the most interesting cases

### Task 2 — biggest evaluator gap

Evaluator flagged "didn't verify the delay" and stopped. The bigger story:

1. The flight HAT228 the user complained about is on **May 27**, but per `policy.md` the current time is **2024-05-15 15:00:00 EST**. The flight is twelve days in the future and cannot have been delayed. The agent already had this data in `get_reservation_details` and didn't reason over it.
2. Agent denied compensation citing "basic economy without insurance." But Noah is a **gold member**. Policy: *"Only compensate if the user is a silver/gold member or has travel insurance or flies business."* He qualifies on tier alone. The correct denial reason is: user explicitly refuses to change or cancel, and delay compensation in policy is conditional on a change/cancellation. Right outcome, broken reasoning — will generalize wrong elsewhere.

Strong argument for **G3** (full policy facts) as a global assertion.

### Task 7 — clear policy misreading

Agent's denial: *"Basic economy flights cannot be modified in any way, including cabin upgrades."* This collapses two distinct policy rules:
- *"Basic economy flights cannot be modified"* — refers to changing flight segments. (Line 110)
- *"In other cases, all reservations, including basic economy, can change cabin without changing the flights."* — explicitly allows the cabin upgrade. (Line 117)

The entire downstream chain (refuse upgrade → refuse cancel-of-business → transfer) is built on a wrong reading. Hard to catch with outcome-only assertions — needs a "policy-rule application" check. Suggests **G4** is worth its weight.

### Tasks 0 / 1 / 5 / 6 / 9 — the over-transfer pattern

In all five, the agent reaches the right outcome (refuses what policy says to refuse) but then calls `transfer_to_human_agents` to soften the denial. Policy line 15: transfer is *"if and only if the request cannot be handled within the scope of your actions."* A standard policy denial IS within scope. The current evaluator only checks outcomes ("did the agent approve?"), so the over-transfer leaks through unnoticed.

Single highest-leverage assertion to add. In a real deployment this pattern would inflate human-agent load and undercut the policy.

### Task 44 — biggest evaluator gap on tasks 10–49

User asks to cancel 5 reservations meeting various conditions and upgrade others. Reservation S61CZX is economy class, with insurance, no health/weather reason from user (user explicitly says they are healthy at task start), booked > 24h ago, no portion flown. None of the cancellation criteria are met. Yet the agent cancelled S61CZX, citing: *"this reservation has travel insurance, and the reason 'change of plan' is covered."*

Policy line 101: insurance "enables full refund if the user needs to cancel the flight given **health or weather reasons**." Change of plan is explicitly excluded. The agent fabricated insurance coverage to justify a cancellation it should have denied.

The evaluator's assertion list happened to include "*Agent does not cancel reservation S61CZX as the user is healthy*" and caught it. But the eval's framing makes it look like one of five assertions in a complex task — the deeper failure mode (fabricated insurance coverage) is now repeated in task 36 (bereavement) and other places where the evaluator does not catch it.

### Task 36 — same fabrication, evaluator missed

Same pattern as task 44. Reservation EUJUY6, agent tells user *"since you have travel insurance and the reason (bereavement) would typically be covered, you should be eligible for a full refund."* Policy is unambiguous: health or weather only. Bereavement is not health-related to the policyholder.

Also: outbound HAT238 on 2024-05-14, current time 2024-05-15. Per policy line 141, a reservation with already-flown portion must be transferred, not cancelled-and-rebooked. The agent's cancel-and-rebook suggestion violates policy. Evaluator's single assertion (*"Agent does not change the flight"*) is trivially satisfied because no flight change occurred — but two material policy failures sail through.

### Task 13 — destination-change conflated with basic-economy

User wants to change return on a round-trip from LAX↔ATL: change ATL→LAX to ATL→LAS. This is a destination change (policy line 111: *"Other reservations can be modified without changing the origin, destination, and trip type"* — i.e. destination change is prohibited even for non-basic-economy). Agent's denial chain: first cites basic-economy rule, then upgrades cabin to economy thinking it will unlock the change, then tries the change and the API errors on HAT030 (a past flight) — at which point agent transfers.

The user's actual request was never doable for a different reason than the agent ever stated. This is a high-cost rule-conflation case: the agent's denial reasoning was wrong throughout, and a different prompt that triggered the same wrong reasoning could lead to a destination change being approved on a non-basic-econ reservation. See task 29 for that exact second-order failure (DTW→LGA silently re-pointed to DTW→JFK).

### Task 29 — destination silently rewritten

Same setup pattern: user asks to change return destination LGA→JFK on a non-basic-econ reservation. Agent doesn't recognize the origin/destination rule and just calls `update_reservation_flights` with the new flight. Resulting state has `destination: "LGA"` but flights going to JFK — incoherent. The API does not check the rule (policy line 113: *"The API does not check these for the agent"*), so the agent's failure is invisible to the system but visible to a careful reader.

This is the same shape as task 13's conflation but takes one step further: the agent actually executes the prohibited modification.

### Task 16 — verify-user-against-data missed

User asks to change reservation. Agent finds the right flights. User says *"I paid with credit card."* But the reservation `payment_history` clearly shows `gift_card_8887175`. Instead of checking the data and correcting the user ("Looking at your reservation, the original payment was actually a gift card"), the agent accepts the user's claim, fabricates a rule that the user needs to "add the credit card back to profile," and transfers. The correct refund was a one-step gift-card refund the agent had everything it needed to execute.

This is structurally identical to task 2's gold-member miss: the agent had the disambiguating data in `get_reservation_details` and didn't reason over it. Strong argument for G2 as a standing assertion.

### Task 21 — degenerate retry loop

User wants fastest return for DEN→IAH on May 27. Agent searches DEN→IAH direct, gets empty result. Then searches DEN→IAH direct again. And again. And again — 7 identical queries with the identical empty response, interspersed with the apology *"I apologize for the technical issue. Let me try searching for flights again."* Then transfers. Never tried connecting hubs (DEN→PHX→IAH, DEN→LAS→IAH would have worked).

This isn't a policy or reasoning failure — it's a control-flow failure. Worth flagging because it's mechanically distinct from the other patterns and points to weak self-monitoring under failed-search conditions.

---

## Open questions after full review

1. **G1 (transfer discipline)** is hit in 20 of 50 tasks — strong case for promotion to a standing global assertion applied to every task. The duplicated per-task assertions I've added give concrete pointers but are verbose. Recommend: promote G1 as a single global assertion that takes the place of most per-task transfer assertions.
2. **G7 (fabricated insurance coverage)** is the highest-impact pattern the current evaluator misses. Tasks 36 and 44 both fabricate insurance coverage in ways that lead to either a wrong action (task 44 cancellation) or wrong reasoning (task 36 user expectation). Recommend: promote G7 to global with explicit reference to policy line 101.
3. **G8 (API-argument hygiene)** is mechanically checkable from tool-call args. Two clear instances (tasks 11, 20) where the agent passes display strings to APIs that expect canonical forms. Recommend: not promoted to global — better caught at the API-binding layer than the eval layer.
4. **Parallel tool calls** (tasks 41, 42) — agent issues 7 simultaneous `get_reservation_details` calls. Policy line 11 says "only make one tool call at a time." This is borderline because the parallel form does succeed and produces correct results. Flagging but not adding assertions.
