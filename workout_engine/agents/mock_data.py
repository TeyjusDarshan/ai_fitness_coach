SAMPLE_HEART_PATIENT_INPUT = {
    "task": "GENERATE_WEEKLY_MACRO_SPLIT",
    "client_profile": {
        "biometrics": {
            "full_name": "Karthik Subramaniam",
            "age": 52,
            "biological_sex": "Male",
            "height_cm": 172,
            "weight_kg": 84,
            "ethnicity_demographic": "South Asian / South Indian",
        },
        "clinical_status": {
            "primary_diagnoses": [{"condition": "Type 2 Diabetes", "years_since_diagnosis": 4}],
            "medications": [{"name": "Metformin", "dosage_timing": "Daily"}],
            "medical_clearance_constraints": "Cleared for light-to-moderate exercise only. Explicitly told to walk more.",
            "orthopedic_limitations": {
                "active_injuries": [],
                "chronic_pain_points": [],
                "functional_mobility_restrictions": "Sedentary joint stiffness; fear of knee pain.",
            },
        },
        "logistics": {
            "frequency_capability_days_per_week": 5,
            "session_duration_ceiling_minutes": 45,
            "preferred_time_of_day": "Early morning",
            "environment_type": "Home-based",
            "available_equipment": [],
            "dietary_archetype": "Traditional South Indian Vegetarian",
        },
        "behavioral_psychology": {
            "past_failure_modes": "Dropped out at the 2-week mark twice in the past due to 'busy-ness'.",
            "psychological_barriers_fears": ["Anxiety regarding knee pain", "Fear of acute breathlessness"],
            "communication_preference": "Spoken Tamil; casual, reassuring tone.",
        },
    },
    "high_level_recent_history": {
        "week_minus_2_compliance": "3 out of 5 sessions completed. Reported slight ankle stiffness.",
        "week_minus_1_compliance": "4 out of 5 sessions completed. Stated confidence is rising because knees felt fine.",
    },
}

SAMPLE_HEALTHY_MALE_INPUT = {
    "task": "GENERATE_WEEKLY_MACRO_SPLIT",
    "client_profile": {
        "biometrics": {
            "full_name": "Arjun Mehta",
            "age": 35,
            "biological_sex": "Male",
            "height_cm": 180,
            "weight_kg": 88,
            "ethnicity_demographic": "North Asian / South Asian Mix",
        },
        "clinical_status": {
            "primary_diagnoses": [],
            "medications": [],
            "medical_clearance_constraints": "Fully cleared for all exercise intensities.",
            "orthopedic_limitations": {
                "active_injuries": [],
                "chronic_pain_points": [],
                "functional_mobility_restrictions": "General detraining sluggishness; slight hip tightness from desk work.",
            },
        },
        "logistics": {
            "frequency_capability_days_per_week": 4,
            "session_duration_ceiling_minutes": 60,
            "preferred_time_of_day": "Late afternoon / Evening",
            "environment_type": "Commercial Gym",
            "available_equipment": ["Barbells", "Dumbbells", "Cables", "Machines", "Cardio Equipment"],
            "dietary_archetype": "Omnivore / High-Protein Balanced",
        },
        "behavioral_psychology": {
            "past_failure_modes": "Tended to overcomplicate programming and burned out by trying to lift at his peak strength levels immediately.",
            "psychological_barriers_fears": ["Frustration with current loss of strength and muscle mass compared to last year", "Fear of ego lifting and causing an avoidable injury"],
            "communication_preference": "English; direct, numbers-driven, and highly motivating tone.",
        },
    },
    "high_level_recent_history": {
        "week_minus_2_compliance": "0 out of 4 sessions completed. Focus was strictly on baseline assessments, habit re-establishment, and gym membership reactivation.",
        "week_minus_1_compliance": "2 out of 4 sessions completed. Light introductory full-body workouts; reported significant delayed onset muscle soreness (DOMS) but high motivation.",
    },
}


SAMPLE_MACRO_PLAN = {
    "split_strategy_rationale": (
        "This weekly macro schedule is designed for a 52-year-old male with Type 2 Diabetes, "
        "sedentary joint stiffness, and fear of knee pain. The program prioritizes low-impact, "
        "joint-friendly movement patterns to improve metabolic health, mobility, and confidence. "
        "It avoids consecutive high spinal-loading days (e.g., `squat` and `hinge`) and "
        "incorporates daily `gait` or `cardio` to align with medical clearance for walking. "
        "Movement patterns are grouped to balance intensity and recovery, with rest days "
        "strategically placed to prevent overuse and accommodate joint stiffness. The schedule "
        "also addresses psychological barriers by including reassuring, low-complexity movements "
        "and avoiding overtraining."
    ),
    "schedule": [
        {
            "name": "Mobility & Core Activation",
            "day": "Monday",
            "type": "Workout",
            "target_movement_patterns": ["gait", "core_stability", "rotation"],
        },
        {
            "name": "Lower Body Strength & Stability",
            "day": "Tuesday",
            "type": "Workout",
            "target_movement_patterns": ["squat", "lunge", "core_stability"],
        },
        {
            "name": "Active Recovery & Cardio",
            "day": "Wednesday",
            "type": "Workout",
            "target_movement_patterns": ["gait", "cardio", "rotation"],
        },
        {
            "name": "Upper Body Push & Pull Balance",
            "day": "Thursday",
            "type": "Workout",
            "target_movement_patterns": ["push_horizontal", "pull_horizontal", "core_stability"],
        },
        {
            "name": "Full-Body Integration",
            "day": "Friday",
            "type": "Workout",
            "target_movement_patterns": ["hinge", "carry", "gait"],
        },
        {
            "name": "Rest Day",
            "day": "Saturday",
            "type": "Rest",
            "target_movement_patterns": [],
        },
        {
            "name": "Rest Day",
            "day": "Sunday",
            "type": "Rest",
            "target_movement_patterns": [],
        },
    ],
}
