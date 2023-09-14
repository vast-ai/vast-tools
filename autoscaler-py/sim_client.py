import time
from threading import Lock
import requests
from collections import defaultdict
import os

from autoscaler import get_curr_instances, get_model_address
from prompt_model import send_vllm_request_auth, send_vllm_request_streaming_auth, send_hf_tgi_streaming_auth

WAIT_INTERVAL = 5

class ClientMetrics:
	def __init__(self, streaming, backend):

		self.streaming = streaming
		self.backend = backend

		self.num_serverless_server_started = 0
		self.num_serverless_server_finished = 0

		self.num_requests_started = 0
		self.num_requests_finished = 0
		self.num_requests_successful = 0
		self.total_tokens_generated = 0

		self.total_cost = 0.0

		self.total_request_time = 0.0 #elapsed time across all successful requests
		self.session_start_time = 0.0

		self.min_request_latency = float('inf')
		self.max_request_latency = 0.0

		self.total_first_msg_wait = 0.0
		self.min_first_msg_wait = float('inf')
		self.max_first_msg_wait = 0.0

		default_value = {"num_requests_started": 0, "num_requests_finished": 0, "num_requests_successful" : 0, "total_tokens_generated" : 0, "total_request_time": 0.0, "reported_tps": 0.0}
		self.machine_stats_dict = defaultdict(lambda: default_value.copy())

		self.lock = Lock()

	#call below with lock LOCKED
	def get_time_elapsed(self):
		ret = self.session_end_time - self.session_start_time
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

	def get_average_first_msg_wait(self):
		if self.num_requests_successful != 0:
			ret = self.total_first_msg_wait / self.num_requests_successful
		else:
			ret = 0.0
		return ret

	def calculate_costs(self):
		instances = None
		for _ in range(5):
			instances = get_curr_instances()
			if instances is not None:
				break
		if instances is None:
			print("error!")
			return
		dph = 0.0
		for instance in instances:
			if "ports" not in instance.keys():
				continue
			if get_model_address(instance, self.streaming, self.backend) in self.machine_stats_dict.keys():
				dph += instance["dph_base"]
		self.total_cost = (self.get_time_elapsed() / (60 * 60)) * dph

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
		print(f"printing metrics and lock is locked: {self.lock.locked()}")
		# print("waiting_for_lock")
		# self.lock.acquire()
		# print("got_lock")
		self.calculate_costs()
		print("overall metrics:")
		print("-----------------------------------------------------")
		print("number of serverless server requests started: {}".format(self.num_serverless_server_started))
		print("number of serverless server requests finished: {}".format(self.num_serverless_server_finished))
		print("number of gpu server requests started: {}".format(self.num_requests_started))
		print("number of gpu server requests finished: {}".format(self.num_requests_finished))
		print("number of gpu server requests successful: {}".format(self.num_requests_successful))
		rel_ratio = (self.num_requests_successful / self.num_requests_started) if self.num_requests_started != 0 else 0.0
		print(f"reliability ratio: {rel_ratio}")

		print("number of tokens generated: {}".format(self.total_tokens_generated))
		print("total time elapsed: {}".format(self.get_time_elapsed()))

		print("number of requests per second: {}".format(self.get_request_throughput()))
		print("number of tokens per second: {}".format(self.get_tokens_throughput()))

		print("average request latency: {}".format(self.get_average_latency()))
		print("min request latency: {}".format(self.min_request_latency))
		print("max request latency: {}".format(self.max_request_latency))

		if self.streaming:
			print("avg first msg wait: {}".format(self.get_average_first_msg_wait()))
			print("min first msg wait: {}".format(self.min_first_msg_wait))
			print("max first msg wait: {}".format(self.max_first_msg_wait))

		print("total cost in dollars: {}".format(self.get_total_cost()))
		print("total cost per 1000 tokens: {}".format(self.get_cost_per_token()))
		print("-----------------------------------------------------")

		for ip in self.machine_stats_dict.keys():
			print("-----------------------------------------------------")
			self.print_instance_metrics(ip)

		# self.lock.release()

