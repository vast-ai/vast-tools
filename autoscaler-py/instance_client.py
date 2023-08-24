import requests
from queue import Queue

class InstanceClient:
    def __init__(self, instance_addr, mtoken):
        self.instance_addr = instance_addr
        self.mtoken = mtoken
        self.token_queue = Queue()
        self.monitor_token_queue()
        print(self.token_queue.qsize())

    def monitor_token_queue(self):
        if self.token_queue.qsize() < 10:
            new_tokens = self.get_tokens()
            for t in new_tokens:
                self.token_queue.put(t)

    def get_tokens(self):
        URI = f'http://{self.instance_addr}/tokens'
        request_dict = {"mtoken" : self.mtoken}
        response = requests.get(URI, json=request_dict)
        print(response)
        if response.status_code == 200:
            return response.json()["tokens"]

