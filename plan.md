# Everyday Strength Program: Plan

Status: proposal, nothing built yet · Written 2026-11-24

This plan changes the workout program so that it trains what a Tamil woman aged 50–60 needs day to day, and so that the Everyday Strength Check benchmark (`Everyday Strength Check – Benchmark Protocol.md`) measures it. It covers:

- New movement types
- New exercise ladders
- A new 3-day template, with a draft 4-day template
- Rest times
- Safety rules
- The benchmark test in the app, with its scoring
- The data and code changes, phase by phase

Each section ends with the decisions that are still open.

---

## 1. Problem statement

### 1.1 Who it's for

The core client is a Tamil woman aged 50–60. She is usually post-menopausal and new to strength training. Common for her:

- **Joints:** knee osteoarthritis, and knee, shoulder or back pain. Both 50-year-old clients on file today have knee OA and flag knee, shoulder and back pain.
- **Bones and muscle:** low bone density or osteoporosis, low vitamin D, and muscle loss.
- **Health conditions:** type 2 diabetes and high blood pressure, both common in Tamil Nadu.
- **Pelvic floor:** leaking urine after menopause or several childbirths, which is rarely talked about.

Her day asks her to:
- Sit on the floor and get up again, for meals, pooja and kolam.
- Climb stairs, temple steps and bus steps.
- Carry vegetables, a water can or a grandchild, often on one side.
- Reach overhead to clothes lines and shelves.
- Lift vessels, buckets and bags from the floor.
- Stand for long stretches while cooking.

### 1.2 What the program does today

- **Templates:** two fixed day templates (`DAY_TEMPLATES` in `agents/prompts_v1.py`).
  - 3-day: Day 1 is Hinge, Push H, Pull V and Rotation. Day 3 is Squat, Pull H, Push V and Carry. Day 5 is Lunge, Hinge, Carry and Rotation.
  - Cardio on days 2, 4 and 6 (`backend/cardio.py`).
- **Movement types:** 7 (squat, hinge, lunge, push, pull, rotation, carry). The library has 66 exercises; all are bodyweight or resistance-band.
- **Sets:** 3 per main (dominant) slot and 2 per extra slot. The starting reps come from her experience level.
- **Progression** (`_compute_progressed_reps`):
  - Easy (RPE 6): +1 rep, or +5 s, on every set straight away.
  - About right (RPE 8): +1 on one set at a time, only after she hits the same targets two weeks in a row.
  - Too difficult (RPE 10): −1.
  - **Moving to a harder exercise:** when every set is at the exercise's `max_reps` and she earns another step, she swaps to its progression link at that exercise's `min_reps`.
  - **Moving to an easier exercise:** when a target falls below `min_reps`, she swaps to the "lack of strength" regression at its `max_reps`.
- **Rest:** a fixed 60 s between sets and 90 s between exercises for every exercise (`frontend/src/constants.ts`). The "Exercise Complete!" feedback screen adds another 20–40 s between exercises.
- **Cardio:** a 10-exercise low-impact circuit that starts at 1 round × 30 s, about 5 minutes of work.

### 1.3 Gaps found

**Against the benchmark.** Expected change in 8 weeks if nothing changes:

| Test | What trains it today | Chance of a meaningful change |
|---|---|---|
| Saree balance | Nothing direct. Lunges are often the "Assisted" versions. | Low |
| Kolam sit-and-rise | Box squats and bridges; no floor transitions or hip mobility | Low to moderate |
| Chair stand | Sit-to-stands and squats, once a week | Good |
| Temple steps | Lunges once a week, small cardio dose; no step-ups in the library | Moderate |
| Market bag carry | The "Carry" slot holds planks; nothing is carried; no grip work | Low to moderate |

**Against her daily life (high priority):**

1. **Overhead strength.** "Push (Vertical)" only has pike push-ups, which are hard on the wrists and shoulders. One client with a shoulder pain flag is prescribed Feet-Elevated Push-ups and wall pike push-ups.
2. **Bone loading.** All loads are low with no impact, so there is almost no stimulus for bone.
3. **Hip strength for knee osteoarthritis.** There is no hip abduction work at all.
4. **Lifting from the floor.** Every hinge is unloaded; she never practises lifting a bucket or a child.
5. **Walking.** About 5 minutes of cardio three times a week, against a guideline of about 150 minutes a week. There's no post-meal walking.
6. **Pelvic floor.** Nothing.

**Program-level gaps:**

- Each leg pattern comes up only once a week on the 3-day plan, and 4 of its 11 slots are push or pull.
- Progression moves slowly through wide rep ranges: at "about right", roughly one 5 s or 1-rep step a month.
- The rest times are the same for every exercise.
- Intake has no medical screening; every profile has `medical_clearance_obtained: false`.
- `search_exercises_by_movement` doesn't filter on `on_board`, so exercises taken off the board can still be prescribed.

---

## 2. Goals and non-goals

**Goals**
- Every test in the benchmark has a direct training ladder.
- All six high-priority daily-life gaps are trained on the strength days.
- Knee-heavy work is trained about 3 times a week and bend-from-the-hips work twice.
- Sessions stay within 40 minutes.
- Progression rules stay as they are. New ladders are built so the current rules move her through them fast enough for an 8-week cohort.

**Non-goals (for now)**
- No changes to the progression algorithm.
- Mid-workout pose estimation and camera counting are later work (see §8.6).
- Rotation exercises stay in the library and the 4-day plan, but leave the 3-day plan.

---

## 3. New movement types

