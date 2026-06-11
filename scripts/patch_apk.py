#!/usr/bin/env python3
"""Patch a decompiled NagramX APK to look like stock Telegram."""

import argparse
import sys
from pathlib import Path

from patch_utils import (
    patch_activity_alias_enabled,
    patch_application_attrs,
    patch_smali,
    patch_xml_string,
    smali_escape,
    verify_smali_contains,
    xml_escape_text,
)

_BRAND_NAME = "Nagram X"


def _strip_nagram_branding(text: str, app_name: str) -> str:
    """Remove Nagram-specific prefixes/suffixes and replace brand names with app_name."""
    value = text.replace(_BRAND_NAME, app_name)
    value = value.replace("ناگرام", app_name)
    value = value.removeprefix("N-")
    value = value.removesuffix(" N")
    value = value.removesuffix("-N")
    return value


def patch_app_name(work_dir: Path, app_name: str) -> bool:
    """Rename every visible NagramX/Nagram string to the chosen app name."""
    print(f"📝 App name → '{app_name}'")
    res_dir = work_dir / "res"
    xml_name = xml_escape_text(app_name)
    smali_name = smali_escape(app_name)

    results = [
        patch_xml_string(res_dir, tag, lambda _: xml_name)
        for tag in ("NagramX", "AppName", "Nagram", "NekoX")
    ]
    results += [
        patch_xml_string(res_dir, tag, lambda t: _strip_nagram_branding(t, xml_name))
        for tag in ("CustomTitleHint", "NekoSettings")
    ]
    results += [
        patch_smali(work_dir, glob, old, old.replace(_BRAND_NAME, smali_name), desc)
        for glob, old, desc in (
            ("**/nagram/NaConfig.smali", f'"{_BRAND_NAME}"', "NaConfig default"),
            ("**/utils/AndroidUtil.smali", f'"{_BRAND_NAME} v"', "Version string"),
        )
    ]
    return all(results)


def patch_icons(work_dir: Path) -> bool:
    """Replace the launcher, notification, and default icons with stock Telegram."""
    print("🎨 Icons → stock Telegram")
    manifest_path = work_dir / "AndroidManifest.xml"

    results = [
        patch_application_attrs(
            manifest_path,
            r"@mipmap/ic_launcher_nagram_blue(_round)?",
            r"@mipmap/ic_launcher_dr\1",
            "Application icons",
        ),
        patch_activity_alias_enabled(manifest_path, "BlueIcon", False),
        patch_activity_alias_enabled(manifest_path, "TelegramIcon", True),
    ]
    results += [
        patch_smali(
            work_dir,
            f"**/messenger/{service}.smali",
            r"->(?:nagramx|nagram|neko)_notification:I",
            "->notification:I",
            service,
        )
        for service in ("NotificationsService", "NotificationsController")
    ]
    # Make sure the stock Telegram icon entry still exists before the next edit points at it.
    results += [
        verify_smali_contains(
            work_dir,
            "**/LauncherIconController$LauncherIcon.smali",
            r"enum TELEGRAM:",
            "LauncherIconController.LauncherIcon.TELEGRAM",
        ),
        patch_smali(
            work_dir,
            "**/LauncherIconController.smali",
            r"LauncherIconController\$LauncherIcon;->BLUE:",
            "LauncherIconController$LauncherIcon;->TELEGRAM:",
            "LauncherIconController default",
        ),
    ]
    return all(results)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("work_dir", type=Path, help="apktool output directory")
    parser.add_argument("app_name", help="replacement app name")
    args = parser.parse_args()

    if not all(
        [patch_app_name(args.work_dir, args.app_name), patch_icons(args.work_dir)]
    ):
        sys.exit(
            "❌ One or more patches did not match - APK may be an unexpected version"
        )
    print("✅ All patches applied")


if __name__ == "__main__":
    main()
