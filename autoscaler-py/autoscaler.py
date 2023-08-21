import subprocess
from threading import Thread, Lock, Event
import time
import re
import json
import os
from ratio_manager import update_rolling_average

TIME_INTERVAL_SECONDS = 10
MAX_COST_PER_HOUR = 10.0
INSTANCE_CONFIG_NAME = "OOBA_configs.json"
IGNORE_INSTANCE_IDS = ["6802321"]

####################################### INSTANCE ACCESS HELPERS #######################################
#could be called on the output from 'show instance' or 'search offers'
def tps(instance):
	# print(instance['machine_id'])
	if "tokens/s" in instance.keys():
		return instance["tokens/s"]
	# filepath = f"instance_info/{instance['machine_id']}.json"
	# if os.path.exists(filepath):
	# 	with open(filepath, "r") as f:
	# 		instance_log = json.load(f)
	# 		if "tokens/s" in instance_log.keys():
	# 			return instance_log["tokens/s"]
	return 0.0

def expected_performance(instance): #could be made more sophisticated, change to cost per token
	return float(instance['dlperf_per_dphtotal']) if instance['dlperf_per_dphtotal'] is not None else 0

def get_instance_id(instance):
	return instance["id"]

####################################### MAIN CLASSES ##################################################
class SimpleStrategy:
	def __init__(self, avg_num_hot=0):
		self.start_num_hot = 10

		self.target_hot_busy_ratio_upper = 0.9
		self.target_hot_busy_ratio_lower = 0.6
		self.target_hot_ratio = 0.3

		self.avg_num_busy = 0
		self.avg_num_hot = avg_num_hot

		# self.price_limit = 0.3

class InstanceSetMetrics: #Represents metrics that the client would have available to them, not the backend autoscaler
	def __init__(self):
		self.num_requests_started = 0
		self.total_tokens_requested = 0

		self.total_cost = 0.0
		self.curr_cost_per_hour = 0.0
		self.session_start_time = time.time() #maybe make this the time of the first send request
		self.lock = Lock()

	#call below with lock LOCKED
	def get_time_elapsed(self):
		ret = time.time() - self.session_start_time
		return ret

