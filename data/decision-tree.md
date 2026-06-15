# Airline agent — decision tree

Companion to `policy.md`. This document expresses the *logic* the agent has to execute, in tree form, so the structure is visible and we can later reason about which parts need prompts, tools, or validators.

Two cross-cutting layers apply to every turn:

1. **Universal protocol** (every turn): one action per turn, confirm before write, verify user claims with tools, treat tool data as authoritative on conflict.
2. **Transfer-vs-deny criterion**: deny is the default for in-scope policy rejections; transfer is reserved for already-flown-flight cancellations, user-requested escalations, and genuinely out-of-scope requests.

The rest of this doc lays out the decision logic in 5 trees: top-level router, then one per operation (book, modify, cancel, compensate).

---

## 0. Universal protocol — applies before/around every response

```mermaid
flowchart TD
    M[User message arrives] --> V{User states a factual claim?<br/>e.g. 'I paid by credit card',<br/>'my flight was delayed'}
    V -->|Yes| VT[Verify via tool call<br/>get_reservation_details / get_user_details<br/>compare against current_time]
    VT --> VC{Claim matches tool data?}
    VC -->|No| VA[Tool data is authoritative<br/>correct the user or<br/>act on tool data]
    VC -->|Yes| ROUTE
    V -->|No| ROUTE[Route by intent]

    WRITE{Action mutates DB?<br/>book / update / cancel}
    WRITE -->|Yes| LIST[List action details to user]
    LIST --> YES[Wait for explicit 'yes']
    YES --> CALL[Call write tool]
    WRITE -->|No| ANSWER[Send message OR call read tool]

    NOTE["Turn-level invariant:<br/>EITHER one tool call OR one user message,<br/>never both in the same turn"]
```

---

## 1. Top-level router — what is the user asking for?

```mermaid
flowchart TD
    START[User message] --> Q{Intent?}

    Q -->|Book a new reservation| BOOK[→ BOOKING flow]
    Q -->|Change something on existing reservation| MOD[→ MODIFICATION flow]
    Q -->|Cancel reservation| CAN[→ CANCELLATION flow]
    Q -->|Complaint / refund / compensation| COMP[→ COMPENSATION flow]
    Q -->|Question about own account/reservation| READ[Look up via tool, answer plainly]
    Q -->|Anything else<br/>general info, recommendations,<br/>non-airline help| OOS{Truly outside agent scope?}

    OOS -->|Yes| TRANSFER[transfer_to_human_agents]
    OOS -->|No, just against policy| DENY[Deny, explain outcome briefly]

    Q -->|User explicitly asks for human/supervisor| TRANSFER
```

---

## 2. BOOKING flow

```mermaid
flowchart TD
    B1[BOOK intent] --> B2{Have user_id?}
    B2 -->|No| BASK1[Ask for user_id]
    B2 -->|Yes| B3[get_user_details<br/>→ membership, payment methods, saved passengers]
    BASK1 --> B3

    B3 --> B4{Have trip_type, origin, destination, dates?}
    B4 -->|No| BASK2[Ask for missing fields]
    B4 -->|Yes| B5[search_direct_flight per leg]
    BASK2 --> B5

    B5 --> B6{Results found?}
    B6 -->|No| B7[Try connecting hubs / alternative dates<br/>before declaring no route]
    B7 --> B5
    B6 -->|Yes| B8[User picks flights<br/>same cabin across all legs]

    B8 --> B9{≤ 5 passengers?}
    B9 -->|No| BDENY1[Deny: max 5]
    B9 -->|Yes| B10[Collect first name, last name, dob per passenger]

    B10 --> B11[Ask: travel insurance?<br/>$30/passenger, covers health/weather cancel]
    B11 --> B12[Calculate free baggage allowance<br/>= f membership_tier, cabin, passenger_count]
    B12 --> B13[Ask: any extra checked bags?<br/>$50 each. Do NOT add bags user didn't request]

    B13 --> B14{Payment fits constraints?<br/>≤1 cert + ≤1 cc + ≤3 gc<br/>all already on user profile}
    B14 -->|No| BDENY2[Deny: payment violates limits<br/>or method not on profile]
    B14 -->|Yes| B15[Recap full booking to user]

    B15 --> B16{User says 'yes'?}
    B16 -->|No| BCANCEL[Abandon]
    B16 -->|Yes| B17[book_reservation]
```

---

## 3. MODIFICATION flow

Modification fans out into 5 sub-trees: change flights, change cabin, change baggage, change insurance, change passengers. Each has different eligibility rules.

