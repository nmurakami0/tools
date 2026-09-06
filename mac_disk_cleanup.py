#!/usr/bin/env python3
"""Read-only inventory, followed by explicit, revalidated, individual deletions."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time

COMMAND_TIMEOUT = 30


class Unsafe(RuntimeError):
    pass


def command(args, timeout=None, allowed=(0,)):
    # Git read operations must not opportunistically refresh/write the index.
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0",
               GH_PROMPT_DISABLED="1", LC_ALL="C")
    try:
        result = subprocess.run([str(x) for x in args], capture_output=True,
                                text=True, errors="surrogateescape", env=env,
                                timeout=COMMAND_TIMEOUT if timeout is None else timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Unsafe(f"{args[0]} unavailable or timed out: {exc}") from exc
    if result.returncode not in allowed:
        raise Unsafe(f"{args[0]} failed ({result.returncode}): {result.stderr.strip()[:400]}")
    return result


def git(path, *args):
    return command(["git", "-C", path, *args]).stdout


def within(path, parent):
    return path == parent or parent in path.parents


def human(size):
    if size is None:
        return "unknown"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(size) < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024


def identity(path):
    s = path.lstat()
    return [s.st_dev, s.st_ino, s.st_mtime_ns, s.st_size]


def plain_path(path):
    # Do not resolve away symlinks: reject them, including in ancestors.
    if not path.is_absolute() or path == Path("/"):
        raise Unsafe("not a non-root absolute path")
    for p in (path, *path.parents):
        if p.is_symlink():
            raise Unsafe(f"symlink path: {p}")
    if path.resolve() != path:
        raise Unsafe("non-canonical path")


def old_tree(path, cutoff, timeout=15, allow_child_links=False):
    """An old directory mtime alone says nothing about files inside it."""
    plain_path(path)
    deadline = time.monotonic() + timeout
    device = path.stat().st_dev
    stack = [path]
    while stack:
        item = stack.pop()
        if time.monotonic() > deadline:
            raise Unsafe("age check timed out")
        s = item.lstat()
        if allow_child_links and item != path and stat.S_ISLNK(s.st_mode) and s.st_mtime < cutoff:
            continue  # rmtree unlinks these without following them
        if s.st_dev != device or stat.S_ISLNK(s.st_mode):
            raise Unsafe("symlink or nested filesystem")
        if not (stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode)):
            raise Unsafe("special file")
        if s.st_mtime >= cutoff:
            raise Unsafe("recently modified content")
        if stat.S_ISDIR(s.st_mode):
            stack.extend(item.iterdir())


def idle(path):
    plain_path(path)
    if within(Path.cwd().resolve(), path):
        raise Unsafe("contains current working directory")
    result = command(["lsof", "-nP", *(["+D", path] if path.is_dir() else ["--", path])], allowed=(0, 1))
    # An incomplete process/file inspection must never count as idle.
    if result.returncode == 0 or result.stdout.strip() or result.stderr.strip():
        raise Unsafe("open files / working directory, or incomplete lsof inspection")


def agents_idle():
    processes = command(["ps", "-axo", "comm="]).stdout.splitlines()
    if any(re.search(r"(^|[/ ])(claude|codex)([ /.-]|$)", p, re.I) for p in processes):
        raise Unsafe("Claude/Codex process active; close agents before deleting their logs")


def measure(path, timeout=20):
    try:
        result = command(["du", "-sk", "-x", path], timeout=timeout)
        if result.stderr.strip():
            return None
        return int(result.stdout.split()[0]) * 1024
    except (Unsafe, ValueError, IndexError):
        return None


def stamp(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, AttributeError):
        return float("inf")  # unknown date is never old


def docker_bytes(value):
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*([kMGTPE]?B)", value or "", re.I)
    if not match:
        return None
    unit = match[2].upper()
    power = 0 if unit == "B" else "KMGTPE".index(unit[0]) + 1
    return int(float(match[1]) * 1000 ** power)


@dataclass
class Candidate:
    kind: str
    target: str
    evidence: str
    signature: object
    size: object = None
    meta: dict = field(default_factory=dict)

    @property
    def id(self):
        data = json.dumps([self.kind, self.target, self.signature], sort_keys=True)
        return self.kind + "-" + hashlib.sha256(data.encode("utf-8", "surrogateescape")).hexdigest()[:12]


class Docker:
    def __init__(self):
        # Pin the context and daemon. Ambient remote host overrides are rejected.
        if os.environ.get("DOCKER_HOST"):
            raise Unsafe("DOCKER_HOST is set; unset it and choose a local Docker context")
        self.context = command(["docker", "context", "show"]).stdout.strip()
        data = json.loads(command(["docker", "context", "inspect", self.context]).stdout)
        if not data[0]["Endpoints"]["docker"]["Host"].startswith("unix://"):
            raise Unsafe("remote Docker endpoint; only local Unix sockets are supported")
        self.daemon = self.call("info", "--format", "{{.ID}}").strip()
        if not self.daemon:
            raise Unsafe("missing Docker daemon identity")

    def call(self, *args, timeout=None):
        return command(["docker", "--context", self.context, *args], timeout=timeout).stdout

    def verify(self):
        if Docker().daemon != self.daemon:
            raise Unsafe("Docker context/daemon changed")

    def objects(self, kind, *filters):
        ids = self.call(kind, "ls", "-q", *filters).split()
        # Batch inspect; any disappeared resource aborts the snapshot safely.
        result = []
        for start in range(0, len(ids), 100):
            result.extend(json.loads(self.call(kind, "inspect", *ids[start:start + 100])))
        return result

    def containers(self):
        return self.objects("container", "-a", "--no-trunc")


def worktree_records(repo):
    records = []
    record = {}
    for item in git(repo, "worktree", "list", "--porcelain", "-z").split("\0"):
        if not item:
            if record:
                records.append(record)
                record = {}
            continue
        key, _, value = item.partition(" ")
        record[key] = value
    if record:
        records.append(record)
    return records


def github_repo(path):
    url = git(path, "remote", "get-url", "origin").strip()
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([\w.-]+/[\w.-]+?)(?:\.git)?", url)
    if not match:
        raise Unsafe("origin is not a supported github.com remote")
    return match[1]


def merged_pr(path, head, cutoff):
    repo = github_repo(path)
    pages = json.loads(command(["gh", "api", "--hostname", "github.com", "--paginate", "--slurp",
        f"repos/{repo}/commits/{head}/pulls?per_page=100"]).stdout)
    matches = [pr for page in pages for pr in page
               if pr.get("merged_at") and stamp(pr["merged_at"]) < cutoff
               and pr.get("head", {}).get("sha") == head
               and pr.get("base", {}).get("repo", {}).get("full_name", "").lower() == repo.lower()]
    if not matches:
        raise Unsafe("no old merged PR whose exact head SHA matches (including squash merges)")
    return matches[0]["html_url"]


def check_worktree(repo, path, head, allow_ignored=False):
    plain_path(path)
    records = worktree_records(repo)
    matches = [r for r in records[1:] if r.get("worktree") == str(path)]
    if len(matches) != 1 or any(k in matches[0] for k in ("locked", "prunable", "bare")):
        raise Unsafe("main, missing, locked, or prunable worktree")
    if matches[0].get("HEAD") != head or git(path, "rev-parse", "HEAD").strip() != head:
        raise Unsafe("HEAD changed")
    if git(path, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none"):
        raise Unsafe("tracked changes or untracked files")
    if not allow_ignored and git(path, "ls-files", "--others", "--ignored", "--exclude-standard", "-z"):
        raise Unsafe("ignored files exist (may include .env, local data, or build outputs)")
    if any(line.startswith("160000 ") for line in git(path, "ls-files", "--stage").splitlines()):
        raise Unsafe("submodule worktree")
    # status may intentionally hide modifications with these index flags.
    if any(line and (line[0].islower() or line[0] == "S") for line in git(path, "ls-files", "-v").splitlines()):
        raise Unsafe("assume-unchanged or skip-worktree index entries")
    for marker in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG", "index.lock"):
        target = git(path, "rev-parse", "--git-path", marker).strip()
        if (path / target).exists():
            raise Unsafe(f"Git operation in progress: {marker}")
    if within(Path.cwd().resolve(), path):
        raise Unsafe("current worktree")


def container_paths(container):
    labels = container.get("Config", {}).get("Labels") or {}
    paths = [labels.get("com.docker.compose.project.working_dir", "")]
    paths.extend(labels.get("com.docker.compose.project.config_files", "").split(","))
    paths.extend(m.get("Source", "") for m in container.get("Mounts", []) if m.get("Type") == "bind")
    return [Path(p).resolve() for p in paths if p.startswith("/")]


def uses_worktree(containers, path):
    return any(within(p, path) or within(path, p) for c in containers for p in container_paths(c))


def compose_association(containers, project, proven):
    related = [c for c in containers if (c.get("Config", {}).get("Labels") or {}).get("com.docker.compose.project") == project]
    if not project or not related:
        return None
    paths = set()
    for c in related:
        labels = c.get("Config", {}).get("Labels") or {}
        wd = labels.get("com.docker.compose.project.working_dir", "")
        if not wd.startswith("/") or c.get("State", {}).get("Status") not in ("exited", "created"):
            return None
        owners = [p for p in proven if within(Path(wd).resolve(), Path(p))]
        if len(owners) != 1:
            return None
        paths.add(owners[0])
    return next(iter(paths)) if len(paths) == 1 else None


def locked_providers(lock):
    """Accept only complete, recognisable provider/version blocks; fail closed."""
    text = lock.read_text()
    # Generated lock files allow comments; malformed/unrecognised blocks must not
    # accidentally turn the keep set into an empty delete-everything list.
    blocks = re.findall(r'\bprovider\s+"([^"\n]+)"\s*\{([^{}]*)\}', text)
    declarations = re.findall(r'\bprovider\s*"', text)
    if not blocks or len(blocks) != len(declarations):
        raise Unsafe("unrecognised or empty Terraform lock file")
    keep = set()
    for name, body in blocks:
        versions = re.findall(r'^\s*version\s*=\s*"([0-9][\w.+-]*)"\s*(?:#.*)?$', body, re.M)
        if len(versions) != 1 or len(name.split("/")) != 3:
            raise Unsafe("invalid Terraform provider/version block")
        keep.add(name + "/" + versions[0])
    return keep


class Cleanup:
    def __init__(self, args):
        self.args = args
        self.home = Path.home().resolve()
        self.cutoff = time.time() - args.min_age_days * 86400
        self.candidates = []
        self.notices = []
        self.docker = None
        self.containers = None
        self.proven = {}

    def note(self, text):
        self.notices.append(text)

    def file_candidate(self, path, evidence, kind="cache", meta=None):
        try:
            old_tree(path, self.cutoff, self.args.timeout, allow_child_links=kind == "dependencies")
            self.candidates.append(Candidate(kind, str(path), evidence, identity(path),
                                             meta=meta or {}))
        except (Unsafe, OSError) as exc:
            self.note(f"KEEP {path}: {exc}")

    def cache_scan(self):
        # Only explicitly regenerable caches, never blanket ~/Library/Caches,
        # browser profiles, agent state/history, plugins, models, or credentials.
        roots = [".npm/_cacache", ".gradle/caches", "Library/Caches/pip",
                 "Library/Caches/Yarn", "Library/Caches/go-build",
                 "Library/Caches/typescript", "Library/Caches/node-gyp",
                 "Library/Caches/Homebrew"]
        if self.args.xcode:
            roots.append("Library/Developer/Xcode/DerivedData")
        if self.args.trash:
            roots.append(".Trash")
        for relative in roots:
            path = self.home / relative
            if path.exists():
                try:
                    plain_path(path)
                    for child in sorted(path.iterdir()):
                        self.file_candidate(child, "old cache; regeneration/download may be required" if relative != ".Trash" else "explicit Trash opt-in; permanent deletion")
                except (OSError, Unsafe) as exc:
                    self.note(f"KEEP {path}: {exc}")
        if self.args.agent_logs:
            for relative in (".claude/debug", ".codex/log"):
                root = self.home / relative
                if root.exists():
                    try:
                        plain_path(root)
                        for child in sorted(root.iterdir()):
                            if child.is_file() and child.suffix in (".log", ".txt"):
                                self.file_candidate(child, "old diagnostic log; sessions/history are preserved", "agent-log")
                    except (OSError, Unsafe) as exc:
                        self.note(f"KEEP {root}: {exc}")
        if shutil.which("uv"):
            try:
                path = Path(command(["uv", "cache", "dir"]).stdout.strip())
                plain_path(path)
                if path.is_dir():
                    self.candidates.append(Candidate("uv-cache", str(path),
                        "native uv cache prune (unreachable entries); age filter does not apply; never directly delete uv cache files",
                        identity(path)[:2]))
            except (Unsafe, OSError) as exc:
                self.note(f"uv cache inspection incomplete: {exc}")

    def docker_scan(self):
        if self.args.no_docker:
            self.note("Docker inspection disabled; worktree removal is blocked without container inspection")
            return
        try:
            self.docker = Docker()
            print("\nDocker logical usage (not host reclaimable bytes):", flush=True)
            print(self.docker.call("system", "df", timeout=self.args.timeout))
            self.containers = self.docker.containers()
            images = self.docker.objects("image", "--no-trunc", *([] if self.args.docker_all else ["--filter", "dangling=true"]))
            used_images = {c["Image"] for c in self.containers}
            for im in {im["Id"]: im for im in images}.values():
                if im["Id"] not in used_images and stamp(im.get("Created")) < self.cutoff:
                    self.candidates.append(Candidate("image", im["Id"], "old image without container reference; layers may be shared", self.docker.daemon,
                                                     im.get("Size")))
            self.candidates.append(Candidate("build-cache", self.docker.context,
                f"dangling build cache unused for {self.args.min_age_days} days; retain at least {self.args.keep_build_cache}",
                [self.docker.daemon, self.args.min_age_days, self.args.keep_build_cache]))
            volumes = self.docker.objects("volume")
            volume_sizes = {}
            try:
                rows = json.loads(self.docker.call("system", "df", "-v", "--format", "{{json .Volumes}}"))
                volume_sizes = {row["Name"]: docker_bytes(row.get("Size")) for row in rows or []}
            except (Unsafe, ValueError, KeyError, TypeError) as exc:
                self.note(f"Per-volume sizes unavailable (not zero): {exc}")
            refs = {m["Name"] for c in self.containers for m in c.get("Mounts", []) if m.get("Type") == "volume"}
            unused = [v for v in volumes if v["Name"] not in refs]
            self.note(f"Docker: {len(volumes)} volumes, {len(unused)} unreferenced by ALL containers; unused does not mean disposable")
            for v in unused:
                labels = v.get("Labels") or {}
                detail = f"volume {v['Name']} project={labels.get('com.docker.compose.project', '?')}"
                if v.get("Driver") != "local" or v.get("Options"):
                    self.note("KEEP " + detail + " (non-local driver or custom mount options)")
                    continue
                if self.args.docker_volumes and stamp(v.get("CreatedAt")) < self.cutoff:
                    self.candidates.append(Candidate("volume", v["Name"], "DATA LOSS opt-in; ownership/PR is unproven; no container references",
                        [self.docker.daemon, v.get("CreatedAt"), labels], volume_sizes.get(v["Name"])))
                else:
                    self.note("REVIEW " + detail + " (requires --docker-volumes and age threshold)")
        except (Unsafe, ValueError, KeyError, TypeError) as exc:
            self.note(f"Docker incomplete: {exc}")
            self.docker = None
            self.containers = None
            self.candidates = [c for c in self.candidates if c.kind not in ("image", "volume", "build-cache")]

    def repositories(self):
        roots = self.args.repo_root or [self.home / "projects/src", self.home / ".codex/worktrees"]
        found = set()
        skip = {"node_modules", ".venv", "venv", ".git", ".terraform", "Library", "build", "dist"}
        deadline = time.monotonic() + self.args.timeout
        for root in roots:
            root = Path(root).expanduser().absolute()
            if not root.exists():
                continue
            plain_path(root)
            for base, dirs, files in os.walk(root, onerror=lambda e: self.note(str(e))):
                if time.monotonic() > deadline:
                    self.note("Repository discovery timed out; use narrower --repo-root")
                    return sorted(found)
                # Continue through repo folders to find nested agent worktrees,
                # but prune expensive generated trees and symlinks.
                dirs[:] = [d for d in dirs if d not in skip and not (Path(base) / d).is_symlink()]
                if (Path(base) / ".git").exists():
                    found.add(Path(base))
                    dirs[:] = []  # git worktree list discovers its linked trees
        return sorted(found)

    def worktree_scan(self):
        if not (self.args.worktrees or self.args.worktree_deps):
            return
        seen = set()
        for repo in self.repositories():
            try:
                records = worktree_records(repo)
                if not records:
                    continue
                main = Path(records[0]["worktree"])
                for record in records[1:]:
                    path = Path(record["worktree"])
                    if path in seen:
                        continue
                    seen.add(path)
                    try:
                        head = record["HEAD"]
                        check_worktree(main, path, head, allow_ignored=True)
                        pr = merged_pr(path, head, self.cutoff)
                        meta = {"repo": str(main), "head": head, "pr": pr}
                        if self.args.worktree_deps:
                            self.dependency_scan(path, meta)
                        check_worktree(main, path, head)
                        self.proven[str(path)] = meta
                        if self.containers is None:
                            raise Unsafe("Docker inspection unavailable")
                        if uses_worktree(self.containers, path):
                            raise Unsafe("Docker container references path; inspect/remove its resources first")
                        self.candidates.append(Candidate("worktree", str(path), f"clean, no ignored files; exact merged head: {pr}",
                                                         [head, identity(path)], meta=self.proven[str(path)]))
                    except (Unsafe, OSError, KeyError, ValueError) as exc:
                        self.note(f"KEEP worktree {path}: {exc}")
            except (Unsafe, OSError, ValueError) as exc:
                self.note(f"Repository inspection incomplete {repo}: {exc}")
        if self.docker and self.containers is not None:
            self.compose_scan()

    def dependency_scan(self, path, meta):
        # Keep ignored .env/local databases. Offer only ignored node_modules in
        # exact merged PR worktrees, never arbitrary ignored directories.
        deadline = time.monotonic() + self.args.timeout
        for base, dirs, _ in os.walk(path, onerror=lambda e: self.note(str(e))):
            if time.monotonic() > deadline:
                self.note(f"Dependency discovery timed out: {path}")
                return
            dirs[:] = [d for d in dirs if d not in (".git", ".venv", ".terraform") and not (Path(base) / d).is_symlink()]
            if "node_modules" in dirs:
                dirs.remove("node_modules")
                target = Path(base) / "node_modules"
                relative = str(target.relative_to(path))
                if git(path, "ls-files", "-z", "--", relative):
                    continue
                ignored = command(["git", "-C", path, "check-ignore", "-q", "--", relative], allowed=(0, 1))
                if ignored.returncode == 0:
                    self.file_candidate(target, f"ignored node_modules; reinstall required; exact merged PR {meta['pr']}",
                                        "dependencies", {"path": str(path), **meta})

    def compose_scan(self):
        projects = {(c.get("Config", {}).get("Labels") or {}).get("com.docker.compose.project") for c in self.containers}
        for project in projects:
            path = compose_association(self.containers, project, self.proven)
            if not path:
                continue
            for candidate in self.candidates:
                if candidate.kind == "volume" and candidate.signature[2].get("com.docker.compose.project") == project:
                    candidate.evidence = (f"DATA LOSS opt-in; no container references; Compose labels associate project={project} "
                                          f"with exact merged worktree={path}; {self.proven[path]['pr']}; contents still require review")
            for c in self.containers:
                if (c.get("Config", {}).get("Labels") or {}).get("com.docker.compose.project") != project:
                    continue
                if stamp(c.get("Created")) >= self.cutoff:
                    continue
                self.candidates.append(Candidate("container", c["Id"],
                    f"stopped Compose project={project}; exact merged worktree={path}; writable layer will be lost",
                    [self.docker.daemon, c["Id"]], meta={"path": path, "project": project, **self.proven[path]}))
            # Volume labels alone cannot identify a worktree. Explain provenance
            # while containers still exist, and never delete dependent volumes in
            # the same invocation. A fresh inventory is required after container rm.
            self.note(f"Verified stopped Compose project {project} -> {path}; after selected container deletion, rescan --docker-volumes. Volume deletion always needs explicit selection.")

    def terraform_scan(self):
        if not (self.args.terraform or self.args.terraform_all or self.args.terraform_dir):
            return
        roots = self.args.terraform_dir or [self.home / "projects/src"]
        seen = set()
        deadline = time.monotonic() + self.args.timeout
        for root in roots:
            root = Path(root).expanduser().absolute()
            plain_path(root)
            for base, dirs, _ in os.walk(root, onerror=lambda e: self.note(str(e))):
                if time.monotonic() > deadline:
                    self.note("Terraform discovery timed out; use narrower --terraform-dir")
                    return
                dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".venv") and not (Path(base) / d).is_symlink()]
                if ".terraform" not in dirs:
                    continue
                dirs.remove(".terraform")
                tf = Path(base) / ".terraform"
                if tf in seen:
                    continue
                seen.add(tf)
                if self.args.terraform_all:
                    for name in ("providers", "modules"):
                        if (tf / name).exists():
                            self.file_candidate(tf / name, "Terraform cache; terraform init required; state preserved", "terraform", {"all": True})
                else:
                    lock = Path(base) / ".terraform.lock.hcl"
                    try:
                        keep = locked_providers(lock)
                        for version in (tf / "providers").glob("*/*/*/*"):
                            relative = str(version.relative_to(tf / "providers"))
                            if relative not in keep:
                                self.file_candidate(version, f"unpinned provider {relative}", "terraform",
                                    {"lock": str(lock), "relative": relative})
                    except (Unsafe, OSError) as exc:
                        self.note(f"KEEP Terraform {tf}: {exc}")

    def overview(self):
        roots = self.args.overview_root or [self.home]
        print("\nAllocated disk usage by immediate child (read-only; overlapping rows are NOT additive):", flush=True)
        for root in roots:
            root = Path(root).expanduser().absolute()
            try:
                plain_path(root)
                children = sorted(p for p in root.iterdir() if not p.is_symlink())
                with ThreadPoolExecutor(max_workers=4) as pool:
                    sizes = list(pool.map(lambda p: measure(p, self.args.timeout), children))
                rows = sorted(zip(children, sizes), key=lambda x: x[1] if x[1] is not None else -1, reverse=True)
                for path, size in rows[:self.args.top]:
                    print(f"  {human(size):>12}  {str(path)!r}", flush=True)
                unknown = [str(p) for p, size in rows if size is None]
                if unknown:
                    self.note("Incomplete measurements (permissions/timeout), not zero: " + repr(unknown))
            except (OSError, Unsafe) as exc:
                self.note(f"Overview incomplete {root}: {exc}")

    def scan(self):
        if not self.args.no_overview:
            self.overview()
        self.cache_scan()
        self.docker_scan()
        self.worktree_scan()
        self.terraform_scan()
        # Deduplicate overlapping roots and measure each filesystem candidate once.
        self.candidates = list({c.id: c for c in self.candidates}.values())
        files = [c for c in self.candidates if c.kind in ("cache", "agent-log", "worktree", "terraform", "dependencies")]
        with ThreadPoolExecutor(max_workers=4) as pool:
            for c, size in zip(files, pool.map(lambda c: measure(c.target, self.args.timeout), files)):
                c.size = size
        self.candidates.sort(key=lambda c: (-(c.size or 0), c.id))

    def validate(self, c):
        if c.kind == "uv-cache":
            path = Path(c.target)
            plain_path(path)
            if identity(path)[:2] != c.signature:
                raise Unsafe("uv cache directory replaced")
            processes = command(["ps", "-axo", "comm="]).stdout.splitlines()
            if any(re.search(r"(^|[/ ])uvx?$", p.strip()) for p in processes):
                raise Unsafe("uv/uvx process active; stop it before pruning")
            idle(path)  # also protects running Python environments inside cache
        elif c.kind in ("cache", "agent-log", "terraform", "dependencies"):
            path = Path(c.target)
            if identity(path) != c.signature:
                raise Unsafe("path identity/content changed")
            old_tree(path, self.cutoff, self.args.timeout, allow_child_links=c.kind == "dependencies")
            if c.kind == "terraform" and not c.meta.get("all"):
                if c.meta["relative"] in locked_providers(Path(c.meta["lock"])):
                    raise Unsafe("provider is now pinned")
            if c.kind == "agent-log":
                agents_idle()
            if c.kind == "dependencies":
                wt = Path(c.meta["path"])
                check_worktree(c.meta["repo"], wt, c.meta["head"], allow_ignored=True)
                merged_pr(wt, c.meta["head"], self.cutoff)
                if git(wt, "ls-files", "-z", "--", str(path.relative_to(wt))):
                    raise Unsafe("dependencies are now tracked")
                command(["git", "-C", wt, "check-ignore", "-q", "--", str(path.relative_to(wt))])
                if self.docker is None:
                    raise Unsafe("Docker inspection unavailable")
                self.docker.verify()
                if uses_worktree(self.docker.containers(), wt):
                    raise Unsafe("container references worktree")
                idle(wt)
            idle(path)
        elif c.kind == "worktree":
            path = Path(c.target)
            if identity(path) != c.signature[1]:
                raise Unsafe("worktree directory identity changed")
            check_worktree(c.meta["repo"], path, c.meta["head"])
            merged_pr(path, c.meta["head"], self.cutoff)
            self.docker.verify()
            if uses_worktree(self.docker.containers(), path):
                raise Unsafe("container now references worktree")
            idle(path)
        else:
            self.docker.verify()
            containers = self.docker.containers()
            if c.kind == "volume":
                current = json.loads(self.docker.call("volume", "inspect", c.target))[0]
                if current.get("Driver") != "local" or current.get("Options"):
                    raise Unsafe("volume has non-local driver or custom mount options")
                if [self.docker.daemon, current.get("CreatedAt"), current.get("Labels") or {}] != c.signature:
                    raise Unsafe("volume was replaced or relabeled")
                if any(m.get("Name") == c.target for co in containers for m in co.get("Mounts", [])):
                    raise Unsafe("volume now referenced by a container")
            elif c.kind == "image":
                if any(co["Image"] == c.target for co in containers):
                    raise Unsafe("image now referenced by a container")
            elif c.kind == "container":
                path = Path(c.meta["path"])
                check_worktree(c.meta["repo"], path, c.meta["head"])
                merged_pr(path, c.meta["head"], self.cutoff)
                if compose_association(containers, c.meta["project"], {str(path): c.meta}) != str(path):
                    raise Unsafe("Compose project is active, shared, or ownership changed")
                if not any(co["Id"] == c.target for co in containers):
                    raise Unsafe("container disappeared")
                idle(path)

    def execute(self, selected):
        # Reject overlapping filesystem selections up front; no double counting
        # or deleting a child that was already removed with its parent.
        paths = [Path(c.target) for c in selected if c.kind in ("cache", "agent-log", "terraform", "worktree", "dependencies")]
        if any(a != b and (within(a, b) or within(b, a)) for i, a in enumerate(paths) for b in paths[i+1:]):
            raise Unsafe("overlapping selections; choose either the parent or its children")
        failures = 0
        for c in selected:
            validated = False
            try:
                self.validate(c)
                validated = True
                if c.kind in ("cache", "agent-log", "terraform", "dependencies"):
                    path = Path(c.target)
                    if path.is_dir():
                        if not shutil.rmtree.avoids_symlink_attacks:
                            raise Unsafe("Python does not support symlink-safe rmtree on this platform")
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                elif c.kind == "worktree":
                    git(c.meta["repo"], "worktree", "remove", "--", c.target)
                elif c.kind == "build-cache":
                    print(self.docker.call("builder", "prune", "--force", "--filter",
                        f"until={self.args.min_age_days * 24}h", "--keep-storage", self.args.keep_build_cache,
                        timeout=self.args.timeout))
                elif c.kind == "uv-cache":
                    result = command(["uv", "cache", "prune", "--cache-dir", c.target,
                                      "--offline", "--no-config"], timeout=self.args.timeout)
                    print(result.stdout + result.stderr)
                else:
                    # No --force, system prune, compose down -v, or volume prune.
                    print(self.docker.call(c.kind, "rm", c.target))
                action = "COMPLETED" if c.kind in ("build-cache", "uv-cache") else "REMOVED"
                print(f"{action} {c.id} {c.target!r}", flush=True)
            except (Unsafe, OSError, ValueError, KeyError) as exc:
                failures += 1
                status = "FAILED (may be partially completed)" if validated else "KEPT"
                print(f"{status} {c.id}: {exc}", file=sys.stderr, flush=True)
        return 1 if failures else 0


def positive(value):
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return n


def arguments(argv=None):
    p = argparse.ArgumentParser(description=__doc__, epilog="See mac-disk-cleanup.md for policy, limitations and examples. --run alone never deletes anything.")
    p.add_argument("--run", action="store_true", help="execute only explicitly selected candidate IDs")
    p.add_argument("--select", action="append", default=[], metavar="ID", help="repeat for each exact candidate ID shown in a dry run")
    p.add_argument("--min-age-days", type=positive, default=30)
    p.add_argument("--timeout", type=positive, default=30, help="per-command/discovery time limit in seconds")
    p.add_argument("--top", type=positive, default=20)
    p.add_argument("--no-overview", action="store_true", help="skip broad home inventory for a faster repeat scan")
    p.add_argument("--overview-root", action="append", type=Path, help="repeat to inspect a large directory in more detail")
    p.add_argument("--no-docker", action="store_true")
    p.add_argument("--docker-all", action="store_true", help="also offer old tagged images without container references")
    p.add_argument("--docker-volumes", action="store_true", help="offer old unreferenced volumes for explicit DATA LOSS selection")
    p.add_argument("--keep-build-cache", default="10GB")
    p.add_argument("--worktrees", action="store_true", help="verify linked worktrees against merged GitHub PR exact head SHAs")
    p.add_argument("--worktree-deps", action="store_true", help="also offer old ignored node_modules in exact merged PR worktrees; preserve other ignored data")
    p.add_argument("--repo-root", action="append", type=Path, help="repository discovery roots (repeatable)")
    p.add_argument("--agent-logs", action="store_true", help="offer old Claude/Codex diagnostic log files only")
    p.add_argument("--terraform", action="store_true")
    p.add_argument("--terraform-all", action="store_true")
    p.add_argument("--terraform-dir", action="append", type=Path)
    p.add_argument("--trash", action="store_true", help="offer old Trash entries, preserving ~/.Trash itself")
    p.add_argument("--xcode", action="store_true", help="offer old DerivedData entries (no simulator deletion)")
    args = p.parse_args(argv)
    if args.run and not args.select:
        p.error("--run requires at least one --select ID from a dry run")
    if not re.fullmatch(r"[1-9][0-9]*(?:[KMGTP]B|[kmgtp]b|[bB])?", args.keep_build_cache):
        p.error("--keep-build-cache must be a positive Docker size such as 10GB")
    return args


def main(argv=None):
    global COMMAND_TIMEOUT
    args = arguments(argv)
    COMMAND_TIMEOUT = args.timeout
    if os.geteuid() == 0:
        print("Refusing to run as root; use your normal user account.", file=sys.stderr)
        return 2
    cleanup = Cleanup(args)
    before = shutil.disk_usage(cleanup.home).free
    print(f"Mac disk cleanup: {'EXECUTE SELECTED' if args.run else 'DRY RUN'}; host available {human(before)}", flush=True)
    print("Discovery only until execution. Active files are rechecked immediately before deletion.", flush=True)
    try:
        cleanup.scan()
        print("\nCandidates (size is allocated bytes or approximate Docker logical size, not guaranteed reclaim):")
        for c in cleanup.candidates:
            print(f"{c.id:28} {human(c.size):>12}  {c.target!r}\n  {c.evidence}")
        print("\nInspection notes:")
        for note in cleanup.notices:
            print("  " + note)
        by_id = {c.id: c for c in cleanup.candidates}
        unknown = set(args.select) - by_id.keys()
        if unknown:
            raise Unsafe(f"unknown/stale/unavailable selections; nothing deleted: {sorted(unknown)}")
        selected = [by_id[key] for key in dict.fromkeys(args.select)]
        if not args.run:
            print("\nNothing deleted. Repeat the same options with --run --select ID (repeat --select as needed).")
            print("No additive reclaim estimate: APFS clones/snapshots, hardlinks, sparse VM disks and Docker shared layers can overlap.")
            return 0
        result = cleanup.execute(selected)
        after = shutil.disk_usage(cleanup.home).free
        print(f"Host available: {human(after)}; observed change {human(after - before)} (includes concurrent activity).")
        print("Docker VM reclamation / APFS snapshots may delay host free-space changes.")
        return result
    except (Unsafe, OSError, ValueError, KeyError) as exc:
        print(f"Inspection/selection failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
