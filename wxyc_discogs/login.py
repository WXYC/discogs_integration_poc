import requests
import os
from dotenv import load_dotenv

def authenticate(username: str, password: str) -> str:
    # Load environment variables
    AWS_REGION = os.getenv("AWS_REGION")
    CLIENT_ID = os.getenv("AWS_CLIENT_ID")

    LOGIN_URL = f"https://cognito-idp.{AWS_REGION}.amazonaws.com/"

    login_payload = {
        "AuthFlow": "USER_PASSWORD_AUTH",
        "AuthParameters": {
            "USERNAME": username,
            "PASSWORD": password
        },
        "ClientId": CLIENT_ID
    }

    login_headers = {
        'X-Amz-Target': 'AWSCognitoIdentityProviderService.InitiateAuth',
        'Content-Type': 'application/x-amz-json-1.1',
    }

    response = requests.post(LOGIN_URL, headers=login_headers, json=login_payload)
    response_data = response.json()

    if 'ChallengeName' in response_data and response_data['ChallengeName'] == "NEW_PASSWORD_REQUIRED":
        print("New password required.")
        return {
            "authenticating": False,
            "isAuthenticated": False,
            "user": {
                "username": username,
                "resetPassword": True,
                "session": response_data['Session']
            }
        }

    access_token = str(response_data['AuthenticationResult'].get('AccessToken'))

    return access_token


if __name__ == "__main__":
    load_dotenv()

    username = input("Enter your username: ")
    password = input("Enter your password: ")

    print(authenticate(username, password))

