from dotenv import load_dotenv
from os import getenv, path
from .base import * # noqa
from .base import BASE_DIR

local_env_file = path.join(BASE_DIR, ".envs", ".env.local")

if path.isfile(local_env_file):
    load_dotenv(local_env_file)

SECRET_KEY = getenv('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = getenv('DEBUG')

SITE_NAME = getenv('SITE_NAME')

ALLOWED_HOSTS = ['localhost', '127.0.0.1', '0.0.0.0']

ADMIN_URL = getenv('ADMIN_URL')

EMAIL_BACKEND = 'djcelery_email.backends.CeleryEmailBackend' #'django.core.mail.backends.console.EmailBackend'
EMAIL_HOST = getenv('EMAIL_HOST')
EMAIL_PORT = getenv('EMAIL_PORT')
DEFAULT_EMAIL_FROM = getenv('DEFAULT_EMAIL_FROM')
DOMAIN = getenv('DOMAIN')

MAX_UPLOAD_SIZE = 1 * 1024 * 1024

CSRF_TRUSTED_ORIGINS = ["http://localhost:8080"]
LOCKOUT_DURATION = timedelta(minutes=1)
LOGIN_ATTEMPS = 3
OTP_EXPIRATION = timedelta(minutes=1)
