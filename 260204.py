import requests
url = "https://jsonplaceholder.typicode.com/posts"
data = {
    "title": "공부중",
    "body" : "파이썬 열심히 공부중",
    "userId": 10
    }
response = requests.post(url,json=data)
print("응답 코드: ", response.status_code)
print("응답 본몬: ", response.text)
print("응답 본몬: ", response.__bool__)