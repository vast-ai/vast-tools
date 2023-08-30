from collections import defaultdict
from threading import Thread, Lock, Event
from concurrent.futures import ThreadPoolExecutor, wait
from queue import PriorityQueue
import time

from autoscaler_client import Client
from instance_client import InstanceClient

TIME_INTERVAL_SECONDS = 5
FULL_LOAD_THRESHOLD = 2.5
DEFAULT_TPS = 35.0
MAX_CONCURRENCY = 100

class LoadBalancer:
	def __init__(self, cold_set_size=0, manage=True):
		self.client = Client()

		self.old_ready_ids = [] #need a better system to delay busy classification of new instances
		self.ready_queue = PriorityQueue()
		self.num_ready = 0
		self.queue_duration = defaultdict(int)
		self.instance_clients = {}

		self.lock = Lock()
		self.exit_event = Event()

		self.client.setup_autoscaler()
		self.update_ready_queue()
		self.bt = Thread(target=self.tick_background, args=(self.exit_event, ))
		self.bt.start()

	def update_ready_queue(self):
		ready_instances = self.client.get_ready_instances()
		self.lock.acquire()
		queue_duration = self.queue_duration
		self.lock.release()

		ready_queue = PriorityQueue()
		ready_ids = []
		num_ready = 0
		for ready_instance in ready_instances:
			id = ready_instance["id"]
			if id in self.old_ready_ids:
				num_ready += 1
			else:
				self.instance_clients[id] = InstanceClient(ready_instance["id"], self.get_address(ready_instance), ready_instance["mtoken"])

			ready_queue.put((queue_duration[id], id, ready_instance))
			ready_ids.append(id)

		self.lock.acquire()
		self.ready_queue = ready_queue
		self.old_ready_ids = ready_ids
		self.num_ready = num_ready
		self.lock.release()

	#needs to keep track of how many tokens it has per GPU
	def monitor_instance_clients(self):
		with ThreadPoolExecutor(MAX_CONCURRENCY) as e:
			futures = [e.submit(c.monitor_token_queue) for c in self.instance_clients.values()]
			wait(futures) #not sure if we need to wait here

	def tick_duration(self):
		self.lock.acquire()

		tot_duration = 0
		num_ready = 0

		for ready_id in list(self.old_ready_ids):
			prev_queue_duration = self.queue_duration[ready_id]
			curr_queue_duration = max(0, prev_queue_duration - TIME_INTERVAL_SECONDS)
			self.queue_duration[ready_id] = curr_queue_duration
			tot_duration += curr_queue_duration

		num_soon_ready = self.ready_queue.qsize()
		avg_duration = tot_duration / num_soon_ready if num_soon_ready != 0 else 0
		busy_level = avg_duration / FULL_LOAD_THRESHOLD
		num_busy = int(busy_level * num_ready)

		print(f"[loadbalancer] ticking duration with {self.ready_queue.qsize()} ready and {avg_duration} avg duration")
		self.client.report_hot_busy(num_hot=self.num_ready, num_busy=num_busy)
		self.lock.release()

	def tick_background(self, event):
		prev_time = time.time()
		while not event.is_set():
			curr_time = time.time()
			print(f"[loadbalancer] ticking with interval: {curr_time - prev_time}")
			prev_time = curr_time
			# t1 = time.time()
			self.update_ready_queue()
			# t2 = time.time()
			# print(f"[loadbalancer] updated ready queue in: {t2 - t1}")
			# t1 = time.time()
			self.tick_duration()
			# t2 = time.time()
			# print(f"[loadbalancer] ticked duration in: {t2 - t1}")
			# t1 = time.time()
			self.monitor_instance_clients()
			# t2 = time.time()
			# print(f"[loadbalancer] monitored instance clients in: {t2 - t1}")
			time.sleep(TIME_INTERVAL_SECONDS)

	def get_address(self, instance):
		addr = instance["public_ipaddr"] + ":" + instance["ports"]["5000/tcp"][0]["HostPort"]
		addr = addr.replace('\n', '')
		return addr

	def get_next_addr(self, num_tokens):
		addr = None
		if not(self.ready_queue.empty()):
			(work_time, _, ready_server) = self.ready_queue.get()
			addr = self.get_address(ready_server)
			token_queue = self.instance_clients[ready_server["id"]].token_queue
			token = token_queue.get()
			# print(f"[loadbalancer] got token for instance id: {ready_server['id']}, and token qsize: {token_queue.qsize()}")
			tps = DEFAULT_TPS
			self.queue_duration[ready_server["id"]] += ((1 / tps) * num_tokens)
			self.ready_queue.put((self.queue_duration[ready_server["id"]], ready_server["id"], ready_server))
		# print(f"[loadbalancer] next addr is: {addr} on instance: {id}")
		return addr, token

	def deconstruct(self, kill_servers=False):
		print("[loadbalancer] deconstructing")
		self.client.destroy_autoscaler()
		self.exit_event.set()
		self.bt.join()

