import tempfile
import unittest
from unittest.mock import Mock, patch

from zog.network_register.operations import ensure_a

DOMAIN = 'example.uk'
NAME = 'demo.example.uk'
MARKER = 'Managed by Zog network-register: ' + NAME
RECORD = dict(id='record', type='A', name=NAME, content='192.0.2.1',
              ttl=60, proxied=False, comment=MARKER)


def client(rows):
    c = Mock(account='a' * 32)
    c.pages.side_effect = lambda path, query: (
        [{'id': 'zone', 'name': DOMAIN, 'account': {'id': c.account}}]
        if path == '/zones' else list(rows()))
    return c


class LegacyUncertainRecoveryTests(unittest.TestCase):
    def test_uncertain_create_with_empty_inventory_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as root:
            c = client(lambda: [])
            c.result.side_effect = TimeoutError('lost response')
            with self.assertRaises(TimeoutError):
                ensure_a(c, DOMAIN, NAME, '192.0.2.1', root)
            with self.assertRaises(RuntimeError):
                ensure_a(c, DOMAIN, NAME, '192.0.2.1', root)
            self.assertEqual(c.result.call_count, 1)

    def test_uncertain_update_with_old_inventory_is_not_replayed(self):
        with tempfile.TemporaryDirectory() as root:
            c = client(lambda: [RECORD])
            c.result.side_effect = TimeoutError('lost response')
            with self.assertRaises(TimeoutError):
                ensure_a(c, DOMAIN, NAME, '192.0.2.2', root)
            with self.assertRaises(RuntimeError):
                ensure_a(c, DOMAIN, NAME, '192.0.2.2', root)
            self.assertEqual(c.result.call_count, 1)

    def test_lost_response_with_visible_result_finalizes_read_only(self):
        with tempfile.TemporaryDirectory() as root:
            visible = [False]
            c = client(lambda: [RECORD] if visible[0] else [])
            def accepted(method, path, body):
                visible[0] = True
                raise TimeoutError('lost response')
            c.result.side_effect = accepted
            with self.assertRaises(TimeoutError):
                ensure_a(c, DOMAIN, NAME, '192.0.2.1', root)
            self.assertEqual(
                ensure_a(c, DOMAIN, NAME, '192.0.2.1', root), RECORD)
            self.assertEqual(c.result.call_count, 1)

    def test_prewrite_storage_fault_prevents_provider_call(self):
        with tempfile.TemporaryDirectory() as root:
            c = client(lambda: [])
            with patch('zog.network_register.operations.save',
                       side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    ensure_a(c, DOMAIN, NAME, '192.0.2.1', root)
            c.result.assert_not_called()


if __name__ == '__main__':
    unittest.main()
