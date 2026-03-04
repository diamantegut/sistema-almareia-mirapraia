
import requests

def smoke_check(path):
    url = f'http://127.0.0.1:5001{path}'
    print(f"Testing {url}...")
    try:
        response = requests.get(url)
        print(f"Status Code: {response.status_code}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    smoke_check('/')
    smoke_check('/login')
    smoke_check('/api/reception/return_to_restaurant')
