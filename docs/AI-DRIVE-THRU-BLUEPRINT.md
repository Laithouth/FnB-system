# AI Drive-Thru Ordering Platform — Product Blueprint

**Codename:** `LaneAI` (working title)
**Category:** B2B SaaS + Edge Hardware for Food & Beverage operators
**Target buyers:** Independent QSRs, multi-branch chains, franchises, cloud kitchens, mall food courts, airport/petrol-station outlets
**One-line pitch:** *A trained drive-thru employee, on demand — multilingual, accurate, always upselling, integrated with your POS and KDS.*

---

## 1. Product Description

LaneAI is a voice-first ordering agent that replaces or augments the human order-taker at drive-thru lanes and front-counter kiosks. Customers speak naturally; the AI parses speech against the restaurant's specific menu, asks the same clarifying questions a trained crew member would, upsells using rules the operator configures, displays a live order on the customer screen, and pushes a structured order into the existing POS / KDS / receipt printer.

The system is sold as a **multi-tenant SaaS platform** with a per-store hardware bundle. Each tenant brings its own menu, prices, modifiers, combos, promotions, brand voice, and POS — LaneAI adapts. The same core engine powers every brand; only the **Menu Knowledge Pack** and **Brand Voice Profile** change.

**Why it wins:** purpose-built for a single, narrow job — taking restaurant orders accurately and fast — with deep menu intelligence, deterministic order validation, and graceful human handoff. It is not a generalist chatbot dressed up as a kiosk.

---

## 2. Main User Journey

| Actor | Step | Outcome |
|---|---|---|
| Driver | Pulls into lane, triggers presence sensor / loop detector | Greeting plays |
| LaneAI | Greets in brand voice | "Welcome to Brand X, what can I get started for you?" |
| Driver | Speaks order (any phrasing, any language supported) | ASR + NLU produce a candidate order |
| LaneAI | Asks only the missing required questions | Order becomes complete and valid |
| LaneAI | Suggests 0–1 contextual upsell | Higher AOV without friction |
| LaneAI | Reads back full summary + total | Customer confirms |
| Driver | Pulls forward to pay/collect | POS already has the order, KDS is firing tickets |
| Manager | Sees lane in real time on the dashboard | Can take over with one click if needed |

**Target lane time:** ≤ 35 seconds for a 2–3 item order in production, comparable to or faster than top-decile human crews.

---

## 3. AI Conversation Flow

### State machine (deterministic, LLM-assisted)

```
GREETING → LISTENING → PARSING → CLARIFYING ⇄ LISTENING
                                     ↓
                             ITEM_VALIDATING
                                     ↓
                                 UPSELL? ── no ──→ SUMMARY
                                     │ yes
                                     ↓
                                 LISTENING (upsell answer)
                                     ↓
                                 SUMMARY
                                     ↓
                              CONFIRM ⇄ LISTENING (edits)
                                     ↓
                                 SUBMIT → POS/KDS → CLOSE
```

A finite-state controller — not the LLM — owns transitions. The LLM is used for **understanding** (slot filling) and **phrasing** (response generation), but never to decide whether the order is valid. That guarantees structural correctness and lets us audit every state change.

### Slot-filling model

Each menu item declares **required slots** and **optional slots**. The dialogue manager only asks about unfilled required slots. Order-of-questions is configurable per brand (size first vs. flavor first, etc.).

```yaml
item: spicy_chicken_meal
required_slots: [meal_size, side, drink]
optional_slots: [sauce, no_ingredients, add_ons]
default_slots:  { side: fries, drink: coke }   # if brand allows defaults
```

### Eight canonical phases

1. **Greeting** — brand-configurable, < 2 seconds.
2. **Capture** — open mic, partial transcription streamed.
3. **Parse** — extract `{item, qty, size, modifiers}` tuples with confidence per slot.
4. **Clarify** — ask only about low-confidence or missing required slots.
5. **Confirm-on-screen** — every parsed item appears on the customer screen within 300 ms.
6. **Upsell** — at most one upsell prompt per cart, governed by upsell ruleset.
7. **Summary** — read full order + total, ask for confirmation.
8. **Submit** — push structured order to POS, fire KDS, end session.

---

## 4. Menu Adaptation Framework

The system is menu-agnostic. Every restaurant uploads a **Menu Knowledge Pack (MKP)**:

### 4.1 MKP structure

