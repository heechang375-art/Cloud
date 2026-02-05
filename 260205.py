# fruits = ['banana', 'apple', 'grape']
# for i in fruits:
#     print(i)

# dan = int(input("출력할 단을 입력하세요: "))
# for i in range(1,10):
#     print(dan*i)
    
# score = [10,20,30,40,50]
# total = 0
# for i in score:
#     total += i 
# print("총점: ", total)

# attempts = 0
# while attempts < 3:
#     password = input("비밀번호를 입력하세요: ")
#     if password == "1234":
#         print("로그인 성공")
#         break
#     else:
#         attempts += 1
#         if attempts == 3:
#             print("로그인 실패. 프로그램을 종료합니다.")
#         else:
#             print(f"비밀번호가 틀렸습니다. 남은 시도 횟수: {3 - attempts}")

# while i < 5:
#     i += 1
#     if i == 4:
#         continue
#     print(i)
    
# users = [
#     {'name': '김철수', 'age': 25, 'city': '서울'},
#     {'name': '이영희', 'age': 30, 'city': '부산'},
#     {'name': '박민수', 'age': 28, 'city': '서울'}
# ]

# for user in users:
#     if user['city'] == '서울':
#         print(user['name'])

# for i in range(1,4):
#     for name in users:
#         print(i,name)

# def user(name, city , age = 30):
#     print(f"안녕하세요 저는 {name}이고, 나이는 {age}살이며, {city}에 살고 있습니다.")

# user("김철수","서울")
# user("김철수","서울",25)
# def check_score(score):
#     if score >= 90:
#         return "A"
#     elif score >= 80:
#         return "B"
#     else:
#         return "C"
# print(check_score(90))
# def divide(a,b):
#     if b == 0:
#         print("0으로 나눌 수 없습니다.")
#         return None
#     return a / b

# number1 = divide(2,2)
# number2 = divide(2,0)
import requests

def request(baseUrl,uri,METHOD, token=None,header=None,body=None):
    url = f"{baseUrl}{uri}"
    header ={
        "x-auth-token" : token
    }
    return requests.request(METHOD,url,headers=header,json=body)

request("https://api-identity-infrastructure.nhncloudservice.com","/v2.0/tokens","POST:")