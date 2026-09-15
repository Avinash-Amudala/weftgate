import unittest

from orders import create_order


class OrderTests(unittest.TestCase):
    def test_duplicate_is_not_created_twice(self):
        seen = set()
        self.assertTrue(create_order("order-1", seen))
        self.assertFalse(create_order("order-1", seen))
        self.assertTrue(create_order("order-2", seen))


if __name__ == "__main__":
    unittest.main()
