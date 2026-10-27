"""A losing official calibration candidate still uses its owner's close hook."""
import unittest
from unittest.mock import Mock, patch
from tools import calibrate


class CandidateCloseBridgeTests(unittest.TestCase):
    def test_dead_candidate_retains_earlier_results_and_closes_through_owner(self):
        engine = object()
        session = Mock()
        session.rate.side_effect = RuntimeError('engine exited during rate')
        close = Mock()
        report, rates = {}, {'earlier': [11.0, 12.0]}
        with patch.object(calibrate, 'Session', return_value=session):
            calibrate.measure_candidate(lambda _: engine, [], 'candidate', lambda _: None,
                                        report, rates, 'candidate', [], close_engine=close)
        self.assertEqual(rates, {'earlier': [11.0, 12.0]})
        self.assertIn('candidate', report['failed_starts'])
        close.assert_called_once_with(engine)

    def test_operator_cancel_propagates_after_owner_cleanup(self):
        engine = object()
        session = Mock()
        session.warm_up.side_effect = calibrate.CalibrationCancelled('cancelled')
        close = Mock()
        with patch.object(calibrate, 'Session', return_value=session):
            with self.assertRaises(calibrate.CalibrationCancelled):
                calibrate.measure_candidate(lambda _: engine, [], 'candidate', lambda _: None,
                                            {}, {}, 'candidate', [], close_engine=close)
        close.assert_called_once_with(engine)
