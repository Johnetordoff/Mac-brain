import ssl
import unittest
from unittest import mock

import install as installer


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeContext:
    def __init__(self):
        self.loaded = []

    def load_verify_locations(self, *, cafile=None, capath=None, cadata=None):
        self.loaded.append({"cafile": cafile, "capath": capath, "cadata": cadata})


class BigSurTlsTests(unittest.TestCase):
    def test_darwin_adds_system_keychain_roots_without_disabling_verification(self):
        ctx = FakeContext()
        pem = "-----BEGIN CERTIFICATE-----\\nTEST\\n-----END CERTIFICATE-----\\n"
        with mock.patch.object(installer.platform, "system", return_value="Darwin"), \
             mock.patch.object(installer.ssl, "create_default_context", return_value=ctx) as create, \
             mock.patch.object(installer, "sh", return_value=FakeResult(0, pem)) as sh:
            result = installer.download_ssl_context()

        self.assertIs(result, ctx)
        create.assert_called_once_with()
        self.assertEqual(ctx.loaded[0]["cadata"], pem)
        self.assertIn("/usr/bin/security", sh.call_args.args[0])
        self.assertTrue(any(str(arg).endswith("SystemRootCertificates.keychain") for arg in sh.call_args.args[0]))

    def test_non_darwin_uses_normal_verified_default_context(self):
        ctx = FakeContext()
        with mock.patch.object(installer.platform, "system", return_value="Linux"), \
             mock.patch.object(installer.ssl, "create_default_context", return_value=ctx), \
             mock.patch.object(installer, "sh") as sh:
            result = installer.download_ssl_context()

        self.assertIs(result, ctx)
        self.assertEqual(ctx.loaded, [])
        sh.assert_not_called()

    def test_unload_cleanup_is_captured_and_nonfatal(self):
        with mock.patch.object(installer, "sh", return_value=FakeResult(5, "", "Unload failed: 5")) as sh:
            installer.unload_agent()

        self.assertFalse(sh.call_args.kwargs["check"])
        self.assertTrue(sh.call_args.kwargs["capture"])


if __name__ == "__main__":
    unittest.main()
