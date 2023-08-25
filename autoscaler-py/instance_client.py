import requests
from queue import Queue
import time

class InstanceClient:
    def __init__(self, instance_id, instance_addr, mtoken):
        self.instance_id = instance_id
        self.instance_addr = instance_addr
        self.mtoken = mtoken
        self.token_queue = Queue()
        self.monitor_token_queue()

    def monitor_token_queue(self):
        if self.token_queue.qsize() < 100:
            new_tokens = self.get_tokens()
            for t in new_tokens:
                self.token_queue.put(t)

    def get_tokens(self):
        print(f"[instance_client] getting tokens for instance: {self.instance_id}")
        URI = f'http://{self.instance_addr}/tokens'
        request_dict = {"mtoken" : self.mtoken}
        t1 = time.time()
        response = requests.get(URI, json=request_dict)
        t2 = time.time()
        print(f"[instance_client] got tokens in {t2 - t1} and status code is {response.status_code}")
        if response.status_code == 200:
            return response.json()["tokens"]

