import subprocess
from threading import Thread, Lock, Event
from concurrent.futures import ThreadPoolExecutor
import time
import re
import json
import secrets
import os
from ratio_manager import update_rolling_average
from prompt_OOBA import send_vllm_request_auth, send_vllm_request_streaming_test_auth

TIME_INTERVAL_SECONDS = 5
MAX_COST_PER_HOUR = 10.0
MAX_CONCURRENCY = 100
MAX_ACTIONS = 3
INSTANCE_CONFIG_NAME = "configs/OOBA_configs.json"
IGNORE_INSTANCE_IDS = [6924410, 6924411, 6925426, 6924389, 6924390, 6924720] # 6925427
BAD_MACHINE_IDS = [4424]
ERROR_STRINGS = ["safetensors_rust.SafetensorError", "RuntimeError", "Error: remote port forwarding failed"]
TEST_PROMPT = "What?"

####################################### INSTANCE ACCESS HELPERS #######################################
def get_curr_instances():
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

def get_model_address(instance, streaming):
	if streaming:
		addr = instance["public_ipaddr"] + ":" + instance["ports"]["5005/tcp"][0]["HostPort"]
	else:
		addr = instance["public_ipaddr"] + ":" + instance["ports"]["5000/tcp"][0]["HostPort"]
	addr = addr.replace('\n', '')
	return addr