- **Items**: id, names + aliases (incl. nicknames, common mispronunciations), category, base price, SKU, kitchen station.
- **Modifier groups**: e.g., `meal_size`, `bread_type`, `milk_type`, `sauce`, `spice_level`. Each modifier has price delta, default flag, exclusivity, min/max selections.
- **Item ↔ modifier-group bindings**: which modifiers apply, which are required, which are optional, in what order to ask.
- **Combos**: parent item + child slot graph (a meal is just an item with required child-slots).
- **Promotions**: time-bounded discounts, BOGOs, bundle deals, conditional (e.g., "free upgrade on Mondays").
- **Availability rules**: per-store, per-daypart, per-stockout.
- **Allergen tags**: per-item, per-modifier.
- **Tax rules**: VAT / service charge / tip if applicable.
- **Upsell rules**: see §6.
- **Brand voice profile**: greeting, tone (casual/formal), pace, language priority, max upsells per order.

### 4.2 Adapter examples

| Vertical | Required slots example | Sample clarifier |
|---|---|---|
| Burger QSR | meal_size, side, drink, sauce | "Regular or large meal?" |
| Coffee shop | size, milk_type, hot_or_iced, sweetness | "What milk would you like?" |
| Fried chicken | piece_count, sides[2], drink, sauce | "Mashed potatoes or coleslaw?" |
| Pizza | size, crust, sauce, toppings, cheese | "Thin crust or classic?" |
| Shawarma | protein, bread, sauces, spice, meal_or_sandwich | "Garlic sauce or tahini?" |
| Dessert | flavor, size, toppings | "Cup or cone?" |

The same engine handles all of these — only the MKP changes.

---

## 5. POS / KDS / Hardware Integration Model

### 5.1 Order delivery

LaneAI emits a canonical order document (see §19) and writes it through a **POS Adapter**. We ship adapters for major systems (Foodics, Toast, Square, NCR Aloha, Oracle Micros, Lightspeed, Revel, Olo, internal HTTP/REST or webhook). Any system not yet supported can be integrated via:

- **Push API**: HTTPS POST with HMAC signed payload.
- **Receipt printer fallback**: ESC/POS network printing — works for any restaurant with a network printer, no POS API needed (critical for mid-MVP rollouts).
- **KDS direct**: emit ticket directly to KDS if POS has no receive endpoint.

### 5.2 Sync direction

- **Outbound** (LaneAI → POS): orders, voids, modifications.
- **Inbound** (POS → LaneAI): menu updates, 86-list (out-of-stock), price changes, daypart toggles, pause/resume from store manager.

### 5.3 Hardware bundle (per lane)

| Component | Notes |
|---|---|
| Outdoor microphone (beam-forming, IP65) | Existing intercom mic can be reused via line-in |
| Outdoor speaker | Same |
| Edge compute box (mini-PC, GPU optional) | Runs ASR + dialogue locally, falls back to cloud for LLM |
| Customer-facing display (sunlight-readable LCD) | Live order screen |
| 4G/5G failover modem | Resilience |
| Manager tablet | Live dashboard, takeover button |
| Loop / presence sensor | Optional but reduces false greetings |

---

## 6. Upselling Engine

Upsell logic must never be annoying. Rules:

- **At most one** upsell per order by default (configurable up to two).
- Upsells must be **contextual**: drink → size up; meal → dessert; combo → add cheese/bacon.
- **Margin-weighted**: rules engine ranks candidates by margin × likelihood × inventory.
- **Suppress** when: customer rushed (interrupted twice), large order (>5 items), customer already declined an upsell in this session, item out of stock.
- **Brand override**: each brand can blacklist specific upsell pairings.

```yaml
upsell_rule:
  trigger: item.category == "burger_meal" and meal_size == "regular"
  offer: "make_it_large"
  copy: "Want to make that large for {{price_delta}}?"
  max_per_session: 1
  cooldown_after_decline: session
```

---

## 7. Technical Architecture

