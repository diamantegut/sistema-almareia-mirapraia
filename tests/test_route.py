
import requests

def test(path):
    url = f'http://127.0.0.1:5001{path}'
    print(f"Testing {url}...")
    try:
        response = requests.get(url)
        print(f"Status Code: {response.status_code}")
    except Exception as e:
        print(f"Error: {e}")

test('/')
test('/login')
test('/api/reception/return_to_restaurant') # This is POST, but GET should return 405 if route exists
