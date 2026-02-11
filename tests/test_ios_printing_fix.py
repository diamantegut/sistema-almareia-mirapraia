import unittest
from unittest.mock import MagicMock, patch
import threading
import time
from datetime import datetime
import sys
import os

# Import the service (assuming it's in the root or accessible path)
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from printing_service import send_to_printer

class TestIOSPrintingFix(unittest.TestCase):
    
    def setUp(self):
        # Reset any global state if necessary
        pass

    @patch('printing_service.socket.socket')
    def test_concurrent_printing_requests(self, mock_socket):
        """
        Simulate multiple iOS devices sending print requests simultaneously.
        Verify that they are processed sequentially due to the lock.
        """
        mock_conn = MagicMock()
        mock_socket.return_value = mock_conn
        mock_conn.__enter__.return_value = mock_conn
        
        # Determine success on the first try to avoid retries complicating the test
        # or simulate a slight delay to test locking
        def side_effect_connect(addr):
            time.sleep(0.1) # Simulate network delay
            return None
            
        mock_conn.connect.side_effect = side_effect_connect
        
        threads = []
        errors = []
        
        def print_task(order_id):
            try:
                # Mock data for printing
                ip = '192.168.1.100'
                port = 9100
                content = f"Order {order_id}\nItem 1..."
                
                success, error = send_to_printer(ip, port, content.encode('utf-8'))
                if not success:
                    errors.append(f"Failed to print order {order_id}: {error}")
            except Exception as e:
                errors.append(f"Exception in order {order_id}: {str(e)}")

        # Launch 5 concurrent threads
        for i in range(5):
            t = threading.Thread(target=print_task, args=(i,))
            threads.append(t)
            t.start()
            
        for t in threads:
            t.join()
            
        self.assertEqual(len(errors), 0, f"Errors occurred: {errors}")
        
        # Verify that connect was called 5 times
        self.assertEqual(mock_conn.connect.call_count, 5)

    @patch('printing_service.socket.socket')
    def test_retry_logic_with_backoff(self, mock_socket):
        """
        Simulate a network failure that succeeds after retries.
        """
        mock_conn = MagicMock()
        mock_socket.return_value = mock_conn
        mock_conn.__enter__.return_value = mock_conn
        
        # Fail twice, then succeed
        # connect raises OSError on failure
        mock_conn.connect.side_effect = [OSError("Connection refused"), OSError("Timeout"), None]
        
        ip = '192.168.1.100'
        port = 9100
        content = b"Retry Test Order"
        
        start_time = time.time()
        success, error = send_to_printer(ip, port, content)
        end_time = time.time()
        
        self.assertTrue(success, f"Printing should succeed eventually. Error: {error}")
        self.assertEqual(mock_conn.connect.call_count, 3, "Should have retried twice (3 attempts total)")
        
        # Verify backoff happened (approx 0.5s + 1.0s waits = 1.5s)
        self.assertGreater(end_time - start_time, 1.0, "Should have waited for backoff")

    @patch('printing_service.socket.socket')
    def test_max_retries_exceeded(self, mock_socket):
        """
        Simulate persistent failure where max retries are exceeded.
        """
        mock_conn = MagicMock()
        mock_socket.return_value = mock_conn
        mock_conn.__enter__.return_value = mock_conn
        
        # Always fail
        mock_conn.connect.side_effect = OSError("Host down")
        
        ip = '192.168.1.100'
        port = 9100
        content = b"Failed Order"
        
        success, error = send_to_printer(ip, port, content)
        
        self.assertFalse(success, "Printing should fail after max retries")
        self.assertEqual(mock_conn.connect.call_count, 3, "Should have tried exactly 3 times")

if __name__ == '__main__':
    unittest.main()
