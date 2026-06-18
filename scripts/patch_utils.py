"""Helpers for patching decompiled files by editing matched spans in place.

There is deliberately no XML or smali parser here. A parser rewrites a whole
file when it saves, whereas this project is meant to stay auditable through
small, easy-to-read diffs, so each edit touches only the bytes it has to.
"""

import re
import shutil
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape_text  # noqa: F401 (re-export)


def log_ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def log_warn(msg: str) -> None:
    print(f"  ⚠️ {msg}")


def log_change(desc: str, old: str, new: str) -> None:
    inline = f"{desc}: {old} → {new}"
    if "\n" in old or "\n" in new or len(inline) > shutil.get_terminal_size().columns:
        log_ok(desc)
    else:
        log_ok(inline)


_SMALI_ESCAPES = str.maketrans({"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r"})


def smali_escape(s: str) -> str:
    """Escape a value for a smali string literal."""
    return s.translate(_SMALI_ESCAPES)


@dataclass
class Match:
    """A regex hit inside a file. `text` is the matched substring."""

    path: Path
    start: int
    end: int
    text: str


def find_in_files(
    paths: Iterable[Path], pattern: re.Pattern[str], *, group: int = 0
) -> list[Match]:
    """Search several files and return every place the pattern matches.

    By default, each result covers the whole match. Set *group* to a capture
    number to record only that part instead - useful when the pattern needs
    surrounding context to match but only its inner part should be edited.
    """
    return [
        Match(path, m.start(group), m.end(group), m.group(group))
        for path in paths
        for m in pattern.finditer(path.read_text(encoding="utf-8"))
    ]


def _attr_re(name: str, value: str, value_prefix: str = "") -> str:
    """Build the regex that matches an attribute written as ``name="value"``.

    A *value_prefix* loosens the value side: passing ``[^"]*`` makes it match
    any value that merely ends with the given text.
    """
    return rf'{re.escape(name)}="{value_prefix}{re.escape(value)}"'


def _open_tag_re(
    tag: str,
    attrs: dict[str, str] | None,
    attrs_endswith: dict[str, str] | None = None,
) -> str:
    """Build the regex that matches an opening tag.

    Each attribute filter becomes a lookahead, so the tag matches no matter
    what order its attributes happen to appear in.
    """
    lookaheads = "".join(
        rf"(?=[^>]*\s{_attr_re(k, v, prefix)})"
        for constraints, prefix in ((attrs, ""), (attrs_endswith, '[^"]*'))
        for k, v in (constraints or {}).items()
    )
    if not lookaheads:
        return rf"<{re.escape(tag)}(?:\s[^>]*)?>"
    return rf"<{re.escape(tag)}{lookaheads}\s[^>]*>"


def find_element(
    paths: Iterable[Path],
    tag: str,
    attrs: dict[str, str] | None = None,
    attrs_endswith: dict[str, str] | None = None,
) -> list[Match]:
    """Find opening tags, keeping the whole tag as the match.

    A tag is kept only if its attributes pass the given filters: *attrs* must
    match a value exactly, *attrs_endswith* only needs the value to end with
    the given text. The suffix form is handy for class names that carry a
    package prefix - ``{"android:name": ".BlueIcon"}`` matches regardless of
    which package the class sits in.
    """
    pattern = re.compile(_open_tag_re(tag, attrs, attrs_endswith))
    return find_in_files(paths, pattern)


def find_element_text(
    paths: Iterable[Path],
    tag: str,
    attrs: dict[str, str] | None = None,
    attrs_endswith: dict[str, str] | None = None,
) -> list[Match]:
    """Find the text sitting between an opening and closing tag.

    The match covers only that inner text, never the surrounding tags, so a
    replacement changes the content and leaves the markup intact. Tags are
    selected by the same attribute filters used to find a tag by its name.
    """
    pattern = re.compile(
        rf"{_open_tag_re(tag, attrs, attrs_endswith)}(.*?)</{re.escape(tag)}>",
        re.DOTALL,
    )
    return find_in_files(paths, pattern, group=1)


def find_attribute(
    paths: Iterable[Path],
    tag: str,
    attr: str,
    attrs: dict[str, str] | None = None,
    attrs_endswith: dict[str, str] | None = None,
) -> list[Match]:
    """Find one attribute's value inside the matching tags.

    The match covers only the value, without the surrounding quotes, so a
    replacement changes that value and leaves the rest of the tag alone.
    """
    attr_re = re.compile(rf'{re.escape(attr)}="([^"]*)"')
    return [
        Match(e.path, e.start + m.start(1), e.start + m.end(1), m.group(1))
        for e in find_element(paths, tag, attrs, attrs_endswith)
        if (m := attr_re.search(e.text))
    ]


