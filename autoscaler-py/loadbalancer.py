from collections import defaultdict
from threading import Thread, Lock, Event
import heapq
import time

from autoscaler import InstanceSet

TIME_INTERVAL_SECONDS = 5
FULL_LOAD_THRESHOLD = 2.5
DEFAULT_TPS = 35.0

class LoadBalancer:
	def __init__(self, cold_set_size=0, manage=True):
		self.instance_set = InstanceSet(cold_set_size, manage)

		self.old_ready_ids = []
		self.ready_queue = []
		self.queue_duration = defaultdict(int)

		self.lock = Lock()
		self.exit_event = Event()

		self.update_ready_queue()
		self.bt = Thread(target=self.tick_background, args=(self.exit_event, ))
		self.bt.start()

	def deconstruct(self, kill_servers=False):
		print("[loadbalancer] deconstructing")
		self.instance_set.deconstruct()
		if kill_servers:
			time.sleep(5)
			self.instance_set.destroy_all_instances()
		self.exit_event.set()
		self.bt.join()

	def update_ready_queue(self):
		self.instance_set.lock.acquire()
		ready_instances = self.instance_set.ready_instances
		self.instance_set.lock.release()

		self.lock.acquire()
		ready_queue = []
		ready_ids = []
		for ready_instance in ready_instances:
			heapq.heappush(ready_queue, (self.queue_duration[ready_instance["id"]], ready_instance["id"], ready_instance))
			ready_ids.append(ready_instance["id"])

		self.ready_queue = ready_queue
		self.old_ready_ids
		self.lock.release()
		# print("[loadbalancer] ready queue has len: {}".format(len(self.ready_queue)))

	def tick_duration(self):
		self.lock.acquire()
		tot_duration = 0
		num_ready = 0
		ready_ids = []

		for (_, _, instance) in list(self.ready_queue):
			ready_ids.append(instance["id"])
			prev_queue_duration = self.queue_duration[instance['id']]
			curr_queue_duration = max(0, prev_queue_duration - TIME_INTERVAL_SECONDS)
			self.queue_duration[instance['id']] = curr_queue_duration
			if instance["id"] in self.old_ready_ids:
				num_ready += 1
			tot_duration += curr_queue_duration
			# print("[loadbalancer] instance: {} has queue duration: {}".format(instance['id'], curr_queue_duration))

		num_soon_ready = len(self.ready_queue)
		avg_duration = tot_duration / num_soon_ready if num_soon_ready != 0 else 0
		busy_level = avg_duration / FULL_LOAD_THRESHOLD
		num_busy = int(busy_level * num_ready)

		print(f"[loadbalancer] ticking duration with {len(self.ready_queue)} ready and {avg_duration} avg duration")
		self.old_ready_ids = ready_ids
		self.instance_set.lock.acquire()
		self.instance_set.num_busy = num_busy
		self.instance_set.num_hot = num_ready
		self.instance_set.lock.release()
		self.lock.release()

	def tick_background(self, event):
		while not event.is_set():
			self.update_ready_queue()
			self.tick_duration()
			time.sleep(TIME_INTERVAL_SECONDS)

	def get_address(self, instance):
		addr = instance["public_ipaddr"] + ":" + instance["ports"]["5000/tcp"][0]["HostPort"]
		addr = addr.replace('\n', '')
		return addr

	def get_next_addr(self, num_tokens):
		addr = None
		self.lock.acquire()
		if len(self.ready_queue) != 0:
			(_, _, ready_server) = heapq.heappop(self.ready_queue)
			addr = self.get_address(ready_server)
			id = ready_server["id"]
			# if "tokens/s" in ready_server.keys():
			# 	tps = ready_server["tokens/s"]
			# else:
			# 	tps = DEFAULT_TPS
			tps = DEFAULT_TPS
			self.queue_duration[ready_server["id"]] += ((1 / tps) * num_tokens)
			heapq.heappush(self.ready_queue, (self.queue_duration[ready_server["id"]], ready_server["id"], ready_server))
		self.lock.release()
		print(f"[loadbalancer] next addr is: {addr} on instance: {id}")
		return addr

