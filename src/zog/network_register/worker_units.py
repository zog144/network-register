"""Stage reviewed systemd units; never install, enable or start them.

The immutable source provides templates only. The deployment owner selects the
actual application's interpreter, service UID/GID, vault environment and
persistent directories from installed/attested configuration.
"""
import argparse
import hashlib
from importlib import resources
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

TEMPLATE_ROOT = resources.files("zog.network_register").joinpath("systemd")
FIELDS = frozenset({
    "schema", "python", "working_directory", "environment_file",
    "state_directory", "receipt_directory", "service_user", "service_group",
})
PATH_RE = re.compile(r"/[A-Za-z0-9_./@+:-]+\Z")
NAME_RE = re.compile(r"[a-z_][a-z0-9_-]{0,62}\Z")


class UnitSelectionError(ValueError):
    pass


def _path(value):
    if (type(value) is not str or not PATH_RE.fullmatch(value)
            or value in ("/", "/etc", "/usr", "/tmp")
            or ".." in PurePosixPath(value).parts
            or "//" in value or "% " in value):
        raise UnitSelectionError("invalid-selected-path")
    return value


def _name(value):
    if type(value) is not str or not NAME_RE.fullmatch(value):
        raise UnitSelectionError("invalid-service-identity")
    return value


def render_units(selection, *, mode="inspect"):
    """Render deployment-bound units, without any filesystem changes."""
    if (type(selection) is not dict or set(selection) != FIELDS
            or selection["schema"] != 1 or type(selection["schema"]) is not int):
        raise UnitSelectionError("invalid-selection")
    if mode not in ("inspect", "apply"):
        raise UnitSelectionError("invalid-mode")
    mapping = {
        "PYTHON": _path(selection["python"]),
        "WORKING_DIRECTORY": _path(selection["working_directory"]),
        "ENVIRONMENT_FILE": _path(selection["environment_file"]),
        "STATE_DIRECTORY": _path(selection["state_directory"]),
        "RECEIPT_DIRECTORY": _path(selection["receipt_directory"]),
        "SERVICE_USER": _name(selection["service_user"]),
        "SERVICE_GROUP": _name(selection["service_group"]),
        "MODE_ARG": "" if mode == "inspect" else "--apply",
    }
    if selection["python"].endswith("/"):
        raise UnitSelectionError("invalid-selected-interpreter")
    files = {}
    for suffix in ("service", "timer"):
        name = "zog-shared-dns-worker." + suffix
        template = TEMPLATE_ROOT.joinpath(name + ".in").read_text(encoding="utf-8")
        for key, value in mapping.items():
            template = template.replace("@" + key + "@", value)
        if re.search(r"@[A-Z_]+@", template):
            raise UnitSelectionError("unresolved-template-field")
        files[name] = "\n".join(line.rstrip() for line in template.splitlines()) + "\n"
    # A selected/apply service is not installed or armed by rendering it.
    return files


def _staging_directory(path):
    p = Path(path)
    if not p.is_absolute():
        raise UnitSelectionError("invalid-staging-directory")
    try:
        fd = os.open(p, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        st = os.fstat(fd)
        if (not stat.S_ISDIR(st.st_mode) or st.st_uid != os.geteuid()
                or stat.S_IMODE(st.st_mode) != 0o700):
            raise UnitSelectionError("unsafe-staging-directory")
        return fd
    except OSError:
        raise UnitSelectionError("unavailable-staging-directory") from None


def stage_units(selection, output_directory, *, mode="inspect"):
    """Create two exclusive, fsync'd files in an existing protected stage."""
    files = render_units(selection, mode=mode)
    directory = _staging_directory(output_directory)
    details = {}
    try:
        # Refuse partial replacement of previously staged files.
        for name in files:
            try:
                os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise UnitSelectionError("staging-file-exists")
        for name, contents in files.items():
            data = contents.encode("utf-8")
            fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                         0o600, dir_fd=directory)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            details[name] = hashlib.sha256(data).hexdigest()
        os.fsync(directory)
        return {"schema": 1, "mode": mode, "files_sha256": details,
                "installed": False, "enabled": False}
    finally:
        os.close(directory)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Stage (never install) shared DNS service/timer for review")
    parser.add_argument("--selection", required=True,
                        help="Protected deployment-chosen JSON with schema=1")
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--mode", choices=("inspect", "apply"), default="inspect")
    args = parser.parse_args(argv)
    try:
        source = Path(args.selection)
        # The selection must be a protected existing file, not a link.
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 8192):
                raise UnitSelectionError("unsafe-selection-file")
            selection = json.loads(stream.read())
        outcome = stage_units(selection, args.output_directory, mode=args.mode)
    except (OSError, ValueError, TypeError):
        print(json.dumps({"status": "blocked", "reason": "staging-refused"}))
        return 2
    print(json.dumps(outcome, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
