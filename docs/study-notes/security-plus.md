# CompTIA Security+ — Study Notes

Personal cert-prep notes, kept separate from the Kitty Hawk engineering docs.
Source: ed2go CompTIA Security+ Certification Training (Voucher Included).

## Lesson 11 — Networking Threats, Assessments, and Defenses

### Key Terms

| Term | Definition |
| --- | --- |
| Bluetooth | A wireless technology that uses short-range radio frequency (RF) transmissions and provides rapid ad hoc device pairings. |
| point-to-point | A network topology in which one device is connected to one other device. |
| point-to-multipoint | A network topology in which one device is connected to multiple devices. |
| Bluejacking | An attack that sends unsolicited messages to Bluetooth-enabled devices. |
| Bluesnarfing | An attack that accesses unauthorized information from a wireless device through a Bluetooth connection. |
| Near field communication (NFC) | A set of standards used to establish communication between devices in very close proximity. |
| payment method | An electronic alternative to using cash or a credit card for payments; also called contactless payment system. |
| radio frequency identification (RFID) | A wireless set of standards used to transmit information from paper-based tags to a proximity reader. |
| Wi-Fi | A wireless network designed to replace or supplement a wired local area network (LAN). Also called wireless local area network (WLAN). |
| ad hoc mode | A WLAN functioning without an AP. |
| Wi-Fi Direct | The Wi-Fi Alliance implementation of WLAN ad hoc mode. |
| controller APs | An AP that is managed through a dedicated wireless LAN controller (WLC). |
| captive portal AP | An infrastructure on public access WLANs that uses a standard web browser to provide information, and gives the wireless user the opportunity to agree to a policy or present valid login credentials to provide a higher degree of security. |
| rogue AP | An unauthorized AP that allows an attacker to bypass many network security configurations and opens the network and its users to attacks. |
| evil twin | An AP set up by an attacker to mimic an authorized AP and capture transmissions, so a user's device will unknowingly connect to the evil twin instead of the authorized AP. |
| jamming | Intentionally flooding the radio frequency (RF) spectrum with extraneous RF signal "noise" that creates interference and prevents communications from occurring. |
| disassociation attack | A wireless attack in which false deauthentication or disassociation frames are sent to an AP that appear to come from another client device, causing the client to disconnect. |
| initialization vector (IV) | A 24-bit value that changes each time a packet is encrypted. |
| Wi-Fi Protected Setup (WPS) | An optional means of configuring security on wireless local area networks primarily intended to help users who have little or no knowledge of security to implement security quickly and easily on their WLANs. |
| Media Access Control (MAC) address filtering | A method for controlling access to a WLAN based on the device's MAC address. |
| open method | A wireless network mode in which no authentication is required. |
| preshared key (PSK) | The authentication model used in WPA that requires a secret key value to be entered into the AP and all approved wireless devices prior to communicating. |
| Wi-Fi Protected Access 2 (WPA2) | The second generation of WPA security from the Wi-Fi Alliance that addresses authentication and encryption on WLANs and is currently the most secure model for Wi-Fi security. |
| Counter Mode with Cipher Block Chaining Message Authentication Code Protocol (CCMP) | The encryption protocol used for WPA2 that specifies the use of a general-purpose cipher mode algorithm providing data privacy with AES. |
| Cipher Block Chaining Message Authentication Code (CBC-MAC) | A component of CCMP that provides data integrity and authentication. |
| enterprise method | Authentication for the WPA2 Enterprise model. |
| IEEE 802.1x | A standard, originally developed for wired networks, that provides a greater degree of security by implementing port-based authentication. |
| Extensible Authentication Protocol (EAP) | A framework for transporting authentication protocols that defines the format of the messages. |
| Protected EAP (PEAP) | An EAP method designed to simplify the deployment of 802.1x by using Microsoft Windows logins and passwords. |
| EAP-TLS | An Extensible Authentication Protocol that uses digital certificates for authentication. |
| EAP-TTLS | An Extensible Authentication Protocol that securely tunnels client password authentication within Transport Layer Security (TLS) records. |
| EAP-FAST | An Extensible Authentication Protocol that securely tunnels any credential form for authentication (such as a password or a token) using TLS. |
| WPA3 | The current generation of Wi-Fi Protected Access (WPA) whose goal is to deliver a suite of features to simplify security configuration for users while enhancing network security protections. |
| Simultaneous Authentication of Equals (SAE) | A component of WPA3 that is designed to increase security at the time of the handshake when the key is being exchanged. |
| site survey | An in-depth examination and analysis of a WLAN site. |
| wireless access point placement | Placing an AP in the optimum location. |
| heat map | A software tool that provides a visual representation of the wireless signal coverage and strength. |
| Wi-Fi analyzer | A software tool that helps to visualize the essential details of the wireless network. |
| channel overlays | Conflicting frequency channels in a Wi-Fi network. |
| Zigbee | A low-power, short-range, and low-data rate specification designed for occasional data or signal transmission from a sensor or IoT device. |
| 5G | The fifth-generation cellular wireless standard. |
| Narrowband Internet of Things (NB-IoT) | A low-power wide area network (LPWAN) radio technology standard. |
| baseband | The original frequency range of a transmission signal before it is converted to a different frequency range. |
| SIM card | An integrated circuit that securely stores information used to identify and authenticate the IoT device on a cellular network. |
| controller AP | An AP that is managed through a dedicated wireless LAN controller (WLC). |
| subscriber identity module (SIM) card | An integrated circuit that securely stores information used to identify and authenticate the IoT device on a cellular network. |
