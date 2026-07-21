import html
import json

import gradio as gr

from agents.mock_data import SAMPLE_HEALTHY_MALE_INPUT, SAMPLE_HEART_PATIENT_INPUT
from agents.workout_agent import CoachState, generate_macro_split_node, generate_micro_workout_node

# Mirrors the __main__ block in workout_agent.py: only expand one sample day
# into a full micro workout instead of looping the whole week.
SAMPLE_DAY_INDEX = 3

STYLE = """
<style>
.wc-section { margin-bottom: 24px; }
.wc-rationale {
    background: var(--background-fill-secondary);
    border: 1px solid var(--border-color-primary);
    border-radius: 10px;
    padding: 14px 18px;
    line-height: 1.5;
    margin-bottom: 18px;
}
.wc-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 14px;
}
.wc-card {
    border: 1px solid var(--border-color-primary);
    border-radius: 12px;
    padding: 14px 16px;
    background: var(--block-background-fill);
}
.wc-day-title { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.wc-day-name { font-weight: 700; font-size: 1.05em; }
.wc-badge { font-size: 0.72em; font-weight: 600; padding: 2px 10px; border-radius: 999px; text-transform: uppercase; letter-spacing: .03em; }
.wc-badge-workout { background: rgba(47, 158, 68, 0.12); color: #2f9e44; border: 1px solid rgba(47, 158, 68, 0.35); }
.wc-badge-rest { background: rgba(108, 117, 125, 0.12); color: #868e96; border: 1px solid rgba(108, 117, 125, 0.35); }
.wc-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.wc-tag { font-size: 0.75em; padding: 2px 9px; border-radius: 999px; background: var(--background-fill-secondary); border: 1px solid var(--border-color-primary); }
.wc-day-name-header { font-size: 1.15em; font-weight: 700; margin: 22px 0 10px; }
.wc-day-name-header:first-child { margin-top: 0; }
.wc-phase { margin-top: 14px; }
.wc-phase-title { font-weight: 700; font-size: 0.8em; text-transform: uppercase; letter-spacing: .04em; opacity: 0.65; margin-bottom: 6px; }
.wc-exercise { border-left: 3px solid #4c6ef5; padding: 6px 0 6px 12px; margin-bottom: 8px; }
.wc-exercise-name { font-weight: 600; }
.wc-exercise-meta { font-size: 0.85em; opacity: 0.7; margin-left: 6px; }
.wc-why { font-size: 0.9em; margin-top: 3px; }
.wc-cue { font-size: 0.9em; margin-top: 2px; color: #4c6ef5; }
.wc-rest-card {
    border: 1px dashed var(--border-color-primary);
    border-radius: 12px;
    padding: 14px 16px;
    background: var(--background-fill-secondary);
    margin: 22px 0;
}
.wc-empty { opacity: 0.7; font-style: italic; }
</style>
"""

PHASE_ORDER = ["Mobility Warm-Up", "Strength Core", "Conditioning Finisher"]


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _tag_list(values) -> str:
    return "".join(f'<span class="wc-tag">{_esc(v)}</span>' for v in values or [])


def render_macro_plan(macro_plan: dict) -> str:
    """Render the weekly movement-pattern split as a grid of day cards."""
    schedule = macro_plan.get("schedule", [])
    if not schedule:
        return f'{STYLE}<div class="wc-empty">No macro plan was generated.</div>'

    cards = []
    for day in schedule:
        is_rest = str(day.get("type", "")).lower() == "rest"
        badge_class = "wc-badge-rest" if is_rest else "wc-badge-workout"
        cards.append(f"""
        <div class="wc-card">
            <div class="wc-day-title">
                <span class="wc-day-name">{_esc(day.get("day"))}</span>
                <span class="wc-badge {badge_class}">{_esc(day.get("type"))}</span>
            </div>
            <div>{_esc(day.get("name", ""))}</div>
            <div class="wc-tags">{_tag_list(day.get("target_movement_patterns"))}</div>
        </div>
        """)

    rationale = macro_plan.get("split_strategy_rationale", "")
    rationale_block = f'<div class="wc-rationale">{_esc(rationale)}</div>' if rationale else ""

    return f"""
    {STYLE}
    <div class="wc-section">
        {rationale_block}
        <div class="wc-grid">{"".join(cards)}</div>
    </div>
    """


def _render_exercise(exercise: dict) -> str:
    sets = exercise.get("sets", "")
    reps = exercise.get("reps", "")
    meta = f"{sets} sets &times; {reps}" if sets or reps else ""
    return f"""
    <div class="wc-exercise">
        <div>
            <span class="wc-exercise-name">{_esc(exercise.get("name"))}</span>
            <span class="wc-exercise-meta">{meta}</span>
        </div>
        <div class="wc-why">{_esc(exercise.get("why", ""))}</div>
        <div class="wc-cue">Cue: {_esc(exercise.get("cue", ""))}</div>
    </div>
    """


