#!/usr/bin/env python3
"""Patch a decompiled NagramX APK to look like stock Telegram.

Usage: patch_apk.py <work_dir> <app_name>
"""

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


def patch_app_name(work_dir: Path, res_dir: Path, app_name: str) -> bool:
    """Rename all visible NagramX/Nagram strings to app_name.

    Returns True iff every locator matched. A False means at least one
    pattern is stale and the caller should treat the build as failed.
    """
    print(f"📝 App name → '{app_name}'")
    escaped_xml_name = xml_escape_text(app_name)
    escaped_smali_name = smali_escape(app_name)

    results = [
        patch_xml_string(res_dir, tag, lambda _: escaped_xml_name)
        for tag in ("NagramX", "AppName", "Nagram", "NekoX")
    ]
    # _strip_nagram_branding keys off Latin "Nagram X" and Arabic "ناگرام";
    # localized transliterations (e.g. "Нагрхам") pass through unchanged -
    # closing that gap needs per-locale string audits.
    # Passing the already-escaped name is safe because the literals replaced
    # ("Nagram X", "ناگرام", "N-", " N", "-N") contain no XML-special chars,
    # so the substitution preserves a valid escaped XML inner text.
    results += [
        patch_xml_string(
            res_dir, tag, lambda t: _strip_nagram_branding(t, escaped_xml_name)
        )
        for tag in ("CustomTitleHint", "NekoSettings")
    ]
    results += [
        patch_smali(
            work_dir, glob, old, old.replace(_BRAND_NAME, escaped_smali_name), desc
        )
        for glob, old, desc in (
            ("**/nagram/NaConfig.smali", f'"{_BRAND_NAME}"', "NaConfig default"),
            ("**/utils/AndroidUtil.smali", f'"{_BRAND_NAME} v"', "Version string"),
        )
    ]
    return all(results)


def patch_icons(work_dir: Path, manifest_path: Path) -> bool:
    """Replace launcher, notification, and default icons with stock Telegram.

    Returns True iff every locator matched. A False means at least one
    pattern is stale and the caller should treat the build as failed.
    """
    print("🎨 Icons → stock Telegram")

    notification_icon_pattern = (
        r"->(nagramx_notification|nagram_notification|neko_notification):I"
    )
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
            notification_icon_pattern,
            "->notification:I",
            service,
        )
        for service in ("NotificationsService", "NotificationsController")
    ]
    # Verify TELEGRAM enum member exists before injecting a reference to it;
    # if upstream renamed it, a dangling reference would only crash at runtime.
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
    if len(sys.argv) < 3:
        print("Usage: patch_apk.py <work_dir> <app_name>", file=sys.stderr)
        sys.exit(1)

    work_dir = Path(sys.argv[1])
    app_name = sys.argv[2]
    res_dir = work_dir / "res"
    manifest_path = work_dir / "AndroidManifest.xml"

    name_ok = patch_app_name(work_dir, res_dir, app_name)
    icons_ok = patch_icons(work_dir, manifest_path)

    if not (name_ok and icons_ok):
        print(
            "❌ One or more patches did not match - APK may be an unexpected version",
            file=sys.stderr,
        )
        sys.exit(1)

    print("✅ All patches applied")


if __name__ == "__main__":
    main()
