"""Unit tests validating production Gunicorn configuration parameters and lifecycle hooks."""

import unittest
from unittest.mock import MagicMock

import gunicorn_conf


class TestGunicornConfiguration(unittest.TestCase):
    """Verifies that Gunicorn server settings match production specifications."""

    def test_default_configuration_attributes(self):
        self.assertIn("8000", gunicorn_conf.bind)
        self.assertEqual(gunicorn_conf.worker_class, "uvicorn.workers.UvicornWorker")
        self.assertGreaterEqual(gunicorn_conf.workers, 2)
        self.assertEqual(gunicorn_conf.timeout, 120)
        self.assertEqual(gunicorn_conf.graceful_timeout, 30)
        self.assertEqual(gunicorn_conf.keepalive, 5)
        self.assertEqual(gunicorn_conf.max_requests, 5000)
        self.assertEqual(gunicorn_conf.accesslog, "-")
        self.assertEqual(gunicorn_conf.errorlog, "-")
        self.assertIn("status", gunicorn_conf.access_log_format)
        self.assertIn("duration_ms", gunicorn_conf.access_log_format)

    def test_lifecycle_hooks_execution(self):
        mock_server = MagicMock()
        mock_worker = MagicMock()
        mock_worker.pid = 12345

        # on_starting hook
        gunicorn_conf.on_starting(mock_server)
        mock_server.log.info.assert_called()

        # post_fork hook
        gunicorn_conf.post_fork(mock_server, mock_worker)
        mock_server.log.info.assert_called()

        # worker_int hook
        gunicorn_conf.worker_int(mock_worker)
        mock_worker.log.info.assert_called()

        # worker_abort hook
        gunicorn_conf.worker_abort(mock_worker)
        mock_worker.log.error.assert_called()

        # on_exit hook
        gunicorn_conf.on_exit(mock_server)
        mock_server.log.info.assert_called()


if __name__ == "__main__":
    unittest.main()