The plan builder fills each slot by `movement_type` and `dominant` (`WorkoutRepository.get_exercises_by_movement`). Distinct slots therefore need distinct types.

| Movement type | Slot(s) | Dominant | Purpose |
|---|---|---|---|
| `balance` | Balance | false | Single-leg balance (saree balance test) |
| `floor_transfer` | Sit-and-rise | false | Getting down to the floor and up (kolam test, fall recovery) |
| `step` | Step-up | true | Stairs and bus steps (temple steps test), bone loading |
| `lift` | Floor lift | true | Lifting loads from the floor with a bent-knee hinge |
| `hip_abduction` | Hip side | false | Side-hip muscles for knee osteoarthritis, balance and falls |
| `impact` | Heel drops | false | Bone loading |
| `pelvic_floor` | Pelvic floor & core | false | Pelvic floor, breathing and deep core |
| `core` | (4-day plan, coach use) | false | Planks, dead bug and side plank moved here out of `carry` |

**Changed meaning:**
- `carry` now means only exercises that are actually carried. Move the 6 plank-type rows to `core`: standing wall plank, Knee plank, full plank, Side Plank, Dead-Bug, Long lever plank.
- **Push (Vertical)** keeps its type (`push`, vertical). The pike push-ups move off the board, and the shoulder-friendly overhead press ladder (§4.4) is added under `push` vertical.

**Code that lists movement types and must be updated:**
- The `movement_type` description in `agents/tools/workout_tools.py`.
- The agent prompt in `agents/prompts_v1.py`.
- The Workout Builder board, if it has a fixed list.
- `evaluation/personas.py`.

**Decision:** filter `on_board = true` in `get_exercises_by_movement` so off-board exercises can't be prescribed. Existing plans keep theirs, since progression copies rows.

---

## 4. New exercise ladders

### 4.1 How each ladder works with the current progression rules

**Each level is a fixed target: `min_reps = max_reps`.** With the current rules, that gives:

- **About right (RPE 8):** two weeks at a level, then the next level. Week 1 on a new exercise has no streak; week 2 completes it and triggers the move.
- **Easy (RPE 6):** the next level after one week.
- **Too difficult (RPE 10), or a target missed:** the target drops below `min_reps`, so she moves back to the level below at its fixed target.

So a cohort climbs about 4 levels in 8 weeks, more when things feel easy. **The level she starts at matters more than the climb**, so it comes from her baseline benchmark score (§7.6).

- **Links:** each level links to the next with a `progression` edge and back with a `regression` edge, reason "Lack of strength". Only one of each per exercise.
- **Names:** "Level N …", like the band row and pulldown ladders.
- **Timed levels:** these use `is_time_based = true` and store seconds in `min_reps` / `max_reps`.

### 4.2 New per-side column

Several levels are done on each leg or each side. Add **`exercises.per_side` (bool, default false)**:

- The timed screen runs the hold on the left, a 5 s switch, then the right.
- The rep screen says "each leg".
- One logged value per set: the lower of the two sides. With manual entry she logs the side she found harder.

### 4.3 Equipment

The new ladders use household items: a chair, a step, bags, 1-litre water bottles, a towel and a cushion. Two options:

- **A (simpler):** tag them `bodyweight` and put the item in the name and `avoid_if` / notes.
- **B (cleaner):** add an `equipment` row "household items", and make sure the agent's equipment guardrail treats it as always available.

**Recommended: B.**

### 4.4 The ladders

Joints listed are what each exercise loads (`exercise_loaded_joints`); they drive the joint-pain adjustment. "Cap" is the highest level allowed for a health flag (§6).

#### Ladder 1: Balance (`balance`, timed, per side, 2 sets)

| Level | Name | Target | Notes |
|---|---|---|---|
| 1 | Level 1 Single-leg stand, both hands on wall | 20 s | Standing foot flat, the other foot just off the floor |
| 2 | Level 2 Single-leg stand, fingertips on wall | 20 s | |
| 3 | Level 3 Single-leg stand, arms folded | 20 s | The test position, beside the wall |
| 4 | Level 4 Single-leg stand, arms folded | 30 s | |
| 5 | Level 5 Single-leg stand, arms folded | 45 s | Test maximum |
| 6 | Level 6 Single-leg stand, arms folded, slow head turns | 30 s | |
| 7 | Level 7 Single-leg stand, eyes closed, beside wall | 15 s | Helper nearby the first time |
| 8 | Level 8 Single-leg stand, eyes closed, beside wall | 30 s | |

- **Joints:** ankle (mid), knee (low), hip (low).
- **avoid_if:** frequent dizziness or vertigo → cap at level 2. Osteoporosis with a past fracture → cap at level 2.

#### Ladder 2: Sit-and-rise (`floor_transfer`, reps, 2 sets)

Each level takes away one support, mirroring the test's deductions.

| Level | Name | Target | Notes |
|---|---|---|---|
| 1 | Level 1 Kneel down and up, both hands on a chair | 4 | Folded towel under the knees |
| 2 | Level 2 Half-kneel to stand, one hand on chair | 4 each leg | `per_side` |
| 3 | Level 3 Half-kneel to stand, no hands | 4 each leg | `per_side` |
| 4 | Level 4 Floor sit-and-rise, chair beside her to push up | 3 | Cross-legged sit, chair to rise |
| 5 | Level 5 Floor sit-and-rise, one hand on the floor | 3 | |
| 6 | Level 6 Floor sit-and-rise, one knee down, no hands | 3 | |
| 7 | Level 7 Floor sit-and-rise, no support | 3 | The test movement |

