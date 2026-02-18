import requests


def send_push(message: str, user_key: str, app_token: str) -> None:
    if not user_key or not app_token:
        print("PUSH_USER_KEY eller PUSH_APP_TOKEN mangler – springer push over.")
        return

    try:
        resp = requests.post(
            "https://api.pushover.net/1/messages.json",
            data={
                "token": app_token,
                "user": user_key,
                "message": message,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            print(f"Pushover fejl: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"Pushover exception: {e}")
