"""Bounded readiness probe for the local Compose stack."""
import os
import time
import psycopg
import redis
from confluent_kafka.admin import AdminClient


def wait():
    deadline = time.monotonic()+60
    while True:
        try:
            with psycopg.connect(os.environ['VOICE_TEST_POSTGRES'], connect_timeout=2):pass
            redis.Redis.from_url(os.environ['VOICE_TEST_REDIS'], socket_connect_timeout=2).ping()
            AdminClient({'bootstrap.servers':os.environ['VOICE_TEST_KAFKA']}).list_topics(timeout=2)
            return
        except Exception:
            if time.monotonic()>=deadline:raise
            time.sleep(1)


if __name__ == '__main__':wait()