- **Joints:** knee (high), hip (high), ankle (mid); wrist (low) on levels 1, 4 and 5.
- **avoid_if:**
  - Knee or hip replacement → leave the ladder out.
  - Knee pain above 5/10 → cap at level 4.
  - Osteoporosis with a past fracture → leave it out.

#### Ladder 3: Bag carry (`carry`, timed walking, 2 sets)

Weight goes up first, then time. One 1-litre bottle is about 1 kg.

| Level | Name | Target | Notes |
|---|---|---|---|
| 1 | Level 1 Bag carry, 2 bottles each hand | 30 s | Walk between two marks 3 m apart |
| 2 | Level 2 Bag carry, 2 bottles each hand | 60 s | |
| 3 | Level 3 Bag carry, 3 bottles each hand | 45 s | |
| 4 | Level 4 Bag carry, 3 bottles each hand | 90 s | |
| 5 | Level 5 One-bag carry, 3 bottles, each side | 45 s | `per_side`; trains her not to lean, one of the test's stop rules |
| 6 | Level 6 Bag carry, 5 bottles each hand | 60 s | |
| 7 | Level 7 Bag carry, 5 bottles each hand | 120 s | |

- **Joints:** wrist (mid), shoulder (mid), spine (mid), hip (low).
- **avoid_if:** back pain that spreads down a leg → leave it out.
- **Cue:** "pick up and put down by bending your knees".

#### Ladder 4: Overhead press (`push`, vertical, dominant, reps, 3 sets)

Replaces the pike push-ups for this group.

| Level | Name | Target | Notes |
|---|---|---|---|
| 1 | Level 1 Wall slides | 8 | Back and arms against the wall, slide up and down |
| 2 | Level 2 Seated band overhead press | 8 | Band under the seat or feet |
| 3 | Level 3 Seated band overhead press | 12 | |
| 4 | Level 4 Standing band overhead press | 10 | |
| 5 | Level 5 Standing water-bottle press, 2 bottles each hand | 10 | |
| 6 | Level 6 Half-kneeling one-arm bottle press | 8 each arm | `per_side` |

- **Joints:** shoulder (high), elbow (mid), spine (low).
- **avoid_if:** shoulder pain flag → cap at level 3 until she rates it "about right"; acute frozen shoulder → leave it out.

#### Ladder 5: Floor lift (`lift`, dominant, reps, 3 sets)

| Level | Name | Target | Notes |
|---|---|---|---|
| 1 | Level 1 Hip hinge holding a bag, 2 bottles | 8 | Bag held against the thighs, push the hips back |
| 2 | Level 2 Bag lift from a step, 3 bottles | 8 | Bag starts on a step, about 20 cm up |
| 3 | Level 3 Bag lift from the floor, 3 bottles | 8 | Bent knees, flat back |
| 4 | Level 4 Bag lift from the floor, 5 bottles | 8 | |
| 5 | Level 5 Water-can lift from the floor | 8 | A filled 5–10 L can, or two bags |
| 6 | Level 6 One-sided lift, bag beside one foot | 6 each side | `per_side` |

- **Joints:** hip (high), spine (mid), knee (mid), wrist (low).
- **avoid_if:**
  - Back pain that spreads down a leg → cap at level 1.
  - Osteoporosis with a past fracture → cap at level 3.
- **Cue:** breathe out as she stands up.

#### Ladder 6: Step-up (`step`, dominant, reps, 3 sets)

| Level | Name | Target | Notes |
|---|---|---|---|
| 1 | Level 1 Step-up 10 cm, hand on rail | 8 each leg | `per_side` |
| 2 | Level 2 Step-up 15 cm, hand on rail | 8 each leg | |
| 3 | Level 3 Step-up 15 cm, no hands | 8 each leg | |
| 4 | Level 4 Step-up 20 cm, no hands | 8 each leg | |
| 5 | Level 5 Step-up 20 cm, slow 3-second step down | 8 each leg | |
| 6 | Level 6 Step-up 20 cm holding bags, 2 bottles each hand | 8 each leg | |

- **Joints:** knee (high), hip (mid), ankle (mid).
- **avoid_if:** knee osteoarthritis or knee pain → cap at level 3 (15 cm); knee replacement → cap at level 2.

#### Ladder 7: Hip side (`hip_abduction`, reps, 2 sets)

| Level | Name | Target | Notes |
|---|---|---|---|
| 1 | Level 1 Lying side leg raise | 10 each side | `per_side` |
| 2 | Level 2 Standing side leg raise, hand on chair | 10 each side | `per_side` |
| 3 | Level 3 Banded clamshell | 12 each side | `per_side` |
| 4 | Level 4 Banded side steps | 10 each way | |
| 5 | Level 5 Banded side steps, half squat | 10 each way | |

- **Joints:** hip (mid), knee (low).
- **avoid_if:** hip replacement → level 1 only, and only once her surgeon has cleared side-lying.

#### Ladder 8: Heel drops (`impact`, reps, 2 sets)

| Level | Name | Target | Notes |
|---|---|---|---|
| 1 | Level 1 Calf raises, hands on wall | 12 | |
| 2 | Level 2 Heel drops | 10 | Up on toes, drop the heels firmly |
| 3 | Level 3 Heel drops, one leg | 10 each leg | `per_side` |
| 4 | Level 4 Stomp-steps | 10 each leg | Firm marching stomps |
| 5 | Level 5 Mini-hops | 10 | Only for women who are cleared |