class Client:
	def __init__(self, streaming, backend, model, manage):
		self.streaming = streaming
		self.backend = backend
		self.model = model
		self.manage = manage
		self.metrics = ClientMetrics(streaming=streaming, backend=backend)
		self.lb_server_addr = '127.0.0.1:5000'
		self.auto_server_addr = '127.0.0.1:8000'
		# self.vllm_server_addr = '89.37.121.214:48271'
		self.error_fd = os.open("logs/error.txt", os.O_WRONLY | os.O_CREAT)
		os.write(self.error_fd, f"ERRORS: \n".encode("utf-8"))
		self.error_lock = Lock()

	def setup_lb(self):
		URI = f'http://{self.lb_server_addr}/setup'
		autoscaler_args = {"streaming" : self.streaming, "backend" : self.backend, "manage" : self.manage, "model" : self.model}
		request_dict = {"args" : autoscaler_args}
		response = requests.post(URI, json=request_dict)
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


	def update_metrics_started(self, gpu_addr):
		# self.metrics.lock.acquire()
		self.metrics.num_requests_started += 1
		self.metrics.machine_stats_dict[gpu_addr]['num_requests_started'] += 1
		# self.metrics.lock.release()

	def update_metrics(self, gpu_addr, success, num_tokens, time_elapsed, first_msg_wait=None):
		# self.metrics.lock.acquire()
		machine_entry = self.metrics.machine_stats_dict[gpu_addr]
		self.metrics.num_requests_finished += 1
		machine_entry['num_requests_finished'] += 1
		if success:
			self.metrics.num_requests_successful += 1
			machine_entry["num_requests_successful"] += 1
			self.metrics.total_request_time += time_elapsed
			machine_entry['total_request_time'] += time_elapsed
			self.metrics.min_request_latency = min(self.metrics.min_request_latency, time_elapsed)
			self.metrics.max_request_latency = max(self.metrics.max_request_latency, time_elapsed)
			self.metrics.total_tokens_generated += num_tokens
			machine_entry["total_tokens_generated"] += num_tokens

			if first_msg_wait:
				self.metrics.min_first_msg_wait = min(self.metrics.min_first_msg_wait, first_msg_wait)
				self.metrics.max_first_msg_wait = max(self.metrics.max_first_msg_wait, first_msg_wait)
				self.metrics.total_first_msg_wait += first_msg_wait

		# self.metrics.lock.release()

	def send_prompt(self, text_prompt, id, num_tokens=100):
		request_dict = {"num_tokens" : num_tokens}
		URI = f'http://{self.lb_server_addr}/connect'
		self.metrics.num_serverless_server_started += 1
		response = requests.get(URI, json=request_dict)
		self.metrics.num_serverless_server_finished += 1

		if response.status_code == 200 and response.json()["addr"] is not None:
			gpu_addr = response.json()["addr"]
			id_token = response.json()["token"]
			self.update_metrics_started(gpu_addr)
			start_time = time.time()
			if self.backend == "hf_tgi":
				gpu_response = send_hf_tgi_streaming_auth(gpu_addr, token=id_token, inputs=text_prompt)
			else:
				if self.streaming:
					gpu_response = send_vllm_request_streaming_auth(gpu_addr, token=id_token, prompt=text_prompt)
				else:
					gpu_response = send_vllm_request_auth(gpu_addr, id_token, text_prompt)

			end_time = time.time()
			time_elapsed = end_time - start_time
			success = (gpu_response["reply"] is not None)
			self.update_metrics(gpu_addr, success, gpu_response["num_tokens"], time_elapsed, gpu_response["first_msg_wait"])
			if not success:
				self.error_lock.acquire()
				os.write(self.error_fd, f"{gpu_response['error']}\n".encode("utf-8"))
				self.error_lock.release()

	def get_status(self):
		URI = f'http://{self.auto_server_addr}/status'
		response = requests.get(URI)
		if response.status_code == 200:
			response = response.json()
			return response

	def wait_for_hot(self):
		num_hot = 0
		while num_hot == 0:
			print("[client] server not yet ready")
			time.sleep(WAIT_INTERVAL)
			status = self.get_status()
			if status is not None:
				num_hot = status["num_hot"]
		print("[client] server now ready")

	def deconstruct(self):
		os.close(self.error_fd)

def main():
	pass

if __name__ == "__main__":
	main()
