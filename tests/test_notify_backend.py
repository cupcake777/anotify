"""Tests for anotify notify_backend module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from anotify.notify_backend import notify, play_sound


class TestNotify:
    def test_windows_toast(self):
        with patch("anotify.notify_backend.platform") as mock_plat, \
             patch("anotify.notify_backend.subprocess") as mock_sub:
            mock_plat.system.return_value = "Windows"
            mock_sub.run.return_value = MagicMock()
            result = notify("Title", "Message", "medium")
            assert result is True
            mock_sub.run.assert_called_once()

    def test_macos_notify(self):
        with patch("anotify.notify_backend.platform") as mock_plat, \
             patch("anotify.notify_backend.subprocess") as mock_sub:
            mock_plat.system.return_value = "Darwin"
            mock_sub.run.return_value = MagicMock()
            result = notify("Title", "Message", "medium")
            assert result is True

    def test_linux_notify(self):
        with patch("anotify.notify_backend.platform") as mock_plat, \
             patch("anotify.notify_backend.subprocess") as mock_sub:
            mock_plat.system.return_value = "Linux"
            mock_sub.run.return_value = MagicMock()
            result = notify("Title", "Message", "medium")
            assert result is True

    def test_unknown_platform_fallback(self, capsys):
        with patch("anotify.notify_backend.platform") as mock_plat:
            mock_plat.system.return_value = "FreeBSD"
            result = notify("Title", "Message", "medium")
            assert result is False
            captured = capsys.readouterr()
            assert "Title" in captured.err


class TestPlaySound:
    def test_low_priority_no_sound(self):
        """Low/medium priority should not play sound."""
        play_sound("low")
        play_sound("medium")

    def test_high_priority(self):
        with patch("anotify.notify_backend.platform") as mock_plat, \
             patch("anotify.notify_backend.subprocess") as mock_sub:
            mock_plat.system.return_value = "Darwin"
            mock_sub.run.return_value = MagicMock()
            play_sound("high")
            mock_sub.run.assert_called_once()

    def test_critical_priority(self):
        with patch("anotify.notify_backend.platform") as mock_plat, \
             patch("anotify.notify_backend.subprocess") as mock_sub:
            mock_plat.system.return_value = "Darwin"
            mock_sub.run.return_value = MagicMock()
            play_sound("critical")
            mock_sub.run.assert_called_once()

    def test_unknown_platform_no_crash(self):
        with patch("anotify.notify_backend.platform") as mock_plat:
            mock_plat.system.return_value = "FreeBSD"
            play_sound("high")  # should not raise