- **Joints:** ankle (mid), knee (low).
- **avoid_if:**
  - Osteoporosis or a past fragility fracture → cap at level 3.
  - Knee OA with knee pain, or pelvic floor leaking → cap at level 3.
  - Heel pain (plantar fasciitis) → level 1 only.

#### Ladder 9: Pelvic floor & core (`pelvic_floor`, timed guided set, 2 sets)

| Level | Name | Target | Notes |
|---|---|---|---|
| 1 | Level 1 Pelvic floor breathing, lying | 60 s | Breathe in and relax; breathe out and gently lift |
| 2 | Level 2 Pelvic floor squeezes, lying | 60 s | 5 s squeeze, 5 s rest, guided |
| 3 | Level 3 Pelvic floor squeezes, sitting | 60 s | Adds quick squeezes |
| 4 | Level 4 Pelvic floor squeezes, standing | 60 s | |
| 5 | Level 5 Squeeze, then breathe out as she stands from a chair | 60 s | Brings the squeeze into daily movements |
| 6 | Level 6 Dead bug with pelvic floor squeeze | 60 s | Takes over from the planks and dead bugs |

- **Joints:** spine (low), hip (low).
- **avoid_if:** none. Pelvic pain or prolapse symptoms → refer her to a women's health physiotherapist.
- **Content:** needs a guided voice in Tamil, with the cues timed to the timer. The copy must be private and respectful.

**Library total:** about 54 new rows.

**Decision:** do the existing squat, lunge, bridge, row, pulldown and push-up ladders stay as they are? Recommended yes, but check that each has exactly one progression and one regression link.

---

## 5. New 3-day template

Cardio stays on days 2, 4 and 6 (`CARDIO_DAYS`). Main slots are 3 sets; extras are 2.

| Slot | Day 1: Stand & Reach | Day 3: Lift & Carry | Day 5: Legs & Balance |
|---|---|---|---|
| Main 1 | Squat: sit-to-stand, stand up fast and sit down slow (`squat`) | Floor lift (`lift`) | Lunge: split squat (`lunge`) |
| Main 2 | Overhead press (`push`, vertical) | Step-up (`step`) | Hinge: glute bridge ladder (`hinge`) |
| Main 3 | Row (`pull`, horizontal) | Push-up, wall or incline (`push`, horizontal) | Pulldown (`pull`, vertical) |
| Extra 1 | Heel drops (`impact`) | Bag carry (`carry`) | Hip side (`hip_abduction`) |
| Extra 2 | Hip side (`hip_abduction`) | Sit-and-rise (`floor_transfer`) | Heel drops (`impact`) |
| Extra 3 | Pelvic floor & core (`pelvic_floor`) | Pelvic floor & core (`pelvic_floor`) | Balance (`balance`) |
| Extra 4 | Balance (`balance`) | | Pelvic floor & core (`pelvic_floor`) |

**Removed from the 3-day plan:** both Rotation slots, the plank-type Carry slots, and the pike push-ups under Push (Vertical).

**Order within a day:** fast or skill work first, while she's fresh; then the other main exercises; then the extras.

**Weekly coverage**

| Need | Where | Times a week |
|---|---|---|
| Knee-heavy work | Sit-to-stand, step-up, split squat | 3 |
| Bend-from-the-hips work | Floor lift, bridge | 2 |
| Overhead | Press, plus the pulldown's overhead range | 2 |
| Hip abduction | Days 1 and 5 | 2 |
| Bone loading | Heel drops ×2, step-ups, lift, carry, plus cardio heel drops | 5–6 |
| Pelvic floor | Every strength day | 3 |
| Balance / sit-and-rise / carry | Benchmark ladders | 2 / 1 / 1 |
| Horizontal push and pull | Days 3 and 1 | 1 each |

**`DAY_TEMPLATES` shape** (Day 1 as an example):

```python
{
    "day_number": 1, "day_label": "Day 1", "split_name": "Stand & Reach", "is_rest_day": False,
    "primary": [
        {"slot": "Squat", "movement_type": "squat", "dominant": True, "orientation": None},
        {"slot": "Push (Overhead)", "movement_type": "push", "dominant": True, "orientation": "vertical"},
        {"slot": "Pull (Horizontal)", "movement_type": "pull", "dominant": True, "orientation": "horizontal"},
    ],
    "secondary": [
        {"slot": "Heel Drops", "movement_type": "impact", "dominant": False, "orientation": None},
        {"slot": "Hip Side", "movement_type": "hip_abduction", "dominant": False, "orientation": None},
        {"slot": "Pelvic Floor", "movement_type": "pelvic_floor", "dominant": False, "orientation": None},
        {"slot": "Balance", "movement_type": "balance", "dominant": False, "orientation": None},
    ],
},
```

### 5.1 Draft 4-day template (for consistency)

Cardio stays on days 3 and 6.

| Slot | Day 1: Lower A | Day 2: Upper A | Day 4: Lower B | Day 5: Upper B |
|---|---|---|---|---|
| Main 1 | Squat (fast sit-to-stand) | Overhead press | Step-up | Push-up (wall or incline) |
| Main 2 | Floor lift | Row | Split squat | Pulldown |
| Main 3 | — | — | Bridge | — |
| Extra 1 | Hip side | Bag carry | Hip side | Rotation (bird-dog, knee drops) |
| Extra 2 | Heel drops | Sit-and-rise | Heel drops | Core (`core`) |
| Extra 3 | Balance | Pelvic floor & core | Balance | Pelvic floor & core |

**Decision:** keep the 4-day plan as it is until the 3-day version has run with one cohort?