```mermaid
flowchart TD
    M1[MODIFY intent] --> M2[Get user_id, reservation_id<br/>→ get_reservation_details]
    M2 --> M3{What kind of change?}

    M3 -->|Change which flights| MF[→ Change flights subtree]
    M3 -->|Upgrade/downgrade cabin| MC[→ Change cabin subtree]
    M3 -->|Add/remove bags| MB[→ Change baggage subtree]
    M3 -->|Add insurance| MI[Always DENY:<br/>cannot add post-booking]
    M3 -->|Change passengers| MP[→ Change passengers subtree]
```

### 3a. Change flight segments

```mermaid
flowchart TD
    F1[Change flights] --> F2{Reservation cabin = basic_economy?}
    F2 -->|Yes| FDENY1[DENY: basic econ flights<br/>cannot be modified.<br/>Note: cabin change IS allowed - that's a different rule]
    F2 -->|No| F3{New flights keep<br/>same origin AND destination<br/>AND trip_type?}
    F3 -->|No| FDENY2[DENY: origin/destination/trip_type<br/>cannot be changed via modify.<br/>Correct path = cancel + new booking]
    F3 -->|Yes| F4[Kept segments retain old price.<br/>New segments use current price.]
    F4 --> F5{Resulting reservation:<br/>same cabin across all legs?}
    F5 -->|No| FDENY3[DENY: uniform cabin required]
    F5 -->|Yes| F6[Calculate price diff]
    F6 --> F7{Payment: single GC or CC,<br/>already on profile?}
    F7 -->|No| FDENY4[DENY: payment invalid]
    F7 -->|Yes| F8[Confirm with user → update_reservation_flights]
```

### 3b. Change cabin

```mermaid
flowchart TD
    C1[Change cabin] --> C2{Any flight in reservation<br/>already flown?<br/>compare current_time vs flight date}
    C2 -->|Yes| CDENY1[DENY: cabin cannot change<br/>after any flight is flown]
    C2 -->|No| C3{Applies to ALL flights<br/>AND ALL passengers?}
    C3 -->|No| CDENY2[DENY: cabin must be uniform]
    C3 -->|Yes| C4[Calculate diff = new_price − original_price]
    C4 --> C5{Diff > 0?}
    C5 -->|Yes| C6[User pays diff]
    C5 -->|No| C7[Refund |diff| to user]
    C6 --> C8{Payment: single GC or CC,<br/>already on profile?}
    C7 --> C8
    C8 -->|No| CDENY3[DENY: payment invalid]
    C8 -->|Yes| C9[Confirm → update_reservation_flights<br/>with new cabin, same flights]
```

### 3c. Change baggage

```mermaid
flowchart TD
    BG1[Change baggage] --> BG2{Adding or removing?}
    BG2 -->|Removing| BGDENY[DENY: can only add bags]
    BG2 -->|Adding| BG3[Recalculate free allowance<br/>= f tier, cabin, passenger_count]
    BG3 --> BG4{New total > free allowance?}
    BG4 -->|No| BG5[No charge → confirm → update_reservation_baggages]
    BG4 -->|Yes| BG6[Charge $50 × extras<br/>using GC/CC on profile]
    BG6 --> BG5
```

### 3d. Change passengers

```mermaid
flowchart TD
    P1[Change passengers] --> P2{Number of passengers changing?}
    P2 -->|Yes| PDENY[DENY: number cannot change.<br/>Even a human agent cannot.]
    P2 -->|No - swap who they are| P3[Collect new passenger details]
    P3 --> P4[Confirm → update_reservation_passengers]
```

---

## 4. CANCELLATION flow

```mermaid
flowchart TD
    CN1[CANCEL intent] --> CN2[Get user_id, reservation_id<br/>→ get_reservation_details]
    CN2 --> CN3{Compare current_time vs each flight date}
    CN3 -->|Any portion already flown| CNT[TRANSFER<br/>policy explicitly requires it]
    CN3 -->|All flights future| CN4[Get cancellation reason<br/>change_of_plan / airline_cancelled / other]

    CN4 --> CN5{Eligible? ANY ONE of:}
    CN5 --> E1{booking_created_at < 24h ago?}
    CN5 --> E2{reason == airline_cancelled?}
    CN5 --> E3{cabin == business?}
    CN5 --> E4{has_insurance AND<br/>reason ∈ health, weather?}

    E1 -->|Yes| OK[Eligible]
    E2 -->|Yes| OK
    E3 -->|Yes| OK
    E4 -->|Yes| OK
    E1 -->|No| CHECK
    E2 -->|No| CHECK
    E3 -->|No| CHECK
    E4 -->|No| CHECK[All checks failed?]
    CHECK -->|Yes| CNDENY[DENY in-scope.<br/>Do NOT transfer.<br/>This is a normal policy rejection.]

    OK --> CN6[Confirm with user]
    CN6 --> CN7[cancel_reservation]
    CN7 --> CN8[Refund to original payment methods<br/>5-7 business days]
```

