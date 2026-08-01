SAMPLE_USER_PROFILE_V1 = {
    "demographics": {
        "age": 52,
        "sex": "female",
        "height_cm": 165,
        "weight_kg": 72,
    },
    "goals": {
        "primary_goal": "improve_mobility",
        "secondary_goals": ["weight_loss", "strength"],
        "target_timeline_weeks": 12,
    },
    "experience": {
        "training_experience_level": "beginner",
        "years_training": 0,
        "past_activities": ["walking", "occasional yoga"],
        "current_activity_level": "sedentary",
    },
    "health": {
        "medical_clearance_obtained": True,
        "conditions": [
            {
                "name": "osteoarthritis",
                "location": "right_knee",
                "severity": "moderate",
                "notes": "pain on deep flexion, avoid high-impact loading",
            }
        ],
        "past_injuries": [
            {
                "type": "rotator_cuff_strain",
                "side": "left",
                "year": 2021,
                "status": "healed_with_limited_rom",
            }
        ],
        "pain_flags": ["knee", "lower_back"],
        "movements_to_avoid": ["deep_squats", "overhead_press_left_arm"],
        "medications_affecting_exercise": ["beta_blockers"],
        "cardiovascular_risk_factors": ["hypertension"],
        "pregnancy_status": "not_applicable",
    },
    "availability": {
        "days_per_week": 3,
        "session_duration_minutes": 30,
        "preferred_times": ["morning"],
        "preferred_days": ["monday", "wednesday", "friday"],
    },
    "equipment_access": {
        "location": "home",
        "available_equipment": ["dumbbells_light", "resistance_bands", "chair"],
        "no_access_to": ["barbell", "machines"],
    },
    "preferences": {
        "liked_activities": ["walking", "swimming"],
        "disliked_activities": ["running", "burpees"],
        "music_or_class_style": "low_impact",
        "coaching_tone": "encouraging",
    },
    "current_metrics": {
        "resting_heart_rate": 78,
        "max_heart_rate_known": None,
        "resting_blood_pressure": "132/85",
        "flexibility_notes": "limited hip mobility",
        "balance_concerns": False,
    },
    "constraints_and_notes": {
        "recovery_speed": "average",
        "sleep_quality": "poor",
        "stress_level": "moderate",
        "free_text_notes": "Prefers seated or low-impact options when knee flares up.",
    },
    "progress_tracking": {
        "last_assessment_date": "2026-06-15",
        "adherence_rate_pct": 80,
        "last_reported_pain_level": 3,
    },
}


# Same client, but available 5 days/week -> should still cap at the 4-day template.
SAMPLE_USER_PROFILE_V1_FOUR_DAY = {
    **SAMPLE_USER_PROFILE_V1,
    "user_id": "usr_10235",
    "availability": {
        "days_per_week": 5,
        "session_duration_minutes": 45,
        "preferred_times": ["evening"],
        "preferred_days": ["monday", "tuesday", "thursday", "friday", "saturday"],
    },
    "health": {
        **SAMPLE_USER_PROFILE_V1["health"],
        "medical_clearance_obtained": False,
    },
}