def find_smali_files(work_dir: Path, glob: str) -> list[Path]:
    """Find every smali file matching the glob.

    A decompiled APK that uses multidex splits its classes across several
    folders (``smali``, ``smali_classes2``, and so on), and the wanted class
    may sit in any of them, so all of those folders are searched.
    """
    return [
        match
        for smali_dir in sorted(work_dir.glob("smali*"))
        for match in smali_dir.glob(glob)
    ]


def find_in_smali(work_dir: Path, glob: str, pattern: str) -> list[Match]:
    """Search every smali file matching the glob for the given pattern."""
    return find_in_files(find_smali_files(work_dir, glob), re.compile(pattern))


def verify_smali_contains(work_dir: Path, glob: str, pattern: str, desc: str) -> bool:
    """Confirm a symbol is still present in the decompiled code.

    A guard for edits that point at an existing symbol: if a newer upstream
    release renamed or removed it, the build can stop right here with a clear
    message instead of producing an app that crashes only once installed.
    """
    if find_in_smali(work_dir, glob, pattern):
        log_ok(f"{desc} - present")
        return True
    log_warn(f"{desc} - missing (upstream may have renamed)")
    return False


def verify_xml_contains(
    paths: Iterable[Path], tag: str, pattern: str, desc: str
) -> bool:
    """Confirm the wanted text is present inside a matching XML tag.

    A guard for edits that target a tag which is always there: such an edit
    can't tell a real change from a no-op when a newer upstream release renames
    the value it meant to replace, so the build can stop right here instead of
    publishing a half-patched APK.
    """
    if any(re.search(pattern, e.text) for e in find_element(list(paths), tag)):
        log_ok(f"{desc} - present")
        return True
    log_warn(f"{desc} - missing (upstream may have renamed it)")
    return False


def apply_patches(
    matches: list[Match], transform: Callable[[str], str], desc: str
) -> bool:
    """Run the transform on every match and save the files whose text changed.

    Returns True when the search found at least one place to act on, even if
    the transform left every one of them unchanged - that happens when the
    files are already in the wanted state, so running again is harmless.

    Returns False when the search found nothing at all. That means the thing
    being looked for is no longer in the files, so the patch has gone stale.
    """
    if not matches:
        log_warn(f"{desc} - not matched")
        return False

    by_path: dict[Path, list[Match]] = defaultdict(list)
    for m in matches:
        by_path[m.path].append(m)

    any_changed = False
    for path, file_matches in by_path.items():
        # Splice back-to-front so earlier offsets stay valid; non-overlap
        # makes this safe.
        file_matches.sort(key=lambda fm: fm.start, reverse=True)
        assert all(b.end <= a.start for a, b in pairwise(file_matches)), (
            f"overlapping matches in {path}"
        )
        original = content = path.read_text(encoding="utf-8")
        for m in file_matches:
            new = transform(m.text)
            if new != m.text:
                content = content[: m.start] + new + content[m.end :]
                log_change(desc, m.text, new)
        if content != original:
            path.write_text(content, encoding="utf-8")
            any_changed = True

    if not any_changed:
        log_ok(f"{desc} - already applied")
    return True


def patch_smali(
    work_dir: Path, glob: str, pattern: str, replacement: str, desc: str
) -> bool:
    """Replace every match of the pattern with the replacement text, across
    the smali files selected by the glob."""
    return apply_patches(
        find_in_smali(work_dir, glob, pattern), lambda _: replacement, desc
    )


def patch_xml_string(res_dir: Path, name: str, transform: Callable[[str], str]) -> bool:
    """Transform the text of a named string resource in every locale.

    A localized app keeps one ``strings.xml`` per language, so the named entry
    is edited in all of them at once.
    """
    return apply_patches(
        find_element_text(
            sorted(res_dir.glob("values*/strings.xml")),
            "string",
            {"name": name},
        ),
        transform,
        name,
    )


def patch_application_attrs(
    manifest_path: Path, pattern: str, replacement: str, desc: str
) -> bool:
    """Run a search-and-replace limited to the opening ``<application>`` tag.

    Only the attributes on that tag itself are touched; the activities,
    services and other child elements inside it are left alone. The
    replacement may refer back to captured groups from the pattern.
    """
    return apply_patches(
        find_element([manifest_path], "application"),
        lambda t: re.sub(pattern, replacement, t),
        desc,
    )


def patch_activity_alias_enabled(manifest_path: Path, suffix: str, value: bool) -> bool:
    """Enable or disable the activity-alias whose name ends with the suffix."""
    return apply_patches(
        find_attribute(
            [manifest_path],
            "activity-alias",
            "android:enabled",
            attrs_endswith={"android:name": f".{suffix}"},
        ),
        lambda _: str(value).lower(),
        suffix,
    )
