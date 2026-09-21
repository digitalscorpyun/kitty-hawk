# CompTIA Security+ — Lesson 11 Exam, Attempt #1 Results

- **Date:** September 21, 2026, 7:43 AM
- **Score:** 86.7% — 26 correct out of 30
- **Attempts remaining:** 2
- **Learning objectives passed:** 11.1 (wireless network attacks), 11.2
  (WLAN security vulnerabilities), 11.3 (solutions for securing a wireless
  network) — the LMS flagged all three as solid despite the 4 misses below.

## The 4 missed questions

| # | Question (short) | Your answer | Correct answer | LMS rationale |
| - | --- | :-: | :-: | --- |
| 1 | Attack copying personal info via unauthorized RF connection | C RFID attack | **A** Bluesnarfing | RFID attacks (fake tags) undermine inventory-system integrity with fictitious data — they don't copy personal info off a device. Bluesnarfing is the unauthorized-access/copy attack. |
| 11 | Site survey tool visualizing channel bandwidth, channel coverage, data rate, interference | A Heat maps | **D** Wi-Fi analyzers | A heat map is a coverage/strength overlay on a floor plan — narrower than the metric set the question lists. Wi-Fi analyzers cover the broader set (bandwidth, coverage, rate, interference). |
| 17 | Mitigation for attacker bumping a portable reader against a phone (NFC data theft) | A Protect phone with password/PIN | **B** Turn NFC off while in a crowded area | Password/PIN protects against *device theft*, not a live-NFC proximity read. Since the attack requires NFC to be on and the attacker nearby, disabling NFC in crowds removes the exposure. |
| 22 | Melvin, 5-employee business moving into an office — AP type | B Controller AP | **D** Fat AP | Controller APs need a dedicated WLC to manage them — overkill at 5 employees. A Fat AP is self-contained and standard for this scale; Controller APs fit once you're managing many APs centrally. |

## Notes for next attempt

- Questions 1, 11, 17, 22 are the four to drill before retaking.
- `security-plus-lesson11-exam-answer-key-tier-a.md` has been corrected
  to match this official grading (it originally had 11, 17, and 22 wrong —
  those were authored before this attempt existed, from general Security+
  knowledge rather than this course's specific LMS key).
- Everything else (26/30) held up against the official key exactly as
  banked.