```
┌────────────────────────── EDGE (per lane) ──────────────────────────┐
│  Mic → ASR (streaming) → VAD → Dialogue Client → TTS → Speaker      │
│                              │                                       │
│                              ↓                                       │
│                   Customer Display (WebGL/HTML)                      │
│                              │                                       │
│                              ↓ WSS                                   │
└──────────────────────────────┼───────────────────────────────────────┘
                               │
┌────────────────────────── CLOUD ────────────────────────────────────┐
│  API Gateway (TLS, mTLS for stores)                                  │
│      │                                                               │
│      ├── Session Service (state machine, slot tracker)               │
│      ├── NLU Service (LLM + structured output, function-calling)     │
│      ├── Menu Service (MKP store, versioning, 86-list)               │
│      ├── Rules Engine (validation, upsell, promo)                    │
│      ├── Order Service (canonical order, idempotency)                │
│      ├── POS Adapter Layer (Foodics/Toast/Square/...)                │
│      ├── Telephony/Audio Gateway (if voice goes via cloud)           │
│      ├── Admin API (dashboard, menu CRUD)                            │
│      ├── Analytics Pipeline (Kafka → warehouse)                      │
│      └── Takeover Service (real-time bridge to staff console)        │
│                                                                       │
│  Storage: Postgres (metadata) · Redis (sessions) · S3 (audio/logs)   │
│           ClickHouse/BigQuery (analytics) · Vector DB (alias search) │
│  LLM: hosted Claude/Sonnet for NLU + on-device small model fallback  │
│  ASR: streaming engine (Deepgram/AssemblyAI/Whisper) + custom        │
│       restaurant-specific language model bias                         │
└──────────────────────────────────────────────────────────────────────┘
```

### Key choices
- **Edge-first audio.** ASR streams locally to keep latency under 250 ms. Cloud is used for NLU and order persistence. If cloud drops, edge runs a degraded "menu-bounded" parser and queues orders.
- **LLM as parser, not as decider.** The LLM emits structured JSON via constrained decoding / function-calling; the rules engine validates against the MKP. Hallucinated items are rejected at the validation layer.
- **Versioned menus.** Every order is stamped with `menu_version_id` so price disputes are auditable.
- **Idempotent submission.** Duplicate POS pushes are deduped via `order_id`.

---

## 8. Database Structure (essentials)

```
restaurants(id, name, brand_voice_id, default_language, currency, timezone)
branches(id, restaurant_id, store_code, address, hours_jsonb, pos_adapter, pos_credentials_secret_id)

menu_versions(id, restaurant_id, version, published_at, status)
categories(id, menu_version_id, name, sort_order)
items(id, menu_version_id, category_id, sku, name, base_price, kitchen_station, calories, allergens[], tags[])
item_aliases(id, item_id, alias, language, weight)             -- nicknames, mispronunciations
modifier_groups(id, menu_version_id, name, min_select, max_select, exclusive)
modifiers(id, modifier_group_id, name, price_delta, default_flag, sku)
item_modifier_bindings(item_id, modifier_group_id, required, ask_order)

combos(id, parent_item_id, slot_definition_jsonb)
promotions(id, menu_version_id, type, conditions_jsonb, effect_jsonb, starts_at, ends_at)
availability(id, branch_id, item_id, available, reason, until)

upsell_rules(id, restaurant_id, trigger_jsonb, offer_item_id, copy, priority)

orders(id, branch_id, lane_id, menu_version_id, channel, language, subtotal, tax, total, status, created_at, pos_external_id)
order_items(id, order_id, item_id, qty, size, base_price, line_total, special_instructions)
order_item_modifiers(id, order_item_id, modifier_id, price_delta)

sessions(id, lane_id, started_at, ended_at, transcript_uri, audio_uri, takeover_at)
transcripts(id, session_id, role, text, confidence, ts)
audio_segments(id, session_id, s3_uri, ts_start, ts_end)

users(id, restaurant_id, role, email)                          -- admin / manager / crew
analytics_events(id, restaurant_id, branch_id, type, payload_jsonb, ts)
```

PII (audio) retention is configurable per tenant for GDPR/PDPL compliance.

---

## 9. Admin Dashboard Features

### For store/brand managers
- Live lane view: current transcript, current cart, order timer, confidence meter, **Take Over** button.
- Menu editor: items, modifiers, combos, prices, photos, aliases, allergen flags, drag-and-drop ordering.
- 86-list / availability toggles (per-branch, per-item, per-time).
- Promotions builder (visual rule builder, no code).
- Upsell rules builder.
- Brand voice settings (greeting, pace, language priority, formality slider).
- Hours, dayparts, holiday overrides.

### For ops / analytics
- Order accuracy %, intent-recognition %, takeover rate, average lane time, upsell attach rate, AOV uplift, item-level drop-off (where customers abandon).
- Per-language performance.
- Failed-order review queue with audio + transcript side-by-side.
- A/B testing for prompts and upsell copy.