### 5.2 Changes to the cardio circuit

- Add two clips to `cardio_exercises`: **Step-ups on the bottom stair** and **Heel drops**. Add heel drops in place of "Arm reaches" or on top of it; adding is recommended. This puts bone loading and stair practice on cardio days too.
- Cardio progression is unchanged.

---

## 6. Safety rules

### 6.1 Medical screening at intake

The coach's intake step (`/admin` → profile) and the benchmark's safety screen ask the same questions. Store the answers in **`user_profiles.health_screen` (jsonb)**:

| Question | Stored as | Effect on the program |
|---|---|---|
| Heart condition, or chest pain when active? | `heart` | Block plan creation until the doctor has cleared her (`medical_clearance_obtained`) |
| Dizzy, faint or vertigo often? | `dizzy` | Balance capped at level 2; sit-and-rise beside a chair |
| BP above 160/100 or uncontrolled? | `bp_uncontrolled` | Block until controlled. Controlled high BP → `bp_controlled` |
| Surgery, fracture or joint injury in 6 months? | `recent_injury` + joint | Becomes a `user_joint_pain` row (severe) for that joint |
| Knee or hip replacement? | `replacement` + joint | Sit-and-rise left out; step-up capped at level 2 |
| Knee or hip pain above 5/10 most days? | `joint_pain_high` | Sit-and-rise capped at level 4; step-up at level 3 |
| Osteoporosis with a past fracture? | `osteoporosis_fracture` | Heel drops capped at level 3; sit-and-rise left out; floor lift capped at level 3; balance at the wall |
| Diabetes with insulin or tablets that can cause low sugar? | `hypo_risk` | Snack reminder before workouts; sugar-nearby note on the start screen |
| Back pain spreading down a leg? | `sciatica` | Carry left out; floor lift capped at level 1 |
| Leaking urine on coughing, lifting or jumping? | `pelvic_floor_symptoms` | Heel drops capped at level 3; pelvic floor ladder kept; a private tip shown |

### 6.2 Where the caps are applied

The caps are enforced in code, not left to the agent.

- **Plan creation and progression:** after the slot is filled or progressed, if the exercise's level is above the woman's cap for that ladder, swap down to the capped level (walking the regression links).
- **Where it lives:** a new helper `apply_level_caps(user, items)` in `workout_plan_repository.py`, called from `create_plan`, `create_progressed_plan` and the admin initial plan.
- **What it needs:** each ladder exercise has `ladder` and `ladder_level` columns (§8.1), so a cap is just "ladder X ≤ level N".

### 6.3 Workout cues

- Every set of a main exercise shows "Breathe out as you push or stand up. Don't hold your breath." This matters for blood pressure.
- The start screen for a woman with `hypo_risk` says "Had a light snack? Keep sugar nearby."
- Stop rules are on the rest screen: chest pain, dizziness, breathless to the point she can't speak, sharp joint pain, or nausea.

---

## 7. Benchmark test in the app (Everyday Strength Check)

The full protocol is in `Everyday Strength Check – Benchmark Protocol.md`. This section is the app version of it.

### 7.1 Schedule

| Cohort | Practice (not scored) | Baseline | Mid-point | Final |
|---|---|---|---|---|
| 8 weeks | Day −3 to −2 | Day 0, before the first workout | End of week 4 | Day 55–57 |
| 4 weeks | Day −3 to −2 | Day 0 | — | Day 27–29 |

- **The day before a test** has no strength session; the final week's last strength session is light (§9.3).
- **Time of day:** the same within 2 hours. The app suggests the time she did the baseline.
- **Reminders:** a WhatsApp or app nudge for each date, plus the 48-hour no-hard-workout rule.

### 7.2 Session flow (about 20 minutes, fixed order)

1. Safety questions (1 min), from `health_screen` (§6.1), with the answers confirmed again. Any "yes" removes the affected tests.
2. Setup check: chair height, step height, bag load, and the arm and support method saved at baseline (shown at every retest).
3. Warm-up (5 min): march, arm circles, ankle circles, 5 sit-to-stands, 5 step-ups each leg, one practice of each test.
4. Test 1, Saree balance (3 min) → rest 1 min.
5. Test 2, Kolam sit-and-rise (2 min) → rest 1 min.
6. Test 3, Chair stand (1 min) → rest 2 min.
7. Test 4, Temple steps (1 min) → effort rating 0–10 → talk test → rest 2 min.
8. Test 5, Market bag carry (load check, then up to 3 min).
9. Cool-down (2 min) → results card.

Each test shows a demo video, runs the timer with a spoken countdown in Tamil, then asks for one number.

### 7.3 How each test is scored

