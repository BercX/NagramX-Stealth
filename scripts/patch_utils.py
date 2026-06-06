import re
import shutil
import xml.sax.saxutils
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path


def log_ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def log_warn(msg: str) -> None:
    print(f"  ⚠️ {msg}")


def xml_escape_text(s: str) -> str:
    """Escape ``&``, ``<``, ``>`` for safe insertion into XML text nodes.

    Needed whenever a caller-supplied value (e.g. the app name) is spliced
    into ``<string>…</string>`` content - without this, a name like
    ``Rock & Roll`` would corrupt the resource file.
    """
    return xml.sax.saxutils.escape(s)


def smali_escape(s: str) -> str:
    """Escape a value for inclusion inside a smali string literal (``"…"``).

    Smali uses C-like escapes; mis-escaping ``"`` or ``\\`` inside a
    ``const-string`` breaks the assembler. Backslash must be escaped
    first so subsequent substitutions don't double-escape.
    """
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def log_change(desc: str, old: str, new: str) -> None:
    inline = f"{desc}: {old} → {new}"
    if "\n" in old or "\n" in new or len(inline) > shutil.get_terminal_size().columns:
        log_ok(desc)
    else:
        log_ok(inline)


@dataclass
class Match:
    """A regex hit inside a file. `text` is the matched substring."""

    path: Path
    start: int
    end: int
    text: str


def find_in_files(
    paths: Iterable[Path],
    pattern: re.Pattern[str],
    *,
    group: int = 0,
) -> list[Match]:
    """Collect every regex hit across *paths*.

    *group* picks which capture group's span/text lands in the ``Match`` -
    0 is the whole hit, 1+ picks a capture. Useful for "match with context,
    edit only the inner bit" patterns.
    """
    out: list[Match] = []
    for path in paths:
        content = path.read_text(encoding="utf-8")
        for m in pattern.finditer(content):
            out.append(Match(path, m.start(group), m.end(group), m.group(group)))
    return out


def _attr_re(name: str, value: str) -> str:
    """Regex fragment matching ``name="value"`` exactly."""
    return rf'{re.escape(name)}="{re.escape(value)}"'


def _attr_re_endswith(name: str, value: str) -> str:
    """Regex fragment matching ``name="…value"`` (value ends with *value*)."""
    return rf'{re.escape(name)}="[^"]*{re.escape(value)}"'


def _open_tag_re(
    tag: str,
    attrs: dict[str, str] | None,
    attrs_endswith: dict[str, str] | None = None,
) -> str:
    """Regex for an opening ``<tag ...>`` with exact and/or endswith attr constraints.

    Attributes may be in any order - each is checked via a non-consuming
    lookahead that scans the tag body, so we don't care which comes first.
    """
    if not attrs and not attrs_endswith:
        return rf"<{re.escape(tag)}(?:\s[^>]*)?>"
    parts: list[str] = []
    for k, v in (attrs or {}).items():
        parts.append(rf"(?=[^>]*\s{_attr_re(k, v)})")
    for k, v in (attrs_endswith or {}).items():
        parts.append(rf"(?=[^>]*\s{_attr_re_endswith(k, v)})")
    return rf"<{re.escape(tag)}{''.join(parts)}\s[^>]*>"


def find_element(
    paths: Iterable[Path],
    tag: str,
    attrs: dict[str, str] | None = None,
    attrs_endswith: dict[str, str] | None = None,
) -> list[Match]:
    """Find opening tags ``<tag ...>`` whose attributes match.

    ``Match.text`` is the entire opening tag.

    ``attrs`` entries require an exact ``name="value"`` match; ``attrs_endswith``
    entries require the attribute value to end with the given suffix (useful for
    matching fully-qualified class names - e.g. ``{"android:name": ".BlueIcon"}``).
    """
    pattern = re.compile(_open_tag_re(tag, attrs, attrs_endswith))
    return find_in_files(paths, pattern)