### For HQ / chains
- Multi-branch rollout console.
- Permission scopes (brand-admin, region, branch).
- Compliance / audit logs.

---

## 10. Customer-Facing Screen Design

Layout (top to bottom):
1. **Brand header** (logo, lane number).
2. **Live AI bubble** ("I heard: 1x Spicy Chicken Meal — large, no mayo").
3. **Cart panel** with each line item, quantity, modifiers, price; updates within 300 ms of speech.
4. **Subtotal / tax / total** in large type, in local currency.
5. **Promotions strip** (rotating, only relevant ones).
6. **Status indicator**: Listening / Thinking / Confirmed.
7. **Allergy & dietary callouts** when relevant.

Design rules: high-contrast for outdoor sun, no animations during listening, max 3 lines of text per item, accessible font sizes (≥ 24 px effective), works at 720p and 1080p.

---

## 11. Voice System Design

| Layer | Component | Notes |
|---|---|---|
| Capture | Beam-forming mic + AEC + noise suppression | Cancels engine, kid noise, music |
| ASR | Streaming, restaurant-biased LM | Inject menu vocabulary as boost list |
| VAD | Two-stage (energy + neural) | Detects barge-in within 120 ms |
| NLU | LLM with function-calling, schema-constrained | Emits structured slots |
| Dialogue | Deterministic FSM + slot tracker | LLM does NOT control flow |
| TTS | Brand-tuned voice (cloned w/ consent or licensed) | Cached canned phrases for greetings & confirmations to cut latency |
| Bargein | Yes — TTS ducks instantly when VAD fires | Crew-employee feel |

**Latency budget** (target end-to-end):
- ASR partial → screen update: < 300 ms
- End of customer turn → AI speaks: < 700 ms
- Confirm to POS push: < 500 ms

**Multilingual:** code-switching enabled (English/Arabic/Hindi/Urdu/Tagalog/French/Spanish). Detection per utterance. Reply language follows customer's last utterance unless brand pins a language.

---

## 12. Order Validation Logic

Every cart change is run through a deterministic validator before it appears on screen:

1. **Item exists** in current `menu_version` and is `available` at this `branch` at this time.
2. **All required modifier groups** have been satisfied (or are pending — the dialogue manager will ask).
3. **Modifier exclusivity / min-max** rules respected.
4. **Promotion eligibility** evaluated.
5. **Price recalculated** server-side — never trust the LLM with arithmetic.
6. **Allergy flags** copied to the order if the customer mentioned any.
7. **Final cart hashed**; the AI reads back from the hash. If hash changes after summary, re-confirm.

If validation fails, the AI says "I don't see that on the menu, did you mean X or Y?" — never "added" something that doesn't exist.

---

## 13. Human Takeover Process

### Triggers (any one fires takeover)
- Two consecutive low-confidence parses.
- Customer says "manager", "person", "human", or local equivalents.
- Customer raises voice (sentiment + prosody).
- Allergy mention + customer asks for safety guarantee.
- Payment-related dispute.
- Repeated correction on the same item.
- Network failure / POS error.

### Flow
1. AI says, "One moment, connecting you to a team member."
2. Manager tablet rings; manager taps **Take Over**.
3. Two-way voice opens between manager and lane; AI mutes but keeps transcribing.
4. Manager can edit the cart on screen during the call.
5. Manager taps **Return to AI** or **Submit & Close**.
6. Session is flagged for QA review.

A target metric: **takeover rate < 5%** in a healthy deployment.

---

## 14. Multilingual Strategy

- **Tier 1 launch:** English, Arabic (MSA + Gulf), Hindi.
- **Tier 2:** Urdu, Tagalog, French, Spanish.
- **Code-switching:** the LLM is instructed and the ASR is configured to accept mixed-language utterances (e.g., "Give me wahed shawarma meal kbeer please").
- **Per-brand language pinning:** some chains require all replies in Arabic; configurable.
- **Menu localization:** every item supports `name_i18n` and aliases per language.
- **TTS voices:** native-quality voice per language; same brand persona where possible.

---

## 15. Allergy & Safety Handling

- The AI **never** guarantees zero cross-contamination unless the brand has an explicit configuration flag for an allergen-free kitchen.
- On any allergy mention:
  1. Allergy is parsed and attached to the order as a structured flag.
  2. AI says a brand-approved safety script.
  3. KDS ticket prints the allergy in red.
  4. If the brand has a strict allergy SOP, takeover is auto-triggered.
