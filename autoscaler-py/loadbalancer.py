from collections import defaultdict
from threading import Thread, Lock, Event
from concurrent.futures import ThreadPoolExecutor, wait
from queue import PriorityQueue
import time

from autoscaler_client import Client
from instance_client import InstanceClient
from autoscaler import get_model_address

TIME_INTERVAL_SECONDS = 5
FULL_LOAD_THRESHOLD = 2.5
DEFAULT_TPS = 35.0
MAX_CONCURRENCY = 100

def get_address_auth(instance): #used to be 5000, might change soon
	addr = instance["public_ipaddr"] + ":" + instance["ports"]["3000/tcp"][0]["HostPort"]
	addr = addr.replace('\n', '')
	return addr

class LoadBalancer:
	def __init__(self, autoscaler_args):
		self.client = Client()

		self.old_hot_ids = [] #need a better system to delay busy classification of new instances
		self.hot_queue = PriorityQueue()
		self.num_hot = 0
		self.queue_duration = defaultdict(int)
		self.instance_clients = {}

		self.lock = Lock()
		self.exit_event = Event()

		self.streaming = autoscaler_args["streaming"]

		self.client.setup_autoscaler(autoscaler_args=autoscaler_args)
		self.update_hot_queue()
		self.bt = Thread(target=self.tick_background, args=(self.exit_event, ))
		self.bt.start()

	def update_hot_queue(self):
		hot_instances = self.client.get_hot_instances()
		self.lock.acquire()
		queue_duration = self.queue_duration
		self.lock.release()

		hot_queue = PriorityQueue()
		hot_ids = []
		num_hot = 0
		for hot_instance in hot_instances:
			id = hot_instance["id"]
			if id in self.old_hot_ids:
				num_hot += 1
			else:
				self.instance_clients[id] = InstanceClient(hot_instance["id"], get_address_auth(hot_instance), hot_instance["mtoken"])

			hot_queue.put((queue_duration[id], id, hot_instance))
			hot_ids.append(id)

		self.lock.acquire()
		self.hot_queue = hot_queue
		self.old_hot_ids = hot_ids
		self.num_hot = num_hot
		self.lock.release()

	#needs to keep track of how many tokens it has per GPU
	def monitor_instance_clients(self):
		with ThreadPoolExecutor(MAX_CONCURRENCY) as e:
			futures = [e.submit(c.monitor_token_queue) for c in self.instance_clients.values()]
			wait(futures) #not sure if we need to wait here

	def tick_duration(self):
		self.lock.acquire()

		tot_duration = 0
		num_hot = 0

		for hot_id in list(self.old_hot_ids):
			prev_queue_duration = self.queue_duration[hot_id]
			curr_queue_duration = max(0, prev_queue_duration - TIME_INTERVAL_SECONDS)
			self.queue_duration[hot_id] = curr_queue_duration
			tot_duration += curr_queue_duration

		num_soon_hot = self.hot_queue.qsize()
		avg_duration = tot_duration / num_soon_hot if num_soon_hot != 0 else 0
		busy_level = avg_duration / FULL_LOAD_THRESHOLD
		num_busy = int(busy_level * num_hot)

		self.client.report_hot_busy(num_hot=self.num_hot, num_busy=num_busy)
		self.lock.release()

	def tick_background(self, event):
		while not event.is_set():
			self.update_hot_queue()
			self.tick_duration()
			self.monitor_instance_clients()
			time.sleep(TIME_INTERVAL_SECONDS)

	def get_next_addr(self, num_tokens):
		addr = None
		token = None
		if not(self.hot_queue.empty()):
			(work_time, _, hot_server) = self.hot_queue.get()
			addr = get_model_address(hot_server, self.streaming)
			token_queue = self.instance_clients[hot_server["id"]].token_queue
			token = token_queue.get()
			if ("tokens/s" in hot_server.keys()) and (hot_server["tokens/s"] is not None):
				tps = hot_server["tokens/s"]
			else:
				tps = DEFAULT_TPS
			self.queue_duration[hot_server["id"]] += ((1 / tps) * num_tokens)
			self.hot_queue.put((self.queue_duration[hot_server["id"]], hot_server["id"], hot_server))
		return addr, token

	def deconstruct(self, kill_servers=False):
		print("[loadbalancer] deconstructing")
		self.client.destroy_autoscaler()
		self.exit_event.set()
		self.bt.join()

