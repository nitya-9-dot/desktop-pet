"""Reminder times for the desktop pet, using the computer's local time."""

from datetime import datetime


MEALS = {
    9: "Breakfast time!",
    14: "Lunch time!",
    19: "Dinner time!",
}
WATER_HOURS = {8, 10, 12, 14, 16, 18, 20}


class ReminderSchedule:
    """Emits each reminder once, even though the timer checks every second."""

    def __init__(self):
        self.sent = set()

    def due_reminders(self, now=None):
        now = now or datetime.now()
        if now.minute != 0:
            return []

        minute_key = (now.year, now.month, now.day, now.hour, now.minute)
        if minute_key in self.sent:
            return []

        reminders = []
        if now.hour in MEALS:
            reminders.append(("food", MEALS[now.hour]))
        if now.hour in WATER_HOURS:
            reminders.append(("water", "Time to drink water!"))

        if reminders:
            self.sent.add(minute_key)
        return reminders