- The AI never gives medical advice and is filtered against off-topic claims by a safety classifier.

---

## 16. Business Model

| Tier | What's included | Indicative pricing (for plan, not commitment) |
|---|---|---|
| **Starter** (1 lane, 1 brand) | SaaS only, BYO hardware, receipt-printer integration | $299–$599 / lane / month |
| **Growth** (multi-branch) | Hardware bundle leased, full POS adapter, dashboard | $799–$1,499 / lane / month + $1k setup |
| **Enterprise** (chains/franchise) | SLAs, custom POS adapter, dedicated CSM, sandbox | Negotiated; often setup fee + monthly + usage |
| **Per-order** | Optional alternative for low-volume sites | $0.05–$0.15 / completed order |
| **Upsell rev-share** | Brands that prefer outcome pricing | 15–25% of measured upsell uplift |

**Unit economics target:** payback < 9 months on hardware, > 70% gross margin on software.

**Value prop math (illustrative):** if AI saves 0.8 FTE per shift × 16 hr × $5/hr = $64/day × 30 = ~$1,920/month/lane in labor displacement, plus 5–8% AOV uplift via consistent upselling. Pricing must sit comfortably below that.

---

## 17. Competitive Advantage

1. **Menu intelligence over chat intelligence.** We model menus as structured graphs, not prose. Hallucinations are blocked at the validator.
2. **Edge-first latency.** Most competitors round-trip everything to the cloud. We don't.
3. **Receipt-printer fallback** lets us land in stores that don't have a modern POS API — huge in emerging markets.
4. **Multilingual + code-switching by default** — critical for GCC, India, SEA.
5. **Outcome-priced tier** (rev-share on upsells) lowers buyer risk.
6. **Operator-grade dashboard** built for crew managers, not data scientists.
7. **Hardware + software** as a single SKU shortens procurement.
8. **Compliance-first** logging, retention, PDPL/GDPR posture.

---

## 18. MVP Scope

**Goal of MVP:** prove that one real restaurant, one lane, can run a full lunch shift on LaneAI with takeover ≤ 10%, accuracy ≥ 95%, and lane time ≤ a human baseline.

### MVP feature set
- Single brand, single store.
- Menu uploaded via CSV/JSON + simple web editor.
- Streaming ASR (off-the-shelf), English only.
- Slot-filling NLU using LLM with function-calling.
- Deterministic dialogue FSM, hard-coded canonical flow.
- Customer screen (web app on edge box).
- Live transcript + cart panel.
- Order summary + confirmation.
- Order delivery via **receipt printer** + email of structured JSON to manager.
- Manager tablet with Take Over button (two-way audio bridge).
- Basic admin dashboard: menu CRUD, 86-list, live lane view.
- Audio + transcript logging to S3.
- Hardware: edge mini-PC + USB mic/speaker + outdoor display + tablet.

### Explicitly out of MVP
- POS API integrations (printer fallback only).
- Promotions builder (hard-coded for MVP brand).
- Multilingual.
- Advanced analytics.
- Inventory sync.
- Multi-branch.
- Brand-cloned TTS.

### MVP success criteria (after a 4-week pilot)
- ≥ 95% intent recognition.
- ≥ 90% complete-order accuracy at-window.
- ≤ 10% takeover rate.
- Lane time at or under store baseline.
- NPS from store manager ≥ 7/10.

---

## 19. Example Structured Order JSON

```json
{
  "order_id": "DT-10294",
  "session_id": "sess_01HM...",
  "channel": "drive_thru",
  "lane_id": "L1",
  "store_id": "DXB-001",
  "menu_version_id": "mv_2026_05_01",
  "customer_language": "en",
  "items": [
    {
      "line_id": 1,
      "item_id": "burger_001",
      "name": "Spicy Chicken Burger Meal",
      "quantity": 1,
      "size": "large",
      "base_price": 32.0,
      "modifiers": [
        { "modifier_id": "no_mayo", "name": "No Mayo", "price_delta": 0 },
        { "modifier_id": "extra_cheese", "name": "Extra Cheese", "price_delta": 3 }
      ],
      "children": {
        "side": { "item_id": "fries_lg", "name": "Large Fries" },
        "drink": { "item_id": "coke_lg", "name": "Large Coke" }
      },
      "special_instructions": "No mayo, extra cheese",
      "allergy_flags": [],
      "kitchen_station": "grill"
    }
  ],
  "promotions_applied": [],
  "subtotal": 35.0,
  "tax": 1.75,
  "total": 36.75,
  "currency": "AED",
  "payment_status": "pending",
  "order_status": "confirmed",
  "ai_confidence": 0.97,
  "takeover": false,
  "created_at": "2026-05-04T19:42:11Z"
}
```

