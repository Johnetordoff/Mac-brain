import unittest

from macbrain.metrics import on_ac_power, parse_pmset_battery


class MetricTests(unittest.TestCase):
    def test_parse_ac_battery(self):
        raw = "Now drawing from 'AC Power'\n -InternalBattery-0\t82%; charging; 1:20 remaining present: true"
        value = parse_pmset_battery(raw)
        self.assertEqual(value["source"], "AC Power")
        self.assertEqual(value["percent"], 82)
        self.assertEqual(value["status"], "charging")
        self.assertTrue(on_ac_power(value))

    def test_parse_battery_power(self):
        raw = "Now drawing from 'Battery Power'\n -InternalBattery-0\t31%; discharging; 0:50 remaining present: true"
        value = parse_pmset_battery(raw)
        self.assertEqual(value["source"], "Battery Power")
        self.assertEqual(value["status"], "discharging")
        self.assertFalse(on_ac_power(value))


if __name__ == "__main__":
    unittest.main()
