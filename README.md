# Iotics for Home Assistant

**Author:** Vinoth Sakthivel  
**Email:** [vinoth@kandiyar.com](mailto:vinoth@kandiyar.com)

Unofficial Home Assistant integration for Iotics panels. Sign in with your Iotics app account to discover devices and receive cloud MQTT updates. No separate MQTT broker is required.

## Install with HACS

1. Open **HACS → ⋮ → Custom repositories**.
2. Add `https://github.com/KANDIYARR/iotics-home-assistant` with type **Integration**.
3. Find **Iotics** in HACS and download it.
4. Copy your private `iotics_app_profile.json` into the Home Assistant configuration folder, alongside `configuration.yaml`.
5. Restart Home Assistant.
6. Open **Settings → Devices & services → Add integration → Iotics** and enter your Iotics account email and password.

The private connection profile is required and is **not distributed in this repository**. It contains app connection credentials obtained from the user's own Iotics 4.9 package during local analysis. This repository alone does not supply those credentials or an automated profile extractor. Existing users with that locally prepared profile can use it. Do not upload your profile, account credentials or configuration backups to GitHub.

For manual installation, copy `custom_components/iotics` into your Home Assistant configuration folder and follow steps 4–6.

## Features and limits

- Automatic account device discovery and reauthentication.
- Switch/plug channels reported as `bN` and fan power.
- Four-level speed control for non-BLDC fans with reported level channels.
- MQTT feedback, reconnects and availability detection.
- Use the entities in Home Assistant scenes and automations.

BLDC fans currently support **power only**. Curtains, dimmers, pairing, firmware updates, child locks, vendor scene/schedule import and BLDC speed are not implemented. Use the Iotics app for these functions.

Cloud snapshot values are provisional until hardware feedback arrives. Commands wait up to ten seconds for matching feedback and are not queued for offline replay. A timeout does not prove the device failed to act; check its actual state before retrying. Discovery refreshes every five minutes; status queries run every minute.

## Validation

Account login, device discovery, signed MQTT connection and a hardware-status response were checked live against an Iotics 4.9 account. No on/off or speed commands were sent during validation. Physical actuation remains unverified.

15 offline tests passed on Python 3.12.14 and Home Assistant Core 2024.11.3. That release is a compatibility-test baseline, not a recommendation to install an older Home Assistant version. Current production installation compatibility has not yet been verified.

```sh
python -m pip install -r tests_ha/requirements.txt
python -m pytest tests_ha -q
```

## Troubleshooting

- **Missing profile:** place `iotics_app_profile.json` next to `configuration.yaml`, not inside `custom_components`.
- **Authentication failure:** verify credentials and account verification in the Iotics app.
- **Unavailable:** check panel connectivity and outbound HTTPS/WSS access on port 443. Valid hardware feedback is required for availability.
- **No fan speed slider:** expected for BLDC fans in this release.

Account credentials are stored in Home Assistant configuration-entry storage. Protect backups. Diagnostic exports omit account identifiers, device tokens and connection credentials.

This project is independent of Iotics and is intended as a HACS **custom repository**, not an integration included in HACS's default catalog.
