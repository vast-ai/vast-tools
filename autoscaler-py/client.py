import time
from threading import Lock
import requests
from collections import defaultdict

from prompt_OOBA import format_prompt_request

WAIT_INTERVAL = 20

class ClientMetrics:
	def __init__(self):
		self.num_requests_started = 0
		self.num_requests_finished = 0
		self.num_requests_successful = 0
		self.total_tokens_generated = 0

		self.total_cost = 0.0

		self.total_request_time = 0.0 #elapsed time across all successful requests
		self.session_start_time = time.time() #maybe make this the time of the first send request

		self.min_request_latency = float('inf')
		self.max_request_latency = 0.0

		default_value = {"num_requests_started": 0, "num_requests_finished": 0, "num_requests_successful" : 0, "total_tokens_generated" : 0, "total_request_time": 0.0, "reported_tps": 0.0}
		self.machine_stats_dict = defaultdict(lambda: default_value.copy())

		self.lock = Lock()

	#call below with lock LOCKED
	def get_time_elapsed(self):
		ret = time.time() - self.session_start_time
		return ret

	def get_request_throughput(self):
		ret = self.num_requests_successful / self.get_time_elapsed()
		return ret

	def get_tokens_throughput(self):
		ret = self.total_tokens_generated / self.get_time_elapsed()
		return ret

	def get_average_latency(self):
		if self.num_requests_successful != 0:
			ret = self.total_request_time / self.num_requests_successful
		else:
			ret = 0.0
		return ret

	def get_total_cost(self):
		ret = self.total_cost
		return ret

	def get_cost_per_token(self): #cost per kilo-token
		if self.total_tokens_generated != 0:
			ret = self.get_total_cost() / (self.total_tokens_generated / 1000)
		else:
			ret = 0.0
		return ret

	def print_instance_metrics(self, instance_ip):
		print("instance ip: {} metrics".format(instance_ip))
		metric_dict = self.machine_stats_dict[instance_ip]
		for metric, value in metric_dict.items():
			print(f"{metric}: {value}")
		real_tps = 0 if metric_dict["total_request_time"] == 0 else metric_dict["total_tokens_generated"] / metric_dict["total_request_time"]
		print("real_tps: {}".format(real_tps))

	def print_metrics(self):
		self.lock.acquire()
		print("overall metrics:")
		print("-----------------------------------------------------")
		print("number of requests started: {}".format(self.num_requests_started))
		print("number of requests finished: {}".format(self.num_requests_finished))
		print("number of requests successful: {}".format(self.num_requests_successful))
		print("number of tokens generated: {}".format(self.total_tokens_generated))

		print("total time elapsed: {}".format(self.get_time_elapsed()))

		print("number of requests per second: {}".format(self.get_request_throughput()))
		print("number of tokens per second: {}".format(self.get_tokens_throughput()))

		print("average request latency: {}".format(self.get_average_latency()))
		print("min request latency: {}".format(self.min_request_latency))
		print("max request latency: {}".format(self.max_request_latency))

		print("total cost in dollars: {}".format(self.get_total_cost()))
		print("total cost per 1000 tokens: {}".format(self.get_cost_per_token()))
		print("-----------------------------------------------------")

		for ip in self.machine_stats_dict.keys():
			print("-----------------------------------------------------")
			self.print_instance_metrics(ip)

		self.lock.release()

