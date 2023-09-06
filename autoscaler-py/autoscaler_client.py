import requests

class Client:
	def __init__(self):
		self.auto_server_addr = '127.0.0.1:8000'

	def setup_autoscaler(self, autoscaler_args):
		URI = f'http://{self.auto_server_addr}/setup'
		request_dict = {"args" : autoscaler_args}
		response = requests.post(URI, json=request_dict)
		if response.status_code == 200:
			print("[as-client] autoscaler server set-up succeeded")
		else:
			print("[as-client] autoscaler server set-up failed")

	def destroy_autoscaler(self):
		URI = f'http://{self.auto_server_addr}/destroy'
		response = requests.post(URI)
		if response.status_code == 200:
			print("[as-client] autoscaler server shut-down succeeded")
		else:
			print("[as-client] autoscaler server shut-down failed")

	def get_ready_instances(self):
		URI = f'http://{self.auto_server_addr}/ready'
		response = requests.get(URI)
		if response.status_code == 200:
			return response.json()['ready_instances']

	def report_hot_busy(self, num_hot, num_busy):
		URI = f'http://{self.auto_server_addr}/report'
		request_dict = {"num_hot" : num_hot, "num_busy" : num_busy}
		response = requests.post(URI, json=request_dict)
		if response.status_code != 200:
			print("[as-client] failed to report num_hot/busy")