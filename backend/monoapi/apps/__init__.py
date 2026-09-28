from fastapi import FastAPI

from monoapi.apps.fastapi import api

app: FastAPI = api

all = [
    "app",
]