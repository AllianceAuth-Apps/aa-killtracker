import json
from unittest.mock import patch

from requests.exceptions import HTTPError

from django.contrib.auth.models import Group

from app_utils.django import app_labels
from app_utils.testing import NoSocketsTestCase

from killtracker.core.zkb import Killmail
from killtracker.models import Tracker
from killtracker.tests.testdata.factories import KillmailFactory, TrackerFactory

MODULE_PATH = "killtracker.core.trackers"

if "discord" in app_labels():

    @patch(MODULE_PATH + "._import_discord_user")
    class TestGroupPings(NoSocketsTestCase):
        @classmethod
        def setUpClass(cls):
            super().setUpClass()
            cls.group_1 = Group.objects.create(name="Dummy Group 1")
            cls.group_2 = Group.objects.create(name="Dummy Group 2")

        @staticmethod
        def _my_group_to_role(group: Group) -> dict:
            if not isinstance(group, Group):
                raise TypeError("group must be of type Group")

            return {"id": group.pk, "name": group.name}

        def test_can_ping_one_group(self, mock_import_discord_user):
            # given
            mock_import_discord_user.return_value.objects.group_to_role.side_effect = (
                self._my_group_to_role
            )
            tracker = TrackerFactory()
            tracker.ping_groups.add(self.group_1)
            killmail = tracker.process_killmail(KillmailFactory())

            # when
            tracker.generate_killmail_message(Killmail.from_json(killmail.asjson()))

            # then
            self.assertTrue(
                mock_import_discord_user.return_value.objects.group_to_role.called
            )
            self.assertEqual(tracker.webhook._main_queue.size(), 1)
            message = json.loads(tracker.webhook._main_queue.dequeue())
            self.assertIn(f"<@&{self.group_1.pk}>", message["content"])

        def test_can_ping_multiple_groups(self, mock_import_discord_user):
            # given
            mock_import_discord_user.return_value.objects.group_to_role.side_effect = (
                self._my_group_to_role
            )
            tracker = TrackerFactory()
            tracker.ping_groups.add(self.group_1)
            tracker.ping_groups.add(self.group_2)
            killmail = tracker.process_killmail(KillmailFactory())

            # when
            tracker.generate_killmail_message(Killmail.from_json(killmail.asjson()))

            # then
            self.assertTrue(
                mock_import_discord_user.return_value.objects.group_to_role.called
            )
            self.assertEqual(tracker.webhook._main_queue.size(), 1)
            message = json.loads(tracker.webhook._main_queue.dequeue())
            self.assertIn(f"<@&{self.group_1.pk}>", message["content"])
            self.assertIn(f"<@&{self.group_2.pk}>", message["content"])

        def test_can_combine_with_channel_ping(self, mock_import_discord_user):
            # given
            mock_import_discord_user.return_value.objects.group_to_role.side_effect = (
                self._my_group_to_role
            )
            tracker = TrackerFactory()
            tracker.ping_groups.add(self.group_1)
            tracker.ping_type = Tracker.ChannelPingType.HERE
            tracker.save()
            killmail = tracker.process_killmail(KillmailFactory())

            # when
            tracker.generate_killmail_message(Killmail.from_json(killmail.asjson()))

            # then
            self.assertTrue(
                mock_import_discord_user.return_value.objects.group_to_role.called
            )
            self.assertEqual(tracker.webhook._main_queue.size(), 1)
            message = json.loads(tracker.webhook._main_queue.dequeue())
            self.assertIn(f"<@&{self.group_1.pk}>", message["content"])
            self.assertIn("@here", message["content"])

        def test_can_handle_error_from_discord(self, mock_import_discord_user):
            # given
            mock_import_discord_user.return_value.objects.group_to_role.side_effect = (
                HTTPError
            )
            tracker = TrackerFactory()
            tracker.ping_groups.add(self.group_1)
            killmail = tracker.process_killmail(KillmailFactory())

            # when
            tracker.generate_killmail_message(Killmail.from_json(killmail.asjson()))

            # then
            self.assertTrue(
                mock_import_discord_user.return_value.objects.group_to_role.called
            )
            self.assertEqual(tracker.webhook._main_queue.size(), 1)
            message = json.loads(tracker.webhook._main_queue.dequeue())
            self.assertNotIn(f"<@&{self.group_1.pk}>", message["content"])


# ---