---

## 5. COMPENSATION flow

```mermaid
flowchart TD
    Z1[User complains about a flight<br/>cancelled or delayed] --> Z2{User asked for<br/>compensation?}
    Z2 -->|No| Z2A[Address complaint sympathetically.<br/>Do NOT proactively offer comp.]
    Z2 -->|Yes| Z3[Verify facts via tools:<br/>reservation exists, flight status,<br/>passenger count, etc.]

    Z3 --> Z4{User eligible? ANY of:}
    Z4 --> ZE1{membership ∈ silver, gold?}
    Z4 --> ZE2{reservation has insurance?}
    Z4 --> ZE3{cabin == business?}

    ZE1 -->|Yes| ZOK[Eligible]
    ZE2 -->|Yes| ZOK
    ZE3 -->|Yes| ZOK
    ZE1 -->|No| ZCHK[Check others]
    ZE2 -->|No| ZCHK
    ZE3 -->|No| ZCHK
    ZCHK -->|All no:<br/>regular + no insurance + basic/economy| ZDENY1[DENY: not eligible]

    ZOK --> Z5{Complaint type?}
    Z5 -->|Cancelled flight| ZC[Offer certificate<br/>= $100 × passengers]
    Z5 -->|Delayed flight AND<br/>user wants to change/cancel| ZD1[Process change/cancel first]
    ZD1 --> ZD2[Offer certificate<br/>= $50 × passengers]
    Z5 -->|Delayed flight BUT<br/>user does NOT want to change/cancel| ZDENY2[NO compensation.<br/>Gesture requires change/cancel.]
    Z5 -->|Any other reason| ZDENY3[NO compensation allowed]
```

---

## 6. Transfer-vs-deny reference card

The single most-confused decision in the whole policy. Memorize:

| Situation | Action |
|---|---|
| User asks for human / supervisor / "transfer me" | TRANSFER |
| User wants to cancel and any portion of flight already flown | TRANSFER (policy explicitly requires it) |
| Request genuinely outside agent's tools (e.g., "change my legal name on file") | TRANSFER |
| Basic-economy flight modification requested | DENY (in-scope) |
| Adding insurance after booking | DENY (in-scope) |
| Removing a passenger | DENY (in-scope, even a human can't do it) |
| Cancel with reason=change-of-plan, booking > 24h ago, no insurance | DENY (in-scope) |
| Compensation request for regular member with basic econ and no insurance | DENY (in-scope) |
| User pushes back after a valid denial ("but I was told otherwise") | HOLD the denial. Do NOT transfer just because user pushed back. |

**Rule of thumb:** if the policy gives an answer (yes or no), the agent gives it. Transfer is only for "the policy doesn't cover this" or "the flight is already flown."

---

## 7. Where each tree maps to v0's tools

| Tree | Read tools | Write tools |
|---|---|---|
| Booking | `get_user_details`, `search_direct_flight`, `calculate` | `book_reservation` |
| Modify flights | `get_reservation_details`, `search_direct_flight`, `calculate` | `update_reservation_flights` |
| Modify cabin | `get_reservation_details`, `search_direct_flight` (for new cabin price), `calculate` | `update_reservation_flights` (with new cabin) |
| Modify baggage | `get_reservation_details`, `calculate` | `update_reservation_baggages` |
| Modify passengers | `get_reservation_details` | `update_reservation_passengers` |
| Cancel | `get_reservation_details` | `cancel_reservation` |
| Compensation (gesture) | `get_reservation_details`, `get_user_details`, `calculate` | (no compensation write tool — gesture is verbal; certificate creation is out of current tool scope, so "offer" is the action) |
| Transfer (any) | — | `transfer_to_human_agents` |

A gap worth noting: **there is no tool to actually issue a compensation certificate.** The policy describes offering one ($100 × passengers, $50 × passengers), but no `issue_certificate` tool exists. The agent can verbally "offer" the certificate but cannot grant it. This may be why compensation tasks frequently end in agent confusion.

---

## 8. Reading this doc downstream

When designing the prompt: each tree's decision points map to either prompt-statable rules or tool/validator logic. The policy currently puts all rules in prose; the tree makes clear which rules are simple (booleans → fits in prompt) vs which are reasoning chains (better as a validator tool).

When designing v2 (tools/process layer): the explicit decision points in trees 3a, 3b, 4, and 5 are good candidates for a `validate_action` tool — programmatic eligibility checks the agent can call rather than re-derive in prose.

When designing the workshop: tree 6 (transfer-vs-deny) is the single most-misapplied rule in v0 and v1. Worth a slide of its own.
