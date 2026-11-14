"""Implicit-prerequisite tasks: no prompt mentions creating a folder."""
from run_agent import T

PREREQ = [
    T("P01", "prereq", "prereq", "Save the text: Q4 draft into reports/q4.txt", files={"reports/q4.txt": {"contains": ["Q4 draft"]}}),
    T("P02", "prereq", "prereq", "Write the word healthy into exports/health.txt", files={"exports/health.txt": {"contains": ["healthy"]}}),
    T("P03", "prereq", "prereq", "Put the line nightly ok in backups/night.txt", files={"backups/night.txt": {"contains": ["nightly ok"]}}),
    T("P04", "prereq", "prereq", "Save the text: v2 released into releases/notes.txt", files={"releases/notes.txt": {"contains": ["v2 released"]}}),
    T("P05", "prereq", "prereq", "Write the text archived into logs/old/today.txt", files={"logs/old/today.txt": {"contains": ["archived"]}}),
    T("P06", "prereq", "prereq", "Save the text: final into docs/drafts/final.txt", files={"docs/drafts/final.txt": {"contains": ["final"]}}),
]
