# Meal reminder timer (VM)

`meal-reminders.timer` runs `python -m voice_processor.meal_reminders --due`
every 15 minutes. Each pass reminds every diet-tracking client whose own
local time (`user_profiles.timezone`) has just passed 11:00, 15:00 or 20:00
— within 45 minutes of it — and who hasn't logged the meals due by then
(see `voice_processor/meal_reminders.py`). A pass with nobody due does nothing.

## Install

1. In `meal-reminders.service`, replace `User`, `WorkingDirectory`,
   `EnvironmentFile` and the python path with the values the voice
   processor's existing service uses (`systemctl cat <its unit>`).
2. Copy and enable:

   ```sh
   sudo cp voice_processor/deploy/meal-reminders.service voice_processor/deploy/meal-reminders.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now meal-reminders.timer
   ```

3. Check the next pass:

   ```sh
   systemctl list-timers meal-reminders.timer
   ```

## Try it

```sh
.venv/bin/python -m voice_processor.meal_reminders --due --dry-run               # who is due right now, and why
.venv/bin/python -m voice_processor.meal_reminders --slot lunch --dry-run        # one slot for everyone, now
.venv/bin/python -m voice_processor.meal_reminders --slot lunch --user-id <id>   # one real client
sudo systemctl start meal-reminders.service                                      # a real pass, now
journalctl -u meal-reminders.service --since today                               # what happened
```

Each reminder writes one `meal_reminders` row per client, local date and
slot (sent, skipped_logged, skipped_window_closed, failed), so a slot is never
sent twice on the same day.

# Weight tracking timer (VM)

`weight-jobs.timer` runs `python -m voice_processor.weight_jobs --due` every
15 minutes (see `voice_processor/weight_jobs.py`): it closes each client's
Mon–Sun week once her own Sunday 19:00 has passed (one `weight_weeks` row per
client and week) and, with `WEIGHT_NUDGES_ENABLED=1`, sends the weigh-in
how-to and the 10:00 nudge while her WhatsApp window is open.

Environment (in the same `.env`):

- `WEIGHT_WEEKLY_MODE` — `shadow` (default: weeks are stored for the coach,
  nothing is sent, no calorie suggestions) or `live`.
- `WEIGHT_NUDGES_ENABLED` — `1` to send the how-to and morning nudges; off by default.

Install exactly like the meal reminders, with `weight-jobs.service` /
`weight-jobs.timer`. Try it:

```sh
.venv/bin/python -m voice_processor.weight_jobs --due --dry-run               # every client's decision, nothing stored or sent
.venv/bin/python -m voice_processor.weight_jobs --due --dry-run --user-id <id>
journalctl -u weight-jobs.service --since today
```
