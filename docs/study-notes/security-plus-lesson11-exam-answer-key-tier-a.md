# CompTIA Security+ — Lesson 11 Exam, Tier A Answer Key

Source: ed2go/Cengage "Lesson 11: Networking Threats, Assessments, and
Defenses" practice exam (30 questions). Tier A = the instructor-grade key
(correct letter + one-line rationale), for checking a self-attempt against.

| # | Question (short) | Answer | Why |
| - | --- | :-: | --- |
| 1 | Attack copying personal info via unauthorized RF connection | **A** Bluesnarfing | Bluesnarfing = accessing unauthorized info from a device over Bluetooth; Bluejacking (D) only sends unsolicited messages, it doesn't extract data. |
| 2 | Attack designed to capture transmissions from legitimate users | **C** Evil twin | A rogue AP mimics a legitimate one so the victim's device connects unknowingly, letting the attacker capture its traffic. |
| 3 | "Easy" attack that exposes user data/passwords/PINs, and why | **C** WLAN consumer attack | Home WLANs are frequently misconfigured or left with weak/default security by non-expert users. |
| 4 | Eavesdropping vs. MITM protection for NFC | **D** | Eavesdropping → stay aware of surroundings (limit who's in range); MITM → pair so one device only sends, the other only receives. |
| 5 | Correct definition of jamming | **B** | Jamming = intentionally flooding the RF spectrum with noise to create interference. |
| 6 | Packet w/ function field, identifier (match req/resp), data type + data | **C** EAP packet | EAP fields: Code (function), Identifier (matches request/response), Length, Type, Type-Data. |
| 7 | Intentional RF interference (jamming, RTS duration field attacks) | **A** Wireless denial of service attacks | Both are WDoS techniques — flood/exploit RF so devices can't reach the AP. |
| 8 | RFID attack: listening to tag↔reader communications | **C** Eavesdropping | Passive interception of the RF exchange between tag and reader. |
| 9 | AP type managed by a WLC | **D** Controller AP | By definition, a controller AP is managed through a dedicated WLC. |
| 10 | Why jamming attacks are rare | **D** Require expensive, sophisticated equipment | Effective RF jamming needs specialized transmit hardware, raising the barrier to entry. |
| 11 | Site survey tool visualizing coverage/bandwidth/rate/interference | **A** Heat maps | Heat maps are the standard visual site-survey output. |
| 12 | Probe: a configured laptop scanning/reporting to a central DB | **D** Wireless device probe | A "wireless device probe" is an ordinary wireless client (e.g., a laptop) repurposed to scan and report — vs. a purpose-built dedicated probe. |
| 13 | Shared secret key + IV that changes per packet | **C** WEP | WEP's defining (weak) mechanism is a static key combined with a per-packet IV. |
| 14 | IC that stores IoT device identity/auth info | **D** Subscriber identity module | This is the textbook definition of a SIM card. |
| 15 | Probe that *only* monitors RF/airwaves | **D** Dedicated probe | Dedicated probes have no other function — they can't also serve as an AP or client. |
| 16 | Employee secretly attaches a cheap router to the wired network | **D** Rogue access point | An unauthorized AP plugged into the trusted network, bypassing security controls — textbook rogue AP. |
| 17 | Mitigation for a "bump the reader against the phone" NFC data-theft attack | **A** Protect the phone with a unique password/PIN | This attack needs no active pairing, so pairing/proximity-awareness advice (B, C, D) doesn't stop it — a locked device does. |
| 18 | Prevent all devices at an event from communicating/calling | **A** Jamming | Deliberately flooding RF to block all wireless communication in range. |
| 19 | Attendance system replacing sign-in sheets, personal devices banned | **A** RFID | Badge-based RFID needs no personal electronic device, unlike Bluetooth/NFC/Wi-Fi options. |
| 20 | Adjust frequency bands, optimum channels, available spectrum when relocating an AP | **C** Spectrum selection | Spectrum selection is the configuration step that governs which bands/channels the AP uses. |
| 21 | Wide-range, indoor-focused, low-cost, long-battery, high-density LPWAN cellular tech | **A** Narrowband IoT | NB-IoT is the LPWAN standard defined by exactly these characteristics. |
| 22 | Small business (5 employees) moving into an office — enterprise AP choice | **B** Controller AP | Once you're past a single AP, controller-managed APs are the standard enterprise-grade choice for centralized management. |
| 23 | Car hands-free system: voice control, contacts, calls, screen mirroring | **C** Bluetooth | Bluetooth is the standard for hands-free pairing and screen-mirroring in vehicle infotainment. |
| 24 | Steal phone data via a device connected without physical touch | **A** Data theft | This defines the NFC "data theft" vulnerability category (proximity read, no contact needed). |
| 25 | Control multiple devices (speakers, mice) wirelessly within ~100m | **C** Bluetooth | Bluetooth Class 1 range is ~100m and is the standard for peripheral pairing. |
| 26 | Medical device measuring vitals, sending data to a phone | **C** Bluetooth | Short-range pairing between a medical sensor and a phone is the classic Bluetooth use case. |
| 27 | Protocol restricting traffic to specific (device) addresses | **B** MAC address filtering | MAC filtering permits/denies access based on the device's MAC address. |
| 28 | Strongest wireless security, longer encryption bits, better IoT support | **D** WPA3 | WPA3 is the current generation, strengthening encryption and IoT/onboarding support over WPA2. |
| 29 | Probe monitoring airwaves even when idle, reporting to a central DB, for rogue-AP detection | **B** Dedicated probes | Dedicated probes continuously monitor RF regardless of device activity — their sole purpose. |
| 30 | Access point probe vs. dedicated probe | **C** | A dedicated probe only monitors RF; an access point probe can serve double duty as both a probe and a roaming AP. |

## Score key (quick-scan)

```
1-A  2-C  3-C  4-D  5-B  6-C  7-A  8-C  9-D  10-D
11-A 12-D 13-C 14-D 15-D 16-D 17-A 18-A 19-A 20-C
21-A 22-B 23-C 24-A 25-C 26-C 27-B 28-D 29-B 30-C
```
