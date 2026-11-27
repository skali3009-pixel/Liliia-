from pathlib import Path
import subprocess
import tempfile
import unittest


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        script = (Path(__file__).resolve().parents[1] / 'watchdog.sh').read_text()
        script = script.replace('STATE_DIR="/var/lib/nutrition-bot"',
                                'STATE_DIR="' + str(self.root / 'state') + '"')
        (self.root / 'watchdog.sh').write_text(script)
        self.stub('systemctl', '''case "$1" in
is-active) exit "${TEST_INACTIVE:-0}";;
show) echo "$TEST_RESTARTS";;
*) exit 90;;
esac
''')
        self.stub('curl', '''for arg in "$@"; do
case "$arg" in text=*) printf '%s\\n' "$arg" >> "$TEST_MESSAGES";; esac
done
exit 0
''')
        self.stub('journalctl', 'echo "synthetic test log"\n')
        self.stub('date', 'echo "${TEST_NOW:-10000}"\n')
        (self.root / 'state').mkdir()
        self.state = self.root / 'state/watchdog.state'
        self.state.write_text('FAILS=0\nLAST_ALERT=0\nPREV_RESTARTS=0\n')

    def stub(self, name, body):
        p = self.bin / name
        p.write_text('#!/bin/sh\n' + body)
        p.chmod(0o700)

    def run_check(self, restarts, inactive=0, now=10000):
        env = {'PATH': str(self.bin) + ':/usr/bin:/bin',
               'BOT_TOKEN': 'TEST_ONLY', 'ADMIN_IDS': '1',
               'TEST_MESSAGES': str(self.root / 'messages'),
               'TEST_RESTARTS': str(restarts), 'TEST_INACTIVE': str(inactive),
               'TEST_NOW': str(now)}
        subprocess.run(['/bin/bash', str(self.root / 'watchdog.sh')],
                       env=env, check=True, capture_output=True, text=True)

    def messages(self):
        p = self.root / 'messages'
        return p.read_text() if p.exists() else ''

    def test_old_burst_does_not_become_continuing_crash(self):
        self.run_check(33)
        self.run_check(33)
        self.assertNotIn('🛑', self.messages())
        self.assertIn('FAILS=0', self.state.read_text())
        self.assertIn('PREV_RESTARTS=33', self.state.read_text())

    def test_continuing_restarts_alert_and_stability_recovers(self):
        self.run_check(4)
        self.run_check(8)
        self.assertEqual(self.messages().count('🛑'), 1)
        self.run_check(12, now=10030)
        self.assertEqual(self.messages().count('🛑'), 1)
        self.run_check(12, now=10060)
        self.assertIn('✅', self.messages())
        self.assertIn('FAILS=0', self.state.read_text())

    def test_inactive_service_still_alerts(self):
        self.run_check(0, inactive=3)
        self.run_check(0, inactive=3)
        self.assertIn('служба nutrition-bot не работает', self.messages())

    def test_counter_reset_does_not_alert(self):
        self.state.write_text('FAILS=0\nLAST_ALERT=0\nPREV_RESTARTS=33\n')
        self.run_check(0)
        self.run_check(0)
        self.assertNotIn('🛑', self.messages())


if __name__ == '__main__':
    unittest.main()