def find_element_text(
    paths: Iterable[Path],
    tag: str,
    attrs: dict[str, str] | None = None,
    attrs_endswith: dict[str, str] | None = None,
) -> list[Match]:
    """Find inner text between ``<tag ...>`` and ``</tag>``.

    ``Match.text`` is only the inner content, so edits stay scoped inside the
    element and don't touch the surrounding tags.
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
    """Find the *value* span of ``attr`` inside matching ``<tag ...>`` tags.

    ``Match.text`` is just the attribute value (without the surrounding
    quotes), so the transform handed to ``apply_patches`` gets the bare
    value and returns the bare replacement.
    """
    attr_re = re.compile(rf'{re.escape(attr)}="([^"]*)"')
    out: list[Match] = []
    for element in find_element(paths, tag, attrs, attrs_endswith):
        m = attr_re.search(element.text)
        if not m:
            continue
        out.append(
            Match(
                element.path,
                element.start + m.start(1),
                element.start + m.end(1),
                m.group(1),
            )
        )
    return out


def find_smali_files(work_dir: Path, glob: str) -> list[Path]:
    """Return every smali file matching *glob*, across all ``smali*`` dirs.

    Multidex splits classes across ``smali``, ``smali_classes2``, etc. The
    target class may live in any of them - patching only the first hit
    would silently miss siblings. In the common case (one class = one
    file) this returns a single path.
    """
    return [
        match
        for smali_dir in sorted(work_dir.glob("smali*"))
        for match in smali_dir.glob(glob)
    ]


def find_in_smali(work_dir: Path, glob: str, pattern: str) -> list[Match]:
    """Collect every regex hit in smali files matching *glob*.

    Thin convenience layer: compiles *pattern* and feeds the smali file list
    into :func:`find_in_files`. Prefer this over calling `find_in_files`
    directly so callers don't need to know about the ``smali*`` multidex layout.
    """
    return find_in_files(find_smali_files(work_dir, glob), re.compile(pattern))


def verify_smali_contains(work_dir: Path, glob: str, pattern: str, desc: str) -> bool:
    """Precondition check: a smali pattern must exist somewhere.

    Use before a patch that *injects* a reference to a symbol - if the
    target went away upstream (rename, removal), fail the build early
    instead of writing a dangling reference that would only surface as
    a runtime crash when the app is installed.
    """
    if find_in_smali(work_dir, glob, pattern):
        log_ok(f"{desc} - present")
        return True
    log_warn(f"{desc} - missing (upstream may have renamed)")
    return False


def apply_patches(
    matches: list[Match], transform: Callable[[str], str], desc: str
) -> bool:
    """Run *transform* on every match's text; write and log when it differs.

    Returns True iff the locator matched anything (even when every transform
    was a no-op). Returns False only when nothing matched at all - that
    means the pattern is stale (wrong APK, or upstream renamed things) and
    the caller should treat it as a build failure.

    A matched-but-no-op outcome is a legitimate idempotent re-run (target
    already in the desired state) and is reported as success.
    """
    if not matches:
        log_warn(f"{desc} - not matched")
        return False

    by_path: dict[Path, list[Match]] = defaultdict(list)
    for m in matches:
        by_path[m.path].append(m)

    any_changed = False
    for path, file_matches in by_path.items():
        content = path.read_text(encoding="utf-8")
        file_matches.sort(key=lambda fm: fm.start, reverse=True)
        # Reverse splicing is safe only when matches don't overlap; callers'
        # finders don't produce overlaps, but make that invariant explicit.
        for prev, curr in zip(file_matches, file_matches[1:]):
            assert curr.end <= prev.start, (
                f"overlapping matches in {path}: {curr} vs {prev}"
            )
        file_changed = False
        for m in file_matches:
            new = transform(m.text)
            if new == m.text:
                continue
            content = content[: m.start] + new + content[m.end :]
            log_change(desc, m.text, new)
            file_changed = True
        if file_changed:
            path.write_text(content, encoding="utf-8")
            any_changed = True

    if not any_changed:
        log_ok(f"{desc} - already applied")
    return True


def patch_smali(
    work_dir: Path, glob: str, pattern: str, replacement: str, desc: str
) -> bool:
    """Replace every regex hit of *pattern* with *replacement* in smali files matching *glob*."""
    return apply_patches(
        find_in_smali(work_dir, glob, pattern), lambda _: replacement, desc
    )


def patch_xml_string(res_dir: Path, name: str, transform: Callable[[str], str]) -> bool:
    """Transform the inner text of ``<string name="...">`` across all locales."""
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
    """Regex-replace inside the opening ``<application ...>`` tag only.

    Scope is the attributes on the tag itself - child elements
    (``<activity>``, ``<service>``, etc.) are NOT touched. *pattern* and
    *replacement* are passed directly to :func:`re.sub`, so back-references
    like ``\\1`` work and one call can cover multiple related variants
    (e.g. an icon that has ``_round`` and non-``_round`` forms).
    """
    return apply_patches(
        find_element([manifest_path], "application"),
        lambda t: re.sub(pattern, replacement, t),
        desc,
    )


def patch_activity_alias_enabled(manifest_path: Path, suffix: str, value: bool) -> bool:
    """Set ``android:enabled`` on an ``<activity-alias>`` whose name ends with *suffix*."""
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
