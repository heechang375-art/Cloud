import requests
import json
import datetime
from dotenv import load_dotenv # type: ignore
import os

load_dotenv()
os.path.exists(".env")
tenantId = os.getenv("NHNCloud_tenant_id")
NHNClouduserId = os.getenv("NHNCloud_ID")  # NHNCloud_ID
NHNClouduserPass = os.getenv("NHNCloudpass")  # NHNCloudpass
date = datetime.datetime.now()
url = "https://api-identity-infrastructure.nhncloudservice.com"
url2 = "https://kr1-api-instance-infrastructure.nhncloudservice.com"
url3 = "https://kr1-api-image-infrastructure.nhncloudservice.com"
url4 = "https://kr1-api-network-infrastructure.nhncloudservice.com"
uri = "/v2.0/tokens"
uri2 = f"/v2/{tenantId}/servers"
uri3 = f"/v2/{tenantId}/flavors"
uri4 = f"/v2/images"
uri5 = "/v2.0/security-groups"
uri6 = f"/v2/{tenantId}/os-availability-zone"
uri7 = "/v2.0/vpcs"
body = {
    "auth": {
        "tenantId": tenantId,
        "passwordCredentials": {
            "username": NHNClouduserId,
            "password": NHNClouduserPass
        }
    }
}
response = requests.post(url+uri,json=body)
token_id = "gAAAAABpgtqsyssfUbJWP67xvfXP1s-BZzWC_YzuqehiEQ8aKWP_ibqW-mQxh7TenArXg6BZEhXdf9pIbnHLJ_rGeTBBYfCMbFHCL8uAvc54Y0RjVIOIBQ_vVq7ZK6BBwSiipdsub7f4ix0Smt6hZAhzVwmzQdcKRzEf40kL9BIya974TON_FKU"
#print(response.json())
header = {
    "X-Auth-Token": token_id
}
instanse_body = {
  "server": {
    "name": "api-instance-01",
    "flavorRef": "6ab714c1-26c6-4b39-ba37-53a8f6c83f86",
    "networks": [{
      "subnet": "c4f6373c-4292-4307-a6c7-f38e73677152"
    }],
    "availability_zone": "kr-pub-a",
    "key_name": "vm1-key",
    "max_count": 1,
    "min_count": 1,
    "block_device_mapping_v2": [{
      "source_type": "image",
      "uuid": "7342b6e2-74d6-4d2c-a65c-90242d1ee218",
      "boot_index": 0,
      "volume_size": 50,
      "destination_type": "volume",
      "delete_on_termination": True
    }],
    "security_groups": [{
      "id": "c33a6a83-f3f7-450e-bc6b-8c687a44514f"
    }] 
  }
}
flavors = requests.get(url2+uri3,headers=header)
instanse = requests.get(url2+uri2,headers=header)
image = requests.get(url3+uri4,headers=header)
vpc = requests.get(url4+uri7,headers=header)
#print(requests.post(url2+uri2,headers=header,json=instanse_body))
print(image.json()["images"][0]["id"])
print(flavors.json()["flavors"][9]["id"])
network = requests.get(url4+uri5,headers=header)
#print(network.json()["security_groups"][2]["name"])
availability_zone = requests.get(url2+uri6,headers=header)
#print(availability_zone.json())
#response = requests.post(url2+uri2, headers=header, json=instanse_body)
#print(response.status_code)
#print(response.text)
vpc_body = {
   "vpc": {
      "name": "api-vpc",
      "tenant_id": tenantId,
      "state": "available",
      "create_time": str(date),
      "cidrv4": "10.10.0.0/16",
      "shared": False
   }
}
response = requests.post(url4+uri7, headers=header, json=vpc_body)