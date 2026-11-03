"""Authentication regressions. All account operations use simulated services."""
import asyncio
import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telethon import TelegramClient, errors, functions, types
from telepilot.config import Paths
from telepilot.core.models import DomainError
from telepilot.service import ApplicationService
from telepilot.telegram.client import TelethonGateway


API_ID = "123456"
API_HASH = "a" * 32
PHONE = "+33612345678"


class AuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.paths = Paths(Path(self.temporary.name))
        self.paths.prepare()
        self.gateway = TelethonGateway(self.paths.sessions / "test")
        self.patch_client = patch("telepilot.telegram.client.TelegramClient", autospec=True)
        self.constructor = self.patch_client.start()
        self.client = self.constructor.return_value
        # Telethon.disconnect is sync but returns an awaitable inside a running loop.
        self.client.disconnect = AsyncMock()
        self.client.is_user_authorized.return_value = False
        self.client.get_me.return_value = SimpleNamespace(id=42, first_name="Compte", last_name="Test")
        self.client.send_code_request.return_value = types.auth.SentCode(
            types.auth.SentCodeTypeApp(length=5), "fake-code-hash", timeout=60)
        self.client.log_out.return_value = True

    async def asyncTearDown(self):
        await self.gateway.close()
        self.patch_client.stop()
        self.temporary.cleanup()

    async def configured(self):
        await self.gateway.configure(API_ID, API_HASH)

    async def code_sent(self):
        await self.configured()
        await self.gateway.request_code(PHONE)

    async def test_configure_uses_installed_telethon_signature_and_enters_phone_stage(self):
        await self.configured()
        args, kwargs = self.constructor.call_args
        inspect.signature(TelegramClient).bind(*args, **kwargs)
        self.assertIsInstance(args[0], str)
        self.assertIsInstance(args[1], int)
        self.assertEqual(kwargs["request_retries"], 0)
        self.client.connect.assert_awaited_once()
        self.client.send_code_request.assert_not_awaited()
        self.assertEqual(self.gateway.auth_state, "phone")
        self.assertFalse(self.gateway.connected)

    async def test_empty_invalid_phone_is_rejected_before_telethon_serialization(self):
        await self.configured()
        for phone in ("", "   ", None, "invalid", "06 12 34 56 78", "+", "+123", "+336hello"):
            with self.subTest(phone=phone), self.assertRaises(DomainError):
                await self.gateway.request_code(phone)
        self.client.send_code_request.assert_not_awaited()
        self.assertEqual(self.gateway.auth_state, "phone")

    async def test_configuration_rejects_malformed_api_credentials(self):
        for api_id, api_hash in (("", API_HASH), ("-1", API_HASH), (str(2**31), API_HASH),
                                 ("123456", "z" * 32), ("123456", None)):
            with self.subTest(api_id=api_id), self.assertRaises(DomainError):
                await self.gateway.configure(api_id, api_hash)
        self.constructor.assert_not_called()

    async def test_valid_phone_is_normalized_and_code_hash_reused(self):
        await self.configured()
        await self.gateway.request_code("+33 (6) 12-34-56-78")
        self.client.send_code_request.assert_awaited_once_with(PHONE)
        self.assertEqual(self.gateway.auth_state, "code")
        self.assertIn("application Telegram", self.gateway.code_delivery)
        self.client.is_user_authorized.return_value = True
        await self.gateway.sign_in(code="12345")
        self.client.sign_in.assert_awaited_once_with(phone=PHONE, code="12345", phone_code_hash="fake-code-hash")
        self.assertTrue(self.gateway.connected)
        self.assertIsNone(self.gateway.code_hash)
        self.assertEqual(self.gateway.auth_state, "connected")

    async def test_missing_code_cannot_trigger_implicit_send_or_authenticate(self):
        await self.configured()
        with self.assertRaises(DomainError):
            await self.gateway.sign_in(code="12345")
        await self.gateway.request_code(PHONE)
        for code in ("", "  ", "invalid", None):
            with self.assertRaises(DomainError):
                await self.gateway.sign_in(code=code)
        self.client.sign_in.assert_not_awaited()

    async def test_two_factor_is_requested_only_after_telegram_challenge(self):
        await self.code_sent()
        with self.assertRaises(DomainError):
            await self.gateway.sign_in(code="12345", password="do-not-send-yet")
        self.client.sign_in.side_effect = errors.SessionPasswordNeededError(request=None)
        await self.gateway.sign_in(code="12345")
        self.assertEqual(self.gateway.auth_state, "password")
        self.assertFalse(self.gateway.connected)
        self.client.sign_in.reset_mock(side_effect=True)
        with self.assertRaises(DomainError):
            await self.gateway.sign_in(password="")
        self.client.is_user_authorized.return_value = True
        await self.gateway.sign_in(password="fake-password")
        self.client.sign_in.assert_awaited_once_with(password="fake-password")
        self.assertTrue(self.gateway.connected)

    async def test_invalid_code_stays_on_code_stage_and_expired_code_returns_to_phone(self):
        await self.code_sent()
        self.client.sign_in.side_effect = errors.PhoneCodeInvalidError(request=None)
        with self.assertRaises(errors.PhoneCodeInvalidError):
            await self.gateway.sign_in(code="12345")
        self.assertEqual(self.gateway.auth_state, "code")
        self.client.sign_in.side_effect = errors.PhoneCodeExpiredError(request=None)
        with self.assertRaises(errors.PhoneCodeExpiredError):
            await self.gateway.sign_in(code="12345")
        self.assertEqual(self.gateway.auth_state, "phone")
        self.assertIsNone(self.gateway.code_hash)

    async def test_wrong_password_stays_on_password_stage(self):
        await self.code_sent()
        self.client.sign_in.side_effect = errors.SessionPasswordNeededError(request=None)
        await self.gateway.sign_in(code="12345")
        self.client.sign_in.side_effect = errors.PasswordHashInvalidError(request=None)
        with self.assertRaises(errors.PasswordHashInvalidError):
            await self.gateway.sign_in(password="wrong")
        self.assertEqual(self.gateway.auth_state, "password")

    async def test_existing_session_skips_phone_code_and_password(self):
        self.client.is_user_authorized.return_value = True
        await self.configured()
        self.assertEqual(self.gateway.auth_state, "connected")
        self.assertEqual(self.gateway.account_id, 42)
        self.client.send_code_request.assert_not_awaited()
        self.client.sign_in.assert_not_awaited()

    async def test_stale_authorization_without_identity_is_not_connected(self):
        self.client.is_user_authorized.return_value = True
        self.client.get_me.return_value = None
        await self.configured()
        self.assertFalse(self.gateway.connected)
        self.assertEqual(self.gateway.auth_state, "phone")

    async def test_configure_failure_disconnects_and_clears_partial_client(self):
        self.client.connect.side_effect = ConnectionError("sensitive details")
        with self.assertRaises(ConnectionError):
            await self.configured()
        self.client.disconnect.assert_awaited_once()
        self.assertIsNone(self.gateway.client)
        self.assertEqual(self.gateway.auth_state, "credentials")

    async def test_reconfigure_clears_old_challenge(self):
        await self.code_sent()
        await self.configured()
        self.assertIsNone(self.gateway.phone)
        self.assertIsNone(self.gateway.code_hash)
        self.assertEqual(self.gateway.auth_state, "phone")

    async def test_flood_wait_does_not_retry_or_advance_stage(self):
        await self.configured()
        self.client.send_code_request.side_effect = errors.FloodWaitError(request=None, capture=60)
        with self.assertRaises(errors.FloodWaitError):
            await self.gateway.request_code(PHONE)
        self.assertEqual(self.gateway.auth_state, "phone")
        self.assertEqual(self.client.send_code_request.await_count, 1)

    async def test_explicit_auth_dc_migration_can_retry_without_publication_retries(self):
        await self.configured()
        sent = self.client.send_code_request.return_value
        self.client.send_code_request.side_effect = [errors.PhoneMigrateError(request=None, capture=2), sent]
        await self.gateway.request_code(PHONE)
        self.assertEqual(self.client.send_code_request.await_count, 2)
        self.assertEqual(self.gateway.auth_state, "code")

    async def test_logout_and_return_to_phone_clear_transient_challenge(self):
        await self.code_sent()
        await self.gateway.edit_phone()
        self.assertIsNone(self.gateway.code_hash)
        self.assertEqual(self.gateway.auth_state, "phone")
        await self.gateway.logout()
        self.assertEqual(self.gateway.auth_state, "credentials")
        self.assertIsNone(self.gateway.client)

    async def test_service_keychain_failure_keeps_configured_session_and_logs_safe_trace(self):
        service = ApplicationService(self.paths, self.gateway, False)
        with patch("telepilot.service.Keychain") as keychain:
            keychain.return_value.set.side_effect = TypeError("secret-keychain-payload")
            with self.assertLogs("telepilot", level="ERROR") as logs, self.assertRaises(DomainError):
                await service.command("configure", api_id=API_ID, api_hash=API_HASH, remember=True)
        self.assertEqual(service.snapshot()["auth_state"], "phone")
        output = "\n".join(logs.output)
        self.assertIn("TypeError", output)
        self.assertNotIn("secret-keychain-payload", output)
        self.assertNotIn(API_HASH, output)

    async def test_service_restores_secret_from_keychain_without_storing_it_in_sqlite(self):
        service = ApplicationService(self.paths, self.gateway, False)
        service.db.set_setting("api_id", API_ID)
        with patch("telepilot.service.Keychain") as keychain:
            keychain.return_value.get.return_value = API_HASH
            await service.command("configure", api_id="", api_hash="", remember=False)
        values = repr(service.db.rows("SELECT * FROM settings"))
        self.assertNotIn(API_HASH, values)
        self.assertEqual(service.snapshot()["auth_state"], "phone")

    async def test_service_rejects_another_account_in_same_workspace(self):
        service = ApplicationService(self.paths, self.gateway, False)
        service.db.set_setting("account_id", "999")
        self.client.is_user_authorized.return_value = True
        with self.assertRaises(DomainError):
            await service.command("configure", api_id=API_ID, api_hash=API_HASH, remember=False)
        self.assertFalse(self.gateway.connected)
        self.assertEqual(self.gateway.auth_state, "credentials")


class InstalledTelethonTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_type_error_is_in_telethon_serialization_of_missing_phone(self):
        # Real installed Telethon methods. Only the transport is replaced by its
        # serialization step; no Telegram account or network request is used.
        async def serialize(client, request, *args, **kwargs):
            return bytes(request)

        with tempfile.TemporaryDirectory() as folder:
            client = TelegramClient(str(Path(folder) / "test"), int(API_ID), API_HASH)
            try:
                with patch.object(TelegramClient, "__call__", new=serialize):
                    with self.assertRaisesRegex(TypeError, "bytes or str expected.*NoneType"):
                        await client.send_code_request("")
            finally:
                await client.disconnect()

    async def test_real_constructor_configure_and_close_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            gateway = TelethonGateway(Path(folder) / "test")
            with patch.object(TelegramClient, "connect", new_callable=AsyncMock), patch.object(
                TelegramClient, "is_user_authorized", new_callable=AsyncMock, return_value=False
            ):
                try:
                    await gateway.configure(API_ID, API_HASH)
                    self.assertIsInstance(gateway.client, TelegramClient)
                    self.assertEqual(gateway.auth_state, "phone")
                finally:
                    await gateway.close()