def _render_workout_day(day_name: str, day_data: dict) -> str:
    focus = day_data.get("focus", [])
    routine = day_data.get("routine", [])

    by_phase = {}
    for exercise in routine:
        by_phase.setdefault(exercise.get("phase", "Other"), []).append(exercise)

    ordered_phases = [p for p in PHASE_ORDER if p in by_phase] + [p for p in by_phase if p not in PHASE_ORDER]
    phase_blocks = "".join(
        f"""
        <div class="wc-phase">
            <div class="wc-phase-title">{_esc(phase)}</div>
            {"".join(_render_exercise(ex) for ex in by_phase[phase])}
        </div>
        """
        for phase in ordered_phases
    )

    if not phase_blocks:
        phase_blocks = '<div class="wc-empty">No exercises were generated for this day.</div>'

    return f"""
    <div class="wc-day-name-header">{_esc(day_name)}</div>
    <div class="wc-tags">{_tag_list(focus)}</div>
    {phase_blocks}
    """


def _render_rest_day(day_name: str, day_data: dict) -> str:
    activities = ", ".join(day_data.get("activities", [])) or "Full rest"
    return f"""
    <div class="wc-rest-card">
        <strong>{_esc(day_name)} &mdash; Rest Day</strong>
        <div>{_esc(activities)}</div>
    </div>
    """


def render_single_day(day_name: str, day_data: dict) -> str:
    """Render one day's detailed routine (or rest note)."""
    if not day_data:
        return f'{STYLE}<div class="wc-empty">No workout was generated for {_esc(day_name)}.</div>'

    if day_data.get("type") == "Rest Day":
        body = _render_rest_day(day_name, day_data)
    else:
        body = _render_workout_day(day_name, day_data)

    return f'{STYLE}<div class="wc-section">{body}</div>'


def generate_plan(client_json_text: str):
    try:
        parsed = json.loads(client_json_text)
    except json.JSONDecodeError as e:
        error_html = f'{STYLE}<div class="wc-empty">Invalid JSON input.</div>'
        return error_html, error_html, gr.update(value=f"**Invalid JSON:** {e}", visible=True)

    client_profile = parsed.get("client_profile", parsed)

    try:
        macro_state = CoachState(user_profile=client_profile)
        macro_result = generate_macro_split_node(macro_state)
        macro_plan = macro_result["macro_plan"]

        schedule = macro_plan.get("schedule", [])
        if not schedule:
            raise ValueError("Macro plan generation returned an empty schedule.")
        day_idx = min(SAMPLE_DAY_INDEX, len(schedule) - 1)

        micro_state = CoachState(
            user_profile=client_profile,
            macro_plan=macro_plan,
            current_day_idx=day_idx,
        )
        micro_result = generate_micro_workout_node(micro_state)
        detailed_workouts = micro_result["detailed_workouts"]
    except Exception as e:
        error_html = f'{STYLE}<div class="wc-empty">Plan generation failed.</div>'
        return error_html, error_html, gr.update(value=f"**Generation failed:** {e}", visible=True)

    macro_html = render_macro_plan(macro_plan)

    day_name = schedule[day_idx]["day"]
    micro_html = render_single_day(day_name, detailed_workouts.get(day_name, {}))

    return macro_html, micro_html, gr.update(value="", visible=False)


with gr.Blocks(title="AI Fitness Coach") as demo:
    gr.Markdown(
        "# AI Fitness Coach\n"
        "Paste a client profile JSON (a pre-filled example is loaded below) to generate the "
        "weekly movement-pattern split, plus a fully expanded sample day's workout."
    )

    with gr.Row():
        with gr.Column(scale=1):
            client_input = gr.Textbox(
                label="Client Input JSON",
                value=json.dumps(SAMPLE_HEART_PATIENT_INPUT, indent=2),
                lines=28,
            )
            with gr.Row():
                heart_btn = gr.Button("Load Heart/Diabetes Patient Example")
                healthy_btn = gr.Button("Load Healthy Adult Example")
            generate_btn = gr.Button("Generate Weekly Plan", variant="primary")
            error_box = gr.Markdown(visible=False)

        with gr.Column(scale=2):
            with gr.Tabs():
                with gr.Tab("Weekly Split (Macro Plan)"):
                    macro_output = gr.HTML()
                with gr.Tab("Sample Day (Micro Plan)"):
                    micro_output = gr.HTML()

    heart_btn.click(fn=lambda: json.dumps(SAMPLE_HEART_PATIENT_INPUT, indent=2), outputs=client_input)
    healthy_btn.click(fn=lambda: json.dumps(SAMPLE_HEALTHY_MALE_INPUT, indent=2), outputs=client_input)

    generate_btn.click(
        fn=generate_plan,
        inputs=client_input,
        outputs=[macro_output, micro_output, error_box],
    )


if __name__ == "__main__":
    demo.launch()
