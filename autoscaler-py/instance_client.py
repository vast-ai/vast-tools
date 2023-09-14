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
        print(f"[instance_client] monitoring token queue with size : {self.token_queue.qsize()}")
        if self.token_queue.qsize() < 100:
            new_tokens = self.get_tokens()
            if new_tokens:
                for t in new_tokens:
                    self.token_queue.put(t)
                print(f"[instance_client] new tokens returned, now token queue with size : {self.token_queue.qsize()}")
            else:
                print(f"[instance_client] error communicating with auth server")

    def get_tokens(self):
        print(f"[instance_client] getting tokens for instance: {self.instance_id}, using mtoken: {self.mtoken}")
        URI = f'http://{self.instance_addr}/tokens'
        request_dict = {"mtoken" : self.mtoken}
        response = requests.get(URI, json=request_dict)
        print(response)

        if response.status_code == 200:
            return response.json()["tokens"]

