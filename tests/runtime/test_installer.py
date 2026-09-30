import json
import hashlib
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from runtime.agentic_runtime import installer
from runtime.agentic_runtime.installer import apply_install, merge_settings_file, plan_install, remove_install


ROOT = pathlib.Path(__file__).resolve().parents[2]


class InstallerTests(unittest.TestCase):
    def test_plan_is_read_only_and_apply_creates_journal(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            files = {".agentic/config.json": {"content": '{"mode":"hitl"}\n',
                                                "template": "config", "owner": "managed"}}
            plan = plan_install(target, files)
            self.assertEqual(plan["actions"][0]["action"], "create")
            self.assertFalse((target / ".agentic/config.json").exists())
            result = apply_install(target, files, agentic_os_version="0.1.0")
            self.assertEqual(result["applied"], [".agentic/config.json"])
            journal = json.loads((target / ".agentic/agentic-os/install.json").read_text())
            self.assertEqual(journal["files"][".agentic/config.json"]["owner"], "managed")

    def test_user_modified_files_are_preserved_and_managed_files_can_replace(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            managed = {"config.json": {"content": "v1\n"}}
            apply_install(target, managed)
            managed_update = {"config.json": {"content": "v2\n"}}
            self.assertEqual(plan_install(target, managed_update)["actions"][0]["action"], "replace")
            apply_install(target, managed_update)
            self.assertEqual((target / "config.json").read_text(), "v2\n")
            (target / "config.json").write_text("user edit\n")
            user_update = {"config.json": {"content": "v3\n"}}
            self.assertEqual(plan_install(target, user_update)["actions"][0]["action"], "preserve_modified")
            result = apply_install(target, user_update)
            self.assertEqual(result["preserved"], ["config.json"])
            self.assertEqual((target / "config.json").read_text(), "user edit\n")

    def test_matching_preexisting_file_is_not_claimed_for_uninstall(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            (target / "config.json").write_text("same\n")
            result = apply_install(target, {"config.json": "same\n"})
            self.assertEqual(result["actions"][0]["action"], "unchanged")
            removed = remove_install(target)
            self.assertEqual(removed["removed"], [])
            self.assertEqual((target / "config.json").read_text(), "same\n")

    def test_same_bytes_user_replacement_is_not_reclaimed(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            path = target / "config.txt"
            apply_install(target, {"config.txt": "same\n"})
            original = path.stat()
            path.unlink()
            path.write_text("same\n")
            os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000_000))
            self.assertNotEqual((path.stat().st_ino, path.stat().st_mtime_ns),
                                (original.st_ino, original.st_mtime_ns))
            result = apply_install(target, {"config.txt": "same\n"})
            self.assertEqual(result["preserved"], ["config.txt"])
            removed = remove_install(target)
            self.assertEqual(removed["removed"], [])
            self.assertEqual(path.read_text(), "same\n")

    def test_same_bytes_replacement_during_plan_does_not_journal_stale_inode(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            path = target / "config.txt"
            apply_install(target, {"config.txt": "v1\n"})
            original_plan = installer.plan_install

            def replace_before_plan(*args, **kwargs):
                replacement = target / "replacement.txt"
                replacement.write_text("v1\n")
                replacement.replace(path)
                return original_plan(*args, **kwargs)

            with patch.object(installer, "plan_install", side_effect=replace_before_plan):
                with self.assertRaises(RuntimeError):
                    apply_install(target, {"config.txt": "v2\n"})
            self.assertEqual(path.read_text(), "v1\n")
            journal = json.loads((target / ".agentic/agentic-os/install.json").read_text())
            self.assertNotEqual(journal["files"]["config.txt"]["inode"], path.stat().st_ino)
            self.assertEqual(apply_install(target, {"config.txt": "v2\n"})["preserved"],
                             ["config.txt"])
            updated = json.loads((target / ".agentic/agentic-os/install.json").read_text())
            self.assertEqual(updated["files"]["config.txt"]["inode"], path.stat().st_ino)
            self.assertEqual(updated["files"]["config.txt"]["owner"], "user")

    def test_same_bytes_user_replacement_survives_direct_uninstall(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            path = target / "config.txt"
            apply_install(target, {"config.txt": "same\n"})
            original = path.stat()
            path.unlink()
            path.write_text("same\n")
            os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000_000))
            result = remove_install(target)
            self.assertEqual(result["removed"], [])
            self.assertEqual(path.read_text(), "same\n")

    def test_legacy_managed_entry_without_file_identity_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            path = target / "config.txt"
            path.write_text("same\n")
            journal = target / ".agentic/agentic-os/install.json"
            journal.parent.mkdir(parents=True)
            journal.write_text(json.dumps({"files": {"config.txt": {
                "sha256": hashlib.sha256(b"same\n").hexdigest(),
                "owner": "managed", "template": "old", "origin": "plugin"}}}))
            result = remove_install(target)
            self.assertEqual(result["removed"], [])
            self.assertEqual(path.read_text(), "same\n")

    def test_uninstall_preserves_generated_files_without_individual_decision(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"managed.txt": "managed\n", "generated.txt": {
                "content": "generated\n", "owner": "generated", "origin": "generated"}})
            result = remove_install(target)
            self.assertEqual(result["removed"], ["managed.txt"])
            self.assertEqual(result["preserved"], ["generated.txt"])
            self.assertEqual((target / "generated.txt").read_text(), "generated\n")
            journal = json.loads((target / ".agentic/agentic-os/install.json").read_text())
            self.assertEqual(journal["files"]["generated.txt"]["owner"], "generated")
            repeated = remove_install(target, ["generated.txt"])
            self.assertEqual(repeated["removed"], [])
            self.assertEqual(repeated["preserved"], ["generated.txt"])
            self.assertEqual(json.loads((target / ".agentic/agentic-os/install.json").read_text())
                             ["files"]["generated.txt"]["owner"], "generated")

    def test_detected_user_edit_remains_user_owned_after_bytes_restored(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            path = target / "config.txt"
            apply_install(target, {"config.txt": "managed-v1\n"})
            path.write_text("user-custom\n")
            result = apply_install(target, {"config.txt": "managed-v2\n"})
            self.assertEqual(result["preserved"], ["config.txt"])
            path.write_text("managed-v1\n")
            removed = remove_install(target)
            self.assertEqual(removed["removed"], [])
            self.assertEqual(path.read_text(), "managed-v1\n")

    def test_invalid_version_does_not_create_files(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            with self.assertRaises(ValueError):
                apply_install(target, {"created.txt": "payload\n"}, agentic_os_version="")
            self.assertFalse((target / "created.txt").exists())
            self.assertFalse((target / ".agentic/agentic-os/install.json").exists())

    def test_invalid_stored_or_supplied_version_blocks_before_file_write(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            journal = target / ".agentic/agentic-os/install.json"
            journal.parent.mkdir(parents=True)
            for invalid in (123, [], "", "not-a-version"):
                journal.write_text(json.dumps({"agentic_os_version": invalid, "files": {}}))
                with self.assertRaises((RuntimeError, ValueError)):
                    apply_install(target, {"created.txt": "payload\n"})
                self.assertFalse((target / "created.txt").exists())
            journal.unlink()
            with self.assertRaises(ValueError):
                apply_install(target, {"created.txt": "payload\n"},
                              agentic_os_version="not-a-version")
            self.assertFalse((target / "created.txt").exists())

    def test_path_escape_and_malformed_journal_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            with self.assertRaises(ValueError):
                plan_install(target, {"../escape": "x"})
            with self.assertRaises(ValueError):
                plan_install(target, {".": "x"})
            with self.assertRaises(ValueError):
                apply_install(target, {".": "x"})
            with self.assertRaises(ValueError):
                merge_settings_file(target, ".", {"x": True})
            with self.assertRaises(ValueError):
                apply_install(target, {"a": "first\n", "a/b": "second\n"},
                              agentic_os_version="1.2.3")
            self.assertFalse((target / "a").exists())
            with self.assertRaises(ValueError):
                apply_install(target, {".agentic": "not a directory\n"})
            self.assertFalse((target / ".agentic").exists())
            journal = target / ".agentic/agentic-os/install.json"
            journal.parent.mkdir(parents=True)
            journal.write_text(json.dumps({"files": {".": {
                "sha256": hashlib.sha256(b"x").hexdigest(), "owner": "managed"}}}))
            with self.assertRaises(ValueError):
                remove_install(target)
            journal.unlink()
            journal.write_text("not-json")
            with self.assertRaises(RuntimeError):
                plan_install(target, {"config.json": "x"})

    def test_remove_preserves_modified_files_and_removes_managed_files(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"managed.txt": "managed\n", "user.txt": "original\n"})
            (target / "user.txt").write_text("user edit\n")
            result = remove_install(target)
            self.assertEqual(result["removed"], ["managed.txt"])
            self.assertEqual(result["preserved"], ["user.txt"])
            self.assertFalse((target / "managed.txt").exists())
            self.assertEqual((target / "user.txt").read_text(), "user edit\n")
            journal = json.loads((target / ".agentic/agentic-os/install.json").read_text())
            self.assertEqual(journal["files"]["user.txt"]["owner"], "user")

    def test_settings_merge_preserves_user_values_and_journals_result(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            settings = target / ".claude/settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({
                "permissions": {"allow": ["Read"], "mode": "user"},
                "custom": True,
            }))
            result = merge_settings_file(target, ".claude/settings.json", {
                "permissions": {"allow": ["Read", "Write"], "deny": ["Bash"], "mode": "managed"},
                "hooks": {"Stop": ["agentic-stop"]},
            }, agentic_os_version="0.2.0")
            merged = json.loads(settings.read_text())
            self.assertEqual(merged["permissions"]["allow"], ["Read", "Write"])
            self.assertEqual(merged["permissions"]["mode"], "user")
            self.assertEqual(merged["custom"], True)
            self.assertEqual(merged["hooks"]["Stop"], ["agentic-stop"])
            journal = json.loads((target / ".agentic/agentic-os/install.json").read_text())
            self.assertEqual(journal["files"][".claude/settings.json"]["template"], "settings-merge")
            self.assertTrue(result["changed"])

    def test_settings_merge_rejects_invalid_existing_json_without_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            path = target / ".claude/settings.json"
            path.parent.mkdir(parents=True)
            path.write_text("not-json")
            with self.assertRaisesRegex(RuntimeError, "invalid JSON"):
                merge_settings_file(target, ".claude/settings.json", {"hooks": {}})
            self.assertEqual(path.read_text(), "not-json")

    def test_settings_merge_rejects_bad_journal_before_changing_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            settings = target / ".claude/settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text('{"user": true}\n')
            journal = target / ".agentic/agentic-os/install.json"
            journal.parent.mkdir(parents=True)
            journal.write_text("not-json")
            with self.assertRaisesRegex(RuntimeError, "journal is unreadable"):
                merge_settings_file(target, ".claude/settings.json", {"hooks": {"Stop": ["x"]}})
            self.assertEqual(settings.read_text(), '{"user": true}\n')

    def test_settings_merge_preserves_preexisting_file_on_uninstall(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            settings = target / ".claude/settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text('{"user": true}\n')
            merge_settings_file(target, ".claude/settings.json", {"hooks": {"Stop": ["x"]}})
            result = remove_install(target)
            self.assertIn(".claude/settings.json", result["preserved"])
            self.assertTrue(settings.exists())

    def test_settings_merge_preserves_modified_managed_file_on_uninstall(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            settings = target / ".claude/settings.json"
            merge_settings_file(target, ".claude/settings.json", {"hooks": {"Stop": ["x"]}})
            settings.write_text('{"hooks": {"Stop": ["x"]}, "user": true}\n')
            merge_settings_file(target, ".claude/settings.json", {"hooks": {"Stop": ["y"]}})
            result = remove_install(target)
            self.assertIn(".claude/settings.json", result["preserved"])
            self.assertTrue(settings.exists())

    def test_installer_rejects_symlinked_parent_and_leaf(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            target = root / "target"
            outside = root / "outside"
            target.mkdir()
            outside.mkdir()
            (target / ".claude").symlink_to(outside, target_is_directory=True)
            for operation in (
                lambda: plan_install(target, {".claude/settings.json": "x"}),
                lambda: apply_install(target, {".claude/settings.json": "x"}),
                lambda: merge_settings_file(target, ".claude/settings.json", {"x": True}),
            ):
                with self.assertRaises(ValueError):
                    operation()
            self.assertFalse((outside / "settings.json").exists())
            (target / ".claude").unlink()
            (target / "settings.json").symlink_to(outside / "settings.json")
            with self.assertRaises(ValueError):
                merge_settings_file(target, "settings.json", {"x": True})

    def test_installer_rejects_symlinked_journal_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            target = root / "target"
            outside = root / "outside"
            target.mkdir()
            outside.mkdir()
            (target / ".agentic").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                apply_install(target, {"config.json": "x\n"})
            self.assertFalse((target / "config.json").exists())
            self.assertEqual(list(outside.iterdir()), [])

    def test_parent_swap_after_validation_cannot_redirect_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            target = root / "target"
            outside = root / "outside"
            target.mkdir()
            outside.mkdir()
            (target / "sub").mkdir()
            original = installer._destination
            calls = 0

            def swap_after_check(base, relative):
                nonlocal calls
                result = original(base, relative)
                if relative == "sub/pwn.txt":
                    calls += 1
                    if calls == 2:
                        (target / "sub").rename(target / "saved")
                        (target / "sub").symlink_to(outside, target_is_directory=True)
                return result

            with patch.object(installer, "_destination", side_effect=swap_after_check):
                with self.assertRaises((ValueError, OSError)):
                    apply_install(target, {"sub/pwn.txt": "outside\n"})
            self.assertFalse((outside / "pwn.txt").exists())

    def test_edit_after_plan_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            path = target / "config.txt"
            apply_install(target, {"config.txt": "v1\n"})
            original = installer._atomic_write

            def edit_before_write(root, relative, content, **kwargs):
                if relative == "config.txt":
                    path.write_text("USER EDIT\n")
                return original(root, relative, content, **kwargs)

            with patch.object(installer, "_atomic_write", side_effect=edit_before_write):
                with self.assertRaises(RuntimeError):
                    apply_install(target, {"config.txt": "v2\n"})
            self.assertEqual(path.read_text(), "USER EDIT\n")

    def test_edit_after_uninstall_check_is_not_deleted(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            path = target / "config.txt"
            apply_install(target, {"config.txt": "v1\n"})
            original = installer._unlink

            def edit_before_unlink(root, relative, **kwargs):
                path.write_text("USER EDIT\n")
                return original(root, relative, **kwargs)

            with patch.object(installer, "_unlink", side_effect=edit_before_unlink):
                with self.assertRaises(RuntimeError):
                    remove_install(target)
            self.assertEqual(path.read_text(), "USER EDIT\n")

    def test_same_bytes_new_inode_after_check_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            path = target / "config.txt"
            apply_install(target, {"config.txt": "v1\n"})
            original = installer._atomic_write

            def replace_before_write(root, relative, content, **kwargs):
                if relative == "config.txt":
                    replacement = target / "replacement.txt"
                    replacement.write_text("v1\n")
                    replacement.replace(path)
                return original(root, relative, content, **kwargs)

            with patch.object(installer, "_atomic_write", side_effect=replace_before_write):
                with self.assertRaises(RuntimeError):
                    apply_install(target, {"config.txt": "v2\n"})
            self.assertEqual(path.read_text(), "v1\n")

    def test_journal_edit_before_write_is_not_lost(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"config.txt": "v1\n"})
            journal = target / ".agentic/agentic-os/install.json"
            original = installer._atomic_write

            def edit_journal(root, relative, content, **kwargs):
                if relative == installer.JOURNAL_RELATIVE.as_posix():
                    value = json.loads(journal.read_text())
                    value["operator_note"] = "preserve"
                    journal.write_text(json.dumps(value))
                return original(root, relative, content, **kwargs)

            with patch.object(installer, "_atomic_write", side_effect=edit_journal):
                with self.assertRaises(RuntimeError):
                    apply_install(target, {"config.txt": "v2\n"})
            self.assertEqual(json.loads(journal.read_text())["operator_note"], "preserve")
            self.assertEqual((target / "config.txt").read_text(), "v1\n")
            retry = apply_install(target, {"config.txt": "v2\n"})
            self.assertEqual(retry["applied"], ["config.txt"])

    def test_settings_journal_conflict_restores_user_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            settings = target / "settings.json"
            settings.write_text('{"user": true}\n')
            merge_settings_file(target, "settings.json", {"hooks": {"Stop": ["x"]}})
            before = settings.read_bytes()
            journal = target / ".agentic/agentic-os/install.json"
            original = installer._atomic_write

            def edit_journal(root, relative, content, **kwargs):
                if relative == installer.JOURNAL_RELATIVE.as_posix():
                    value = json.loads(journal.read_text())
                    value["operator_note"] = "preserve"
                    journal.write_text(json.dumps(value))
                return original(root, relative, content, **kwargs)

            with patch.object(installer, "_atomic_write", side_effect=edit_journal):
                with self.assertRaises(RuntimeError):
                    merge_settings_file(target, "settings.json", {"hooks": {"Stop": ["y"]}})
            self.assertEqual(settings.read_bytes(), before)

    def test_uninstall_journal_conflict_restores_removed_file(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"config.txt": "v1\n"})
            journal = target / ".agentic/agentic-os/install.json"
            original = installer._atomic_write

            def edit_journal(root, relative, content, **kwargs):
                if relative == installer.JOURNAL_RELATIVE.as_posix():
                    value = json.loads(journal.read_text())
                    value["operator_note"] = "preserve"
                    journal.write_text(json.dumps(value))
                return original(root, relative, content, **kwargs)

            with patch.object(installer, "_atomic_write", side_effect=edit_journal):
                with self.assertRaises(RuntimeError):
                    remove_install(target)
            self.assertEqual((target / "config.txt").read_text(), "v1\n")
            retry = remove_install(target)
            self.assertEqual(retry["removed"], ["config.txt"])

    def test_journal_directory_sync_failure_does_not_undo_visible_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"config.txt": "v1\n"})
            real_fsync = os.fsync
            calls = 0

            def fail_journal_parent(fd):
                nonlocal calls
                calls += 1
                if calls == 4:
                    raise OSError("injected journal directory sync failure")
                return real_fsync(fd)

            with patch.object(installer.os, "fsync", side_effect=fail_journal_parent):
                with self.assertRaises(OSError):
                    apply_install(target, {"config.txt": "v2\n"})
            self.assertEqual((target / "config.txt").read_text(), "v2\n")
            journal = json.loads((target / ".agentic/agentic-os/install.json").read_text())
            self.assertEqual(journal["files"]["config.txt"]["inode"],
                             (target / "config.txt").stat().st_ino)
            retry = apply_install(target, {"config.txt": "v2\n"})
            self.assertEqual(retry["actions"][0]["action"], "unchanged")

    def test_data_directory_sync_failure_restores_original_inode(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"config.txt": "v1\n"})
            original_inode = (target / "config.txt").stat().st_ino
            real_fsync = os.fsync
            calls = 0

            def fail_data_parent(fd):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected data directory sync failure")
                return real_fsync(fd)

            with patch.object(installer.os, "fsync", side_effect=fail_data_parent):
                with self.assertRaises(OSError):
                    apply_install(target, {"config.txt": "v2\n"})
            self.assertEqual((target / "config.txt").read_text(), "v1\n")
            self.assertEqual((target / "config.txt").stat().st_ino, original_inode)
            self.assertEqual(apply_install(target, {"config.txt": "v2\n"})["applied"],
                             ["config.txt"])

    def test_later_conflict_keeps_earlier_write_journaled(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"a.txt": "v1\n", "b.txt": "v1\n"})
            original = installer._atomic_write

            def conflict_after_a(root, relative, content, **kwargs):
                result = original(root, relative, content, **kwargs)
                if relative == "a.txt":
                    (target / "b.txt").write_text("USER\n")
                return result

            with patch.object(installer, "_atomic_write", side_effect=conflict_after_a):
                with self.assertRaises(RuntimeError):
                    apply_install(target, {"a.txt": "v2\n", "b.txt": "v2\n"})
            journal = json.loads((target / ".agentic/agentic-os/install.json").read_text())
            self.assertEqual(journal["files"]["a.txt"]["sha256"], hashlib.sha256(b"v2\n").hexdigest())
            self.assertEqual((target / "a.txt").read_text(), "v2\n")
            self.assertEqual((target / "b.txt").read_text(), "USER\n")

    def test_uninstall_rejects_path_escape_in_journal_before_deletion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            target = root / "target"
            target.mkdir()
            external = root / "external.txt"
            external.write_text("keep\n")
            journal = target / ".agentic/agentic-os/install.json"
            journal.parent.mkdir(parents=True)
            for escaped in (str(external), "../external.txt"):
                journal.write_text(json.dumps({"files": {
                    escaped: {"sha256": hashlib.sha256(b"keep\n").hexdigest(),
                              "owner": "managed"}}}))
                with self.assertRaises(ValueError):
                    remove_install(target)
            self.assertEqual(external.read_text(), "keep\n")

    def test_malformed_journal_entry_cannot_claim_user_file(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            path = target / "user.txt"
            path.write_text("mine\n")
            journal = target / ".agentic/agentic-os/install.json"
            journal.parent.mkdir(parents=True)
            journal.write_text(json.dumps({"files": {"user.txt": {
                "sha256": hashlib.sha256(b"mine\n").hexdigest()}}}))
            with self.assertRaises(RuntimeError):
                remove_install(target)
            with self.assertRaises(RuntimeError):
                apply_install(target, {"user.txt": "replacement\n"})
            self.assertEqual(path.read_text(), "mine\n")

    def test_journal_ancestor_collisions_and_null_files_fail_before_write(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            journal = target / ".agentic/agentic-os/install.json"
            journal.parent.mkdir(parents=True)
            entry = {"sha256": hashlib.sha256(b"x").hexdigest(), "owner": "managed"}
            for invalid in ({"files": {"a": entry, "a/b": entry}}, {"files": None}):
                journal.write_text(json.dumps(invalid))
                before = journal.read_bytes()
                with self.assertRaises((RuntimeError, ValueError)):
                    remove_install(target)
                self.assertEqual(journal.read_bytes(), before)

    def test_invalid_journal_metadata_fails_before_file_write(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            journal = target / ".agentic/agentic-os/install.json"
            journal.parent.mkdir(parents=True)
            entry = {"sha256": hashlib.sha256(b"x").hexdigest(), "owner": "managed"}
            for invalid in (
                {"phase": 42, "files": {}},
                {"files": {"a": dict(entry, template=[]) }},
                {"files": {"a": dict(entry, origin=None) }},
                {"files": {"a": dict(entry, mtime_ns=1) }},
                {"files": {"a": dict(entry, device=1, inode=2, mtime_ns=True) }},
            ):
                journal.write_text(json.dumps(invalid))
                with self.assertRaises(RuntimeError):
                    apply_install(target, {"created.txt": "payload\n"})
                self.assertFalse((target / "created.txt").exists())

    def test_invalid_manifest_metadata_fails_before_file_write(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            for field in ("template", "origin"):
                with self.subTest(field=field):
                    with self.assertRaises(ValueError):
                        apply_install(target, {"created.txt": {
                            "content": "payload\n", field: object()}})
                    self.assertFalse((target / "created.txt").exists())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO required")
    def test_fifo_destination_and_journal_reject_without_blocking(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            fifo = target / "pipe"
            os.mkfifo(fifo)
            command = ([sys.executable, "-c",
                        "from runtime.agentic_runtime.installer import plan_install; "
                        "import sys; plan_install(sys.argv[1], {'pipe':'x'})", str(target)])
            result = subprocess.run(command, capture_output=True, text=True, timeout=3,
                                    cwd=ROOT)
            self.assertNotEqual(result.returncode, 0)
            journal = target / ".agentic/agentic-os/install.json"
            journal.parent.mkdir(parents=True)
            os.mkfifo(journal)
            command = ([sys.executable, "-c",
                        "from runtime.agentic_runtime.installer import plan_install; "
                        "import sys; plan_install(sys.argv[1], {'safe.txt':'x'})", str(target)])
            result = subprocess.run(command, capture_output=True, text=True, timeout=3,
                                    cwd=ROOT)
            self.assertNotEqual(result.returncode, 0)

    def test_uninstall_preflights_all_selected_file_types(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"a.txt": "owned\n"})
            os.mkfifo(target / "zpipe")
            journal = target / ".agentic/agentic-os/install.json"
            value = json.loads(journal.read_text())
            value["files"]["zpipe"] = {"sha256": hashlib.sha256(b"x").hexdigest(),
                                       "owner": "managed"}
            journal.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                remove_install(target)
            self.assertEqual((target / "a.txt").read_text(), "owned\n")

    def test_real_directory_swap_after_planning_cannot_redirect_write(self):
        with tempfile.TemporaryDirectory() as temp:
            base = pathlib.Path(temp)
            target = base / "target"
            target.mkdir()
            (target / "sub").mkdir()
            original = installer._atomic_write
            swapped = False

            def swap_parent(root, relative, content, **kwargs):
                nonlocal swapped
                if relative == "sub/pwn.txt" and not swapped:
                    swapped = True
                    (target / "sub").rename(target / "old-sub")
                    (target / "sub").mkdir()
                return original(root, relative, content, **kwargs)

            with patch.object(installer, "_atomic_write", side_effect=swap_parent):
                with self.assertRaises(RuntimeError):
                    apply_install(target, {"sub/pwn.txt": "payload\n"})
            self.assertFalse((target / "sub/pwn.txt").exists())

    def test_root_directory_swap_after_planning_cannot_redirect_write(self):
        with tempfile.TemporaryDirectory() as temp:
            base = pathlib.Path(temp)
            target = base / "target"
            target.mkdir()
            original = installer._atomic_write
            swapped = False

            def swap_root(root, relative, content, **kwargs):
                nonlocal swapped
                if relative == "pwn.txt" and not swapped:
                    swapped = True
                    target.rename(base / "old-target")
                    target.mkdir()
                return original(root, relative, content, **kwargs)

            with patch.object(installer, "_atomic_write", side_effect=swap_root):
                with self.assertRaises(RuntimeError):
                    apply_install(target, {"pwn.txt": "payload\n"})
            self.assertFalse((target / "pwn.txt").exists())

    def test_parent_move_at_rename_cannot_report_success(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            (target / "sub").mkdir()
            original_rename = os.rename
            moved = False

            def move_at_write(source, destination, *args, **kwargs):
                nonlocal moved
                if destination == "pwn.txt" and not moved:
                    moved = True
                    original_rename(target / "sub", target / "old-sub")
                    (target / "sub").mkdir()
                return original_rename(source, destination, *args, **kwargs)

            with patch.object(installer.os, "rename", side_effect=move_at_write):
                with self.assertRaises(RuntimeError):
                    apply_install(target, {"sub/pwn.txt": "payload\n"})
            self.assertFalse((target / "sub/pwn.txt").exists())
            self.assertFalse((target / "old-sub/pwn.txt").exists())

    def test_settings_merge_does_not_replace_existing_null_or_scalar_shapes(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            path = target / "settings.json"
            path.write_text(json.dumps({"nullable": None, "scalar": "user", "items": None}))
            with self.assertRaisesRegex(ValueError, "non-object setting: nullable"):
                merge_settings_file(target, "settings.json", {"nullable": {"x": 1}})
            self.assertEqual(json.loads(path.read_text())["nullable"], None)
            with self.assertRaisesRegex(ValueError, "non-array setting: items"):
                merge_settings_file(target, "settings.json", {"items": ["x"]})
            self.assertEqual(json.loads(path.read_text())["scalar"], "user")

    def test_public_install_operations_are_versioned(self):
        with tempfile.TemporaryDirectory() as temp:
            payload = {
                "api_version": "1.0.0", "operation": "install.plan",
                "target": temp, "files": {"config.json": "x\n"},
            }
            response = subprocess.run([sys.executable, str(ROOT / "runtime/run.py")],
                                      input=json.dumps(payload), text=True,
                                      capture_output=True)
            self.assertEqual(response.returncode, 0, response.stderr)
            result = json.loads(response.stdout)
            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["actions"][0]["action"], "create")

    def test_public_settings_merge_operation_is_versioned(self):
        with tempfile.TemporaryDirectory() as temp:
            payload = {
                "api_version": "1.0.0", "operation": "install.merge-settings",
                "target": temp, "path": ".claude/settings.json",
                "fragment": {"hooks": {"Stop": ["agentic-stop"]}},
            }
            response = subprocess.run([sys.executable, str(ROOT / "runtime/run.py")],
                                      input=json.dumps(payload), text=True,
                                      capture_output=True)
            self.assertEqual(response.returncode, 0, response.stderr)
            result = json.loads(response.stdout)
            self.assertTrue(result["ok"])
            self.assertTrue((pathlib.Path(temp) / ".claude/settings.json").is_file())


class InstallerDecisionTests(unittest.TestCase):
    """Operator decisions, journal recording and permission bits (G1-G7)."""

    def journal(self, target):
        return json.loads((pathlib.Path(target) / ".agentic/agentic-os/install.json").read_text())

    def run_public(self, operation, **fields):
        payload = {"api_version": "1.0.0", "operation": operation, **fields}
        response = subprocess.run([sys.executable, str(ROOT / "runtime/run.py")],
                                  input=json.dumps(payload), text=True, capture_output=True)
        return response.returncode, json.loads(response.stdout)

    @staticmethod
    def digest(data):
        return hashlib.sha256(data).hexdigest()

    # G1 validation before writes

    def test_g1_unknown_file_spec_fields_fail_before_any_write(self):
        with tempfile.TemporaryDirectory() as temp:
            for field in ("kind", "kinds", "Kind", "expect_sha", "mode"):
                with self.assertRaisesRegex(ValueError, "unknown installation file field"):
                    apply_install(temp, {"a.txt": "x\n", "b.txt": {"content": "y\n", field: "block"}})
            self.assertEqual(os.listdir(temp), [])

    def test_g1_digests_must_be_exact_lowercase_hex(self):
        with tempfile.TemporaryDirectory() as temp:
            for bad in ("ABC", "0" * 63, 7, "G" * 64, "A" * 64, "0" * 64 + "zz", "0" * 64 + "\n"):
                with self.assertRaises(ValueError):
                    plan_install(temp, {"x.md": {"content": "x", "expect_sha256": bad}})
            apply_install(temp, {"a.md": "a\n"})
            for bad in ({"a.md": "nope"}, {"a.md": 3}, ["a.md"], {"a.md": "0" * 64 + "zz"}):
                with self.assertRaises(ValueError):
                    remove_install(temp, confirm=bad)
            self.assertTrue((pathlib.Path(temp) / "a.md").exists())

    def test_g1_record_sets_fields_without_touching_file_entries(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            recorded = installer.record_journal(target, {"answers": {"presets": ["developer"]},
                                                          "phase": "interview"})
            self.assertEqual(recorded["recorded"], ["answers", "phase"])
            apply_install(target, {"a.md": "a\n"}, agentic_os_version="1.2.3")
            before = self.journal(target)
            installer.record_journal(target, {"phase": "done", "follow_ups": ["review"],
                                              "stack_discovery": {"language": "python"},
                                              "sdlc_skills": ["gate-runner"], "qe_blueprints": [],
                                              "adoption": {"mode": "adopt-existing"},
                                              "agentic_os_version": "1.2.4"})
            after = self.journal(target)
            self.assertEqual(after["files"], before["files"])
            self.assertEqual(after["answers"], {"presets": ["developer"]})
            self.assertEqual((after["phase"], after["agentic_os_version"]), ("done", "1.2.4"))

    def test_g1_record_rejects_files_unknown_keys_bad_values_and_nonstandard_json(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"a.md": "a\n"})
            journal = (target / ".agentic/agentic-os/install.json").read_bytes()
            for bad in ({}, {"files": {}}, {"files": []}, {"files": ["a.md"]}, {"other": 1},
                        {"phase": "sideways"}, {"answers": ["x"]}, {"follow_ups": "x"},
                        {"follow_ups": [1]}, {"agentic_os_version": "one"},
                        {"answers": {"x": float("nan")}}, {"stack_discovery": {"y": float("inf")}},
                        {"answers": {"x": "y" * 1_100_000}}, [1]):
                with self.assertRaises(ValueError, msg=str(bad)[:40]):
                    installer.record_journal(target, bad)
            self.assertEqual((target / ".agentic/agentic-os/install.json").read_bytes(), journal)

    def test_g1_record_rejects_nan_through_the_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            payload = ('{"api_version":"1.0.0","operation":"install.record","target":%s,'
                       '"fields":{"answers":{"x":NaN}}}' % json.dumps(temp))
            response = subprocess.run([sys.executable, str(ROOT / "runtime/run.py")],
                                      input=payload, text=True, capture_output=True)
            self.assertEqual(response.returncode, 2)
            self.assertFalse((pathlib.Path(temp) / ".agentic").exists())

    def test_g1_record_refuses_an_invalid_journal_and_detects_a_concurrent_edit(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            (target / ".agentic/agentic-os").mkdir(parents=True)
            broken = target / ".agentic/agentic-os/install.json"
            broken.write_text("{not json")
            with self.assertRaises(RuntimeError):
                installer.record_journal(target, {"phase": "done"})
            self.assertEqual(broken.read_text(), "{not json")
            broken.write_text("{}")
            original = installer._journal

            def racing(root):
                value = original(root)
                broken.write_text('{"phase": "verify"}')
                return value
            with patch.object(installer, "_journal", racing):
                with self.assertRaises(RuntimeError):
                    installer.record_journal(target, {"phase": "done"})
            self.assertEqual(json.loads(broken.read_text()), {"phase": "verify"})

    # G2 confirmed apply is compare-and-swap

    def test_g2_confirmed_replacement_overwrites_only_the_reviewed_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"guide.md": "v1\n"})
            (target / "guide.md").write_text("user edit\n")
            plain = {"guide.md": {"content": "v2\n"}}
            self.assertEqual(plan_install(target, plain)["actions"][0]["action"], "preserve_modified")
            confirmed = {"guide.md": {"content": "v2\n", "expect_sha256": self.digest(b"user edit\n")}}
            self.assertEqual(plan_install(target, confirmed)["actions"][0]["action"], "replace_confirmed")
            self.assertEqual(apply_install(target, confirmed)["applied"], ["guide.md"])
            self.assertEqual((target / "guide.md").read_text(), "v2\n")
            self.assertEqual(self.journal(target)["files"]["guide.md"]["sha256"], self.digest(b"v2\n"))

    def test_g2_stale_or_absent_confirmation_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            (target / "guide.md").write_text("edited after review\n")
            reviewed = self.digest(b"reviewed\n")
            for files in ({"a-first.txt": "new\n", "guide.md": {"content": "v2\n", "expect_sha256": reviewed}},
                          {"a-first.txt": "new\n", "gone.md": {"content": "x\n", "expect_sha256": reviewed}}):
                self.assertIn("stale_confirmation",
                              [item["action"] for item in plan_install(target, files)["actions"]])
                with self.assertRaisesRegex(RuntimeError, "changed since it was reviewed"):
                    apply_install(target, files)
            self.assertEqual(sorted(os.listdir(target)), ["guide.md"])
            self.assertEqual((target / "guide.md").read_text(), "edited after review\n")

    # G3 confirmation never raises ownership

    def test_g3_confirmed_apply_of_a_preexisting_file_stays_adopted_user(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            (target / "CLAUDE.md").write_text("MY NOTES\n")
            apply_install(target, {"CLAUDE.md": {"content": "MY NOTES\nblock\n",
                                                  "expect_sha256": self.digest(b"MY NOTES\n")}})
            entry = self.journal(target)["files"]["CLAUDE.md"]
            self.assertEqual((entry["owner"], entry["origin"]), ("user", "adopted-existing"))
            apply_install(target, {"CLAUDE.md": {"content": "MY NOTES\nblock v2\n", "origin": "plugin",
                                                  "expect_sha256": self.digest(b"MY NOTES\nblock\n")}})
            entry = self.journal(target)["files"]["CLAUDE.md"]
            self.assertEqual((entry["owner"], entry["origin"]), ("user", "adopted-existing"))
            self.assertEqual(remove_install(target)["removed"], [])
            with self.assertRaisesRegex(ValueError, "existed before agentic-os"):
                remove_install(target, confirm={"CLAUDE.md": self.digest(b"MY NOTES\nblock v2\n")})
            self.assertEqual((target / "CLAUDE.md").read_text(), "MY NOTES\nblock v2\n")

    def test_g3_confirmation_cannot_claim_or_promote_ownership(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            (target / "secret.env").write_text("K=1\n")
            apply_install(target, {"gen.md": {"content": "g\n", "owner": "generated"},
                                   "mod.md": "m\n"})
            (target / "mod.md").write_text("edited\n")
            apply_install(target, {"mod.md": "m2\n"})          # demotes mod.md to user
            cases = (("secret.env", b"K=1\n", "managed"), ("secret.env", b"K=1\n", "generated"),
                     ("gen.md", b"g\n", "managed"), ("mod.md", b"edited\n", "managed"))
            for path, current, owner in cases:
                with self.assertRaisesRegex(RuntimeError, "cannot claim"):
                    apply_install(target, {"a-first.txt": "x\n",
                                           path: {"content": current.decode() + "+\n",
                                                  "expect_sha256": self.digest(current), "owner": owner}})
                self.assertFalse((target / "a-first.txt").exists())
            self.assertEqual((target / "secret.env").read_text(), "K=1\n")

    def test_g3_confirmation_may_keep_the_recorded_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"gen.md": {"content": "g\n", "owner": "generated"},
                                   "man.md": "m\n"})
            apply_install(target, {"gen.md": {"content": "g2\n", "owner": "generated",
                                              "expect_sha256": self.digest(b"g\n")},
                                   "man.md": {"content": "m2\n", "owner": "managed",
                                              "expect_sha256": self.digest(b"m\n")}})
            files = self.journal(target)["files"]
            self.assertEqual((files["gen.md"]["owner"], files["man.md"]["owner"]), ("generated", "managed"))
            self.assertEqual(remove_install(target)["removed"], ["man.md"])
            self.assertTrue((target / "gen.md").exists())

    def test_g3_unchanged_bytes_never_change_an_existing_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"m.md": "m\n"})
            before = self.journal(target)["files"]["m.md"]
            apply_install(target, {"m.md": {"content": "m\n", "owner": "generated",
                                            "template": "other"}})
            apply_install(target, {"m.md": {"content": "m\n", "expect_sha256": self.digest(b"m\n")}})
            self.assertEqual(self.journal(target)["files"]["m.md"], before)

    # G4 generic removal

    def test_g4_generic_removal_keeps_generated_and_user_files(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            (target / "mine.md").write_text("mine\n")
            apply_install(target, {"gen.md": {"content": "g\n", "owner": "generated"},
                                   "mine.md": "mine\n", "man.md": "m\n", "mod.md": "x\n"})
            (target / "mod.md").write_text("edited\n")
            result = remove_install(target)
            self.assertEqual(result["removed"], ["man.md"])
            self.assertEqual(sorted(result["preserved"]), ["gen.md", "mine.md", "mod.md"])

    # G5 confirmed removal

    def test_g5_confirmed_removal_of_generated_and_modified_managed_files(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"gen.md": {"content": "g\n", "owner": "generated"},
                                   "mod.md": "m\n", "keep.md": "k\n"})
            (target / "mod.md").write_text("edited\n")
            result = remove_install(target, confirm={"gen.md": self.digest(b"g\n"),
                                                     "mod.md": self.digest(b"edited\n")})
            self.assertEqual(sorted(result["removed"]), ["gen.md", "keep.md", "mod.md"])
            self.assertEqual(self.journal(target)["files"], {})

    def test_g5_entries_demoted_by_generic_removal_remain_confirmable(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"m.txt": "m\n", "o.txt": "o\n"})
            (target / "m.txt").write_text("edited\n")
            path = target / ".agentic/agentic-os/install.json"
            journal = json.loads(path.read_text())
            for key in ("device", "inode", "mtime_ns"):   # legacy entry without identity
                journal["files"]["o.txt"].pop(key)
            path.write_text(json.dumps(journal))
            first = remove_install(target)
            self.assertEqual(sorted(first["preserved"]), ["m.txt", "o.txt"])
            self.assertEqual(self.journal(target)["files"]["m.txt"]["owner"], "user")
            second = remove_install(target, confirm={"m.txt": self.digest(b"edited\n"),
                                                     "o.txt": self.digest(b"o\n")})
            self.assertEqual(sorted(second["removed"]), ["m.txt", "o.txt"])

    def test_g5_stale_confirmation_deletes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"a.md": "a\n", "gen.md": {"content": "g\n", "owner": "generated"}})
            (target / "gen.md").write_text("changed\n")
            with self.assertRaisesRegex(RuntimeError, "changed since it was reviewed"):
                remove_install(target, confirm={"gen.md": self.digest(b"g\n")})
            self.assertTrue((target / "a.md").exists())
            self.assertEqual((target / "gen.md").read_text(), "changed\n")

    def test_g5_confirmation_is_bound_to_its_own_selected_path(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"a.md": {"content": "same\n", "owner": "generated"},
                                   "b.md": {"content": "same\n", "owner": "generated"}})
            digest = self.digest(b"same\n")
            (target / "a.md").write_text("edited\n")
            with self.assertRaisesRegex(RuntimeError, "changed since it was reviewed"):
                remove_install(target, confirm={"a.md": digest})
            with self.assertRaisesRegex(ValueError, "unselected path"):
                remove_install(target, ["a.md"], confirm={"b.md": digest})
            for alias in ("./b.md", "sub/../b.md", "b.md/", "/b.md"):
                with self.assertRaises(ValueError, msg=alias):
                    installer._relative_path(alias)
                with self.assertRaises(ValueError, msg=alias):
                    remove_install(target, ["b.md"], confirm={alias: digest})
            (target / "a.md").write_text("same\n")
            self.assertEqual(remove_install(target, ["a.md"], confirm={"a.md": digest})["removed"], ["a.md"])
            self.assertTrue((target / "b.md").exists())

    def test_g5_preexisting_files_never_accept_a_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            (target / "mine.md").write_text("mine\n")
            apply_install(target, {"mine.md": "mine\n"})
            with self.assertRaisesRegex(ValueError, "existed before agentic-os"):
                remove_install(target, confirm={"mine.md": self.digest(b"mine\n")})
            path = target / ".agentic/agentic-os/install.json"
            journal = json.loads(path.read_text())
            journal["files"]["mine.md"].pop("origin")      # older user entry without origin
            path.write_text(json.dumps(journal))
            with self.assertRaisesRegex(ValueError, "existed before agentic-os"):
                remove_install(target, confirm={"mine.md": self.digest(b"mine\n")})
            self.assertEqual((target / "mine.md").read_text(), "mine\n")

    def test_g5_confirmation_for_an_absent_file_is_reported_unapplied(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"sub/g.md": {"content": "g\n", "owner": "generated"}})
            (target / "sub").rename(target / "sub.bak")
            result = remove_install(target, confirm={"sub/g.md": self.digest(b"g\n")})
            self.assertEqual((result["removed"], result["unapplied_confirmations"]), ([], ["sub/g.md"]))

    def test_g5_reapplying_over_a_preexisting_file_keeps_it_unconfirmable(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            (target / "CLAUDE.md").write_text("my own notes\n")
            apply_install(target, {"CLAUDE.md": "template v1\n"})
            apply_install(target, {"CLAUDE.md": "template v2\n"})
            entry = self.journal(target)["files"]["CLAUDE.md"]
            self.assertEqual((entry["owner"], entry["origin"]), ("user", "adopted-existing"))
            apply_install(target, {"CLAUDE.md": {"content": "notes+\n",
                                                  "expect_sha256": self.digest(b"my own notes\n")}})
            apply_install(target, {"CLAUDE.md": "template v3\n"})
            self.assertEqual(self.journal(target)["files"]["CLAUDE.md"]["origin"], "adopted-existing")
            with self.assertRaisesRegex(ValueError, "existed before agentic-os"):
                remove_install(target, confirm={"CLAUDE.md": self.digest(b"notes+\n")})
            self.assertEqual((target / "CLAUDE.md").read_text(), "notes+\n")

    def test_g5_modified_installer_file_stays_confirmable_after_reapply(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"a.md": "v1\n"})
            (target / "a.md").write_text("edited\n")
            apply_install(target, {"a.md": "v2\n"})
            self.assertEqual(self.journal(target)["files"]["a.md"]["origin"], "user-modified")
            result = remove_install(target, confirm={"a.md": self.digest(b"edited\n")})
            self.assertEqual(result["removed"], ["a.md"])

    def test_g5_confirmation_for_an_absent_managed_file_is_unapplied(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"g.md": {"content": "g\n", "owner": "generated"}})
            (target / "g.md").unlink()
            result = remove_install(target, confirm={"g.md": self.digest(b"g\n")})
            self.assertEqual((result["missing"], result["unapplied_confirmations"]), (["g.md"], ["g.md"]))
            with self.assertRaisesRegex(ValueError, "not journaled"):
                remove_install(target, ["g.md"], confirm={"g.md": self.digest(b"g\n")})

    def test_g1_nonstandard_json_in_an_existing_journal_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"a.md": "a\n"})
            path = target / ".agentic/agentic-os/install.json"
            text = path.read_text().replace('"files"', '"answers": {"x": NaN},\n  "files"', 1)
            path.write_text(text)
            for step in (lambda: installer.record_journal(target, {"phase": "done"}),
                         lambda: apply_install(target, {"b.md": "b\n"}),
                         lambda: remove_install(target)):
                with self.assertRaises(RuntimeError):
                    step()
            self.assertEqual(path.read_text(), text)
            self.assertTrue((target / "a.md").exists())

    def test_g1_settings_merge_never_reads_or_writes_nonstandard_json(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            with self.assertRaisesRegex(ValueError, "standard JSON"):
                merge_settings_file(target, "s.json", {"x": float("nan")})
            self.assertEqual(os.listdir(target), [])
            (target / "s.json").write_text('{"a": Infinity}')
            with self.assertRaises(RuntimeError):
                merge_settings_file(target, "s.json", {"b": 1})
            self.assertEqual((target / "s.json").read_text(), '{"a": Infinity}')
            payload = ('{"api_version":"1.0.0","operation":"install.merge-settings","target":%s,'
                       '"path":"t.json","fragment":{"x":NaN}}' % json.dumps(temp))
            response = subprocess.run([sys.executable, str(ROOT / "runtime/run.py")],
                                      input=payload, text=True, capture_output=True)
            self.assertEqual(response.returncode, 2)
            self.assertFalse((target / "t.json").exists())

    def test_g5_confirmation_keys_that_name_the_same_path_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"g.md": {"content": "g\n", "owner": "generated"}})
            with self.assertRaises(ValueError):
                remove_install(target, confirm={"g.md": self.digest(b"g\n"), "./g.md": self.digest(b"x")})
            self.assertTrue((target / "g.md").exists())

    def test_g5_confirmed_apply_keeps_an_installer_origin_confirmable(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"a.md": "v1\n"})
            (target / "a.md").write_text("edited\n")
            remove_install(target, ["a.md"])                       # demoted, origin plugin
            apply_install(target, {"a.md": {"content": "v2\n", "expect_sha256": self.digest(b"edited\n")}})
            entry = self.journal(target)["files"]["a.md"]
            self.assertEqual((entry["owner"], entry["origin"]), ("user", "plugin"))
            self.assertEqual(remove_install(target, confirm={"a.md": self.digest(b"v2\n")})["removed"], ["a.md"])

    def test_g5_legacy_entries_without_origin_stay_confirmable_after_demotion(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            path = target / ".agentic/agentic-os/install.json"
            path.parent.mkdir(parents=True)
            (target / "a.md").write_text("rendered-edited\n")
            path.write_text(json.dumps({"files": {"a.md": {
                "sha256": self.digest(b"rendered\n"), "template": "t", "owner": "managed"}}}))
            self.assertEqual(remove_install(target)["preserved"], ["a.md"])
            entry = self.journal(target)["files"]["a.md"]
            self.assertEqual((entry["owner"], entry["origin"]), ("user", "user-modified"))
            result = remove_install(target, confirm={"a.md": self.digest(b"rendered-edited\n")})
            self.assertEqual((result["removed"], result["unapplied_confirmations"]), (["a.md"], []))

    def test_g1_out_of_range_numbers_in_the_journal_are_refused_before_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"a.md": "a\n"})
            path = target / ".agentic/agentic-os/install.json"
            text = path.read_text().replace('"files"', '"answers": {"x": 1e400},\n  "files"', 1)
            path.write_text(text)
            for step in (lambda: apply_install(target, {"b.md": "b\n"}),
                         lambda: remove_install(target),
                         lambda: installer.record_journal(target, {"phase": "done"})):
                with self.assertRaises(RuntimeError):
                    step()
            self.assertEqual(path.read_text(), text)
            self.assertFalse((target / "b.md").exists())
            self.assertTrue((target / "a.md").exists())

    def test_kept_files_record_their_current_bytes_but_generated_keeps_its_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"m.md": "m\n", "g.md": {"content": "g\n", "owner": "generated"}})
            (target / "m.md").unlink()
            (target / "m.md").write_text("edited\n")        # new inode as well as new bytes
            (target / "g.md").write_text("g edited\n")
            remove_install(target)
            files = self.journal(target)["files"]
            self.assertEqual((files["m.md"]["owner"], files["m.md"]["sha256"]), ("user", self.digest(b"edited\n")))
            info = (target / "m.md").stat()
            self.assertEqual((files["m.md"]["device"], files["m.md"]["inode"], files["m.md"]["mtime_ns"]),
                             (info.st_dev, info.st_ino, info.st_mtime_ns))
            self.assertEqual((files["g.md"]["owner"], files["g.md"]["sha256"]), ("generated", self.digest(b"g\n")))
            # The refreshed record is still confirmable at the bytes on disk.
            self.assertEqual(remove_install(target, ["m.md"], confirm={"m.md": self.digest(b"edited\n")})["removed"],
                             ["m.md"])

    # G6 absent entries

    def test_g6_absent_files_drop_only_managed_entries_in_reachable_directories(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            (target / "mine.md").write_text("mine\n")
            apply_install(target, {"mine.md": "mine\n", "gone.md": "g\n",
                                   "sub/moved.md": "m\n", "gen.md": {"content": "x\n", "owner": "generated"}})
            (target / "mine.md").rename(target / "mine.bak")
            (target / "gone.md").unlink()
            (target / "gen.md").unlink()
            (target / "sub").rename(target / "sub.bak")
            result = remove_install(target)
            self.assertEqual(sorted(result["missing"]), ["gen.md", "gone.md"])
            self.assertEqual(sorted(result["preserved"]), ["mine.md", "sub/moved.md"])
            self.assertEqual(sorted(self.journal(target)["files"]), ["mine.md", "sub/moved.md"])

    # G7 permissions

    def test_g7_new_files_follow_umask_and_replacements_keep_mode(self):
        old = os.umask(0o022)
        try:
            with tempfile.TemporaryDirectory() as temp:
                target = pathlib.Path(temp)
                apply_install(target, {"a.txt": "one\n", "bin/tool.sh": "one\n"})
                self.assertEqual(oct((target / "a.txt").stat().st_mode & 0o7777), "0o644")
                os.chmod(target / "bin/tool.sh", 0o755)
                os.chmod(target / "a.txt", 0o600)
                apply_install(target, {"a.txt": "two\n", "bin/tool.sh": "two\n"})
                self.assertEqual(oct((target / "bin/tool.sh").stat().st_mode & 0o7777), "0o755")
                self.assertEqual(oct((target / "a.txt").stat().st_mode & 0o7777), "0o600")
                merge_settings_file(target, "settings.json", {"a": 1})
                self.assertEqual(oct((target / "settings.json").stat().st_mode & 0o7777), "0o644")
                os.chmod(target / "bin/tool.sh", 0o4755)
                apply_install(target, {"bin/tool.sh": "three\n"})
                self.assertEqual(oct((target / "bin/tool.sh").stat().st_mode & 0o7777), "0o755")
        finally:
            os.umask(old)

    def test_g7_journal_is_rewritten_owner_only(self):
        with tempfile.TemporaryDirectory() as temp:
            target = pathlib.Path(temp)
            apply_install(target, {"tool.sh": "one\n"})
            journal = target / ".agentic/agentic-os/install.json"
            self.assertEqual(oct(journal.stat().st_mode & 0o7777), "0o600")
            for step in (lambda: apply_install(target, {"tool.sh": "two\n"}),
                         lambda: installer.record_journal(target, {"phase": "done"}),
                         lambda: merge_settings_file(target, "s.json", {"a": 1}),
                         lambda: remove_install(target, ["s.json"])):
                os.chmod(journal, 0o666)
                step()
                self.assertEqual(oct(journal.stat().st_mode & 0o7777), "0o600")

    def test_public_operations_are_versioned(self):
        with tempfile.TemporaryDirectory() as temp:
            code, result = self.run_public("install.record", target=temp,
                                           fields={"phase": "preflight", "answers": {"defaults": True}})
            self.assertEqual(code, 0, result)
            code, result = self.run_public("install.apply", target=temp, files={
                "g.md": {"content": "g\n", "owner": "generated", "expect_sha256": None}})
            self.assertEqual(code, 0, result)
            code, result = self.run_public("install.remove", target=temp, paths=["g.md"],
                                           confirm={"g.md": self.digest(b"g\n")})
            self.assertEqual((code, result["result"]["removed"]), (0, ["g.md"]))
            code, result = self.run_public("install.record", target=temp, fields={"files": {}})
            self.assertEqual((code, result["ok"]), (2, False))

if __name__ == "__main__":
    unittest.main()