class Client:
	def __init__(self):
		self.metrics = ClientMetrics()
		self.lb_server_addr = '127.0.0.1:5000'

	def init_cold_set(self, cold_set_size):
		request_dict = {"cold_set_size" : cold_set_size}
		URI = f'http://{self.lb_server_addr}/cold'
		response = requests.post(URI, json=request_dict)
		if response.status_code == 200:
			print("[client] cold set creation succeeded")
		else:
			print("[client] cold set creation succeeded failed")

	def setup_lb(self):
		URI = f'http://{self.lb_server_addr}/setup'
		response = requests.post(URI)
		if response.status_code == 200:
			print("[client] load balancer server set-up succeeded")
		else:
			print("[client] load balancer server set-up failed")

	def shutdown_lb(self, kill_servers=False):
		request_dict = {"kill_servers": kill_servers}
		URI = f'http://{self.lb_server_addr}/destroy'
		response = requests.post(URI, json=request_dict)
		if response.status_code == 200:
			print("[client] load balancer server shutdown succeeded")
		else:
			print("[client] load balancer server shutdown failed")

	def send_prompt(self, text_prompt, num_tokens, request_num):
		# print("[client] sending prompt")
		request_dict = {"num_tokens" : num_tokens}
		URI = f'http://{self.lb_server_addr}/connect'
		try:
			response = requests.get(URI, json=request_dict)
		except requests.exceptions.ConnectionError as e:
			print("[client] unable to reach loadbalancer with request: {}".format(e.request.path_url))
			return

		if response.status_code == 200 and response.json()["addr"] is not None:
			gpu_server_addr = response.json()["addr"]
			print("[client] request num: {} using hot address: {}".format(request_num, gpu_server_addr))

			self.metrics.lock.acquire()
			self.metrics.num_requests_started += 1
			self.metrics.machine_stats_dict[gpu_server_addr]["num_requests_started"] += 1
			self.metrics.lock.release()

			start_time = time.time()
			gpu_response = format_prompt_request(gpu_server_addr, text_prompt, num_tokens)
			# print(gpu_response)
			end_time = time.time()
			print("[client] request num: {} using address: {} returned, success: {}".format(request_num, gpu_server_addr, gpu_response is not None))
			time_elapsed = end_time - start_time

			self.metrics.lock.acquire()
			machine_entry = self.metrics.machine_stats_dict[gpu_server_addr]
			self.metrics.num_requests_finished += 1
			machine_entry['num_requests_finished'] += 1
			if gpu_response is not None:
				self.metrics.num_requests_successful += 1
				machine_entry["num_requests_successful"] += 1
				self.metrics.total_request_time += time_elapsed
				machine_entry['total_request_time'] += time_elapsed
				self.metrics.min_request_latency = min(self.metrics.min_request_latency, time_elapsed)
				self.metrics.max_request_latency = max(self.metrics.max_request_latency, time_elapsed)
				self.metrics.total_tokens_generated += num_tokens
				machine_entry["total_tokens_generated"] += num_tokens
			self.metrics.lock.release()
		else:
			print("[client] unable to get free gpu server address from the load balancer server")

	def get_metrics(self):
		URI = f'http://{self.lb_server_addr}/metrics'
		response = requests.get(URI)
		if response.status_code == 200:
			response = response.json()
			self.metrics.lock.acquire()
			self.metrics.total_cost = response["total_cost"]
			reported_tps_dict = response["reported_tps"]
			for ip, tps in reported_tps_dict.items():
				self.metrics.machine_stats_dict[ip]["reported_tps"] = tps
			self.metrics.lock.release()

	def get_status(self):
		URI = f'http://{self.lb_server_addr}/status'
		response = requests.get(URI)
		if response.status_code == 200:
			response = response.json()
			return response

	def wait_for_hot(self):
		num_hot = 0
		while num_hot == 0:
			print("[client] server not yet ready")
			time.sleep(WAIT_INTERVAL)
			num_hot = self.get_status()["num_hot"]
		print("[client] server now ready")

	def create_cold_set(self, cold_set_size):
		self.init_cold_set(cold_set_size)
		num_cold = 0
		iters = 0
		while num_cold < cold_set_size:
			time.sleep(WAIT_INTERVAL)
			status = self.get_status()
			if status:
				print("[client] status update:")
				for k, v in status.items():
					print(f"{k} : {v}")
				num_cold = status["num_cold"]
			if iters % 5 == 0:
				self.get_metrics()
				print(f"current cost: {self.metrics.total_cost}")
			iters += 1
		self.shutdown_lb()

# def main():
# 	c = Client()
# 	c.create_cold_set(2)

# if __name__ == "__main__":
# 	main()
