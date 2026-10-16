<div align="center">

<img src="https://raw.githubusercontent.com/KANDIYARR/iotics/main/custom_components/iotics/brand/icon.png" alt="Iotics" width="112" height="112">

# Iotics for Home Assistant

**Your Iotics panels. Your Home Assistant dashboard.**

Discover your devices, control supported switches and fans, and bring them into your Home Assistant scenes and automations.

[![Validation](https://github.com/KANDIYARR/iotics/actions/workflows/validate.yml/badge.svg)](https://github.com/KANDIYARR/iotics/actions/workflows/validate.yml)
[![Release](https://img.shields.io/github/v/release/KANDIYARR/iotics?color=0088cc)](https://github.com/KANDIYARR/iotics/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![HACS: Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](#installation)

[Installation](#installation) · [Supported features](#supported-features) · [Troubleshooting](#troubleshooting) · [Report an issue](https://github.com/KANDIYARR/iotics/issues)

</div>

---

An **unofficial, cloud-connected integration** for Iotics panels. Sign in with your existing Iotics account to discover devices and receive MQTT updates. No separate MQTT broker is required.

> **Before you install**
> You need your Iotics account **and a private `iotics_app_profile.json` connection file**. The profile is not included in this repository, and this project does not currently provide an automated extractor. Email and password alone are not enough to complete setup.

## Supported features

| Feature | Current support |
| :--- | :--- |
| Account connection | Sign-in, automatic device discovery and reauthentication |
| Switches and plugs | On/off for channels reported as `bN` |
| Fans | Power control; four speed levels for eligible non-BLDC fans |
| BLDC fans | Power only — speed adjustment is not supported |
| Device updates | MQTT feedback, reconnects and availability detection |
| Scenes and automations | Use the entities in Home Assistant's native tools |

**Keep using the Iotics app** for pairing, curtains, dimmers, BLDC speed, firmware updates and child locks. Importing vendor scenes and schedules is not supported.

> **Validation status:** Account login, discovery, MQTT connection and hardware-status feedback were checked live. No on/off or speed commands were sent during validation, so physical actuation remains unverified.

## Installation

### 1 · Download through HACS

Open **HACS → ⋮ → Custom repositories** and add:

| Setting | Value |
| :--- | :--- |
| Repository | `https://github.com/KANDIYARR/iotics` |
| Type | **Integration** |

Find **Iotics** in HACS and select **Download**.

<details>
<summary><strong>Prefer manual installation?</strong></summary>

Download the [latest release source](https://github.com/KANDIYARR/iotics/releases) and copy its `custom_components/iotics` folder into your Home Assistant configuration folder. Then continue below.

</details>

### 2 · Add your private connection profile

Copy `iotics_app_profile.json` into the **same folder as `configuration.yaml`**:

```text
Home Assistant configuration folder
├── configuration.yaml
├── iotics_app_profile.json       ← Your private connection profile
└── custom_components/
    └── iotics/
        ├── manifest.json
        ├── config_flow.py
        └── brand/
            └── icon.png
```

This is the configuration folder on the machine running Home Assistant. In a container, it is `/config`; on the host, use the folder mapped to that location. If you use File editor, upload the profile beside `configuration.yaml`.

The profile contains app connection settings recovered from the user's own Iotics 4.9 package during local analysis. **Keep it private. Do not upload it, account credentials or configuration backups to GitHub.**

### 3 · Restart and sign in

1. **Restart Home Assistant.**
2. Open **Settings → Devices & services → Add integration**.
3. Search for **Iotics**.
4. Enter your Iotics **email and password**.
5. Wait for discovery and hardware status, then add the available entities to your dashboard.

You can rename entities, assign rooms, and use supported controls in Home Assistant scenes and automations.

## How device updates work

| Stage | What happens |
| :--- | :--- |
| Sign in | Your Iotics account supplies an access token and device list. |
| Connect | The integration subscribes to MQTT topics for devices returned by your account. |
| Show state | Cloud values are provisional until the channel sends hardware feedback. |
| Send a command | The integration waits up to **10 seconds** for matching feedback. |
| Keep current | Device discovery refreshes every **5 minutes**; status queries run every **minute**. |

Commands are not queued for replay while offline. A timeout means confirmation was not received — the device may still have acted. Check its actual state before retrying.

## Troubleshooting

| What you see | What to check |
| :--- | :--- |
| **Missing or invalid profile** | Put `iotics_app_profile.json` beside `configuration.yaml`, not inside `custom_components`. |
| **Authentication failed** | Verify the same credentials and account verification in the Iotics app. |
| **Device unavailable** | Check the panel in the Iotics app and outbound HTTPS/WSS access on port 443. Availability requires valid hardware feedback. |
| **No fan speed slider** | Expected for BLDC fans in this version. |
| **Command confirmation timed out** | Check the physical device or the Iotics app before sending another command. |
| **Logo missing in HACS search** | Some HACS versions use the central branding service instead of the bundled icon; see below. |

<details>
<summary><strong>About the logo</strong></summary>

Home Assistant **2026.3+** supports the icon bundled in `custom_components/iotics/brand/icon.png` after installation and restart. The image also appears on this README and the HACS repository details page.

Some HACS search lists still use the central branding service and may show a placeholder. This repository cannot override that URL. See [Home Assistant brand-image support](https://developers.home-assistant.io/docs/core/integration/brand_images/) and [the HACS tracking issue](https://github.com/hacs/integration/issues/5402).

</details>

<details>
<summary><strong>Account storage and diagnostics</strong></summary>

Account credentials are stored in Home Assistant's configuration-entry storage. Protect your configuration backups. Diagnostic exports omit account identifiers, device tokens and connection credentials.

</details>

### Troubleshooting a command timeout

Version 0.1.2 matches the app's first-byte status decoding and distinguishes send failures from missing feedback. It also includes anonymous command/feedback counters in diagnostics. This does not establish that all switch models respond to the implemented commands.

If a control still fails, note whether the physical load changed, then open the Iotics integration menu under **Settings → Devices & services** and download its diagnostics. The counters distinguish command echoes, actual channel feedback, retained messages, and timeouts without exposing topics, device tokens, credentials, or payloads.

## Development and verification

**23 offline tests passed** using Python 3.12.14 and Home Assistant Core 2024.11.3. This is a compatibility-test baseline, not a recommendation to install an older Home Assistant version. Current production installation compatibility has not yet been verified.

```sh
python -m pip install -r tests_ha/requirements.txt
python -m pytest tests_ha -q
```

GitHub Actions run Home Assistant's **hassfest** and **HACS validation**. The central brands-catalog check is excluded because this integration bundles its icon locally.

Found an issue? [Open a GitHub issue](https://github.com/KANDIYARR/iotics/issues) with your Home Assistant version, device model and a description of what happened. Remove credentials and private connection settings from any logs or screenshots.

---

<div align="center">

**Maintained by Vinoth Sakthivel**<br>
[vinoth@kandiyar.com](mailto:vinoth@kandiyar.com) · [MIT License](LICENSE) · [Releases](https://github.com/KANDIYARR/iotics/releases)

</div>

This project is independent of Iotics and is available as a **HACS custom repository**, not part of HACS's default catalog. The MIT license covers this project's code. The Iotics logo and trademarks remain the property of their respective owner and do not imply endorsement.
