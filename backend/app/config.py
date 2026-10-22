import os

from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.environ["SECRET_KEY"]
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

# The origins the API answers for. Used twice: the CORS middleware hands out
# these origins, and the origin check in session_cookie refuses a request that
# a page on any other site made us. Both read the same list.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]

# When the refresh token only ever travels in an httpOnly cookie, no client
# can read it and no script can steal it. The switch is a setting rather than
# a code change so a rollout can be reversed without a deploy; the code
# default was turned on in step 3 of the M26 rollout, once every client had
# moved over. REFRESH_COOKIE_ONLY=false puts the body token back for one
# deploy if a client cannot be updated.
REFRESH_COOKIE_ONLY = os.getenv("REFRESH_COOKIE_ONLY", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