---

## 20. Example Conversations

### 20.1 Burger restaurant (golden path)
- **AI:** "Welcome to Burger Lab, what can I get started?"
- **Customer:** "Spicy chicken meal, large, no mayo, extra cheese, with a Coke."
- **AI:** *(screen updates immediately)* "Got it — large spicy chicken meal, no mayo, extra cheese, with Coke. Anything else?"
- **Customer:** "That's it."
- **AI:** "Want to make it a combo with a chocolate shake for 8 dirhams more?"
- **Customer:** "No thanks."
- **AI:** "All good. That's one large spicy chicken meal, no mayo, extra cheese, Coke. Total is 36.75. Confirm?"
- **Customer:** "Yes."
- **AI:** "Thanks, please pull forward to the next window."

### 20.2 Coffee shop with edits
- **AI:** "Welcome to Bean & Co, what can I get?"
- **Customer:** "Iced latte, oat milk, less ice."
- **AI:** "What size?"
- **Customer:** "Medium."
- **AI:** "Medium iced latte, oat milk, less ice. Anything else?"
- **Customer:** "Actually make it large, and add a croissant."
- **AI:** *(screen updates: size→large, +1 croissant)* "Large iced latte, oat milk, less ice, plus one croissant. Total 28 dirhams. Confirm?"
- **Customer:** "Yes."

### 20.3 Out of stock
- **Customer:** "Chocolate milkshake."
- **AI:** "We're out of chocolate today — vanilla or strawberry?"
- **Customer:** "Vanilla."
- **AI:** "One vanilla shake. Anything else?"

### 20.4 Allergy mention
- **Customer:** "I'm allergic to peanuts. Is the brownie safe?"
- **AI:** "I'll flag the peanut allergy on your order. Our brownie is made in a kitchen that handles nuts, so please confirm with the team at the window before eating. Want me to add it or skip it?"

### 20.5 Mixed English-Arabic (UAE)
- **Customer:** "Wahed shawarma kbeer, garlic sauce, no pickles, w Pepsi small."
- **AI (Arabic-English):** "تمام — one large chicken shawarma, garlic sauce, no pickles, and a small Pepsi. شي ثاني؟"
- **Customer:** "بس."
- **AI:** "المجموع 27 درهم. أكد؟"

### 20.6 Pizza with multiple changes
- **Customer:** "Two large pizzas, one pepperoni thin crust, one veggie classic crust extra cheese."
- **AI:** "Got it — large pepperoni thin crust, and large veggie classic crust with extra cheese. Any sides or drinks?"
- **Customer:** "Add garlic bread, and make the veggie one without onions."
- **AI:** *(updates line 2: -onions; +garlic bread)* "Updated. Anything else?"

### 20.7 Unclear speech
- **Customer:** *(mumbled)* "...two...chicken..."
- **AI:** "Sorry, I didn't catch that — was that two spicy chicken sandwiches or two grilled?"
- **Customer:** "Spicy."
- **AI:** "Two spicy chicken sandwiches. Meal or sandwich only?"

### 20.8 Off-topic
- **Customer:** "What's the weather?"
- **AI:** "I can only help with your order. What would you like today?"

---

## 21. Critical Risks & Mitigations

| Risk | Mitigation |
|---|---|
| ASR accuracy in noise / accents | Beam-forming hardware; restaurant-biased LM; per-store fine-tuning on real audio after week 1 |
| LLM hallucinates items / prices | Constrained decoding; validator rejects anything outside MKP; price computed server-side |
| POS integration drift | Daily contract tests against partner sandboxes; receipt-printer fallback always works |
| Allergy liability | Conservative scripts; never guarantee; auto-takeover on strict-SOP brands; legal review per market |
| Privacy / consent (audio recording) | Visible signage; configurable retention; on-device redaction option; PDPL/GDPR DPAs |
| Multilingual confusion | Per-utterance language detection; reply-language pinning option; manual override |
| Power / network outage | Edge-first design; 4G failover; offline degraded mode; retry queue for POS |
| Brand voice mismatch | Brand voice profile + UAT with brand before go-live |
| Long-tail menu edge cases | "Unknown item" path always handed to staff; weekly QA review queue |
| Procurement friction (hardware) | Bundle as a single SKU; financing/lease option |
| Crew resistance | Position as augmentation; takeover one-tap; share upsell bonuses |

