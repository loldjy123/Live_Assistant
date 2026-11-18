import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import launcher


class LauncherTests(unittest.TestCase):
    def test_reuses_running_project_server(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(launcher,'ROOT',Path(directory)), \
                 patch.object(launcher,'read_health',return_value={'ready':True,'websocket_path':'/ws'}), \
                 patch.object(launcher.subprocess,'Popen') as start:
                self.assertFalse(launcher.start_server())
                start.assert_not_called()

    def test_old_server_is_not_silently_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(launcher, 'ROOT', Path(directory)), \
                 patch.object(launcher, 'read_health', return_value={'ready': True}), \
                 patch.object(launcher.subprocess, 'Popen') as start:
                with self.assertRaisesRegex(RuntimeError, 'older server'):
                    launcher.start_server()
                start.assert_not_called()

    def test_waits_for_both_servers_before_reporting_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'.venv'/'bin').mkdir(parents=True)
            (root/'.venv'/'bin'/'python').touch()
            process=Mock(pid=98765)
            process.poll.return_value=None
            with patch.object(launcher,'ROOT',root), \
                 patch.object(launcher,'LOG_PATH',root/'server.log'), \
                 patch.object(launcher,'read_health',side_effect=[None,{'ready':True,'pid':98765}]), \
                 patch.object(launcher.subprocess,'Popen',return_value=process) as start:
                self.assertTrue(launcher.start_server())
                self.assertEqual(start.call_args.args[0][-1],str(root/'main.py'))
                self.assertTrue(start.call_args.kwargs['start_new_session'])
                process.terminate.assert_not_called()

    def test_rejects_another_project_health_response(self):
        payload={'app':launcher.APP_ID,'project':'another-project','ready':True,'pid':1234}
        opener=Mock()
        opener.open.return_value=io.BytesIO(json.dumps(payload).encode())
        with patch.object(launcher.urllib.request,'build_opener',return_value=opener):
            self.assertIsNone(launcher.read_health())

    def test_no_browser_option_does_not_open_browser(self):
        with patch.object(launcher.sys,'argv',['launcher.py','--no-browser']), \
             patch.object(launcher,'start_server',return_value=False), \
             patch.object(launcher.webbrowser,'open') as open_browser:
            launcher.main()
            open_browser.assert_not_called()


if __name__=='__main__': unittest.main()
