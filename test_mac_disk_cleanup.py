"""Safety regressions. All mutations are confined to TemporaryDirectory fixtures."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import mac_disk_cleanup as m


def result(stdout="", code=0, stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.cleanup = m.Cleanup(m.arguments(["--no-overview", "--no-docker"]))
        self.cleanup.home = self.root

    def tearDown(self):
        self.tmp.cleanup()

    def old(self, path):
        value = time.time() - 60 * 86400
        if path.is_dir():
            for base, dirs, files in os.walk(path, topdown=False):
                for name in files + dirs:
                    os.utime(Path(base) / name, (value, value), follow_symlinks=False)
        os.utime(path, (value, value), follow_symlinks=False)
        return path

    def cache(self):
        path = self.root / "cache"
        path.mkdir()
        (path / "data").write_text("regenerable")
        self.old(path)
        self.cleanup.file_candidate(path, "fixture")
        return path, self.cleanup.candidates[-1]

    def test_run_requires_selection(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            m.arguments(["--run"])

    def test_negative_age_and_timeout_rejected(self):
        for args in (["--min-age-days", "0"], ["--timeout", "-1"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                m.arguments(args)

    def test_changed_candidate_has_different_id(self):
        path, candidate = self.cache()
        os.utime(path, None)
        other = m.Candidate(candidate.kind, candidate.target, "", m.identity(path))
        self.assertNotEqual(candidate.id, other.id)
        with self.assertRaises(m.Unsafe):
            self.cleanup.validate(candidate)

    def test_recent_nested_file_blocks_old_parent(self):
        path, _ = self.cache()
        (path / "data").write_text("new local activity")
        self.old(path)  # reset all ages, then change child alone
        os.utime(path / "data", None)
        with self.assertRaises(m.Unsafe):
            m.old_tree(path, self.cleanup.cutoff)

    def test_symlink_ancestor_rejected(self):
        real = self.root / "real"
        real.mkdir()
        (real / "child").mkdir()
        link = self.root / "link"
        link.symlink_to(real)
        with self.assertRaises(m.Unsafe):
            m.plain_path(link / "child")

    def test_symlink_descendant_rejected_for_caches(self):
        path, _ = self.cache()
        (path / "link").symlink_to(self.root / "outside")
        self.old(path)
        with self.assertRaises(m.Unsafe):
            m.old_tree(path, self.cleanup.cutoff)

    def test_dependency_links_unlinked_without_following(self):
        outside = self.root / "valuable"
        outside.write_text("keep")
        path, _ = self.cache()
        (path / "link").symlink_to(outside)
        self.old(path)
        m.old_tree(path, self.cleanup.cutoff, allow_child_links=True)
        # Exercise real safe deletion after independently testing policy guards.
        c = m.Candidate("dependencies", str(path), "", m.identity(path))
        with patch.object(self.cleanup, "validate"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.cleanup.execute([c]), 0)
        self.assertEqual(outside.read_text(), "keep")

    def test_unknown_file_measurement_is_not_zero(self):
        with patch.object(m, "command", side_effect=m.Unsafe("denied")):
            self.assertIsNone(m.measure(self.root))

    def test_partial_du_output_is_unknown(self):
        with patch.object(m, "command", return_value=result("9999\t/tmp\n", stderr="partial")):
            self.assertIsNone(m.measure(self.root))

    def test_open_file_and_lsof_warning_block(self):
        path, c = self.cache()
        for response in (result("open file", 0), result("", 1, "cannot stat")):
            with patch.object(m, "command", return_value=response), self.assertRaises(m.Unsafe):
                self.cleanup.validate(c)
        self.assertTrue(path.exists())

    def test_failed_delete_returns_nonzero(self):
        path, c = self.cache()
        with patch.object(m, "idle"), patch.object(m.shutil, "rmtree", side_effect=OSError("denied")), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.cleanup.execute([c]), 1)
        self.assertTrue(path.exists())

    def test_real_selected_cache_deletion(self):
        path, c = self.cache()
        with patch.object(m, "idle"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.cleanup.execute([c]), 0)
        self.assertFalse(path.exists())

    def test_overlapping_selections_rejected_before_delete(self):
        path, c = self.cache()
        child = m.Candidate("cache", str(path / "data"), "", [])
        with self.assertRaises(m.Unsafe):
            self.cleanup.execute([c, child])
        self.assertTrue(path.exists())

    def test_active_agent_preserves_logs(self):
        with patch.object(m, "command", return_value=result("/Applications/Codex.app/Contents/MacOS/Codex\n")), self.assertRaises(m.Unsafe):
            m.agents_idle()

    def test_agent_scan_never_offers_sessions_plugins_or_auth(self):
        for name in (".codex/sessions/session.jsonl", ".codex/auth.json", ".claude/projects/transcript.jsonl", ".claude/plugins/data.log", ".codex/log/old.log"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture")
            self.old(path)
        self.cleanup.args.agent_logs = True
        with patch.object(m.shutil, "which", return_value=None):
            self.cleanup.cache_scan()
        self.assertEqual([c.target for c in self.cleanup.candidates], [str(self.root / ".codex/log/old.log")])

    def test_uv_scan_uses_native_prune_never_direct_file_candidates(self):
        path = self.root / "uv"
        path.mkdir()
        with patch.object(m.shutil, "which", return_value="/bin/uv"), patch.object(m, "command", return_value=result(str(path))):
            self.cleanup.cache_scan()
        self.assertEqual([c.kind for c in self.cleanup.candidates], ["uv-cache"])

    def test_uv_prune_blocks_active_uv(self):
        path, _ = self.cache()
        c = m.Candidate("uv-cache", str(path), "", m.identity(path)[:2])
        with patch.object(m, "command", return_value=result("/usr/bin/uv\n")), self.assertRaises(m.Unsafe):
            self.cleanup.validate(c)

    def test_uv_prune_passes_exact_cache_without_force_or_ci(self):
        path, _ = self.cache()
        c = m.Candidate("uv-cache", str(path), "", m.identity(path)[:2])
        with patch.object(m, "idle"), patch.object(m, "command", return_value=result()) as cmd, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.cleanup.execute([c]), 0)
        self.assertEqual(cmd.call_args.args[0], ["uv", "cache", "prune", "--cache-dir", str(path), "--offline", "--no-config"])

    def test_dry_run_never_validates_or_executes(self):
        path, c = self.cache()
        with patch.object(m.os, "geteuid", return_value=501), patch.object(m.Cleanup, "scan", side_effect=lambda: None), patch.object(m.Cleanup, "execute") as execute, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(["--no-overview", "--no-docker"]), 0)
            execute.assert_not_called()
        self.assertTrue(path.exists())

    def test_unknown_selection_blocks_all_execution(self):
        with patch.object(m.os, "geteuid", return_value=501), patch.object(m.Cleanup, "scan"), patch.object(m.Cleanup, "execute") as execute, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(m.main(["--no-overview", "--no-docker", "--run", "--select", "stale"]), 1)
            execute.assert_not_called()

    def test_terraform_malformed_lock_is_not_empty_keep_set(self):
        lock = self.root / "lock"
        for text in ("", "garbage", 'provider "registry.terraform.io/hashicorp/aws" {}', 'provider "registry.terraform.io/hashicorp/aws" {\nversion = "1.0"\n}\nprovider "broken" {'):
            lock.write_text(text)
            with self.assertRaises(m.Unsafe):
                m.locked_providers(lock)

    def test_terraform_now_pinned_is_preserved(self):
        path, _ = self.cache()
        lock = self.root / "lock"
        lock.write_text('provider "registry.terraform.io/hashicorp/aws" {\n  version = "1.0"\n}\n')
        c = m.Candidate("terraform", str(path), "", m.identity(path), meta={"lock": str(lock), "relative": "registry.terraform.io/hashicorp/aws/1.0"})
        with self.assertRaises(m.Unsafe):
            self.cleanup.validate(c)

    def test_terraform_adjacent_provider_blocks_are_both_preserved(self):
        lock = self.root / "lock"
        lock.write_text('provider "registry.terraform.io/hashicorp/aws" { version = "1.0" } provider "registry.terraform.io/hashicorp/random" { version = "2.0" }')
        self.assertEqual(m.locked_providers(lock), {"registry.terraform.io/hashicorp/aws/1.0", "registry.terraform.io/hashicorp/random/2.0"})

    def test_terraform_all_finds_modules_without_providers_preserves_state(self):
        tf = self.root / ".terraform"
        (tf / "modules").mkdir(parents=True)
        (tf / "modules" / "download").write_text("source")
        (tf / "terraform.tfstate").write_text("backend config")
        (tf / "environment").write_text("production")
        self.old(tf)
        self.cleanup.args.terraform_all = True
        self.cleanup.args.terraform_dir = [self.root]
        self.cleanup.terraform_scan()
        self.assertEqual([c.target for c in self.cleanup.candidates], [str(tf / "modules")])


class GitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "main"
        self.repo.mkdir()
        m.git(self.repo, "init", "-b", "main")
        m.git(self.repo, "config", "user.email", "test@example.invalid")
        m.git(self.repo, "config", "user.name", "Test")
        m.git(self.repo, "config", "commit.gpgsign", "false")
        (self.repo / "file").write_text("tracked")
        (self.repo / ".gitignore").write_text("node_modules/\n.env\n")
        m.git(self.repo, "add", ".")
        m.git(self.repo, "commit", "-m", "fixture")
        self.wt = self.root / "work tree\nwith newline"
        m.git(self.repo, "worktree", "add", "--detach", str(self.wt))
        self.head = m.git(self.wt, "rev-parse", "HEAD").strip()

    def tearDown(self):
        self.tmp.cleanup()

    def test_nul_delimited_detached_worktree_with_unusual_path(self):
        m.check_worktree(self.repo, self.wt, self.head)
        self.assertEqual(m.worktree_records(self.repo)[1]["worktree"], str(self.wt))

    def test_main_is_protected(self):
        with self.assertRaises(m.Unsafe):
            m.check_worktree(self.repo, self.repo, self.head)

    def test_ignored_env_blocks_full_worktree_removal(self):
        (self.wt / ".env").write_text("valuable")
        with self.assertRaises(m.Unsafe):
            m.check_worktree(self.repo, self.wt, self.head)
        m.check_worktree(self.repo, self.wt, self.head, allow_ignored=True)

    def test_dirty_and_untracked_files_block(self):
        for name in ("file", "untracked"):
            path = self.wt / name
            path.write_text("valuable")
            with self.assertRaises(m.Unsafe):
                m.check_worktree(self.repo, self.wt, self.head)
            if name == "file":
                m.git(self.wt, "checkout", "--", "file")
            else:
                path.unlink()

    def test_locked_worktree_blocks(self):
        m.git(self.repo, "worktree", "lock", str(self.wt))
        with self.assertRaises(m.Unsafe):
            m.check_worktree(self.repo, self.wt, self.head)

    def test_assume_unchanged_blocks_hidden_changes(self):
        m.git(self.wt, "update-index", "--assume-unchanged", "file")
        (self.wt / "file").write_text("valuable")
        with self.assertRaises(m.Unsafe):
            m.check_worktree(self.repo, self.wt, self.head)

    def test_exact_pr_head_not_branch_name_or_ancestor(self):
        def check(sha, merged="2020-01-01T00:00:00Z"):
            pr = {"merged_at": merged, "head": {"sha": sha}, "base": {"repo": {"full_name": "owner/repo"}}, "html_url": "https://github.com/owner/repo/pull/1"}
            with patch.object(m, "github_repo", return_value="owner/repo"), patch.object(m, "command", return_value=result(json.dumps([[pr]]))):
                return m.merged_pr(self.wt, self.head, time.time() - 30 * 86400)
        self.assertIn("pull/1", check(self.head))
        with self.assertRaises(m.Unsafe):
            check("different-sha")
        with self.assertRaises(m.Unsafe):
            check(self.head, None)

    def test_origin_parsing_strips_dot_git(self):
        for remote in ("git@github.com:owner/repo.git", "https://github.com/owner/repo.git", "ssh://git@github.com/owner/repo.git"):
            with patch.object(m, "git", return_value=remote):
                self.assertEqual(m.github_repo(self.repo), "owner/repo")

    def test_ignored_dependencies_offered_without_deleting_env(self):
        deps = self.wt / "node_modules"
        deps.mkdir()
        (deps / "module.js").write_text("installed package")
        (self.wt / ".env").write_text("keep secret")
        age = time.time() - 60 * 86400
        os.utime(deps / "module.js", (age, age))
        os.utime(deps, (age, age))
        cleanup = m.Cleanup(m.arguments(["--no-overview", "--no-docker", "--worktree-deps"]))
        with patch.object(cleanup, "repositories", return_value=[self.repo]), patch.object(m, "merged_pr", return_value="https://github.com/owner/repo/pull/1"):
            cleanup.worktree_scan()
        self.assertEqual([(c.kind, c.target) for c in cleanup.candidates], [("dependencies", str(deps))])
        self.assertEqual((self.wt / ".env").read_text(), "keep secret")
        with patch.object(m, "merged_pr", return_value="https://github.com/owner/repo/pull/1"), self.assertRaisesRegex(m.Unsafe, "Docker inspection unavailable"):
            cleanup.validate(cleanup.candidates[0])


class DockerTests(unittest.TestCase):
    def setUp(self):
        self.cleanup = m.Cleanup(m.arguments(["--no-overview"]))
        self.docker = Mock(daemon="daemon", context="desktop-linux")
        self.cleanup.docker = self.docker

    def container(self, wd="/work/one", status="exited", project="same"):
        return {"Id": "container-id", "Image": "image-id", "Config": {"Labels": {"com.docker.compose.project": project, "com.docker.compose.project.working_dir": wd}}, "State": {"Status": status}, "Mounts": []}

    def test_remote_context_rejected(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(m, "command", side_effect=[result("remote\n"), result(json.dumps([{"Endpoints": {"docker": {"Host": "ssh://host"}}}]))]), self.assertRaises(m.Unsafe):
            m.Docker()

    def test_docker_host_override_rejected(self):
        with patch.dict(os.environ, {"DOCKER_HOST": "tcp://remote:2375"}), self.assertRaises(m.Unsafe):
            m.Docker()

    def test_shared_compose_project_not_associated(self):
        containers = [self.container(), self.container("/work/two")]
        self.assertIsNone(m.compose_association(containers, "same", {"/work/one": {}, "/work/two": {}}))

    def test_running_compose_project_not_associated(self):
        self.assertIsNone(m.compose_association([self.container(status="running")], "same", {"/work/one": {}}))

    def test_unique_stopped_project_is_associated(self):
        self.assertEqual(m.compose_association([self.container()], "same", {"/work/one": {}}), "/work/one")

    def test_missing_workdir_not_guessed_from_project_name(self):
        self.assertIsNone(m.compose_association([self.container(wd="")], "same", {"/work/one": {}}))

    def test_both_stopped_and_running_references_protect_volume(self):
        for status in ("running", "exited"):
            co = self.container(status=status)
            co["Mounts"] = [{"Type": "volume", "Name": "data"}]
            self.docker.containers.return_value = [co]
            self.docker.call.return_value = json.dumps([{"CreatedAt": "old", "Labels": {}, "Driver": "local"}])
            c = m.Candidate("volume", "data", "", ["daemon", "old", {}])
            with self.assertRaises(m.Unsafe):
                self.cleanup.validate(c)

    def test_recreated_volume_same_name_protected(self):
        self.docker.containers.return_value = []
        self.docker.call.return_value = json.dumps([{"CreatedAt": "new", "Labels": {}, "Driver": "local"}])
        with self.assertRaises(m.Unsafe):
            self.cleanup.validate(m.Candidate("volume", "data", "", ["daemon", "old", {}]))

    def test_container_reference_protects_image(self):
        self.docker.containers.return_value = [self.container()]
        with self.assertRaises(m.Unsafe):
            self.cleanup.validate(m.Candidate("image", "image-id", "", "daemon"))

    def test_volume_delete_never_forces_or_prunes(self):
        self.docker.containers.return_value = []
        self.docker.call.return_value = json.dumps([{"CreatedAt": "old", "Labels": {}, "Driver": "local"}])
        with contextlib.redirect_stdout(io.StringIO()):
            code = self.cleanup.execute([m.Candidate("volume", "data", "", ["daemon", "old", {}])])
        self.assertEqual(code, 0)
        self.assertEqual(self.docker.call.call_args.args, ("volume", "rm", "data"))

    def test_bind_mount_ancestor_protects_worktree(self):
        co = self.container(wd="")
        co["Mounts"] = [{"Type": "bind", "Source": "/work"}]
        self.assertTrue(m.uses_worktree([co], Path("/work/one")))

    def test_custom_volume_mount_is_protected(self):
        self.docker.containers.return_value = []
        self.docker.call.return_value = json.dumps([{"CreatedAt": "old", "Labels": {}, "Driver": "local", "Options": {"type": "nfs"}}])
        with self.assertRaises(m.Unsafe):
            self.cleanup.validate(m.Candidate("volume", "data", "", ["daemon", "old", {}]))

    def test_docker_sizes_are_decimal_and_unknown_stays_unknown(self):
        self.assertEqual(m.docker_bytes("2.469GB"), 2469000000)
        self.assertEqual(m.docker_bytes("383.6kB"), 383600)
        self.assertEqual(m.docker_bytes("0B"), 0)
        self.assertIsNone(m.docker_bytes("N/A"))


if __name__ == "__main__":
    unittest.main()
