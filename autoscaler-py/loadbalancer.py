from collections import defaultdict
from threading import Thread, Lock, Event
import heapq
import time

from autoscaler import InstanceSet

TIME_INTERVAL_SECONDS = 5
BUSY_LOAD_THRESHOLD = 10.0
DEFAULT_TPS = 10.0

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
		busy_ids = []
		num_ready = 0
		ready_ids = []
		for (_, _, instance) in list(self.ready_queue):
			ready_ids.append(instance["id"])
			prev_queue_duration = self.queue_duration[instance['id']]
			curr_queue_duration = max(0, prev_queue_duration - TIME_INTERVAL_SECONDS)
			self.queue_duration[instance['id']] = curr_queue_duration
			if instance["id"] in self.old_ready_ids:
				num_ready += 1
				if curr_queue_duration >= BUSY_LOAD_THRESHOLD:
					busy_ids.append(instance['id'])
			# print("[loadbalancer] instance: {} has queue duration: {}".format(instance['id'], curr_queue_duration))

		self.old_ready_ids = ready_ids
		self.instance_set.lock.acquire()
		self.instance_set.busy_instance_ids = busy_ids
		self.instance_set.num_hot = num_ready
		self.instance_set.lock.release()
		self.lock.release()

	def tick_background(self, event):
		while not event.is_set():
			self.update_ready_queue()
			self.tick_duration()
			time.sleep(TIME_INTERVAL_SECONDS)

	def get_address(self, instance):
		return instance["public_ipaddr"] + ":" + instance["ports"]["5000/tcp"][0]["HostPort"]

	def get_next_addr(self, num_tokens):
		addr = None
		self.lock.acquire()
		if len(self.ready_queue) != 0:
			(_, _, ready_server) = heapq.heappop(self.ready_queue)
			addr = self.get_address(ready_server)
			if "tokens/s" in ready_server.keys():
				tps = ready_server["tokens/s"]
			else:
				tps = DEFAULT_TPS

			self.queue_duration[ready_server["id"]] += ((1 / tps) * num_tokens)
			#could check here to see if a server is being overloaded
			# if self.queue_duration[ready_server["id"]] > BUSY_LOAD_THRESHOLD:
			# 	self.instance_set.report_busy(ready_server["id"])
			heapq.heappush(self.ready_queue, (self.queue_duration[ready_server["id"]], ready_server["id"], ready_server))
		self.lock.release()
		print("[loadbalancer] next addr is: {}".format(addr))
		return addr

