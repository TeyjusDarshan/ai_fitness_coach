"""Every WhatsApp text about her weight, in Tanglish (pure). Fixed wording,
no AI call. Weekly summaries: at most 5 lines and at most two weights (this
week's average and last week's), never a change from one day to the next."""
from typing import Any, Dict, Optional

from diet.weight import rules


def _name(name: Optional[str]) -> str:
    return name.strip() if name and name.strip() else ""


def _kg(value: Optional[float]) -> str:
    return f"{float(value):.1f}"


def noted(weight_kg: float) -> str:
    return f"Noted ✅ {_kg(weight_kg)} kg"


def outlier(weight_kg: float) -> str:
    return (f"{_kg(weight_kg)} kg nu vandhuchu. Idhu unga vazhakkamaana weight-ai vida romba vithyaasama irukku, "
            "sariyaa illama irukkalaam. Scale-a check panni marubadiyum weight paathu anuppunga 🙏")


def no_number() -> str:
    return "Unga weight number puriyala 🙏 Number mattum anuppunga, e.g. 72.4"


def intro(name: Optional[str]) -> str:
    greeting = f"Vanakkam {_name(name)} 🙏" if _name(name) else "Vanakkam 🙏"
    return (f"{greeting} Innaila irundhu dhinamum kaalaila weight paathu enakku anuppunga. "
            "Number type pannalaam, illa voice note-la sollalaam. "
            "Toilet poittu, saapdradhukku munnaadi, ore scale-la paarunga.")


def morning_nudge(name: Optional[str]) -> str:
    prefix = f"{_name(name)}, " if _name(name) else ""
    return f"{prefix}inniki weight innum anuppala 🙂 Kaalaila paatha number-a anuppunga."


_MEANING = {
    rules.ON_TRACK: {
        "lose": "Nalla poitu irukku 👏 Same food plan continue pannunga.",
        "gain": "Nalla poitu irukku 👏 Same food plan continue pannunga.",
        "maintain": "Unga range-kulla steady-a irukeenga ✅",
    },
    rules.PERIOD_WEEK: "Period irundhadhaala weight konjam adhigama kaattum, adhu water dhaan. Indha vaaram count panna maattom.",
    rules.LOGS_OVER: "Saapadu target-a vida konjam adhigama irukku. Plan-la irukkura alavu saapdunga 🙏",
    rules.LOGS_UNDER: "Saapadu target-a vida kammiya irukku. Konjam adhigama saapdunga 🙏",
    rules.LOGS_OFF: "Saapadu target-oda konjam vithyaasama irukku. Plan alavu saapdunga 🙏",
    rules.CHANGE_PENDING: "Unga coach unga food plan-a paathutu irukkanga.",
    rules.LOWER: "Unga coach unga food plan-a paathu solluvaanga.",
    rules.RAISE: "Unga coach unga food plan-a paathu solluvaanga.",
    rules.AT_FLOOR: "Unga coach unga plan-a paathu solluvaanga.",
    rules.COOL_DOWN: "Pudhu plan-la 2nd vaaram. Adutha vaaram-la irundhu marubadiyum check pannuvom.",
}


def _meaning(outcome: str, goal: str, ctx: Dict[str, Any]) -> str:
    if outcome == rules.BASELINE:
        if ctx.get("after_change"):
            return "Pudhu food plan start aagi first vaaram. Body adjust aaga 2 vaaram aagum, plan maathama continue pannuvom."
        if ctx.get("previous_avg_kg") is None:
            return "Idhu unga starting average. Adutha vaaram-la irundhu compare pannuvom. Daily weight mela keela pogum, adhu normal 🙂"
        return "Adutha vaaram-la irundhu compare pannuvom 🙂"
    if outcome == rules.WAIT:
        if goal == "maintain":
            way = "mela" if (ctx.get("change_kg") or 0) > 0 else "keezha"
            return f"Konjam {way} pogudhu, kavanippom. Same plan continue pannunga."
        return "Indha vaaram konjam slow, adhu normal. Same plan, adutha vaaram paapom."
    if outcome == rules.TOO_FAST:
        if goal == "lose":
            return "Weight romba vegama korayudhu, muscle-um poidum. Unga coach unga food plan-a paathu solluvaanga."
        return "Weight romba vegama yerudhu. Unga coach unga food plan-a paathu solluvaanga."
    if outcome == rules.TARGET_REACHED:
        return f"🎉 Neenga unga target {_kg(ctx.get('goal_kg'))} kg reach pannitteenga! Coach unga plan-a maathuvaanga."
    if outcome == rules.LOGS_LOW:
        return (f"Food konjam dhaan log aagirukku ({ctx.get('meals_logged', 0)}/{ctx.get('meals_total', 0)}). "
                "Ellaa meal-um log panna dhaan enna maathanum-nu theriyum 🙏")
    meaning = _MEANING.get(outcome, "")
    return meaning.get(goal, "") if isinstance(meaning, dict) else meaning


def weekly_summary(outcome: str, goal: str, ctx: Dict[str, Any]) -> str:
    """ctx: name, readings, avg_kg, previous_avg_kg, change_kg, meals_logged,
    meals_total, goal_kg, after_change."""
    name = _name(ctx.get("name"))
    lines = [f"{name}, indha vaaram weight summary 📊" if name else "Indha vaaram weight summary 📊"]
    if outcome == rules.NOT_ENOUGH_DATA:
        lines.append(f"Indha vaaram {ctx.get('readings', 0)} naal dhaan weight vandhuchu, compare panna mudiyala. "
                     "Dhinamum kaalaila anuppunga 🙏")
    else:
        avg, previous = ctx.get("avg_kg"), ctx.get("previous_avg_kg")
        line = f"Average: {_kg(avg)} kg"
        if previous is not None:
            change = round(float(avg) - float(previous), 1)
            arrow = "↓" if change < 0 else "↑" if change > 0 else "→"
            line += f" (pona vaaram {_kg(previous)}) {arrow} {abs(change):.1f} kg"
        lines.append(line)
        meaning = _meaning(outcome, goal, ctx)
        if meaning:
            lines.append(meaning)
    lines.append(f"Weight: {ctx.get('readings', 0)}/7 naal · Food: {ctx.get('meals_logged', 0)}/{ctx.get('meals_total', 0)} meal")
    return "\n".join(lines)


def change_approved(name: Optional[str], from_kcal: Optional[int], to_kcal: int, outcome: Optional[str],
                    goal: str) -> str:
    """Sent when the coach accepts a weekly suggestion."""
    prefix = f"{_name(name)}, " if _name(name) else ""
    if outcome == rules.TARGET_REACHED:
        return (f"{prefix}ini unga weight-a maintain pannuvom 💚 Unga daily calories {to_kcal} kcal. "
                "Naalaila irundhu app-la pudhu target theriyum.")
    change = f"{from_kcal} → {to_kcal}" if from_kcal else f"{to_kcal}"
    why = {
        rules.TOO_FAST: "Weight romba vegama maarudhu, adhaan.",
        rules.LOWER: "2 vaaram weight sariyaa maarala, adhaan 🙂" if goal != "maintain" else "Weight konjam yerudhu, adhaan 🙂",
        rules.RAISE: "2 vaaram weight sariyaa maarala, adhaan 🙂" if goal != "maintain" else "Weight konjam korayudhu, adhaan 🙂",
    }.get(outcome or "", "")
    return f"{prefix}unga coach daily calories-a {change} aa maathirukkanga. Naalaila irundhu app-la pudhu target theriyum. {why}".strip()
