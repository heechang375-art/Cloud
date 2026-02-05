import requests
tenantId = "c3ef7c629cad4448bd1f84bd32b21dee"
url = "https://kr1-api-instance-infrastructure.nhncloudservice.com"
url2 ="https://api-identity-infrastructure.nhncloudservice.com"
uri = f"/v2/{tenantId}/os-keypairs"
uri2 = "/v2.0/tokens"
body = {
    "auth": {
        "tenantId": tenantId,
        "passwordCredentials": {
            "username": "test06",
            "password": "test0606"
        }
    }
}
response = requests.post(url2+uri2,json=body)
token_id = response.json()["access"]["token"]["id"]
header = {"X-Auth-Token": token_id}
response = requests.get(url+uri,headers=header)
# for i in range(5):
#     a = i+1
#     payload = {
#         "keypair": {
#             "name": f"keypair-{a}",
#         }
#     }
#     response = requests.post(url+uri,headers=header,json=payload)

for i in range(5):
    a = i+1
    response = requests.delete(url+uri+f"/keypair-{a}",headers=header)