---

## 22. Restaurant Onboarding Flow

1. **Discovery call** — assess store layout, POS, lane geometry, peak volume, languages.
2. **Contract & site survey** — power, networking, intercom wiring, display placement.
3. **Menu intake** — ingest current menu (CSV/PDF/POS export); we pre-fill the MKP.
4. **MKP review session** — brand confirms required-slots, modifier orders, upsell rules, brand voice.
5. **POS adapter setup** — sandbox first; if no API, configure printer fallback.
6. **Hardware install** — half-day install per lane.
7. **Synthetic testing** — the system auto-generates 200+ test conversations covering each item, each modifier, each promotion. Brand reviews failures.
8. **Shadow mode (1 week)** — AI listens but staff still takes orders; we measure parity.
9. **Co-pilot mode (1 week)** — AI takes orders, staff approves before submission.
10. **Full live (1 week pilot)** — measured against MVP success criteria.
11. **Tuning & sign-off.**
12. **Roll-out to additional branches** with a templated MKP.

---

## 23. Roadmap: MVP → Scalable Commercial Product

### Phase 0 — Foundation (months 0–3)
- Build menu schema, slot-filling NLU, dialogue FSM, customer screen, manager tablet, audio logging, basic dashboard.
- Run internal demo restaurant (synthetic).

### Phase 1 — MVP Pilot (months 3–6)
- One real pilot brand, one lane, English only, printer fallback.
- Hit MVP success criteria.
- Collect 10–20k real audio samples for tuning.

### Phase 2 — Productization (months 6–12)
- Add Foodics, Toast, Square POS adapters.
- Multilingual (English + Arabic + Hindi).
- Promotions builder, upsell engine, advanced analytics.
- Multi-branch rollout console.
- Brand voice profiles + cloned TTS.
- 5–10 paying brands.

### Phase 3 — Scale (months 12–24)
- Enterprise dashboard, SSO, audit logs, SLAs.
- Inventory sync (real-time 86-list from POS).
- Payment integrations (pay-at-lane).
- Drive-thru analytics suite (lane-time benchmarks, AOV uplift attribution).
- Hardware bundle v2 (smaller, ruggedized).
- Channel partnerships with POS vendors.
- 50–200 brands.

### Phase 4 — Platform (24+ months)
- Open MKP marketplace (templates per cuisine).
- Self-serve onboarding for independents.
- Front-counter / call-center / mobile-app variants reuse the same engine.
- International expansion (GCC → SEA → LATAM → US/EU).

---

## 24. Hard Rules the System Must Follow

**Never:**
- Invent items or prices.
- Confirm unavailable items.
- Submit without explicit customer confirmation.
- Guarantee allergen safety beyond brand-approved scripts.
- Continue after two failed clarifications without takeover.
- Over-talk, repeat itself, or upsell more than the configured cap.
- Compute totals client-side or trust the LLM's arithmetic.

**Always:**
- Validate every item against the live MKP and 86-list.
- Reflect every change on the customer screen within 300 ms.
- Read back the full order before submission.
- Stamp every order with `menu_version_id`.
- Log transcript + audio for QA (subject to retention policy).
- Allow one-tap takeover.
- Surface allergy flags to the kitchen.

---

## 25. Go-to-Market Summary

- **Beachhead segment:** mid-size regional QSR chains (5–50 stores) in the GCC, where labor cost is rising, multilingual demand is acute, and decision-making is faster than global enterprise chains.
- **Wedge offer:** free 4-week pilot in one lane, outcome-priced (we get paid only on measured AOV uplift + accuracy).
- **Land:** one lane, one shift. **Expand:** all lanes, all branches, then upsell analytics + payments.
- **Channel partners:** POS vendors (Foodics in MENA), kitchen-equipment distributors, drive-thru hardware integrators.
- **Moats over time:** proprietary menu corpus, restaurant-tuned ASR, brand-voice library, integration breadth, deployment playbook.

---

*End of blueprint. This document is intended as a working founder-level brief; it should be paired with a financial model, a technical RFC per subsystem, and a brand-by-brand MKP before any commercial commitment.*
