import unittest
from unittest.mock import patch
from datetime import datetime

# Assuming the classes and functions to be tested are imported:
# from your_module import should_force_change, DeviceState
from auto import get_force_change, DeviceState

class TestShouldForceChange(unittest.TestCase):

    @patch('auto.read_last_n_rows')
    def test_ac_off_temp_falling(self, mock_read_last_n_rows):
        # Simulating last 5 rows where AC is off, but temp is falling
        mock_read_last_n_rows.return_value = [
            ['time1', 'False', '25.0'],  # AC off, temperature at 25°C
            ['time2', 'False', '24.5'],  # Temp is falling
            ['time3', 'False', '24.0'],
            ['time4', 'False', '23.5'],
            ['time5', 'False', '23.0'],
        ]

        # AC is currently off
        current_state = DeviceState.OFF
        current_temp = 23.0

        # Should force a change because temp is falling while AC is off
        result = get_force_change(current_state, current_temp)
        self.assertEqual(result, DeviceState.OFF)


    @patch('auto.read_last_n_rows')
    def test_ac_on_temp_rising(self, mock_read_last_n_rows):
        # Simulating last 5 rows where AC is on, but temp is rising
        mock_read_last_n_rows.return_value = [
            ['time1', 'True', '23.0'],   # AC on, temperature at 23°C
            ['time2', 'True', '23.5'],   # Temp is rising
            ['time3', 'True', '24.0'],
            ['time4', 'True', '24.5'],
            ['time5', 'True', '25.0'],
        ]

        # AC is currently on
        current_state = DeviceState.ON
        current_temp = 25.0

        # Should force a change because temp is rising while AC is on
        result = get_force_change(current_state, current_temp)
        self.assertEqual(result, DeviceState.ON)

    @patch('auto.read_last_n_rows')
    def test_no_force_change_needed(self, mock_read_last_n_rows):
        # Simulating last 5 rows where AC is off, and temp is stable or rising as expected
        mock_read_last_n_rows.return_value = [
            ['time1', 'False', '25.0'],  # AC off, temperature at 25°C
            ['time2', 'False', '25.5'],  # Temp is rising
            ['time3', 'False', '26.0'],
            ['time4', 'False', '26.5'],
            ['time5', 'False', '27.0'],
        ]

        # AC is currently off
        current_state = DeviceState.OFF
        current_temp = 27.0

        # No need to force a change because the temperature is rising as expected
        result = get_force_change(current_state, current_temp)
        self.assertIsNone(result)

    @patch('auto.read_last_n_rows')
    def test_not_enough_data(self, mock_read_last_n_rows):
        # Simulating less than 5 rows of data
        mock_read_last_n_rows.return_value = [
            ['time1', 'True', '23.0'],   # AC on, temperature at 23°C
            ['time2', 'True', '23.5'],   # Temp is rising
        ]

        # AC is currently on
        current_state = DeviceState.ON
        current_temp = 23.5

        # Not enough data, should return None
        result = get_force_change(current_state, current_temp)
        self.assertIsNone(result)

    @patch('auto.read_last_n_rows')
    def test_cooldown_prevents_consecutive_force_changes(self, mock_read_last_n_rows):
        # Simulating a temperature trend where the AC is off, but the temperature is falling
        # A force change is expected, but the cooldown should prevent consecutive changes

        # First 5 data points: AC is off, temperature is falling
        mock_read_last_n_rows.return_value = [
            ['time1', 'False', '25.0'],  # AC off, temperature at 25°C
            ['time2', 'False', '24.5'],  # Temperature falling
            ['time3', 'False', '24.0'],
            ['time4', 'False', '23.5'],
            ['time5', 'False', '23.0'],
        ]

        # AC is currently off, temperature is falling
        current_state = DeviceState.OFF
        current_temp = 23.0
        last_force_time = None  # No force change has happened yet

        # First call should trigger a force change
        result = get_force_change(current_state, current_temp, last_force_time)
        self.assertEqual(result, DeviceState.OFF, "First force change should be triggered")

        # Simulate that a force change happened now (update last_force_time)
        last_force_time = datetime.now()

        # Now, keep the same falling temperature trend but expect no force change due to cooldown
        mock_read_last_n_rows.return_value = [
            ['time1', 'False', '23.0'],  # Temperature still falling
            ['time2', 'False', '22.5'],
            ['time3', 'False', '22.0'],
            ['time4', 'False', '21.5'],
            ['time5', 'False', '21.0'],
        ]

        # Second call should not trigger a force change due to cooldown
        result = get_force_change(current_state, 21.0, last_force_time)
        self.assertIsNone(result, "No force change should be triggered during cooldown")



if __name__ == '__main__':
    unittest.main()
