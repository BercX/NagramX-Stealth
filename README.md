[![Version](https://img.shields.io/github/v/release/BercX/NagramX-Stealth?label=version&display_name=release)](../../releases/latest)
[![Release date](https://img.shields.io/github/release-date/BercX/NagramX-Stealth)](../../releases/latest)

# NagramX-Stealth

[NagramX](https://github.com/risin42/NagramX) that looks and feels like stock Telegram. Builds automatically on every upstream release.

## Installation and updates

> [!IMPORTANT]
> The APK is re-signed, so it is incompatible with the original NagramX. If you have it installed, **uninstall it first**. The built-in updater also won't work because it downloads the original APK.

**Option 1 (recommended).** Install [Obtainium](https://github.com/ImranR98/Obtainium) and add this repository. It will handle both the initial install and future updates automatically.

<a href="https://apps.obtainium.imranr.dev/redirect.html?r=obtainium://add/https://github.com/BercX/NagramX-Stealth"><img src="https://raw.githubusercontent.com/ImranR98/Obtainium/main/assets/graphics/badge_obtainium.png" alt="Get it on Obtainium" height="50"></a>

**Option 2.** Download the APK from the [Releases](../../releases) page and install it manually. To update, install the new version over the existing one.

<details>
<summary>How to preserve settings when reinstalling</summary>

**Before uninstalling (export):**
1. Go to **Settings → N-Settings → Export Settings**. The settings file will be sent to your **Saved Messages**.

**After installing (import):**
1. Log in to your account.
2. Open **Saved Messages** and tap the previously exported settings file.

> Alternatively, you can use cloud sync: **Settings → N-Settings → Cloud Settings** (icon in the top right corner).

</details>

<details>
<summary>How to disable update notifications</summary>

The built-in updater queries the upstream NagramX repository, so its update prompts will never succeed on this build anyway (the signatures don't match). To silence them:

1. Open **Settings** and scroll to the very bottom.
2. Tap the **Telegram vX.Y.Z (build_number)** row.
3. Tap **Update Channel** and select **OFF**.

</details>

## What's changed

- **App name and strings** - app name, menu items and other strings containing "Nagram" renamed to look like stock Telegram
- **Icons** - launcher and notification icons replaced with stock Telegram

## Security

- **Fully automated builds** - every APK is built by GitHub Actions on GitHub-hosted runners. The full pipeline is defined in [`build.yml`](.github/workflows/build.yml) and [`patch_apk.py`](scripts/patch_apk.py) - anyone can audit it.
- **SHA-256 checksums** - each run publishes the APK checksum in the job summary, so you can verify the downloaded file matches.
- **Auditable patches** - each run publishes a full diff of the decompiled APK (before vs after patching) as a build artifact, so you can see exactly which bytes were touched.
- **Immutable releases** - published releases cannot be altered or replaced. Each release links to the action run that built it, and vice versa.
- **Build attestations** - each release includes [Sigstore](https://www.sigstore.dev/) provenance attestations. You can verify any APK using [GitHub CLI](https://cli.github.com/):
  ```shell
  gh attestation verify <file>.apk --repo BercX/NagramX-Stealth
  ```


## Disclaimer

This is a hobby project with no guarantees of timely updates or support. If you experience any bugs, try reproducing them with the [original NagramX](https://github.com/risin42/NagramX) first.