| # | Test | What she enters | Raw score |
|---|---|---|---|
| 1 | Saree balance | Best of 2 trials per leg, eyes open (0–45 s); eyes-closed trial (0–30 s) on any leg that reached 45 s | Eyes-open average = (best L + best R) / 2; eyes-closed average over the legs tried (0 if none) |
| 2 | Kolam sit-and-rise | Supports used and wobbles for sitting down and getting up (best of 2 attempts) | Down: 5 − supports − 0.5 × wobbles (min 0). Up: the same. Score = down + up (0–10) |
| 3 | Chair stand | Full stands in 30 s; hands used yes/no | Stands |
| 4 | Temple steps | Step-ups in 30 s; effort rating 0–10; talk test (easy / broken / couldn't); rail touched yes/no | Step-ups (effort and talk kept alongside) |
| 5 | Market bag carry | Load (3 or 5 kg each hand, from the load check); seconds walked (0–180) | Load × seconds (kg·s) |

**A test stopped for safety** records `stopped_for_safety = true` and no score. It is never stored as 0.

### 7.4 Points (each test up to 20, total out of 100)

| Test | Formula | Cap |
|---|---|---|
| Saree balance | eyes-open average ÷ 45 × 16 + eyes-closed average ÷ 30 × 4 | 20 |
| Kolam sit-and-rise | score × 2 | 20 |
| Chair stand | stands ÷ 25 × 20 | 20 |
| Temple steps | step-ups ÷ 20 × 20 | 20 |
| Market bag carry | kg × seconds ÷ 900 × 20 (900 = 5 kg for 180 s) | 20 |

**Everyday Strength Score** = sum of the points from the tests she did.

**Skipped tests** (safety or stopped) are shown as "—". The score is shown out of the tests she did (for example "62 / 80"), so a skipped test doesn't read as a failure. Before / after comparisons only use tests done both times.

Round points to one decimal; round the total to a whole number.

### 7.5 Levels and meaningful change

| Test | Building | Steady | Strong | Champion | Meaningful change |
|---|---|---|---|---|---|
| Saree balance (eyes-open avg s) | < 15 | 15–29 | 30–44 | 45 on both legs | +5 s, or unlocking eyes-closed |
| Kolam sit-and-rise (points) | 0–3.5 | 4–6.5 | 7–8.5 | 9–10 | +1 point |
| Chair stand (stands) | < 12 | 12–16 | 17–21 | 22+ | +2 stands |
| Temple steps (step-ups) | < 10 | 10–14 | 15–19 | 20+ | +2 step-ups, or the same count at 2+ points lower effort |
| Market bag carry (kg·s) | < 180 | 180–359 | 360–539 | 540+ | +20 s at the same load |

- **Change below the "meaningful" line** is shown as **"Holding steady"**, never as a gain.
- **A change in method** (hands used, rail touched, different chair or step height, different load) makes the comparison **"Not comparable"**. The app prevents this by locking the setup at baseline.
- **Recalibrate the bands after the first 50 women**, for example by setting full points at the 90th percentile of baseline scores. Keep the bands in a config table, not in code (§8.2).

### 7.6 Baseline score → starting level

At baseline (and again at the mid-point), set each ladder's starting level from her result. The mid-point may only move a ladder **up**, never down.

| Ladder | Rule |
|---|---|
| Balance | eyes-open avg < 5 s → L1; 5–9 → L2; 10–19 → L3; 20–29 → L4; 30–44 → L5; 45 on both legs → L6; eyes-closed avg ≥ 15 → L8 |
| Sit-and-rise | score 0–2 → L1; 2.5–3.5 → L2; 4–5 → L3; 5.5–6.5 → L4; 7–7.5 → L5; 8–8.5 → L6; ≥ 9 → L7 |
| Bag carry | 3 kg: < 30 s → L1; 30–59 → L2; 60–89 → L3; 90–179 → L4; 180 → L5. 5 kg: < 120 s → L6; ≥ 120 → L7 |
| Step-up | < 10 step-ups or rail used → L1; 10–14 → L2; 15–19 → L3; 20+ → L4 |
| Squat (sit-to-stand) | hands used or < 8 stands → high-chair sit-to-stand; 8–11 → box squat; 12–16 → band-resisted sit-to-stand; 17+ → full bodyweight squat (existing ladder) |

Then apply the safety caps (§6.2). With no benchmark (an older client, or the test was skipped), the agent picks as it does today and caps still apply.

### 7.7 Results card

- For each test: before → after, the change, the level, and "Meaningful gain" / "Holding steady" / "Not comparable".
- Total score before → after.
- A radar chart with five spokes (points per test), before and after.
- Shareable on WhatsApp as an image.
- The coach sees every attempt and the Kolam video in Monitor clients.

### 7.8 What the coach sees

In Monitor clients, a new **Benchmark** card:
- Each test session with its raw numbers, points, level and setup.
- The safety flags.
- The Kolam clip, so the coach can check the deductions and correct the score (stored as the coach's edit).

---

## 8. Data model changes

### 8.1 Exercise library

```sql
-- new movement types
insert into movement_types (name) values
  ('balance'), ('floor_transfer'), ('step'), ('lift'),
  ('hip_abduction'), ('impact'), ('pelvic_floor'), ('core');

-- new equipment
insert into equipment (name) values ('household items');

-- exercise columns
alter table exercises
  add column per_side boolean not null default false,
  add column ladder text,            -- e.g. 'balance', 'sit_and_rise', 'carry', 'overhead_press', 'floor_lift', 'step_up', 'hip_side', 'heel_drops', 'pelvic_floor', 'squat'
  add column ladder_level int2,      -- 1-based place in the ladder
  add column cue text;               -- one line shown during the set (breathing, form)

-- carry now means carried things only
update exercises set movement_type_id = (select id from movement_types where name = 'core')
 where id in (58, 59, 60, 61, 62, 70);
```

- Pike push-ups (ids 28–35, 71, 72) → `on_board = false`.
- The new rows go in through the Workout Builder board or a one-off seed script with their progression and regression links (§4).
- **Decision:** if the Workout Builder board needs to edit `per_side`, `ladder`, `ladder_level` and `cue`, add them to its form.

### 8.2 Benchmark tables

```sql
create table benchmark_sessions (
  id int4 generated by default as identity primary key,
  user_id text not null references user_profiles(user_id) on delete cascade,
  kind text not null check (kind in ('practice', 'baseline', 'midpoint', 'final')),
  scheduled_for date,
  started_at timestamptz,
  completed_at timestamptz,
  setup jsonb,          -- chair_cm, step_cm, carry_kg, arm_position, hands_used, rail_touched, chair_beside
  screen jsonb,         -- the safety answers given that day
  total_points numeric(5,1),
  max_points int2,      -- 20 × tests done
  created_at timestamptz default now()
);

create table benchmark_results (
  id int4 generated by default as identity primary key,
  session_id int4 not null references benchmark_sessions(id) on delete cascade,
  test text not null check (test in ('balance', 'sit_rise', 'chair_stand', 'step_up', 'carry')),
  status text not null check (status in ('done', 'skipped_safety', 'stopped_safety')),
  raw jsonb,            -- per test: trials, supports, wobbles, effort, talk, load, seconds
  score numeric(6,1),   -- raw score per §7.3
  points numeric(4,1),
  level text check (level in ('building', 'steady', 'strong', 'champion')),
  video_path text,      -- Kolam clip in a private bucket
  coach_score numeric(6,1),   -- coach correction, used instead of score when set
  created_at timestamptz default now(),
  unique (session_id, test)
);

create table benchmark_bands (   -- §7.5, editable without a deploy
  test text primary key,
  steady_from numeric, strong_from numeric, champion_from numeric,
  meaningful_change numeric,
  points_formula jsonb
);
```

- A 'final' session's `setup` is pre-filled from the baseline and locked.
- RLS: these tables hold per-user health data. Follow whatever is decided for the other per-user tables (see CLAUDE.md; don't enable RLS without policies).

### 8.3 Other columns

```sql
alter table user_profiles add column health_screen jsonb;          -- §6.1
alter table session_exercises
  add column rest_seconds int2,          -- between sets, §9
  add column rest_after_seconds int2;    -- before the next exercise, §9
alter table plans add column is_taper boolean not null default false;  -- final-week light plan, §9.3
```

---

## 9. Rest times

### 9.1 Between sets, by exercise type

Set when the plan is created, from the slot's type. Stored on `session_exercises.rest_seconds` and copied forward by progression.

| Type | Exercises | Now | New |
|---|---|---|---|
| Fast / power | Fast sit-to-stand, step-up | 60 s | **90 s** |
| Main lower body | Floor lift, split squat, bridge, squat | 60 s | **75 s** |
| Main upper body | Overhead press, row, push-up, pulldown | 60 s | **45 s** |
| Carry | Bag carry | 60 s | **60 s** |
| Sit-and-rise | Floor transfer | 60 s | **45 s** |
| Hip side, heel drops | Abduction, impact | 60 s | **30 s** |
| Balance | Balance | 60 s | **15 s** |
| Pelvic floor & core | Pelvic floor | 60 s | **15 s** |

**Automatic extra:** +15 s on main exercises when `health_screen` has `bp_controlled`, a heart risk factor in the profile, or she is 55 or older.

### 9.2 Between exercises

Stored on `session_exercises.rest_after_seconds`. The feedback screen already adds rest, so the base is shorter than today's 90 s.

| From → to | Rest |
|---|---|
| Default | 45 s |
| Main lower → main lower (e.g. floor lift → step-up) | 75 s |
| Next exercise needs setup (bags, step, chair, floor) | 60 s, and the rest screen says what to get ready |
| After she rates an exercise "too difficult" | +30 s on top |

### 9.3 Rest screen and taper

- **`RestTimerScreen`:** add **+30 s** and **Skip rest** buttons, and say what's next ("Next: Bag carry, get two bags with 3 bottles each").
- **Log the rest she takes:** a new table `session_exercise_rest_logs` (`session_exercise_id`, `after_set`, `planned_seconds`, `actual_seconds`, `extended`, `skipped`) or a jsonb column. The AI Coach context gets "rest extended on N of M sets".
- **Taper:** the plan whose week contains the final benchmark is created with `is_taper = true`. Every set count is cut by one (minimum 1), there's no level-up, and the last strength session is at least 48 h before the test date.
- **Phase 2 (optional):** alternating pairs (a set of A, a set of B) to cut 4–5 minutes. This needs changes to the workout screens.

### 9.4 Time check (Day 1)

| Part | Minutes |
|---|---|
| Sit-to-stand, fast (3 sets) | ~5 |
| Overhead press (3 sets) | ~3.5 |
| Row (3 sets) | ~3.5 |
| Heel drops, hip side, balance, pelvic floor | ~8 |
| Rests between exercises, plus feedback screens | ~8 |
| Warm-up and cool-down videos | ~8 |
| **Total** | **~36** |

---

## 10. Related changes outside the workout plan

- **Post-meal walk:** the WhatsApp meal feedback (`voice_processor/meal_feedback.py`) adds one fixed Tanglish line after lunch and dinner ("saapitta apram 10 nimisham nadakkunga"). It's free, since it's in a message already sent. Optional later: a "walked?" tap in the app, counted on the dashboard.
- **Calcium on the Food screen:** `nutrients` already holds `calcium_mg` and `vitamin_d_mcg`. Add calcium to her Daily Goal card, with a target of 1000–1200 mg for women over 50, and to the meal feedback flags. Protein per meal is a later step.
- **Menopause notes:** let the feedback agent (`feedback_prompts.py`) use the category `other` for hot flashes, poor sleep and joint pain. Possibly a new category `menopause`.
- **The period prompt** still applies to women who menstruate. Skip it for women whose `health_screen` says post-menopausal.

---

## 11. Code changes, file by file

### Backend / agents
| File | Change |
|---|---|
| `agents/prompts_v1.py` | New 3-day (and later 4-day) `DAY_TEMPLATES`. Prompt: new movement types, start from the benchmark level when given, never pass a cap. The exception: ladder exercises use their fixed target, not the experience-anchor reps formula (`min_reps` = `max_reps` makes the formula return it anyway). |
| `agents/tools/workout_tools.py` | Update the `movement_type` list. Return `per_side`, `ladder`, `ladder_level`, `cue`. |
| `backend/repository/workout_repository.py` | `get_exercises_by_movement`: filter `on_board = true`; select the new columns. |
| `backend/repository/workout_plan_repository.py` | `apply_level_caps`; set `rest_seconds` / `rest_after_seconds` at create time and copy them in `create_progressed_plan`; taper plan; return the new fields on dashboard exercise entries. |
| `backend/cardio.py` | Nothing, unless heel drops get special treatment. |
| `backend/benchmark.py` (new) | Scoring (§7.3–7.5) as pure functions, starting levels (§7.6), comparison (meaningful / steady / not comparable). |
| `backend/controllers/benchmark_controller.py` (new) | `GET /api/users/<id>/benchmark` (sessions and results); `POST /api/benchmark/sessions` (start, with screen and setup); `PUT /api/benchmark/sessions/<id>/results/<test>`; `POST /api/benchmark/sessions/<id>/complete` (scores, sets starting levels); `POST …/<test>/video`. Admin: `GET /api/admin/users/<id>/benchmark`, `PATCH /api/admin/benchmark-results/<id>` (coach score). |
| `backend/controllers/admin_plan_controller.py` | Intake: save `health_screen`; block plan creation on `heart` / `bp_uncontrolled` without clearance. |
| `backend/coach_agent/context.py` | Add ladder level, caps, rest logs and benchmark results to the AI Coach context. |
| `voice_processor/meal_feedback.py` | Post-meal walk line; calcium flag (later). |

### Frontend
| File | Change |
|---|---|
| `frontend/src/constants.ts` | Rest constants become fallbacks only. |
| `ExerciseScreen.tsx`, `TimedExerciseScreen.tsx` | Use `rest_seconds`; `per_side` flow (left → switch → right); show `cue`. |
| `RestTimerScreen.tsx` | +30 s, Skip, "what's next", rest log. |
| `utils.ts` (`restPath` callers) | Use `rest_after_seconds`. |
| `screens/BenchmarkScreen.tsx` (new) | The whole flow in §7.2: screen, setup, demo, timers, number entry, results card, radar chart. |
| `screens/admin/ClientBenchmark.tsx` (new) | Coach card (§7.8). |
| Admin intake | Health screen questions (§6.1). |
| Admin exercise editor | Edit `rest_seconds`. |

### Content to produce
- Demo clips for about 54 new exercises; levels of one ladder can share a clip with different captions.
- Guided Tamil audio for the pelvic floor levels.
- Demo videos for the 5 benchmark tests.
- 2 new cardio clips: step-ups and heel drops.

### Tests
- `backend/tests/benchmark_test.py`: every formula, cap, band edge, comparison, skipped and stopped tests.
- Progression tests for the fixed-target ladders: 2 weeks at about right, 1 week easy, too difficult drops a level, caps hold after a level-up.
- Template tests: every slot type has at least one on-board exercise.

---

## 12. Rollout

1. **Phase 1: library and template (no UI changes).** Movement types, columns, the ~54 exercises and links, the `on_board` filter, the new 3-day template, level caps. New clients get it straight away. Rest times still come from the constants.
2. **Phase 2: rest and per-side.** `rest_seconds` / `rest_after_seconds`, rest screen buttons and log, the `per_side` flow, cues.
3. **Phase 3: benchmark.** Tables, scoring, app flow, results card, coach card, starting levels from baseline, taper week.
4. **Phase 4: around the plan.** Health screen at intake, post-meal walk line, calcium, cardio clips, 4-day template.

**Existing clients:** progression copies last week's exercises forward, so they won't pick up the new days on their own. For each one, the coach rebuilds the plan in the `/admin` planner at the start of a week, or a one-off script creates the next plan from the new template with the starting levels. Day numbers stay the same, so the "same day last week" progression comparison still works for the slots that remain.

---

## 13. Open decisions

1. Equipment: tag as `bodyweight` or add "household items" (§4.3)? Recommended: household items.
2. Filter `on_board` in exercise search (§3)? Recommended: yes.
3. Change the 4-day plan now or after one cohort (§5.1)?
4. Period days: should the 70% reduction also apply to balance, pelvic floor and hip side? Recommended: no, only main exercises, carry and step-up.
5. `per_side` logging: the lower side's value, or log both sides (two set logs per set)?
6. Mid-point benchmark: can it move a ladder up only, as proposed, or also down?
7. Benchmark bands: keep the starting estimates until 50 women, then recalibrate (§7.5)?
8. Who confirms the Kolam score: the woman's own count, or the coach from the video?
9. Should a heart or uncontrolled-BP "yes" at intake block plan creation completely, or allow a coach override?

---

## 14. How we'll know it worked

- At least 60% of women who finish the 8 weeks show a meaningful change on 3 or more of the 5 tests.
- No rise in sessions rated "too difficult" or in new joint pain notes compared with the current program.
- Session length stays under 40 minutes (measured from `started_at` to `completed_at`).
- At least 70% of scheduled sessions are completed, the same as or better than today.