####################################### MAIN CLASSES ##################################################
class SimpleStrategy:
	def __init__(self, avg_num_hot=0):
		self.start_num_hot = 10

		self.target_hot_busy_ratio_upper = 0.9
		self.target_hot_busy_ratio_lower = 0.6
		self.target_hot_ratio = 0.3

		self.avg_num_busy = 0
		self.avg_num_hot = avg_num_hot

		self.avg_requests_per_second = 0 #should start using this soon

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
	def __init__(self, manage=False, streaming=False, model="vllm-13"):
		self.num_hot = 0
		self.num_busy = 0

		self.hot_instances = []
		self.running_instances = []
		self.loading_instances = []
		self.cold_instances = [] #assumption is that all cold instances are available to be started

		self.instance_info_map = {}
		self.started_instance_ids = []
		self.bad_instance_ids = []
		self.ignore_instance_ids = IGNORE_INSTANCE_IDS

		self.streaming = streaming
		self.manage = manage
		self.model = model

		self.cost_dict = {}
		self.metrics = InstanceSetMetrics()
		self.lock = Lock()
		
		self.update_instance_info(init=True)
		self.strat = SimpleStrategy(avg_num_hot=len(self.running_instances) + len(self.loading_instances) + len(self.cold_instances))

		with open(INSTANCE_CONFIG_NAME, "r") as f:
			self.instance_config = json.load(f)

		self.exit_event = Event()
		self.manage_threads = []
		self.p1 = Thread(target=self.update_and_manage_background, args=(self.exit_event,))
		self.p1.start()

	def deconstruct(self):
		print("[autoscaler] deconstructing")
		self.exit_event.set()
		self.p1.join()

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

		# if tps is not None:
		# 	instance["tokens/s"] = tps
		# 	with open(f"instance_info/{instance['machine_id']}.json", "w") as f:
		# 		json.dump(instance, f)

	def update_and_manage_background(self, event):
		while not event.is_set():
			print("[autoscaler] ticking")
			self.update_instance_info(init=False)
			self.manage_instances()
			time.sleep(TIME_INTERVAL_SECONDS)

	def read_instance_json(self, instance):
		id = instance["id"]
		filepath = f"instance_info/{id}.json"
		if os.path.exists(filepath):
			with open(filepath, "r") as f:
				instance_log = json.load(f)
				self.instance_info_map[id] = instance_log
				return True
		else:
			return False

	def update_instance_info(self, init):
		curr_instances = get_curr_instances()
		if curr_instances is None:
			return

		if init:
			for instance in curr_instances: #could parallelize with act_on_instances
				self.read_instance_json(instance)

		running_instances = []
		cold_instances = []
		loading_instances = []

		for instance in curr_instances:
			if instance["id"] in self.ignore_instance_ids:
				continue
			if instance["id"] not in self.instance_info_map.keys():
				if not (self.read_instance_json(instance)):
					self.bad_instance_ids.append(instance['id'])
					continue
			if (instance['actual_status'] == 'offline') or (instance['status_msg'] is not None and 'Error response from daemon' in instance['status_msg']) or (instance['machine_id'] in BAD_MACHINE_IDS):
				self.bad_instance_ids.append(instance['id'])
			elif instance['actual_status'] == 'running':
				running_instances.append(instance)
			elif instance['actual_status'] == 'loading' or instance['actual_status'] == None or (instance['actual_status'] == 'created' and instance['intended_status'] == 'running'):
				loading_instances.append(instance)
			elif (instance['actual_status'] == 'created' and instance['intended_status'] == 'stopped') or instance['actual_status'] == 'stopping' or instance['actual_status'] == 'exited':
				cold_instances.append(instance)
			else:
				print("[autoscaler] instance id: {} has unidentified status: {}".format(instance['id'], instance['actual_status']))

		running_instances.sort(key=tps, reverse=True)
		cold_instances.sort(key=tps, reverse=True)

		self.lock.acquire()
		self.running_instances = running_instances
		self.cold_instances = cold_instances
		self.loading_instances = loading_instances
		self.lock.release()

		self.update_hot_instances()

	# def check_server_error(self, instance): #will hang, might need to find a faster way to do this
	# 	port_num = str(instance["ssh_port"])
	# 	host = instance["ssh_host"]
	# 	result = subprocess.run([f"ssh -p {port_num} -o StrictHostKeyChecking=no root@{host} grep -E '{ERROR_STRINGS[0]}|{ERROR_STRINGS[1]}' /app/onstart.log"], shell=True, capture_output=True)
	# 	out = result.stdout
	# 	if out is not None and ((ERROR_STRINGS[0] in out.decode('utf-8')) or (ERROR_STRINGS[1] in out.decode('utf-8'))):
	# 		return True
	# 	else:
	# 		return False

	# def find_error_instances(self):
	# 	self.lock.acquire()

	# 	loaded_but_not_hot = [inst for inst in self.running_instances if inst not in self.hot_instances]
	# 	# loaded_but_not_hot = [self.running_instances[0]] if len(self.running_instances) != 0 else []
	# 	if len(loaded_but_not_hot) == 0:
	# 		self.lock.release()
	# 		return

	# 	error_instance_ids = []
	# 	with ThreadPoolExecutor(MAX_CONCURRENCY) as e:
	# 		for instance, result in zip(loaded_but_not_hot, e.map(self.check_server_error, loaded_but_not_hot)):
	# 			if result:
	# 				error_instance_ids.append(instance["id"])

	# 	self.lock.release()
	# 	return error_instance_ids

	# def zero_ready_log(self, instance):
	# 	port_num = str(instance["ssh_port"])
	# 	host = instance["ssh_host"]
	# 	ssh_string = f"ssh -p {port_num} -o StrictHostKeyChecking=no root@{host}"
	# 	command_string1 = f"cp /app/onstart.log /app/onstart_og.log"
	# 	command_string2 = f"echo -n '' > /app/onstart.log"
	# 	result = subprocess.run([ssh_string + command_string1], shell=True, capture_output=True)
	# 	result = subprocess.run([ssh_string + command_string2], shell=True, capture_output=True)

	def check_server_hot(self, instance): #could get notified by the server directly in the future
		port_num = str(instance["ssh_port"])
		host = instance["ssh_host"]
		key_file = "/home/nicholas/Desktop/VastAI/ssh/vast-2" #not necessary if shell=True
		ssh_string = f"ssh -i {key_file} -p {port_num} -o StrictHostKeyChecking=no root@{host}"
		hot_str = "blocks"
		command_string = f"grep '{hot_str}' /src/infer.log | tail -n 1"
		result = subprocess.run([ssh_string + " " + command_string], shell=True, capture_output=True)
		# print(result)
		out = result.stdout
		# print(out)
		if out is not None and hot_str in out.decode('utf-8'):
			return True
		else:
			return False

	def test_hot_instance(self, instance, token):
		addr = get_model_address(instance, self.streaming)
		if self.streaming:
			return send_vllm_request_streaming_test_auth(addr, token)

		print(f"[autoscaler] sending to instance: {instance['id']}")
		response = send_vllm_request_auth(addr, token, TEST_PROMPT)
		print(f"[autoscaler] got response from instance: {instance['id']}")
		if response["reply"] is not None:
			if response["num_tokens"] != 0:
				return True
		return False

	def update_hot_instances(self):
		self.lock.acquire()
		running_instances = self.running_instances
		hot_instances = self.hot_instances
		instance_info_map = self.instance_info_map
		self.lock.release()

		if len(running_instances) == 0:
			return

		running_but_not_hot = [i for i in running_instances if ((i not in hot_instances))] # and (i["id"] not in self.ignore_instance_ids)
		new_hot_instances = []
		with ThreadPoolExecutor(MAX_CONCURRENCY) as e:
			for instance, result in zip(running_but_not_hot, e.map(self.check_server_hot, running_but_not_hot)):
				if result:
					new_hot_instances.append(instance)
		print(f"[autoscaler] initial num hot before testing: {len(new_hot_instances)}")
		new_hot_instances_tested = []
		new_hot_tokens = [instance_info_map[instance["id"]]["mtoken"] for instance in new_hot_instances]
		with ThreadPoolExecutor(MAX_CONCURRENCY) as e:
			for instance, result in zip(new_hot_instances, e.map(self.test_hot_instance, new_hot_instances, new_hot_tokens)):
				if result:
					new_hot_instances_tested.append(instance)

		print(f"[autoscaler] num hot after testing: {len(new_hot_instances_tested)}")
		next_hot_instances = [i for i in running_instances if ((i in hot_instances) or (i in new_hot_instances_tested))] #gets rid of old hot instances that are no longer running

		# if len(self.hot_instances) != 0:
		# 	with ThreadPoolExecutor(len(self.hot_instances)) as e:
		# 		# e.map(self.update_tokens_per_second, self.hot_instances)
		# 		e.map(self.zero_ready_log, self.hot_instances)

		for instance in next_hot_instances:
			instance["mtoken"] = instance_info_map[instance["id"]]["mtoken"]

		self.lock.acquire()
		self.hot_instances = next_hot_instances
		self.lock.release()

	def manage_instances(self):
		self.lock.acquire()

		# print("[autoscaler] dealing with bad instances")
		# self.act_on_instances(self.destroy_instance, len(self.bad_instance_ids), self.bad_instance_ids)
		# self.bad_instance_ids = []

		if self.num_busy > self.strat.avg_num_busy:
			num_hot_busy = self.num_busy
		else:
			num_hot_busy = update_rolling_average(self.strat.avg_num_busy, self.num_busy, TIME_INTERVAL_SECONDS, 0.01)
		self.strat.avg_num_busy = num_hot_busy

		num_hot = self.num_hot
		num_model_loading = len(self.running_instances) - num_hot
		num_loading = len(self.loading_instances) + num_model_loading

		num_cold = len(self.cold_instances) + num_loading
		num_tot = num_hot + num_cold

		hot_busy_ratio = (num_hot_busy + 1) / (num_hot + 0.05)
		hot_ratio = (num_hot + 1) / (num_tot + 0.1)

		num_hot_rolling = update_rolling_average(self.strat.avg_num_hot, num_hot, TIME_INTERVAL_SECONDS, 0.01)
		self.strat.avg_num_hot = num_hot_rolling
		hot_ratio_rolling = (num_hot_rolling + 1) / (num_tot + 0.1)

		print(f"[autoscaler] internal lists: len(self.running_instances): {len(self.running_instances)}, len(self.hot_instances): {len(self.hot_instances)}")
		print("[autoscaler] managing instances: hot_busy_ratio: {}, hot_ratio: {}, hot_ratio_rolling: {}, num_hot: {}, num_busy: {}, num_cold_ready: {}, num_loading: {}, num_total: {}".format(hot_busy_ratio, hot_ratio, hot_ratio_rolling, num_hot, num_hot_busy, len(self.cold_instances), num_loading, num_tot))

		if self.manage:
			#stop and start instances
			if hot_busy_ratio < self.strat.target_hot_busy_ratio_lower:
				print("[autoscaler] hot busy ratio too low!")
				count = num_hot - int((hot_busy_ratio / self.strat.target_hot_busy_ratio_lower) * max(num_hot, 1))
				#maybe I can filter for idle here
				running_instances = self.running_instances[::-1]
				stop_thread = Thread(target=self.act_on_instances, args=(self.stop_instance, count, running_instances))
				stop_thread.start()
				stop_thread.join()

			elif hot_busy_ratio >= self.strat.target_hot_busy_ratio_upper:
				print("[autoscaler] hot busy ratio too high!")
				count = int((hot_busy_ratio / self.strat.target_hot_busy_ratio_upper) * max(num_hot, 1)) - num_hot
				start_thread = Thread(target=self.act_on_instances, args=(self.start_instance, count, self.cold_instances))
				start_thread.start()
				start_thread.join()

			#create and destroy instances
			if hot_ratio > self.strat.target_hot_ratio:
				print("[autoscaler] hot ratio too high!")
				count = int((hot_ratio / self.strat.target_hot_ratio) * max(num_tot, 1)) - num_tot
				create_thread = Thread(target=self.act_on_instances, args=(self.create_instance, count, self.get_asks(budget=True)))
				create_thread.start()
				create_thread.join()

			elif hot_ratio_rolling < self.strat.target_hot_ratio:
				print("[autoscaler] hot ratio too low!")
				count = num_tot - int((hot_ratio_rolling / self.strat.target_hot_ratio) * max(num_tot, 1))
				cold_instances = self.cold_instances[::-1]
				destroy_thread = Thread(target=self.act_on_instances, args=(self.destroy_instance, count, cold_instances))
				destroy_thread.start()
				destroy_thread.join()

		self.lock.release()
	############################### vastai API Helper Functions ##########################################################

	def get_asks(self, budget=True):
		ask_list = []
		config = self.instance_config[self.model]["get"]
		gpu_configs = config["gpu"]
		disk_args =  f"disk_space >= {config['disk_space']}"
		order = "dph" if budget else "dlperf_per_dphtotal"
		for gpu_config in gpu_configs:
			gpu_args = ""
			if "gpu_name" in gpu_config.keys():
				gpu_args += f"gpu_name = {gpu_config['gpu_name']} "
			if "num_gpus" in gpu_config.keys():
				gpu_args += f"num_gpus = {gpu_config['num_gpus']} "
			if "gpu_ram" in gpu_config.keys():
				gpu_args += f"gpu_ram >= {gpu_config['gpu_ram']} "

			full_args = f"'{gpu_args}{disk_args}' -o '{order}'"
			print(full_args)
			result = subprocess.run(["vastai search offers " + full_args + " --raw"], shell=True, capture_output=True)
			listed_instances = result.stdout.decode('utf-8')
			if listed_instances and listed_instances[0] == '[':
				ask_list += json.loads(listed_instances)

		return ask_list

	def create_instances(self, num_instances):
		ask_list = self.get_asks()
		for instance in ask_list:
			instance["model"] = self.model
		self.act_on_instances(self.create_instance, num_instances, ask_list)

	def start_instances(self, num_instances):
		self.act_on_instances(self.start_instance, num_instances, self.cold_instances)

	def act_on_instances(self, action, num_instances, instance_list):
		num_instances = min(num_instances, MAX_ACTIONS)
		print(f"[autoscaler] calling {action.__name__} on {num_instances} instances, len(instance_list): {len(instance_list)}")
		if instance_list is None or len(instance_list) == 0:
			return

		num_acted = 0
		while num_acted < num_instances and len(instance_list) > 0:
			batch_idx = num_instances - num_acted
			batch_idx = min(batch_idx, len(instance_list))
			curr_instances = instance_list[:batch_idx]
			instance_list = instance_list[batch_idx:]
			with ThreadPoolExecutor(MAX_CONCURRENCY) as e:
				for result in e.map(action, curr_instances):
					if result:
						num_acted += 1

		print(f"[autoscaler] sucessfully called {action.__name__} on {num_acted} instances")

	def start_instance(self, instance):
		instance_id = instance["id"]
		if instance_id in self.ignore_instance_ids:
			return
		result = subprocess.run(["vastai", "start", "instance", str(instance_id), "--raw"], capture_output=True)
		if "starting instance" in result.stdout.decode('utf-8'):
			return True
		else:
			return False

	def stop_instance(self, instance):
		instance_id = instance["id"]
		if instance_id in self.ignore_instance_ids:
			return
		result = subprocess.run(["vastai", "stop", "instance", str(instance_id), "--raw"], capture_output=True)
		return True

	def create_instance(self, instance):
		instance_id = instance["id"]
		if "model" in instance.keys():
			model = instance["model"]
		else:
			model = self.model
		num_gpus = instance["num_gpus"]
		config = self.instance_config[model]["create"]
		mtoken = secrets.token_hex(32)
		if self.streaming:
			onstart = f"{config['onstart']}_streaming.sh"
		else:
			onstart = f"{config['onstart']}.sh"
		args = f" --onstart {onstart} --image {config['image']} --disk {config['disk']} --env '-e MASTER_TOKEN={mtoken} -e NUM_GPUS={num_gpus} {config['env']}'" # --ssh --direct
		result = subprocess.run([f"vastai create instance {str(instance_id)}" + args + " --raw"], shell=True, capture_output=True)
		print(result)
		if result is not None and result.stdout.decode('utf-8') is not None:
			try:
				response = json.loads(result.stdout.decode('utf-8'))
				if response["success"]:
					new_id = response["new_contract"]
					init_json = {"mtoken" : mtoken, "model_loaded" : None, "tps" : None}
					self.instance_info_map[new_id] = init_json
					with open(f"instance_info/{new_id}.json", "w") as f:
						json.dump(init_json, f)
					return new_id

			except json.decoder.JSONDecodeError:
				pass

	def destroy_instance(self, instance):
		instance_id = instance["id"]
		if instance_id in self.ignore_instance_ids:
			return
		result = subprocess.run(["vastai", "destroy", "instance", str(instance_id), "--raw"], capture_output=True)
		return True

	def destroy_all_instances(self):
		all = self.running_instances + self.cold_instances + self.loading_instances
		self.act_on_instances(self.destroy_instance, len(all), all)

	def stop_all_instances(self):
		all = self.running_instances + self.loading_instances
		self.act_on_instances(self.stop_instance, len(all), all)

	def print_instance_ids(self, label, instances):
		for instance in instances:
			print("{} instance id: {}".format(label, instance["id"]))

	def print_instances(self, curr_instances=None):
		if curr_instances is None:
			curr_instances = get_curr_instances()
		for instance in curr_instances:
			print("id: {}, actual_status: {}, intended_status: {}, current_state: {}".format(instance["id"], instance["actual_status"], instance["intended_status"], instance["cur_state"]))