class InstanceSet:
	def __init__(self, cold_set_size=0, manage=True):
		self.num_hot = 0
		self.num_busy = 0
		self.ready_instances = []
		self.hot_instances = []
		self.loading_instances = []
		self.cold_instances = [] #assumption is that all cold instances are available to be started

		self.started_instance_ids = []
		self.bad_instance_ids = []
		self.ignore_instance_ids = IGNORE_INSTANCE_IDS

		self.cost_dict = {}

		self.initial = True

		self.metrics = InstanceSetMetrics()

		self.lock = Lock()

		self.update_instance_info()
		self.strat = SimpleStrategy(avg_num_hot=len(self.hot_instances) + len(self.loading_instances) + len(self.cold_instances))

		with open(INSTANCE_CONFIG_NAME, "r") as f:
			self.instance_config = json.load(f)

		self.exit_event = Event()
		self.manage = manage
		self.p1 = Thread(target=self.update_and_manage_background, args=(self.exit_event, self.manage,))
		self.p1.start()
		self.cold_set_size = cold_set_size
		if cold_set_size > 0:
			self.p2 = Thread(target=self.create_cold_set, args=(self.exit_event, cold_set_size,))
			self.p2.start()

	def deconstruct(self):
		print("[autoscaler] deconstructing")
		self.exit_event.set()
		self.p1.join()
		if self.cold_set_size > 0:
			self.p2.join()

	def update_tokens_per_second(self, instance): #need lock here?
		port_num = str(instance["ssh_port"])
		host = instance["ssh_host"]
		result = subprocess.run(["ssh", "-p", port_num, "-o", "StrictHostKeyChecking=no", "root@{}".format(host), "grep 'Output generated' /app/onstart.log | tail -n 1"], capture_output=True)
		out = result.stdout
		tps = None
		if out is not None:
			line = out.decode('utf-8')
			pattern = r"()\d+\.\d+(?=\stokens\/s)"
			match = re.search(pattern, line)
			if match is not None:
				tps = float(match.group())

		if tps is not None:
			instance["tokens/s"] = tps
			with open(f"instance_info/{instance['machine_id']}.json", "w") as f:
				json.dump(instance, f)

	#gets marks instances that are stopped and unable to be started again
	# def tick_duration(self):
	# 	bad_instance_ids = []
	# 	for instance_id in self.started_instance_ids:
	# 		for cold_instance in self.cold_instances:
	# 			if instance_id == cold_instance["id"]:
	# 				bad_instance_ids.append(instance_id)
	# 				self.cold_instances.remove(cold_instance)
	# 				break

	# 	self.bad_instance_ids += bad_instance_ids
	# 	self.started_instance_ids = []

	def update_costs(self):
		self.lock.acquire()
		self.metrics.lock.acquire()

		curr_cost_per_hour = 0.0
		total_add_cost = 0.0
		for instance in self.hot_instances:
			curr_cost_per_hour += instance["dph_total"]
			new_instance_cost = instance["dph_total"] * (instance["duration"] / (60 * 60))
			new_inet_cost = instance["inet_up_cost"] + instance["inet_down_cost"]
			new_cost = new_instance_cost + new_inet_cost
			if instance["id"] in self.cost_dict.keys():
				add_cost = new_cost - self.cost_dict[instance["id"]]
			else:
				add_cost = new_cost

			self.cost_dict[instance["id"]] = new_cost
			total_add_cost += add_cost

		self.metrics.curr_cost_per_hour = curr_cost_per_hour
		self.metrics.total_cost += total_add_cost

		self.metrics.lock.release()
		self.lock.release()

	def cost_safety_check(self):
		self.metrics.lock.acquire()
		hot_idx = 0
		while (self.metrics.curr_cost_per_hour > MAX_COST_PER_HOUR) and (hot_idx < len(self.hot_instances)):
			self.stop_instance(self.hot_instances[hot_idx]["id"])
			self.metrics.curr_cost_per_hour -= self.hot_instances[hot_idx]["dph_base"]
			hot_idx += 1
		self.metrics.lock.release()

	def update_and_manage_background(self, event, manage=True):
		while not event.is_set():
			print("[autoscaler] ticking")
			self.update_instance_info()
			# self.tick_duration()
			if manage:
				self.manage_instances()
			self.update_instance_info() #for cost check for newly started instances
			time.sleep(TIME_INTERVAL_SECONDS)

	def update_instance_info(self):
		curr_instances = self.get_curr_instances()
		if curr_instances is None:
			return

		hot_instances = []
		cold_instances = []
		loading_instances = []

		for instance in curr_instances:
			if instance['actual_status'] == 'offline' or (instance['status_msg'] is not None and 'Error response from daemon' in instance['status_msg']):
				self.bad_instance_ids.append(instance['id'])
			elif instance['actual_status'] == 'running':
				hot_instances.append(instance)
			elif instance['actual_status'] == 'loading' or instance['actual_status'] == None or (instance['actual_status'] == 'created' and instance['intended_status'] == 'running'):
				loading_instances.append(instance)
			elif (instance['actual_status'] == 'created' and instance['intended_status'] == 'stopped') or instance['actual_status'] == 'stopping' or instance['actual_status'] == 'exited':
				cold_instances.append(instance)
			else:
				print("[autoscaler] instance id: {} has unidentified status: {}".format(instance['id'], instance['actual_status']))

		hot_instances.sort(key=tps, reverse=True)
		cold_instances.sort(key=tps, reverse=True)

		self.lock.acquire()
		self.hot_instances = hot_instances
		self.cold_instances = cold_instances
		self.loading_instances = loading_instances
		self.lock.release()

		self.update_ready_instances()
		self.update_costs()
		self.cost_safety_check()

	def check_server_ready(self, instance): #could get notified by the server directly in the future
		port_num = str(instance["ssh_port"])
		host = instance["ssh_host"]
		result = subprocess.run(["ssh", "-p", port_num, "-o", "StrictHostKeyChecking=no", "root@{}".format(host), "grep 'Starting API at http://0.0.0.0:5000/api' /app/onstart.log | tail -n 1"], capture_output=True)
		out = result.stdout
		if out is not None and "Starting API at http://0.0.0.0:5000/api" in out.decode('utf-8'):
			instance["ready"] = True
		else:
			instance["ready"] = False

	def update_ready_instances(self): #might want to take into account issue where a previous instance is no longer ready
		self.lock.acquire()
		ready_instances = []
		threads = []
		for hot_instance in self.hot_instances:
			if hot_instance in self.ready_instances:
				ready_instances.append(hot_instance)
			else:
				t = Thread(target=self.check_server_ready, args=(hot_instance,))
				threads.append((t, hot_instance))
				t.start()

		for (t, hot_instance) in threads:
			t.join()
			if hot_instance["ready"]:
				ready_instances.append(hot_instance)

		self.ready_instances = ready_instances

		threads = []
		for ready_instance in self.ready_instances:
			t = Thread(target=self.update_tokens_per_second, args=(ready_instance,))
			threads.append(t)
			t.start()

		for t in threads:
			t.join()

		self.lock.release()

	def manage_instances(self):
		self.lock.acquire()

		if self.num_busy > self.strat.avg_num_busy:
			num_hot_busy = self.num_busy
		else:
			num_hot_busy = update_rolling_average(self.strat.avg_num_busy, self.num_busy, TIME_INTERVAL_SECONDS, 0.01)
		self.strat.avg_num_busy = num_hot_busy

		num_starting = 0 #might want to keep this as a rolling tally
		num_hot = self.num_hot + num_starting
		num_model_loading = len(self.hot_instances) - num_hot
		num_loading = len(self.loading_instances) + num_model_loading

		num_cold = len(self.cold_instances) + num_loading
		num_tot = num_hot + num_cold

		hot_busy_ratio = (num_hot_busy + 1) / (num_hot + 1)
		hot_ratio = (num_hot + 1) / (num_tot + 0.1)

		num_hot_rolling = update_rolling_average(self.strat.avg_num_hot, num_hot, TIME_INTERVAL_SECONDS, 0.01)
		self.strat.avg_num_hot = num_hot_rolling
		hot_ratio_rolling = (num_hot_rolling + 1) / (num_tot + 0.1)

		print("[autoscaler] managing instances: hot_busy_ratio: {}, hot_ratio: {}, hot_ratio_rolling: {}, num_hot: {}, num_busy: {}, num_cold_ready: {}, num_loading: {}, num_total: {}".format(hot_busy_ratio, hot_ratio, hot_ratio_rolling, num_hot, num_hot_busy, len(self.cold_instances), num_loading, num_tot))
		for instance_id in self.bad_instance_ids:
			print("[autoscaler] destroying bad instance: {}".format(instance_id))
			self.destroy_instance(instance_id)
		self.bad_instance_ids = []

		ask_list = self.get_asks(budget=True)

		#start and stop instances
		if (hot_busy_ratio > self.strat.target_hot_busy_ratio_upper) and (len(self.cold_instances) != 0):
			print("[autoscaler] hot busy ratio too high!")
			cold_idx = 0
			while hot_busy_ratio > self.strat.target_hot_busy_ratio_upper and cold_idx < len(self.cold_instances):
				new_id = self.cold_instances[cold_idx]['id']
				cold_idx += 1
				if self.start_instance(new_id):
					num_hot += 1
					hot_busy_ratio = (num_hot_busy + 1) / (num_hot + 1)

		elif hot_busy_ratio < self.strat.target_hot_busy_ratio_lower:
			print("[autoscaler] hot busy ratio too low!")
			hot_idx = len(self.hot_instances) - 1
			while hot_busy_ratio < self.strat.target_hot_busy_ratio_lower and hot_idx >= 0 and (len(self.hot_instances) != 0):
				self.stop_instance(self.hot_instances[hot_idx]['id'])
				num_hot -= 1
				hot_busy_ratio = (num_hot_busy + 1) / (num_hot + 1)
				hot_idx -= 1

		#create and destroy instances
		if hot_ratio > self.strat.target_hot_ratio:
			print("[autoscaler] hot ratio too high!")
			ask_idx = 0
			while hot_ratio > self.strat.target_hot_ratio and ask_idx < len(ask_list) - 1:
				self.create_instance(ask_list[ask_idx]['id'])
				num_tot += 1
				hot_ratio = (num_hot + 1) / (num_tot + 1)
				ask_idx += 1
		elif hot_ratio_rolling < self.strat.target_hot_ratio:
			print("[autoscaler] hot ratio too low!")
			cold_idx = len(self.cold_instances) - 1
			while hot_ratio_rolling < self.strat.target_hot_ratio and cold_idx >= 0 and (len(self.cold_instances) != 0):
				self.destroy_instance(self.cold_instances[cold_idx]['id']) #need to allow loading instances to be destroyed here because they are also considered cold
				num_tot -= 1
				hot_ratio_rolling = (num_hot_rolling + 1) / (num_tot + 1)
				cold_idx -= 1

		self.lock.release()

	############################### vastai API Helper Functions ##########################################################

	def get_curr_instances(self):
		result = subprocess.run(["vastai", "show", "instances", "--raw"], capture_output=True)
		instance_info = result.stdout.decode('utf-8')
		if instance_info:
			try:
				curr_instances = json.loads(instance_info)
			except json.decoder.JSONDecodeError:
				curr_instances = None
		else:
			curr_instances = None

		return curr_instances

	def get_asks(self, model="13", budget=True):
		config = self.instance_config[model]["get"]
		order = "dph" if budget else "dlperf_per_dphtotal" #could also sort by network speed?
		args = f"'gpu_ram >= {config['gpu_ram']} disk_space >= {config['disk_space']}' -o '{order}'"
		result = subprocess.run(["vastai search offers " + args + " --raw"], shell=True, capture_output=True)
		listed_instances = result.stdout.decode('utf-8')
		if listed_instances:
			ask_list = json.loads(listed_instances)
			return ask_list
		else:
			return None

	def create_cold_set(self, event, num_instances):
		self.create_instances(num_instances, model="13")
		while not event.is_set():
			for ready_instance in self.ready_instances:
				self.stop_instance(ready_instance['id'])
				print(f"[autoscaler] id: {ready_instance['id']} is now ready and cold")
			time.sleep(TIME_INTERVAL_SECONDS)
		print("[autoscaler] done creating cold set")

	def create_instances(self, num_instances, model="13"):
		ask_list = self.get_asks(model=model)
		print(ask_list[:2])
		ask_list_iter = iter(ask_list)
		for _ in range(num_instances):
			self.create_instance(next(ask_list_iter)['id'], model)

	def start_instance(self, instance_id: float):
		if instance_id in self.ignore_instance_ids:
			return
		print("starting instance: {}".format(instance_id))
		result = subprocess.run(["vastai", "start", "instance", str(instance_id), "--raw"], capture_output=True)
		if "starting instance" in result.stdout.decode('utf-8'):
			return True
		else:
			print(result.stdout.decode('utf-8'))
			return False

	def stop_instance(self, instance_id: float):
		if instance_id in self.ignore_instance_ids:
			return
		print("stopping instance {}".format(instance_id))
		result = subprocess.run(["vastai", "stop", "instance", str(instance_id), "--raw"], capture_output=True)
		response = result.stdout.decode('utf-8')
		print(response)

	def create_instance(self, instance_id: float, model="13"):
		config = self.instance_config[model]["create"]
		print("creating instance {}".format(instance_id))
		args = f" --onstart {config['onstart']} --image {config['image']} --disk {config['disk']}"
		result = subprocess.run([f"vastai create instance {str(instance_id)}" + args + " --raw"], shell=True, capture_output=True) #will add more fields as necessary
		if result is not None and result.stdout.decode('utf-8') is not None:
			try:
				response = json.loads(result.stdout.decode('utf-8'))
				if response["success"]:
					new_id = response["new_contract"]
					return new_id
			except json.decoder.JSONDecodeError:
				pass

	def destroy_all_instances(self):
		for instance in (self.hot_instances + self.cold_instances + self.loading_instances):
			self.destroy_instance(instance["id"])

	def stop_all_instances(self):
		for instance in (self.hot_instances + self.loading_instances):
			self.stop_instance(instance["id"])

	def destroy_instance(self, instance_id: float):
		if instance_id in self.ignore_instance_ids:
			return
		print("destroying instance {}".format(instance_id))
		result = subprocess.run(["vastai", "destroy", "instance", str(instance_id), "--raw"], capture_output=True)
		response = result.stdout.decode('utf-8')
		print(response)

	def print_instance_ids(self, label, instances):
		for instance in instances:
			print("{} instance id: {}".format(label, instance["id"]))

	def print_instances(self, curr_instances=None):
		if curr_instances is None:
			curr_instances = self.get_curr_instances()
		for instance in curr_instances:
			print("id: {}, actual_status: {}, intended_status: {}, current_state: {}".format(instance["id"], instance["actual_status"], instance["intended_status"], instance["cur_state"]))
