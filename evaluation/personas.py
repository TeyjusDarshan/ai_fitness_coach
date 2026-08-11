"""Synthetic client personas for testing the preprocessor -> workout agent pipeline.

Each persona is free-form first-person text in the same style as
`agents.preprocessor_agent.SAMPLE_RAW_TEXT` — feed `raw_text` into
`generate_workout_plan_from_text` (or `generate_user_profile` alone) and hand
the resulting plan to an LLM judge alongside `judge_focus` for what to check.

Covers 40-60 year old men and women, all complete beginners, split between
clients with musculoskeletal/health limitations (knee pain, back pain,
arthritis, shoulder pain, and combinations) and clients who are fully healthy
and strong for their age with no restrictions.
"""

from typing import Any, Dict, List

PERSONAS: List[Dict[str, Any]] = [
    {
        "persona_id": "female_50_osteoarthritis_knee_shoulder_back",
        "age": 50,
        "sex": "female",
        "category": "health_conditions",
        "judge_focus": [
            "knee-friendly (low-impact, no deep flexion) exercise selection",
            "shoulder-safe pressing/pulling variations",
            "back-safe hinge/loading patterns",
            "strength & muscle-preservation focus appropriate for a beginner",
        ],
        "raw_text": (
            "Hi, I'm a 50-year-old married working woman. My working hours are 10 AM "
            "to 6 PM. My weight is 58 kg. I'm a non-vegetarian. I have osteoarthritis, "
            "so I have knee pain. Sometimes I also get shoulder pain and back pain. "
            "Currently, I'm doing small exercises daily for about 40 minutes every "
            "morning. I've included protein-rich food in my diet chart. I need body "
            "strengthening exercises and exercises to prevent muscle loss. Similarly, "
            "I need exercises that prevent knee pain and shoulder pain, along with "
            "muscle strengthening exercises that don't cause muscle loss. Thank you."
        ),
    },
    {
        "persona_id": "male_55_desk_job_lower_back_pain",
        "age": 55,
        "sex": "male",
        "category": "health_conditions",
        "judge_focus": [
            "spine-sparing exercise choices (no loaded flexion, controlled hinge)",
            "core stability work before heavy compound lifts",
            "beginner-appropriate volume given years of inactivity",
        ],
        "raw_text": (
            "I'm a 55-year-old man, married with two kids, and I work a desk job from "
            "9 to 5 as an accountant. I weigh around 88 kg and I'm about 175 cm tall. "
            "I've never really exercised in my life outside of the occasional walk. "
            "For the last few years I've had chronic lower back pain, probably from "
            "sitting all day - my doctor said it's mild disc degeneration, nothing "
            "surgical, but bending and lifting heavy things sets it off. No knee or "
            "shoulder issues. I eat pretty normally, nothing special, I do like meat "
            "and rice. I want to start exercising to lose some belly fat and build "
            "enough strength that my back stops bothering me every time I pick "
            "something up off the floor. I can train maybe 3 evenings a week after "
            "work, 30-45 minutes, at home - I don't own any equipment yet."
        ),
    },
    {
        "persona_id": "female_45_healthy_no_conditions",
        "age": 45,
        "sex": "female",
        "category": "healthy",
        "judge_focus": [
            "no unnecessary contraindication-driven substitutions",
            "progressive full-body strength programming for a true beginner",
            "reasonable starting volume/intensity without being overly conservative",
        ],
        "raw_text": (
            "I'm a 45-year-old woman, unmarried, self-employed as a graphic designer "
            "so my schedule is flexible. I'm about 62 kg and 160 cm tall. I'm in good "
            "health overall - no injuries, no chronic conditions, no aches that stop "
            "me from doing anything. I'm a vegetarian and eat fairly balanced meals. "
            "I've honestly never done any structured exercise before, just casual "
            "walking sometimes. I'd like to start proper strength training to build "
            "muscle, improve my posture, and generally feel fitter and more energetic "
            "as I get older. I can commit to 4 days a week, about 45 minutes each "
            "session, mornings work best. I have a small home gym with dumbbells and "
            "resistance bands."
        ),
    },
    {
        "persona_id": "male_60_healthy_strong_active",
        "age": 60,
        "sex": "male",
        "category": "healthy",
        "judge_focus": [
            "programming reflects genuinely higher baseline capacity, not treated as fragile",
            "no unwarranted joint restrictions when none were reported",
            "appropriate progression given no formal structured-training history",
        ],
        "raw_text": (
            "I'm a 60-year-old retired man, married, and honestly I feel great for my "
            "age. I weigh 80 kg at 178 cm and I've stayed active my whole life - lots "
            "of hiking, gardening, and I used to play recreational tennis twice a "
            "week until recently. No injuries, no joint pain, no medical conditions, "
            "blood pressure is normal, my doctor says I'm in excellent shape for 60. "
            "I've just never done any real gym-style strength training - always been "
            "cardio and outdoor activity. I want to start lifting to build muscle and "
            "bone density before I get older, since I know that matters more as you "
            "age. I eat a lot of protein already, my wife makes sure of that. I can "
            "train 4-5 days a week, an hour at a time, and I recently joined a gym "
            "with full equipment access."
        ),
    },
    {
        "persona_id": "female_58_knee_shoulder_arthritis",
        "age": 58,
        "sex": "female",
        "category": "health_conditions",
        "judge_focus": [
            "bilateral knee-safe exercise selection (no deep loaded knee flexion)",
            "shoulder impingement-aware upper body pressing/overhead choices",
            "low-impact conditioning options",
        ],
        "raw_text": (
            "I'm a 58-year-old widow, retired last year after working as a school "
            "teacher. I'm around 70 kg and 158 cm. I've been diagnosed with arthritis "
            "in both knees and I also have a rotator cuff issue in my right shoulder "
            "from years of chalkboard writing and grading, so overhead reaching hurts. "
            "No back problems though. I take medication for mild hypertension. I've "
            "never exercised regularly in my life, just housework and gardening. I "
            "want to become stronger and more mobile so I can keep up with my "
            "grandchildren, and I really want to avoid losing more muscle as I get "
            "older. Diet-wise I try to eat healthy, mostly home-cooked food, some "
            "chicken and fish. I can exercise about 3 times a week, 30 minutes, "
            "afternoons, at home - I have a couple of resistance bands and a chair."
        ),
    },
    {
        "persona_id": "male_48_herniated_disc_back_pain",
        "age": 48,
        "sex": "male",
        "category": "health_conditions",
        "judge_focus": [
            "avoids loaded spinal flexion/rotation given a diagnosed disc issue",
            "builds core/hip stability before any heavier hinge loading",
            "beginner-appropriate progression, medical-clearance awareness",
        ],
        "raw_text": (
            "I'm 48, male, married with three kids, and I run a small retail "
            "business so I'm on my feet a lot but not doing anything athletic. "
            "I'm 95 kg and 180 cm tall - I know I need to lose weight. Five years "
            "ago I was diagnosed with a herniated disc in my lower back (L4-L5) "
            "after an incident lifting boxes at the shop. It's manageable now but I "
            "still get flare-ups if I bend and twist carelessly, and my doctor told "
            "me to avoid heavy deadlifting-type movements. No knee or shoulder "
            "problems otherwise. I've genuinely never worked out before, this would "
            "be my first time doing anything structured. I eat a lot of fast food "
            "honestly, trying to change that too. My goal is to lose weight, build "
            "some strength safely, and stop being scared my back will go out every "
            "time I bend over. I can do 3 days a week, 30 minutes, evenings, at home "
            "with no equipment for now."
        ),
    },
    {
        "persona_id": "female_60_osteoporosis_risk_stiffness",
        "age": 60,
        "sex": "female",
        "category": "health_conditions",
        "judge_focus": [
            "bone-density-friendly progressive loading (not overly cautious to the point of no strength stimulus)",
            "avoids high-impact/high-fall-risk movements given balance/stiffness notes",
            "joint-friendly range of motion given general stiffness",
        ],
        "raw_text": (
            "I'm a 60-year-old woman, married, retired from a nursing career. I'm "
            "around 64 kg and 162 cm. My last bone density scan showed early "
            "osteopenia, so my doctor recommended weight-bearing exercise to help "
            "protect against osteoporosis before it gets worse. I don't have arthritis "
            "or any specific joint diagnosis, but I do feel generally stiff, "
            "especially in my hips and lower back in the mornings, and my balance "
            "isn't what it used to be so I'm a little nervous about falling. No "
            "surgeries, no other major health issues, blood pressure is fine. I've "
            "never done strength training, just some walking and stretching at home. "
            "I eat reasonably well and already try to get enough calcium and protein. "
            "I'd like a program that builds real strength and bone health without "
            "anything that feels risky for falling or too jarring on my joints. I can "
            "train 3 days a week, 30-40 minutes, mornings, at home with light "
            "dumbbells and a chair for support."
        ),
    },
    {
        "persona_id": "male_44_healthy_manual_labor",
        "age": 44,
        "sex": "male",
        "category": "healthy",
        "judge_focus": [
            "leverages higher-than-average baseline conditioning appropriately",
            "still treated as a structured-training beginner despite occupational activity",
            "no invented health restrictions",
        ],
        "raw_text": (
            "I'm 44, male, married, and I work as a construction site supervisor, so "
            "I'm physically active all day carrying materials and being on my feet, "
            "but I've never actually followed a real workout program. I'm 90 kg and "
            "182 cm, pretty solidly built from the manual work. No injuries, no pain "
            "anywhere, no medical conditions, I feel strong and healthy overall. I eat "
            "a lot since the job burns a lot of calories, mostly home-cooked meals "
            "with plenty of meat. I want to start proper structured strength training "
            "now to build more muscle and get more defined, rather than just relying "
            "on the incidental activity from work. I can train 4 days a week, about "
            "an hour, evenings after work, and I have access to a full gym near my "
            "site."
        ),
    },
    {
        "persona_id": "female_55_old_shoulder_injury_otherwise_healthy",
        "age": 55,
        "sex": "female",
        "category": "health_conditions",
        "judge_focus": [
            "shoulder-safe overhead/pressing substitutions on the affected side only",
            "no unnecessary restriction of lower body or the unaffected shoulder",
            "beginner-appropriate full-body progression otherwise",
        ],
        "raw_text": (
            "I'm 55, female, divorced, and I work part-time at a pharmacy. I'm 66 kg "
            "and 165 cm. Health-wise I'm doing quite well overall - no back pain, no "
            "knee pain, blood pressure normal. The one issue is my left shoulder - I "
            "fell skiing about eight years ago and tore something in there, it healed "
            "without surgery but I still can't raise that arm all the way overhead "
            "without discomfort, and heavy pressing on that side bothers it. My right "
            "shoulder is completely fine. I've never done weight training, just some "
            "yoga classes here and there over the years. I eat a balanced diet, mostly "
            "vegetarian with occasional fish. My goal is to build overall strength "
            "and muscle tone and improve my fitness for the long run, while being "
            "careful with that left shoulder. I can train 3-4 days a week, 40 minutes, "
            "either morning or evening, and I have dumbbells and resistance bands at "
            "home."
        ),
    },
    {
        "persona_id": "male_50_post_meniscus_surgery_knee",
        "age": 50,
        "sex": "male",
        "category": "health_conditions",
        "judge_focus": [
            "knee-conservative loading given post-surgical history (limited deep flexion/impact)",
            "otherwise full progression for upper body and unaffected areas",
            "medical-clearance / caution language appropriate to a surgical history",
        ],
        "raw_text": (
            "I'm 50 years old, male, married, and I work as a software engineer, so "
            "very sedentary during the day. I'm 92 kg and 176 cm. About two years ago "
            "I had meniscus surgery on my right knee after a jogging injury - it "
            "recovered well but I still avoid deep squatting or anything high-impact "
            "on it since it can ache afterward. No other health issues, no back or "
            "shoulder pain, blood pressure normal. I've basically never exercised "
            "seriously before, this surgery scared me off running and I never "
            "replaced it with anything else. My diet is average, I could eat "
            "healthier. I want to lose weight and build strength, especially in my "
            "legs, without aggravating the knee again, and I'd like to build muscle "
            "generally since I feel like I've gotten weak sitting at a desk all day. "
            "I can train 3 days a week, 30-45 minutes, evenings, and I have a gym "
            "membership with full equipment."
        ),
    },
    {
        "persona_id": "female_47_healthy_sedentary_desk_job",
        "age": 47,
        "sex": "female",
        "category": "healthy",
        "judge_focus": [
            "no fabricated restrictions given a clean health history",
            "appropriate low-starting-volume progression for a sedentary true beginner",
            "posture/desk-job context reflected without inventing a diagnosis",
        ],
        "raw_text": (
            "I'm a 47-year-old woman, married with one teenager at home, and I work "
            "as an HR manager, fully desk-based, 9 to 5. I'm 68 kg and 163 cm. I "
            "don't have any diagnosed health conditions - no arthritis, no back or "
            "knee pain, blood pressure and everything else is normal on my last "
            "checkup. I am quite sedentary though, I basically don't move much "
            "outside of work and errands, and I've never done any structured exercise "
            "in my adult life. I eat okay, try to avoid too much junk food but I'm not "
            "very disciplined about it. I want to start exercising from scratch to "
            "build strength, lose a bit of weight, and just generally feel more "
            "capable in day to day life - carrying groceries, playing with my kid, "
            "that kind of thing. I can do 3 days a week, 30 minutes, mornings before "
            "work, at home with no equipment right now."
        ),
    },
    {
        "persona_id": "male_58_bilateral_knee_arthritis_back_pain",
        "age": 58,
        "sex": "male",
        "category": "health_conditions",
        "judge_focus": [
            "low-impact, knee-friendly lower body exercise selection given bilateral arthritis",
            "back-safe hinge/loading given concurrent lower back pain",
            "muscle-preservation framing appropriate for an older beginner with multiple limitations",
        ],
        "raw_text": (
            "I'm 58, male, married, retired early from a warehouse job that wore my "
            "body down over the years. I'm 84 kg and 174 cm. I have arthritis in both "
            "knees, diagnosed a few years back, and I also deal with chronic lower "
            "back pain most days - nothing surgical, just years of heavy lifting "
            "catching up with me. No shoulder problems though, upper body is fine. "
            "I take medication for cholesterol and mild hypertension. I've never done "
            "any real workout routine, my job was my exercise for 30 years and now "
            "that I'm retired I've become pretty inactive and I can feel myself "
            "losing muscle. I eat decently, my wife cooks mostly home meals with good "
            "protein. My main goals are to stop losing muscle, manage my weight, and "
            "find ways to strengthen my knees and back without causing more pain. "
            "I can exercise 3 days a week, 30 minutes, mornings, at home - I have "
            "resistance bands and a couple of light dumbbells."
        ),
    },
    {
        "persona_id": "female_42_healthy_beginner_toning",
        "age": 42,
        "sex": "female",
        "category": "healthy",
        "judge_focus": [
            "clean progressive beginner programming without unneeded caution",
            "reflects stated goal (toning/muscle definition) without ignoring general strength basics",
        ],
        "raw_text": (
            "I'm 42, female, married with two young kids, and I work part-time as a "
            "freelance writer. I'm 60 kg and 167 cm. I'm healthy overall - no "
            "injuries, no pain, no medical conditions, I get regular checkups and "
            "everything comes back normal. I've genuinely never worked out before "
            "besides some casual walking with the kids. I eat a fairly balanced diet, "
            "nothing extreme. My goal is mainly to tone up, build some visible muscle "
            "definition, and have more energy to keep up with my kids. I'm not "
            "chasing anything extreme, just want to start somewhere sensible and "
            "build consistency. I can train 3 days a week, 30 minutes, whenever the "
            "kids nap or after they're in bed, at home with just a yoga mat and some "
            "light dumbbells."
        ),
    },
    {
        "persona_id": "male_52_hypertension_only_desk_job",
        "age": 52,
        "sex": "male",
        "category": "health_conditions",
        "judge_focus": [
            "cardiovascular-risk-aware intensity progression (no unnecessary high-intensity spikes)",
            "no fabricated musculoskeletal restrictions since none were reported",
            "medical clearance / medication awareness (beta blockers affecting heart rate response)",
        ],
        "raw_text": (
            "I'm 52, male, married, and I work as a bank manager, fully desk-based. "
            "I'm 96 kg and 179 cm. My main health issue is high blood pressure, which "
            "I take medication for - a beta blocker. Other than that I don't have any "
            "joint pain, no back issues, no knee or shoulder problems, my doctor has "
            "cleared me for exercise as long as I don't overdo intensity suddenly. "
            "I've never worked out in my life really, always been busy with work and "
            "family. My diet isn't great, lots of restaurant meals for work lunches. "
            "I want to lose weight, get my blood pressure under better control through "
            "exercise, and build some general strength since I have zero muscle tone "
            "right now. I can train 3 days a week, 30-40 minutes, evenings, at home "
            "with a couple of resistance bands, no other equipment yet."
        ),
    },
]


def get_personas_by_category(category: str) -> List[Dict[str, Any]]:
    """category: 'healthy' or 'health_conditions'."""
    return [p for p in PERSONAS if p["category"] == category]


if __name__ == "__main__":
    healthy = get_personas_by_category("healthy")
    with_conditions = get_personas_by_category("health_conditions")
    print(f"{len(PERSONAS)} personas total: {len(healthy)} healthy, {len(with_conditions)} with health conditions")
    for p in PERSONAS:
        print(f"- {p['persona_id']} ({p['sex']}, {p['age']}, {p['category']})")
